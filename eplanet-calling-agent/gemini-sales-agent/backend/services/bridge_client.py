"""HTTP client for gemini_bridge internal APIs (originate outbound calls)."""
from __future__ import annotations

import logging
from typing import Any, Optional

import aiohttp

from backend.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


async def originate_outbound(
    *,
    agent_slug: str,
    endpoint: str,
    lead_id: Optional[int] = None,
    caller_id: Optional[str] = None,
) -> dict[str, Any]:
    """Ask the bridge to originate an outbound call via Asterisk ARI."""
    base = (settings.bridge_url or "").rstrip("/")
    if not base:
        raise RuntimeError("BRIDGE_URL is not configured")

    payload: dict[str, Any] = {
        "agent_slug": agent_slug,
        "endpoint": endpoint,
    }
    if lead_id is not None:
        payload["lead_id"] = lead_id
    if caller_id:
        payload["caller_id"] = caller_id

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if settings.bridge_internal_token:
        headers["X-Bridge-Token"] = settings.bridge_internal_token

    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            f"{base}/internal/originate",
            json=payload,
            headers=headers,
        ) as resp:
            body: Any = None
            try:
                body = await resp.json()
            except Exception:
                body = await resp.text()
            if resp.status >= 400:
                detail = body
                if isinstance(body, dict):
                    detail = body.get("detail", body)
                raise RuntimeError(f"Bridge originate failed ({resp.status}): {detail}")
            if not isinstance(body, dict):
                return {"status": "ok", "raw": body}
            return body
