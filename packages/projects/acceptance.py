"""Project Acceptance & Negotiation Engine.
Calculates technical complexity, effort, risk, profitability, and makes deterministic decisions:
ACCEPT, REJECT, NEEDS_INFORMATION, ESCALATE.
"""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field

from packages.shared.config import settings


class AcceptanceDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    NEEDS_INFORMATION = "NEEDS_INFORMATION"
    ESCALATE = "ESCALATE"


class ProjectAssessmentRequest(BaseModel):
    title: str
    description: str
    requested_price: float = Field(default=0.0)
    estimated_effort_hours: float = Field(default=4.0)
    integration_count: int = Field(default=1)
    has_unsupported_scope: bool = False
    requires_security_bypass: bool = False
    deadline_days: int = Field(default=7)
    known_requirements: List[str] = Field(default_factory=list)


class ProjectAssessmentResult(BaseModel):
    decision: AcceptanceDecision
    technical_complexity: float  # [0.0 - 1.0]
    profitability: float         # [0.0 - 1.0]
    success_probability: float   # [0.0 - 1.0]
    quoted_price: float
    max_revisions: int
    reasons: List[str]


class ProjectAcceptanceEngine:
    def __init__(self):
        self.min_price = settings.MIN_PROJECT_PRICE
        self.max_discount = settings.MAX_DISCOUNT_PERCENT
        self.min_profit_margin = settings.MIN_PROFIT_MARGIN

    def evaluate(self, req: ProjectAssessmentRequest) -> ProjectAssessmentResult:
        reasons = []

        # Immediate Rejection criteria (Directives 13, 18, 151)
        if req.requires_security_bypass:
            return ProjectAssessmentResult(
                decision=AcceptanceDecision.REJECT,
                technical_complexity=1.0,
                profitability=0.0,
                success_probability=0.0,
                quoted_price=0.0,
                max_revisions=0,
                reasons=["Security policy violation: Request attempts to bypass platform security or authentication."],
            )

        if req.has_unsupported_scope:
            return ProjectAssessmentResult(
                decision=AcceptanceDecision.REJECT,
                technical_complexity=0.95,
                profitability=0.1,
                success_probability=0.1,
                quoted_price=0.0,
                max_revisions=0,
                reasons=["Scope rejected: Requires massive SaaS migration or unsupported multi-month architecture."],
            )

        # Insufficient requirements
        if len(req.known_requirements) < 2 and len(req.description.split()) < 10:
            return ProjectAssessmentResult(
                decision=AcceptanceDecision.NEEDS_INFORMATION,
                technical_complexity=0.5,
                profitability=0.5,
                success_probability=0.4,
                quoted_price=self.min_price,
                max_revisions=1,
                reasons=["Requirements are underspecified. Detailed acceptance criteria must be gathered."],
            )

        # Calculate technical complexity
        complexity = 0.2 + (req.integration_count * 0.15) + (req.estimated_effort_hours * 0.03)
        complexity = min(round(complexity, 2), 1.0)

        # Feasibility & Profitability calculations
        base_hourly_rate = 50.0  # $50/hour internal valuation
        estimated_cost = req.estimated_effort_hours * base_hourly_rate
        suggested_price = max(self.min_price, estimated_cost * 1.5)

        # If client requested specific price below minimum
        if req.requested_price > 0 and req.requested_price < self.min_price:
            reasons.append(f"Offered price ${req.requested_price:.2f} is below minimum threshold ${self.min_price:.2f}")
            return ProjectAssessmentResult(
                decision=AcceptanceDecision.REJECT,
                technical_complexity=complexity,
                profitability=0.0,
                success_probability=0.2,
                quoted_price=suggested_price,
                max_revisions=2,
                reasons=reasons,
            )

        # Deadline pressure check
        if req.deadline_days < 1 and req.estimated_effort_hours > 4:
            return ProjectAssessmentResult(
                decision=AcceptanceDecision.ESCALATE,
                technical_complexity=complexity,
                profitability=0.6,
                success_probability=0.3,
                quoted_price=suggested_price * 1.3,
                max_revisions=1,
                reasons=["High risk deadline pressure (< 24 hours for multi-hour deliverable). Escalating to operator."],
            )

        # Profitability score
        profitability = min(round((suggested_price - estimated_cost) / suggested_price, 2), 1.0)
        success_prob = max(round(1.0 - (complexity * 0.4), 2), 0.3)

        final_price = max(suggested_price, req.requested_price)

        return ProjectAssessmentResult(
            decision=AcceptanceDecision.ACCEPT,
            technical_complexity=complexity,
            profitability=profitability,
            success_probability=success_prob,
            quoted_price=final_price,
            max_revisions=2,  # Strict negotiation policy limit
            reasons=["Project passes all feasibility, profitability, and security criteria."],
        )


# Global singleton
project_acceptance_engine = ProjectAcceptanceEngine()
