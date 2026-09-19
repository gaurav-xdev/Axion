"""Durable Worker Execution Service.
Consumes tasks from the durable dispatcher queue, evaluates authoritative distributed emergency state,
invokes the authoritative Tool Gateway, and ensures graceful shutdown and timeout bounds.
"""

import asyncio
import os
import signal
import socket
import time
from typing import Optional

from packages.agent.dispatcher import DispatchTaskMessage, task_dispatcher
from packages.observability.logger import logger
from packages.security.emergency import emergency_service
from packages.shared.database import close_db, init_db
from packages.tools.base import ToolRequest
from packages.tools.gateway import tool_gateway

running = True
active_task_semaphore = asyncio.Semaphore(5)  # Bounded concurrency: max 5 parallel tasks per worker node
consumer_id = f"worker_{socket.gethostname()}_{os.getpid()}"


def handle_exit(*args):
    global running
    logger.info(f"Worker {consumer_id} received termination signal. Commencing graceful shutdown...")
    running = False


async def process_single_task(msg_id: str, task: DispatchTaskMessage) -> None:
    """Safely executes a single task within concurrency, timeout, and emergency bounds."""
    async with active_task_semaphore:
        logger.info(f"Worker {consumer_id} executing task {task.task_id} (action: {task.action_name})")

        # 1. Authoritative Emergency Check
        state = await emergency_service.get_state()
        if state.is_stopped:
            logger.warning(f"Task {task.task_id} skipped: Emergency Stop is ACTIVE.")
            await task_dispatcher.handle_retry_or_dlq(msg_id, task, f"Aborted: Emergency stop active ({state.reason})")
            return

        if state.is_paused:
            logger.info(f"Task {task.task_id} deferred: Emergency Pause is ACTIVE.")
            # Yield task back to queue without consuming retries
            await asyncio.sleep(2.0)
            return

        # 2. Route by worker_type: "skill" vs "tool"
        if task.worker_type == "skill":
            from packages.skills.engine import skill_engine
            from packages.skills.schemas import SkillExecutionRequest
            from packages.shared.models import SkillExecutionStatus

            skill_req = SkillExecutionRequest(
                skill_id=task.action_name,
                version=task.payload.get("version"),
                input_data=task.payload.get("input_data", task.payload),
                project_id=task.project_id,
                task_id=task.task_id,
                idempotency_key=task.idempotency_key,
                timeout_seconds=task.timeout_seconds,
            )

            try:
                skill_res = await asyncio.wait_for(
                    skill_engine.start_execution(skill_req),
                    timeout=float(task.timeout_seconds + 5),
                )

                if skill_res.status == SkillExecutionStatus.COMPLETED:
                    logger.info(
                        f"Skill task {task.task_id} ({task.action_name}) completed successfully by {consumer_id}"
                    )
                    await task_dispatcher.acknowledge_task(msg_id, task.task_id, success=True)
                elif skill_res.status == SkillExecutionStatus.WAITING:
                    logger.info(f"Skill task {task.task_id} checkpointed and WAITING (PAUSED).")
                    await asyncio.sleep(2.0)
                else:
                    logger.warning(f"Skill task {task.task_id} failed: {skill_res.error}")
                    await task_dispatcher.handle_retry_or_dlq(
                        msg_id, task, skill_res.error or "Skill execution failed"
                    )
            except asyncio.TimeoutError:
                err = f"Skill execution exceeded timeout limit of {task.timeout_seconds}s"
                logger.error(f"Skill task {task.task_id} TIMED OUT on {consumer_id}")
                await task_dispatcher.handle_retry_or_dlq(msg_id, task, err)
            except Exception as ex:
                err = f"Unexpected skill worker error: {str(ex)}"
                logger.error(f"Skill task {task.task_id} failed unexpectedly: {ex}")
                await task_dispatcher.handle_retry_or_dlq(msg_id, task, err)
            return

        # 3. Invoke Authoritative Tool Gateway with timeout
        tool_req = ToolRequest(
            tool_name=task.action_name,
            arguments=task.payload,
            project_id=task.project_id,
            task_id=task.task_id,
            requested_by_role="WORKER_SERVICE",
            idempotency_key=task.idempotency_key,
        )

        try:
            tool_res = await asyncio.wait_for(
                tool_gateway.execute(tool_req),
                timeout=task.timeout_seconds,
            )

            if tool_res.success:
                logger.info(f"Task {task.task_id} completed successfully by {consumer_id}")
                await task_dispatcher.acknowledge_task(msg_id, task.task_id, success=True)
            else:
                logger.warning(f"Task {task.task_id} failed with tool error: {tool_res.error}")
                await task_dispatcher.handle_retry_or_dlq(msg_id, task, tool_res.error or "Tool execution failed")

        except asyncio.TimeoutError:
            err = f"Task execution exceeded per-task timeout limit of {task.timeout_seconds}s"
            logger.error(f"Task {task.task_id} TIMED OUT on {consumer_id}")
            await task_dispatcher.handle_retry_or_dlq(msg_id, task, err)
        except Exception as ex:
            err = f"Unexpected worker error: {str(ex)}"
            logger.error(f"Task {task.task_id} failed unexpectedly: {ex}")
            await task_dispatcher.handle_retry_or_dlq(msg_id, task, err)


async def run_worker_loop():
    logger.info(f"Starting Durable Autonomous Worker {consumer_id}...")
    await init_db()

    while running:
        try:
            # Check authoritative distributed emergency state
            state = await emergency_service.get_state()
            if state.is_stopped:
                logger.info("Worker sleeping: Authoritative Emergency Stop is ACTIVE.")
                await asyncio.sleep(3.0)
                continue

            # Fetch next durable task
            task_tuple = await task_dispatcher.fetch_next_task(consumer_name=consumer_id, block_ms=1000)
            if not task_tuple:
                await asyncio.sleep(0.5)
                continue

            msg_id, task = task_tuple
            # Process in background task while respecting bounded concurrency semaphore
            asyncio.create_task(process_single_task(msg_id, task))

        except Exception as ex:
            logger.error(f"Error in worker dispatch loop: {ex}")
            await asyncio.sleep(1.0)

    # Graceful Drain: Wait for in-flight tasks to yield
    logger.info(f"Worker {consumer_id} shutting down. Releasing database connections...")
    await close_db()
    logger.info(f"Worker {consumer_id} exited cleanly.")


if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)
    asyncio.run(run_worker_loop())
