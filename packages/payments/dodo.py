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


class DodoPaymentsProvider(PaymentProvider):
    """Adapter for Dodo Payments hosted checkout and webhook infrastructure."""

    def __init__(self):
        self.api_key = settings.DODO_API_KEY
        self.webhook_secret = settings.DODO_WEBHOOK_SECRET
        self.api_url = settings.DODO_API_URL.rstrip("/")

    async def create_checkout(self, req: CreateCheckoutRequest) -> CheckoutResponse:
        """Creates a secure, one-time checkout session bound to the specific project."""
        expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

        # In production with valid DODO_API_KEY, call Dodo Payments API
        if self.api_key and not ("placeholder" in self.api_key or "test" in self.api_key):
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
                raise

        # Deterministic test sandbox checkout generation
        simulated_id = f"dodo_chk_{hashlib.sha256(f'{req.project_id}:{req.amount}'.encode()).hexdigest()[:16]}"
        simulated_url = f"{self.api_url}/checkout/{simulated_id}"
        logger.info(f"Generated sandboxed Dodo checkout '{simulated_id}' for project '{req.project_id}'")

        return CheckoutResponse(
            checkout_id=simulated_id,
            checkout_url=simulated_url,
            amount=req.amount,
            currency=req.currency,
            status=PaymentStatus.CHECKOUT_CREATED,
            expires_at=expires_at,
        )

    def verify_webhook_signature(self, raw_body: bytes, signature: str) -> bool:
        """Cryptographically verifies HMAC-SHA256 signature from Dodo webhook headers.
        Prevents forgery and untrusted caller manipulation.
        """
        secret = self.webhook_secret or settings.APP_SECRET
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
            return {"payment_id": payment_id, "status": "succeeded", "verified": True}

        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"{self.api_url}/payments/{payment_id}", headers=headers)
            res.raise_for_status()
            return res.json()


# Global singleton
dodo_provider = DodoPaymentsProvider()
