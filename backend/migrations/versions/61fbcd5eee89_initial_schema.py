"""initial schema

Revision ID: 61fbcd5eee89
Revises:
Create Date: 2026-02-25 19:56:13.931330
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "61fbcd5eee89"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply this migration."""
    op.create_table(
        "HappyHourLocations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("Name", sa.String(), nullable=False),
        sa.Column("Closed", sa.Boolean(), nullable=False),
        sa.Column("Illegal", sa.Boolean(), nullable=False),
        sa.Column("URL", sa.String(), nullable=True),
        sa.Column("AddressRaw", sa.String(), nullable=False),
        sa.Column("Number", sa.Integer(), nullable=False),
        sa.Column("StreetName", sa.String(), nullable=False),
        sa.Column("City", sa.String(), nullable=False),
        sa.Column("State", sa.String(), nullable=False),
        sa.Column("ZipCode", sa.String(), nullable=False),
        sa.Column("Latitude", sa.Float(), nullable=False),
        sa.Column("Longitude", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("phone_provider", sa.Integer(), nullable=False),
        sa.Column("account_provider", sa.Integer(), nullable=False),
        sa.Column("external_unique_id", sa.String(), nullable=False),
        sa.Column("claims", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(), server_default="pending_approval", nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_provider", "external_unique_id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("phone"),
        sa.UniqueConstraint("username"),
    )
    op.create_table(
        "HappyHourEvents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("Description", sa.String(), nullable=True),
        sa.Column("When", sa.DateTime(), nullable=False),
        sa.Column("LocationID", sa.Integer(), nullable=False),
        sa.Column("TyrantID", sa.Integer(), nullable=True),
        sa.Column("AutoSelected", sa.Boolean(), nullable=False),
        sa.Column("week_of", sa.String(length=8), nullable=False),
        sa.ForeignKeyConstraint(
            ["LocationID"],
            ["HappyHourLocations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["TyrantID"],
            ["accounts.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("week_of", name="uq_events_week_of"),
    )
    with op.batch_alter_table("HappyHourEvents", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_HappyHourEvents_When"), ["When"], unique=False
        )

    op.create_table(
        "HappyHourTyrantRotation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("cycle", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(), nullable=False),
        sa.Column("deadline_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "account_claim_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "requester_provider",
            sa.Integer(),
            nullable=False,
            comment="OIDC provider of the user making the claim",
        ),
        sa.Column(
            "requester_external_id",
            sa.String(),
            nullable=False,
            comment="OIDC 'sub' of the user making the claim",
        ),
        sa.Column(
            "requester_name",
            sa.String(),
            nullable=False,
            comment="Display name from the OIDC identity (for admin review)",
        ),
        sa.Column(
            "requester_email",
            sa.String(),
            nullable=True,
            comment="Email from the OIDC identity (for admin review)",
        ),
        sa.Column(
            "target_account_id",
            sa.Integer(),
            nullable=False,
            comment="The legacy account being claimed",
        ),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["target_account_id"],
            ["accounts.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "receipts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("Credits", sa.Integer(), nullable=False),
        sa.Column("Time", sa.DateTime(), nullable=False),
        sa.Column("RecorderId", sa.Integer(), nullable=True),
        sa.Column("PayerId", sa.Integer(), nullable=False),
        sa.Column("RecipientId", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            '"PayerId" != "RecipientId"', name="ck_receipts_no_self_payment"
        ),
        sa.CheckConstraint('"Credits" > 0', name="ck_receipts_positive_credits"),
        sa.ForeignKeyConstraint(
            ["PayerId"],
            ["accounts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["RecipientId"],
            ["accounts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["RecorderId"],
            ["accounts.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("receipts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_receipts_Time"), ["Time"], unique=False)


def downgrade() -> None:
    """Revert this migration."""
    op.drop_table("receipts")
    op.drop_table("account_claim_requests")
    op.drop_table("HappyHourTyrantRotation")
    op.drop_table("HappyHourEvents")
    op.drop_table("accounts")
    op.drop_table("HappyHourLocations")
