"""add_fk_constraints_and_indexes

Revision ID: 28887d027e99
Revises: portfolio_cache
Create Date: 2026-03-23 02:08:02.381587

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '28887d027e99'
down_revision: Union[str, Sequence[str], None] = 'portfolio_cache'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()

    # Deduplicate risk_free_rates before adding unique constraint
    conn.execute(sa.text("""
        DELETE FROM risk_free_rates
        WHERE id NOT IN (
            SELECT MIN(id) FROM risk_free_rates
            GROUP BY currency, date
        )
    """))

    # Deduplicate breadth_snapshots before adding unique constraint
    conn.execute(sa.text("""
        DELETE FROM breadth_snapshots
        WHERE id NOT IN (
            SELECT MIN(id) FROM breadth_snapshots
            GROUP BY date, hour
        )
    """))

    # Delete orphaned portfolio_holdings (no matching portfolio)
    conn.execute(sa.text("""
        DELETE FROM portfolio_holdings
        WHERE portfolio_id NOT IN (SELECT id FROM portfolios)
    """))

    # Delete orphaned portfolio_cache_meta (no matching portfolio)
    conn.execute(sa.text("""
        DELETE FROM portfolio_cache_meta
        WHERE portfolio_id NOT IN (SELECT id FROM portfolios)
    """))

    # Delete orphaned portfolio_cache_returns (no matching portfolio)
    conn.execute(sa.text("""
        DELETE FROM portfolio_cache_returns
        WHERE portfolio_id NOT IN (SELECT id FROM portfolios)
    """))

    with op.batch_alter_table('breadth_snapshots', schema=None) as batch_op:
        batch_op.create_unique_constraint('uq_breadth_date_hour', ['date', 'hour'])

    with op.batch_alter_table('news_stories', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_news_stories_fetched_at'), ['fetched_at'], unique=False)

    with op.batch_alter_table('portfolio_cache_meta', schema=None) as batch_op:
        batch_op.alter_column('holdings_count',
               existing_type=sa.INTEGER(),
               nullable=False)
        batch_op.alter_column('priceable_count',
               existing_type=sa.INTEGER(),
               nullable=False)
        batch_op.alter_column('computed_at',
               existing_type=sa.DATETIME(),
               nullable=False,
               existing_server_default=sa.text('(CURRENT_TIMESTAMP)'))
        batch_op.create_foreign_key(
            'fk_cache_meta_portfolio', 'portfolios', ['portfolio_id'], ['id'],
            ondelete='CASCADE',
        )

    with op.batch_alter_table('portfolio_cache_returns', schema=None) as batch_op:
        batch_op.alter_column('prorated',
               existing_type=sa.BOOLEAN(),
               nullable=False)
        batch_op.create_index(
            batch_op.f('ix_portfolio_cache_returns_portfolio_id'), ['portfolio_id'], unique=False,
        )
        # Note: ix_cache_returns_lookup is created automatically by batch mode
        # from the model's __table_args__ — do not create it explicitly here.
        batch_op.create_foreign_key(
            'fk_cache_returns_portfolio', 'portfolios', ['portfolio_id'], ['id'],
            ondelete='CASCADE',
        )

    with op.batch_alter_table('portfolio_holdings', schema=None) as batch_op:
        batch_op.create_foreign_key(
            'fk_holdings_portfolio', 'portfolios', ['portfolio_id'], ['id'],
            ondelete='CASCADE',
        )

    with op.batch_alter_table('risk_free_rates', schema=None) as batch_op:
        batch_op.create_unique_constraint('uq_rfr_currency_date', ['currency', 'date'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('risk_free_rates', schema=None) as batch_op:
        batch_op.drop_constraint('uq_rfr_currency_date', type_='unique')

    with op.batch_alter_table('portfolio_holdings', schema=None) as batch_op:
        batch_op.drop_constraint('fk_holdings_portfolio', type_='foreignkey')

    with op.batch_alter_table('portfolio_cache_returns', schema=None) as batch_op:
        batch_op.drop_constraint('fk_cache_returns_portfolio', type_='foreignkey')
        # Note: ix_cache_returns_lookup was created in portfolio_cache_tables migration,
        # not here — do not drop it in this downgrade.
        batch_op.drop_index(batch_op.f('ix_portfolio_cache_returns_portfolio_id'))
        batch_op.alter_column('prorated',
               existing_type=sa.BOOLEAN(),
               nullable=True)

    with op.batch_alter_table('portfolio_cache_meta', schema=None) as batch_op:
        batch_op.drop_constraint('fk_cache_meta_portfolio', type_='foreignkey')
        batch_op.alter_column('computed_at',
               existing_type=sa.DATETIME(),
               nullable=True,
               existing_server_default=sa.text('(CURRENT_TIMESTAMP)'))
        batch_op.alter_column('priceable_count',
               existing_type=sa.INTEGER(),
               nullable=True)
        batch_op.alter_column('holdings_count',
               existing_type=sa.INTEGER(),
               nullable=True)

    with op.batch_alter_table('news_stories', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_news_stories_fetched_at'))

    with op.batch_alter_table('breadth_snapshots', schema=None) as batch_op:
        batch_op.drop_constraint('uq_breadth_date_hour', type_='unique')
