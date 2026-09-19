import hashlib
from pathlib import Path
import uuid
import pytest
from packages.projects.delivery import (
    DeliveryBlockedError,
    project_delivery_engine,
)
from packages.projects.learning import outcome_learning_engine
from packages.projects.manager import project_planning_engine
from packages.shared.database import async_session_factory, init_db
from packages.shared.models import (
    Artifact,
    Client,
    Project,
    ProjectStatus,
    QAFinding,
    QARun,
    Requirement,
    TaskStatus,
)
from packages.tools.filesystem import resolve_sandboxed_path


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()


@pytest.mark.asyncio
async def test_project_planning_engine_generates_milestones():
    """Verify funded project decomposes into 4 concrete skill tasks."""
    unique_email = f"ops_{uuid.uuid4().hex[:6]}@techcorp.io"
    async with async_session_factory() as session:
        client = Client(name="TechCorp", email=unique_email)
        session.add(client)
        await session.flush()

        project = Project(
            client_id=client.id,
            name="CRM Sync Automation",
            description="Automate webhook to CRM lead sync",
            status=ProjectStatus.PAID,
            accepted_price=600.0,
            estimated_effort_hours=4.0,
        )
        session.add(project)
        await session.flush()

        req1 = Requirement(
            project_id=project.id,
            title="n8n Lead Sync",
            description="n8n webhook pipeline",
        )
        session.add(req1)
        await session.commit()
        proj_id = project.id

    tasks = await project_planning_engine.plan_project(proj_id)

    assert len(tasks) == 4
    assert tasks[0].input_payload["skill_id"] == "build_n8n_automation"
    assert tasks[1].input_payload["skill_id"] == "qa_project_deliverable"
    assert tasks[2].input_payload["skill_id"] == "prepare_project_delivery"
    assert tasks[3].input_payload["skill_id"] == "record_project_outcome"

    async with async_session_factory() as session:
        proj = await session.get(Project, proj_id)
        assert proj.status == ProjectStatus.EXECUTING
        assert proj.started_at is not None


@pytest.mark.asyncio
async def test_delivery_strictly_blocked_without_qa():
    """Verify Directive 109: delivery is rejected when no QA run has been performed."""
    unique_email = f"client_{uuid.uuid4().hex[:6]}@testqa.com"
    async with async_session_factory() as session:
        client = Client(name="Client QA Test", email=unique_email)
        session.add(client)
        await session.flush()

        project = Project(
            client_id=client.id,
            name="Unchecked Project",
            status=ProjectStatus.EXECUTING,
            accepted_price=400.0,
        )
        session.add(project)
        await session.commit()
        proj_id = project.id

    with pytest.raises(DeliveryBlockedError, match="No QA evaluation has been executed"):
        await project_delivery_engine.verify_and_deliver(proj_id)


@pytest.mark.asyncio
async def test_delivery_strictly_blocked_with_unresolved_critical_finding():
    """Verify delivery is blocked when QA has unresolved CRITICAL defects."""
    unique_email = f"defects_{uuid.uuid4().hex[:6]}@test.com"
    async with async_session_factory() as session:
        client = Client(name="Defect Test Client", email=unique_email)
        session.add(client)
        await session.flush()

        project = Project(
            client_id=client.id,
            name="Defective Project",
            status=ProjectStatus.EXECUTING,
            accepted_price=400.0,
        )
        session.add(project)
        await session.flush()

        # Write dummy file so artifact check can proceed
        deliverable_path = resolve_sandboxed_path(project.id, "artifacts/main.py")
        deliverable_path.parent.mkdir(parents=True, exist_ok=True)
        content = "print('hello')"
        deliverable_path.write_text(content, encoding="utf-8")
        file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        art = Artifact(
            project_id=project.id,
            name="main.py",
            file_path="artifacts/main.py",
            file_hash=file_hash,
            size_bytes=len(content),
            artifact_type="CODE",
            verification_status="UNVERIFIED",
        )
        session.add(art)
        await session.flush()

        # Add QA Run marked PASSED
        qa_run = QARun(
            project_id=project.id,
            artifact_id=art.id,
            status="PASSED",
            score=0.9,
        )
        session.add(qa_run)
        await session.flush()

        # Add unresolved CRITICAL finding
        finding = QAFinding(
            qa_run_id=qa_run.id,
            severity="CRITICAL",
            category="security_defect",
            description="Hardcoded credential detected in deliverable",
            remediation="Extract credentials to environment variables",
            resolved=False,
        )
        session.add(finding)
        await session.commit()
        proj_id = project.id

    with pytest.raises(DeliveryBlockedError, match="unresolved defects"):
        await project_delivery_engine.verify_and_deliver(proj_id)


@pytest.mark.asyncio
async def test_delivery_and_outcome_learning_complete_cycle():
    """Verify clean QA verification produces cryptographic manifest, delivers, and logs yield."""
    unique_email = f"verified_{uuid.uuid4().hex[:6]}@client.com"
    async with async_session_factory() as session:
        client = Client(name="Verified Client", email=unique_email)
        session.add(client)
        await session.flush()

        project = Project(
            client_id=client.id,
            name="Verified Integration",
            status=ProjectStatus.EXECUTING,
            accepted_price=500.0,
            estimated_effort_hours=4.0,
        )
        session.add(project)
        await session.flush()

        # Write clean deliverable
        deliverable_path = resolve_sandboxed_path(project.id, "artifacts/workflow.json")
        deliverable_path.parent.mkdir(parents=True, exist_ok=True)
        content = '{"name": "lead_sync", "nodes": []}'
        deliverable_path.write_text(content, encoding="utf-8")
        file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        art = Artifact(
            project_id=project.id,
            name="workflow.json",
            file_path="artifacts/workflow.json",
            file_hash=file_hash,
            size_bytes=len(content),
            artifact_type="N8N",
            verification_status="VERIFIED",
        )
        session.add(art)
        await session.flush()

        # Add clean QA Run
        qa_run = QARun(
            project_id=project.id,
            artifact_id=art.id,
            status="PASSED",
            score=0.95,
        )
        session.add(qa_run)
        await session.commit()
        proj_id = project.id

    # 1. Delivery succeeds
    deliv_res = await project_delivery_engine.verify_and_deliver(proj_id)
    assert deliv_res["status"] == "DELIVERED"
    assert deliv_res["artifacts_count"] == 1
    assert deliv_res["manifest_sha256"] is not None

    async with async_session_factory() as session:
        proj = await session.get(Project, proj_id)
        assert proj.status == ProjectStatus.DELIVERED
        assert proj.completed_at is not None

    # 2. Outcome learning records yield and completes project
    outcome = await outcome_learning_engine.record_project_outcome(proj_id)
    assert outcome.project_id == proj_id
    assert outcome.revenue_usd == 500.0
    assert outcome.profit_margin > 0.0

    async with async_session_factory() as session:
        proj = await session.get(Project, proj_id)
        assert proj.status == ProjectStatus.COMPLETED
