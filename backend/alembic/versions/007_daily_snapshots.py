"""keep one snapshot per share per Shanghai day

Revision ID: 007_daily_snapshots
Revises: 006_download_tasks
Create Date: 2026-09-23
"""

from alembic import op

revision = "007_daily_snapshots"
down_revision = "006_download_tasks"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        DELETE FROM share_stat_snapshots
        WHERE id NOT IN (
            SELECT DISTINCT ON (share_link_id, (taken_at AT TIME ZONE 'Asia/Shanghai')::date) id
            FROM share_stat_snapshots
            ORDER BY share_link_id, (taken_at AT TIME ZONE 'Asia/Shanghai')::date, taken_at DESC, id DESC
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_share_stat_snapshots_share_day
        ON share_stat_snapshots (share_link_id, ((taken_at AT TIME ZONE 'Asia/Shanghai')::date))
        """
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS uq_share_stat_snapshots_share_day")
