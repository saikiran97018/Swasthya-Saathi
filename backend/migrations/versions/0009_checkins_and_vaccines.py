"""symptom check-in switch, child's date of birth, vaccination milestones

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-22 15:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import app.database.models


revision: str = '0009'
down_revision: Union[str, None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('user_preferences', schema=None) as batch_op:
        batch_op.add_column(sa.Column('symptom_checkins', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    with op.batch_alter_table('family_members', schema=None) as batch_op:
        batch_op.add_column(sa.Column('birth_date', sa.Date(), nullable=True))
    op.create_table('vaccination_milestones',
    sa.Column('family_member_id', sa.Uuid(), nullable=False),
    sa.Column('milestone', sa.String(length=8), nullable=False),
    sa.Column('given_on', sa.Date(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', app.database.models.UTCDateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', app.database.models.UTCDateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['family_member_id'], ['family_members.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('family_member_id', 'milestone', name='uq_vaccination_member_milestone')
    )
    op.create_index('ix_vaccination_milestones_family_member_id', 'vaccination_milestones', ['family_member_id'])


def downgrade() -> None:
    op.drop_index('ix_vaccination_milestones_family_member_id', table_name='vaccination_milestones')
    op.drop_table('vaccination_milestones')
    with op.batch_alter_table('family_members', schema=None) as batch_op:
        batch_op.drop_column('birth_date')
    with op.batch_alter_table('user_preferences', schema=None) as batch_op:
        batch_op.drop_column('symptom_checkins')
