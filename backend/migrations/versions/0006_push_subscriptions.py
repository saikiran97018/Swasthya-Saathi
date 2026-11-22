"""web push subscriptions (phone / browser notifications)

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-21 14:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import app.database.models


revision: str = '0006'
down_revision: Union[str, None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('push_subscriptions',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('endpoint', sa.Text(), nullable=False),
    sa.Column('p256dh', sa.String(length=160), nullable=False),
    sa.Column('auth', sa.String(length=64), nullable=False),
    sa.Column('user_agent', sa.String(length=200), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', app.database.models.UTCDateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', app.database.models.UTCDateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_push_subscriptions_user', 'push_subscriptions', ['user_id'])
    op.create_index('ux_push_subscriptions_endpoint', 'push_subscriptions', ['endpoint'], unique=True)


def downgrade() -> None:
    op.drop_index('ux_push_subscriptions_endpoint', table_name='push_subscriptions')
    op.drop_index('ix_push_subscriptions_user', table_name='push_subscriptions')
    op.drop_table('push_subscriptions')
