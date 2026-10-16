"""store the folder name shown for a job

Revision ID: 008_job_directory_label
Revises: 007_daily_snapshots
Create Date: 2026-10-09
"""

from alembic import op
import sqlalchemy as sa

revision = "008_job_directory_label"
down_revision = "007_daily_snapshots"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jobs", sa.Column("directory_label", sa.String(length=1024), nullable=True))


def downgrade():
    op.drop_column("jobs", "directory_label")
