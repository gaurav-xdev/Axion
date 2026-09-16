"""Autonomous Project State Machine.
Enforces deterministic, validated transitions across commercial and execution states.
Arbitrary or skipping mutations are strictly rejected.
"""

from typing import Dict, Set
from packages.observability.logger import logger
from packages.shared.models import ProjectStatus

# Formal transition graph: Current Status -> Set of permitted next Statuses
VALID_TRANSITIONS: Dict[ProjectStatus, Set[ProjectStatus]] = {
    ProjectStatus.DISCOVERED: {ProjectStatus.QUALIFYING, ProjectStatus.REJECTED},
    ProjectStatus.QUALIFYING: {ProjectStatus.QUALIFIED, ProjectStatus.REJECTED, ProjectStatus.ESCALATED},
    ProjectStatus.QUALIFIED: {ProjectStatus.CONTACT_PENDING, ProjectStatus.REJECTED},
    ProjectStatus.CONTACT_PENDING: {ProjectStatus.CONTACTED, ProjectStatus.REJECTED},
    ProjectStatus.CONTACTED: {ProjectStatus.CONVERSATION_ACTIVE, ProjectStatus.EXPIRED},
    ProjectStatus.CONVERSATION_ACTIVE: {ProjectStatus.INTERESTED, ProjectStatus.REJECTED, ProjectStatus.EXPIRED},
    ProjectStatus.INTERESTED: {ProjectStatus.REQUIREMENTS_PENDING, ProjectStatus.REJECTED},
    ProjectStatus.REQUIREMENTS_PENDING: {ProjectStatus.QUOTE_PENDING, ProjectStatus.REJECTED, ProjectStatus.ESCALATED},
    ProjectStatus.QUOTE_PENDING: {ProjectStatus.QUOTE_SENT, ProjectStatus.CANCELLED},
    ProjectStatus.QUOTE_SENT: {ProjectStatus.PAYMENT_PENDING, ProjectStatus.EXPIRED, ProjectStatus.REJECTED},
    ProjectStatus.PAYMENT_PENDING: {ProjectStatus.PAID, ProjectStatus.EXPIRED, ProjectStatus.CANCELLED},
    ProjectStatus.PAID: {ProjectStatus.PLANNING, ProjectStatus.ESCALATED},
    ProjectStatus.PLANNING: {ProjectStatus.EXECUTING, ProjectStatus.BLOCKED},
    ProjectStatus.EXECUTING: {ProjectStatus.QA, ProjectStatus.BLOCKED, ProjectStatus.FAILED},
    ProjectStatus.QA: {ProjectStatus.DELIVERY_PENDING, ProjectStatus.EXECUTING, ProjectStatus.FAILED},  # QA can reject back to EXECUTING
    ProjectStatus.DELIVERY_PENDING: {ProjectStatus.DELIVERED, ProjectStatus.BLOCKED},
    ProjectStatus.DELIVERED: {ProjectStatus.COMPLETED},
    ProjectStatus.COMPLETED: set(),  # Terminal state
    ProjectStatus.REJECTED: set(),
    ProjectStatus.FAILED: {ProjectStatus.PLANNING, ProjectStatus.CANCELLED},
    ProjectStatus.CANCELLED: set(),
    ProjectStatus.ESCALATED: {ProjectStatus.PLANNING, ProjectStatus.CANCELLED},
    ProjectStatus.BLOCKED: {ProjectStatus.PLANNING, ProjectStatus.CANCELLED},
    ProjectStatus.EXPIRED: set(),
}


class ProjectStateMachine:
    @staticmethod
    def can_transition(current: ProjectStatus, target: ProjectStatus) -> bool:
        """Determines if the state transition is valid according to the formal state graph."""
        allowed = VALID_TRANSITIONS.get(current, set())
        return target in allowed

    @staticmethod
    def transition(current: ProjectStatus, target: ProjectStatus) -> ProjectStatus:
        """Executes transition or raises ValueError on violation."""
        if not ProjectStateMachine.can_transition(current, target):
            msg = f"Illegal project state transition from '{current.value}' to '{target.value}'"
            logger.error(msg)
            raise ValueError(msg)
        logger.info(f"Project transitioned from {current.value} -> {target.value}")
        return target
