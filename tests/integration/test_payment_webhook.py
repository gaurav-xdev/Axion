"""Integration tests for Dodo Payments webhook verification, replay prevention, and cross-client isolation."""

import hashlib
import hmac
import json
import pytest
from packages.payments.verification import payment_verification_service
from packages.shared.config import settings
from packages.shared.database import async_session_factory, init_db
from packages.shared.models import Client, Project, ProjectStatus


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()


@pytest.mark.asyncio
async def test_payment_webhook_lifecycle():
    secret = settings.DODO_WEBHOOK_SECRET or settings.APP_SECRET

    import uuid
    unique_suffix = str(uuid.uuid4())[:8]

    # 1. Setup client and project
    async with async_session_factory() as session:
        client = Client(name="Acme Corp", email=f"billing_{unique_suffix}@acme.com")
        session.add(client)
        await session.flush()

        proj = Project(
            client_id=client.id,
            name="API Deliverable",
            status=ProjectStatus.PAYMENT_PENDING,
            accepted_price=250.0,
        )
        session.add(proj)
        await session.commit()
        client_id = client.id
        project_id = proj.id

    event_id = f"evt_test_{project_id[:8]}"
    payload = {
        "event_id": event_id,
        "event_type": "payment.succeeded",
        "data": {
            "payment_id": f"pay_{project_id[:8]}",
            "amount": 25000,
            "currency": "USD",
            "metadata": {"project_id": project_id, "client_id": client_id},
        },
    }
    raw_body = json.dumps(payload).encode()
    valid_sig = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()

    # Case 1: Bad Signature -> Must be rejected
    bad_sig_ok, bad_sig_msg = await payment_verification_service.process_webhook(
        raw_body=raw_body, signature="bad_invalid_signature_hash", event_data=payload
    )
    assert bad_sig_ok is False
    assert "Invalid cryptographic" in bad_sig_msg

    # Case 2: Valid Signature -> Verified & Project transitions to PAID
    success, msg = await payment_verification_service.process_webhook(
        raw_body=raw_body, signature=valid_sig, event_data=payload
    )
    assert success is True
    assert "Payment verified" in msg

    # Verify project status in DB is PAID
    async with async_session_factory() as session:
        updated_proj = await session.get(Project, project_id)
        assert updated_proj.status == ProjectStatus.PAID

    # Case 3: Replay / Duplicate Webhook -> Must be harmless & idempotent (Directive 10)
    dup_success, dup_msg = await payment_verification_service.process_webhook(
        raw_body=raw_body, signature=valid_sig, event_data=payload
    )
    assert dup_success is True
    assert "already processed" in dup_msg

    # Case 4: Cross-Client Mismatch -> Must be rejected
    mismatch_event_id = f"evt_mismatch_{project_id[:8]}"
    mismatch_payload = {
        "event_id": mismatch_event_id,
        "event_type": "payment.succeeded",
        "data": {
            "payment_id": "pay_cross_tenant",
            "amount": 25000,
            "metadata": {"project_id": project_id, "client_id": "client_impostor_999"},
        },
    }
    mismatch_raw = json.dumps(mismatch_payload).encode()
    mismatch_sig = hmac.new(secret.encode(), mismatch_raw, hashlib.sha256).hexdigest()

    mismatch_ok, mismatch_msg = await payment_verification_service.process_webhook(
        raw_body=mismatch_raw, signature=mismatch_sig, event_data=mismatch_payload
    )
    assert mismatch_ok is False
    assert "Security Violation" in mismatch_msg
