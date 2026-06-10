"""System info for admin UI (SIP hints, defaults)."""
import os

from fastapi import APIRouter

router = APIRouter(prefix="/api/system", tags=["system"])

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
        "outbound_mode": os.getenv("OUTBOUND_MODE", "lab"),
        "default_admin_email": os.getenv("ADMIN_EMAIL", "admin@aura.ai"),
        "outbound_lab_endpoint": os.getenv("OUTBOUND_LAB_ENDPOINT", "PJSIP/1001"),
        "test_extensions": {
            "701": "Maya — Lead Qualifier",
            "702": "Aria — Trangotech Sales",
            "703": "Sam — Support FAQ",
            "704": "Riley — Cold Outbound (inbound test)",
            "700": "First active agent (legacy)",
            "600": "Echo test",
        },
    }
