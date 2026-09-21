"""Unit tests for the Logical Agent Capability System."""

import pytest
from packages.agent.capabilities import (
    AgentCapabilityProfile,
    AgentCapabilityRegistry,
    AgentDomain,
    agent_registry,
)


def test_agent_registry_initialization():
    agents = agent_registry.list_agents()
    assert len(agents) >= 15

    research_agents = agent_registry.list_agents(AgentDomain.RESEARCH)
    assert len(research_agents) >= 3
    assert any(a.agent_id == "business_research_agent" for a in research_agents)

    sales_agents = agent_registry.list_agents(AgentDomain.SALES)
    assert len(sales_agents) >= 5
    assert any(a.agent_id == "negotiation_agent" for a in sales_agents)

    engineering_agents = agent_registry.list_agents(AgentDomain.ENGINEERING)
    assert len(engineering_agents) >= 4
    assert any(a.agent_id == "backend_agent" for a in engineering_agents)

    qa_agents = agent_registry.list_agents(AgentDomain.QA)
    assert len(qa_agents) >= 3
    assert any(a.agent_id == "functional_qa_agent" for a in qa_agents)

    business_agents = agent_registry.list_agents(AgentDomain.BUSINESS)
    assert len(business_agents) >= 3
    assert any(a.agent_id == "revenue_agent" for a in business_agents)


def test_agent_resolution_for_skills():
    # Skill resolution
    agent = agent_registry.resolve_agent_for_task("build_webhook_integration")
    assert agent.agent_id == "backend_agent"
    assert agent.domain == AgentDomain.ENGINEERING

    agent_qa = agent_registry.resolve_agent_for_task("qa_project_deliverable")
    assert agent_qa.agent_id in ("functional_qa_agent", "security_qa_agent", "browser_qa_agent")

    agent_n8n = agent_registry.resolve_agent_for_task("build_n8n_automation")
    assert agent_n8n.agent_id == "automation_agent"


def test_find_agents_for_capability():
    pricing_agents = agent_registry.find_agents_for_capability("pricing")
    assert len(pricing_agents) >= 1
    assert pricing_agents[0].agent_id == "pricing_agent"

    security_agents = agent_registry.find_agents_for_capability("security")
    assert len(security_agents) >= 1
    assert any(a.agent_id == "security_qa_agent" for a in security_agents)
