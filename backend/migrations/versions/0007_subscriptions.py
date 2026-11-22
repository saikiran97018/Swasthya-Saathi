"""Razorpay subscriptions and webhook idempotency

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-22 10:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import app.database.models


revision: str = '0007'
down_revision: Union[str, None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> list:
    return [
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', app.database.models.UTCDateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', app.database.models.UTCDateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    ]


def upgrade() -> None:
    op.create_table('subscriptions',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('plan', sa.String(length=16), nullable=False),
    sa.Column('razorpay_subscription_id', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('current_end', app.database.models.UTCDateTime(timezone=True), nullable=True),
    sa.Column('cancel_at_cycle_end', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    sa.Column('paid_count', sa.Integer(), nullable=False, server_default='0'),
    sa.Column('last_payment_id', sa.String(length=64), nullable=True),
    *_timestamps(),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_subscriptions_user', 'subscriptions', ['user_id'])
    op.create_index('ux_subscriptions_razorpay_id', 'subscriptions', ['razorpay_subscription_id'], unique=True)
    op.create_table('billing_events',
    sa.Column('event_id', sa.String(length=80), nullable=False),
    sa.Column('event_type', sa.String(length=48), nullable=False),
    *_timestamps(),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ux_billing_events_event_id', 'billing_events', ['event_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ux_billing_events_event_id', table_name='billing_events')
    op.drop_table('billing_events')
    op.drop_index('ux_subscriptions_razorpay_id', table_name='subscriptions')
    op.drop_index('ix_subscriptions_user', table_name='subscriptions')
    op.drop_table('subscriptions')
