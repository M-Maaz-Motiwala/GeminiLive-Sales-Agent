"""Multi-tenant auth, RBAC, access requests, Google Calendar tokens, owner scoping.

Revision ID: 002
Revises: 001
Create Date: 2026-06-30

"""
from alembic import op
import sqlalchemy as sa


revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Extend UserRole enum ---
    op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'org_head'")
    op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'user'")

    # --- User table modifications ---
    op.alter_column('users', 'hashed_password', existing_type=sa.String(255), nullable=True)
    op.add_column('users', sa.Column('is_approved', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('users', sa.Column('auth_provider', sa.String(20), nullable=False, server_default='local'))
    op.add_column('users', sa.Column('google_id', sa.String(255), nullable=True))
    op.add_column('users', sa.Column('google_picture', sa.String(500), nullable=True))
    op.add_column('users', sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=True))
    op.add_column('users', sa.Column('designation', sa.String(255), nullable=True))
    op.create_index('ix_users_google_id', 'users', ['google_id'], unique=True)
    op.create_index('ix_users_organization_id', 'users', ['organization_id'])

    # Mark existing users as approved (they were created via env seed)
    op.execute("UPDATE users SET is_approved = true WHERE is_approved = false")

    # --- owner_id on existing tables ---
    op.add_column('sessions', sa.Column('owner_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True))
    op.create_index('ix_sessions_owner_id', 'sessions', ['owner_id'])

    op.add_column('campaigns', sa.Column('owner_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True))
    op.create_index('ix_campaigns_owner_id', 'campaigns', ['owner_id'])

    op.add_column('leads', sa.Column('owner_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True))
    op.create_index('ix_leads_owner_id', 'leads', ['owner_id'])

    op.add_column('contacts', sa.Column('owner_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True))
    op.create_index('ix_contacts_owner_id', 'contacts', ['owner_id'])

    # --- AccessRequestStatus enum ---
    access_request_status = sa.Enum('pending', 'approved', 'rejected', name='accessrequeststatus')
    access_request_status.create(op.get_bind(), checkfirst=True)

    # --- user_access_requests table ---
    op.create_table(
        'user_access_requests',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False),
        sa.Column('full_name', sa.String(255), nullable=False),
        sa.Column('designation', sa.String(255), nullable=False),
        sa.Column('status', sa.Enum('pending', 'approved', 'rejected', name='accessrequeststatus', create_type=False), nullable=False, server_default='pending'),
        sa.Column('reviewed_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- google_calendar_tokens table ---
    op.create_table(
        'google_calendar_tokens',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), unique=True, nullable=False),
        sa.Column('access_token', sa.Text(), nullable=False),
        sa.Column('refresh_token', sa.Text(), nullable=False),
        sa.Column('token_expiry', sa.DateTime(timezone=True), nullable=True),
        sa.Column('calendar_id', sa.String(255), server_default='primary'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('google_calendar_tokens')
    op.drop_table('user_access_requests')
    op.execute("DROP TYPE IF EXISTS accessrequeststatus")

    op.drop_index('ix_contacts_owner_id', 'contacts')
    op.drop_column('contacts', 'owner_id')
    op.drop_index('ix_leads_owner_id', 'leads')
    op.drop_column('leads', 'owner_id')
    op.drop_index('ix_campaigns_owner_id', 'campaigns')
    op.drop_column('campaigns', 'owner_id')
    op.drop_index('ix_sessions_owner_id', 'sessions')
    op.drop_column('sessions', 'owner_id')

    op.drop_index('ix_users_organization_id', 'users')
    op.drop_index('ix_users_google_id', 'users')
    op.drop_column('users', 'designation')
    op.drop_column('users', 'organization_id')
    op.drop_column('users', 'google_picture')
    op.drop_column('users', 'google_id')
    op.drop_column('users', 'auth_provider')
    op.drop_column('users', 'is_approved')
    op.alter_column('users', 'hashed_password', existing_type=sa.String(255), nullable=False)
