"""Tests verifying evidence-grounded outreach and absence of synthesized URLs/domains."""

import uuid
import pytest
from packages.projects.manager import project_planning_engine
from packages.projects.prospecting import ObservationType, ProspectData, ResearchObservation, prospecting_engine
from packages.shared.database import async_session_factory, init_db
from packages.shared.models import Client, Project, ProjectStatus, Requirement


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()


@pytest.mark.asyncio
async def test_project_planning_does_not_synthesize_crm_url_when_unstated():
    """When a client project does not state an external CRM API URL, it must remain None without fabrication."""
    uid = str(uuid.uuid4())[:8]
    async with async_session_factory() as session:
        client = Client(name=f"No URL Corp {uid}", email=f"client_{uid}@nourl.com")
        session.add(client)
        await session.flush()

        proj = Project(
            client_id=client.id,
            name=f"Internal Webhook Automation {uid}",
            description="Process internal webhook alerts and log to local database",
            status=ProjectStatus.PAID,
            accepted_price=500.0,
        )
        session.add(proj)
        await session.flush()

        req = Requirement(
            project_id=proj.id,
            title="Webhook Receiver",
            description="Build FastAPI webhook endpoint verifying HMAC signatures without third-party CRM push",
        )
        session.add(req)
        await session.commit()
        project_id = proj.id

    tasks = await project_planning_engine.plan_project(project_id)
    eng_task = tasks[0]

    # Verify that crm_api_url is None and NOT fabricated as https://api.internalwebhookautomation.com
    assert eng_task.input_payload.get("crm_api_url") is None
    assert eng_task.input_payload.get("base_url") is None
    # Domain is extracted from client email (nourl.com) rather than fabricated
    assert eng_task.input_payload.get("domain") == "nourl.com"


@pytest.mark.asyncio
async def test_prospecting_records_authentic_observations_and_pain_points():
    """Verifies prospect intake records authentic technical observations and factor provenance."""
    uid = str(uuid.uuid4())[:8]
    prospect_data = ProspectData(
        business_name=f"Grounded Tech {uid}",
        website=f"https://grounded-{uid}.io",
        industry="SaaS Automation",
        contact_name="Alex Rivera",
        contact_email=f"alex@grounded-{uid}.io",
        observed_pain_points=["API rate limit errors during billing reconciliation"],
        observations=[
            ResearchObservation(
                observation_type=ObservationType.FACT,
                statement="HTTP 429 response on Stripe sync webhook trigger",
                confidence=0.98,
            )
        ],
    )

    prospect = await prospecting_engine.ingest_prospect(prospect_data)
    assert prospect.pain_points["points"] == ["API rate limit errors during billing reconciliation"]
    assert len(prospect.pain_points["observations"]) == 1
    assert prospect.pain_points["observations"][0]["observation_type"] == "FACT"

    # Verify economic valuation provenance
    econ_val = prospect.evidence_sources["economic_valuation"]
    assert econ_val["provenance"]["identity_provenance"] == "FACT_VERIFIED"
    assert econ_val["provenance"]["contact_provenance"] == "FACT_DIRECT_MATCH"
    assert econ_val["provenance"]["problem_evidence_provenance"] == "FACT_OBSERVED"
