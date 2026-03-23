"""add missing FK constraints, indexes, and fix revision IDs

Revision ID: 638434f7e199
Revises: dad13af2f6e6
Create Date: 2026-03-23 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '638434f7e199'
down_revision: Union[str, Sequence[str], None] = 'dad13af2f6e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Old slug-based revision IDs that were replaced with hex IDs.
# If an existing DB still has the old IDs in alembic_version, the migration
# chain would break. This mapping lets us fix it during upgrade.
_OLD_TO_NEW = {
    'cusip_map_and_portfolio_group': 'bcfa9d0d5f1a',
    'portfolio_description': 'd7e1d7f29e54',
    'portfolio_cache': '77f433bbe71f',
}


def upgrade() -> None:
    """Add FK constraints on alerts/reports/telegram_messages and indexes on ticker columns."""
    conn = op.get_bind()

    # Fix any stale alembic_version entries from the old slug-based revision IDs
    for old_id, new_id in _OLD_TO_NEW.items():
        conn.execute(sa.text(
            "UPDATE alembic_version SET version_num = :new WHERE version_num = :old"
        ), {"old": old_id, "new": new_id})

    # Delete orphaned alerts (report_id references a non-existent report)
    conn.execute(sa.text("""
        DELETE FROM alerts
        WHERE report_id IS NOT NULL
          AND report_id != ''
          AND report_id NOT IN (SELECT id FROM reports)
    """))

    # Delete orphaned telegram_messages (report_id references a non-existent report)
    conn.execute(sa.text("""
        DELETE FROM telegram_messages
        WHERE report_id IS NOT NULL
          AND report_id != ''
          AND report_id NOT IN (SELECT id FROM reports)
    """))

    # Null out orphaned reports.trade_id (references a non-existent trade)
    conn.execute(sa.text("""
        UPDATE reports
        SET trade_id = NULL
        WHERE trade_id IS NOT NULL
          AND trade_id NOT IN (SELECT id FROM trades)
    """))

    # FK: alerts.report_id → reports.id
    with op.batch_alter_table('alerts', schema=None) as batch_op:
        batch_op.create_foreign_key(
            'fk_alerts_report', 'reports', ['report_id'], ['id'],
            ondelete='SET NULL',
        )

    # FK: reports.trade_id → trades.id
    with op.batch_alter_table('reports', schema=None) as batch_op:
        batch_op.create_foreign_key(
            'fk_reports_trade', 'trades', ['trade_id'], ['id'],
            ondelete='SET NULL',
        )

    # FK: telegram_messages.report_id → reports.id
    with op.batch_alter_table('telegram_messages', schema=None) as batch_op:
        batch_op.create_foreign_key(
            'fk_telegram_report', 'reports', ['report_id'], ['id'],
            ondelete='SET NULL',
        )

    # Index: portfolio_holdings.ticker for reverse lookups
    with op.batch_alter_table('portfolio_holdings', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_portfolio_holdings_ticker'), ['ticker'], unique=False,
        )

    # Index: cusip_ticker_map.ticker for reverse lookups
    with op.batch_alter_table('cusip_ticker_map', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_cusip_ticker_map_ticker'), ['ticker'], unique=False,
        )


def downgrade() -> None:
    """Remove FK constraints and indexes added in this migration."""
    with op.batch_alter_table('cusip_ticker_map', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_cusip_ticker_map_ticker'))

    with op.batch_alter_table('portfolio_holdings', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_portfolio_holdings_ticker'))

    with op.batch_alter_table('telegram_messages', schema=None) as batch_op:
        batch_op.drop_constraint('fk_telegram_report', type_='foreignkey')

    with op.batch_alter_table('reports', schema=None) as batch_op:
        batch_op.drop_constraint('fk_reports_trade', type_='foreignkey')

    with op.batch_alter_table('alerts', schema=None) as batch_op:
        batch_op.drop_constraint('fk_alerts_report', type_='foreignkey')
