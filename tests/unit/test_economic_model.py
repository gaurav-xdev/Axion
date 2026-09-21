"""Unit tests for the Economic Opportunity Value Model."""

import pytest
from packages.projects.economic_model import (
    EconomicValuation,
    OpportunityEconomicEvaluator,
    economic_evaluator,
)
from packages.projects.prospecting import (
    ObservationType,
    ProspectData,
    ResearchObservation,
)


def test_evaluate_high_priority_target():
    prospect = ProspectData(
        business_name="Apex Logistics Cloud",
        website="https://apexlogistics.io",
        industry="Logistics & Supply Chain",
        contact_name="Sarah Chen",
        contact_email="sarah.chen@apexlogistics.io",
        observed_pain_points=["Manual webhook processing errors", "Slow CRM lead synchronization"],
        observations=[
            ResearchObservation(
                observation_type=ObservationType.FACT,
                statement="Webhooks failing with 500 status on peak shipment events",
                confidence=1.0,
            ),
            ResearchObservation(
                observation_type=ObservationType.FACT,
                statement="FastAPI endpoint unverified HMAC signatures",
                confidence=0.95,
            ),
        ],
    )

    valuation = economic_evaluator.evaluate_prospect(prospect)
    assert isinstance(valuation, EconomicValuation)
    assert valuation.factors.identity_confidence >= 0.8
    assert valuation.factors.contact_confidence == 1.0
    assert valuation.factors.problem_evidence >= 0.7
    assert valuation.factors.service_fit >= 0.7
    assert valuation.p_conversion >= 0.4
    assert valuation.expected_project_value_usd >= 1000.0
    assert valuation.expected_margin >= 0.90
    assert valuation.expected_economic_value >= 150.0
    assert valuation.qualification_recommendation == "PRIORITY_TARGET"


def test_evaluate_unverified_target_deferred():
    prospect = ProspectData(
        business_name="Unknown Entity",
        website="unknown-test.xyz",
        industry="General",
        contact_name=None,
        contact_email=None,
        observed_pain_points=[],
        observations=[],
    )

    valuation = economic_evaluator.evaluate_prospect(prospect)
    assert valuation.factors.contact_confidence <= 0.2
    assert valuation.factors.problem_evidence <= 0.2
    assert valuation.p_conversion < 0.2
    assert valuation.qualification_recommendation == "DEFERRED"


def test_economic_valuation_sensitivities():
    evaluator = OpportunityEconomicEvaluator()
    prospect = ProspectData(
        business_name="Acme Corp",
        website="acme.com",
        industry="SaaS",
        contact_name="Bob",
        contact_email="bob@acme.com",
        observed_pain_points=["API integration"],
    )

    val_high_success = evaluator.evaluate_prospect(prospect, historical_delivery_rate=0.98)
    val_low_success = evaluator.evaluate_prospect(prospect, historical_delivery_rate=0.60)

    assert val_high_success.expected_economic_value > val_low_success.expected_economic_value
