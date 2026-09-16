"""Payment provider abstractions and data models.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from packages.shared.models import PaymentStatus


class CreateCheckoutRequest(BaseModel):
    project_id: str
    client_id: str
    quote_id: str
    amount: float = Field(gt=0.0)
    currency: str = Field(default="USD")
    product_name: str
    customer_email: str
    customer_name: Optional[str] = None


class CheckoutResponse(BaseModel):
    checkout_id: str
    checkout_url: str
    amount: float
    currency: str
    status: PaymentStatus
    expires_at: datetime


class PaymentProvider(ABC):
    @abstractmethod
    async def create_checkout(self, req: CreateCheckoutRequest) -> CheckoutResponse:
        pass

    @abstractmethod
    def verify_webhook_signature(self, raw_body: bytes, signature: str) -> bool:
        pass

    @abstractmethod
    async def get_payment_status(self, payment_id: str) -> Dict[str, Any]:
        pass
