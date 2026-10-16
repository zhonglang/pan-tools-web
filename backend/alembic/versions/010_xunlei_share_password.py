"""add the default xunlei share password

Revision ID: 010_xunlei_share_password
Revises: 009_share_settings
Create Date: 2026-10-10
"""

from alembic import op
import sqlalchemy as sa

revision = "010_xunlei_share_password"
down_revision = "009_share_settings"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("share_settings", sa.Column("xunlei_password", sa.String(length=4), nullable=True))


def downgrade():
    op.drop_column("share_settings", "xunlei_password")
