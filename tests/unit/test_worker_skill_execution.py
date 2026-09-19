"""Unit test for apps/worker/main.py executing skill tasks via SkillExecutionEngine."""

import pytest
from apps.worker.main import process_single_task
from packages.agent.dispatcher import DispatchTaskMessage, task_dispatcher
from packages.security.emergency import emergency_service
from packages.shared.database import init_db
from packages.shared.models import SkillExecutionStatus
from packages.skills.schemas import SkillExecutionResult


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()


@pytest.mark.asyncio
async def test_worker_dispatches_skill_task_successfully(monkeypatch):
    """Verify apps/worker process_single_task routes worker_type='skill' to skill_engine."""
    await emergency_service.resume(actor="tester", reason="Ensure active")

    acknowledged_tasks = []

    async def mock_acknowledge(msg_id, task_id, success=True):
        acknowledged_tasks.append((task_id, success))

    monkeypatch.setattr(task_dispatcher, "acknowledge_task", mock_acknowledge)

    # Mock skill_engine.start_execution
    from packages.skills.engine import skill_engine

    async def mock_start_execution(req):
        return SkillExecutionResult(
            execution_id="exec_test_01",
            skill_id=req.skill_id,
            version="1.0.0",
            status=SkillExecutionStatus.COMPLETED,
            output={"result": "Skill executed successfully"},
            current_step=2,
            duration_ms=50,
        )

    monkeypatch.setattr(skill_engine, "start_execution", mock_start_execution)

    msg = DispatchTaskMessage(
        task_id="task_worker_skill_01",
        project_id="proj_01",
        worker_type="skill",
        action_name="research_business",
        payload={"input_data": {"domain": "acme.com", "business_name": "Acme Corp"}},
        idempotency_key="idemp_worker_skill_01",
        timeout_seconds=30,
    )

    await process_single_task("msg_123", msg)

    assert len(acknowledged_tasks) == 1
    assert acknowledged_tasks[0] == ("task_worker_skill_01", True)
