"""add rotation v2 states (on_deck, current)

Revision ID: b7e3a1f20d45
Revises: a2f4c8d91e03
Create Date: 2026-03-27 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b7e3a1f20d45"
down_revision: Union[str, None] = "a2f4c8d91e03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Map existing PENDING assignments to CURRENT.

    The status column is a VARCHAR storing enum string values.  No schema
    change is needed — only a data migration.  Existing PENDING rows
    represent the currently active tyrant, so they map to CURRENT.
    """
    op.execute(
        "UPDATE HappyHourTyrantRotation SET status = 'current' WHERE status = 'pending'"
    )


def downgrade() -> None:
    """Reverse the v2 state mapping.

    CURRENT → PENDING (restore original active-tyrant status).
    ON_DECK → SCHEDULED (collapse back to the simple queue).
    """
    op.execute(
        "UPDATE HappyHourTyrantRotation SET status = 'pending' WHERE status = 'current'"
    )
    op.execute(
        "UPDATE HappyHourTyrantRotation SET status = 'scheduled' WHERE status = 'on_deck'"
    )
