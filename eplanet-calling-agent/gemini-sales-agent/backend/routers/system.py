"""System info for admin UI (SIP hints, defaults)."""
import os

from fastapi import APIRouter

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/info")
async def system_info() -> dict:
    sip_ip = os.getenv("SIP_EXTERNAL_IP") or os.getenv("EXTERNAL_IP") or ""
    return {
        "sip_server": sip_ip,
        "sip_port": 5060,
        "sip_username": "1000",
        "sip_password_hint": "1000pass",
        "default_admin_email": os.getenv("ADMIN_EMAIL", "admin@aura.ai"),
        "test_extensions": {
            "701": "Maya — Lead Qualifier",
            "702": "Aria — Trangotech Sales",
            "703": "Sam — Support FAQ",
            "700": "First active agent (legacy)",
            "600": "Echo test",
        },
    }
