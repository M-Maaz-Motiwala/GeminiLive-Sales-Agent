"""User-deletion cascades — SET NULL on nullable user FKs, CASCADE on NOT NULL FKs.

Preserves leads, contacts, sessions, campaigns, agents, and notes (owner NULL'd).
Deletes the user's access requests and Google Calendar tokens.

Revision ID: 003
Revises: 002
Create Date: 2026-07-01

"""
from alembic import op


revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


# (table, constraint, column, ondelete)
_FKS = [
    ('agents', 'agents_created_by_id_fkey', 'created_by_id', 'SET NULL'),
    ('sessions', 'sessions_owner_id_fkey', 'owner_id', 'SET NULL'),
    ('campaigns', 'campaigns_owner_id_fkey', 'owner_id', 'SET NULL'),
    ('leads', 'leads_owner_id_fkey', 'owner_id', 'SET NULL'),
    ('contacts', 'contacts_owner_id_fkey', 'owner_id', 'SET NULL'),
    ('notes', 'notes_created_by_id_fkey', 'created_by_id', 'SET NULL'),
    ('user_access_requests', 'user_access_requests_user_id_fkey', 'user_id', 'CASCADE'),
    ('user_access_requests', 'user_access_requests_reviewed_by_id_fkey', 'reviewed_by_id', 'SET NULL'),
    ('google_calendar_tokens', 'google_calendar_tokens_user_id_fkey', 'user_id', 'CASCADE'),
]


def upgrade() -> None:
    bind = op.get_bind()
    for table, constraint, column, ondelete in _FKS:
        bind.execute(
            f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}"
        )
        bind.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {constraint} "
            f"FOREIGN KEY ({column}) REFERENCES users(id) ON DELETE {ondelete}"
        )


def downgrade() -> None:
    bind = op.get_bind()
    for table, constraint, column, _ondelete in _FKS:
        bind.execute(
            f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}"
        )
        bind.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {constraint} "
            f"FOREIGN KEY ({column}) REFERENCES users(id)"
        )