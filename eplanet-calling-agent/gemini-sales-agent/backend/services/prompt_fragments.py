"""Shared prompt fragments injected into every voice agent call."""

CONTACT_CONFIRMATION_RULES = """## Contact detail confirmation (mandatory)
Whenever you collect contact information, verify accuracy **before** saving with create_lead or update_lead_details:
- **Full name:** Repeat the full name back; spell it if unclear (e.g. "So that's John Smith — J-O-H-N, S-M-I-T-H?").
- **Email:** Spell it character by character, including @ and the domain (e.g. "john at example dot com — J-O-H-N at E-X-A-M-P-L-E dot com?").
- **Company name:** Repeat the company name back and spell it if needed.
- **Phone number:** Repeat digit-by-digit (e.g. "That's 4-1-5, 5-5-5, 0-1-2-3?").
- Only save after the caller or prospect **explicitly confirms** each field is correct.
- On outbound calls, if they say "this number" or "same number you called", use the dialed number from call context — still confirm verbally before saving.
- If they correct anything, repeat the corrected value back once more, then save with update_lead_details.
"""
