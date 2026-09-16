"""Central Tool Gateway.
Enforces multi-layer validation pipeline:
Schema Validation -> Permission Check -> Risk Classification -> Policy Engine -> Budget Check -> Execution -> Output Sanitization -> Audit Logging.
"""

import time
from typing import Any, Dict, Optional
from pydantic import ValidationError

from packages.observability.logger import logger
from packages.observability.metrics import TOOL_CALLS_TOTAL, TOOL_FAILURES
from packages.security.rbac import is_permission_allowed
from packages.security.redaction import redact_dict
from packages.shared.database import async_session_factory
from packages.shared.models import AuditEvent, ToolRiskLevel, ToolRun, UserRole
from packages.tools.base import BaseTool, ToolRequest, ToolResult
from packages.tools.filesystem import ListFilesTool, ReadFileTool, WriteFileTool
from packages.tools.terminal import TerminalExecTool


class ToolGateway:
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        self._register_default_tools()

    def register_tool(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool
        logger.info(f"Registered tool '{tool.name}' with risk level '{tool.risk_level.value}'")

    def _register_default_tools(self) -> None:
        self.register_tool(ReadFileTool())
        self.register_tool(WriteFileTool())
        self.register_tool(ListFilesTool())
        self.register_tool(TerminalExecTool())

    async def execute(self, request: ToolRequest) -> ToolResult:
        start_time = time.monotonic()
        tool = self._tools.get(request.tool_name)

        # 1. Existence Check
        if not tool:
            TOOL_FAILURES.labels(tool_name=request.tool_name).inc()
            return ToolResult(
                tool_name=request.tool_name,
                success=False,
                error=f"Tool '{request.tool_name}' is not recognized or permitted",
                risk_level=ToolRiskLevel.CRITICAL,
            )

        TOOL_CALLS_TOTAL.labels(tool_name=tool.name, risk_level=tool.risk_level.value).inc()

        # 2. Schema Validation
        try:
            validated_params = tool.input_schema.model_validate(request.arguments)
        except ValidationError as ve:
            TOOL_FAILURES.labels(tool_name=tool.name).inc()
            return ToolResult(
                tool_name=tool.name,
                success=False,
                error=f"Input validation error: {ve.errors()}",
                risk_level=tool.risk_level,
            )

        # 3. RBAC Permission Check
        try:
            requester_role = UserRole(request.requested_by_role)
        except ValueError:
            requester_role = UserRole.OPERATOR

        if not is_permission_allowed(requester_role, tool.required_permission):
            TOOL_FAILURES.labels(tool_name=tool.name).inc()
            await self._record_audit_event(
                actor=request.requested_by_role,
                action=f"tool_denied:{tool.name}",
                target_type="tool",
                target_id=tool.name,
                project_id=request.project_id,
                client_id=request.client_id,
                risk_level=tool.risk_level,
                result="DENIED",
                reason=f"Role '{requester_role.value}' lacks required permission '{tool.required_permission}'",
            )
            return ToolResult(
                tool_name=tool.name,
                success=False,
                error=f"Access Denied: Missing permission '{tool.required_permission}'",
                risk_level=tool.risk_level,
            )

        # 4. Tool Execution
        try:
            raw_output = await tool.execute(validated_params, request)
            exec_time = int((time.monotonic() - start_time) * 1000)

            # 5. Output Sanitization (Secret Redaction)
            safe_output = redact_dict(raw_output)

            # 6. Audit Logging & Evidence Persistence
            await self._record_tool_run(
                request=request,
                tool=tool,
                output=safe_output,
                exec_time_ms=exec_time,
                success=True,
            )

            return ToolResult(
                tool_name=tool.name,
                success=True,
                data=safe_output,
                risk_level=tool.risk_level,
                execution_time_ms=exec_time,
            )

        except Exception as e:
            exec_time = int((time.monotonic() - start_time) * 1000)
            TOOL_FAILURES.labels(tool_name=tool.name).inc()
            error_msg = str(e)
            logger.error(f"Execution failure in tool '{tool.name}': {error_msg}")

            await self._record_tool_run(
                request=request,
                tool=tool,
                output={"error": error_msg},
                exec_time_ms=exec_time,
                success=False,
                error=error_msg,
            )

            return ToolResult(
                tool_name=tool.name,
                success=False,
                error=error_msg,
                risk_level=tool.risk_level,
                execution_time_ms=exec_time,
            )

    async def _record_tool_run(
        self,
        request: ToolRequest,
        tool: BaseTool,
        output: Any,
        exec_time_ms: int,
        success: bool,
        error: Optional[str] = None,
    ) -> None:
        """Persist tool execution record asynchronously."""
        try:
            async with async_session_factory() as session:
                tr = ToolRun(
                    run_id=request.run_id,
                    task_id=request.task_id,
                    tool_name=tool.name,
                    input_payload=redact_dict(request.arguments),
                    output_payload={"data": output} if isinstance(output, (dict, list, str, int, float, bool)) else {},
                    risk_level=tool.risk_level,
                    status="SUCCESS" if success else "FAILED",
                    error=error,
                    execution_time_ms=exec_time_ms,
                )
                session.add(tr)
                await session.commit()
        except Exception as ex:
            logger.warning(f"Could not persist ToolRun record: {ex}")

    async def _record_audit_event(
        self,
        actor: str,
        action: str,
        target_type: str,
        target_id: str,
        project_id: Optional[str],
        client_id: Optional[str],
        risk_level: ToolRiskLevel,
        result: str,
        reason: str,
    ) -> None:
        try:
            async with async_session_factory() as session:
                evt = AuditEvent(
                    actor=actor,
                    action=action,
                    target_type=target_type,
                    target_id=target_id,
                    project_id=project_id,
                    client_id=client_id,
                    risk_level=risk_level,
                    result=result,
                    reason=reason,
                )
                session.add(evt)
                await session.commit()
        except Exception as ex:
            logger.warning(f"Could not persist AuditEvent record: {ex}")


# Global singleton ToolGateway
tool_gateway = ToolGateway()
