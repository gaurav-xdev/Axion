"""Unit tests for Multi-Skill Planning and Dynamic Replanning."""

import pytest
import uuid
from packages.projects.manager import project_planning_engine
from packages.shared.database import async_session_factory
from packages.shared.models import (
    Client,
    Project,
    ProjectStatus,
    ProjectTask,
    Requirement,
    TaskStatus,
)


@pytest.mark.asyncio
async def test_multi_skill_composition_planning():
    uid = str(uuid.uuid4())[:8]
    async with async_session_factory() as session:
        client = Client(name=f"MultiSkill Client {uid}", email=f"tech_{uid}@corp.com")
        session.add(client)
        await session.flush()

        project = Project(
            client_id=client.id,
            name=f"Full Webhook and API Sync {uid}",
            description="Build a FastAPI webhook receiver with HMAC and an async HTTP API client to push leads to CRM",
            status=ProjectStatus.PAID,
            accepted_price=1500.0,
            estimated_effort_hours=12.0,
        )
        session.add(project)
        await session.flush()

        req1 = Requirement(
            project_id=project.id,
            title="FastAPI Webhook Receiver",
            description="FastAPI webhook receiver with HMAC signature verification",
            certainty="CLIENT_STATED",
        )
        req2 = Requirement(
            project_id=project.id,
            title="Async REST API Client",
            description="Async Python httpx client with connection pooling and error retries",
            certainty="CLIENT_STATED",
        )
        session.add(req1)
        session.add(req2)
        await session.commit()
        project_id = project.id

    tasks = await project_planning_engine.plan_project(project_id)
    assert len(tasks) >= 5  # 2 skill tasks + QA + Packaging + Outcome

    skill_names = [t.input_payload.get("skill_id") for t in tasks if t.input_payload]
    assert "build_webhook_integration" in skill_names
    assert "build_api_integration" in skill_names
    assert "qa_project_deliverable" in skill_names
    assert "prepare_project_delivery" in skill_names
    assert "record_project_outcome" in skill_names


@pytest.mark.asyncio
async def test_dynamic_project_replanning():
    uid = str(uuid.uuid4())[:8]
    async with async_session_factory() as session:
        client = Client(name=f"Replan Client {uid}", email=f"ops_{uid}@corp.com")
        session.add(client)
        await session.flush()

        project = Project(
            client_id=client.id,
            name=f"Webhook Project {uid}",
            description="Webhook integration",
            status=ProjectStatus.PAID,
            accepted_price=600.0,
            estimated_effort_hours=5.0,
        )
        session.add(project)
        await session.commit()
        project_id = project.id

    initial_tasks = await project_planning_engine.plan_project(project_id)
    eng_task = [t for t in initial_tasks if t.input_payload.get("skill_id") == "build_webhook_integration"][0]

    # Trigger replanning due to simulated syntax/compilation failure
    remediation_tasks = await project_planning_engine.replan_project(
        project_id=project_id,
        failed_task_id=eng_task.id,
        failure_reason="SyntaxError: invalid syntax at line 14: unclosed string literal",
    )

    remedy = [t for t in remediation_tasks if t.input_payload and t.input_payload.get("remediation_mode") == "SYNTAX_CORRECTION"]
    assert len(remedy) == 1
    assert remedy[0].status == TaskStatus.PENDING
    assert "Remediation: Fix code syntax" in remedy[0].description
