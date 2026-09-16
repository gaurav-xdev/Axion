"""Server-side payment verification and state unlock engine.
Enforces deduplication, idempotent webhook processing, and project state advancement.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Tuple
from sqlalchemy import select

from packages.observability.logger import logger
from packages.observability.metrics import PAYMENT_EVENTS_TOTAL, PAYMENT_FAILURES_TOTAL
from packages.payments.dodo import dodo_provider
from packages.shared.database import async_session_factory
from packages.shared.models import (
    AuditEvent,
    Checkout,
    Payment,
    PaymentEvent,
    PaymentStatus,
    Project,
    ProjectStatus,
    ToolRiskLevel,
)


class PaymentVerificationService:
    def __init__(self):
        self.provider = dodo_provider

    async def process_webhook(
        self, raw_body: bytes, signature: str, event_data: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """Processes and cryptographically verifies an incoming payment webhook event."""
        event_id = event_data.get("event_id") or event_data.get("id")
        event_type = event_data.get("event_type") or event_data.get("type", "payment.succeeded")

        if not event_id:
            PAYMENT_FAILURES_TOTAL.inc()
            return False, "Missing event_id in webhook payload"

        # 1. Cryptographic Signature Verification
        if not self.provider.verify_webhook_signature(raw_body, signature):
            PAYMENT_FAILURES_TOTAL.inc()
            logger.error(f"Invalid webhook signature for event {event_id}")
            return False, "Invalid cryptographic webhook signature"

        async with async_session_factory() as session:
            # 2. Idempotency & Deduplication Check (Directive 10)
            dup_stmt = select(PaymentEvent).where(PaymentEvent.event_id == event_id)
            existing_event = (await session.execute(dup_stmt)).scalar_one_or_none()

            if existing_event:
                logger.info(f"Payment event '{event_id}' already processed. Returning idempotent success.")
                PAYMENT_EVENTS_TOTAL.labels(event_type=event_type, status="duplicate_ignored").inc()
                return True, "Event already processed (idempotent)"

            # Record Payment Event
            pe = PaymentEvent(
                event_id=event_id,
                event_type=event_type,
                payload_json=event_data,
                signature=signature,
                status="PROCESSING",
            )
            session.add(pe)
            await session.flush()

            # 3. Extract Payment & Project References
            data_payload = event_data.get("data", event_data)
            metadata = data_payload.get("metadata", {})
            project_id = metadata.get("project_id")
            client_id = metadata.get("client_id")
            checkout_id = data_payload.get("checkout_id") or data_payload.get("payment_id")
            amount = float(data_payload.get("amount", 0.0))
            if amount > 100:  # If in cents
                amount = amount / 100.0

            if not project_id:
                # Try locating checkout by ID
                if checkout_id:
                    chk_stmt = select(Checkout).where(Checkout.dodo_checkout_id == checkout_id)
                    chk = (await session.execute(chk_stmt)).scalar_one_or_none()
                    if chk:
                        project_id = chk.project_id
                        client_id = chk.client_id

            if not project_id:
                pe.status = "ORPHANED_NO_PROJECT"
                await session.commit()
                return False, "Could not map payment event to a valid project"

            # 4. Fetch Project & Checkout
            proj = await session.get(Project, project_id)
            if not proj:
                pe.status = "PROJECT_NOT_FOUND"
                await session.commit()
                return False, f"Project '{project_id}' not found"

            # Cross-client validation check (Directive 10)
            if client_id and proj.client_id != client_id:
                pe.status = "CLIENT_MISMATCH_REJECTED"
                await session.commit()
                logger.error(f"Cross-client payment mismatch! Event client {client_id} != Project client {proj.client_id}")
                return False, "Security Violation: Payment client does not match project client"

            # 5. Process Settlement / Success
            if "succeeded" in event_type.lower() or "paid" in event_type.lower():
                # Record Payment
                payment_record = Payment(
                    checkout_id=checkout_id or f"chk_{event_id}",
                    project_id=proj.id,
                    client_id=proj.client_id,
                    dodo_payment_id=data_payload.get("payment_id", event_id),
                    amount=amount or proj.accepted_price,
                    currency=data_payload.get("currency", "USD"),
                    status=PaymentStatus.PAID,
                    payment_method=data_payload.get("payment_method", "card"),
                    verified_at=datetime.now(timezone.utc),
                    metadata_json=data_payload,
                )
                session.add(payment_record)

                # Advance Project State to PAID
                proj.status = ProjectStatus.PAID
                proj.updated_at = datetime.now(timezone.utc)
                pe.status = "PROCESSED_SUCCESS"

                # Audit Event
                audit = AuditEvent(
                    actor="dodo_webhook",
                    action="payment_verified",
                    target_type="project",
                    target_id=proj.id,
                    project_id=proj.id,
                    client_id=proj.client_id,
                    risk_level=ToolRiskLevel.CRITICAL,
                    result="SUCCESS",
                    reason=f"Payment of ${payment_record.amount:.2f} cryptographically verified via Dodo Payments webhook",
                    metadata_json={"event_id": event_id, "dodo_payment_id": payment_record.dodo_payment_id},
                )
                session.add(audit)

                await session.commit()
                PAYMENT_EVENTS_TOTAL.labels(event_type=event_type, status="success").inc()
                logger.info(f"Payment verified for project {proj.id}. Project status advanced to PAID.")
                return True, "Payment verified successfully"

            pe.status = f"IGNORED_{event_type}"
            await session.commit()
            return True, f"Event {event_type} recorded"


# Global singleton
payment_verification_service = PaymentVerificationService()
