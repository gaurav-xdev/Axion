"""Relational domain models built with SQLAlchemy 2.0.
Implements strict foreign key constraints, indexes, unique constraints, and enums.
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Dict, Any

from sqlalchemy import (
    String,
    Text,
    Integer,
    Float,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    Enum as SQLEnum,
    UniqueConstraint,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


# -------------------------------------------------------------------------
# ENUMS
# -------------------------------------------------------------------------

class UserRole(str, Enum):
    OWNER = "OWNER"
    OPERATOR = "OPERATOR"
    AUDITOR = "AUDITOR"
    WORKER_SERVICE = "WORKER_SERVICE"


class ProjectStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    QUALIFYING = "QUALIFYING"
    CONTACT_PENDING = "CONTACT_PENDING"
    CONTACTED = "CONTACTED"
    CONVERSATION_ACTIVE = "CONVERSATION_ACTIVE"
    INTERESTED = "INTERESTED"
    REQUIREMENTS_PENDING = "REQUIREMENTS_PENDING"
    QUALIFIED = "QUALIFIED"
    QUOTE_PENDING = "QUOTE_PENDING"
    QUOTE_SENT = "QUOTE_SENT"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAID = "PAID"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    QA = "QA"
    DELIVERY_PENDING = "DELIVERY_PENDING"
    DELIVERED = "DELIVERED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    ESCALATED = "ESCALATED"
    EXPIRED = "EXPIRED"


class AgentRunStatus(str, Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    BLOCKED = "BLOCKED"
    WAITING = "WAITING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    ESCALATED = "ESCALATED"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    RETRYING = "RETRYING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class ToolRiskLevel(str, Enum):
    READ_ONLY = "READ_ONLY"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class PaymentStatus(str, Enum):
    CHECKOUT_CREATED = "CHECKOUT_CREATED"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAID = "PAID"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    REFUNDED = "REFUNDED"
    CHARGEBACK = "CHARGEBACK"
    CANCELLED = "CANCELLED"


class ChannelType(str, Enum):
    EMAIL = "EMAIL"
    WHATSAPP = "WHATSAPP"
    VOICE = "VOICE"
    SYSTEM = "SYSTEM"


# -------------------------------------------------------------------------
# CORE IDENTITY & ORG
# -------------------------------------------------------------------------

class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    organization_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(SQLEnum(UserRole), default=UserRole.OPERATOR, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    organization_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    company: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    phone: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    projects: Mapped[List["Project"]] = relationship("Project", back_populates="client", cascade="all, delete-orphan")


# -------------------------------------------------------------------------
# PROSPECTING & COMMUNICATION
# -------------------------------------------------------------------------

class Prospect(Base):
    __tablename__ = "prospects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    organization_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)
    business_name: Mapped[str] = mapped_column(String(255), nullable=False)
    website: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    domain: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    industry: Mapped[str] = mapped_column(String(128), default="General", nullable=False)
    qualification_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(String(64), default="DISCOVERED", index=True, nullable=False)
    pain_points: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, default=dict)
    evidence_sources: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, default=dict)
    last_contacted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    opt_out: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    contacts: Mapped[List["Contact"]] = relationship("Contact", back_populates="prospect", cascade="all, delete-orphan")
    conversations: Mapped[List["Conversation"]] = relationship("Conversation", back_populates="prospect")


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    prospect_id: Mapped[str] = mapped_column(String(36), ForeignKey("prospects.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), default="", index=True, nullable=False)
    phone: Mapped[str] = mapped_column(String(64), default="", index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    is_decision_maker: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    opt_out: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    prospect: Mapped["Prospect"] = relationship("Prospect", back_populates="contacts")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    prospect_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("prospects.id", ondelete="SET NULL"), nullable=True)
    client_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("clients.id", ondelete="SET NULL"), nullable=True)
    channel: Mapped[ChannelType] = mapped_column(SQLEnum(ChannelType), default=ChannelType.EMAIL, nullable=False)
    status: Mapped[str] = mapped_column(String(64), default="NEW", nullable=False)
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    prospect: Mapped[Optional["Prospect"]] = relationship("Prospect", back_populates="conversations")
    messages: Mapped[List["Message"]] = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)  # INBOUND or OUTBOUND
    channel: Mapped[ChannelType] = mapped_column(SQLEnum(ChannelType), nullable=False)
    sender: Mapped[str] = mapped_column(String(255), nullable=False)
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    policy_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    delivery_status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")


# -------------------------------------------------------------------------
# PROJECTS, REQUIREMENTS & ESTIMATION
# -------------------------------------------------------------------------

class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    client_id: Mapped[str] = mapped_column(String(36), ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[ProjectStatus] = mapped_column(SQLEnum(ProjectStatus), default=ProjectStatus.DISCOVERED, index=True, nullable=False)
    accepted_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    technical_complexity: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    estimated_effort_hours: Mapped[float] = mapped_column(Float, default=4.0, nullable=False)
    estimated_profit: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    deadline: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    client: Mapped["Client"] = relationship("Client", back_populates="projects")
    requirements: Mapped[List["Requirement"]] = relationship("Requirement", back_populates="project", cascade="all, delete-orphan")
    quotes: Mapped[List["Quote"]] = relationship("Quote", back_populates="project", cascade="all, delete-orphan")
    tasks: Mapped[List["ProjectTask"]] = relationship("ProjectTask", back_populates="project", cascade="all, delete-orphan")
    artifacts: Mapped[List["Artifact"]] = relationship("Artifact", back_populates="project", cascade="all, delete-orphan")


class Requirement(Base):
    __tablename__ = "requirements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(32), default="HIGH", nullable=False)
    acceptance_criteria: Mapped[Optional[List[str]]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    project: Mapped["Project"] = relationship("Project", back_populates="requirements")


class Quote(Base):
    __tablename__ = "quotes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    client_id: Mapped[str] = mapped_column(String(36), ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    scope_summary: Mapped[str] = mapped_column(Text, nullable=False)
    max_revisions: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    project: Mapped["Project"] = relationship("Project", back_populates="quotes")
    checkout: Mapped[Optional["Checkout"]] = relationship("Checkout", back_populates="quote", uselist=False)


# -------------------------------------------------------------------------
# PAYMENTS & TRANSACTIONS
# -------------------------------------------------------------------------

class Checkout(Base):
    __tablename__ = "checkouts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    client_id: Mapped[str] = mapped_column(String(36), ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False)
    quote_id: Mapped[str] = mapped_column(String(36), ForeignKey("quotes.id", ondelete="RESTRICT"), nullable=False)
    dodo_checkout_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    checkout_url: Mapped[str] = mapped_column(String(512), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(SQLEnum(PaymentStatus), default=PaymentStatus.CHECKOUT_CREATED, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    quote: Mapped["Quote"] = relationship("Quote", back_populates="checkout")
    payment: Mapped[Optional["Payment"]] = relationship("Payment", back_populates="checkout", uselist=False)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    checkout_id: Mapped[str] = mapped_column(String(36), ForeignKey("checkouts.id", ondelete="RESTRICT"), unique=True, nullable=False)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    client_id: Mapped[str] = mapped_column(String(36), ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False)
    dodo_payment_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(SQLEnum(PaymentStatus), default=PaymentStatus.PAID, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    checkout: Mapped["Checkout"] = relationship("Checkout", back_populates="payment")


class PaymentEvent(Base):
    __tablename__ = "payment_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    event_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    signature: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PROCESSED", nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


# -------------------------------------------------------------------------
# AGENT RUNTIME & TASKS
# -------------------------------------------------------------------------

class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    project_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    client_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("clients.id", ondelete="SET NULL"), nullable=True)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[AgentRunStatus] = mapped_column(SQLEnum(AgentRunStatus), default=AgentRunStatus.CREATED, index=True, nullable=False)
    step_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tool_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    llm_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    current_task: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    checkpoint_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, default=dict)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    steps: Mapped[List["AgentStep"]] = relationship("AgentStep", back_populates="run", cascade="all, delete-orphan")
    tool_runs: Mapped[List["ToolRun"]] = relationship("ToolRun", back_populates="run", cascade="all, delete-orphan")


class AgentStep(Base):
    __tablename__ = "agent_steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False)
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    thought: Mapped[str] = mapped_column(Text, default="", nullable=False)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    action_payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, default=dict)
    result_payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, default=dict)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    run: Mapped["AgentRun"] = relationship("AgentRun", back_populates="steps")


class ProjectTask(Base):
    __tablename__ = "project_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True)
    worker_type: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    input_payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, default=dict)
    expected_output: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[TaskStatus] = mapped_column(SQLEnum(TaskStatus), default=TaskStatus.PENDING, index=True, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    evidence: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    project: Mapped["Project"] = relationship("Project", back_populates="tasks")


# -------------------------------------------------------------------------
# TOOLS & AUDITING
# -------------------------------------------------------------------------

class ToolRun(Base):
    __tablename__ = "tool_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    run_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True)
    task_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("project_tasks.id", ondelete="SET NULL"), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    input_payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    output_payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, default=dict)
    risk_level: Mapped[ToolRiskLevel] = mapped_column(SQLEnum(ToolRiskLevel), default=ToolRiskLevel.LOW, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="SUCCESS", nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    execution_time_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    run: Mapped[Optional["AgentRun"]] = relationship("AgentRun", back_populates="tool_runs")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(128), nullable=False)
    project_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    client_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    risk_level: Mapped[ToolRiskLevel] = mapped_column(SQLEnum(ToolRiskLevel), default=ToolRiskLevel.LOW, nullable=False)
    result: Mapped[str] = mapped_column(String(32), default="SUCCESS", nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


# -------------------------------------------------------------------------
# ARTIFACTS, QA & VERIFICATION
# -------------------------------------------------------------------------

class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    task_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("project_tasks.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA256
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)  # CODE, REPORT, N8N, MEDIA, DELIVERY
    verification_status: Mapped[str] = mapped_column(String(32), default="UNVERIFIED", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    project: Mapped["Project"] = relationship("Project", back_populates="artifacts")
    qa_runs: Mapped[List["QARun"]] = relationship("QARun", back_populates="artifact", cascade="all, delete-orphan")


class QARun(Base):
    __tablename__ = "qa_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    artifact_id: Mapped[str] = mapped_column(String(36), ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)  # PASSED, FAILED, ESCALATED
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    artifact: Mapped["Artifact"] = relationship("Artifact", back_populates="qa_runs")
    findings: Mapped[List["QAFinding"]] = relationship("QAFinding", back_populates="qa_run", cascade="all, delete-orphan")


class QAFinding(Base):
    __tablename__ = "qa_findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    qa_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("qa_runs.id", ondelete="CASCADE"), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), default="MEDIUM", nullable=False)  # LOW, MEDIUM, HIGH, CRITICAL
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    remediation: Mapped[str] = mapped_column(Text, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    qa_run: Mapped["QARun"] = relationship("QARun", back_populates="findings")


# -------------------------------------------------------------------------
# IDEMPOTENCY & METRICS
# -------------------------------------------------------------------------

class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    key: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    response_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CostRecord(Base):
    __tablename__ = "cost_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    project_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    run_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
