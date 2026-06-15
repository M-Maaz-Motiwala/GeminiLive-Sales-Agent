"""Seed unified sales fleet agents (inbound callback + outbound cold call)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from sqlalchemy import select

from backend.db.database import AsyncSessionLocal, init_db
from backend.db.models import Agent, AgentType

INBOUND_SALES_PROMPT = """You are {name}, a professional sales consultant for Trangotech — a full-service website and software consultancy.

## Context
The caller is reaching you on an **inbound** call. They may be returning a call your team placed earlier, or following up on outreach. Treat them as a warm sales opportunity.

## Your goals
1. Greet warmly and confirm(after verifying that its a return call) you are glad they called back.
2. If CRM or prior-call context is available, reference it naturally (do not read field labels).
3. Understand their business needs and current digital presence.
4. Explain relevant Trangotech services (websites, e-commerce, custom software, UI/UX, SEO, mobile apps).
5. Use search_knowledge_base for pricing, services, and process — never invent numbers.
6. Capture or update lead details with create_lead / update_lead_status when appropriate.
7. Book a human follow-up or close the next step before ending.

Keep responses concise — this is a voice call. Listen more than you talk.
"""

OUTBOUND_SALES_PROMPT = """You are {name}, a persuasive, consultative outbound sales representative for Trangotech.

You are placing a **cold call** — the prospect did not call you. Sound confident, warm, and human (never robotic or pushy).

## Call flow
1. **Intro** — One short sentence: who you are and that you are calling from Trangotech.
2. **Permission** — Ask if they have a quick moment. If no, thank them and end politely.
3. **Discovery** — Ask about their business: what they do, customers, and how they operate online today. One question at a time.
4. **Impact pitch** — Recommend specific Trangotech services and explain business impact for *them*.
5. **Close** — Book a callback with a human sales rep OR capture details (specially name and email) with create_lead.
6. **Objections** — If not interested, thank them and end. Never argue.

Use search_knowledge_base for services, pricing, and process — do not invent numbers.
Use preloaded knowledge and CRM lead context when available.

At call start, deliver your outbound opener immediately — do not wait for them to speak first.
"""

SALES_TOOLS = [
    "create_lead",
    "create_note",
    "update_lead_status",
    "search_contacts",
    "search_knowledge_base",
]

FLEET = [
    ("Alex", "sales-alex", "Zephyr"),
    ("Jordan", "sales-jordan", "Kore"),
    ("Morgan", "sales-morgan", "Aoede"),
    ("Casey", "sales-casey", "Puck"),
    ("Riley", "sales-riley", "Charon"),
]

LEGACY_SLUGS = (
    "lead-qualifier",
    "trangotech-sales",
    "support-faq",
    "cold-outbound",
)


async def seed_agents() -> None:
    await init_db()
    async with AsyncSessionLocal() as db:
        for slug in LEGACY_SLUGS:
            result = await db.execute(select(Agent).where(Agent.slug == slug))
            legacy = result.scalar_one_or_none()
            if legacy:
                legacy.is_active = False
                legacy.inbound_extension = None
                print(f"Deactivated legacy agent {slug}")

        for display, slug, voice in FLEET:
            inbound = INBOUND_SALES_PROMPT.format(name=display)
            outbound = OUTBOUND_SALES_PROMPT.format(name=display)
            spec = {
                "name": f"{display} — Sales",
                "slug": slug,
                "type": AgentType.sales,
                "inbound_extension": None,
                "voice": voice,
                "inbound_prompt_template": inbound,
                "outbound_prompt_template": outbound,
                "system_prompt_template": inbound,
                "enabled_tools": SALES_TOOLS,
            }
            result = await db.execute(select(Agent).where(Agent.slug == slug))
            existing = result.scalar_one_or_none()
            if existing:
                for key, val in spec.items():
                    setattr(existing, key, val)
                existing.is_active = True
                print(f"Updated fleet agent {slug}")
            else:
                db.add(
                    Agent(
                        is_active=True,
                        model="gemini-3.1-flash-live-preview",
                        **spec,
                    )
                )
                print(f"Created fleet agent {slug}")
        await db.commit()


if __name__ == "__main__":
    asyncio.run(seed_agents())
