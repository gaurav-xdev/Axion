"""Decoupled Pipeline Integration Test for Autonomous Business Agent Lifecycle.
Tests the decoupled end-to-end commercial and technical pipeline:
Phase 1: Prospecting -> Qualification -> Outreach -> Scoping -> Checkout Creation (Stops at PAYMENT_PENDING).
Fail-Closed Check: Verify unverified project execution is strictly blocked.
Phase 2: Authentic External Webhook Receipt -> Verified Payment.
Phase 3: Execution -> Sandboxed Coding -> Independent 5-Layer QA -> Delivery.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import uuid
import pytest

from packages.agent.lifecycle import autonomous_engine
from packages.payments.base import CheckoutResponse
from packages.payments.dodo import dodo_provider
from packages.payments.verification import payment_verification_service
from packages.shared.config import settings
from packages.shared.database import async_session_factory, init_db
from packages.shared.exceptions import ExternalVerificationRequiredError
from packages.shared.models import (
    Artifact,
    Payment,
    PaymentStatus,
    Project,
    ProjectStatus,
    QARun,
)


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()


@pytest.mark.asyncio
async def test_decoupled_autonomous_business_lifecycle(monkeypatch):
    """Verifies that commercial intake stops at CHECKOUT_CREATED and execution requires verified external payment."""
    uid = str(uuid.uuid4())[:8]

    # Configure mocked Dodo provider for checkout session generation
    async def mock_create_checkout(req):
        return CheckoutResponse(
            checkout_id=f"chk_pipe_{req.project_id[:8]}",
            checkout_url=f"https://test.dodopayments.com/checkout/chk_pipe_{req.project_id[:8]}",
            amount=req.amount,
            currency=req.currency,
            status=PaymentStatus.CHECKOUT_CREATED,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )

    monkeypatch.setattr(dodo_provider, "create_checkout", mock_create_checkout)
    test_secret = "test_webhook_secret_key_12345"
    monkeypatch.setattr(settings, "DODO_WEBHOOK_SECRET", test_secret)
    monkeypatch.setattr(dodo_provider, "webhook_secret", test_secret)

    # -------------------------------------------------------------------------
    # PHASE 1A: COMMERCIAL DISCOVERY & OUTREACH (Stops at OUTREACH_DISPATCHED)
    # -------------------------------------------------------------------------
    outreach = await autonomous_engine.start_commercial_intake(
        business_name=f"Apex Logistics {uid}",
        domain=f"apexlogistics_{uid}.io",
        lead_email=f"ops_{uid}@apexlogistics.io",
    )

    assert outreach["status"] == "OUTREACH_DISPATCHED"
    assert outreach["qualification_score"] >= 0.5
    assert outreach["prospect_id"] is not None

    # -------------------------------------------------------------------------
    # PHASE 1B: INBOUND CLIENT RESPONSE (Conversation Reasoning -> Quote -> Checkout)
    # -------------------------------------------------------------------------
    intake = await autonomous_engine.process_inbound_commercial_response(
        sender=f"ops_{uid}@apexlogistics.io",
        content="Need a serverless webhook receiver with HMAC signature verification in FastAPI with POST endpoint and payload schema",
    )

    assert intake["status"] == "CHECKOUT_CREATED"
    project_id = intake["project_id"]
    client_id = intake["client_id"]
    checkout_id = intake["checkout_id"]
    amount = intake["amount"]
    assert checkout_id.startswith("chk_pipe_")

    # Verify project is in database and NOT yet executed
    async with async_session_factory() as session:
        proj = await session.get(Project, project_id)
        assert proj is not None
        assert proj.status != ProjectStatus.COMPLETED

    # -------------------------------------------------------------------------
    # FAIL-CLOSED CHECK: Execution is BLOCKED before payment verification
    # -------------------------------------------------------------------------
    with pytest.raises(ExternalVerificationRequiredError) as excinfo:
        await autonomous_engine.execute_paid_project(project_id)
    assert "Execution is strictly blocked" in str(excinfo.value)

    # -------------------------------------------------------------------------
    # PHASE 2: AUTHENTIC EXTERNAL PAYMENT WEBHOOK RECEIPT
    # -------------------------------------------------------------------------
    event_id = f"evt_test_{uid}"
    webhook_payload = {
        "event_id": event_id,
        "event_type": "payment.succeeded",
        "data": {
            "checkout_id": checkout_id,
            "amount": int(amount * 100),
            "metadata": {"project_id": project_id, "client_id": client_id},
        },
    }
    raw_body = json.dumps(webhook_payload).encode()
    signature = hmac.new(test_secret.encode(), raw_body, hashlib.sha256).hexdigest()

    verified, msg = await payment_verification_service.process_webhook(
        raw_body=raw_body, signature=signature, event_data=webhook_payload
    )
    assert verified is True, f"Webhook verification failed: {msg}"

    # Verify Project status advanced to PAID
    async with async_session_factory() as session:
        proj = await session.get(Project, project_id)
        assert proj.status == ProjectStatus.PAID

    # -------------------------------------------------------------------------
    # PHASE 3: EXECUTE PAID PROJECT (Planning -> Skill -> QA -> Delivery)
    # -------------------------------------------------------------------------
    exec_res = await autonomous_engine.execute_paid_project(project_id)

    assert exec_res["status"] == "COMPLETED"
    assert exec_res["qa_passed"] is True
    assert exec_res["qa_score"] == 1.0

    # -------------------------------------------------------------------------
    # VERIFY FINAL DATABASE STATE INTEGRITY
    # -------------------------------------------------------------------------
    async with async_session_factory() as session:
        proj = await session.get(Project, project_id)
        assert proj.status == ProjectStatus.COMPLETED

        from sqlalchemy import select
        pay_stmt = select(Payment).where(Payment.project_id == project_id)
        payment = (await session.execute(pay_stmt)).scalar_one_or_none()
        assert payment is not None
        assert payment.status == PaymentStatus.PAID
        assert payment.amount == amount

        art_stmt = select(Artifact).where(Artifact.project_id == project_id)
        artifacts = (await session.execute(art_stmt)).scalars().all()
        assert len(artifacts) >= 1
        assert any(art.name == "webhook_receiver.py" and len(art.file_hash) == 64 for art in artifacts)

        qa_stmt = select(QARun).where(QARun.project_id == project_id)
        qa_runs = (await session.execute(qa_stmt)).scalars().all()
        assert len(qa_runs) >= 1
        assert any(qa.status == "PASSED" and qa.score == 1.0 for qa in qa_runs)
