"""Parse CSV rows into campaign targets (lab endpoints or CRM leads)."""
from __future__ import annotations

import csv
import io
from typing import Any, Optional

from backend.config import get_settings
from backend.services.phone_utils import lab_pjsip_endpoint, normalize_e164

settings = get_settings()

_HEADER_ALIASES = {
    "phone": {"phone", "mobile", "number", "tel", "telephone"},
    "name": {"name", "full_name", "contact", "contact_name"},
    "email": {"email", "e-mail", "mail"},
    "company": {"company", "organization", "org", "business"},
    "endpoint": {"endpoint", "sip", "extension", "pjsip"},
}


def _normalize_header(h: str) -> Optional[str]:
    key = (h or "").strip().lower().replace(" ", "_")
    for field, aliases in _HEADER_ALIASES.items():
        if key in aliases:
            return field
    return None


def parse_campaign_csv(content: str | bytes) -> list[dict[str, Any]]:
    """
    Parse CSV into row dicts with keys: endpoint and/or lead fields.
    Raises ValueError on empty or unparseable input.
    """
    if isinstance(content, bytes):
        text = content.decode("utf-8-sig", errors="replace")
    else:
        text = content
    text = text.strip()
    if not text:
        raise ValueError("CSV file is empty")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row")

    col_map: dict[str, str] = {}
    for raw in reader.fieldnames:
        norm = _normalize_header(raw)
        if norm:
            col_map[raw] = norm

    if not col_map:
        raise ValueError(
            "CSV must include columns such as phone, endpoint, or name "
            "(see docs: phone, name, email, company, endpoint)"
        )

    rows: list[dict[str, Any]] = []
    for i, raw_row in enumerate(reader, start=2):
        row: dict[str, str] = {}
        for k, v in raw_row.items():
            if k in col_map and v is not None:
                row[col_map[k]] = str(v).strip()
        if not any(row.values()):
            continue

        endpoint = row.get("endpoint", "").strip()
        phone = row.get("phone", "").strip()

        if not endpoint and phone.upper().startswith("PJSIP/"):
            endpoint = phone
            phone = ""

        if not endpoint:
            lab = lab_pjsip_endpoint(phone) if phone else None
            if lab:
                endpoint = lab

        if not endpoint and not phone:
            raise ValueError(f"Row {i}: need phone or endpoint")

        out: dict[str, Any] = {}
        if endpoint:
            out["endpoint"] = endpoint
        if phone and not endpoint:
            out["phone"] = phone
            e164 = normalize_e164(phone, settings.outbound_default_country_code)
            if e164:
                out["phone_e164"] = e164
        for field in ("name", "email", "company"):
            if row.get(field):
                out[field] = row[field]
        rows.append(out)

    if not rows:
        raise ValueError("CSV has no data rows")
    return rows
