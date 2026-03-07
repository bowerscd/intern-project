"""add theme column to accounts

Revision ID: a2f4c8d91e03
Revises: 61fbcd5eee89
Create Date: 2026-03-07 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a2f4c8d91e03"
down_revision: Union[str, None] = "61fbcd5eee89"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add theme column with default value."""
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "theme", sa.String(length=32), server_default="default", nullable=False
            ),
        )


def downgrade() -> None:
    """Remove theme column."""
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.drop_column("theme")
