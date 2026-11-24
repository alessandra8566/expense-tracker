"""Baseline the existing expense tracker schema.

Revision ID: 20261124_0001
Revises:
Create Date: 2026-11-24

"""
from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261124_0001"
down_revision = None
branch_labels = None
depends_on = None

legacy_metadata = sa.MetaData()
split_mode = postgresql.ENUM("AA", "CUSTOM", name="splitmode")
user_state = postgresql.ENUM(
    "WAITING_INPUT",
    "WAITING_PAYER",
    "WAITING_SPLIT_MODE",
    "WAITING_CUSTOM_SPLIT",
    name="stateenum",
)

users = sa.Table(
    "users",
    legacy_metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("line_user_id", sa.String(length=100), nullable=False),
    sa.Column("display_name", sa.String(length=200), nullable=False),
    sa.Column("partner_id", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column("invite_code", sa.String(length=10), nullable=True),
    sa.Column("invite_code_expires_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(["partner_id"], ["users.id"]),
    sa.PrimaryKeyConstraint("id"),
)
sa.Index("ix_users_line_user_id", users.c.line_user_id, unique=True)
sa.Index("ix_users_invite_code", users.c.invite_code, unique=True)

expenses = sa.Table(
    "expenses",
    legacy_metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("payer_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("partner_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("description", sa.String(length=200), nullable=False),
    sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column("split_mode", split_mode, nullable=False),
    sa.Column("payer_share", sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column("partner_share", sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column("is_settled", sa.Boolean(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(["payer_id"], ["users.id"]),
    sa.ForeignKeyConstraint(["partner_id"], ["users.id"]),
    sa.PrimaryKeyConstraint("id"),
)
sa.Index("ix_expenses_payer_id", expenses.c.payer_id)
sa.Index("ix_expenses_partner_id", expenses.c.partner_id)

user_states = sa.Table(
    "user_states",
    legacy_metadata,
    sa.Column("line_user_id", sa.String(length=100), nullable=False),
    sa.Column("state", user_state, nullable=False),
    sa.Column("pending_data", sa.JSON(), nullable=True),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint("line_user_id"),
)


def upgrade():
    # This frozen schema adopts the pre-Alembic production tables unchanged,
    # while creating any missing tables on a new or partially initialized DB.
    legacy_metadata.create_all(
        bind=op.get_bind(),
        checkfirst=not context.is_offline_mode(),
    )


def downgrade():
    # This baseline covers a database that may already contain user data.
    # Dropping its tables on downgrade would destroy that data.
    pass
