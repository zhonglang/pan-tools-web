"""create download tasks

Revision ID: 006_download_tasks
Revises: 005_share_snapshots
Create Date: 2026-09-23
"""

from alembic import op
import sqlalchemy as sa

revision = "006_download_tasks"
down_revision = "005_share_snapshots"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "download_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("pan_accounts.id"), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("phase", sa.String(length=16), nullable=False),
        sa.Column("bytes_done", sa.BigInteger(), nullable=False),
        sa.Column("bytes_total", sa.BigInteger(), nullable=False),
        sa.Column("files_done", sa.Integer(), nullable=False),
        sa.Column("files_total", sa.Integer(), nullable=False),
        sa.Column("current_name", sa.String(length=255), nullable=True),
        sa.Column("directory", sa.String(length=1024), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_download_tasks_user_id", "download_tasks", ["user_id"])
    op.create_index("ix_download_tasks_account_id", "download_tasks", ["account_id"])


def downgrade():
    op.drop_index("ix_download_tasks_account_id", table_name="download_tasks")
    op.drop_index("ix_download_tasks_user_id", table_name="download_tasks")
    op.drop_table("download_tasks")
