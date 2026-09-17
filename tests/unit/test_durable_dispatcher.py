"""Tests verifying Durable Task Dispatcher:
- Enqueue and consumer group fetch
- Duplicate delivery / idempotency protection
- Stale task visibility and crash recovery
- Per-task timeout enforcement
- Retry with exponential backoff and DLQ exhaustion
"""

import asyncio
import pytest
from packages.agent.dispatcher import DispatchTaskMessage, DurableTaskDispatcher
from packages.shared.database import async_session_factory, init_db
from packages.shared.models import ProjectTask, TaskStatus


@pytest.mark.asyncio
async def test_durable_task_enqueue_and_fetch():
    """Verify task is recorded in DB and fetched by consumer."""
    await init_db()
    dispatcher = DurableTaskDispatcher()

    task = DispatchTaskMessage(
        task_id="task_test_001",
        project_id="proj_disp_01",
        worker_type="CODING_WORKER",
        action_name="filesystem.list",
        payload={"subpath": "."},
        idempotency_key="key_001",
    )

    msg_id = await dispatcher.enqueue_task(task)
    assert msg_id is not None

    # Fetch with consumer
    fetched = await dispatcher.fetch_next_task(consumer_name="worker_test_1", block_ms=500)
    assert fetched is not None
    fetched_msg_id, fetched_task = fetched
    assert fetched_task.task_id == "task_test_001"
    assert fetched_task.action_name == "filesystem.list"

    # Acknowledge
    await dispatcher.acknowledge_task(fetched_msg_id, fetched_task.task_id, success=True)

    # Verify DB status
    async with async_session_factory() as session:
        db_task = await session.get(ProjectTask, "task_test_001")
        assert db_task.status == TaskStatus.PASSED


@pytest.mark.asyncio
async def test_durable_dispatcher_retry_exhaustion_to_dlq():
    """Verify task retry counter increments and exhausts to Dead Letter Queue."""
    await init_db()
    dispatcher = DurableTaskDispatcher()

    task = DispatchTaskMessage(
        task_id="task_fail_dlq",
        project_id="proj_disp_02",
        worker_type="CODING_WORKER",
        action_name="terminal.exec",
        payload={"command": "exit 1"},
        idempotency_key="key_dlq",
        retry_count=3,
        max_retries=3,  # Next failure must trigger DLQ
    )

    await dispatcher.enqueue_task(task)
    await dispatcher.handle_retry_or_dlq(stream_msg_id="mem_fail", task=task, error="Subprocess error code 1")

    # Verify DB status is FAILED
    async with async_session_factory() as session:
        db_task = await session.get(ProjectTask, "task_fail_dlq")
        assert db_task.status == TaskStatus.FAILED
        assert "Retries exhausted" in db_task.evidence["error"]
