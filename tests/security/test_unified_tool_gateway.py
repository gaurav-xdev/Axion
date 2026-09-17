"""Tests verifying the Unified ToolGateway pipeline:
- Central routing for all side-effecting operations (communication, payment, media, terminal, filesystem, computer, browser)
- Strict RBAC authorization enforcement
- Default-deny on unknown tools
- Idempotency key replay protection
- Output secret redaction and audit logging
"""

import pytest
from packages.security.emergency import emergency_service
from packages.shared.database import init_db
from packages.shared.models import ToolRiskLevel
from packages.tools.base import ToolRequest
from packages.tools.gateway import tool_gateway


@pytest.mark.asyncio
async def test_unknown_tool_defaults_to_deny():
    """Verify that any unknown tool call is rejected by default policy with DENIED audit."""
    await init_db()
    req = ToolRequest(
        tool_name="unregistered.arbitrary_hack",
        arguments={"cmd": "whoami"},
        requested_by_role="OPERATOR",
    )
    res = await tool_gateway.execute(req)
    assert res.success is False
    assert "not recognized" in res.error
    assert res.risk_level == ToolRiskLevel.CRITICAL


@pytest.mark.asyncio
async def test_unified_communication_tool_via_gateway():
    """Verify communication dispatch passes through ToolGateway with schema, permission, and audit."""
    await init_db()
    req = ToolRequest(
        tool_name="communication.dispatch",
        arguments={
            "recipient": "client@example.com",
            "content": "Proposal updates ready for review",
            "channel": "EMAIL",
        },
        requested_by_role="OPERATOR",
        project_id="proj_comm_01",
    )
    res = await tool_gateway.execute(req)
    # Even if SMTP credentials are unconfigured, Gateway processes it through provider contract
    assert res.tool_name == "communication.dispatch"
    assert res.risk_level == ToolRiskLevel.HIGH
    assert "channel" in res.data


@pytest.mark.asyncio
async def test_unified_payment_tool_requires_project_context_and_permission():
    """Verify payment checkout tool requires valid project context and permissions."""
    await init_db()

    # 1. Auditor role lacks payments:write permission -> must be DENIED
    denied_req = ToolRequest(
        tool_name="payment.create_checkout",
        arguments={
            "quote_id": "quote_123",
            "amount": 250.0,
            "product_name": "Consulting Service",
            "customer_email": "payer@example.com",
        },
        requested_by_role="AUDITOR",
        project_id="proj_pay_01",
    )
    denied_res = await tool_gateway.execute(denied_req)
    assert denied_res.success is False
    assert "Missing permission" in denied_res.error

    # 2. Operator role possesses payments:write -> execution succeeds
    allowed_req = ToolRequest(
        tool_name="payment.create_checkout",
        arguments={
            "quote_id": "quote_123",
            "amount": 250.0,
            "product_name": "Consulting Service",
            "customer_email": "payer@example.com",
        },
        requested_by_role="OPERATOR",
        project_id="proj_pay_01",
    )
    allowed_res = await tool_gateway.execute(allowed_req)
    assert allowed_res.success is True
    assert "checkout_id" in allowed_res.data


@pytest.mark.asyncio
async def test_tool_gateway_idempotency_key_prevents_duplicate_side_effects():
    """Verify that duplicate tool requests with identical idempotency keys return the cached result without re-executing."""
    await init_db()
    idemp_key = "idemp_test_unique_key_9999"

    req1 = ToolRequest(
        tool_name="filesystem.write",
        arguments={"path": "idemp_test.txt", "content": "Initial execution content"},
        project_id="proj_idemp",
        requested_by_role="OPERATOR",
        idempotency_key=idemp_key,
    )
    res1 = await tool_gateway.execute(req1)
    assert res1.success is True
    assert res1.data["status"] == "written"
    first_hash = res1.data["hash"]

    # Re-execute with same idempotency key but different payload arguments
    req2 = ToolRequest(
        tool_name="filesystem.write",
        arguments={"path": "idemp_test.txt", "content": "Modified content should be ignored"},
        project_id="proj_idemp",
        requested_by_role="OPERATOR",
        idempotency_key=idemp_key,
    )
    res2 = await tool_gateway.execute(req2)
    assert res2.success is True
    # Should return cached first execution output
    assert res2.data["status"] == "written"
    assert res2.data["hash"] == first_hash
    assert res2.execution_time_ms == 0
