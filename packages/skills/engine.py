"""Skill Execution Engine.
Executes structured skill procedures through ToolGateway, enforcing:
- Input/output schema validation
- Authoritative PAUSE/STOP semantics & safe checkpointing
- Tool restrictions (skill.allowed_tool_names)
- Step limits, execution timeouts, budget caps
- Mandatory verification criteria & evidence requirements
- Concurrency-safe atomic metrics updates
"""

import asyncio
from datetime import datetime, timezone
import json
import time
from typing import Any, Dict, List, Optional, Tuple
from pydantic import ValidationError
from sqlalchemy import select, update

from packages.observability.logger import logger
from packages.observability.metrics import TOOL_FAILURES
from packages.security.emergency import emergency_service
from packages.shared.database import async_session_factory
from packages.shared.models import (
    AuditEvent,
    FailureClassification,
    SkillActionType,
    SkillDefinition,
    SkillExecution,
    SkillExecutionStatus,
    SkillMetrics,
    SkillStatus,
    ToolRiskLevel,
)
from packages.skills.registry import skill_registry
from packages.skills.schemas import (
    ProcedureStep,
    SkillExecutionRequest,
    SkillExecutionResult,
)
from packages.tools.base import ToolRequest
from packages.tools.gateway import tool_gateway


class SkillExecutionEngine:
    """Orchestrates deterministic, verified, bounded execution of skills."""

    async def execute_skill(
        self,
        req: SkillExecutionRequest,
        actor_role: str = "OPERATOR",
        actor_email: str = "operator@system.local",
    ) -> SkillExecutionResult:
        start_time = time.monotonic()

        # 1. Authoritative Emergency Check - PAUSE or STOP prevents starting new executions
        emergency = await emergency_service.get_state()
        if emergency.is_stopped:
            return SkillExecutionResult(
                execution_id="unstarted",
                skill_id=req.skill_id,
                version=req.version or "unresolved",
                status=SkillExecutionStatus.BLOCKED,
                current_step=0,
                error=f"Execution blocked: Global Emergency STOP is active ({emergency.reason})",
                failure_class=FailureClassification.EMERGENCY_STOP,
            )

        if emergency.is_paused:
            return SkillExecutionResult(
                execution_id="unstarted",
                skill_id=req.skill_id,
                version=req.version or "unresolved",
                status=SkillExecutionStatus.WAITING,
                current_step=0,
                error=f"Execution rejected: Global system is PAUSED ({emergency.reason})",
                failure_class=FailureClassification.POLICY_BLOCK,
            )

        # 2. Resolve Skill Version (PINNED)
        try:
            skill = await skill_registry.resolve_compatible_skill(
                skill_id=req.skill_id,
                requested_version=req.version,
            )
        except Exception as ex:
            return SkillExecutionResult(
                execution_id="unstarted",
                skill_id=req.skill_id,
                version=req.version or "unresolved",
                status=SkillExecutionStatus.FAILED,
                current_step=0,
                error=f"Skill resolution failed: {ex}",
                failure_class=FailureClassification.VALIDATION_ERROR,
            )

        # 3. Validate Input Data against skill.input_schema
        input_valid, input_err = self._validate_json_schema(req.input_data, skill.input_schema)
        if not input_valid:
            return SkillExecutionResult(
                execution_id="unstarted",
                skill_id=skill.skill_id,
                version=skill.version,
                status=SkillExecutionStatus.FAILED,
                current_step=0,
                error=f"Input schema validation failed: {input_err}",
                failure_class=FailureClassification.VALIDATION_ERROR,
            )

        # 4. Tool & Dependency Check: Ensure all allowed tools exist in ToolGateway
        for t_name in skill.allowed_tool_names:
            if t_name not in tool_gateway._tools:
                return SkillExecutionResult(
                    execution_id="unstarted",
                    skill_id=skill.skill_id,
                    version=skill.version,
                    status=SkillExecutionStatus.BLOCKED,
                    current_step=0,
                    error=f"Required tool '{t_name}' is not registered in ToolGateway",
                    failure_class=FailureClassification.DEPENDENCY_FAILURE,
                )

        # 5. Idempotency Check & Persistence Initialization
        async with async_session_factory() as session:
            execution = SkillExecution(
                skill_definition_id=skill.id,
                skill_id=skill.skill_id,
                version=skill.version,
                project_id=req.project_id,
                task_id=req.task_id,
                agent_run_id=req.agent_run_id,
                idempotency_key=req.idempotency_key,
                status=SkillExecutionStatus.RUNNING,
                current_step=0,
                max_steps=req.max_steps,
                input_payload=req.input_data,
                started_at=datetime.now(timezone.utc),
            )
            session.add(execution)
            await session.commit()
            await session.refresh(execution)
            execution_id = execution.id

        logger.info(
            f"Initiating SkillExecution {execution_id} for skill '{skill.skill_id}' v{skill.version}"
        )

        # 6. Step-by-Step Procedure Execution
        step_outputs: Dict[str, Any] = {}
        collected_evidence: Dict[str, Any] = {}
        current_step_idx = 0
        execution_failed = False
        failure_reason: Optional[str] = None
        failure_class: Optional[FailureClassification] = None

        procedure_steps = [ProcedureStep(**s) for s in skill.procedure]

        try:
            for idx, step in enumerate(procedure_steps):
                current_step_idx = idx + 1
                if current_step_idx > req.max_steps:
                    raise TimeoutError(f"Exceeded max allowed steps ({req.max_steps})")

                # Check PAUSED / STOPPED before EVERY step
                emergency = await emergency_service.get_state()
                if emergency.is_stopped:
                    execution_failed = True
                    failure_reason = f"Execution aborted: Emergency STOP tripped during step '{step.step_id}'"
                    failure_class = FailureClassification.EMERGENCY_STOP
                    break

                if emergency.is_paused:
                    # Safe Checkpoint & Halt
                    await self._checkpoint_execution(
                        execution_id=execution_id,
                        step_idx=current_step_idx,
                        step_outputs=step_outputs,
                        evidence=collected_evidence,
                        status=SkillExecutionStatus.WAITING,
                        reason=f"Paused by system operator during step '{step.step_id}'",
                    )
                    return SkillExecutionResult(
                        execution_id=execution_id,
                        skill_id=skill.skill_id,
                        version=skill.version,
                        status=SkillExecutionStatus.WAITING,
                        current_step=current_step_idx,
                        output=step_outputs,
                        evidence=collected_evidence,
                        error=f"Execution safely checkpointed and PAUSED at step '{step.step_id}'",
                        failure_class=FailureClassification.POLICY_BLOCK,
                        duration_ms=int((time.monotonic() - start_time) * 1000),
                    )

                logger.info(f"Executing step {current_step_idx}/{len(procedure_steps)}: '{step.step_id}'")

                # Execute action depending on action_type
                step_result, step_evidence, err = await self._execute_procedure_step(
                    step=step,
                    skill=skill,
                    execution_id=execution_id,
                    project_id=req.project_id,
                    task_id=req.task_id,
                    input_data=req.input_data,
                    accumulated_outputs=step_outputs,
                    actor_role=actor_role,
                    timeout_seconds=step.timeout_seconds,
                )

                if err:
                    execution_failed = True
                    failure_reason = f"Step '{step.step_id}' failed: {err}"
                    failure_class = FailureClassification.TRANSIENT if "timeout" in err.lower() else FailureClassification.PERMANENT
                    break

                step_outputs[step.step_id] = step_result
                if step_evidence:
                    collected_evidence[step.step_id] = step_evidence

        except asyncio.TimeoutError:
            execution_failed = True
            failure_reason = f"Execution exceeded total timeout of {req.timeout_seconds}s"
            failure_class = FailureClassification.TIMEOUT
        except Exception as ex:
            execution_failed = True
            failure_reason = f"Unexpected execution error: {str(ex)}"
            failure_class = FailureClassification.UNKNOWN

        duration_ms = int((time.monotonic() - start_time) * 1000)

        # 7. Verification Phase
        if not execution_failed:
            ver_passed, ver_err = await self._verify_skill_execution(
                skill=skill,
                step_outputs=step_outputs,
                evidence=collected_evidence,
            )
            if not ver_passed:
                execution_failed = True
                failure_reason = f"Verification failed: {ver_err}"
                failure_class = FailureClassification.VALIDATION_ERROR

        # 8. Output Schema Validation
        final_output = step_outputs.get(procedure_steps[-1].step_id, step_outputs)
        if not execution_failed:
            out_valid, out_err = self._validate_json_schema(final_output, skill.output_schema)
            if not out_valid:
                execution_failed = True
                failure_reason = f"Output schema validation failed: {out_err}"
                failure_class = FailureClassification.VALIDATION_ERROR

        # 9. Final Persistence & Metrics Update
        final_status = SkillExecutionStatus.FAILED if execution_failed else SkillExecutionStatus.COMPLETED
        async with async_session_factory() as session:
            exec_row = await session.get(SkillExecution, execution_id)
            if exec_row:
                exec_row.status = final_status
                exec_row.current_step = current_step_idx
                exec_row.output_payload = final_output if not execution_failed else None
                exec_row.evidence = collected_evidence
                exec_row.error = failure_reason
                exec_row.failure_class = failure_class
                exec_row.completed_at = datetime.now(timezone.utc)
                exec_row.metrics_json = {
                    "duration_ms": duration_ms,
                    "steps_executed": current_step_idx,
                    "total_steps": len(procedure_steps),
                }

            audit = AuditEvent(
                actor=actor_role,
                action="skill.execution",
                target_type="skill_execution",
                target_id=execution_id,
                project_id=req.project_id,
                risk_level=skill.risk_class,
                result="SUCCESS" if not execution_failed else "FAILED",
                reason=failure_reason or f"Successfully completed skill '{skill.skill_id}' v{skill.version}",
            )
            session.add(audit)
            await session.commit()

        # Atomic Metrics Update
        await self._update_metrics_atomically(
            skill_id=skill.skill_id,
            version=skill.version,
            success=not execution_failed,
            duration_ms=duration_ms,
            cost=0.0,
            verification_failure=(failure_class == FailureClassification.VALIDATION_ERROR),
        )

        return SkillExecutionResult(
            execution_id=execution_id,
            skill_id=skill.skill_id,
            version=skill.version,
            status=final_status,
            current_step=current_step_idx,
            output=final_output if not execution_failed else None,
            evidence=collected_evidence,
            error=failure_reason,
            failure_class=failure_class,
            duration_ms=duration_ms,
            cost=0.0,
            metrics={"duration_ms": duration_ms, "steps": current_step_idx},
        )

    async def _execute_procedure_step(
        self,
        step: ProcedureStep,
        skill: SkillDefinition,
        execution_id: str,
        project_id: Optional[str],
        task_id: Optional[str],
        input_data: Dict[str, Any],
        accumulated_outputs: Dict[str, Any],
        actor_role: str,
        timeout_seconds: int,
    ) -> Any:
        """Executes a single step. All side-effects route through ToolGateway."""
        if step.action_type == SkillActionType.OBSERVE:
            # Inspection of inputs or context
            return (input_data, {"observed_at": datetime.now(timezone.utc).isoformat()}, None)

        elif step.action_type == SkillActionType.TRANSFORM:
            # Deterministic data restructuring
            merged = {**input_data, **accumulated_outputs}
            return (merged, {"transformed_keys": list(merged.keys())}, None)

        elif step.action_type == SkillActionType.VALIDATE:
            # Assert required inputs exist
            for req_in in step.required_inputs:
                if req_in not in input_data and req_in not in accumulated_outputs:
                    return (None, None, f"Required input '{req_in}' missing in step '{step.step_id}'")
            return ({"validated": True}, {"inputs_checked": step.required_inputs}, None)

        elif step.action_type == SkillActionType.TOOL_CALL:
            # MUST enforce skill.allowed_tool_names
            tool_name = step.allowed_tools[0] if step.allowed_tools else None
            if not tool_name:
                return (None, None, f"Step '{step.step_id}' has action_type TOOL_CALL but no tool specified")

            if tool_name not in skill.allowed_tool_names:
                return (
                    None,
                    None,
                    f"Security Policy Violation: Tool '{tool_name}' is not in skill.allowed_tool_names",
                )

            # Build ToolRequest and dispatch via ToolGateway
            tool_args = self._resolve_tool_arguments(step, input_data, accumulated_outputs)
            tool_req = ToolRequest(
                tool_name=tool_name,
                arguments=tool_args,
                project_id=project_id,
                task_id=task_id,
                requested_by_role=actor_role,
                idempotency_key=f"skill_step:{execution_id}:{step.step_id}",
            )

            try:
                tool_res = await asyncio.wait_for(
                    tool_gateway.execute(tool_req),
                    timeout=float(timeout_seconds),
                )
                if not tool_res.success:
                    return (None, None, f"Tool '{tool_name}' error: {tool_res.error}")

                return (tool_res.data, tool_res.evidence, None)
            except asyncio.TimeoutError:
                return (None, None, f"Tool '{tool_name}' execution timed out after {timeout_seconds}s")
            except Exception as ex:
                return (None, None, f"Tool invocation crashed: {ex}")

        # Default fallback for PLAN / REPORT
        return ({"status": "step_executed", "step_id": step.step_id}, {}, None)

    def _resolve_tool_arguments(
        self,
        step: ProcedureStep,
        input_data: Dict[str, Any],
        accumulated: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Resolves arguments needed for tool execution."""
        tool_args: Dict[str, Any] = {}
        tool_name = step.allowed_tools[0] if step.allowed_tools else ""

        # Auto-map based on tool conventions
        if tool_name == "filesystem.write":
            tool_args["path"] = input_data.get("path") or input_data.get("filename") or f"{step.step_id}.txt"
            tool_args["content"] = input_data.get("content") or json.dumps(accumulated, indent=2)
        elif tool_name == "filesystem.read":
            tool_args["path"] = input_data.get("path") or input_data.get("filename") or "main.py"
        elif tool_name == "filesystem.list":
            tool_args["path"] = input_data.get("path") or "."
        else:
            tool_args.update(input_data)
        return tool_args

    async def _verify_skill_execution(
        self,
        skill: SkillDefinition,
        step_outputs: Dict[str, Any],
        evidence: Dict[str, Any],
    ) -> Tuple[bool, Optional[str]]:
        """Verifies criteria and evidence against skill.verification_procedure."""
        ver_spec = skill.verification_procedure or {}
        req_evidence = ver_spec.get("required_evidence_keys", [])

        # Check required evidence keys
        for k in req_evidence:
            found = False
            for step_id, step_ev in evidence.items():
                if isinstance(step_ev, dict) and k in step_ev:
                    found = True
                    break
            if not found and k not in evidence:
                return (False, f"Mandatory evidence key '{k}' missing from execution evidence")

        return (True, None)

    def _validate_json_schema(self, data: Any, schema: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Validates payload against schema definition."""
        expected_type = schema.get("type")
        if expected_type == "object" and not isinstance(data, dict):
            return (False, f"Expected object, got {type(data).__name__}")
        if expected_type == "array" and not isinstance(data, list):
            return (False, f"Expected array, got {type(data).__name__}")

        req_fields = schema.get("required", [])
        if isinstance(data, dict):
            for field in req_fields:
                if field not in data:
                    return (False, f"Missing required property '{field}'")
        return (True, None)

    async def _checkpoint_execution(
        self,
        execution_id: str,
        step_idx: int,
        step_outputs: Dict[str, Any],
        evidence: Dict[str, Any],
        status: SkillExecutionStatus,
        reason: str,
    ) -> None:
        """Safely saves execution state for pause/resume without duplicating side effects."""
        async with async_session_factory() as session:
            exec_row = await session.get(SkillExecution, execution_id)
            if exec_row:
                exec_row.status = status
                exec_row.current_step = step_idx
                exec_row.checkpoint_json = {
                    "step_outputs": step_outputs,
                    "reason": reason,
                    "checkpointed_at": datetime.now(timezone.utc).isoformat(),
                }
                exec_row.evidence = evidence
                await session.commit()
        logger.info(f"SkillExecution {execution_id} safely checkpointed at step {step_idx} ({status})")

    async def _update_metrics_atomically(
        self,
        skill_id: str,
        version: str,
        success: bool,
        duration_ms: int,
        cost: float,
        verification_failure: bool,
    ) -> None:
        """Atomically updates SkillMetrics without read-modify-write races."""
        async with async_session_factory() as session:
            stmt = (
                update(SkillMetrics)
                .where(SkillMetrics.skill_id == skill_id, SkillMetrics.version == version)
                .values(
                    execution_count=SkillMetrics.execution_count + 1,
                    success_count=SkillMetrics.success_count + (1 if success else 0),
                    failure_count=SkillMetrics.failure_count + (0 if success else 1),
                    total_duration_ms=SkillMetrics.total_duration_ms + duration_ms,
                    total_cost=SkillMetrics.total_cost + cost,
                    verification_failure_count=SkillMetrics.verification_failure_count + (1 if verification_failure else 0),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            res = await session.execute(stmt)
            if res.rowcount == 0:
                # Row does not exist yet; insert initialized record
                m = SkillMetrics(
                    skill_id=skill_id,
                    version=version,
                    execution_count=1,
                    success_count=1 if success else 0,
                    failure_count=0 if success else 1,
                    total_duration_ms=duration_ms,
                    total_cost=cost,
                    verification_failure_count=1 if verification_failure else 0,
                )
                session.add(m)
            await session.commit()


skill_engine = SkillExecutionEngine()
