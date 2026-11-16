"""add company verifications

Revision ID: 5ac28db13b7f
Revises: 84138e877bcf
Create Date: 2026-10-29 17:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '5ac28db13b7f'
down_revision: str | Sequence[str] | None = '84138e877bcf'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('company_verifications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('verification_id', sa.String(length=64), nullable=False),
    sa.Column('request_id', sa.String(length=64), nullable=False),
    sa.Column('company_id', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.String(length=64), nullable=False),
    sa.Column('ruc', sa.String(length=11), nullable=False),
    sa.Column('business_name', sa.String(length=255), nullable=False),
    sa.Column('object_key', sa.String(length=255), nullable=False),
    sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('facts', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('checks', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('field_errors', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('demo', sa.Boolean(), nullable=False),
    sa.Column('decision', sa.String(length=30), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('rules_version', sa.String(length=20), nullable=False),
    sa.Column('source_event_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_company_verifications')),
    sa.UniqueConstraint('request_id', name=op.f('uq_company_verifications_request_id')),
    sa.UniqueConstraint('verification_id', name=op.f('uq_company_verifications_verification_id'))
    )
    op.create_index(op.f('ix_company_verifications_company_id'), 'company_verifications', ['company_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_company_verifications_company_id'), table_name='company_verifications')
    op.drop_table('company_verifications')
