"""Authoritative Logical Agent Capability System.
Provides structured capability discovery, agent selection, skill mapping, and policy boundaries
for specialized logical agent roles across Research, Sales, Engineering, QA, and Business domains.

Does NOT instantiate 100 concurrent OS processes or LLM instances; instead provides formal
deterministic routing, role-bound permissions, and skill composition.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from packages.shared.models import ToolRiskLevel


class AgentDomain(str, Enum):
    RESEARCH = "RESEARCH"
    SALES = "SALES"
    ENGINEERING = "ENGINEERING"
    QA = "QA"
    BUSINESS = "BUSINESS"


class AgentCapabilityProfile(BaseModel):
    agent_id: str
    name: str
    domain: AgentDomain
    description: str
    capabilities: List[str] = Field(default_factory=list)
    allowed_skills: List[str] = Field(default_factory=list)
    allowed_tools: List[str] = Field(default_factory=list)
    risk_level: ToolRiskLevel = ToolRiskLevel.LOW
    required_permissions: List[str] = Field(default_factory=list)
    role_instruction: str
    success_criteria: List[str] = Field(default_factory=list)


class AgentCapabilityRegistry:
    """Registry maintaining canonical profiles and routing for logical agents."""

    def __init__(self):
        self._profiles: Dict[str, AgentCapabilityProfile] = {}
        self._register_canonical_agents()

    def register_profile(self, profile: AgentCapabilityProfile) -> None:
        self._profiles[profile.agent_id] = profile

    def get_agent(self, agent_id: str) -> Optional[AgentCapabilityProfile]:
        return self._profiles.get(agent_id)

    def list_agents(self, domain: Optional[AgentDomain] = None) -> List[AgentCapabilityProfile]:
        if domain:
            return [p for p in self._profiles.values() if p.domain == domain]
        return list(self._profiles.values())

    def find_agents_for_capability(self, capability: str) -> List[AgentCapabilityProfile]:
        cap_lower = capability.lower()
        return [
            p for p in self._profiles.values()
            if any(cap_lower in c.lower() for c in p.capabilities)
        ]

    def resolve_agent_for_task(
        self,
        task_action: str,
        preferred_domain: Optional[AgentDomain] = None,
    ) -> AgentCapabilityProfile:
        """Deterministically selects the most specialized agent for an action or skill."""
        action_lower = task_action.lower()

        # 1. Exact skill match
        for profile in self._profiles.values():
            if preferred_domain and profile.domain != preferred_domain:
                continue
            if any(action_lower == s.lower() for s in profile.allowed_skills):
                return profile

        # 2. Capability keyword match
        candidates = self.find_agents_for_capability(task_action)
        if preferred_domain:
            filtered = [c for c in candidates if c.domain == preferred_domain]
            if filtered:
                return filtered[0]
        if candidates:
            return candidates[0]

        # 3. Domain fallbacks
        if preferred_domain:
            domain_agents = self.list_agents(preferred_domain)
            if domain_agents:
                return domain_agents[0]

        # Default general executor
        return self._profiles["automation_agent"]

    def _register_canonical_agents(self) -> None:
        """Registers the standard specialized logical agents across the 5 commercial domains."""
        agents = [
            # -------------------------------------------------------------
            # DOMAIN 1: RESEARCH
            # -------------------------------------------------------------
            AgentCapabilityProfile(
                agent_id="business_research_agent",
                name="Business Research Agent",
                domain=AgentDomain.RESEARCH,
                description="Researches target business operations, corporate signals, and technical infrastructure.",
                capabilities=["domain_inspection", "technology_profiling", "evidence_collection"],
                allowed_skills=["research_business"],
                allowed_tools=["filesystem.write", "filesystem.read"],
                risk_level=ToolRiskLevel.READ_ONLY,
                required_permissions=["tools:execute"],
                role_instruction="Gathers verifiable business intelligence to qualify commercial opportunities.",
                success_criteria=["Verifiable observations logged with FACT or INFERENCE certainty"],
            ),
            AgentCapabilityProfile(
                agent_id="market_research_agent",
                name="Market Research Agent",
                domain=AgentDomain.RESEARCH,
                description="Analyzes industry trends, pricing benchmarks, and service demand patterns.",
                capabilities=["market_benchmarking", "industry_trend_analysis", "demand_estimation"],
                allowed_skills=["analyze_opportunity"],
                allowed_tools=["filesystem.write", "filesystem.read"],
                risk_level=ToolRiskLevel.READ_ONLY,
                required_permissions=["tools:execute"],
                role_instruction="Evaluates market demand and pricing benchmarks across target business sectors.",
                success_criteria=["Empirical pricing data with source documentation"],
            ),
            AgentCapabilityProfile(
                agent_id="opportunity_research_agent",
                name="Opportunity Research Agent",
                domain=AgentDomain.RESEARCH,
                description="Discovers and evaluates high-yield commercial prospects from permitted sources.",
                capabilities=["prospect_discovery", "economic_valuation", "signal_verification"],
                allowed_skills=["analyze_opportunity", "research_business"],
                allowed_tools=["filesystem.write", "filesystem.read"],
                risk_level=ToolRiskLevel.LOW,
                required_permissions=["tools:execute"],
                role_instruction="Identifies and ranks prospective clients based on authentic Economic Value (EV).",
                success_criteria=["Opportunities scored with complete factor breakdown"],
            ),

            # -------------------------------------------------------------
            # DOMAIN 2: SALES & COMMERCIAL
            # -------------------------------------------------------------
            AgentCapabilityProfile(
                agent_id="lead_qualification_agent",
                name="Lead Qualification Agent",
                domain=AgentDomain.SALES,
                description="Scores and filters commercial leads using economic opportunity models.",
                capabilities=["qualification_scoring", "fit_assessment", "budget_probability"],
                allowed_skills=["analyze_opportunity"],
                allowed_tools=["filesystem.read"],
                risk_level=ToolRiskLevel.LOW,
                required_permissions=["tools:execute"],
                role_instruction="Ensures only legitimate, high-probability business leads advance to outreach.",
                success_criteria=["Lead qualification recommendation adheres to policy"],
            ),
            AgentCapabilityProfile(
                agent_id="outreach_agent",
                name="Outreach Agent",
                domain=AgentDomain.SALES,
                description="Dispatches highly personalized, anti-spam compliant commercial outreach.",
                capabilities=["cold_outreach", "personalization", "rate_limit_compliance"],
                allowed_skills=["generate_client_proposal"],
                allowed_tools=["communication.dispatch"],
                risk_level=ToolRiskLevel.MEDIUM,
                required_permissions=["tools:execute", "communications:dispatch"],
                role_instruction="Initiates compliant, value-focused outreach respecting anti-spam limits.",
                success_criteria=["Delivered without spam complaints, strict opt-out compliance"],
            ),
            AgentCapabilityProfile(
                agent_id="conversation_agent",
                name="Conversation Agent",
                domain=AgentDomain.SALES,
                description="Engages in inbound commercial dialogue, intent detection, and requirement scoping.",
                capabilities=["intent_classification", "sentiment_analysis", "dialogue_management"],
                allowed_skills=[],
                allowed_tools=["communication.dispatch"],
                risk_level=ToolRiskLevel.LOW,
                required_permissions=["tools:execute"],
                role_instruction="Understands client intent, addresses objections, and facilitates technical scoping.",
                success_criteria=["Accurate intent categorization and non-hallucinated responses"],
            ),
            AgentCapabilityProfile(
                agent_id="requirements_agent",
                name="Requirements Agent",
                domain=AgentDomain.SALES,
                description="Extracts functional, technical, security, and acceptance criteria from client dialogue.",
                capabilities=["scope_extraction", "certainty_tagging", "unknown_detection"],
                allowed_skills=[],
                allowed_tools=["filesystem.write"],
                risk_level=ToolRiskLevel.LOW,
                required_permissions=["tools:execute"],
                role_instruction="Translates client messages into structured, provenance-linked requirements.",
                success_criteria=["Every requirement contains provenance reference and certainty tag"],
            ),
            AgentCapabilityProfile(
                agent_id="proposal_agent",
                name="Proposal Agent",
                domain=AgentDomain.SALES,
                description="Drafts authoritative, structured commercial proposals and deliverables specifications.",
                capabilities=["proposal_generation", "deliverable_specification", "scope_definition"],
                allowed_skills=["generate_client_proposal"],
                allowed_tools=["filesystem.write"],
                risk_level=ToolRiskLevel.LOW,
                required_permissions=["tools:execute"],
                role_instruction="Generates professional project proposals with clear commercial boundaries.",
                success_criteria=["Contains clear deliverables, terms, and cryptographic QA guarantees"],
            ),
            AgentCapabilityProfile(
                agent_id="negotiation_agent",
                name="Negotiation Agent",
                domain=AgentDomain.SALES,
                description="Enforces strict price floors, revision limits, and commercial negotiation bounds.",
                capabilities=["bounded_negotiation", "price_floor_enforcement", "quote_authorization"],
                allowed_skills=["generate_project_estimate"],
                allowed_tools=["payments.create_checkout"],
                risk_level=ToolRiskLevel.MEDIUM,
                required_permissions=["tools:execute"],
                role_instruction="Ensures all client quotes and revisions strictly comply with pricing bounds.",
                success_criteria=["Zero quotes below price floor, maximum 2 revision cycles"],
            ),

            # -------------------------------------------------------------
            # DOMAIN 3: ENGINEERING
            # -------------------------------------------------------------
            AgentCapabilityProfile(
                agent_id="software_architect_agent",
                name="Software Architect Agent",
                domain=AgentDomain.ENGINEERING,
                description="Plans project architectures, component dependencies, and skill composition.",
                capabilities=["architecture_planning", "skill_composition", "dependency_graphing"],
                allowed_skills=[],
                allowed_tools=["filesystem.read"],
                risk_level=ToolRiskLevel.LOW,
                required_permissions=["tools:execute"],
                role_instruction="Decomposes complex client requirements into dependency-managed milestone plans.",
                success_criteria=["Executable milestone tasks with explicit prerequisite dependencies"],
            ),
            AgentCapabilityProfile(
                agent_id="backend_agent",
                name="Backend Engineering Agent",
                domain=AgentDomain.ENGINEERING,
                description="Implements robust serverless routes, background jobs, and business logic.",
                capabilities=["fastapi_development", "python_engineering", "secure_backend"],
                allowed_skills=["build_webhook_integration", "build_api_integration"],
                allowed_tools=["filesystem.write", "filesystem.read"],
                risk_level=ToolRiskLevel.MEDIUM,
                required_permissions=["tools:execute"],
                role_instruction="Writes production Python code with complete typing and error handling.",
                success_criteria=["Code compiles without syntax errors and fulfills functional criteria"],
            ),
            AgentCapabilityProfile(
                agent_id="frontend_agent",
                name="Frontend Engineering Agent",
                domain=AgentDomain.ENGINEERING,
                description="Builds responsive web interfaces, landing pages, and Tailwind components.",
                capabilities=["html_generation", "tailwind_styling", "responsive_ui"],
                allowed_skills=["build_landing_page", "build_business_dashboard"],
                allowed_tools=["filesystem.write", "filesystem.read"],
                risk_level=ToolRiskLevel.MEDIUM,
                required_permissions=["tools:execute"],
                role_instruction="Creates clean, modern HTML5/Tailwind web interfaces.",
                success_criteria=["Valid DOM structure, responsive viewport, clean rendering"],
            ),
            AgentCapabilityProfile(
                agent_id="api_agent",
                name="API Integration Agent",
                domain=AgentDomain.ENGINEERING,
                description="Creates robust external REST and GraphQL API clients with retries and pooling.",
                capabilities=["api_client_generation", "auth_injection", "connection_pooling"],
                allowed_skills=["build_api_integration"],
                allowed_tools=["filesystem.write", "filesystem.read"],
                risk_level=ToolRiskLevel.MEDIUM,
                required_permissions=["tools:execute"],
                role_instruction="Constructs reliable async HTTP clients with resilient backoff and error handling.",
                success_criteria=["Handles timeouts, token refresh, and HTTP error code mapping"],
            ),
            AgentCapabilityProfile(
                agent_id="automation_agent",
                name="Automation Engineering Agent",
                domain=AgentDomain.ENGINEERING,
                description="Designs n8n workflows, webhook callbacks, and multi-app data pipelines.",
                capabilities=["n8n_workflows", "data_transformation", "webhook_triggers"],
                allowed_skills=["build_n8n_automation"],
                allowed_tools=["filesystem.write", "filesystem.read"],
                risk_level=ToolRiskLevel.MEDIUM,
                required_permissions=["tools:execute"],
                role_instruction="Constructs end-to-end integration workflows connecting disparate SaaS APIs.",
                success_criteria=["Valid n8n workflow JSON specification with correct connections"],
            ),
            AgentCapabilityProfile(
                agent_id="devops_agent",
                name="DevOps Agent",
                domain=AgentDomain.ENGINEERING,
                description="Handles packaging, dependency manifests, cryptographic checksums, and handover.",
                capabilities=["packaging", "checksum_generation", "manifest_assembly"],
                allowed_skills=["prepare_project_delivery"],
                allowed_tools=["filesystem.write", "filesystem.read"],
                risk_level=ToolRiskLevel.LOW,
                required_permissions=["tools:execute"],
                role_instruction="Packages verified deliverables into cryptographic delivery bundles.",
                success_criteria=["SHA-256 signatures for every deliverable file in manifest"],
            ),

            # -------------------------------------------------------------
            # DOMAIN 4: QUALITY ASSURANCE
            # -------------------------------------------------------------
            AgentCapabilityProfile(
                agent_id="functional_qa_agent",
                name="Functional QA Agent",
                domain=AgentDomain.QA,
                description="Executes 5-layer adversarial functional inspection of deliverables against criteria.",
                capabilities=["criteria_verification", "syntax_validation", "stub_detection"],
                allowed_skills=["qa_project_deliverable"],
                allowed_tools=["qa.evaluate"],
                risk_level=ToolRiskLevel.LOW,
                required_permissions=["tools:execute"],
                role_instruction="Adversarially tests deliverables to verify fulfillment of client requirements.",
                success_criteria=["Zero critical defects, all acceptance criteria reflected"],
            ),
            AgentCapabilityProfile(
                agent_id="security_qa_agent",
                name="Security QA Agent",
                domain=AgentDomain.QA,
                description="Audits deliverables for path traversal, secret leaks, and security vulnerabilities.",
                capabilities=["security_linting", "secret_detection", "sandbox_confinement"],
                allowed_skills=["qa_project_deliverable"],
                allowed_tools=["qa.evaluate"],
                risk_level=ToolRiskLevel.LOW,
                required_permissions=["tools:execute"],
                role_instruction="Ensures artifacts strictly adhere to security boundaries and leak zero secrets.",
                success_criteria=["Zero security findings or sandbox escapes"],
            ),
            AgentCapabilityProfile(
                agent_id="browser_qa_agent",
                name="Browser QA Agent",
                domain=AgentDomain.QA,
                description="Validates frontend deliverables in isolated browser environments.",
                capabilities=["dom_inspection", "visual_verification", "console_error_checks"],
                allowed_skills=["qa_project_deliverable"],
                allowed_tools=["browser.action", "qa.evaluate"],
                risk_level=ToolRiskLevel.LOW,
                required_permissions=["tools:execute"],
                role_instruction="Inspects web deliverables in headless browser for clean rendering and script execution.",
                success_criteria=["Zero unhandled JS exceptions, verified visual layout"],
            ),

            # -------------------------------------------------------------
            # DOMAIN 5: BUSINESS & REVENUE
            # -------------------------------------------------------------
            AgentCapabilityProfile(
                agent_id="pricing_agent",
                name="Pricing Agent",
                domain=AgentDomain.BUSINESS,
                description="Determines competitive, margin-optimized pricing derived from effort and complexity.",
                capabilities=["effort_estimation", "margin_calculation", "dynamic_pricing"],
                allowed_skills=["generate_project_estimate"],
                allowed_tools=["filesystem.read"],
                risk_level=ToolRiskLevel.LOW,
                required_permissions=["tools:execute"],
                role_instruction="Computes profitable fixed-scope project prices based on historical calibration.",
                success_criteria=["Maintains >= 80% gross profit margin, complies with price floors"],
            ),
            AgentCapabilityProfile(
                agent_id="revenue_agent",
                name="Revenue Agent",
                domain=AgentDomain.BUSINESS,
                description="Monitors weekly revenue pacing toward $1,200-$1,500 target and diagnoses funnel leaks.",
                capabilities=["revenue_tracking", "funnel_analysis", "leakage_detection"],
                allowed_skills=["record_project_outcome"],
                allowed_tools=["filesystem.read"],
                risk_level=ToolRiskLevel.LOW,
                required_permissions=["tools:execute"],
                role_instruction="Tracks commercial conversion velocity and recommends high-yield interventions.",
                success_criteria=["Real-time 7d pacing metrics and actionable funnel diagnosis"],
            ),
            AgentCapabilityProfile(
                agent_id="learning_agent",
                name="Learning Agent",
                domain=AgentDomain.BUSINESS,
                description="Correlates estimated vs actual project metrics and updates institutional calibration.",
                capabilities=["outcome_analysis", "calibration_multiplier", "institutional_memory"],
                allowed_skills=["record_project_outcome"],
                allowed_tools=["filesystem.write"],
                risk_level=ToolRiskLevel.LOW,
                required_permissions=["tools:execute"],
                role_instruction="Updates operational calibration ratios so future estimates improve monotonically.",
                success_criteria=["Persists outcome records and updates skill metrics"],
            ),
        ]

        for a in agents:
            self.register_profile(a)


agent_registry = AgentCapabilityRegistry()
