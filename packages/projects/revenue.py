"""Revenue Optimization & Commercial Funnel Analytics Engine.
Tracks the end-to-end commercial pipeline and analyzes conversion leakage:
Leads Discovered -> Qualified -> Contacted -> Inbound Reply -> Scoped -> Quoted -> Paid -> Delivered.
Diagnoses operational bottlenecks and provides automated strategic recommendations
to legitimately pursue the $1,200–$1,500/week revenue target.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from packages.observability.logger import logger
from packages.shared.database import async_session_factory
from packages.shared.models import (
    Contact,
    Message,
    Payment,
    PaymentStatus,
    Project,
    ProjectStatus,
    Prospect,
    Quote,
    Requirement,
)

TARGET_WEEKLY_REVENUE_USD = 1200.0


class FunnelMetrics(BaseModel):
    leads_discovered: int = 0
    leads_qualified: int = 0
    contacts_identified: int = 0
    outreach_dispatched: int = 0
    inbound_replies: int = 0
    requirements_completed: int = 0
    quotes_generated: int = 0
    payments_verified: int = 0
    projects_completed: int = 0
    repeat_projects: int = 0
    gross_revenue_usd: float = 0.0
    trailing_7d_revenue_usd: float = 0.0
    target_weekly_revenue_usd: float = TARGET_WEEKLY_REVENUE_USD
    weekly_pacing_pct: float = 0.0


class FunnelConversionRates(BaseModel):
    qualification_rate: float = 0.0      # qualified / discovered
    response_rate: float = 0.0           # replies / outreach
    scoping_rate: float = 0.0            # scoped / replies
    quote_acceptance_rate: float = 0.0   # payments / quotes
    delivery_success_rate: float = 0.0   # completed / payments
    repeat_client_rate: float = 0.0      # repeat / completed


class FunnelBottleneckDiagnosis(BaseModel):
    primary_bottleneck: str
    severity: str  # "CRITICAL", "WARNING", "HEALTHY"
    diagnosis_text: str
    actionable_recommendations: List[str]


class RevenueOptimizationEngine:
    """Authoritative engine driving commercial funnel analytics and revenue optimization."""

    async def compute_funnel_metrics(self, window_days: int = 30) -> FunnelMetrics:
        """Queries authoritative database to measure real funnel velocity and conversion counts."""
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=window_days)
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)

        async with async_session_factory() as session:
            # 1. Leads
            disc_stmt = select(func.count(Prospect.id)).where(Prospect.created_at >= cutoff_date)
            leads_discovered = int((await session.execute(disc_stmt)).scalar() or 0)

            qual_stmt = select(func.count(Prospect.id)).where(
                Prospect.created_at >= cutoff_date,
                Prospect.status.in_(["QUALIFIED", "CONTACTED", "CONVERTED"]),
            )
            leads_qualified = int((await session.execute(qual_stmt)).scalar() or 0)

            # 2. Contacts & Outreach
            contact_stmt = select(func.count(Contact.id)).where(Contact.created_at >= cutoff_date)
            contacts_count = int((await session.execute(contact_stmt)).scalar() or 0)

            outreach_stmt = select(func.count(Prospect.id)).where(
                Prospect.last_contacted_at >= cutoff_date
            )
            outreach_count = int((await session.execute(outreach_stmt)).scalar() or 0)

            # 3. Inbound Replies
            reply_stmt = select(func.count(Message.id)).where(
                Message.created_at >= cutoff_date,
                Message.direction == "INBOUND",
            )
            inbound_replies = int((await session.execute(reply_stmt)).scalar() or 0)

            # 4. Requirements & Quotes
            req_stmt = select(func.count(func.distinct(Requirement.project_id))).where(
                Requirement.created_at >= cutoff_date
            )
            reqs_completed = int((await session.execute(req_stmt)).scalar() or 0)

            quote_stmt = select(func.count(Quote.id)).where(Quote.created_at >= cutoff_date)
            quotes_count = int((await session.execute(quote_stmt)).scalar() or 0)

            # 5. Verified Payments & Revenue
            pay_stmt = select(func.count(Payment.id), func.coalesce(func.sum(Payment.amount), 0.0)).where(
                Payment.created_at >= cutoff_date,
                Payment.status == PaymentStatus.PAID,
            )
            pay_res = (await session.execute(pay_stmt)).first()
            payments_verified = int(pay_res[0] or 0) if pay_res else 0
            gross_revenue = float(pay_res[1] or 0.0) if pay_res else 0.0

            # 7-day revenue pacing
            rev_7d_stmt = select(func.coalesce(func.sum(Payment.amount), 0.0)).where(
                Payment.created_at >= seven_days_ago,
                Payment.status == PaymentStatus.PAID,
            )
            revenue_7d = float((await session.execute(rev_7d_stmt)).scalar() or 0.0)

            # 6. Projects Completed
            comp_stmt = select(func.count(Project.id)).where(
                Project.updated_at >= cutoff_date,
                Project.status == ProjectStatus.COMPLETED,
            )
            projects_completed = int((await session.execute(comp_stmt)).scalar() or 0)

            pacing_pct = round((revenue_7d / TARGET_WEEKLY_REVENUE_USD) * 100, 1)

            return FunnelMetrics(
                leads_discovered=leads_discovered,
                leads_qualified=leads_qualified,
                contacts_identified=contacts_count,
                outreach_dispatched=outreach_count,
                inbound_replies=inbound_replies,
                requirements_completed=reqs_completed,
                quotes_generated=quotes_count,
                payments_verified=payments_verified,
                projects_completed=projects_completed,
                gross_revenue_usd=gross_revenue,
                trailing_7d_revenue_usd=revenue_7d,
                target_weekly_revenue_usd=TARGET_WEEKLY_REVENUE_USD,
                weekly_pacing_pct=pacing_pct,
            )

    def calculate_conversion_rates(self, m: FunnelMetrics) -> FunnelConversionRates:
        """Calculates stage-by-stage conversion efficiencies."""
        qual_rate = round(m.leads_qualified / m.leads_discovered, 3) if m.leads_discovered > 0 else 0.0
        resp_rate = round(m.inbound_replies / m.outreach_dispatched, 3) if m.outreach_dispatched > 0 else 0.0
        scope_rate = round(m.requirements_completed / m.inbound_replies, 3) if m.inbound_replies > 0 else 0.0
        quote_rate = round(m.payments_verified / m.quotes_generated, 3) if m.quotes_generated > 0 else 0.0
        deliv_rate = round(m.projects_completed / m.payments_verified, 3) if m.payments_verified > 0 else 1.0

        return FunnelConversionRates(
            qualification_rate=qual_rate,
            response_rate=resp_rate,
            scoping_rate=scope_rate,
            quote_acceptance_rate=quote_rate,
            delivery_success_rate=deliv_rate,
            repeat_client_rate=0.0,
        )

    def diagnose_funnel_bottlenecks(
        self,
        rates: FunnelConversionRates,
        metrics: FunnelMetrics,
    ) -> FunnelBottleneckDiagnosis:
        """Identifies primary conversion constraints and issues actionable optimizations."""
        recs: List[str] = []

        # Leak 1: Top of funnel dry
        if metrics.leads_discovered < 10:
            return FunnelBottleneckDiagnosis(
                primary_bottleneck="TOP_OF_FUNNEL_INSUFFICIENT",
                severity="CRITICAL",
                diagnosis_text="Insufficient new business discovery activity to sustain $1,200-$1,500/week pacing.",
                actionable_recommendations=[
                    "Expand permitted directory and public domain scanning sources",
                    "Lower minimum qualification discovery threshold slightly to surface more candidates",
                ],
            )

        # Leak 2: Low outreach reply rate
        if metrics.outreach_dispatched >= 5 and rates.response_rate < 0.10:
            return FunnelBottleneckDiagnosis(
                primary_bottleneck="LOW_OUTREACH_RESPONSE_RATE",
                severity="WARNING",
                diagnosis_text=f"Outreach response rate is low ({rates.response_rate * 100:.1f}%). Prospects are not engaging with initial message.",
                actionable_recommendations=[
                    "Increase personalization by citing concrete observed technical pain points",
                    "Verify email deliverability and avoid marketing buzzwords",
                    "Refine subject line to reference specific workflow automation opportunities",
                ],
            )

        # Leak 3: Inbound replies not converting to scoped requirements
        if metrics.inbound_replies >= 3 and rates.scoping_rate < 0.40:
            return FunnelBottleneckDiagnosis(
                primary_bottleneck="SCOPING_CONVERSION_DROP",
                severity="WARNING",
                diagnosis_text=f"Inbound client replies are stalling before technical requirements completion ({rates.scoping_rate * 100:.1f}%).",
                actionable_recommendations=[
                    "Ask targeted clarification questions addressing unknown authentication or payload specs",
                    "Ensure conversation engine responds promptly with concrete technical options",
                ],
            )

        # Leak 4: Quote to Payment drop-off
        if metrics.quotes_generated >= 3 and rates.quote_acceptance_rate < 0.35:
            return FunnelBottleneckDiagnosis(
                primary_bottleneck="QUOTE_PAYMENT_FRICTION",
                severity="WARNING",
                diagnosis_text=f"Quotes are encountering resistance before payment funding ({rates.quote_acceptance_rate * 100:.1f}%).",
                actionable_recommendations=[
                    "Evaluate pricing margin; ensure fixed prices remain competitive within bounded floor",
                    "Emphasize cryptographic 5-layer QA guarantees in proposal deliverables",
                ],
            )

        return FunnelBottleneckDiagnosis(
            primary_bottleneck="NONE",
            severity="HEALTHY",
            diagnosis_text=(
                f"Commercial funnel is operating within target parameters. "
                f"Trailing 7d revenue: ${metrics.trailing_7d_revenue_usd:.2f} ({metrics.weekly_pacing_pct}% of target)."
            ),
            actionable_recommendations=[
                "Maintain continuous discovery and outreach cadence",
                "Monitor delivery QA turnaround to preserve high margin yield",
            ],
        )

    async def get_revenue_intelligence(self, window_days: int = 30) -> Dict[str, Any]:
        """Complete revenue analytics snapshot for the Autonomous Business Manager."""
        metrics = await self.compute_funnel_metrics(window_days)
        rates = self.calculate_conversion_rates(metrics)
        diag = self.diagnose_funnel_bottlenecks(rates, metrics)

        return {
            "metrics": metrics.model_dump(),
            "conversion_rates": rates.model_dump(),
            "bottleneck_diagnosis": diag.model_dump(),
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }


revenue_optimization_engine = RevenueOptimizationEngine()
