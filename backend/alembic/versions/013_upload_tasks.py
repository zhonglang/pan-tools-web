"""create upload tasks

Revision ID: 013_upload_tasks
Revises: 012_account_stat_days
Create Date: 2026-10-18
"""

from alembic import op
import sqlalchemy as sa

revision = "013_upload_tasks"
down_revision = "012_account_stat_days"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "upload_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("pan_accounts.id"), nullable=False),
        sa.Column("dest_path", sa.String(length=1024), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("bytes_done", sa.BigInteger(), nullable=False),
        sa.Column("bytes_total", sa.BigInteger(), nullable=False),
        sa.Column("files_done", sa.Integer(), nullable=False),
        sa.Column("files_total", sa.Integer(), nullable=False),
        sa.Column("current_name", sa.String(length=255), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_upload_tasks_user_id", "upload_tasks", ["user_id"])
    op.create_index("ix_upload_tasks_account_id", "upload_tasks", ["account_id"])


def downgrade():
    op.drop_index("ix_upload_tasks_account_id", table_name="upload_tasks")
    op.drop_index("ix_upload_tasks_user_id", table_name="upload_tasks")
    op.drop_table("upload_tasks")
