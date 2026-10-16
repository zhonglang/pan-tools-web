"""store each user's default share passwords

Revision ID: 009_share_settings
Revises: 008_job_directory_label
Create Date: 2026-10-09
"""

from alembic import op
import sqlalchemy as sa

revision = "009_share_settings"
down_revision = "008_job_directory_label"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "share_settings",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("baidu_password", sa.String(length=4), nullable=True),
        sa.Column("quark_password", sa.String(length=4), nullable=True),
    )


def downgrade():
    op.drop_table("share_settings")
