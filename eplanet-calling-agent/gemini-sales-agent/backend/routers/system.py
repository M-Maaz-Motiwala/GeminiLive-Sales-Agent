"""System info for admin UI (SIP hints, defaults, global settings)."""
import os
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.deps import get_current_user
from backend.db.database import get_db
from backend.db.models import PlatformSetting

router = APIRouter(prefix="/api/system", tags=["system"])

SETTING_MASTER_PROMPT = "master_prompt"


class SettingsOut(BaseModel):
    master_prompt: Optional[str] = None


class SettingsIn(BaseModel):
    master_prompt: Optional[str] = None

_CODEC_LABELS = {
    "PCMU": "G.711 μ-law (PCMU)",
    "PCMA": "G.711 A-law (PCMA)",
    "ulaw": "G.711 μ-law (PCMU)",
    "alaw": "G.711 A-law (PCMA)",
}


def _resolved_lan_ip() -> str:
    """Prefer resolved IP from .host.env; ignore EXTERNAL_IP=auto from .env."""
    for key in ("SIP_EXTERNAL_IP", "EXTERNAL_IP"):
        val = (os.getenv(key) or "").strip()
        if val and val.lower() != "auto":
            return val
    return ""


@router.get("/info")
async def system_info() -> dict:
    sip_ip = _resolved_lan_ip()
    sip_port = int(os.getenv("SIP_PORT", "5060"))
    sip_user = os.getenv("SIP_USER", "1000")
    sip_codec = os.getenv("SIP_CODEC", "PCMU")
    ip_mode = os.getenv("EXTERNAL_IP_MODE", "auto")
    if ip_mode not in ("auto", "fixed"):
        ip_mode = "auto"

    lab_extensions = []
    for ext in range(1001, 1011):
        ext_s = str(ext)
        lab_extensions.append(
            {
                "extension": ext_s,
                "username": os.getenv(f"SIP_USER_{ext_s}", ext_s),
                "password": os.getenv(f"SIP_PASS_{ext_s}", f"{ext_s}pass"),
            }
        )

    return {
        "sip_server": sip_ip,
        "external_ip": sip_ip,
        "external_ip_mode": ip_mode,
        "ip_changed": os.getenv("IP_CHANGED", "0") == "1",
        "sip_port": sip_port,
        "sip_transport": "UDP",
        "sip_username": sip_user,
        "sip_password": os.getenv("SIP_PASS", "1000pass"),
        "sip_password_hint": os.getenv("SIP_PASS", "1000pass"),
        "sip_codec": sip_codec,
        "sip_codec_label": _CODEC_LABELS.get(sip_codec.upper(), sip_codec),
        "sip_user_1001": os.getenv("SIP_USER_1001", "1001"),
        "sip_pass_1001": os.getenv("SIP_PASS_1001", "1001pass"),
        "sip_user_1002": os.getenv("SIP_USER_1002", "1002"),
        "sip_pass_1002": os.getenv("SIP_PASS_1002", "1002pass"),
        "lab_extensions": lab_extensions,
        "outbound_mode": os.getenv("OUTBOUND_MODE", "lab"),
        "default_admin_email": os.getenv("ADMIN_EMAIL", "admin@aura.ai"),
        "outbound_lab_endpoint": os.getenv("OUTBOUND_LAB_ENDPOINT", "PJSIP/1001"),
        "test_extensions": {
            "700": "Sales fleet — inbound callbacks",
            "701": "Alias → 700 (lab)",
            "600": "Echo test",
        },
    }


@router.get("/settings", response_model=SettingsOut)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
) -> SettingsOut:
    result = await db.execute(
        select(PlatformSetting).where(PlatformSetting.key == SETTING_MASTER_PROMPT)
    )
    row = result.scalar_one_or_none()
    return SettingsOut(master_prompt=row.value if row else None)


@router.put("/settings", response_model=SettingsOut)
async def update_settings(
    body: SettingsIn,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
) -> SettingsOut:
    if body.master_prompt is not None:
        result = await db.execute(
            select(PlatformSetting).where(PlatformSetting.key == SETTING_MASTER_PROMPT)
        )
        row = result.scalar_one_or_none()
        if row:
            row.value = body.master_prompt or None
        else:
            db.add(PlatformSetting(key=SETTING_MASTER_PROMPT, value=body.master_prompt or None))
    return SettingsOut(master_prompt=body.master_prompt)
