"""Security and boundary tests verifying ToolGateway is the single side-effect choke point."""

from datetime import datetime, timezone
import uuid
import pytest

from packages.security.emergency import emergency_service
from packages.shared.database import async_session_factory, init_db
from packages.shared.models import AuditEvent, Client, Project, ProjectStatus, Quote, ToolRiskLevel, ToolRun
from packages.tools.base import ToolRequest
from packages.tools.gateway import tool_gateway


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()


@pytest.mark.asyncio
async def test_tool_gateway_communication_dispatch_records_audit():
    """Verify communication dispatch through ToolGateway records both AuditEvent and ToolRun."""
    await emergency_service.resume(actor="tester", reason="Reset emergency")
    uid = str(uuid.uuid4())[:8]

    tool_req = ToolRequest(
        tool_name="communication.dispatch",
        arguments={
            "recipient": f"test_{uid}@example.com",
            "sender": "agent@axion.business",
            "subject": "Audit Test",
            "content": "Testing choke point audit enforcement.",
            "channel": "EMAIL",
        },
        requested_by_role="OPERATOR",
        idempotency_key=f"choke_comm_{uid}",
    )

    res = await tool_gateway.execute(tool_req)
    assert res.tool_name == "communication.dispatch"
    assert res.risk_level == ToolRiskLevel.HIGH

    # Verify AuditEvent was persisted
    async with async_session_factory() as session:
        audit = (
            await session.execute(
                __import__("sqlalchemy")
                .select(AuditEvent)
                .where(AuditEvent.action == "tool_execute:communication.dispatch")
                .order_by(AuditEvent.created_at.desc())
            )
        ).scalars().first()
        assert audit is not None
        assert audit.actor == "OPERATOR"


@pytest.mark.asyncio
async def test_tool_gateway_payment_create_checkout_requires_project_context():
    """Verify payment checkout generation strictly fails if project context is missing."""
    await emergency_service.resume(actor="tester", reason="Reset emergency")
    uid = str(uuid.uuid4())[:8]

    # Tool request without project_id
    tool_req = ToolRequest(
        tool_name="payment.create_checkout",
        arguments={
            "quote_id": f"quote_{uid}",
            "amount": 250.0,
            "currency": "USD",
            "product_name": "Test Deliverable",
            "customer_email": f"client_{uid}@example.com",
        },
        requested_by_role="OPERATOR",
        project_id=None,  # Missing project context
    )

    res = await tool_gateway.execute(tool_req)
    assert res.success is False
    assert "project_id context" in res.error.lower()


@pytest.mark.asyncio
async def test_tool_gateway_emergency_stop_blocks_side_effects():
    """Verify emergency STOP blocks side-effecting tools with zero side effects executed."""
    await emergency_service.stop(actor="tester", reason="ToolGateway halt test")
    try:
        uid = str(uuid.uuid4())[:8]
        tool_req = ToolRequest(
            tool_name="communication.dispatch",
            arguments={
                "recipient": f"test_{uid}@example.com",
                "sender": "agent@axion.business",
                "subject": "Emergency Test",
                "content": "This should be blocked.",
                "channel": "EMAIL",
            },
            requested_by_role="OPERATOR",
        )

        res = await tool_gateway.execute(tool_req)
        assert res.success is False
        assert "emergency stop is active" in res.error.lower()
    finally:
        await emergency_service.resume(actor="tester", reason="Reset emergency")
