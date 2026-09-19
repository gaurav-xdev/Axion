"""Authoritative Project Delivery Engine.
Enforces the strict QA Gate (Directive 109, 137):
Zero deliverables may be delivered without verified PASSED QA and zero unresolved critical findings.
Generates SHA-256 cryptographic manifests and dispatches client handover.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from sqlalchemy import select

from packages.communications.base import OutboundMessageRequest
from packages.communications.gateway import CommunicationGateway
from packages.observability.logger import logger
from packages.shared.config import settings
from packages.shared.database import async_session_factory
from packages.shared.models import (
    Artifact,
    ChannelType,
    Client,
    Project,
    ProjectStatus,
    QAFinding,
    QARun,
    utc_now,
)
from packages.tools.filesystem import resolve_sandboxed_path


class DeliveryBlockedError(Exception):
    """Raised when delivery is attempted on unverified or defective deliverables."""
    pass


class ProjectDeliveryEngine:
    """Manages verified client handover with cryptographic integrity."""

    def __init__(self, gateway: Optional[CommunicationGateway] = None):
        self._gateway = gateway or CommunicationGateway()

    async def verify_and_deliver(self, project_id: str) -> Dict[str, Any]:
        """Validates QA gate, creates cryptographic manifest, and delivers to client."""
        logger.info(f"Initiating delivery verification pipeline for project {project_id}")

        async with async_session_factory() as session:
            # 1. Fetch project and client
            stmt = select(Project).where(Project.id == project_id)
            project = (await session.execute(stmt)).scalar_one_or_none()
            if not project:
                raise ValueError(f"Project '{project_id}' not found")

            client = await session.get(Client, project.client_id)
            if not client:
                raise ValueError(f"Client for project '{project_id}' not found")

            # 2. Strict QA Gate Verification
            qa_stmt = select(QARun).where(QARun.project_id == project_id)
            qa_runs = (await session.execute(qa_stmt)).scalars().all()

            if not qa_runs:
                raise DeliveryBlockedError(
                    f"Delivery BLOCKED for project '{project_id}': No QA evaluation has been executed."
                )

            passed_runs = [r for r in qa_runs if r.status == "PASSED"]
            if not passed_runs:
                raise DeliveryBlockedError(
                    f"Delivery BLOCKED for project '{project_id}': No QA run has status 'PASSED'. Deliverables unverified."
                )

            # Check for unresolved CRITICAL or HIGH findings
            findings_stmt = select(QAFinding).join(QARun).where(
                QARun.project_id == project_id,
                QAFinding.resolved.is_(False),
                QAFinding.severity.in_(["CRITICAL", "HIGH"]),
            )
            unresolved = (await session.execute(findings_stmt)).scalars().all()
            if unresolved:
                reasons = [f"[{f.severity}] {f.description}" for f in unresolved]
                raise DeliveryBlockedError(
                    f"Delivery BLOCKED for project '{project_id}' due to {len(unresolved)} unresolved defects: "
                    + "; ".join(reasons)
                )

            # 3. Cryptographic Artifact Verification & Manifest Assembly
            art_stmt = select(Artifact).where(Artifact.project_id == project_id)
            artifacts = (await session.execute(art_stmt)).scalars().all()

            manifest_items = []
            for art in artifacts:
                try:
                    disk_path = resolve_sandboxed_path(project_id, art.file_path)
                    if not disk_path.exists() or disk_path.stat().st_size == 0:
                        raise DeliveryBlockedError(
                            f"Delivery BLOCKED: Deliverable '{art.name}' missing from disk at {art.file_path}"
                        )
                    actual_bytes = disk_path.read_bytes()
                    actual_hash = hashlib.sha256(actual_bytes).hexdigest()
                    if actual_hash != art.file_hash:
                        raise DeliveryBlockedError(
                            f"Delivery BLOCKED: Hash mismatch for '{art.name}'. Expected {art.file_hash}, got {actual_hash}"
                        )
                    manifest_items.append({
                        "artifact_id": art.id,
                        "name": art.name,
                        "file_path": art.file_path,
                        "sha256": actual_hash,
                        "size_bytes": len(actual_bytes),
                    })
                except PermissionError as pe:
                    raise DeliveryBlockedError(f"Delivery BLOCKED: Security sandbox violation: {pe}")

            # Assemble manifest
            manifest_payload = {
                "project_id": project_id,
                "project_name": project.name,
                "client_name": client.name,
                "delivered_at": utc_now().isoformat(),
                "qa_status": "VERIFIED_PASSED",
                "verified_artifacts": manifest_items,
            }
            manifest_json = json.dumps(manifest_payload, indent=2)
            manifest_hash = hashlib.sha256(manifest_json.encode("utf-8")).hexdigest()

            # Write manifest to disk
            manifest_path = resolve_sandboxed_path(project_id, "artifacts/delivery_manifest.json")
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(manifest_json, encoding="utf-8")

            # Record delivery manifest artifact
            delivery_art = Artifact(
                project_id=project_id,
                name="delivery_manifest.json",
                file_path="artifacts/delivery_manifest.json",
                file_hash=manifest_hash,
                size_bytes=len(manifest_json.encode("utf-8")),
                artifact_type="DELIVERY",
                verification_status="VERIFIED",
            )
            session.add(delivery_art)

            # 4. Update Project Status to DELIVERED
            project.status = ProjectStatus.DELIVERED
            project.completed_at = utc_now()

            await session.commit()
            client_email = client.email
            proj_name = project.name

        # 5. Outbound Delivery Transmission (outside DB transaction)
        delivery_email_body = (
            f"Dear {client.name},\n\n"
            f"We are pleased to inform you that your project '{proj_name}' has been successfully completed, "
            f"verified through our 5-layer adversarial QA pipeline, and is ready for production use.\n\n"
            f"Project Delivery Summary:\n"
            f"- Project ID: {project_id}\n"
            f"- Verification Status: VERIFIED PASSED\n"
            f"- Artifacts Delivered: {len(manifest_items)}\n"
            f"- Manifest SHA-256: {manifest_hash}\n\n"
            f"All deliverables have been cryptographically verified against tampering and packaged into "
            f"your workspace. Please let us know if you need any operational support.\n\n"
            f"Best regards,\nAxion Autonomous Business Operating Agent"
        )

        outbound_req = OutboundMessageRequest(
            recipient=client_email,
            sender=settings.SMTP_FROM_EMAIL,
            channel=ChannelType.EMAIL,
            subject=f"Deliverable Handover: {proj_name}",
            content=delivery_email_body,
            project_id=project_id,
            client_id=project.client_id,
        )
        dispatch_res = await self._gateway.dispatch(outbound_req)

        logger.info(
            f"Project {project_id} successfully delivered to {client_email} "
            f"(transmission: {dispatch_res.status})"
        )

        return {
            "project_id": project_id,
            "status": "DELIVERED",
            "manifest_sha256": manifest_hash,
            "artifacts_count": len(manifest_items),
            "client_recipient": client_email,
            "notification_status": dispatch_res.status,
            "completed_at": project.completed_at.isoformat(),
        }


# Authoritative singleton
project_delivery_engine = ProjectDeliveryEngine()
