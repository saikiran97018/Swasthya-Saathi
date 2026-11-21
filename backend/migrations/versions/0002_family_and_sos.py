"""family members, emergency contacts, appointments.family_member_id

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-21 10:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import app.database.models


revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> list:
    return [
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', app.database.models.UTCDateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', app.database.models.UTCDateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    ]


def upgrade() -> None:
    op.create_table('family_members',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('relation', sa.String(length=16), nullable=False),
    sa.Column('birth_year', sa.Integer(), nullable=True),
    sa.Column('gender', sa.String(length=10), nullable=True),
    sa.Column('mobile', sa.String(length=15), nullable=True),
    sa.Column('language', sa.String(length=8), nullable=True),
    *_timestamps(),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('family_members', schema=None) as batch_op:
        batch_op.create_index('ix_family_members_user', ['user_id'], unique=False)

    op.create_table('emergency_contacts',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('phone', sa.String(length=15), nullable=False),
    sa.Column('relation', sa.String(length=40), nullable=True),
    *_timestamps(),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('emergency_contacts', schema=None) as batch_op:
        batch_op.create_index('ix_emergency_contacts_user', ['user_id'], unique=False)

    with op.batch_alter_table('appointments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('family_member_id', sa.Uuid(), nullable=True))
        batch_op.create_foreign_key('fk_appointments_family_member', 'family_members', ['family_member_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    with op.batch_alter_table('appointments', schema=None) as batch_op:
        batch_op.drop_constraint('fk_appointments_family_member', type_='foreignkey')
        batch_op.drop_column('family_member_id')

    with op.batch_alter_table('emergency_contacts', schema=None) as batch_op:
        batch_op.drop_index('ix_emergency_contacts_user')
    op.drop_table('emergency_contacts')

    with op.batch_alter_table('family_members', schema=None) as batch_op:
        batch_op.drop_index('ix_family_members_user')
    op.drop_table('family_members')
