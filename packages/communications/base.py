"""Communication provider contracts and data models.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
from packages.shared.models import ChannelType


class OutboundMessageRequest(BaseModel):
    recipient: str = Field(description="Target email address or phone number")
    sender: str = Field(description="Sender identification")
    subject: Optional[str] = Field(default=None, description="Email subject or message title")
    content: str = Field(description="Message body")
    channel: ChannelType
    prospect_id: Optional[str] = None
    client_id: Optional[str] = None
    conversation_id: Optional[str] = None


class DispatchResult(BaseModel):
    success: bool
    channel: ChannelType
    status: str  # SENT, NOT_CONFIGURED, POLICY_REJECTED, FAILED
    error: Optional[str] = None
    message_id: Optional[str] = None
    policy_checked: bool = True


class CommunicationProvider(ABC):
    @abstractmethod
    async def send_message(self, request: OutboundMessageRequest) -> DispatchResult:
        pass

    @abstractmethod
    def is_configured(self) -> bool:
        pass
