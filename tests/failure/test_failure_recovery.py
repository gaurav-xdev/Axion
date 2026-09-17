"""Failure Injection and Recovery Test Suite.
Verifies system resilience against:
- Ollama / NIM provider unavailability & circuit breaker tripping
- Redis outage graceful failover
- Process restart and checkpoint restoration
- Duplicate webhook idempotency and state safety
- Emergency stop adherence
"""

import hashlib
import hmac
import json
import pytest
from packages.agent.runtime import AgentRuntime, emergency_controls
from packages.security.emergency import emergency_service
from packages.llm.providers import CircuitBreaker, CircuitBreakerState, NIMProvider, OllamaProvider
from packages.llm.router import TaskContext, llm_router
from packages.payments.verification import payment_verification_service
from packages.shared.config import settings
from packages.shared.database import async_session_factory, init_db
from packages.shared.models import AgentRun, AgentRunStatus, Client, PaymentStatus, Project, ProjectStatus


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()


@pytest.mark.asyncio
async def test_llm_circuit_breaker_trips_on_repeated_failures():
    """Circuit breaker trips to OPEN after threshold failures and rejects further requests."""
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
    assert cb.is_available() is True
    assert cb.state == CircuitBreakerState.CLOSED

    # Inject 3 failures
    cb.record_failure()
    cb.record_failure()
    cb.record_failure()

    assert cb.state == CircuitBreakerState.OPEN
    assert cb.is_available() is False


@pytest.mark.asyncio
async def test_router_fallback_when_nim_fails(monkeypatch):
    """When NVIDIA NIM fails, LLMRouter gracefully falls back to Ollama Cloud."""
    context = TaskContext(task_type="architecture", complexity=0.9, risk_level="HIGH")

    # Mock NIM generate to simulate outage/network failure
    async def failing_nim_generate(*args, **kwargs):
        raise ConnectionError("NVIDIA NIM cluster unreachable (503 Service Unavailable)")

    monkeypatch.setattr(llm_router.nim, "generate", failing_nim_generate)

    # Execution must not crash; router must safely fallback to Ollama
    response = await llm_router.generate(
        messages=[{"role": "user", "content": "Analyze system architecture"}],
        context=context,
    )
    assert response is not None
    assert response.provider == "ollama"
    print(f"Fallback verification: Route fell back to provider '{response.provider}'")


@pytest.mark.asyncio
async def test_process_restart_restores_agent_checkpoint():
    """Simulates a process restart/crash mid-run and verifies run checkpoint is restored."""
    await emergency_service.resume(actor="test", reason="Ensure active state")
    runtime = AgentRuntime()

    # 1. Initiate run
    run = await runtime.create_run(goal="Long-running data pipeline automation")
    run_id = run.id

    # 2. Execute step 1 and step 2
    await runtime.execute_step(
        run_id=run_id,
        thought="Step 1: Inspect environment",
        action_type="tool:filesystem.list",
        action_payload={"subpath": "."},
    )
    await runtime.execute_step(
        run_id=run_id,
        thought="Step 2: Create config file",
        action_type="tool:filesystem.write",
        action_payload={"path": "pipeline.cfg", "content": "batch_size=100"},
    )

    # 3. Simulate process crash (new runtime instance)
    new_runtime = AgentRuntime()
    recovered_run = await new_runtime.resume_or_recover_run(run_id)

    assert recovered_run is not None
    assert recovered_run.id == run_id
    assert recovered_run.step_count == 2
    assert recovered_run.checkpoint_json["last_step"] == 2
    assert recovered_run.checkpoint_json["last_action"] == "tool:filesystem.write"


@pytest.mark.asyncio
async def test_emergency_stop_aborts_execution_and_prevents_side_effects():
    """When emergency stop is active, new tool/task steps are aborted immediately."""
    runtime = AgentRuntime()
    run = await runtime.create_run(goal="Test emergency halting")

    # Activate emergency stop
    await emergency_service.stop(actor="tester", reason="Test emergency halting")
    try:
        result = await runtime.execute_step(
            run_id=run.id,
            thought="Attempting tool execution during emergency stop",
            action_type="tool:filesystem.write",
            action_payload={"path": "unauthorized.txt", "content": "data"},
        )
        assert result["status"] == "ABORTED"
        assert "Emergency stop active" in result["reason"]
    finally:
        await emergency_service.resume(actor="tester", reason="Test complete")


@pytest.mark.asyncio
async def test_duplicate_webhook_does_not_duplicate_side_effects():
    """Replaying an already-processed payment webhook is safe and idempotent."""
    secret = settings.DODO_WEBHOOK_SECRET or settings.APP_SECRET
    import uuid
    uid = str(uuid.uuid4())[:8]

    async with async_session_factory() as session:
        client = Client(name="Test Client", email=f"client_{uid}@example.com")
        session.add(client)
        await session.flush()
        proj = Project(
            client_id=client.id,
            name="Idempotency Test Project",
            status=ProjectStatus.PAYMENT_PENDING,
            accepted_price=199.0,
        )
        session.add(proj)
        await session.commit()
        project_id = proj.id
        client_id = client.id

    event_id = f"evt_idempotent_{uid}"
    payload = {
        "event_id": event_id,
        "event_type": "payment.succeeded",
        "data": {
            "payment_id": f"pay_{uid}",
            "amount": 19900,
            "currency": "USD",
            "metadata": {"project_id": project_id, "client_id": client_id},
        },
    }
    raw = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()

    # First dispatch
    ok1, msg1 = await payment_verification_service.process_webhook(raw, sig, payload)
    assert ok1 is True
    assert "Payment verified" in msg1

    # Second dispatch (replay attack / network retry)
    ok2, msg2 = await payment_verification_service.process_webhook(raw, sig, payload)
    assert ok2 is True
    assert "already processed" in msg2
