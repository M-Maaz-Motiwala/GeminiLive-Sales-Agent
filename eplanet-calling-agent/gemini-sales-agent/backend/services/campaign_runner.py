"""Background campaign dialer — fleet of sales agents with per-agent cooldown."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.db.database import AsyncSessionLocal
from backend.db.models import (
    Agent,
    Campaign,
    CampaignLead,
    CampaignLeadStatus,
    CampaignStatus,
    Lead,
    Session as DBSession,
    SessionStatus,
)
from backend.services.bridge_client import bridge_status
from backend.services.callback_router import busy_agent_ids
from backend.services.outbound_dialer import dial_one
from backend.services.platform_settings import get_platform_setting

logger = logging.getLogger(__name__)

POLL_SEC = 2.0
DIAL_SETUP_GRACE_SEC = 45.0
DEFAULT_INTER_CALL_DELAY_SEC = 30
_tasks: dict[int, asyncio.Task] = {}


def _bridge_channel_ids(bridge: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for row in bridge.get("calls") or []:
        cid = row.get("channel_id") or row.get("human_channel_id")
        if cid:
            ids.add(cid)
    return ids


def campaign_agent_ids(campaign: Campaign) -> list[int]:
    meta = campaign.meta or {}
    ids = meta.get("agent_ids")
    if isinstance(ids, list) and ids:
        return [int(x) for x in ids]
    return [int(campaign.agent_id)]


def campaign_inter_call_delay(campaign: Campaign) -> float:
    meta = campaign.meta or {}
    delay = meta.get("inter_call_delay_sec")
    if delay is None:
        runner = meta.get("runner") or {}
        delay = runner.get("inter_call_delay_sec")
    try:
        return max(0.0, float(delay if delay is not None else DEFAULT_INTER_CALL_DELAY_SEC))
    except (TypeError, ValueError):
        return float(DEFAULT_INTER_CALL_DELAY_SEC)


def _normalize_active_dials(raw: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(raw, dict):
        return out
    for cl_id, val in raw.items():
        if isinstance(val, str):
            out[str(cl_id)] = {
                "channel_id": val,
                "started_at": time.monotonic(),
                "seen_live": False,
            }
        elif isinstance(val, dict) and val.get("channel_id"):
            out[str(cl_id)] = {
                "channel_id": val["channel_id"],
                "started_at": float(val.get("started_at") or time.monotonic()),
                "seen_live": bool(val.get("seen_live")),
                "agent_id": val.get("agent_id"),
            }
    return out


def is_runner_active(campaign_id: int) -> bool:
    task = _tasks.get(campaign_id)
    return task is not None and not task.done()


async def stop_runner(campaign_id: int) -> None:
    task = _tasks.pop(campaign_id, None)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def start_runner(
    campaign_id: int,
    *,
    max_parallel: int,
    scheduled_at: Optional[datetime] = None,
) -> None:
    await stop_runner(campaign_id)
    _tasks[campaign_id] = asyncio.create_task(
        _run_loop(campaign_id, max_parallel=max_parallel, scheduled_at=scheduled_at),
        name=f"campaign-runner-{campaign_id}",
    )


def _runner_meta(campaign: Campaign) -> dict[str, Any]:
    meta = dict(campaign.meta or {})
    runner = dict(meta.get("runner") or {})
    meta["runner"] = runner
    return meta


async def _attach_session_for_channel(
    db, campaign_lead: CampaignLead, channel_id: str
) -> None:
    if campaign_lead.session_id:
        return
    result = await db.execute(
        select(DBSession).order_by(DBSession.id.desc()).limit(100)
    )
    for sess in result.scalars():
        if (sess.meta or {}).get("channel_id") == channel_id:
            campaign_lead.session_id = sess.id
            return


def _set_agent_cooldown(
    runner: dict[str, Any], agent_id: int, delay_sec: float
) -> None:
    agent_state = runner.setdefault("agent_state", {})
    agent_state[str(agent_id)] = {
        "status": "cooldown",
        "cooldown_until": time.monotonic() + delay_sec,
    }


def _available_fleet_agents(
    agent_ids: list[int],
    active_dials: dict[str, dict[str, Any]],
    runner: dict[str, Any],
    extra_busy: set[int],
) -> list[int]:
    now = time.monotonic()
    busy = set(extra_busy)
    for info in active_dials.values():
        aid = info.get("agent_id")
        if aid is not None:
            busy.add(int(aid))

    agent_state = runner.get("agent_state") or {}
    available: list[int] = []
    for aid in agent_ids:
        if aid in busy:
            continue
        st = agent_state.get(str(aid)) or {}
        if float(st.get("cooldown_until") or 0) > now:
            continue
        available.append(aid)
    return available


async def _reconcile_active(
    db,
    campaign: Campaign,
    active_dials: dict[str, dict[str, Any]],
    bridge_channels: set[str],
    inter_call_delay: float,
    runner: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    now = time.monotonic()
    for cl_id, info in list(active_dials.items()):
        channel_id = info.get("channel_id")
        if not channel_id:
            active_dials.pop(cl_id, None)
            continue

        if channel_id in bridge_channels:
            info["seen_live"] = True
            continue

        age = now - float(info.get("started_at") or now)
        seen_live = bool(info.get("seen_live"))

        if not seen_live and age < DIAL_SETUP_GRACE_SEC:
            continue

        cl = await db.get(CampaignLead, int(cl_id))
        if cl and cl.status == CampaignLeadStatus.dialing:
            if seen_live:
                cl.status = CampaignLeadStatus.completed
                await _attach_session_for_channel(db, cl, channel_id)
            else:
                cl.status = CampaignLeadStatus.failed
                cl.last_error = "Call never connected on bridge (timeout)"
        aid = info.get("agent_id")
        if aid is not None:
            _set_agent_cooldown(runner, int(aid), inter_call_delay)
        active_dials.pop(cl_id, None)
    return active_dials


async def _fill_slots(
    db,
    campaign: Campaign,
    agent_ids: list[int],
    active_dials: dict[str, dict[str, Any]],
    max_parallel: int,
    inter_call_delay: float,
    runner: dict[str, Any],
    extra_busy: set[int],
    platform_available: int = 50,
) -> dict[str, dict[str, Any]]:
    slots = min(max_parallel - len(active_dials), platform_available)
    if slots <= 0:
        return active_dials

    available_agents = _available_fleet_agents(
        agent_ids, active_dials, runner, extra_busy
    )
    if not available_agents:
        return active_dials

    result = await db.execute(
        select(CampaignLead)
        .where(
            CampaignLead.campaign_id == campaign.id,
            CampaignLead.status == CampaignLeadStatus.pending,
        )
        .order_by(CampaignLead.id)
        .limit(min(slots, len(available_agents)))
    )
    pending = list(result.scalars().all())
    if not pending:
        return active_dials

    for cl, agent_id in zip(pending, available_agents):
        agent = await db.get(Agent, agent_id)
        if not agent:
            continue
        lead = await db.get(Lead, cl.lead_id) if cl.lead_id else None
        cl.status = CampaignLeadStatus.dialing
        cl.dialed_at = datetime.now(timezone.utc)
        try:
            resp = await dial_one(
                db,
                agent=agent,
                lead=lead,
                lead_id=cl.lead_id,
                endpoint=cl.endpoint,
                campaign_lead_id=cl.id,
                owner_id=campaign.owner_id,
            )
            channel_id = (resp.get("bridge") or {}).get("channel_id")
            if channel_id:
                active_dials[str(cl.id)] = {
                    "channel_id": channel_id,
                    "agent_id": agent.id,
                    "started_at": time.monotonic(),
                    "seen_live": False,
                }
                agent_state = runner.setdefault("agent_state", {})
                agent_state[str(agent.id)] = {"status": "dialing"}
                logger.info(
                    "Campaign %s agent=%s lead=%s endpoint=%s channel=%s",
                    campaign.id,
                    agent.slug,
                    cl.id,
                    cl.endpoint,
                    channel_id,
                )
            else:
                cl.status = CampaignLeadStatus.failed
                cl.last_error = "Originate returned no channel id"
                _set_agent_cooldown(runner, agent.id, inter_call_delay)
        except Exception as exc:
            cl.status = CampaignLeadStatus.failed
            cl.last_error = str(exc)
            _set_agent_cooldown(runner, agent.id, inter_call_delay)
            logger.warning(
                "Campaign %s lead %s dial failed: %s", campaign.id, cl.id, exc
            )
    return active_dials


async def _run_loop(
    campaign_id: int,
    *,
    max_parallel: int,
    scheduled_at: Optional[datetime],
) -> None:
    logger.info(
        "Campaign runner started id=%s parallel=%s scheduled=%s",
        campaign_id,
        max_parallel,
        scheduled_at,
    )
    try:
        while True:
            if scheduled_at:
                now = datetime.now(timezone.utc)
                sched = scheduled_at
                if sched.tzinfo is None:
                    sched = sched.replace(tzinfo=timezone.utc)
                if now < sched:
                    await asyncio.sleep(1.0)
                    continue

            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Campaign)
                    .where(Campaign.id == campaign_id)
                    .options(selectinload(Campaign.campaign_leads))
                )
                campaign = result.scalar_one_or_none()
                if not campaign:
                    break

                if campaign.status == CampaignStatus.paused:
                    await db.commit()
                    await asyncio.sleep(POLL_SEC)
                    continue

                if campaign.status != CampaignStatus.running:
                    break

                agent_ids = campaign_agent_ids(campaign)
                if not agent_ids:
                    campaign.status = CampaignStatus.paused
                    await db.commit()
                    break

                inter_call_delay = campaign_inter_call_delay(campaign)
                meta = _runner_meta(campaign)
                runner = meta["runner"]
                runner["max_parallel"] = max_parallel
                runner["inter_call_delay_sec"] = inter_call_delay
                runner["agent_ids"] = agent_ids
                active_dials = _normalize_active_dials(runner.get("active_dials"))

                bridge = await bridge_status()
                bridge_channels = _bridge_channel_ids(bridge)
                inbound_busy = await busy_agent_ids(db)

                active_dials = await _reconcile_active(
                    db,
                    campaign,
                    active_dials,
                    bridge_channels,
                    inter_call_delay,
                    runner,
                )
                # Enforce platform-wide concurrent call limit
                val = await get_platform_setting("max_concurrent_calls", db)
                from backend.config import get_settings
                settings = get_settings()
                default_limit = settings.max_concurrent_outbound
                try:
                    platform_limit = int(val) if val is not None else default_limit
                except ValueError:
                    platform_limit = default_limit

                # Platform limit is capped at 50 hard ceiling
                platform_limit = min(max(1, platform_limit), 50)
                active_calls_on_bridge = int(bridge.get("active_calls") or 0)
                platform_available = max(0, platform_limit - active_calls_on_bridge)

                active_dials = await _fill_slots(
                    db,
                    campaign,
                    agent_ids,
                    active_dials,
                    max_parallel,
                    inter_call_delay,
                    runner,
                    inbound_busy,
                    platform_available=platform_available,
                )
                runner["active_dials"] = active_dials
                runner["last_tick"] = datetime.now(timezone.utc).isoformat()
                campaign.meta = meta

                pending_count = sum(
                    1
                    for cl in campaign.campaign_leads
                    if cl.status == CampaignLeadStatus.pending
                )
                if pending_count == 0 and not active_dials:
                    campaign.status = CampaignStatus.completed
                    await db.commit()
                    logger.info("Campaign %s completed", campaign_id)
                    break

                await db.commit()

            await asyncio.sleep(POLL_SEC)
    except asyncio.CancelledError:
        logger.info("Campaign runner cancelled id=%s", campaign_id)
        raise
    except Exception:
        logger.exception("Campaign runner error id=%s", campaign_id)
    finally:
        _tasks.pop(campaign_id, None)


def campaign_progress(campaign: Campaign) -> dict[str, Any]:
    leads = campaign.campaign_leads or []
    counts = {s.value: 0 for s in CampaignLeadStatus}
    for cl in leads:
        st = cl.status.value if hasattr(cl.status, "value") else str(cl.status)
        counts[st] = counts.get(st, 0) + 1
    total = len(leads)
    done = counts.get("completed", 0) + counts.get("failed", 0) + counts.get("skipped", 0)
    meta = campaign.meta or {}
    runner = meta.get("runner") or {}
    agent_state = runner.get("agent_state") or {}
    cooling = sum(
        1
        for st in agent_state.values()
        if isinstance(st, dict) and st.get("status") == "cooldown"
    )
    return {
        "total": total,
        "pending": counts.get("pending", 0),
        "dialing": counts.get("dialing", 0),
        "completed": counts.get("completed", 0),
        "failed": counts.get("failed", 0),
        "skipped": counts.get("skipped", 0),
        "percent_done": round(100 * done / total) if total else 0,
        "active_slots": len(_normalize_active_dials(runner.get("active_dials"))),
        "max_parallel": runner.get("max_parallel"),
        "inter_call_delay_sec": campaign_inter_call_delay(campaign),
        "agent_ids": campaign_agent_ids(campaign),
        "agents_in_cooldown": cooling,
        "scheduled_at": runner.get("scheduled_at"),
        "runner_active": is_runner_active(campaign.id),
    }
