"""Inbound Conversation and Response Management Engine.
Handles ingestion of inbound client communications, intent classification,
state machine transitions, and automated contextual responses.
"""

from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field
from sqlalchemy import select

from packages.communications.base import OutboundMessageRequest
from packages.communications.gateway import CommunicationGateway
from packages.observability.logger import logger
from packages.observability.metrics import MESSAGES_SENT_TOTAL
from packages.shared.database import async_session_factory
from packages.shared.models import (
    ChannelType,
    Client,
    Contact,
    Conversation,
    Message,
    Project,
    ProjectStatus,
    Prospect,
    utc_now,
)


class InboundClassification(str, Enum):
    INTERESTED = "INTERESTED"
    QUESTIONS = "QUESTIONS"
    OBJECTION = "OBJECTION"
    REJECTED = "REJECTED"
    OPT_OUT = "OPT_OUT"
    GENERAL_REPLY = "GENERAL_REPLY"


class InboundMessagePayload(BaseModel):
    sender: str = Field(description="Sender email address or phone number")
    recipient: str = Field(description="Target recipient email or phone")
    channel: ChannelType = Field(default=ChannelType.EMAIL)
    content: str = Field(description="Message body text")
    subject: Optional[str] = Field(default=None)
    raw_headers: Optional[Dict[str, str]] = Field(default=None)
    received_at: datetime = Field(default_factory=utc_now)


class InboundClassificationResult(BaseModel):
    classification: InboundClassification
    confidence: float = 1.0
    reasoning: str = ""
    engine_used: str = "rule_based"


class ConversationReasoningResult(BaseModel):
    classification: InboundClassification
    confidence: float = 1.0
    reasoning: str = ""
    requirements_status: str = "NONE"  # NONE, REQUIREMENTS_PENDING, REQUIREMENTS_COMPLETE
    extracted_requirements: Optional[Any] = None
    client_id: Optional[str] = None
    project_id: Optional[str] = None
    quote_id: Optional[str] = None


class InboundProcessingResult(BaseModel):
    prospect_id: Optional[str] = None
    client_id: Optional[str] = None
    conversation_id: str
    inbound_message_id: str
    classification: InboundClassification
    response_sent: bool
    response_message_id: Optional[str] = None
    suggested_next_action: str
    engine_used: str = "rule_based"
    requirements_status: str = "NONE"
    extracted_requirements: Optional[Any] = None
    project_id: Optional[str] = None
    quote_id: Optional[str] = None
    reasoning: str = ""


class ConversationEngine:
    """Authoritative inbound conversation processing and intent management."""

    def __init__(self, gateway: Optional[CommunicationGateway] = None):
        self._gateway = gateway or CommunicationGateway()

    async def ingest_inbound_message(
        self, payload: InboundMessagePayload
    ) -> InboundProcessingResult:
        """Ingests, classifies, updates state, and generates authoritative replies."""
        logger.info(f"Ingesting inbound message from {payload.sender} via {payload.channel.value}")

        async with async_session_factory() as session:
            # 1. Resolve Contact and Prospect
            contact, prospect, client = await self._resolve_entity(session, payload.sender)

            if not prospect and not client:
                # Create prospect and contact from sender identity
                prospect, contact = await self._create_prospect_from_sender(session, payload.sender)

            prospect_id = prospect.id if prospect else None
            client_id = client.id if client else (contact.prospect.organization_id if contact and contact.prospect else None)

            # 2. Check if contact/prospect has already opted out
            is_opted_out = (contact and contact.opt_out) or (prospect and prospect.opt_out)

            # 3. Find or create active Conversation
            stmt = select(Conversation).where(
                Conversation.channel == payload.channel,
            )
            if prospect_id:
                stmt = stmt.where(Conversation.prospect_id == prospect_id)
            elif client_id:
                stmt = stmt.where(Conversation.client_id == client_id)

            conversation = (await session.execute(stmt)).scalars().first()
            if not conversation:
                conversation = Conversation(
                    prospect_id=prospect_id,
                    client_id=client_id,
                    channel=payload.channel,
                    status="NEW",
                    last_message_at=payload.received_at,
                )
                session.add(conversation)
                await session.flush()

            # 4. Idempotency / Duplicate Ingestion Check
            content_hash = hashlib.sha256(payload.content.strip().encode("utf-8")).hexdigest()
            recent_cutoff = payload.received_at - timedelta(minutes=10)
            dup_stmt = select(Message).where(
                Message.conversation_id == conversation.id,
                Message.direction == "INBOUND",
                Message.content_hash == content_hash,
                Message.created_at >= recent_cutoff,
            )
            duplicate_msg = (await session.execute(dup_stmt)).scalars().first()
            if duplicate_msg:
                logger.warning(f"Duplicate inbound message detected for conversation {conversation.id}")
                return InboundProcessingResult(
                    prospect_id=prospect_id,
                    client_id=client_id,
                    conversation_id=conversation.id,
                    inbound_message_id=duplicate_msg.id,
                    classification=InboundClassification.GENERAL_REPLY,
                    response_sent=False,
                    suggested_next_action="IGNORE_DUPLICATE",
                )

            # 5. Persist Inbound Message
            inbound_msg = Message(
                conversation_id=conversation.id,
                direction="INBOUND",
                channel=payload.channel,
                sender=payload.sender,
                recipient=payload.recipient,
                content=payload.content,
                content_hash=content_hash,
                policy_approved=True,
                delivery_status="RECEIVED",
                sent_at=payload.received_at,
            )
            session.add(inbound_msg)
            conversation.last_message_at = payload.received_at

            # 6. Intent Classification
            class_res = await self.classify_intent_with_reasoning(payload.content)
            classification = class_res.classification
            if is_opted_out and classification != InboundClassification.OPT_OUT:
                classification = InboundClassification.OPT_OUT

            # 7. Update Prospect & Conversation State
            await self._apply_state_transitions(
                session,
                conversation=conversation,
                prospect=prospect,
                contact=contact,
                classification=classification,
            )

            await session.commit()
            inbound_id = inbound_msg.id
            conv_id = conversation.id

        # 8. Structured Reasoning for Inbound Commercial Inquiry
        reasoning_res: Optional[ConversationReasoningResult] = None
        if classification == InboundClassification.INTERESTED:
            reasoning_res = await self.reason_over_inbound_inquiry(
                sender=payload.sender,
                content=payload.content,
                source_message_id=inbound_id,
                prospect_id=prospect_id,
                client_id=client_id,
            )
            if reasoning_res.client_id:
                client_id = reasoning_res.client_id

        # 9. Generate and Dispatch Contextual Reply (outside session block)
        reply_content, next_action = self._compose_reply_text(classification, payload.sender)
        if reasoning_res and reasoning_res.requirements_status == "REQUIREMENTS_COMPLETE" and reasoning_res.quote_id:
            next_action = "PROPOSE_QUOTE"

        response_sent = False
        response_msg_id = None

        if reply_content:
            outbound_req = OutboundMessageRequest(
                recipient=payload.sender,
                sender=payload.recipient,
                channel=payload.channel,
                subject=f"Re: {payload.subject}" if payload.subject else "Response from Axion Support",
                content=reply_content,
                prospect_id=prospect_id,
                client_id=client_id,
                conversation_id=conv_id,
            )
            dispatch_res = await self._gateway.dispatch(outbound_req)
            response_sent = dispatch_res.success
            response_msg_id = dispatch_res.message_id

        return InboundProcessingResult(
            prospect_id=prospect_id,
            client_id=client_id,
            conversation_id=conv_id,
            inbound_message_id=inbound_id,
            classification=classification,
            response_sent=response_sent,
            response_message_id=response_msg_id,
            suggested_next_action=next_action,
            engine_used=class_res.engine_used,
            requirements_status=reasoning_res.requirements_status if reasoning_res else "NONE",
            extracted_requirements=reasoning_res.extracted_requirements if reasoning_res else None,
            project_id=reasoning_res.project_id if reasoning_res else None,
            quote_id=reasoning_res.quote_id if reasoning_res else None,
            reasoning=reasoning_res.reasoning if reasoning_res else class_res.reasoning,
        )

    async def classify_intent_with_reasoning(self, content: str) -> InboundClassificationResult:
        """Classifies intent using structured LLM reasoning if configured, falling back to rule-based classification."""
        from packages.shared.config import settings
        if settings.NIM_API_KEY:
            try:
                from packages.llm.router import llm_router
                prompt = (
                    f"Classify the commercial intent of this inbound message into one of: "
                    f"OPT_OUT, REJECTED, INTERESTED, OBJECTION, QUESTIONS, GENERAL_REPLY.\n"
                    f"Message: {content}\n"
                    f"Respond ONLY with valid JSON: {{\"classification\": \"...\", \"confidence\": 0.95, \"reasoning\": \"...\"}}"
                )
                res = await llm_router.generate(prompt, temperature=0.1)
                import json
                cleaned = res.strip("` \n").removeprefix("json")
                parsed = json.loads(cleaned)
                c_str = parsed.get("classification", "").upper()
                if c_str in InboundClassification.__members__:
                    return InboundClassificationResult(
                        classification=InboundClassification[c_str],
                        confidence=float(parsed.get("confidence", 0.9)),
                        reasoning=str(parsed.get("reasoning", "")),
                        engine_used="llm",
                    )
            except Exception as e:
                logger.warning(f"LLM intent classification fallback to rule-based: {e}")

        # Deterministic rule-based classification
        rule_class = self.classify_intent(content)
        return InboundClassificationResult(
            classification=rule_class,
            confidence=1.0,
            reasoning=f"Matched deterministic patterns for {rule_class.value}",
            engine_used="rule_based",
        )

    def classify_intent(self, content: str) -> InboundClassification:
        """Deterministically classifies message content using comprehensive intent patterns."""
        normalized = content.lower().strip()

        # 1. OPT-OUT
        opt_out_patterns = [
            r"\bunsubscribe\b",
            r"\bstop\b",
            r"\bopt[- ]out\b",
            r"\bremove me\b",
            r"\bleave me alone\b",
            r"\bdo not contact\b",
            r"\bdo not email\b",
            r"\bdon't contact\b",
            r"\bcease\b",
        ]
        if any(re.search(pat, normalized) for pat in opt_out_patterns):
            return InboundClassification.OPT_OUT

        # 2. REJECTED
        rejected_patterns = [
            r"\bnot interested\b",
            r"\bno thanks\b",
            r"\bpass\b",
            r"\bno need\b",
            r"\bnot looking\b",
            r"\bdon't need\b",
            r"\bnever contact\b",
            r"\bwe are happy with\b",
        ]
        if any(re.search(pat, normalized) for pat in rejected_patterns):
            return InboundClassification.REJECTED

        # 3. INTERESTED / READY TO BUY
        interested_patterns = [
            r"\binterested\b",
            r"\blet's talk\b",
            r"\blets talk\b",
            r"\bsend (a )?quote\b",
            r"\bsend (a )?proposal\b",
            r"\bpricing quote\b",
            r"\bschedule (a )?call\b",
            r"\bhow do we proceed\b",
            r"\bhow to proceed\b",
            r"\bnext steps\b",
            r"\blet's do it\b",
            r"\bsounds good\b",
            r"\bcan you build\b",
            r"\bcan you implement\b",
            r"\bwe need help with\b",
            r"\bwe need\b",
            r"\bneed a\b",
            r"\bneed an\b",
            r"\blooking to\b",
            r"\blooking for\b",
            r"\bwant to build\b",
            r"\brequire\b",
        ]
        if any(re.search(pat, normalized) for pat in interested_patterns):
            return InboundClassification.INTERESTED

        # 4. OBJECTION
        objection_patterns = [
            r"\btoo expensive\b",
            r"\bout of (our )?budget\b",
            r"\bover budget\b",
            r"\bcan you do better on price\b",
            r"\bdiscount\b",
            r"\bcannot afford\b",
            r"\bprice is high\b",
        ]
        if any(re.search(pat, normalized) for pat in objection_patterns):
            return InboundClassification.OBJECTION

        # 5. QUESTIONS / INQUIRY
        question_patterns = [
            r"\bhow much\b",
            r"\bcost\b",
            r"\bpricing\b",
            r"\brate\b",
            r"\bhow long\b",
            r"\btimeline\b",
            r"\bdo you support\b",
            r"\bcan you integrate\b",
            r"\bwhat stack\b",
            r"\bhow does it work\b",
            r"\btell me more\b",
            r"\?",
        ]
        if any(re.search(pat, normalized) for pat in question_patterns):
            return InboundClassification.QUESTIONS

        return InboundClassification.GENERAL_REPLY

    async def _resolve_entity(
        self, session, sender: str
    ) -> Tuple[Optional[Contact], Optional[Prospect], Optional[Client]]:
        """Resolves existing Contact, Prospect, or Client matching sender."""
        # 1. Check Contact table
        stmt_c = select(Contact).where(
            (Contact.email == sender) | (Contact.phone == sender)
        )
        contact = (await session.execute(stmt_c)).scalars().first()
        if contact:
            stmt_p = select(Prospect).where(Prospect.id == contact.prospect_id)
            prospect = (await session.execute(stmt_p)).scalars().first()
            return (contact, prospect, None)

        # 2. Check Client table
        stmt_cl = select(Client).where(
            (Client.email == sender) | (Client.phone == sender)
        )
        client = (await session.execute(stmt_cl)).scalars().first()
        if client:
            return (None, None, client)

        # 3. Check domain match on Prospect
        if "@" in sender:
            domain = sender.split("@")[-1].strip().lower()
            stmt_p = select(Prospect).where(Prospect.domain == domain)
            prospect = (await session.execute(stmt_p)).scalars().first()
            if prospect:
                return (None, prospect, None)

        return (None, None, None)

    async def _create_prospect_from_sender(
        self, session, sender: str
    ) -> Tuple[Prospect, Contact]:
        """Creates a new prospect and contact record for an unknown inbound sender."""
        domain = sender.split("@")[-1].strip().lower() if "@" in sender else "inbound.phone"
        clean_name = sender.split("@")[0].replace(".", " ").title() if "@" in sender else sender

        prospect = Prospect(
            business_name=f"{clean_name} Business",
            domain=domain,
            website=f"https://{domain}" if "@" in sender else "",
            status="CONVERSATION_ACTIVE",
            qualification_score=0.7,
        )
        session.add(prospect)
        await session.flush()

        contact = Contact(
            prospect_id=prospect.id,
            name=clean_name,
            email=sender if "@" in sender else "",
            phone=sender if "@" not in sender else "",
            role="Lead",
            is_decision_maker=True,
        )
        session.add(contact)
        await session.flush()

        return (prospect, contact)

    async def _apply_state_transitions(
        self,
        session,
        conversation: Conversation,
        prospect: Optional[Prospect],
        contact: Optional[Contact],
        classification: InboundClassification,
    ) -> None:
        """Applies authoritative state machine transitions based on intent classification."""
        if classification == InboundClassification.OPT_OUT:
            conversation.status = "OPT_OUT"
            if contact:
                contact.opt_out = True
            if prospect:
                prospect.opt_out = True
                prospect.status = "OPT_OUT"

        elif classification == InboundClassification.REJECTED:
            conversation.status = "REJECTED"
            if prospect and prospect.status not in ("PAID", "COMPLETED"):
                prospect.status = "REJECTED"

        elif classification == InboundClassification.INTERESTED:
            conversation.status = "INTERESTED"
            if prospect and prospect.status not in ("PAID", "EXECUTING", "COMPLETED"):
                prospect.status = "INTERESTED"

        elif classification == InboundClassification.QUESTIONS:
            conversation.status = "QUESTIONS"
            if prospect and prospect.status in ("DISCOVERED", "CONTACT_PENDING", "CONTACTED"):
                prospect.status = "CONVERSATION_ACTIVE"

        elif classification == InboundClassification.OBJECTION:
            conversation.status = "OBJECTION"
            if prospect and prospect.status in ("DISCOVERED", "CONTACT_PENDING", "CONTACTED"):
                prospect.status = "CONVERSATION_ACTIVE"

        else:
            conversation.status = "CONVERSATION_ACTIVE"
            if prospect and prospect.status in ("DISCOVERED", "CONTACT_PENDING", "CONTACTED"):
                prospect.status = "CONVERSATION_ACTIVE"

    def _compose_reply_text(
        self, classification: InboundClassification, recipient: str
    ) -> Tuple[Optional[str], str]:
        """Composes contextual, compliant response text."""
        if classification == InboundClassification.OPT_OUT:
            text = (
                "You have been successfully unsubscribed from all future communications. "
                "No further messages will be sent to this address."
            )
            return (text, "CLOSE_CONVERSATION")

        elif classification == InboundClassification.REJECTED:
            text = (
                "Thank you for letting us know. We appreciate your time and have noted your preference. "
                "Best regards."
            )
            return (text, "CLOSE_CONVERSATION")

        elif classification == InboundClassification.INTERESTED:
            text = (
                "Thank you for your interest! We can certainly help streamline and automate this workflow.\n\n"
                "To prepare an exact, fixed-price quote and timeline, could you briefly share:\n"
                "1. The primary systems/tools you need integrated (e.g., CRM, Webhooks, Google Sheets, Stripe)\n"
                "2. Any specific business rules or triggers required\n"
                "3. Your target completion date\n\n"
                "Once confirmed, we will generate a formal proposal and delivery roadmap."
            )
            return (text, "GATHER_REQUIREMENTS")

        elif classification == InboundClassification.QUESTIONS:
            text = (
                "Hello, thanks for reaching out!\n\n"
                "We provide autonomous engineering and integration services, including custom API clients, "
                "n8n automation pipelines, serverless webhooks, and monitoring dashboards.\n\n"
                "Our turnaround time is typically 3-5 business days with fixed pricing and 5-layer adversarial QA verification.\n\n"
                "Please let us know what specific integration or automation you have in mind and we'll provide details."
            )
            return (text, "AWAIT_CLIENT_DETAILS")

        elif classification == InboundClassification.OBJECTION:
            text = (
                "We completely understand budget constraints and want to ensure you get a high-return solution. "
                "We can phase the implementation or focus exclusively on the core high-impact automation "
                "to fit within your required budget.\n\n"
                "Would you like us to outline a simplified initial scope?"
            )
            return (text, "NEGOTIATE_BOUNDED_SCOPE")

        else:
            text = (
                "Thank you for your message. An engineer has received your note and will follow up shortly with details."
            )
            return (text, "CONTINUE_CONVERSATION")

    async def reason_over_inbound_inquiry(
        self,
        sender: str,
        content: str,
        source_message_id: Optional[str] = None,
        prospect_id: Optional[str] = None,
        client_id: Optional[str] = None,
    ) -> ConversationReasoningResult:
        """Reasons over inbound client inquiry to determine whether requirements are pending or complete,
        and provisions Client, Project, and Authoritative Quote only when requirements are concrete.
        """
        from packages.projects.negotiation import requirements_extractor, negotiation_engine
        from packages.projects.acceptance import project_acceptance_engine, ProjectAssessmentRequest

        extracted = requirements_extractor.extract(content, source_message_id=source_message_id)

        # Check if client has provided concrete implementation specifications or is asking initial inquiry
        has_detailed_spec = any(k in content.lower() for k in ["endpoint", "payload", "schema", "header", "secret", "fastapi", "database", "webhook receiver"]) and len(content.split()) >= 8
        if not has_detailed_spec or not extracted.ready_for_quote or len(extracted.deliverables) < 2:
            return ConversationReasoningResult(
                classification=InboundClassification.INTERESTED,
                confidence=0.85,
                reasoning=f"Identified interest; gathering specifications and constraints before formal quote.",
                requirements_status="REQUIREMENTS_PENDING",
                extracted_requirements=extracted,
                client_id=client_id,
                project_id=None,
                quote_id=None,
            )

        # Requirements are complete enough for client onboarding & quote
        async with async_session_factory() as session:
            # Resolve or create Client
            resolved_client_id = client_id
            if resolved_client_id:
                client = await session.get(Client, resolved_client_id)
            else:
                stmt_c = select(Client).where(Client.email == sender)
                client = (await session.execute(stmt_c)).scalars().first()

            if not client:
                company_name = None
                if prospect_id:
                    prosp = await session.get(Prospect, prospect_id)
                    if prosp:
                        company_name = prosp.business_name
                clean_name = sender.split("@")[0].replace(".", " ").title() if "@" in sender else "Client"
                client = Client(
                    name=clean_name,
                    email=sender,
                    company=company_name or clean_name,
                )
                session.add(client)
                await session.flush()
            resolved_client_id = client.id

            # Create Project
            # Create Project
            project = Project(
                client_id=resolved_client_id,
                name=extracted.project_title,
                description=f"Autonomous project for {extracted.project_title} derived from client requirements",
                status=ProjectStatus.CONVERSATION_ACTIVE,
            )
            session.add(project)
            await session.commit()
            resolved_project_id = project.id

        # Evaluate project feasibility
        assessment = project_acceptance_engine.evaluate(
            ProjectAssessmentRequest(
                title=extracted.project_title,
                description=content[:200],
                requested_price=0.0,
                estimated_effort_hours=extracted.estimated_effort_hours,
                integration_count=extracted.estimated_integration_count,
                known_requirements=extracted.deliverables,
            )
        )

        # Create Authoritative Quote
        quote = await negotiation_engine.create_authoritative_quote(
            project_id=resolved_project_id,
            client_id=resolved_client_id,
            amount=assessment.quoted_price,
            scope_summary=f"Deliverables for {extracted.project_title}",
            requirements=extracted.tagged_requirements or extracted.deliverables,
            max_revisions=assessment.max_revisions,
            valid_days=7,
        )
        resolved_quote_id = quote.id

        return ConversationReasoningResult(
            classification=InboundClassification.INTERESTED,
            confidence=1.0,
            reasoning="Requirements concrete; Client, Project, and Authoritative Quote successfully established.",
            requirements_status="REQUIREMENTS_COMPLETE",
            extracted_requirements=extracted,
            client_id=resolved_client_id,
            project_id=resolved_project_id,
            quote_id=resolved_quote_id,
        )


# Authoritative singleton conversation engine
conversation_engine = ConversationEngine()
