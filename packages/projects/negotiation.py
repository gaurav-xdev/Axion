"""Bounded Negotiation and Requirements Extraction Engine.
Extracts structured deliverables, acceptance criteria, constraints, and enforces
strict commercial boundaries (pricing floors, maximum discounts, revision limits).
"""

from datetime import datetime, timedelta, timezone
from enum import Enum
import re
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field
from sqlalchemy import select

from packages.observability.logger import logger
from packages.projects.acceptance import AcceptanceDecision, project_acceptance_engine
from packages.shared.config import settings
from packages.shared.database import async_session_factory
from packages.shared.models import (
    Client,
    Project,
    ProjectStatus,
    Quote,
    Requirement,
    utc_now,
)


class NegotiationDecision(str, Enum):
    ACCEPT_TERMS = "ACCEPT_TERMS"
    COUNTER_OFFER = "COUNTER_OFFER"
    REJECT_PRICE_FLOOR = "REJECT_PRICE_FLOOR"
    REJECT_EXCESSIVE_REVISIONS = "REJECT_EXCESSIVE_REVISIONS"
    ESCALATE_TO_OPERATOR = "ESCALATE_TO_OPERATOR"


class ExtractedRequirements(BaseModel):
    project_title: str
    project_type: str  # AUTOMATION, INTEGRATION, WEBHOOK, FRONTEND, DASHBOARD
    deliverables: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)
    technical_constraints: List[str] = Field(default_factory=list)
    unresolved_unknowns: List[str] = Field(default_factory=list)
    tagged_requirements: List[Dict[str, str]] = Field(default_factory=list)
    estimated_integration_count: int = 1
    estimated_effort_hours: float = 4.0
    ready_for_quote: bool = True


class NegotiationResult(BaseModel):
    decision: NegotiationDecision
    original_price: float
    final_offered_price: float
    effective_discount_pct: float
    max_revisions: int
    turnaround_days: int
    scope_adjustment: Optional[str] = None
    response_narrative: str


class RequirementsExtractor:
    """Extracts structured engineering deliverables and criteria from client messages."""

    def extract(self, client_text: str, context: Optional[Dict[str, Any]] = None) -> ExtractedRequirements:
        text_lower = client_text.lower()
        ctx = context or {}

        # 1. Determine Project Type
        if any(w in text_lower for w in ["n8n", "crm sync", "workflow", "automate"]):
            proj_type = "AUTOMATION"
            title = "n8n Workflow & CRM Sync Automation"
        elif any(w in text_lower for w in ["webhook", "hmac", "callback", "receiver"]):
            proj_type = "WEBHOOK"
            title = "Secure Serverless Webhook Handler"
        elif any(w in text_lower for w in ["api client", "rest api", "api integration"]):
            proj_type = "INTEGRATION"
            title = "Robust REST API Client Integration"
        elif any(w in text_lower for w in ["dashboard", "metrics", "analytics display"]):
            proj_type = "DASHBOARD"
            title = "Operational Business Metrics Dashboard"
        elif any(w in text_lower for w in ["landing page", "html", "tailwind", "website"]):
            proj_type = "FRONTEND"
            title = "Responsive Conversion Landing Page"
        else:
            proj_type = "AUTOMATION"
            title = ctx.get("title") or "Business Workflow Automation"

        # 2. Extract Deliverables with Certainty Tagging
        deliverables: List[str] = []
        tagged_requirements: List[Dict[str, str]] = []

        if proj_type == "AUTOMATION":
            deliverables.append("Production-ready n8n workflow JSON configuration")
            tagged_requirements.append({
                "title": "n8n Workflow Configuration",
                "description": "Production-ready n8n workflow JSON configuration",
                "certainty": "CLIENT_STATED",
            })
            deliverables.append("Tested webhook inbound trigger and payload transformer")
            tagged_requirements.append({
                "title": "Inbound Webhook Trigger",
                "description": "Tested webhook inbound trigger and payload transformer",
                "certainty": "INFERRED",
            })
            deliverables.append("Error notification dispatch handler")
            tagged_requirements.append({
                "title": "Error Dispatch Handler",
                "description": "Error notification dispatch handler",
                "certainty": "INFERRED",
            })
        elif proj_type == "WEBHOOK":
            deliverables.append("FastAPI production webhook route handler")
            tagged_requirements.append({
                "title": "FastAPI Webhook Route",
                "description": "FastAPI production webhook route handler",
                "certainty": "CLIENT_STATED",
            })
            deliverables.append("Cryptographic HMAC SHA-256 signature verification")
            tagged_requirements.append({
                "title": "HMAC SHA-256 Verification",
                "description": "Cryptographic HMAC SHA-256 signature verification",
                "certainty": "INFERRED",
            })
            deliverables.append("Sandbox integration test verifying valid and rejected signatures")
            tagged_requirements.append({
                "title": "Sandbox Verification Suite",
                "description": "Sandbox integration test verifying valid and rejected signatures",
                "certainty": "ASSUMED",
            })
        elif proj_type == "INTEGRATION":
            deliverables.append("Async Python httpx client with connection pooling and retries")
            tagged_requirements.append({
                "title": "Async REST Client",
                "description": "Async Python httpx client with connection pooling and retries",
                "certainty": "CLIENT_STATED",
            })
            deliverables.append("Authentication header injection and token refresh logic")
            tagged_requirements.append({
                "title": "Auth Header Injection",
                "description": "Authentication header injection and token refresh logic",
                "certainty": "INFERRED",
            })
            deliverables.append("Comprehensive error handling and status code mapping")
            tagged_requirements.append({
                "title": "Error Handling & Status Mapping",
                "description": "Comprehensive error handling and status code mapping",
                "certainty": "INFERRED",
            })
        elif proj_type == "FRONTEND":
            deliverables.append("Clean semantic HTML5 / Tailwind responsive page")
            tagged_requirements.append({
                "title": "Semantic HTML5 Page",
                "description": "Clean semantic HTML5 / Tailwind responsive page",
                "certainty": "CLIENT_STATED",
            })
            deliverables.append("Mobile-first viewport layout with conversion CTA")
            tagged_requirements.append({
                "title": "Mobile Viewport Layout",
                "description": "Mobile-first viewport layout with conversion CTA",
                "certainty": "INFERRED",
            })
            deliverables.append("Zero placeholder markers or broken assets")
            tagged_requirements.append({
                "title": "Asset Integrity",
                "description": "Zero placeholder markers or broken assets",
                "certainty": "ASSUMED",
            })
        elif proj_type == "DASHBOARD":
            deliverables.append("Interactive dashboard layout JSON specification")
            tagged_requirements.append({
                "title": "Dashboard Specification",
                "description": "Interactive dashboard layout JSON specification",
                "certainty": "CLIENT_STATED",
            })
            deliverables.append("Metric widget configurations and refresh schedules")
            tagged_requirements.append({
                "title": "Metric Widgets",
                "description": "Metric widget configurations and refresh schedules",
                "certainty": "INFERRED",
            })

        # 3. Define Acceptance Criteria
        criteria: List[str] = [
            "Passes 5-layer adversarial QA verification with zero critical findings",
            "Artifact code parses cleanly with Python AST and compiles without syntax errors",
            "Contains zero unfinished TODO/FIXME placeholder markers",
            "Includes SHA-256 verifiable manifest bundle",
        ]

        # 4. Extract Constraints & Unknowns
        constraints: List[str] = []
        unknowns: List[str] = []

        if "immediately" in text_lower or "today" in text_lower:
            constraints.append("Urgent delivery timeframe requested")
        else:
            constraints.append("Standard 3-5 business day delivery window")

        # Identify missing specifications
        if proj_type == "INTEGRATION" and not any(k in text_lower for k in ["stripe", "hubspot", "airtable", "salesforce", "api"]):
            unknowns.append("Target API documentation URL and authentication mechanism")
            tagged_requirements.append({
                "title": "Target API Documentation",
                "description": "Missing target API documentation URL and authentication credentials",
                "certainty": "UNKNOWN",
            })
        if proj_type == "WEBHOOK" and "secret" not in text_lower:
            unknowns.append("Webhook provider signature header name and hashing algorithm")
            tagged_requirements.append({
                "title": "Webhook Secret Specification",
                "description": "Missing signature header name and secret key environment variable",
                "certainty": "UNKNOWN",
            })

        # Estimate integration count and effort
        integrations = 1
        if "and" in text_lower or "," in text_lower:
            integrations = min(4, 1 + text_lower.count("and") + text_lower.count(","))
        base_effort = 4.0 if proj_type in ("AUTOMATION", "WEBHOOK", "FRONTEND") else 6.0
        effort = base_effort + (integrations - 1) * 2.5

        ready = len(unknowns) == 0

        return ExtractedRequirements(
            project_title=title,
            project_type=proj_type,
            deliverables=deliverables,
            acceptance_criteria=criteria,
            technical_constraints=constraints,
            unresolved_unknowns=unknowns,
            tagged_requirements=tagged_requirements,
            estimated_integration_count=integrations,
            estimated_effort_hours=effort,
            ready_for_quote=ready,
        )


class BoundedNegotiationEngine:
    """Enforces deterministic commercial policy bounds on pricing, revisions, and deadlines."""

    def __init__(
        self,
        min_price: Optional[float] = None,
        max_discount_pct: Optional[float] = None,
        max_revisions: int = 2,
    ):
        self.min_price = min_price or settings.MIN_PROJECT_PRICE
        self.max_discount_pct = max_discount_pct or settings.MAX_DISCOUNT_PERCENT
        self.max_revisions = max_revisions

    def evaluate_commercial_terms(
        self,
        base_quoted_price: float,
        client_offered_price: Optional[float] = None,
        client_requested_revisions: Optional[int] = None,
        client_requested_days: Optional[int] = None,
    ) -> NegotiationResult:
        """Evaluates client offer against non-negotiable policy bounds."""
        target_price = client_offered_price if client_offered_price is not None and client_offered_price > 0 else base_quoted_price
        revisions = client_requested_revisions if client_requested_revisions is not None else self.max_revisions
        days = client_requested_days if client_requested_days is not None else 5

        # 1. Price Floor Violation Check
        if target_price < self.min_price:
            logger.warning(f"Negotiation floor breach: offer ${target_price:.2f} < floor ${self.min_price:.2f}")
            narrative = (
                f"Thank you for the counter-proposal. Our platform policy establishes a fixed minimum investment "
                f"of ${self.min_price:.2f} USD to cover dedicated engineering, infrastructure, and 5-layer adversarial QA. "
                f"We can deliver the core scope for ${self.min_price:.2f}."
            )
            return NegotiationResult(
                decision=NegotiationDecision.REJECT_PRICE_FLOOR,
                original_price=base_quoted_price,
                final_offered_price=self.min_price,
                effective_discount_pct=round(((base_quoted_price - self.min_price) / base_quoted_price) * 100, 1),
                max_revisions=self.max_revisions,
                turnaround_days=max(days, 3),
                scope_adjustment="Adjusted scope to core critical deliverable to match platform price floor.",
                response_narrative=narrative,
            )

        # 2. Maximum Discount Check
        requested_discount = ((base_quoted_price - target_price) / base_quoted_price) * 100
        if requested_discount > self.max_discount_pct:
            capped_price = round(base_quoted_price * (1.0 - (self.max_discount_pct / 100.0)), 2)
            logger.info(f"Discount capped: requested {requested_discount:.1f}% > allowed {self.max_discount_pct:.1f}%")
            narrative = (
                f"We want to work within your budget. While we cannot offer {requested_discount:.0f}% off the full package, "
                f"we can provide a maximum courtesy discount of {self.max_discount_pct:.0f}%, bringing the total to "
                f"${capped_price:,.2f} USD with all quality benchmarks preserved."
            )
            return NegotiationResult(
                decision=NegotiationDecision.COUNTER_OFFER,
                original_price=base_quoted_price,
                final_offered_price=capped_price,
                effective_discount_pct=self.max_discount_pct,
                max_revisions=self.max_revisions,
                turnaround_days=max(days, 3),
                scope_adjustment="Full scope maintained with maximum authorized margin discount.",
                response_narrative=narrative,
            )

        # 3. Revision Limit Check (Strict Cap = 2)
        if revisions > self.max_revisions:
            narrative = (
                f"To maintain fixed delivery timelines and quality guarantees, all projects include up to "
                f"{self.max_revisions} structured revision rounds. Any additional revisions beyond {self.max_revisions} "
                f"are billed separately at standard engineering hourly rates."
            )
            return NegotiationResult(
                decision=NegotiationDecision.REJECT_EXCESSIVE_REVISIONS,
                original_price=base_quoted_price,
                final_offered_price=target_price,
                effective_discount_pct=max(0.0, requested_discount),
                max_revisions=self.max_revisions,
                turnaround_days=max(days, 3),
                scope_adjustment=f"Revisions bounded to maximum {self.max_revisions} cycles.",
                response_narrative=narrative,
            )

        # 4. Turnaround Emergency (< 24 hours on multi-hour job)
        if days < 1:
            rush_price = round(target_price * 1.25, 2)
            narrative = (
                f"For urgent same-day turnaround (< 24 hours), a 25% expedited priority surcharge applies. "
                f"Expedited total: ${rush_price:,.2f} USD."
            )
            return NegotiationResult(
                decision=NegotiationDecision.ESCALATE_TO_OPERATOR,
                original_price=base_quoted_price,
                final_offered_price=rush_price,
                effective_discount_pct=0.0,
                max_revisions=1,
                turnaround_days=1,
                scope_adjustment="Expedited single-day emergency delivery schedule.",
                response_narrative=narrative,
            )

        # 5. Terms Accepted within bounds
        narrative = (
            f"We agree to the proposed terms of ${target_price:,.2f} USD. "
            f"Delivery timeline is confirmed for {days} business days with {self.max_revisions} revision rounds."
        )
        return NegotiationResult(
            decision=NegotiationDecision.ACCEPT_TERMS,
            original_price=base_quoted_price,
            final_offered_price=target_price,
            effective_discount_pct=max(0.0, requested_discount),
            max_revisions=self.max_revisions,
            turnaround_days=days,
            response_narrative=narrative,
        )

    async def create_authoritative_quote(
        self,
        project_id: str,
        client_id: str,
        amount: float,
        scope_summary: str,
        requirements: List[str],
        max_revisions: int = 2,
        valid_days: int = 7,
    ) -> Quote:
        """Persists authoritative Quote and Requirements into database."""
        async with async_session_factory() as session:
            quote = Quote(
                project_id=project_id,
                client_id=client_id,
                amount=amount,
                currency="USD",
                scope_summary=scope_summary,
                max_revisions=max_revisions,
                expires_at=utc_now() + timedelta(days=valid_days),
                status="PENDING",
            )
            session.add(quote)

            # Persist individual requirements with certainty
            for idx, req_item in enumerate(requirements):
                if isinstance(req_item, dict):
                    title = req_item.get("title", f"Requirement {idx + 1}")
                    desc = req_item.get("description", str(req_item))
                    certainty = req_item.get("certainty", "CLIENT_STATED")
                else:
                    title = f"Requirement {idx + 1}"
                    desc = str(req_item)
                    certainty = "CLIENT_STATED"

                req_row = Requirement(
                    project_id=project_id,
                    title=title,
                    description=desc,
                    priority="HIGH",
                    certainty=certainty,
                    acceptance_criteria=[f"Verified: {desc}"],
                    status="PENDING",
                )
                session.add(req_row)

            # Update Project status to QUOTE_SENT
            proj = await session.get(Project, project_id)
            if proj:
                proj.status = ProjectStatus.QUOTE_SENT
                proj.accepted_price = amount

            await session.commit()
            await session.refresh(quote)
            return quote


# Global singletons
requirements_extractor = RequirementsExtractor()
negotiation_engine = BoundedNegotiationEngine()
