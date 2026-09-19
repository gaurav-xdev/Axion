"""Unit test for active prospect discovery and qualification using BrowserWorker signals."""

import pytest
from packages.browser.worker import BrowserTaskOutput, browser_worker
from packages.projects.prospecting import prospecting_engine
from packages.shared.database import init_db


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()


@pytest.mark.asyncio
async def test_active_prospect_discovery_with_browser_signals(monkeypatch):
    """Verify discover_and_qualify_target actively extracts signals via BrowserWorker."""
    import uuid
    domain = f"innovate-{uuid.uuid4().hex[:6]}.com"

    async def mock_execute_task(task):
        return BrowserTaskOutput(
            url=task.url,
            title="Innovate Logistics Solutions",
            extracted_text={
                "title": "Innovate Logistics Solutions",
                "body": "Contact us at ops@innovate.com to request a custom quote or schedule an onboarding call.",
            },
            screenshot_path=None,
            success=True,
        )

    monkeypatch.setattr(browser_worker, "execute_task", mock_execute_task)

    prospect = await prospecting_engine.discover_and_qualify_target(domain)

    assert prospect is not None
    assert prospect.domain == domain
    assert prospect.business_name == "Innovate Logistics Solutions"
    assert prospect.qualification_score >= 0.5
    assert "Manual quotation/inquiry intake process" in prospect.pain_points.get("points", [])
