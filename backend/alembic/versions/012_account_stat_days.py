"""account daily stat totals for charts and range cards

Revision ID: 012_account_stat_days
Revises: 011_library_items
Create Date: 2026-10-15
"""

from alembic import op
import sqlalchemy as sa

revision = "012_account_stat_days"
down_revision = "011_library_items"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    exists = conn.execute(
        sa.text("SELECT to_regclass('public.account_stat_days') IS NOT NULL")
    ).scalar()
    if not exists:
        op.create_table(
            "account_stat_days",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("account_id", sa.Integer(), sa.ForeignKey("pan_accounts.id"), nullable=False),
            sa.Column("stat_date", sa.Date(), nullable=False),
            sa.Column("transfer_total", sa.Integer(), nullable=True),
            sa.Column("view_total", sa.Integer(), nullable=True),
            sa.Column("download_total", sa.Integer(), nullable=True),
            sa.Column("link_total", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("account_id", "stat_date", name="uq_account_stat_days_account_date"),
        )
        op.create_index("ix_account_stat_days_account_id", "account_stat_days", ["account_id"])
        op.create_index("ix_account_stat_days_account_date", "account_stat_days", ["account_id", "stat_date"])
    else:
        op.execute("CREATE INDEX IF NOT EXISTS ix_account_stat_days_account_id ON account_stat_days (account_id)")
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_account_stat_days_account_date ON account_stat_days (account_id, stat_date)"
        )
        op.execute(
            """
            DO $$ BEGIN
                ALTER TABLE account_stat_days
                ADD CONSTRAINT uq_account_stat_days_account_date UNIQUE (account_id, stat_date);
            EXCEPTION WHEN duplicate_object OR duplicate_table THEN
                NULL;
            END $$
            """
        )
    op.execute(
        """
        INSERT INTO account_stat_days (
            account_id, stat_date, transfer_total, view_total, download_total, link_total, updated_at
        )
        SELECT
            account_id,
            ((taken_at AT TIME ZONE 'Asia/Shanghai')::date) AS stat_date,
            SUM(transfer_count) FILTER (WHERE transfer_count IS NOT NULL),
            SUM(view_count) FILTER (WHERE view_count IS NOT NULL),
            SUM(download_count) FILTER (WHERE download_count IS NOT NULL),
            COUNT(DISTINCT share_link_id),
            NOW()
        FROM (
            SELECT DISTINCT ON (
                account_id,
                share_link_id,
                ((taken_at AT TIME ZONE 'Asia/Shanghai')::date)
            )
                account_id,
                share_link_id,
                transfer_count,
                view_count,
                download_count,
                taken_at
            FROM share_stat_snapshots
            ORDER BY
                account_id,
                share_link_id,
                ((taken_at AT TIME ZONE 'Asia/Shanghai')::date),
                taken_at DESC,
                id DESC
        ) AS last_per_share_day
        GROUP BY account_id, ((taken_at AT TIME ZONE 'Asia/Shanghai')::date)
        ON CONFLICT (account_id, stat_date) DO UPDATE SET
            transfer_total = EXCLUDED.transfer_total,
            view_total = EXCLUDED.view_total,
            download_total = EXCLUDED.download_total,
            link_total = EXCLUDED.link_total,
            updated_at = EXCLUDED.updated_at
        """
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_account_stat_days_account_date")
    op.execute("DROP INDEX IF EXISTS ix_account_stat_days_account_id")
    op.drop_table("account_stat_days")
