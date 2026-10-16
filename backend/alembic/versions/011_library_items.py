"""store grouped pan links for one drama

Revision ID: 011_library_items
Revises: 010_xunlei_share_password
Create Date: 2026-10-11
"""

from alembic import op
import sqlalchemy as sa

revision = "011_library_items"
down_revision = "010_xunlei_share_password"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "library_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("xunlei_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("quark_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("baidu_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "prefix"),
    )


def downgrade():
    op.drop_table("library_items")
