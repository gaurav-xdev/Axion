"""Unit tests for the 7-Dimensional Business Memory Architecture."""

import pytest
from packages.memory.context import (
    ClientMemoryProfile,
    EpisodicEvent,
    FailureRecord,
    MemoryManager,
    SkillExecutionMetric,
)


def test_episodic_memory_recording():
    mem = MemoryManager()
    evt = mem.record_episodic_event(
        event_type="OUTREACH_DISPATCHED",
        entity_id="prospect_123",
        description="Cold outreach sent to ops@apexlogistics.io",
        evidence={"channel": "EMAIL", "template": "automation_value"},
    )

    assert isinstance(evt, EpisodicEvent)
    assert evt.event_type == "OUTREACH_DISPATCHED"
    assert evt.entity_id == "prospect_123"
    assert len(mem._episodic_events) == 1


def test_failure_memory_and_prevention_matching():
    mem = MemoryManager()
    mem.record_failure_lesson(
        failure_type="SIGNATURE_MISMATCH",
        root_cause="Webhook signature header did not match hex digest",
        context_keywords=["webhook", "hmac", "fastapi"],
        prevention_rule="Ensure raw request body bytes are hashed before json deserialization",
        solution_verified=True,
    )

    rules = mem.get_prevention_rules_for_context(["FastAPI", "Webhook Receiver"])
    assert len(rules) == 1
    assert "raw request body bytes" in rules[0]

    unrelated_rules = mem.get_prevention_rules_for_context(["React", "Landing Page"])
    assert len(unrelated_rules) == 0


def test_skill_performance_metrics_and_calibration():
    mem = MemoryManager()
    # 2 successes, 1 failure
    mem.record_skill_execution("build_api_integration", success=True, duration_seconds=120.0, cost_usd=0.05)
    mem.record_skill_execution("build_api_integration", success=True, duration_seconds=130.0, cost_usd=0.06)
    mem.record_skill_execution("build_api_integration", success=False, duration_seconds=150.0, cost_usd=0.08, failure_mode="TIMEOUT")

    metric = mem.get_skill_metric("build_api_integration")
    assert metric.total_runs == 3
    assert metric.successful_runs == 2
    assert metric.success_rate == 0.667
    assert metric.avg_duration_seconds == 133.33
    assert metric.failure_modes.get("TIMEOUT") == 1

    # Calibration multiplier increases buffer due to failures
    multiplier = mem.get_calibration_multiplier("build_api_integration")
    assert multiplier > 1.0


def test_client_profile_memory():
    mem = MemoryManager()
    prof = mem.update_client_memory(
        client_id="client_789",
        domain="apexlogistics.io",
        constraint="Must use Python 3.11+",
        payment_amount=1200.0,
    )

    assert isinstance(prof, ClientMemoryProfile)
    assert prof.total_projects_count == 1
    assert prof.total_paid_usd == 1200.0
    assert "Must use Python 3.11+" in prof.stated_technical_constraints
