"""Unit tests for the Autonomous Business Scheduler Service.
Verifies revenue calculation, emergency control compliance, and durable task dispatching.
"""

import pytest
from apps.scheduler.main import TARGET_REVENUE_USD_PER_WEEK, AutonomousSchedulerService
from packages.security.emergency import emergency_service
from packages.shared.database import async_session_factory, init_db
from packages.shared.models import Client, Payment, PaymentStatus, Project, ProjectStatus


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()


@pytest.mark.asyncio
async def test_scheduler_weekly_revenue_calculation():
    """Verify scheduler computes 7-day trailing revenue and pacing percentage accurately."""
    scheduler = AutonomousSchedulerService()
    assert scheduler.target_weekly_revenue == TARGET_REVENUE_USD_PER_WEEK

    import uuid
    uid = str(uuid.uuid4())[:8]

    from datetime import datetime, timedelta, timezone
    from packages.shared.models import Checkout, Quote

    async with async_session_factory() as session:
        client = Client(name="Revenue Corp", email=f"rev_{uid}@example.com")
        session.add(client)
        await session.flush()

        proj = Project(
            client_id=client.id,
            name="Revenue Test Project",
            status=ProjectStatus.PAID,
            accepted_price=300.0,
        )
        session.add(proj)
        await session.flush()

        quote = Quote(
            project_id=proj.id,
            client_id=client.id,
            amount=300.0,
            scope_summary="Revenue test deliverable",
            expires_at=datetime.now(timezone.utc) + timedelta(days=3),
            status="ACCEPTED",
        )
        session.add(quote)
        await session.flush()

        checkout = Checkout(
            project_id=proj.id,
            client_id=client.id,
            quote_id=quote.id,
            dodo_checkout_id=f"chk_{uid}",
            checkout_url=f"https://test.dodopayments.com/checkout/chk_{uid}",
            amount=300.0,
            status=PaymentStatus.PAID,
            expires_at=datetime.now(timezone.utc) + timedelta(days=3),
        )
        session.add(checkout)
        await session.flush()

        pay = Payment(
            checkout_id=checkout.id,
            project_id=proj.id,
            client_id=client.id,
            dodo_payment_id=f"pay_{uid}",
            amount=300.0,
            currency="USD",
            status=PaymentStatus.PAID,
        )
        session.add(pay)
        await session.commit()

    metrics = await scheduler.calculate_weekly_revenue()
    assert metrics["revenue_7d"] >= 300.0
    assert metrics["pacing_percentage"] >= 25.0
    assert metrics["target_weekly_revenue"] == 1200.0
    assert metrics["remaining_gap"] <= 900.0


@pytest.mark.asyncio
async def test_scheduler_respects_emergency_controls():
    """Scheduler must stop or defer dispatching tasks when emergency stop or pause is active."""
    scheduler = AutonomousSchedulerService()

    # Emergency STOP
    await emergency_service.stop(actor="tester", reason="Scheduler emergency test")
    try:
        counts = await scheduler.check_pipeline_and_dispatch()
        assert counts["execution"] == 0
    finally:
        await emergency_service.resume(actor="tester", reason="Reset emergency")

    # Emergency PAUSE
    await emergency_service.pause(actor="tester", reason="Scheduler pause test")
    try:
        counts = await scheduler.check_pipeline_and_dispatch()
        assert counts["execution"] == 0
    finally:
        await emergency_service.resume(actor="tester", reason="Reset pause")


@pytest.mark.asyncio
async def test_scheduler_dispatches_paid_projects_to_skill_engine():
    """Paid projects without active tasks are transitioned and enqueued for skill execution."""
    scheduler = AutonomousSchedulerService()
    await emergency_service.resume(actor="tester", reason="Ensure active state")

    import uuid
    uid = str(uuid.uuid4())[:8]

    async with async_session_factory() as session:
        client = Client(name="Exec Corp", email=f"exec_{uid}@example.com")
        session.add(client)
        await session.flush()

        proj = Project(
            client_id=client.id,
            name="Dispatchable Automation",
            status=ProjectStatus.PAID,
            accepted_price=450.0,
        )
        session.add(proj)
        await session.commit()
        project_id = proj.id

    counts = await scheduler.check_pipeline_and_dispatch()
    assert counts["execution"] >= 1

    # Verify project status in DB transitioned to EXECUTING
    async with async_session_factory() as session:
        updated_proj = await session.get(Project, project_id)
        assert updated_proj.status == ProjectStatus.EXECUTING
