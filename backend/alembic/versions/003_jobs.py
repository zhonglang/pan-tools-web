"""create jobs and daily usage

Revision ID: 003_jobs
Revises: 002_pan_accounts
Create Date: 2026-09-22
"""

from alembic import op
import sqlalchemy as sa

revision = "003_jobs"
down_revision = "002_pan_accounts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("pan_accounts.id"), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("directory", sa.String(length=1024), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_jobs_user_id", "jobs", ["user_id"])
    op.create_index("ix_jobs_account_id", "jobs", ["account_id"])
    op.create_table(
        "job_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_job_items_job_id", "job_items", ["job_id"])
    op.create_table(
        "daily_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("transfer_count", sa.Integer(), nullable=False),
        sa.Column("share_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("user_id", "usage_date", name="uq_daily_usage_user_day"),
    )
    op.create_index("ix_daily_usage_user_id", "daily_usage", ["user_id"])


def downgrade():
    op.drop_index("ix_daily_usage_user_id", table_name="daily_usage")
    op.drop_table("daily_usage")
    op.drop_index("ix_job_items_job_id", table_name="job_items")
    op.drop_table("job_items")
    op.drop_index("ix_jobs_account_id", table_name="jobs")
    op.drop_index("ix_jobs_user_id", table_name="jobs")
    op.drop_table("jobs")
