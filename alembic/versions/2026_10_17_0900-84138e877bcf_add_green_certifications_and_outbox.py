"""add green certifications and the outbox

Revision ID: 84138e877bcf
Revises: 0fb418f2daea
Create Date: 2026-10-17 09:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '84138e877bcf'
down_revision: str | Sequence[str] | None = '0fb418f2daea'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('green_certifications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('certification_id', sa.String(length=64), nullable=False),
    sa.Column('submission_id', sa.String(length=64), nullable=False),
    sa.Column('company_id', sa.String(length=64), nullable=False),
    sa.Column('mype_user_id', sa.String(length=64), nullable=False),
    sa.Column('ruc', sa.String(length=11), nullable=False),
    sa.Column('business_name', sa.String(length=255), nullable=False),
    sa.Column('object_key', sa.String(length=255), nullable=False),
    sa.Column('content_type', sa.String(length=40), nullable=False),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('extraction', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('criteria', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('decision', sa.String(length=20), nullable=False),
    sa.Column('standard', sa.String(length=20), nullable=True),
    sa.Column('issuer', sa.String(length=300), nullable=True),
    sa.Column('valid_until', sa.Date(), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('reader', sa.String(length=80), nullable=False),
    sa.Column('rules_version', sa.String(length=20), nullable=False),
    sa.Column('source_event_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_green_certifications')),
    sa.UniqueConstraint('certification_id', name=op.f('uq_green_certifications_certification_id')),
    sa.UniqueConstraint('submission_id', name=op.f('uq_green_certifications_submission_id'))
    )
    op.create_index(op.f('ix_green_certifications_mype_user_id'), 'green_certifications', ['mype_user_id'], unique=False)
    op.create_table('outbox_messages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('event_id', sa.String(length=64), nullable=False),
    sa.Column('event_type', sa.String(length=80), nullable=False),
    sa.Column('topic', sa.String(length=255), nullable=False),
    sa.Column('message_key', sa.String(length=255), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_outbox_messages')),
    sa.UniqueConstraint('event_id', name=op.f('uq_outbox_messages_event_id'))
    )
    op.create_index('ix_outbox_messages_due', 'outbox_messages', ['sent_at', 'next_attempt_at'], unique=False)
    op.add_column('risk_assessments', sa.Column('green_status', sa.String(length=30), nullable=True))
    op.add_column('risk_assessments', sa.Column('green_certificate', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('risk_assessments', 'green_certificate')
    op.drop_column('risk_assessments', 'green_status')
    op.drop_index('ix_outbox_messages_due', table_name='outbox_messages')
    op.drop_table('outbox_messages')
    op.drop_index(op.f('ix_green_certifications_mype_user_id'), table_name='green_certifications')
    op.drop_table('green_certifications')
