"""Full Sandbox End-to-End Test for the Autonomous Business Agent Lifecycle.
Tests complete commercial and technical execution:
Prospecting -> Qualification -> Outreach -> Scoping -> Checkout -> Verified Payment -> Sandboxed Coding -> Independent 5-Layer QA -> Delivery.
"""

import pytest
from packages.agent.lifecycle import autonomous_engine
from packages.shared.database import async_session_factory, init_db
from packages.shared.models import Artifact, Payment, Project, ProjectStatus, QARun


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()


@pytest.mark.asyncio
async def test_full_autonomous_business_cycle(monkeypatch):
    import uuid
    from datetime import datetime, timedelta, timezone
    from packages.payments.base import CheckoutResponse
    from packages.payments.dodo import dodo_provider
    from packages.shared.models import PaymentStatus

    async def mock_create_checkout(req):
        return CheckoutResponse(
            checkout_id=f"chk_e2e_{req.project_id[:8]}",
            checkout_url=f"https://test.dodopayments.com/checkout/chk_e2e_{req.project_id[:8]}",
            amount=req.amount,
            currency=req.currency,
            status=PaymentStatus.CHECKOUT_CREATED,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )

    monkeypatch.setattr(dodo_provider, "create_checkout", mock_create_checkout)
    from packages.shared.config import settings
    monkeypatch.setattr(settings, "DODO_WEBHOOK_SECRET", "test_webhook_secret_key_12345")
    monkeypatch.setattr(dodo_provider, "webhook_secret", "test_webhook_secret_key_12345")
    uid = str(uuid.uuid4())[:8]

    # Execute full autonomous lifecycle
    result = await autonomous_engine.run_autonomous_cycle(
        business_name=f"Vertex Logistics {uid}",
        domain=f"vertexlogistics_{uid}.io",
        lead_email=f"ops_{uid}@vertexlogistics.io",
    )

    assert result["status"] == "COMPLETED"
    assert result["qa_passed"] is True
    assert result["qa_score"] == 1.0

    project_id = result["project_id"]

    # Verify Database State Integrity
    async with async_session_factory() as session:
        # Project must be COMPLETED
        proj = await session.get(Project, project_id)
        assert proj is not None
        assert proj.status == ProjectStatus.COMPLETED

        # Verified Payment record must exist
        from sqlalchemy import select
        pay_stmt = select(Payment).where(Payment.project_id == project_id)
        payment = (await session.execute(pay_stmt)).scalar_one_or_none()
        assert payment is not None
        assert payment.status.value == "PAID"
        assert payment.amount == 350.0

        # Physical Artifacts must exist with valid SHA256 hash
        art_stmt = select(Artifact).where(Artifact.project_id == project_id)
        artifacts = (await session.execute(art_stmt)).scalars().all()
        assert len(artifacts) >= 1
        assert any(art.name == "webhook_receiver.py" and len(art.file_hash) == 64 for art in artifacts)

        # Independent QA Run must be PASSED
        qa_stmt = select(QARun).where(QARun.project_id == project_id)
        qa_runs = (await session.execute(qa_stmt)).scalars().all()
        assert len(qa_runs) >= 1
        assert any(qa.status == "PASSED" and qa.score == 1.0 for qa in qa_runs)
