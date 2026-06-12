"""Add targets to a campaign from endpoints, lead ids, or parsed CSV rows."""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.db.models import Campaign, CampaignLead, Lead, LeadStatus
from backend.services.phone_utils import lab_pjsip_endpoint, normalize_e164

settings = get_settings()


def normalize_dial_endpoint(raw: str) -> str:
    """Accept PJSIP/1002, 1002, or +E164 and return an Asterisk endpoint string."""
    ep = (raw or "").strip()
    if not ep:
        return ep
    if ep.upper().startswith("PJSIP/"):
        return ep
    lab = lab_pjsip_endpoint(ep)
    if lab:
        return lab
    e164 = normalize_e164(ep, settings.outbound_default_country_code)
    if e164:
        return e164
    return ep


async def add_endpoints(db: AsyncSession, campaign: Campaign, endpoints: list[str]) -> int:
    added = 0
    for ep in endpoints:
        ep = normalize_dial_endpoint(ep)
        if not ep:
            continue
        db.add(CampaignLead(campaign_id=campaign.id, endpoint=ep))
        added += 1
    return added


async def add_lead_ids(db: AsyncSession, campaign: Campaign, lead_ids: list[int]) -> int:
    added = 0
    for lid in lead_ids:
        lead = await db.get(Lead, lid)
        if lead:
            db.add(CampaignLead(campaign_id=campaign.id, lead_id=lid))
            added += 1
    return added


async def add_csv_rows(db: AsyncSession, campaign: Campaign, rows: list[dict[str, Any]]) -> int:
    added = 0
    for row in rows:
        endpoint = row.get("endpoint")
        if endpoint:
            db.add(CampaignLead(campaign_id=campaign.id, endpoint=str(endpoint).strip()))
            added += 1
            continue

        phone = row.get("phone")
        name = row.get("name") or (f"CSV {phone}" if phone else "CSV import")
        lead = Lead(
            name=name,
            email=row.get("email"),
            phone=phone,
            phone_e164=row.get("phone_e164")
            or (normalize_e164(phone, settings.outbound_default_country_code) if phone else None),
            company=row.get("company"),
            status=LeadStatus.new,
            notes=f"Imported for campaign #{campaign.id}",
        )
        db.add(lead)
        await db.flush()
        db.add(CampaignLead(campaign_id=campaign.id, lead_id=lead.id))
        added += 1
    return added
