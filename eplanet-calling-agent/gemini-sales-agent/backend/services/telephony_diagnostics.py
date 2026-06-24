"""Docker + telephony diagnostics for admin UI (no SSH required)."""
from __future__ import annotations

import ipaddress
import logging
import os
import re
import subprocess
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

ASTERISK_CONTAINER = os.getenv("ASTERISK_CONTAINER_NAME", "asterisk")
BRIDGE_CONTAINER = os.getenv("BRIDGE_CONTAINER_NAME", "gemini_bridge")

ALLOWED_LOG_CONTAINERS = frozenset(
    {
        "asterisk",
        "gemini_bridge",
        "aura_platform",
        "aura_frontend",
        "aura_celery",
        "aura_postgres",
        "aura_redis",
    }
)

MAX_LOG_TAIL = 500
DEFAULT_LOG_TAIL = 200

_REDACT_PATTERNS = [
    (
        re.compile(
            r"(?i)(api[_-]?key|password|secret|token|authorization|bearer|jwt)([=:]\s*)(\S+)"
        ),
        r"\1\2***",
    ),
    (re.compile(r"(?i)(DIDWW_SIP_SECRET=)(\S+)"), r"\1***"),
    (re.compile(r"(?i)(PINECONE_API_KEY=)(\S+)"), r"\1***"),
    (re.compile(r"(?i)(GEMINI_API_KEY=)(\S+)"), r"\1***"),
]


def _resolved_external_ip() -> str:
    for key in ("SIP_EXTERNAL_IP", "EXTERNAL_IP"):
        val = (os.getenv(key) or "").strip()
        if val and val.lower() != "auto":
            return val
    return ""


def _is_likely_private_ip(ip: str) -> bool:
    if not ip:
        return False
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return False


def _docker_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _run(cmd: list[str], *, timeout: int = 20) -> dict[str, Any]:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": (result.stdout or "").strip(),
            "stderr": (result.stderr or "").strip(),
        }
    except FileNotFoundError:
        return {"ok": False, "error": "docker CLI not installed in platform container"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"command timed out after {timeout}s"}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


def redact_logs(text: str) -> str:
    out = text
    for pattern, repl in _REDACT_PATTERNS:
        out = pattern.sub(repl, out)
    return out


def list_containers() -> list[dict[str, str]]:
    if not _docker_available():
        return []
    result = _run(
        [
            "docker",
            "ps",
            "-a",
            "--format",
            "{{.Names}}\t{{.Status}}\t{{.State}}",
        ],
        timeout=12,
    )
    if not result.get("ok"):
        return []
    rows: list[dict[str, str]] = []
    for line in (result.get("stdout") or "").splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        name, status, state = parts
        if name in ALLOWED_LOG_CONTAINERS:
            rows.append({"name": name, "status": status, "state": state})
    order = list(ALLOWED_LOG_CONTAINERS)
    rows.sort(key=lambda r: order.index(r["name"]) if r["name"] in order else 99)
    return rows


def fetch_container_logs(
    container: str,
    *,
    tail: int = DEFAULT_LOG_TAIL,
    since_minutes: int = 60,
    grep: Optional[str] = None,
) -> dict[str, Any]:
    if container not in ALLOWED_LOG_CONTAINERS:
        return {"ok": False, "error": f"container not allowed: {container}"}
    tail = max(10, min(int(tail), MAX_LOG_TAIL))
    since_minutes = max(5, min(int(since_minutes), 24 * 60))
    cmd = [
        "docker",
        "logs",
        "--tail",
        str(tail),
        "--since",
        f"{since_minutes}m",
        container,
    ]
    result = _run(cmd, timeout=30)
    if not result.get("ok"):
        return {
            "ok": False,
            "container": container,
            "error": result.get("error") or result.get("stderr") or "docker logs failed",
        }
    # docker logs writes to stderr for some engines
    combined = "\n".join(
        part for part in (result.get("stdout"), result.get("stderr")) if part
    ).strip()
    if grep:
        needles = [n.strip().lower() for n in grep.split("|") if n.strip()]
        if needles:
            lines = [
                ln
                for ln in combined.splitlines()
                if any(n in ln.lower() for n in needles)
            ]
            combined = "\n".join(lines[-tail:])
    return {
        "ok": True,
        "container": container,
        "tail": tail,
        "since_minutes": since_minutes,
        "grep": grep,
        "lines": len(combined.splitlines()) if combined else 0,
        "logs": redact_logs(combined),
    }


def _asterisk_exec(command: str) -> dict[str, Any]:
    return _run(
        ["docker", "exec", ASTERISK_CONTAINER, "asterisk", "-rx", command],
        timeout=15,
    )


def _read_asterisk_file_grep(pattern: str) -> str:
    result = _run(
        [
            "docker",
            "exec",
            ASTERISK_CONTAINER,
            "grep",
            "-E",
            pattern,
            "/etc/asterisk/pjsip.conf",
        ],
        timeout=12,
    )
    if result.get("ok"):
        return result.get("stdout") or ""
    return ""


def _parse_rtp_settings(cli_output: str) -> dict[str, Optional[int]]:
    start = end = None
    for line in cli_output.splitlines():
        low = line.lower().strip()
        if low.startswith("port start:"):
            try:
                start = int(low.split(":", 1)[1].strip())
            except ValueError:
                pass
        if low.startswith("port end:"):
            try:
                end = int(low.split(":", 1)[1].strip())
            except ValueError:
                pass
    return {"rtp_start": start, "rtp_end": end}


def _bridge_health() -> dict[str, Any]:
    base = (os.getenv("BRIDGE_URL") or "http://bridge:8000").rstrip("/")
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{base}/health")
            if resp.status_code == 200:
                return {"ok": True, **resp.json()}
            return {"ok": False, "status_code": resp.status_code, "body": resp.text[:500]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _check(
    check_id: str,
    ok: bool,
    message: str,
    *,
    owner: str,
    severity: str = "error",
    hint: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "ok": ok,
        "message": message,
        "owner": owner,
        "severity": severity if not ok else "ok",
        "hint": hint,
    }


def run_telephony_diagnostics() -> dict[str, Any]:
    """Run read-only checks; classify issues as platform vs devops vs didww."""
    external_ip = _resolved_external_ip()
    checks: list[dict[str, Any]] = []
    telephony: dict[str, Any] = {"external_ip": external_ip or None}

    docker_ok = _docker_available()
    checks.append(
        _check(
            "docker_socket",
            docker_ok,
            "Platform can reach Docker (log viewer & Asterisk checks)"
            if docker_ok
            else "Docker socket unavailable — install docker CLI and mount /var/run/docker.sock",
            owner="platform",
            hint="Ensure docker-compose mounts /var/run/docker.sock on aura_platform and rebuild.",
        )
    )

    containers = list_containers()
    required = {"asterisk", "gemini_bridge", "aura_platform"}
    running = {c["name"] for c in containers if c.get("state") == "running"}
    missing = sorted(required - running)
    checks.append(
        _check(
            "core_containers",
            not missing,
            "Core containers running: asterisk, gemini_bridge, aura_platform"
            if not missing
            else f"Not running: {', '.join(missing)}",
            owner="platform",
            hint="On server run: ./start.sh up -d --build",
        )
    )

    if external_ip:
        private = _is_likely_private_ip(external_ip)
        checks.append(
            _check(
                "external_ip_public",
                not private,
                f"EXTERNAL_IP={external_ip} (public — OK for PSTN)"
                if not private
                else f"EXTERNAL_IP={external_ip} looks private — DIDWW cannot send RTP to this",
                owner="platform",
                hint="Set EXTERNAL_IP=your.public.ip in .env on the server, then: "
                "./start.sh up -d --force-recreate asterisk",
            )
        )
    else:
        checks.append(
            _check(
                "external_ip_set",
                False,
                "EXTERNAL_IP not set (or still 'auto') — inbound RTP will fail on cloud servers",
                owner="platform",
                hint="Set EXTERNAL_IP=38.86.174.122 (public IP) in server .env",
            )
        )

    if docker_ok:
        nat_lines = _read_asterisk_file_grep(r"external_media_address|external_signaling_address")
        telephony["pjsip_nat"] = nat_lines or None
        media_match = re.search(r"external_media_address=(\S+)", nat_lines or "")
        media_ip = media_match.group(1) if media_match else ""
        if media_ip:
            telephony["external_media_address"] = media_ip
            bad = _is_likely_private_ip(media_ip)
            checks.append(
                _check(
                    "asterisk_sdp_ip",
                    not bad,
                    f"Asterisk advertises media at {media_ip}"
                    if not bad
                    else f"Asterisk advertises private media IP {media_ip} — inbound RTP timeout likely",
                    owner="platform",
                    hint="Recreate asterisk after fixing EXTERNAL_IP. If still private, Docker NAT/local_net fix needed.",
                )
            )

        rtp_cli = _asterisk_exec("rtp show settings")
        telephony["rtp_cli"] = rtp_cli.get("stdout")
        rtp_ports = _parse_rtp_settings(rtp_cli.get("stdout") or "")
        telephony.update(rtp_ports)
        rtp_ok = rtp_ports.get("rtp_start") == 10000 and rtp_ports.get("rtp_end") == 10050
        checks.append(
            _check(
                "rtp_port_range",
                rtp_ok,
                "Asterisk RTP range 10000–10050 (matches firewall & docker-compose)"
                if rtp_ok
                else f"Asterisk RTP range {rtp_ports.get('rtp_start')}–{rtp_ports.get('rtp_end')} — "
                "firewall must allow UDP 10000–10050 (not only 16384–32767)",
                owner="devops",
                hint="Open UDP 10000–10050 on server + cloud security group. "
                "16384–32767 is generic Asterisk default; this stack uses 10000–10050.",
            )
        )

        didww = _asterisk_exec("pjsip show endpoint didww_in")
        telephony["didww_in"] = (didww.get("stdout") or "")[:2000]

    bridge = _bridge_health()
    telephony["bridge"] = bridge
    checks.append(
        _check(
            "bridge_health",
            bool(bridge.get("ok")),
            "Gemini bridge reachable"
            if bridge.get("ok")
            else f"Bridge health failed: {bridge.get('error') or bridge.get('status_code')}",
            owner="platform",
        )
    )

    checks.append(
        _check(
            "didww_inbound_rtp_whitelist",
            True,
            "Manual: DIDWW inbound trunk → Allowed RTP IPs must include your public server IP",
            owner="didww",
            severity="info",
            hint="Separate from outbound trunk whitelist. RTP timeout on inbound often means "
            "DIDWW is not accepting RTP from your new server IP.",
        )
    )
    checks.append(
        _check(
            "didww_voice_in_route",
            True,
            "Manual: DIDWW Voice-IN must route to sip:YOUR_PUBLIC_IP:5060",
            owner="didww",
            severity="info",
        )
    )

    failed = [c for c in checks if not c["ok"] and c.get("severity") != "info"]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "docker_available": docker_ok,
        "containers": containers,
        "telephony": telephony,
        "checks": checks,
        "summary": {
            "ok": len(failed) == 0,
            "failed_count": len(failed),
            "failed_owners": sorted({c["owner"] for c in failed}),
        },
    }
