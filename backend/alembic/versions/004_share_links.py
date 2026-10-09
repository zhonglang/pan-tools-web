"""create share links

Revision ID: 004_share_links
Revises: 003_jobs
Create Date: 2026-09-23
"""

from alembic import op
import sqlalchemy as sa

revision = "004_share_links"
down_revision = "003_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "share_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("pan_accounts.id"), nullable=False),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("baidu_share_id", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("password", sa.String(length=16), nullable=True),
        sa.Column("expired", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("view_count", sa.Integer(), nullable=True),
        sa.Column("transfer_count", sa.Integer(), nullable=True),
        sa.Column("download_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_share_links_user_id", "share_links", ["user_id"])
    op.create_index("ix_share_links_account_id", "share_links", ["account_id"])
    op.create_index("ix_share_links_job_id", "share_links", ["job_id"])


def downgrade():
    op.drop_index("ix_share_links_job_id", table_name="share_links")
    op.drop_index("ix_share_links_account_id", table_name="share_links")
    op.drop_index("ix_share_links_user_id", table_name="share_links")
    op.drop_table("share_links")
