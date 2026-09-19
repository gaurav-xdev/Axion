"""Seed Starter Skills Catalog.
Contains 12 canonical, structured, typed skills.
Each skill defines machine-readable schemas, strict allowed tools, and explicit verification criteria.
All procedures execute concrete tool calls and deterministic validation.
"""

from typing import List
from packages.shared.models import SkillActionType, ToolRiskLevel
from packages.skills.schemas import (
    KnowledgeResourceRef,
    ProcedureStep,
    SkillDefinitionPayload,
    SolutionPatternRef,
    VerificationCheck,
    VerificationProcedure,
)


def get_starter_skills() -> List[SkillDefinitionPayload]:
    """Returns the 12 canonical starter skill definitions."""
    return [
        # 1. Research Business
        SkillDefinitionPayload(
            skill_id="research_business",
            name="Research Target Business",
            description="Analyzes public signals, technology stack, and pain points for a business domain.",
            category="RESEARCH",
            purpose="Gathers verifiable business intelligence to qualify opportunities.",
            version="1.0.0",
            input_schema={
                "type": "object",
                "required": ["domain", "business_name"],
                "properties": {
                    "domain": {"type": "string"},
                    "business_name": {"type": "string"},
                    "pain_points": {"type": "array", "items": {"type": "string"}},
                },
            },
            output_schema={
                "type": "object",
                "required": ["domain", "pain_points"],
                "properties": {
                    "domain": {"type": "string"},
                    "pain_points": {"type": "array", "items": {"type": "string"}},
                },
            },
            allowed_tool_names=["filesystem.write"],
            procedure=[
                ProcedureStep(
                    step_id="observe_domain",
                    description="Record initial target parameters",
                    objective="Initialize research context",
                    action_type=SkillActionType.OBSERVE,
                    required_inputs=["domain"],
                    expected_output="Domain recorded",
                ),
                ProcedureStep(
                    step_id="synthesize_findings",
                    description="Produce structured opportunity findings",
                    objective="Summarize findings into valid output",
                    action_type=SkillActionType.TRANSFORM,
                    expected_output="Formatted research output",
                ),
                ProcedureStep(
                    step_id="persist_research_dossier",
                    description="Persist findings to sandboxed project workspace",
                    objective="Write dossier to filesystem",
                    action_type=SkillActionType.TOOL_CALL,
                    allowed_tools=["filesystem.write"],
                    expected_output="Dossier file written",
                ),
            ],
            verification_procedure=VerificationProcedure(
                checks=[
                    VerificationCheck(
                        check_name="evidence_check",
                        check_type="SCHEMA",
                        description="Ensure domain is verified and dossier written",
                    )
                ],
                required_evidence_keys=["observed_at", "tool_name"],
            ),
            risk_class=ToolRiskLevel.LOW,
            evidence_requirements=["observed_at", "tool_name"],
        ),

        # 2. Analyze Opportunity
        SkillDefinitionPayload(
            skill_id="analyze_opportunity",
            name="Analyze Commercial Opportunity",
            description="Evaluates technical feasibility, scope risk, and profitability of a prospect.",
            category="ANALYSIS",
            purpose="Scores commercial viability before preparing quotes.",
            version="1.0.0",
            input_schema={
                "type": "object",
                "required": ["business_name", "observed_pain_points"],
                "properties": {
                    "business_name": {"type": "string"},
                    "observed_pain_points": {"type": "array"},
                },
            },
            output_schema={
                "type": "object",
                "required": ["feasible", "opportunity_score"],
                "properties": {
                    "feasible": {"type": "boolean"},
                    "opportunity_score": {"type": "number"},
                },
            },
            allowed_tool_names=["filesystem.write"],
            procedure=[
                ProcedureStep(
                    step_id="evaluate_feasibility",
                    description="Evaluate feasibility based on observed pain points",
                    objective="Calculate score and feasibility",
                    action_type=SkillActionType.TRANSFORM,
                    expected_output="Opportunity score and feasibility flag",
                ),
                ProcedureStep(
                    step_id="persist_opportunity_score",
                    description="Write opportunity analysis to workspace",
                    objective="Persist scored evaluation",
                    action_type=SkillActionType.TOOL_CALL,
                    allowed_tools=["filesystem.write"],
                    expected_output="Evaluation report written",
                ),
            ],
            verification_procedure=VerificationProcedure(
                required_evidence_keys=["tool_name"],
            ),
            risk_class=ToolRiskLevel.LOW,
            evidence_requirements=["tool_name"],
        ),

        # 3. Generate Project Estimate
        SkillDefinitionPayload(
            skill_id="generate_project_estimate",
            name="Generate Project Cost & Effort Estimate",
            description="Calculates engineering effort hours, pricing floor, and margins.",
            category="ESTIMATION",
            purpose="Produces deterministic commercial quote estimates.",
            version="1.0.0",
            input_schema={
                "type": "object",
                "required": ["project_type", "integration_count"],
                "properties": {
                    "project_type": {"type": "string"},
                    "integration_count": {"type": "integer"},
                },
            },
            output_schema={
                "type": "object",
                "required": ["estimated_hours", "quoted_price"],
                "properties": {
                    "estimated_hours": {"type": "number"},
                    "quoted_price": {"type": "number"},
                },
            },
            allowed_tool_names=["filesystem.write"],
            procedure=[
                ProcedureStep(
                    step_id="compute_pricing",
                    description="Compute effort and pricing parameters",
                    objective="Determine project quote",
                    action_type=SkillActionType.TRANSFORM,
                    expected_output="Pricing breakdown",
                ),
                ProcedureStep(
                    step_id="persist_estimate",
                    description="Write formal project estimate to workspace",
                    objective="Persist cost and effort ledger",
                    action_type=SkillActionType.TOOL_CALL,
                    allowed_tools=["filesystem.write"],
                    expected_output="Estimate file written",
                ),
            ],
            verification_procedure=VerificationProcedure(
                required_evidence_keys=["tool_name"],
            ),
            risk_class=ToolRiskLevel.LOW,
            evidence_requirements=["tool_name"],
        ),

        # 4. Generate Client Proposal
        SkillDefinitionPayload(
            skill_id="generate_client_proposal",
            name="Generate Formal Client Proposal",
            description="Drafts a structured scope of work and deliverables contract.",
            category="COMMUNICATION",
            purpose="Packages commercial terms into clear deliverables for clients.",
            version="1.0.0",
            input_schema={
                "type": "object",
                "required": ["client_name", "scope_summary", "price"],
                "properties": {
                    "client_name": {"type": "string"},
                    "scope_summary": {"type": "string"},
                    "price": {"type": "number"},
                },
            },
            output_schema={
                "type": "object",
                "required": ["proposal_text", "status"],
                "properties": {
                    "proposal_text": {"type": "string"},
                    "status": {"type": "string"},
                },
            },
            allowed_tool_names=["filesystem.write"],
            procedure=[
                ProcedureStep(
                    step_id="format_proposal",
                    description="Format scope and deliverables into text",
                    objective="Generate proposal document",
                    action_type=SkillActionType.TRANSFORM,
                    expected_output="Proposal document text",
                ),
                ProcedureStep(
                    step_id="save_proposal_file",
                    description="Persist formal proposal markdown in workspace",
                    objective="Write proposal to file",
                    action_type=SkillActionType.TOOL_CALL,
                    allowed_tools=["filesystem.write"],
                    expected_output="Proposal file written",
                ),
            ],
            verification_procedure=VerificationProcedure(
                required_evidence_keys=["tool_name"],
            ),
            risk_class=ToolRiskLevel.LOW,
            evidence_requirements=["tool_name"],
        ),

        # 5. Build n8n Automation
        SkillDefinitionPayload(
            skill_id="build_n8n_automation",
            name="Build n8n Automation Workflow",
            description="Constructs valid, tested n8n workflow JSON deliverables.",
            category="AUTOMATION",
            purpose="Creates automated webhook to CRM integrations for clients.",
            version="1.0.0",
            input_schema={
                "type": "object",
                "required": ["workflow_name", "trigger_type"],
                "properties": {
                    "workflow_name": {"type": "string"},
                    "trigger_type": {"type": "string"},
                },
            },
            output_schema={
                "type": "object",
                "required": ["workflow_json", "nodes_count"],
                "properties": {
                    "workflow_json": {"type": "object"},
                    "nodes_count": {"type": "integer"},
                },
            },
            allowed_tool_names=["filesystem.write", "filesystem.read"],
            procedure=[
                ProcedureStep(
                    step_id="create_workflow_structure",
                    description="Assemble n8n workflow nodes and connections",
                    objective="Produce valid JSON workflow",
                    action_type=SkillActionType.TRANSFORM,
                    expected_output="Workflow JSON structure",
                ),
                ProcedureStep(
                    step_id="write_workflow_file",
                    description="Write workflow specification to project workspace",
                    objective="Persist JSON workflow",
                    action_type=SkillActionType.TOOL_CALL,
                    allowed_tools=["filesystem.write"],
                    expected_output="Workflow JSON file written",
                ),
                ProcedureStep(
                    step_id="verify_workflow_file",
                    description="Read back workflow file to verify integrity",
                    objective="Verify written file readable",
                    action_type=SkillActionType.TOOL_CALL,
                    allowed_tools=["filesystem.read"],
                    expected_output="Workflow file verified",
                ),
            ],
            verification_procedure=VerificationProcedure(
                required_evidence_keys=["tool_name"],
            ),
            risk_class=ToolRiskLevel.MEDIUM,
            evidence_requirements=["tool_name"],
            solution_patterns=[SolutionPatternRef(solution_id="pattern_n8n_crm_sync", version="1.0.0")],
        ),

        # 6. Build Webhook Integration
        SkillDefinitionPayload(
            skill_id="build_webhook_integration",
            name="Build Secure Webhook Integration",
            description="Generates serverless webhook endpoints with HMAC verification.",
            category="INTEGRATION",
            purpose="Implements reliable HTTP callback handlers.",
            version="1.0.0",
            input_schema={
                "type": "object",
                "required": ["endpoint_path", "secret_env_var"],
                "properties": {
                    "endpoint_path": {"type": "string"},
                    "secret_env_var": {"type": "string"},
                },
            },
            output_schema={
                "type": "object",
                "required": ["code", "language"],
                "properties": {
                    "code": {"type": "string"},
                    "language": {"type": "string"},
                },
            },
            allowed_tool_names=["filesystem.write", "filesystem.read"],
            procedure=[
                ProcedureStep(
                    step_id="generate_handler",
                    description="Generate secure webhook receiver code",
                    objective="Produce Python FastAPI webhook route",
                    action_type=SkillActionType.TRANSFORM,
                    expected_output="Webhook route source code",
                ),
                ProcedureStep(
                    step_id="write_webhook_file",
                    description="Write webhook receiver Python module",
                    objective="Persist Python source code",
                    action_type=SkillActionType.TOOL_CALL,
                    allowed_tools=["filesystem.write"],
                    expected_output="Source file written",
                ),
                ProcedureStep(
                    step_id="verify_webhook_file",
                    description="Read back module to verify byte integrity",
                    objective="Verify module readable",
                    action_type=SkillActionType.TOOL_CALL,
                    allowed_tools=["filesystem.read"],
                    expected_output="Module verified",
                ),
            ],
            verification_procedure=VerificationProcedure(
                required_evidence_keys=["tool_name"],
            ),
            risk_class=ToolRiskLevel.MEDIUM,
            evidence_requirements=["tool_name"],
        ),

        # 7. Build API Integration
        SkillDefinitionPayload(
            skill_id="build_api_integration",
            name="Build REST API Client Integration",
            description="Creates robust API clients with retries and authentication.",
            category="INTEGRATION",
            purpose="Connects external APIs to client software systems.",
            version="1.0.0",
            input_schema={
                "type": "object",
                "required": ["target_api_name", "base_url"],
                "properties": {
                    "target_api_name": {"type": "string"},
                    "base_url": {"type": "string"},
                },
            },
            output_schema={
                "type": "object",
                "required": ["client_code"],
                "properties": {
                    "client_code": {"type": "string"},
                },
            },
            allowed_tool_names=["filesystem.write", "filesystem.read"],
            procedure=[
                ProcedureStep(
                    step_id="build_client",
                    description="Build HTTP API client module",
                    objective="Generate client class",
                    action_type=SkillActionType.TRANSFORM,
                    expected_output="API client code",
                ),
                ProcedureStep(
                    step_id="write_client_file",
                    description="Write API client module to workspace",
                    objective="Persist client source code",
                    action_type=SkillActionType.TOOL_CALL,
                    allowed_tools=["filesystem.write"],
                    expected_output="Client file written",
                ),
                ProcedureStep(
                    step_id="verify_client_file",
                    description="Read back client file to verify syntax and bytes",
                    objective="Verify client readable",
                    action_type=SkillActionType.TOOL_CALL,
                    allowed_tools=["filesystem.read"],
                    expected_output="Client file verified",
                ),
            ],
            verification_procedure=VerificationProcedure(
                required_evidence_keys=["tool_name"],
            ),
            risk_class=ToolRiskLevel.LOW,
            evidence_requirements=["tool_name"],
        ),

        # 8. Build Landing Page
        SkillDefinitionPayload(
            skill_id="build_landing_page",
            name="Build Responsive Landing Page",
            description="Develops clean HTML/Tailwind landing page templates.",
            category="FRONTEND",
            purpose="Generates client conversion pages.",
            version="1.0.0",
            input_schema={
                "type": "object",
                "required": ["headline", "cta_text"],
                "properties": {
                    "headline": {"type": "string"},
                    "cta_text": {"type": "string"},
                },
            },
            output_schema={
                "type": "object",
                "required": ["html_content"],
                "properties": {
                    "html_content": {"type": "string"},
                },
            },
            allowed_tool_names=["filesystem.write", "filesystem.read"],
            procedure=[
                ProcedureStep(
                    step_id="render_template",
                    description="Render responsive landing page HTML",
                    objective="Generate complete HTML markup",
                    action_type=SkillActionType.TRANSFORM,
                    expected_output="Complete HTML string",
                ),
                ProcedureStep(
                    step_id="write_landing_page",
                    description="Write index.html to project workspace",
                    objective="Persist HTML landing page",
                    action_type=SkillActionType.TOOL_CALL,
                    allowed_tools=["filesystem.write"],
                    expected_output="HTML file written",
                ),
                ProcedureStep(
                    step_id="verify_landing_page",
                    description="Read back HTML file to verify markup integrity",
                    objective="Verify HTML readable",
                    action_type=SkillActionType.TOOL_CALL,
                    allowed_tools=["filesystem.read"],
                    expected_output="HTML verified",
                ),
            ],
            verification_procedure=VerificationProcedure(
                required_evidence_keys=["tool_name"],
            ),
            risk_class=ToolRiskLevel.LOW,
            evidence_requirements=["tool_name"],
        ),

        # 9. Build Business Dashboard
        SkillDefinitionPayload(
            skill_id="build_business_dashboard",
            name="Build Business Metrics Dashboard",
            description="Creates interactive dashboards for revenue, conversion, and leads.",
            category="FRONTEND",
            purpose="Visualizes business metrics for stakeholders.",
            version="1.0.0",
            input_schema={
                "type": "object",
                "required": ["dashboard_title", "metric_keys"],
                "properties": {
                    "dashboard_title": {"type": "string"},
                    "metric_keys": {"type": "array"},
                },
            },
            output_schema={
                "type": "object",
                "required": ["dashboard_spec"],
                "properties": {
                    "dashboard_spec": {"type": "object"},
                },
            },
            allowed_tool_names=["filesystem.write", "filesystem.read"],
            procedure=[
                ProcedureStep(
                    step_id="compose_dashboard",
                    description="Compose metrics widgets and data bindings",
                    objective="Produce dashboard schema",
                    action_type=SkillActionType.TRANSFORM,
                    expected_output="Dashboard spec JSON",
                ),
                ProcedureStep(
                    step_id="write_dashboard_spec",
                    description="Write dashboard specification to workspace",
                    objective="Persist dashboard JSON spec",
                    action_type=SkillActionType.TOOL_CALL,
                    allowed_tools=["filesystem.write"],
                    expected_output="Dashboard spec written",
                ),
                ProcedureStep(
                    step_id="verify_dashboard_spec",
                    description="Read back dashboard spec to verify JSON integrity",
                    objective="Verify spec readable",
                    action_type=SkillActionType.TOOL_CALL,
                    allowed_tools=["filesystem.read"],
                    expected_output="Dashboard spec verified",
                ),
            ],
            verification_procedure=VerificationProcedure(
                required_evidence_keys=["tool_name"],
            ),
            risk_class=ToolRiskLevel.LOW,
            evidence_requirements=["tool_name"],
        ),

        # 10. QA Project Deliverable
        SkillDefinitionPayload(
            skill_id="qa_project_deliverable",
            name="QA 5-Layer Deliverable Verification",
            description="Executes independent 5-layer adversarial verification on client deliverables.",
            category="QA",
            purpose="Ensures deliverables meet security, schema, and quality benchmarks.",
            version="1.0.0",
            input_schema={
                "type": "object",
                "required": ["artifact_path", "artifact_type"],
                "properties": {
                    "artifact_path": {"type": "string"},
                    "artifact_type": {"type": "string"},
                    "project_id": {"type": "string"},
                },
            },
            output_schema={
                "type": "object",
                "required": ["passed", "score"],
                "properties": {
                    "passed": {"type": "boolean"},
                    "score": {"type": "number"},
                },
            },
            allowed_tool_names=["filesystem.read", "qa.evaluate"],
            procedure=[
                ProcedureStep(
                    step_id="read_artifact",
                    description="Read target artifact to verify accessibility",
                    objective="Confirm artifact exists and is readable",
                    action_type=SkillActionType.TOOL_CALL,
                    allowed_tools=["filesystem.read"],
                    expected_output="Artifact bytes verified",
                ),
                ProcedureStep(
                    step_id="evaluate_artifact",
                    description="Run independent 5-layer adversarial QA",
                    objective="Execute QA evaluation pipeline",
                    action_type=SkillActionType.TOOL_CALL,
                    allowed_tools=["qa.evaluate"],
                    expected_output="QA evaluation result",
                ),
            ],
            verification_procedure=VerificationProcedure(
                required_evidence_keys=["tool_name"],
            ),
            risk_class=ToolRiskLevel.LOW,
            evidence_requirements=["tool_name"],
        ),

        # 11. Prepare Project Delivery
        SkillDefinitionPayload(
            skill_id="prepare_project_delivery",
            name="Prepare Final Project Delivery Bundle",
            description="Packages validated artifacts, documentation, and handover instructions.",
            category="DELIVERY",
            purpose="Prepares completed deliverable package for client handover.",
            version="1.0.0",
            input_schema={
                "type": "object",
                "required": ["project_id", "artifacts"],
                "properties": {
                    "project_id": {"type": "string"},
                    "artifacts": {"type": "array"},
                },
            },
            output_schema={
                "type": "object",
                "required": ["bundle_manifest", "package_status"],
                "properties": {
                    "bundle_manifest": {"type": "object"},
                    "package_status": {"type": "string"},
                },
            },
            allowed_tool_names=["filesystem.list", "filesystem.write"],
            procedure=[
                ProcedureStep(
                    step_id="list_deliverable_artifacts",
                    description="List project workspace directory",
                    objective="Inspect existing artifact directory",
                    action_type=SkillActionType.TOOL_CALL,
                    allowed_tools=["filesystem.list"],
                    expected_output="Artifact directory listing",
                ),
                ProcedureStep(
                    step_id="bundle_artifacts",
                    description="Compile manifest of deliverable artifacts",
                    objective="Generate delivery package manifest",
                    action_type=SkillActionType.TRANSFORM,
                    expected_output="Package manifest",
                ),
                ProcedureStep(
                    step_id="write_delivery_bundle",
                    description="Write delivery manifest to workspace",
                    objective="Persist delivery bundle manifest",
                    action_type=SkillActionType.TOOL_CALL,
                    allowed_tools=["filesystem.write"],
                    expected_output="Delivery manifest written",
                ),
            ],
            verification_procedure=VerificationProcedure(
                required_evidence_keys=["tool_name"],
            ),
            risk_class=ToolRiskLevel.LOW,
            evidence_requirements=["tool_name"],
        ),

        # 12. Record Project Outcome
        SkillDefinitionPayload(
            skill_id="record_project_outcome",
            name="Record Project Outcome & Financial Metrics",
            description="Records project delivery outcome, final profit margin, and performance metrics.",
            category="METRICS",
            purpose="Persists verified outcome metrics for accountability.",
            version="1.0.0",
            input_schema={
                "type": "object",
                "required": ["project_id", "outcome", "revenue"],
                "properties": {
                    "project_id": {"type": "string"},
                    "outcome": {"type": "string"},
                    "revenue": {"type": "number"},
                },
            },
            output_schema={
                "type": "object",
                "required": ["recorded", "timestamp"],
                "properties": {
                    "recorded": {"type": "boolean"},
                    "timestamp": {"type": "string"},
                },
            },
            allowed_tool_names=["filesystem.write"],
            procedure=[
                ProcedureStep(
                    step_id="finalize_metrics",
                    description="Finalize accounting and execution logs",
                    objective="Record final summary",
                    action_type=SkillActionType.TRANSFORM,
                    expected_output="Confirmation summary",
                ),
                ProcedureStep(
                    step_id="persist_outcome_ledger",
                    description="Write final financial ledger to workspace",
                    objective="Persist outcome record",
                    action_type=SkillActionType.TOOL_CALL,
                    allowed_tools=["filesystem.write"],
                    expected_output="Financial ledger written",
                ),
            ],
            verification_procedure=VerificationProcedure(
                required_evidence_keys=["tool_name"],
            ),
            risk_class=ToolRiskLevel.LOW,
            evidence_requirements=["tool_name"],
        ),
    ]
