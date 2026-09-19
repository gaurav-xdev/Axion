"""Dodo Payments integration adapter.
Handles one-time checkout generation, HMAC-SHA256 webhook signature verification, and API queries.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from typing import Any, Dict, Optional
import httpx

from packages.observability.logger import logger
from packages.payments.base import CheckoutResponse, CreateCheckoutRequest, PaymentProvider
from packages.shared.config import settings
from packages.shared.models import PaymentStatus


class PaymentProviderError(RuntimeError):
    """Base error for payment provider operations."""
    pass


class PaymentNotConfiguredError(PaymentProviderError):
    """Raised when payment provider is invoked without mandatory credentials."""
    pass


class DodoPaymentsProvider(PaymentProvider):
    """Adapter for Dodo Payments hosted checkout and webhook infrastructure."""

    def __init__(self):
        self.api_key = settings.DODO_API_KEY
        self.webhook_secret = settings.DODO_WEBHOOK_SECRET
        self.api_url = settings.DODO_API_URL.rstrip("/")

    async def create_checkout(self, req: CreateCheckoutRequest) -> CheckoutResponse:
        """Creates a secure, one-time checkout session bound to the specific project."""
        expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

        if not self.api_key or "placeholder" in self.api_key:
            raise PaymentNotConfiguredError(
                "Dodo Payments API key is not configured; live checkout creation rejected."
            )

        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "billing": {"email": req.customer_email, "name": req.customer_name or "Client"},
                "payment_link": True,
                "product_cart": [
                    {
                        "product_id": f"proj_{req.project_id[:8]}",
                        "amount": int(req.amount * 100),  # In smallest currency units
                        "quantity": 1,
                    }
                ],
                "metadata": {
                    "project_id": req.project_id,
                    "client_id": req.client_id,
                    "quote_id": req.quote_id,
                },
            }

            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(f"{self.api_url}/checkouts", headers=headers, json=payload)
                res.raise_for_status()
                data = res.json()

            return CheckoutResponse(
                checkout_id=data.get("payment_id") or data.get("checkout_id"),
                checkout_url=data.get("checkout_url") or data.get("payment_link"),
                amount=req.amount,
                currency=req.currency,
                status=PaymentStatus.CHECKOUT_CREATED,
                expires_at=expires_at,
            )
        except Exception as e:
            logger.error(f"Dodo Payments API error: {e}")
            raise PaymentProviderError(f"Dodo Payments checkout creation failed: {e}") from e

    def verify_webhook_signature(self, raw_body: bytes, signature: str) -> bool:
        """Cryptographically verifies HMAC-SHA256 signature from Dodo webhook headers.
        Prevents forgery and untrusted caller manipulation.
        Requires DODO_WEBHOOK_SECRET exclusively; fails closed if unset.
        """
        secret = self.webhook_secret or settings.DODO_WEBHOOK_SECRET
        if not signature or not secret:
            return False

        # Support 'v1=hash' or raw hex string
        clean_sig = signature.split("=")[-1].strip()

        computed = hmac.new(
            key=secret.encode("utf-8"),
            msg=raw_body,
            digestmod=hashlib.sha256,
        ).hexdigest()

        # Constant-time comparison to prevent timing attacks
        return hmac.compare_digest(computed, clean_sig)

    async def get_payment_status(self, payment_id: str) -> Dict[str, Any]:
        """Direct server-side API verification of a payment status."""
        if not self.api_key or "placeholder" in self.api_key:
            raise PaymentNotConfiguredError(
                "Dodo Payments API key is not configured; cannot query payment status from external provider."
            )

        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"{self.api_url}/payments/{payment_id}", headers=headers)
            res.raise_for_status()
            return res.json()


# Global singleton
dodo_provider = DodoPaymentsProvider()
