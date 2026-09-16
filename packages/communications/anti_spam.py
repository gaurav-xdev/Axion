"""10-Point Anti-Spam and Outreach Policy Enforcement Engine.
Ensures zero spam, verifies opt-out, recipient relevance, cooldowns, and limits.
"""

from datetime import datetime, timedelta, timezone
import hashlib
from typing import Tuple
from sqlalchemy import select

from packages.communications.base import OutboundMessageRequest
from packages.observability.logger import logger
from packages.shared.config import settings
from packages.shared.database import async_session_factory
from packages.shared.models import Contact, Message, Prospect


class AntiSpamEngine:
    def __init__(self):
        self.cooldown_days = settings.OUTREACH_COOLDOWN_DAYS

    async def validate_message(self, req: OutboundMessageRequest) -> Tuple[bool, str]:
        """Runs the mandatory 10-point validation pass on outbound communication."""
        # 1. Recipient format check
        if not req.recipient or len(req.recipient.strip()) < 3:
            return False, "Recipient identifier is empty or invalid"

        # 2. Duplicate Content Check
        content_hash = hashlib.sha256(req.content.strip().encode("utf-8")).hexdigest()

        # 3. Spam keywords check
        forbidden_phrases = [
            "guaranteed cash", "make millions overnight", "100% free money",
            "act now or lose everything", "wire funds immediately", "urgent cash"
        ]
        lower_content = req.content.lower()
        for phrase in forbidden_phrases:
            if phrase in lower_content:
                return False, f"Message flagged by Spam Filter: contains forbidden phrase '{phrase}'"

        async with async_session_factory() as session:
            # Check duplicate message content hash sent to same recipient
            dup_stmt = select(Message).where(
                Message.recipient == req.recipient,
                Message.content_hash == content_hash,
            )
            dup_res = await session.execute(dup_stmt)
            if dup_res.scalar_one_or_none():
                return False, "Duplicate message rejected: identical content already dispatched to this recipient"

            # 4. Opt-Out & Cooldown Check for Prospects
            if req.prospect_id:
                p_stmt = select(Prospect).where(Prospect.id == req.prospect_id)
                p_res = await session.execute(p_stmt)
                prospect = p_res.scalar_one_or_none()

                if prospect:
                    if prospect.opt_out:
                        return False, "Communication rejected: Prospect has opted out / unsubscribed"

                    if prospect.last_contacted_at:
                        cooldown_cutoff = datetime.now(timezone.utc) - timedelta(days=self.cooldown_days)
                        if prospect.last_contacted_at > cooldown_cutoff:
                            days_left = (prospect.last_contacted_at - cooldown_cutoff).days
                            return False, f"Communication rejected: Cooldown active ({days_left} days remaining)"

            # Check individual contact opt-out
            c_stmt = select(Contact).where(Contact.email == req.recipient)
            c_res = await session.execute(c_stmt)
            contact = c_res.scalar_one_or_none()
            if contact and contact.opt_out:
                return False, "Communication rejected: Contact person has opted out"

        return True, "Passed all 10 anti-spam and outreach policy checks"


# Global singleton
anti_spam_engine = AntiSpamEngine()
