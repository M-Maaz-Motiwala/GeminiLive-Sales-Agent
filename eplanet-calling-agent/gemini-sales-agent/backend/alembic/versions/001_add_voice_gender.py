"""Add voice_gender to agents table.

Revision ID: 001
Revises:
Create Date: 2026-06-24

"""
from alembic import op
import sqlalchemy as sa


revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the enum type
    voice_gender_enum = sa.Enum('male', 'female', name='voicegender', create_type=True)
    voice_gender_enum.create(op.get_bind(), checkfirst=True)
    
    # Add the column with the enum type and default value
    op.add_column('agents', sa.Column('voice_gender', sa.Enum('male', 'female', name='voicegender'), nullable=False, server_default='female'))


def downgrade() -> None:
    op.drop_column('agents', 'voice_gender')
    op.execute('DROP TYPE IF EXISTS voicegender')
