"""Lightweight idempotent schema patches (create_all does not alter existing tables)."""
from __future__ import annotations

from sqlalchemy import text

from backend.db.database import engine


_PATCHES = (
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS inbound_prompt_template TEXT",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS outbound_prompt_template TEXT",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS master_prompt_override TEXT",
    """CREATE TABLE IF NOT EXISTS platform_settings (
        key VARCHAR(255) PRIMARY KEY,
        value TEXT,
        updated_at TIMESTAMPTZ DEFAULT now()
    )""",
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS lead_profile JSONB DEFAULT '{}'::jsonb",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS last_error TEXT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS last_attempt_at TIMESTAMPTZ",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS did VARCHAR(32)",
    "ALTER TYPE agenttype ADD VALUE IF NOT EXISTS 'support'",
    "CREATE INDEX IF NOT EXISTS ix_agents_did ON agents (did)",
    """CREATE TABLE IF NOT EXISTS organizations (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        slug VARCHAR(255) UNIQUE NOT NULL,
        did VARCHAR(32) UNIQUE NOT NULL,
        is_active BOOLEAN DEFAULT TRUE NOT NULL,
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_organizations_did ON organizations (did)",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS organization_id INTEGER REFERENCES organizations(id)",
    "CREATE INDEX IF NOT EXISTS ix_agents_organization_id ON agents (organization_id)",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS organization_id INTEGER REFERENCES organizations(id)",
    "CREATE INDEX IF NOT EXISTS ix_documents_organization_id ON documents (organization_id)",
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS organization_id INTEGER REFERENCES organizations(id)",
    "CREATE INDEX IF NOT EXISTS ix_leads_organization_id ON leads (organization_id)",
    "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS organization_id INTEGER REFERENCES organizations(id)",
    "CREATE INDEX IF NOT EXISTS ix_contacts_organization_id ON contacts (organization_id)",
    """UPDATE leads l SET organization_id = a.organization_id
       FROM sessions s JOIN agents a ON s.agent_id = a.id
       WHERE l.source_session_id = s.id AND l.organization_id IS NULL AND a.organization_id IS NOT NULL""",
    """UPDATE contacts c SET organization_id = l.organization_id
       FROM leads l
       WHERE c.organization_id IS NULL AND l.organization_id IS NOT NULL
         AND ((c.phone IS NOT NULL AND c.phone = l.phone) OR (c.email IS NOT NULL AND c.email = l.email))""",
)


async def apply_migrations() -> None:
    async with engine.begin() as conn:
        for stmt in _PATCHES:
            await conn.execute(text(stmt))
