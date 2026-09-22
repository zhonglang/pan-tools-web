"""create pan accounts

Revision ID: 002_pan_accounts
Revises: 001_users
Create Date: 2026-09-22
"""

from alembic import op
import sqlalchemy as sa

revision = "002_pan_accounts"
down_revision = "001_users"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pan_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("nickname", sa.String(length=255), nullable=False),
        sa.Column("cookie_ciphertext", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_pan_accounts_user_id", "pan_accounts", ["user_id"])


def downgrade():
    op.drop_index("ix_pan_accounts_user_id", table_name="pan_accounts")
    op.drop_table("pan_accounts")
