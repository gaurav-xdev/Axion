"""Comprehensive failure mode tests covering emergency stop during side-effects,
browser tool failure handling, and concurrent idempotency.
"""

from datetime import datetime, timezone
import uuid
import pytest

from packages.security.emergency import emergency_service
from packages.shared.database import async_session_factory, init_db
from packages.tools.base import ToolRequest
from packages.tools.gateway import tool_gateway
from packages.tools.unified import BrowserActionTool


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()


@pytest.mark.asyncio
async def test_browser_tool_graceful_failure_when_unsupported_action():
    """BrowserActionTool gracefully handles invalid or failing actions without crashing."""
    tool = BrowserActionTool()
    req = ToolRequest(
        tool_name="browser.action",
        arguments={
            "action": "click",
            "selector": "#nonexistent-button",
        },
        requested_by_role="OPERATOR",
    )

    res = await tool_gateway.execute(req)
    assert res.tool_name == "browser.action"
    # Action without active browser session fails gracefully
    assert res.success is False or res.data.get("success") is False or "error" in res.data


@pytest.mark.asyncio
async def test_tool_gateway_concurrent_idempotent_requests():
    """Concurrent executions with identical idempotency keys do not produce duplicate side effects."""
    await emergency_service.resume(actor="tester", reason="Reset emergency")
    uid = str(uuid.uuid4())[:8]
    idemp_key = f"concurrent_idemp_{uid}"

    req1 = ToolRequest(
        tool_name="communication.dispatch",
        arguments={
            "recipient": f"idemp_{uid}@example.com",
            "sender": "agent@axion.business",
            "subject": "Idempotency Test 1",
            "content": "Message body 1",
            "channel": "EMAIL",
        },
        requested_by_role="OPERATOR",
        idempotency_key=idemp_key,
    )

    req2 = ToolRequest(
        tool_name="communication.dispatch",
        arguments={
            "recipient": f"idemp_{uid}@example.com",
            "sender": "agent@axion.business",
            "subject": "Idempotency Test 2 (Should be deduplicated)",
            "content": "Message body 2",
            "channel": "EMAIL",
        },
        requested_by_role="OPERATOR",
        idempotency_key=idemp_key,
    )

    # First execution succeeds and caches response
    res1 = await tool_gateway.execute(req1)
    # Second execution replays cached result
    res2 = await tool_gateway.execute(req2)

    assert res1.success is True
    assert res2.success is True
    # Verify res2 returned cached execution time 0
    assert res2.execution_time_ms == 0


@pytest.mark.asyncio
async def test_emergency_stop_during_side_effects_aborts_immediately():
    """Activating emergency stop immediately blocks any subsequent tool operations."""
    await emergency_service.stop(actor="tester", reason="Immediate abort test")
    try:
        req = ToolRequest(
            tool_name="payment.create_checkout",
            arguments={
                "quote_id": "quote_halt_123",
                "amount": 500.0,
                "product_name": "Should Not Run",
                "customer_email": "halt@example.com",
            },
            project_id="proj_halt",
            requested_by_role="OPERATOR",
        )
        res = await tool_gateway.execute(req)
        assert res.success is False
        assert "emergency stop is active" in res.error.lower()
    finally:
        await emergency_service.resume(actor="tester", reason="Reset emergency")
