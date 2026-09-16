"""Unit tests for Project Acceptance Engine and Negotiation Policy."""

import pytest
from packages.projects.acceptance import (
    AcceptanceDecision,
    ProjectAssessmentRequest,
    project_acceptance_engine,
)


def test_reject_security_bypass():
    req = ProjectAssessmentRequest(
        title="Bypass cloud MFA",
        description="Write script to bypass MFA and CAPTCHA",
        requires_security_bypass=True,
    )
    result = project_acceptance_engine.evaluate(req)
    assert result.decision == AcceptanceDecision.REJECT
    assert "Security policy violation" in result.reasons[0]


def test_reject_unsupported_scope():
    req = ProjectAssessmentRequest(
        title="Build massive MMO Game",
        description="Create multiplayer 3D online game",
        has_unsupported_scope=True,
    )
    result = project_acceptance_engine.evaluate(req)
    assert result.decision == AcceptanceDecision.REJECT
    assert "Scope rejected" in result.reasons[0]


def test_accept_feasible_workflow():
    req = ProjectAssessmentRequest(
        title="CRM Webhook Automation",
        description="Parse incoming leads and forward to CRM API",
        estimated_effort_hours=3.0,
        integration_count=2,
        known_requirements=["Parse webhook", "Format JSON", "POST to CRM"],
    )
    result = project_acceptance_engine.evaluate(req)
    assert result.decision == AcceptanceDecision.ACCEPT
    assert result.quoted_price >= 150.0  # Min price limit
    assert result.max_revisions == 2     # Strict negotiation policy limit
