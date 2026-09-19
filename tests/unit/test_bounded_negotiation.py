import pytest
from packages.projects.negotiation import (
    BoundedNegotiationEngine,
    NegotiationDecision,
    RequirementsExtractor,
)
from packages.shared.database import async_session_factory, init_db
from packages.shared.models import Client, Project, ProjectStatus, Quote


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()


def test_requirements_extraction_automation():
    """Verify structured deliverable extraction from client inquiry."""
    extractor = RequirementsExtractor()
    client_message = "We need an n8n workflow to sync inbound webhook leads with our CRM and notify on Slack."
    reqs = extractor.extract(client_message)

    assert reqs.project_type == "AUTOMATION"
    assert len(reqs.deliverables) >= 2
    assert any("n8n" in d.lower() for d in reqs.deliverables)
    assert len(reqs.acceptance_criteria) >= 2
    assert reqs.estimated_effort_hours > 0


def test_requirements_extraction_webhook():
    """Verify webhook deliverable extraction."""
    extractor = RequirementsExtractor()
    client_message = "Need a serverless webhook receiver with HMAC signature verification in FastAPI."
    reqs = extractor.extract(client_message)

    assert reqs.project_type == "WEBHOOK"
    assert any("hmac" in d.lower() for d in reqs.deliverables)


def test_negotiation_enforces_price_floor():
    """Verify offers below MIN_PROJECT_PRICE are deterministically rejected to floor."""
    engine = BoundedNegotiationEngine(min_price=150.0, max_discount_pct=15.0)
    result = engine.evaluate_commercial_terms(
        base_quoted_price=300.0,
        client_offered_price=75.0,  # Below $150 floor
    )

    assert result.decision == NegotiationDecision.REJECT_PRICE_FLOOR
    assert result.final_offered_price == 150.0
    assert "fixed minimum investment" in result.response_narrative.lower()


def test_negotiation_caps_excessive_discount():
    """Verify discounts beyond max_discount_pct are capped."""
    engine = BoundedNegotiationEngine(min_price=100.0, max_discount_pct=15.0)
    result = engine.evaluate_commercial_terms(
        base_quoted_price=500.0,
        client_offered_price=300.0,  # 40% discount requested
    )

    assert result.decision == NegotiationDecision.COUNTER_OFFER
    # Max discount is 15% -> $500 * 0.85 = $425
    assert result.final_offered_price == 425.0
    assert result.effective_discount_pct == 15.0


def test_negotiation_bounds_revision_cycles():
    """Verify clients cannot demand unlimited revisions beyond policy limit."""
    engine = BoundedNegotiationEngine(max_revisions=2)
    result = engine.evaluate_commercial_terms(
        base_quoted_price=400.0,
        client_offered_price=380.0,
        client_requested_revisions=6,  # Demanding 6 revision cycles
    )

    assert result.decision == NegotiationDecision.REJECT_EXCESSIVE_REVISIONS
    assert result.max_revisions == 2


def test_negotiation_accepts_valid_terms():
    """Verify fair terms within bounds are accepted."""
    engine = BoundedNegotiationEngine(min_price=150.0, max_discount_pct=15.0, max_revisions=2)
    result = engine.evaluate_commercial_terms(
        base_quoted_price=400.0,
        client_offered_price=360.0,  # 10% discount (allowed)
        client_requested_revisions=2,
    )

    assert result.decision == NegotiationDecision.ACCEPT_TERMS
    assert result.final_offered_price == 360.0


@pytest.mark.asyncio
async def test_create_authoritative_quote():
    """Verify quote persistence updates project status to QUOTE_SENT."""
    engine = BoundedNegotiationEngine()

    import uuid
    unique_email = f"lead_{uuid.uuid4().hex[:8]}@acmepartner.com"
    async with async_session_factory() as session:
        client = Client(name="Acme Partner", email=unique_email)
        session.add(client)
        await session.flush()

        project = Project(
            client_id=client.id,
            name="Workflow Integration",
            status=ProjectStatus.CONVERSATION_ACTIVE,
        )
        session.add(project)
        await session.commit()
        proj_id = project.id
        client_id = client.id

    quote = await engine.create_authoritative_quote(
        project_id=proj_id,
        client_id=client_id,
        amount=450.0,
        scope_summary="n8n CRM integration and QA",
        requirements=["Deliverable 1: n8n workflow", "Deliverable 2: QA Report"],
    )

    assert quote.id is not None
    assert quote.amount == 450.0
    assert quote.status == "PENDING"

    async with async_session_factory() as session:
        proj = await session.get(Project, proj_id)
        assert proj.status == ProjectStatus.QUOTE_SENT
        assert proj.accepted_price == 450.0
