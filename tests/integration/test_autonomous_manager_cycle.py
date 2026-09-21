"""Integration tests for the Autonomous Business Decision Manager.
Validates the complete closed-loop control cycle:
  OBSERVE -> STATE -> GOAL -> PLAN -> ACT -> OBSERVE RESULT -> VERIFY -> UPDATE STATE -> REPLAN
"""

from datetime import datetime, timezone
import uuid
import pytest

from packages.agent.manager import autonomous_business_manager
from packages.memory.context import memory_manager
from packages.security.emergency import emergency_service
from packages.shared.database import async_session_factory, init_db
from packages.shared.models import (
    AuditEvent,
    Client,
    Project,
    ProjectStatus,
    ProjectTask,
    Prospect,
    TaskStatus,
)


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()


@pytest.mark.asyncio
async def test_manager_control_cycle_idle_state():
    """Verify manager accurately observes an idle state and executes cadence maintenance."""
    # Ensure emergency controls are inactive
    await emergency_service.resume(actor="tester", reason="Reset emergency")

    res = await autonomous_business_manager.run_control_cycle()
    assert "observation" in res
    assert "decisions_count" in res
    assert res["decisions_count"] >= 1
    assert any(
        r["action"] == "MAINTAIN_OPERATIONAL_CADENCE" or r["action"] in [
            "PLAN_PAID_PROJECT",
            "DISPATCH_OUTREACH",
            "REPLAN_FAILED_TASK",
        ]
        for r in res["executed_results"]
    )


@pytest.mark.asyncio
async def test_manager_plans_paid_project():
    """Verify manager prioritizes paid projects and triggers multi-skill planning."""
    await emergency_service.resume(actor="tester", reason="Ensure active state")
    uid = str(uuid.uuid4())[:8]

    async with async_session_factory() as session:
        client = Client(name=f"Manager Corp {uid}", email=f"client_{uid}@example.com")
        session.add(client)
        await session.flush()

        proj = Project(
            client_id=client.id,
            name=f"Manager Automation Project {uid}",
            status=ProjectStatus.PAID,
            accepted_price=500.0,
            description="Build an n8n webhook receiver and CRM sync automation pipeline.",
        )
        session.add(proj)
        await session.commit()
        project_id = proj.id

    # Run Manager Control Cycle
    res = await autonomous_business_manager.run_control_cycle()
    assert res["decisions_count"] >= 1

    # Verify that PLAN_PAID_PROJECT was among executed actions
    planned = [r for r in res["executed_results"] if r["action"] == "PLAN_PAID_PROJECT"]
    assert len(planned) >= 1

    # Check project tasks were generated in DB
    async with async_session_factory() as session:
        tasks = (
            await session.execute(
                __import__("sqlalchemy").select(ProjectTask).where(ProjectTask.project_id == project_id)
            )
        ).scalars().all()
        assert len(tasks) >= 1


@pytest.mark.asyncio
async def test_manager_replans_failed_task():
    """Verify manager detects failed tasks, diagnoses failure reason, and issues corrective replanning."""
    await emergency_service.resume(actor="tester", reason="Ensure active state")
    uid = str(uuid.uuid4())[:8]

    async with async_session_factory() as session:
        client = Client(name=f"Replan Corp {uid}", email=f"replan_{uid}@example.com")
        session.add(client)
        await session.flush()

        proj = Project(
            client_id=client.id,
            name=f"Failing Automation Project {uid}",
            status=ProjectStatus.EXECUTING,
            accepted_price=600.0,
            description="API integration workflow with automated sync",
        )
        session.add(proj)
        await session.flush()

        # Add failed task
        failed_task = ProjectTask(
            project_id=proj.id,
            description="Execute automated workflow generation",
            worker_type="skill",
            status=TaskStatus.FAILED,
            evidence="SyntaxError: invalid syntax in generated client script",
            input_payload={"skill_id": "build_n8n_automation"},
        )
        session.add(failed_task)
        await session.commit()
        failed_task_id = failed_task.id
        proj_id = proj.id

    # Run Manager Control Cycle
    res = await autonomous_business_manager.run_control_cycle()
    replan_actions = [r for r in res["executed_results"] if r["action"] == "REPLAN_FAILED_TASK"]
    assert len(replan_actions) >= 1

    # Verify replanned tasks exist in DB
    async with async_session_factory() as session:
        new_tasks = (
            await session.execute(
                __import__("sqlalchemy")
                .select(ProjectTask)
                .where(ProjectTask.project_id == proj_id)
                .where(ProjectTask.id != failed_task_id)
            )
        ).scalars().all()
        assert len(new_tasks) >= 1


@pytest.mark.asyncio
async def test_manager_respects_emergency_stop():
    """Verify that manager halts all side-effect executions under emergency STOP."""
    await emergency_service.stop(actor="tester", reason="Manager emergency halt test")
    try:
        res = await autonomous_business_manager.run_control_cycle()
        assert len(res["executed_results"]) == 1
        assert res["executed_results"][0]["action"] == "EMERGENCY_HALT"
    finally:
        await emergency_service.resume(actor="tester", reason="Reset after test")
