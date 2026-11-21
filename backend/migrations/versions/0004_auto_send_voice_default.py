"""send spoken messages automatically by default

The setting used to default to OFF, which made every voice message wait for a manual Send tap. New accounts now start with it
ON (see UserPreference.auto_send_voice). This also switches it on for accounts created before, because for them it was only the
old default, not a choice. Anyone can turn it off again in Settings ("Send what I say automatically").

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-21 12:30:00
"""
from typing import Sequence, Union

from alembic import op


revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE user_preferences SET auto_send_voice = true WHERE NOT auto_send_voice")


def downgrade() -> None:
    pass  # the old values cannot be told apart from deliberate choices any more
