"""Base contracts, schemas, and abstract classes for the tool execution system.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional, Type
from pydantic import BaseModel, Field

from packages.shared.models import ToolRiskLevel


class ToolRequest(BaseModel):
    tool_name: str
    arguments: Dict[str, Any]
    project_id: Optional[str] = None
    client_id: Optional[str] = None
    run_id: Optional[str] = None
    task_id: Optional[str] = None
    requested_by_role: str = "OPERATOR"
    idempotency_key: Optional[str] = None


class ToolResult(BaseModel):
    tool_name: str
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    risk_level: ToolRiskLevel
    execution_time_ms: int = 0
    evidence: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BaseTool(ABC):
    """Abstract base tool with explicit metadata, risk level, and pydantic schema validation."""

    name: str
    description: str
    risk_level: ToolRiskLevel
    input_schema: Type[BaseModel]
    required_permission: str

    @abstractmethod
    async def execute(self, params: BaseModel, context: ToolRequest) -> Any:
        """Executes tool logic with typed, validated inputs."""
        pass
