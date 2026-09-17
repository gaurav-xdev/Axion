"""Central Authoritative Tool Gateway.
Enforces multi-layer validation pipeline:
Tool Request
→ Existence Check (Unknown tools default to DENY)
→ Schema Validation
→ Authentication/Authorization & RBAC Permission Check
→ Emergency State Check (PAUSE blocks non-read side-effects, STOP blocks ALL side-effects)
→ Policy & Risk Classification
→ Idempotency Check (replays cached response for duplicate side-effects)
→ Tool Execution
→ Output Sanitization (Redacts secrets)
→ Evidence Generation
→ Audit Event & ToolRun Persistence
→ Tool Result
"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import time
from typing import Any, Dict, Optional
from pydantic import ValidationError
from sqlalchemy import select

from packages.observability.logger import logger
from packages.observability.metrics import TOOL_CALLS_TOTAL, TOOL_FAILURES
from packages.security.emergency import emergency_service
from packages.security.rbac import is_permission_allowed
from packages.security.redaction import redact_dict
from packages.shared.database import async_session_factory
from packages.shared.models import AuditEvent, IdempotencyKey, ToolRiskLevel, ToolRun, UserRole
from packages.tools.base import BaseTool, ToolRequest, ToolResult
from packages.tools.filesystem import ListFilesTool, ReadFileTool, WriteFileTool
from packages.tools.terminal import TerminalExecTool
from packages.tools.unified import (
    BrowserActionTool,
    CommunicationDispatchTool,
    ComputerActionTool,
    MediaProbeTool,
    PaymentCreateCheckoutTool,
)


class ToolGateway:
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        self._register_default_tools()

    def register_tool(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool
        logger.info(f"Registered tool '{tool.name}' with risk level '{tool.risk_level.value}'")

    def _register_default_tools(self) -> None:
        # Filesystem & Sandbox
        self.register_tool(ReadFileTool())
        self.register_tool(WriteFileTool())
        self.register_tool(ListFilesTool())
        self.register_tool(TerminalExecTool())

        # Unified Side-Effecting Tools
        self.register_tool(CommunicationDispatchTool())
        self.register_tool(PaymentCreateCheckoutTool())
        self.register_tool(MediaProbeTool())
        self.register_tool(BrowserActionTool())
        self.register_tool(ComputerActionTool())

    async def execute(self, request: ToolRequest) -> ToolResult:
        start_time = time.monotonic()
        tool = self._tools.get(request.tool_name)

        # 1. Existence Check (Unknown tools DEFAULT TO DENY)
        if not tool:
            TOOL_FAILURES.labels(tool_name=request.tool_name).inc()
            await self._record_audit_event(
                actor=request.requested_by_role,
                action=f"tool_unknown:{request.tool_name}",
                target_type="tool",
                target_id=request.tool_name,
                project_id=request.project_id,
                client_id=request.client_id,
                risk_level=ToolRiskLevel.CRITICAL,
                result="DENIED",
                reason=f"Tool '{request.tool_name}' is not recognized or registered. Unknown tools default to DENY.",
            )
            return ToolResult(
                tool_name=request.tool_name,
                success=False,
                error=f"Tool '{request.tool_name}' is not recognized. Policy defaults to DENY.",
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

        # 3. RBAC Permission & Authorization Check
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

        # 4. Authoritative Distributed Emergency State Check
        emergency_state = await emergency_service.get_state()
        is_side_effecting = tool.risk_level != ToolRiskLevel.READ_ONLY

        if emergency_state.is_stopped and is_side_effecting:
            TOOL_FAILURES.labels(tool_name=tool.name).inc()
            reason_msg = f"Operation blocked: Authoritative Emergency Stop is ACTIVE ({emergency_state.reason})"
            await self._record_audit_event(
                actor=request.requested_by_role,
                action=f"emergency_blocked:{tool.name}",
                target_type="tool",
                target_id=tool.name,
                project_id=request.project_id,
                client_id=request.client_id,
                risk_level=tool.risk_level,
                result="BLOCKED",
                reason=reason_msg,
            )
            return ToolResult(
                tool_name=tool.name,
                success=False,
                error=reason_msg,
                risk_level=tool.risk_level,
            )

        if emergency_state.is_paused and is_side_effecting:
            TOOL_FAILURES.labels(tool_name=tool.name).inc()
            reason_msg = f"Operation paused: Distributed Emergency Pause is ACTIVE ({emergency_state.reason})"
            return ToolResult(
                tool_name=tool.name,
                success=False,
                error=reason_msg,
                risk_level=tool.risk_level,
            )

        # 5. Idempotency Check for Side-Effecting Tools
        if request.idempotency_key and is_side_effecting:
            cached_res = await self._check_idempotency(request.idempotency_key)
            if cached_res is not None:
                logger.info(f"Returning idempotent cached result for key '{request.idempotency_key}'")
                return ToolResult(
                    tool_name=tool.name,
                    success=True,
                    data=cached_res,
                    risk_level=tool.risk_level,
                    execution_time_ms=0,
                )

        # 6. Tool Execution
        try:
            raw_output = await tool.execute(validated_params, request)
            exec_time = int((time.monotonic() - start_time) * 1000)

            # 7. Output Sanitization (Secret Redaction)
            safe_output = redact_dict(raw_output)

            # 8. Store Idempotency Result if requested
            if request.idempotency_key and is_side_effecting:
                await self._save_idempotency(
                    key=request.idempotency_key,
                    resource_type=tool.name,
                    resource_id=request.project_id or request.task_id or "global",
                    response_data=safe_output,
                )

            # 9. Audit Logging & ToolRun Persistence
            await self._record_tool_run(
                request=request,
                tool=tool,
                output=safe_output,
                exec_time_ms=exec_time,
                success=True,
            )

            # Generate evidence snapshot
            evidence = {
                "tool_name": tool.name,
                "risk_level": tool.risk_level.value,
                "project_id": request.project_id,
                "execution_time_ms": exec_time,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            return ToolResult(
                tool_name=tool.name,
                success=True,
                data=safe_output,
                risk_level=tool.risk_level,
                execution_time_ms=exec_time,
                evidence=evidence,
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

    async def _check_idempotency(self, key: str) -> Optional[Any]:
        try:
            async with async_session_factory() as session:
                stmt = select(IdempotencyKey).where(IdempotencyKey.key == key)
                rec = (await session.execute(stmt)).scalar_one_or_none()
                if rec:
                    exp = rec.expires_at
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=timezone.utc)
                    if exp > datetime.now(timezone.utc):
                        return rec.response_json
        except Exception as ex:
            logger.warning(f"Error reading idempotency key: {ex}")
        return None

    async def _save_idempotency(self, key: str, resource_type: str, resource_id: str, response_data: Any) -> None:
        try:
            async with async_session_factory() as session:
                entry = IdempotencyKey(
                    key=key,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    response_json=response_data if isinstance(response_data, (dict, list)) else {"result": response_data},
                    expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                )
                session.add(entry)
                await session.commit()
        except Exception as ex:
            logger.warning(f"Error saving idempotency key: {ex}")

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


# Global authoritative singleton ToolGateway
tool_gateway = ToolGateway()
