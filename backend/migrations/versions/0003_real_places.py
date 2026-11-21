"""real places: provider source/coordinates, planned visits (appointments.clinic_confirmed)

Existing sample ("demo") providers are switched off, not deleted, so old appointments that point at them stay readable.
Run backend/scripts/remove_demo_data.py to delete them for good.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-21 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_WHERE_OLD = sa.text("status = 'booked'")
_WHERE_NEW = sa.text("status = 'booked' AND clinic_confirmed")


def upgrade() -> None:
    with op.batch_alter_table('providers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source', sa.String(length=12), nullable=False, server_default='partner'))
        batch_op.add_column(sa.Column('osm_id', sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column('lat', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('lon', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('website', sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column('opening_hours', sa.String(length=300), nullable=True))
        batch_op.create_unique_constraint('uq_providers_osm_id', ['osm_id'])

    with op.batch_alter_table('appointments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('clinic_confirmed', sa.Boolean(), nullable=False, server_default=sa.text('true')))
        batch_op.drop_index('uq_appointments_active_slot', sqlite_where=_WHERE_OLD, postgresql_where=_WHERE_OLD)
        batch_op.create_index('uq_appointments_active_slot', ['provider_id', 'starts_at'], unique=True, sqlite_where=_WHERE_NEW, postgresql_where=_WHERE_NEW)

    # The invented sample clinics stop being offered (their old appointments keep working).
    op.execute("UPDATE providers SET source = 'demo', active = false WHERE is_demo")


def downgrade() -> None:
    with op.batch_alter_table('appointments', schema=None) as batch_op:
        batch_op.drop_index('uq_appointments_active_slot', sqlite_where=_WHERE_NEW, postgresql_where=_WHERE_NEW)
        batch_op.create_index('uq_appointments_active_slot', ['provider_id', 'starts_at'], unique=True, sqlite_where=_WHERE_OLD, postgresql_where=_WHERE_OLD)
        batch_op.drop_column('clinic_confirmed')

    with op.batch_alter_table('providers', schema=None) as batch_op:
        batch_op.drop_constraint('uq_providers_osm_id', type_='unique')
        batch_op.drop_column('opening_hours')
        batch_op.drop_column('website')
        batch_op.drop_column('lon')
        batch_op.drop_column('lat')
        batch_op.drop_column('osm_id')
        batch_op.drop_column('source')
