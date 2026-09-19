import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from packages.communications.conversation import (
    InboundClassification,
    InboundMessagePayload,
    conversation_engine,
)
from packages.shared.database import async_session_factory, init_db
from packages.shared.models import ChannelType, Contact, Conversation, Prospect
from apps.api.main import app


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()


@pytest.mark.asyncio
async def test_conversation_engine_interested_intent():
    """Test inbound lead stating interest is classified and transitioned to INTERESTED."""
    uid = uuid.uuid4().hex[:6]
    payload = InboundMessagePayload(
        sender=f"sarah_{uid}@cyberdyne-robotics.com",
        recipient="agent@autonomousagency.local",
        channel=ChannelType.EMAIL,
        subject=f"Inquiry regarding webhook pipeline {uid}",
        content=f"We are very interested in your automation services. Can you send a quote for an n8n CRM sync? Ref {uid}",
    )

    result = await conversation_engine.ingest_inbound_message(payload)

    assert result.classification == InboundClassification.INTERESTED
    assert result.suggested_next_action == "GATHER_REQUIREMENTS"
    assert result.conversation_id is not None
    assert result.prospect_id is not None

    async with async_session_factory() as session:
        prospect = await session.get(Prospect, result.prospect_id)
        assert prospect is not None
        assert prospect.status == "INTERESTED"
        assert prospect.domain == "cyberdyne-robotics.com"

        conv = await session.get(Conversation, result.conversation_id)
        assert conv is not None
        assert conv.status == "INTERESTED"


@pytest.mark.asyncio
async def test_conversation_engine_opt_out():
    """Test opt-out request sets prospect and contact opt_out flag to True."""
    uid = uuid.uuid4().hex[:6]
    payload = InboundMessagePayload(
        sender=f"busy_{uid}@bigcorp.io",
        recipient="agent@autonomousagency.local",
        channel=ChannelType.EMAIL,
        subject=f"Unsubscribe {uid}",
        content=f"Please unsubscribe me immediately. Do not contact again. Ref {uid}",
    )

    result = await conversation_engine.ingest_inbound_message(payload)

    assert result.classification == InboundClassification.OPT_OUT
    assert result.suggested_next_action == "CLOSE_CONVERSATION"

    async with async_session_factory() as session:
        prospect = await session.get(Prospect, result.prospect_id)
        assert prospect is not None
        assert prospect.opt_out is True
        assert prospect.status == "OPT_OUT"


@pytest.mark.asyncio
async def test_conversation_engine_duplicate_detection():
    """Test rapid duplicate message ingestion is detected and skipped."""
    uid = uuid.uuid4().hex[:6]
    payload = InboundMessagePayload(
        sender=f"repeat_{uid}@acme.org",
        recipient="agent@autonomousagency.local",
        channel=ChannelType.EMAIL,
        subject=f"Duplicate check {uid}",
        content=f"Hello, what is your pricing structure? Ref {uid}",
    )

    res1 = await conversation_engine.ingest_inbound_message(payload)
    assert res1.suggested_next_action == "AWAIT_CLIENT_DETAILS"

    # Ingest identical message again
    res2 = await conversation_engine.ingest_inbound_message(payload)
    assert res2.suggested_next_action == "IGNORE_DUPLICATE"
    assert res2.conversation_id == res1.conversation_id


@pytest.mark.asyncio
async def test_api_inbound_communication_webhook():
    """Test the /webhooks/communications/inbound HTTP endpoint."""
    uid = uuid.uuid4().hex[:6]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/webhooks/communications/inbound",
            json={
                "sender": f"dave_{uid}@techstartup.co",
                "recipient": "agent@autonomousagency.local",
                "channel": "EMAIL",
                "subject": f"Need automation {uid}",
                "content": f"Sounds good, let's talk and discuss next steps for this project. Ref {uid}",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "processed"
        assert data["classification"] == "INTERESTED"
        assert data["conversation_id"] is not None
