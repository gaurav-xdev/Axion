"""Prospecting and Market Research Engine.
Discovers, normalizes, deduplicates, scores, and qualifies business prospects.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from pydantic import BaseModel, Field
from sqlalchemy import select

from packages.observability.logger import logger
from packages.shared.database import async_session_factory
from packages.shared.models import Contact, Prospect


class ProspectData(BaseModel):
    business_name: str
    website: str
    industry: str = "Technology"
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    observed_pain_points: List[str] = Field(default_factory=list)
    evidence_urls: List[str] = Field(default_factory=list)


def normalize_domain(url: str) -> str:
    """Normalize web URL to bare canonical domain (e.g. https://www.example.com/page -> example.com)."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


class ProspectingEngine:
    def __init__(self):
        pass

    def calculate_qualification_score(self, prospect: ProspectData) -> float:
        """Scores commercial opportunity [0.0 - 1.0] based on verifiable attributes."""
        score = 0.2  # Baseline discovery score

        # Has reachable website
        if prospect.website and "." in prospect.website:
            score += 0.2

        # Has identified decision maker or contact info
        if prospect.contact_email and "@" in prospect.contact_email:
            score += 0.3
        elif prospect.contact_name:
            score += 0.15

        # Has verifiable observed pain points
        if prospect.observed_pain_points:
            score += min(len(prospect.observed_pain_points) * 0.15, 0.3)

        return min(round(score, 2), 1.0)

    async def ingest_prospect(self, data: ProspectData) -> Prospect:
        """Atomically checks for duplicate domains, scores, and persists prospect."""
        domain = normalize_domain(data.website)
        score = self.calculate_qualification_score(data)

        async with async_session_factory() as session:
            # Deduplication check
            stmt = select(Prospect).where(Prospect.domain == domain)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                logger.info(f"Prospect with domain '{domain}' already exists. Updating score.")
                existing.qualification_score = max(existing.qualification_score, score)
                existing.updated_at = datetime.now(timezone.utc)
                await session.commit()
                await session.refresh(existing)
                return existing

            # Create new prospect
            new_prospect = Prospect(
                business_name=data.business_name,
                website=data.website,
                domain=domain,
                industry=data.industry,
                qualification_score=score,
                status="QUALIFIED" if score >= 0.6 else "DISCOVERED",
                pain_points={"points": data.observed_pain_points},
                evidence_sources={"urls": data.evidence_urls, "discovered_at": datetime.now(timezone.utc).isoformat()},
            )
            session.add(new_prospect)
            await session.flush()

            # Add contact if provided
            if data.contact_name or data.contact_email:
                contact = Contact(
                    prospect_id=new_prospect.id,
                    name=data.contact_name or "Contact Person",
                    email=data.contact_email or "",
                    is_decision_maker=True if data.contact_name else False,
                )
                session.add(contact)

            await session.commit()
            await session.refresh(new_prospect)
            logger.info(f"Created prospect '{new_prospect.business_name}' with score {score}")
            return new_prospect


# Global singleton
prospecting_engine = ProspectingEngine()
