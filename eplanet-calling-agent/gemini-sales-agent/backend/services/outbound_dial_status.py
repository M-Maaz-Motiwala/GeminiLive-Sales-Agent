"""Map Asterisk hangup signals to CRM-friendly outbound dial outcomes."""
from __future__ import annotations

from typing import Any, Optional

DIAL_PHASE_LABELS: dict[str, str] = {
    "originating": "Starting outbound call…",
    "ringing": "Ringing prospect…",
    "connecting": "Prospect answered — connecting AI agent…",
    "in_call": "In call with prospect",
    "ended": "Call ended",
}

OUTCOME_LABELS: dict[str, str] = {
    "completed": "Call completed",
    "answered": "Prospect answered",
    "no_answer": "No answer",
    "busy": "Line busy",
    "rejected": "Call declined",
    "failed": "Call failed",
}


def hangup_outcome(
    *,
    cause: Optional[str],
    cause_txt: Optional[str],
    dial_phase: str,
    had_media: bool,
) -> str:
    """Classify how an outbound attempt ended."""
    txt = (cause_txt or "").lower()
    cause_i: Optional[int] = None
    if cause is not None and str(cause).strip().isdigit():
        cause_i = int(str(cause).strip())

    if cause_i == 17 or "busy" in txt:
        return "busy"
    if cause_i in (19, 18) or "no answer" in txt or "noanswer" in txt:
        return "no_answer"
    if cause_i == 21 or "reject" in txt or "declin" in txt:
        return "rejected"
    if had_media or dial_phase == "in_call":
        return "completed"
    if dial_phase in ("ringing", "connecting", "originating"):
        return "no_answer"
    return "failed"


def status_message(phase: str, outcome: Optional[str] = None) -> str:
    if phase == "ended" and outcome:
        return OUTCOME_LABELS.get(outcome, OUTCOME_LABELS["failed"])
    return DIAL_PHASE_LABELS.get(phase, phase.replace("_", " ").title())


def enrich_dial_status(row: dict[str, Any]) -> dict[str, Any]:
    phase = row.get("dial_phase") or row.get("phase") or "originating"
    outcome = row.get("outcome")
    return {
        **row,
        "dial_phase": phase,
        "label": status_message(phase, outcome),
        "terminal": phase == "ended" or bool(outcome),
    }
