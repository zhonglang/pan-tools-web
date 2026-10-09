"""create share stat snapshots

Revision ID: 005_share_snapshots
Revises: 004_share_links
Create Date: 2026-09-23
"""

from alembic import op
import sqlalchemy as sa

revision = "005_share_snapshots"
down_revision = "004_share_links"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "share_stat_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("share_link_id", sa.Integer(), sa.ForeignKey("share_links.id"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("pan_accounts.id"), nullable=False),
        sa.Column("view_count", sa.Integer(), nullable=True),
        sa.Column("transfer_count", sa.Integer(), nullable=True),
        sa.Column("download_count", sa.Integer(), nullable=True),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_share_stat_snapshots_share_link_id", "share_stat_snapshots", ["share_link_id"])
    op.create_index("ix_share_stat_snapshots_account_id", "share_stat_snapshots", ["account_id"])
    op.create_index("ix_share_stat_snapshots_taken_at", "share_stat_snapshots", ["taken_at"])


def downgrade():
    op.drop_index("ix_share_stat_snapshots_taken_at", table_name="share_stat_snapshots")
    op.drop_index("ix_share_stat_snapshots_account_id", table_name="share_stat_snapshots")
    op.drop_index("ix_share_stat_snapshots_share_link_id", table_name="share_stat_snapshots")
    op.drop_table("share_stat_snapshots")
