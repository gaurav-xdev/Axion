"""Unit tests for packages/shared/exceptions.py."""

import pytest
from packages.shared.exceptions import (
    AxionBaseException,
    MissingRequiredContextError,
    ProviderNotConfiguredError,
    UnsupportedActionError,
    ExternalVerificationRequiredError,
    InvalidStateTransitionError,
    SandboxExecutionError,
    SecurityViolationError,
)


def test_missing_required_context_error():
    err = MissingRequiredContextError("domain", step_id="synthesize_findings")
    assert err.missing_key == "domain"
    assert err.step_id == "synthesize_findings"
    assert "Missing required context key 'domain'" in str(err)
    assert "synthesize_findings" in str(err)


def test_provider_not_configured_error():
    err = ProviderNotConfiguredError("DodoPayments", missing_config="DODO_API_KEY")
    assert err.provider_name == "DodoPayments"
    assert "DODO_API_KEY" in str(err)
    assert "Synthetic success is strictly prohibited" in str(err)


def test_unsupported_action_error():
    err = UnsupportedActionError("FLY_DRONE", step_id="step_99")
    assert err.action_type == "FLY_DRONE"
    assert err.step_id == "step_99"
    assert "Unsupported or unhandled action type 'FLY_DRONE'" in str(err)


def test_invalid_state_transition_error():
    err = InvalidStateTransitionError("COMPLETED", "DISCOVERED", entity_name="Project")
    assert err.current_state == "COMPLETED"
    assert err.target_state == "DISCOVERED"
    assert "Invalid state transition for Project from 'COMPLETED' to 'DISCOVERED'" in str(err)


def test_sandbox_execution_error():
    err = SandboxExecutionError(exit_code=1, stdout="", stderr="AssertionError: 1 != 2")
    assert err.exit_code == 1
    assert "AssertionError: 1 != 2" in str(err)


def test_security_violation_error():
    err = SecurityViolationError("SSRF", "Target IP is a loopback address")
    assert err.violation_type == "SSRF"
    assert "Security policy violation [SSRF]" in str(err)
