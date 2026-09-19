"""Live External Sandbox End-to-End Test for the Autonomous Business Agent.
Validates live external provider integration against Dodo Payments Sandbox.
Strictly zero-mock: if external sandbox credentials are not configured in the host
environment, the test is marked as BLOCKED_EXTERNAL_DEPENDENCY (skipped) rather than
fabricating synthetic success.
"""

import os
import uuid
import pytest

from packages.agent.lifecycle import autonomous_engine
from packages.shared.config import settings
from packages.shared.database import async_session_factory, init_db
from packages.shared.exceptions import ExternalVerificationRequiredError
from packages.shared.models import Project, ProjectStatus


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()


@pytest.mark.asyncio
async def test_live_dodo_sandbox_e2e():
    """Live sandbox verification against external Dodo Payments API.
    Fails closed / skips if real external credentials are not present in environment.
    """
    api_key = settings.DODO_API_KEY or os.environ.get("DODO_API_KEY")
    webhook_secret = settings.DODO_WEBHOOK_SECRET or os.environ.get("DODO_WEBHOOK_SECRET")

    if not api_key or not webhook_secret:
        pytest.skip(
            "BLOCKED_EXTERNAL_DEPENDENCY: Real Dodo sandbox credentials "
            "(DODO_API_KEY, DODO_WEBHOOK_SECRET) are not configured in environment. "
            "Zero-mock rule: live external payment verification is marked UNVERIFIED/BLOCKED."
        )

    uid = str(uuid.uuid4())[:8]

    # Execute Phase 1: Real Commercial Intake against live Dodo Sandbox API
    intake = await autonomous_engine.start_commercial_intake(
        business_name=f"Live Enterprise {uid}",
        domain=f"live-enterprise-{uid}.com",
        lead_email=f"contact_{uid}@live-enterprise-{uid}.com",
    )

    assert intake["status"] == "CHECKOUT_CREATED"
    assert intake["checkout_id"]
    assert intake["checkout_url"].startswith("https://")
    project_id = intake["project_id"]

    # Verify project is recorded in DB awaiting external payment
    async with async_session_factory() as session:
        proj = await session.get(Project, project_id)
        assert proj is not None
        assert proj.status != ProjectStatus.COMPLETED

    # Verify fail-closed enforcement: execution is strictly blocked until external payment is verified
    with pytest.raises(ExternalVerificationRequiredError):
        await autonomous_engine.execute_paid_project(project_id)
