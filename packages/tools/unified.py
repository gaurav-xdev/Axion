"""Unified Tool Wrappers for ToolGateway.
Encapsulates communication, payment, media, browser, and computer actions
as first-class BaseTool implementations.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from packages.shared.config import settings
from packages.shared.models import ChannelType, ToolRiskLevel
from packages.tools.base import BaseTool, ToolRequest


# -----------------------------------------------------------------------------
# COMMUNICATION DISPATCH TOOL
# -----------------------------------------------------------------------------

class CommunicationDispatchInput(BaseModel):
    recipient: str = Field(description="Target phone number or email address")
    sender: str = Field(default_factory=lambda: settings.SMTP_FROM_EMAIL, description="Authoritative sender address")
    channel: str = Field(default="EMAIL", description="Communication channel: EMAIL, WHATSAPP, VOICE, SYSTEM")
    content: str = Field(description="Message body text")
    subject: Optional[str] = Field(default=None, description="Email subject if applicable")
    prospect_id: Optional[str] = None
    client_id: Optional[str] = None


class CommunicationDispatchTool(BaseTool):
    name = "communication.dispatch"
    description = "Authoritative outbound message transmission across verified channels"
    risk_level = ToolRiskLevel.HIGH
    input_schema = CommunicationDispatchInput
    required_permission = "conversations:write"

    def __init__(self):
        self._gw = None

    async def execute(self, params: CommunicationDispatchInput, context: ToolRequest) -> Dict[str, Any]:
        if self._gw is None:
            from packages.communications.gateway import CommunicationGateway
            self._gw = CommunicationGateway()
        from packages.communications.base import OutboundMessageRequest
        ch_enum = ChannelType[params.channel.upper()] if params.channel.upper() in ChannelType.__members__ else ChannelType.EMAIL
        req = OutboundMessageRequest(
            recipient=params.recipient,
            sender=params.sender,
            channel=ch_enum,
            content=params.content,
            subject=params.subject,
            prospect_id=params.prospect_id or context.client_id,
            client_id=params.client_id or context.client_id,
        )
        res = await self._gw.dispatch(req)
        return {
            "success": res.success,
            "channel": res.channel.value,
            "status": res.status,
            "message_id": res.message_id,
            "error": res.error,
        }


# -----------------------------------------------------------------------------
# PAYMENT CREATE CHECKOUT TOOL
# -----------------------------------------------------------------------------

class PaymentCreateCheckoutInput(BaseModel):
    quote_id: str = Field(description="ID of the accepted quote")
    amount: float = Field(gt=0, description="Exact billable amount")
    currency: str = Field(default="USD", description="Currency symbol")
    product_name: str = Field(description="Descriptive product line item")
    customer_email: str = Field(description="Recipient client email")
    customer_name: Optional[str] = None


class PaymentCreateCheckoutTool(BaseTool):
    name = "payment.create_checkout"
    description = "Generate a secure, single-use, merchant-hosted checkout session"
    risk_level = ToolRiskLevel.CRITICAL
    input_schema = PaymentCreateCheckoutInput
    required_permission = "payments:write"

    def __init__(self):
        self._provider = None

    async def execute(self, params: PaymentCreateCheckoutInput, context: ToolRequest) -> Dict[str, Any]:
        if not context.project_id:
            raise ValueError("Payment checkout generation requires an authoritative project_id context")

        if self._provider is None:
            from packages.payments.dodo import DodoPaymentsProvider
            self._provider = DodoPaymentsProvider()

        from packages.payments.base import CreateCheckoutRequest
        req = CreateCheckoutRequest(
            project_id=context.project_id,
            client_id=context.client_id or "default_client",
            quote_id=params.quote_id,
            amount=params.amount,
            currency=params.currency,
            product_name=params.product_name,
            customer_email=params.customer_email,
            customer_name=params.customer_name,
        )
        res = await self._provider.create_checkout(req)
        return {
            "checkout_id": res.checkout_id,
            "checkout_url": res.checkout_url,
            "amount": res.amount,
            "currency": res.currency,
            "status": res.status.value,
            "expires_at": res.expires_at.isoformat(),
        }


# -----------------------------------------------------------------------------
# MEDIA PROBE AND RENDER TOOL
# -----------------------------------------------------------------------------

class MediaProbeInput(BaseModel):
    file_path: str = Field(description="Path to local media file")


class MediaProbeTool(BaseTool):
    name = "media.probe"
    description = "Inspect and verify media container metadata, bitrates, and streams"
    risk_level = ToolRiskLevel.READ_ONLY
    input_schema = MediaProbeInput
    required_permission = "tools:read"

    def __init__(self):
        self._worker = None

    async def execute(self, params: MediaProbeInput, context: ToolRequest) -> Dict[str, Any]:
        if self._worker is None:
            from packages.media.worker import VideoWorker
            self._worker = VideoWorker()
        meta = await self._worker.probe_media(params.file_path)
        return meta.model_dump()


# -----------------------------------------------------------------------------
# BROWSER ACTION TOOL
# -----------------------------------------------------------------------------

class BrowserActionInput(BaseModel):
    url: str = Field(description="Safe external target URL")
    extract_selectors: List[str] = Field(default_factory=list)
    capture_screenshot: bool = True


class BrowserActionTool(BaseTool):
    name = "browser.navigate"
    description = "Isolated headless browser navigation and selector extraction with SSRF defenses"
    risk_level = ToolRiskLevel.MEDIUM
    input_schema = BrowserActionInput
    required_permission = "tools:execute"

    def __init__(self):
        self._worker = None

    async def execute(self, params: BrowserActionInput, context: ToolRequest) -> Dict[str, Any]:
        if self._worker is None:
            from packages.browser.worker import BrowserWorker
            self._worker = BrowserWorker()
        from packages.browser.worker import BrowserTaskInput
        task = BrowserTaskInput(
            url=params.url,
            extract_selectors=params.extract_selectors,
            capture_screenshot=params.capture_screenshot,
            client_id=context.client_id,
            project_id=context.project_id,
        )
        res = await self._worker.execute_task(task)
        return res.model_dump()


# -----------------------------------------------------------------------------
# COMPUTER ACTION TOOL
# -----------------------------------------------------------------------------

class ComputerActionInput(BaseModel):
    action_type: str = Field(description="screenshot, observe_windows, or click")
    x: Optional[int] = None
    y: Optional[int] = None
    text: Optional[str] = None


class ComputerActionTool(BaseTool):
    name = "computer.action"
    description = "Sandboxed OS desktop observation and input driver"
    risk_level = ToolRiskLevel.HIGH
    input_schema = ComputerActionInput
    required_permission = "tools:execute"

    def __init__(self):
        self._worker = None

    async def execute(self, params: ComputerActionInput, context: ToolRequest) -> Dict[str, Any]:
        if self._worker is None:
            from packages.computer.worker import ComputerWorker
            self._worker = ComputerWorker()
        from packages.computer.worker import ComputerAction
        action = ComputerAction(
            action_type=params.action_type,
            x=params.x,
            y=params.y,
            text=params.text,
        )
        res = await self._worker.execute_action(action)
        return res.model_dump()


# -----------------------------------------------------------------------------
# QUALITY ASSURANCE EVALUATION TOOL
# -----------------------------------------------------------------------------

class QAEvaluateInput(BaseModel):
    project_id: Optional[str] = Field(default=None, description="Project identifier")
    artifact_id: str = Field(default="artifact_1", description="Artifact identifier")
    artifact_path: str = Field(description="Path to artifact inside project workspace")
    artifact_type: str = Field(default="CODE", description="Artifact type: CODE, N8N, MEDIA, REPORT")
    expected_criteria: List[str] = Field(default_factory=list, description="Quality criteria")


class QAEvaluateTool(BaseTool):
    name = "qa.evaluate"
    description = "Adversarial 5-layer quality assurance evaluation of project deliverables"
    risk_level = ToolRiskLevel.READ_ONLY
    input_schema = QAEvaluateInput
    required_permission = "tools:execute"

    def __init__(self):
        self._worker = None

    async def execute(self, params: QAEvaluateInput, context: ToolRequest) -> Dict[str, Any]:
        if self._worker is None:
            from packages.qa.worker import QAWorker
            self._worker = QAWorker()
        from packages.qa.worker import QAEvaluationRequest
        req = QAEvaluationRequest(
            project_id=params.project_id or context.project_id or "default_project",
            artifact_id=params.artifact_id,
            artifact_path=params.artifact_path,
            artifact_type=params.artifact_type,
            expected_criteria=params.expected_criteria,
        )
        res = await self._worker.evaluate_deliverable(req)
        return {
            "passed": res.passed,
            "score": res.score,
            "checks": {
                "input_valid": res.check1_input_valid,
                "security_valid": res.check2_security_policy_valid,
                "execution_valid": res.check3_execution_valid,
                "functional_qa_valid": res.check4_functional_qa_valid,
                "final_state_evidence_valid": res.check5_final_state_evidence_valid,
            },
            "findings": res.findings,
            "sha256_hash": res.sha256_hash,
        }

