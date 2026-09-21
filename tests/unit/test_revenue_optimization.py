"""Unit tests for the Revenue Optimization & Funnel Analytics Engine."""

import pytest
from packages.projects.revenue import (
    FunnelBottleneckDiagnosis,
    FunnelConversionRates,
    FunnelMetrics,
    RevenueOptimizationEngine,
    revenue_optimization_engine,
)


def test_conversion_rates_calculation():
    engine = RevenueOptimizationEngine()
    m = FunnelMetrics(
        leads_discovered=100,
        leads_qualified=60,
        outreach_dispatched=50,
        inbound_replies=15,
        requirements_completed=10,
        quotes_generated=10,
        payments_verified=5,
        projects_completed=5,
        gross_revenue_usd=6000.0,
        trailing_7d_revenue_usd=1200.0,
    )

    rates = engine.calculate_conversion_rates(m)
    assert rates.qualification_rate == 0.60
    assert rates.response_rate == 0.30
    assert rates.scoping_rate == 0.667
    assert rates.quote_acceptance_rate == 0.50
    assert rates.delivery_success_rate == 1.0


def test_diagnose_low_top_of_funnel():
    engine = RevenueOptimizationEngine()
    m = FunnelMetrics(leads_discovered=4)
    rates = engine.calculate_conversion_rates(m)
    diag = engine.diagnose_funnel_bottlenecks(rates, m)

    assert diag.primary_bottleneck == "TOP_OF_FUNNEL_INSUFFICIENT"
    assert diag.severity == "CRITICAL"
    assert len(diag.actionable_recommendations) >= 1


def test_diagnose_low_outreach_response():
    engine = RevenueOptimizationEngine()
    m = FunnelMetrics(
        leads_discovered=50,
        leads_qualified=30,
        outreach_dispatched=20,
        inbound_replies=1,  # 5% response rate
    )
    rates = engine.calculate_conversion_rates(m)
    diag = engine.diagnose_funnel_bottlenecks(rates, m)

    assert diag.primary_bottleneck == "LOW_OUTREACH_RESPONSE_RATE"
    assert diag.severity == "WARNING"


def test_diagnose_healthy_funnel():
    engine = RevenueOptimizationEngine()
    m = FunnelMetrics(
        leads_discovered=40,
        leads_qualified=25,
        outreach_dispatched=20,
        inbound_replies=5,
        requirements_completed=4,
        quotes_generated=4,
        payments_verified=2,
        projects_completed=2,
        trailing_7d_revenue_usd=1350.0,
    )
    rates = engine.calculate_conversion_rates(m)
    diag = engine.diagnose_funnel_bottlenecks(rates, m)

    assert diag.primary_bottleneck == "NONE"
    assert diag.severity == "HEALTHY"
