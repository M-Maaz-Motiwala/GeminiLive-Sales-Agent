"""Lightweight idempotent schema patches (create_all does not alter existing tables)."""
from __future__ import annotations

import json

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
    # --- Phase 1: Multi-tenant auth, RBAC, access requests, calendar tokens ---
    "ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'org_head'",
    "ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'user'",
    "ALTER TABLE users ALTER COLUMN hashed_password DROP NOT NULL",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_approved BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_provider VARCHAR(20) NOT NULL DEFAULT 'local'",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS google_id VARCHAR(255) UNIQUE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS google_picture VARCHAR(500)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS organization_id INTEGER REFERENCES organizations(id)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS designation VARCHAR(255)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_google_id ON users (google_id)",
    "CREATE INDEX IF NOT EXISTS ix_users_organization_id ON users (organization_id)",
    "UPDATE users SET is_approved = true WHERE is_approved = false",
    # owner_id on existing tables
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS owner_id INTEGER REFERENCES users(id)",
    "CREATE INDEX IF NOT EXISTS ix_sessions_owner_id ON sessions (owner_id)",
    "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS owner_id INTEGER REFERENCES users(id)",
    "CREATE INDEX IF NOT EXISTS ix_campaigns_owner_id ON campaigns (owner_id)",
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS owner_id INTEGER REFERENCES users(id)",
    "CREATE INDEX IF NOT EXISTS ix_leads_owner_id ON leads (owner_id)",
    "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS owner_id INTEGER REFERENCES users(id)",
    "CREATE INDEX IF NOT EXISTS ix_contacts_owner_id ON contacts (owner_id)",
    # AccessRequestStatus enum + user_access_requests table
    "DO $$ BEGIN CREATE TYPE accessrequeststatus AS ENUM ('pending', 'approved', 'rejected'); EXCEPTION WHEN duplicate_object THEN NULL; END $$",
    """CREATE TABLE IF NOT EXISTS user_access_requests (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        organization_id INTEGER NOT NULL REFERENCES organizations(id),
        full_name VARCHAR(255) NOT NULL,
        designation VARCHAR(255) NOT NULL,
        status accessrequeststatus NOT NULL DEFAULT 'pending',
        reviewed_by_id INTEGER REFERENCES users(id),
        reviewed_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT now()
    )""",
    # Google Calendar tokens table
    """CREATE TABLE IF NOT EXISTS google_calendar_tokens (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
        access_token TEXT NOT NULL,
        refresh_token TEXT NOT NULL,
        token_expiry TIMESTAMPTZ,
        calendar_id VARCHAR(255) DEFAULT 'primary',
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now()
    )""",
    # --- User-deletion cascades: SET NULL on nullable user FKs, CASCADE on NOT NULL ---
    # Leads/contacts/sessions/campaigns/agents/notes are preserved (owner NULL'd).
    "ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_created_by_id_fkey",
    "ALTER TABLE agents ADD CONSTRAINT agents_created_by_id_fkey FOREIGN KEY (created_by_id) REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE sessions DROP CONSTRAINT IF EXISTS sessions_owner_id_fkey",
    "ALTER TABLE sessions ADD CONSTRAINT sessions_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE campaigns DROP CONSTRAINT IF EXISTS campaigns_owner_id_fkey",
    "ALTER TABLE campaigns ADD CONSTRAINT campaigns_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE leads DROP CONSTRAINT IF EXISTS leads_owner_id_fkey",
    "ALTER TABLE leads ADD CONSTRAINT leads_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE contacts DROP CONSTRAINT IF EXISTS contacts_owner_id_fkey",
    "ALTER TABLE contacts ADD CONSTRAINT contacts_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE notes DROP CONSTRAINT IF EXISTS notes_created_by_id_fkey",
    "ALTER TABLE notes ADD CONSTRAINT notes_created_by_id_fkey FOREIGN KEY (created_by_id) REFERENCES users(id) ON DELETE SET NULL",
    # Access requests: the request row is deleted with the user; reviewer link is NULL'd.
    "ALTER TABLE user_access_requests DROP CONSTRAINT IF EXISTS user_access_requests_user_id_fkey",
    "ALTER TABLE user_access_requests ADD CONSTRAINT user_access_requests_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE",
    "ALTER TABLE user_access_requests DROP CONSTRAINT IF EXISTS user_access_requests_reviewed_by_id_fkey",
    "ALTER TABLE user_access_requests ADD CONSTRAINT user_access_requests_reviewed_by_id_fkey FOREIGN KEY (reviewed_by_id) REFERENCES users(id) ON DELETE SET NULL",
    # Google Calendar tokens: deleted with the user.
    "ALTER TABLE google_calendar_tokens DROP CONSTRAINT IF EXISTS google_calendar_tokens_user_id_fkey",
    "ALTER TABLE google_calendar_tokens ADD CONSTRAINT google_calendar_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE",
)


_CALENDAR_TOOLS = ("find_next_available_slot", "list_available_slots", "schedule_meeting", "cancel_meeting")


async def apply_migrations() -> None:
    async with engine.begin() as conn:
        for stmt in _PATCHES:
            await conn.execute(text(stmt))

        # Backfill calendar tools into existing agents' enabled_tools.
        rows = await conn.execute(text("SELECT id, enabled_tools FROM agents"))
        for row in rows:
            current = list(row[1] or [])
            changed = False
            for tool in _CALENDAR_TOOLS:
                if tool not in current:
                    current.append(tool)
                    changed = True
            if changed:
                await conn.execute(
                    text("UPDATE agents SET enabled_tools = CAST(:tools AS json) WHERE id = :id"),
                    {"tools": json.dumps(current), "id": row[0]},
                )
