"""Automation Worker.
Generates, validates, and packages n8n workflow definitions exclusively as client project deliverables.
NOTE: n8n is NEVER the agent's internal orchestration backbone.
"""

import json
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from packages.observability.logger import logger


class N8nNodeConfig(BaseModel):
    name: str
    type: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    position: List[int] = Field(default_factory=lambda: [250, 300])


class N8nWorkflowDefinition(BaseModel):
    name: str
    nodes: List[Dict[str, Any]]
    connections: Dict[str, Any]
    active: bool = False
    settings: Dict[str, Any] = Field(default_factory=dict)


class WorkflowValidationResult(BaseModel):
    valid: bool
    node_count: int
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class AutomationWorker:
    """Specialist worker for creating automated n8n workflows for clients."""

    def generate_webhook_to_crm_workflow(
        self, workflow_name: str, webhook_path: str, crm_api_url: str
    ) -> Dict[str, Any]:
        """Generates a standard n8n workflow JSON definition for webhook processing."""
        workflow = {
            "name": workflow_name,
            "nodes": [
                {
                    "name": "Webhook Trigger",
                    "type": "n8n-nodes-base.webhook",
                    "typeVersion": 1,
                    "position": [240, 300],
                    "parameters": {
                        "path": webhook_path,
                        "httpMethod": "POST",
                        "responseMode": "onReceived",
                    },
                },
                {
                    "name": "Validate & Format Data",
                    "type": "n8n-nodes-base.code",
                    "typeVersion": 2,
                    "position": [460, 300],
                    "parameters": {
                        "jsCode": "return [{ json: { lead_email: $input.first().json.email, processed_at: new Date().toISOString() } }];",
                    },
                },
                {
                    "name": "Dispatch to CRM API",
                    "type": "n8n-nodes-base.httpRequest",
                    "typeVersion": 4.2,
                    "position": [680, 300],
                    "parameters": {
                        "method": "POST",
                        "url": crm_api_url,
                        "sendBody": True,
                        "specifyBody": "json",
                        "jsonBody": "={{ JSON.stringify($json) }}",
                    },
                },
            ],
            "connections": {
                "Webhook Trigger": {
                    "main": [[{"node": "Validate & Format Data", "type": "main", "index": 0}]]
                },
                "Validate & Format Data": {
                    "main": [[{"node": "Dispatch to CRM API", "type": "main", "index": 0}]]
                },
            },
            "settings": {"executionOrder": "v1"},
        }
        return workflow

    def validate_workflow_schema(self, workflow_json: Dict[str, Any]) -> WorkflowValidationResult:
        """Validates that a generated workflow meets official n8n schema specifications."""
        errors = []
        warnings = []

        if not isinstance(workflow_json, dict):
            return WorkflowValidationResult(valid=False, node_count=0, errors=["Workflow must be a JSON object"])

        if "nodes" not in workflow_json or not isinstance(workflow_json["nodes"], list):
            errors.append("Workflow is missing required 'nodes' array")

        if "connections" not in workflow_json or not isinstance(workflow_json["connections"], dict):
            errors.append("Workflow is missing required 'connections' object")

        nodes = workflow_json.get("nodes", [])
        if not nodes:
            errors.append("Workflow must contain at least one node")

        node_names = set()
        for idx, node in enumerate(nodes):
            if "name" not in node or not node["name"]:
                errors.append(f"Node at index {idx} lacks a valid 'name'")
            else:
                node_names.add(node["name"])

            if "type" not in node or not node["type"]:
                errors.append(f"Node at index {idx} lacks a valid 'type'")

        # Verify all connections point to declared nodes
        connections = workflow_json.get("connections", {})
        for src_node, outputs in connections.items():
            if src_node not in node_names:
                errors.append(f"Connection source '{src_node}' is not in nodes list")
            if isinstance(outputs, dict) and "main" in outputs:
                for branch in outputs["main"]:
                    for link in branch:
                        dest_node = link.get("node")
                        if dest_node not in node_names:
                            errors.append(f"Connection destination '{dest_node}' does not exist")

        is_valid = len(errors) == 0
        logger.info(f"n8n Workflow validation result: valid={is_valid}, {len(nodes)} nodes, {len(errors)} errors")

        return WorkflowValidationResult(
            valid=is_valid,
            node_count=len(nodes),
            errors=errors,
            warnings=warnings,
        )


# Global singleton
automation_worker = AutomationWorker()
