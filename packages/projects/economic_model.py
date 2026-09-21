"""Economic Opportunity Value Model.
Calculates authentic expected economic value for prospective business opportunities:

Expected Value (EV) =
  (P(conversion) * expected_project_value * expected_margin * P(delivery_success))
  / estimated_acquisition_effort_hours

Grounded in verifiable signals: identity confidence, contact confidence, problem evidence,
service fit, budget likelihood, policy risk, and historical delivery performance.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from packages.projects.prospecting import ObservationType, ProspectData, ResearchObservation


class EconomicFactors(BaseModel):
    identity_confidence: float = Field(ge=0.0, le=1.0, description="Confidence in business identity & web presence")
    contact_confidence: float = Field(ge=0.0, le=1.0, description="Confidence in reaching an authentic decision maker")
    problem_evidence: float = Field(ge=0.0, le=1.0, description="Strength of observable technical pain points")
    service_fit: float = Field(ge=0.0, le=1.0, description="Alignment between client problem and Axion capabilities")
    budget_likelihood: float = Field(ge=0.0, le=1.0, description="Estimated capacity to pay commercial rates")
    urgency: float = Field(ge=0.0, le=1.0, description="Operational urgency or time sensitivity")
    communication_feasibility: float = Field(ge=0.0, le=1.0, description="Feasibility of clean, deliverable outreach")
    policy_risk: float = Field(ge=0.0, le=1.0, description="Compliance, security, or platform terms risk [0=none, 1=high]")
    competition_discount: float = Field(ge=0.0, le=1.0, description="Discount factor for competitive density [0=monopoly, 1=saturated]")


class EconomicValuation(BaseModel):
    prospect_domain: str
    expected_project_value_usd: float
    expected_internal_cost_usd: float
    expected_margin: float
    p_conversion: float
    p_delivery_success: float
    estimated_acquisition_effort_hours: float
    expected_economic_value: float
    factors: EconomicFactors
    qualification_recommendation: str  # "PRIORITY_TARGET", "QUALIFIED", "DEFERRED", "REJECTED"
    rationale: str
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class OpportunityEconomicEvaluator:
    """Calculates grounded economic valuation and priority ranking for business prospects."""

    def evaluate_prospect(
        self,
        prospect: ProspectData,
        historical_delivery_rate: float = 0.95,
        target_hourly_rate_usd: float = 125.0,
    ) -> EconomicValuation:
        # 1. Identity Confidence
        identity_conf = 0.3
        if prospect.website and "." in prospect.website:
            identity_conf += 0.4
        if prospect.business_name and len(prospect.business_name) > 2:
            identity_conf += 0.3
        identity_conf = min(identity_conf, 1.0)

        # 2. Contact Confidence
        contact_conf = 0.1
        if prospect.contact_email and "@" in prospect.contact_email:
            contact_conf = 0.9
            # Corporate domain match
            if prospect.website and prospect.contact_email.split("@")[-1] in prospect.website:
                contact_conf = 1.0
        elif prospect.contact_name:
            contact_conf = 0.5

        # 3. Problem Evidence
        # Weighted by observation provenance (FACT vs INFERENCE vs UNKNOWN)
        fact_count = 0
        inference_count = 0
        for obs in prospect.observations:
            if obs.observation_type == ObservationType.FACT:
                fact_count += 1
            elif obs.observation_type == ObservationType.INFERENCE:
                inference_count += 1

        if prospect.observations:
            raw_evidence = (fact_count * 0.35) + (inference_count * 0.15)
            problem_ev = min(1.0, max(0.2, raw_evidence))
        elif prospect.observed_pain_points:
            problem_ev = min(1.0, 0.2 + (len(prospect.observed_pain_points) * 0.25))
        else:
            problem_ev = 0.15  # Unverified baseline

        # 4. Service Fit & Scope Estimation
        # Check alignment with core technical automation capabilities
        combined_text = (
            f"{prospect.industry} " + " ".join(prospect.observed_pain_points)
            + " ".join(obs.statement for obs in prospect.observations)
        ).lower()

        fit_keywords = ["webhook", "api", "crm", "workflow", "automation", "integration", "n8n", "dashboard", "leads"]
        matched_keywords = [k for k in fit_keywords if k in combined_text]
        service_fit = min(1.0, 0.3 + (len(matched_keywords) * 0.2))

        # 5. Budget Likelihood based on business maturity indicators
        budget_likelihood = 0.5  # Standard commercial default
        high_budget_indicators = ["enterprise", "logistics", "fintech", "healthcare", "saas", "b2b"]
        if any(ind in prospect.industry.lower() or ind in combined_text for ind in high_budget_indicators):
            budget_likelihood = 0.8
        if any(term in combined_text for term in ["nonprofit", "hobby", "student"]):
            budget_likelihood = 0.2

        # 6. Urgency & Feasibility
        urgency = 0.5
        if any(u in combined_text for u in ["broken", "failing", "immediate", "bottleneck", "manual error"]):
            urgency = 0.85

        comm_feasibility = 0.8 if contact_conf >= 0.5 else 0.3
        policy_risk = 0.05  # Low baseline policy risk for standard commercial software
        comp_discount = 0.20  # Baseline competitive pressure

        factors = EconomicFactors(
            identity_confidence=round(identity_conf, 2),
            contact_confidence=round(contact_conf, 2),
            problem_evidence=round(problem_ev, 2),
            service_fit=round(service_fit, 2),
            budget_likelihood=round(budget_likelihood, 2),
            urgency=round(urgency, 2),
            communication_feasibility=round(comm_feasibility, 2),
            policy_risk=round(policy_risk, 2),
            competition_discount=round(comp_discount, 2),
        )

        # 7. Probability of Conversion
        # Composite of contactability, need strength, service fit, budget, and risk discount
        p_conv_raw = (
            (factors.contact_confidence * 0.35)
            + (factors.problem_evidence * 0.25)
            + (factors.service_fit * 0.20)
            + (factors.budget_likelihood * 0.15)
            + (factors.urgency * 0.05)
        ) * (1.0 - factors.policy_risk) * (1.0 - factors.competition_discount)

        p_conversion = max(0.01, min(round(p_conv_raw, 3), 0.95))

        # 8. Project Value & Effort Estimation
        # Typical scope tiers:
        # Simple automation/webhook: 4-6h ($500-$750)
        # Moderate integration/dashboard: 8-12h ($1000-$1500)
        # Complex multi-skill workflow: 14-20h ($1750-$2500)
        if len(matched_keywords) >= 3:
            estimated_eng_hours = 12.0
        elif len(matched_keywords) >= 1:
            estimated_eng_hours = 6.0
        else:
            estimated_eng_hours = 4.0

        expected_value_usd = round(estimated_eng_hours * target_hourly_rate_usd, 2)
        # Compute cost basis: tool/token cost (~$3.50/hour of agent work)
        expected_cost_usd = round(estimated_eng_hours * 3.50, 2)
        expected_margin = round((expected_value_usd - expected_cost_usd) / expected_value_usd, 3)

        # Acquisition effort: outreach preparation + conversational requirements + proposal (1.0 - 2.5 hours)
        acquisition_effort_hours = 1.0 if factors.contact_confidence >= 0.8 else 2.0

        p_delivery = max(0.5, min(1.0, historical_delivery_rate))

        # 9. Expected Economic Value (Net EV per acquisition effort hour)
        expected_economic_value = round(
            (p_conversion * expected_value_usd * expected_margin * p_delivery)
            / acquisition_effort_hours,
            2,
        )

        # 10. Qualification Recommendation
        if factors.policy_risk > 0.5 or factors.identity_confidence < 0.3:
            recommendation = "REJECTED"
            rationale = "High policy risk or unverified business identity."
        elif expected_economic_value >= 150.0 and p_conversion >= 0.3:
            recommendation = "PRIORITY_TARGET"
            rationale = (
                f"High expected yield (${expected_economic_value:.2f}/effort-hr) "
                f"with strong conversion probability ({p_conversion * 100:.1f}%)."
            )
        elif expected_economic_value >= 60.0:
            recommendation = "QUALIFIED"
            rationale = (
                f"Solid commercial prospect (${expected_economic_value:.2f}/effort-hr) "
                f"ready for personalized outreach."
            )
        else:
            recommendation = "DEFERRED"
            rationale = (
                f"Low expected return (${expected_economic_value:.2f}/effort-hr). "
                "Recommend deeper signal gathering or prioritizing higher-yield targets."
            )

        return EconomicValuation(
            prospect_domain=prospect.website or "unknown_domain",
            expected_project_value_usd=expected_value_usd,
            expected_internal_cost_usd=expected_cost_usd,
            expected_margin=expected_margin,
            p_conversion=p_conversion,
            p_delivery_success=p_delivery,
            estimated_acquisition_effort_hours=acquisition_effort_hours,
            expected_economic_value=expected_economic_value,
            factors=factors,
            qualification_recommendation=recommendation,
            rationale=rationale,
        )


economic_evaluator = OpportunityEconomicEvaluator()
