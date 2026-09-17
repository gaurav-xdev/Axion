"""Tests verifying Authoritative Distributed Emergency Control State,
persistence across restarts, multi-worker observation, audit logging,
and prevention of side-effects under STOP and PAUSE conditions.
"""

import asyncio
import pytest
from packages.security.emergency import DistributedEmergencyService, emergency_service
from packages.shared.database import async_session_factory, init_db
from packages.shared.models import AuditEvent, SystemState, ToolRiskLevel
from packages.tools.base import ToolRequest
from packages.tools.gateway import tool_gateway


@pytest.mark.asyncio
async def test_emergency_state_defaults_and_transitions():
    """Verify initial state is active, and transitions update DB and bump versions."""
    await init_db()
    # Reset to normal active state first
    await emergency_service.resume(actor="test_init", reason="Reset initial state")
    
    # 1. Fetch initial state
    state = await emergency_service.get_state(force_refresh=True)
    assert state.is_stopped is False
    assert state.is_paused is False

    # 2. Pause
    p_state = await emergency_service.pause(actor="admin@test.local", reason="Testing pause")
    assert p_state.is_paused is True
    assert p_state.is_stopped is False
    assert p_state.version > state.version

    # 3. Stop
    s_state = await emergency_service.stop(actor="admin@test.local", reason="Testing hard stop")
    assert s_state.is_stopped is True
    assert s_state.is_paused is True
    assert s_state.version > p_state.version

    # 4. Resume
    r_state = await emergency_service.resume(actor="admin@test.local", reason="Testing resume")
    assert r_state.is_stopped is False
    assert r_state.is_paused is False
    assert r_state.version > s_state.version


@pytest.mark.asyncio
async def test_emergency_state_survives_process_restart():
    """Verify state persists in the database and is immediately inherited by a brand-new service instance."""
    await init_db()
    await emergency_service.stop(actor="security_officer", reason="Shutdown for maintenance")

    # Simulate completely new worker/API process by instantiating fresh service with empty memory
    new_worker_emergency_svc = DistributedEmergencyService()
    fresh_state = await new_worker_emergency_svc.get_state(force_refresh=True)

    assert fresh_state.is_stopped is True
    assert fresh_state.updated_by == "security_officer"
    assert fresh_state.reason == "Shutdown for maintenance"

    # Clean up state
    await emergency_service.resume(actor="security_officer", reason="Recovery")


@pytest.mark.asyncio
async def test_stopped_state_prevents_side_effecting_tools_in_tool_gateway():
    """Verify that when emergency stop is active, side-effecting tools are strictly blocked by ToolGateway,
    while READ_ONLY tools remain accessible.
    """
    await init_db()
    await emergency_service.stop(actor="admin@test.local", reason="Hard halt testing")

    # 1. Attempt side-effecting filesystem.write
    write_req = ToolRequest(
        tool_name="filesystem.write",
        arguments={"path": "malicious.txt", "content": "should be blocked"},
        project_id="proj_emergency_test",
        requested_by_role="OPERATOR",
    )
    write_res = await tool_gateway.execute(write_req)
    assert write_res.success is False
    assert "Emergency Stop is ACTIVE" in write_res.error

    # 2. Attempt side-effecting terminal.exec
    term_req = ToolRequest(
        tool_name="terminal.exec",
        arguments={"command": "echo test"},
        project_id="proj_emergency_test",
        requested_by_role="OPERATOR",
    )
    term_res = await tool_gateway.execute(term_req)
    assert term_res.success is False
    assert "Emergency Stop is ACTIVE" in term_res.error

    # 3. Read-only tool should still execute safely
    read_req = ToolRequest(
        tool_name="filesystem.list",
        arguments={"subpath": "."},
        project_id="proj_emergency_test",
        requested_by_role="OPERATOR",
    )
    read_res = await tool_gateway.execute(read_req)
    assert read_res.success is True

    # Resume system
    await emergency_service.resume(actor="admin@test.local", reason="Test completed")


@pytest.mark.asyncio
async def test_concurrent_emergency_transitions_atomic_audit():
    """Verify concurrent emergency updates do not corrupt state and record distinct AuditEvents."""
    await init_db()

    async def trigger_pause(idx: int):
        svc = DistributedEmergencyService()
        await svc.pause(actor=f"operator_{idx}", reason=f"Concurrent pause {idx}")

    # Launch 5 concurrent pause requests
    await asyncio.gather(*(trigger_pause(i) for i in range(5)))

    state = await emergency_service.get_state(force_refresh=True)
    assert state.is_paused is True

    # Check AuditEvents in database
    async with async_session_factory() as session:
        from sqlalchemy import select
        stmt = select(AuditEvent).where(AuditEvent.action == "EMERGENCY_PAUSE")
        events = (await session.execute(stmt)).scalars().all()
        assert len(events) >= 5

    await emergency_service.resume(actor="admin", reason="Concurrent test cleanup")
