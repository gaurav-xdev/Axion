"""Asynchronous Agent Runtime.
Executes plan steps, persists checkpoints, enforces budget caps, and provides crash recovery.
"""

from datetime import datetime, timezone
import time
from typing import Any, Dict, List, Optional
from sqlalchemy import select

from packages.llm.router import TaskContext, llm_router
from packages.observability.logger import logger
from packages.observability.metrics import AGENT_RUNS_COMPLETED, AGENT_RUNS_FAILED, AGENT_RUNS_TOTAL
from packages.shared.config import settings
from packages.shared.database import async_session_factory
from packages.security.emergency import emergency_service
from packages.shared.models import AgentRun, AgentRunStatus, AgentStep, ProjectTask, TaskStatus
from packages.tools.base import ToolRequest
from packages.tools.gateway import tool_gateway


class EmergencyControlProxy:
    """Backwards-compatible proxy routing to authoritative distributed emergency service."""
    @property
    def is_paused(self) -> bool:
        if emergency_service._cached_state:
            return emergency_service._cached_state.is_paused
        return False

    @is_paused.setter
    def is_paused(self, val: bool) -> None:
        if not emergency_service._cached_state:
            emergency_service._cached_state = EmergencyState()
        emergency_service._cached_state.is_paused = val

    @property
    def is_stopped(self) -> bool:
        if emergency_service._cached_state:
            return emergency_service._cached_state.is_stopped
        return False

    @is_stopped.setter
    def is_stopped(self, val: bool) -> None:
        if not emergency_service._cached_state:
            emergency_service._cached_state = EmergencyState()
        emergency_service._cached_state.is_stopped = val

    @property
    def stop_outreach(self) -> bool:
        if emergency_service._cached_state:
            return emergency_service._cached_state.stop_outreach
        return False

    @stop_outreach.setter
    def stop_outreach(self, val: bool) -> None:
        if not emergency_service._cached_state:
            emergency_service._cached_state = EmergencyState()
        emergency_service._cached_state.stop_outreach = val


emergency_controls = EmergencyControlProxy()


class AgentRuntime:
    def __init__(self):
        self.max_steps = settings.AGENT_MAX_STEPS
        self.max_cost = settings.AGENT_MAX_COST

    async def create_run(self, goal: str, project_id: Optional[str] = None, client_id: Optional[str] = None) -> AgentRun:
        async with async_session_factory() as session:
            run = AgentRun(
                goal=goal,
                project_id=project_id,
                client_id=client_id,
                status=AgentRunStatus.CREATED,
                started_at=datetime.now(timezone.utc),
            )
            session.add(run)
            await session.commit()
            await session.refresh(run)
            AGENT_RUNS_TOTAL.labels(status="created").inc()
            return run

    async def resume_or_recover_run(self, run_id: str) -> Optional[AgentRun]:
        """Restores run checkpoint following process restart or worker crash."""
        async with async_session_factory() as session:
            run = await session.get(AgentRun, run_id)
            if not run:
                return None

            if run.status in (AgentRunStatus.RUNNING, AgentRunStatus.CREATED):
                logger.info(f"Recovering interrupted run {run.id} at step {run.step_count}")
                run.status = AgentRunStatus.RUNNING
                await session.commit()
                await session.refresh(run)
            return run

    async def execute_step(
        self,
        run_id: str,
        thought: str,
        action_type: str,
        action_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Executes a discrete step within an agent run, with tool gateway invocation and checkpointing."""
        # Authoritative Distributed Emergency Check
        state = await emergency_service.get_state()
        if state.is_stopped:
            logger.warning("Execution aborted: Authoritative distributed Emergency Stop is ACTIVE.")
            return {"status": "ABORTED", "reason": f"Emergency stop active: {state.reason}"}

        if state.is_paused:
            logger.info("Execution paused: Distributed Emergency Pause is ACTIVE.")
            return {"status": "PAUSED", "reason": f"Emergency pause active: {state.reason}"}

        async with async_session_factory() as session:
            run = await session.get(AgentRun, run_id)
            if not run:
                raise ValueError(f"Run {run_id} not found")

            # Guardrails check
            if run.step_count >= self.max_steps:
                run.status = AgentRunStatus.BLOCKED
                run.last_error = f"Step limit exceeded ({self.max_steps})"
                await session.commit()
                return {"status": "LIMIT_EXCEEDED", "reason": run.last_error}

            if run.cost >= self.max_cost:
                run.status = AgentRunStatus.BLOCKED
                run.last_error = f"Budget limit exceeded (${self.max_cost})"
                await session.commit()
                return {"status": "BUDGET_EXCEEDED", "reason": run.last_error}

            # Increment step
            run.step_count += 1
            step_num = run.step_count

            # Execute tool if action is a tool call
            result_payload = {}
            verified = False
            if action_type.startswith("tool:"):
                tool_name = action_type.split("tool:", 1)[1]
                tool_req = ToolRequest(
                    tool_name=tool_name,
                    arguments=action_payload,
                    project_id=run.project_id,
                    client_id=run.client_id,
                    run_id=run.id,
                )
                tool_res = await tool_gateway.execute(tool_req)
                result_payload = {
                    "success": tool_res.success,
                    "data": tool_res.data,
                    "error": tool_res.error,
                }
                verified = tool_res.success
                run.tool_count += 1
            else:
                result_payload = {"action": action_type, "status": "acknowledged"}
                verified = True

            # Checkpoint step
            step_record = AgentStep(
                run_id=run.id,
                step_number=step_num,
                thought=thought,
                action_type=action_type,
                action_payload=action_payload,
                result_payload=result_payload,
                verified=verified,
            )
            session.add(step_record)

            # Update run checkpoint
            run.checkpoint_json = {
                "last_step": step_num,
                "last_action": action_type,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            run.updated_at = datetime.now(timezone.utc)
            await session.commit()

            return result_payload

    async def mark_run_completed(self, run_id: str) -> None:
        async with async_session_factory() as session:
            run = await session.get(AgentRun, run_id)
            if run:
                run.status = AgentRunStatus.COMPLETED
                run.completed_at = datetime.now(timezone.utc)
                await session.commit()
                AGENT_RUNS_COMPLETED.inc()

    async def mark_run_failed(self, run_id: str, error: str) -> None:
        async with async_session_factory() as session:
            run = await session.get(AgentRun, run_id)
            if run:
                run.status = AgentRunStatus.FAILED
                run.last_error = error
                run.completed_at = datetime.now(timezone.utc)
                await session.commit()
                AGENT_RUNS_FAILED.inc()


# Global singleton
agent_runtime = AgentRuntime()
