"""add portfolio cache tables

Revision ID: portfolio_cache
Revises: portfolio_description
Create Date: 2026-03-22 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'portfolio_cache'
down_revision: Union[str, Sequence[str], None] = 'portfolio_description'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create portfolio cache tables."""
    op.create_table(
        'portfolio_cache_meta',
        sa.Column('portfolio_id', sa.String(16), primary_key=True),
        sa.Column('start_date', sa.String(10), nullable=False),
        sa.Column('end_date', sa.String(10), nullable=False),
        # Analytics
        sa.Column('total_return', sa.Float(), nullable=True),
        sa.Column('annualized_vol', sa.Float(), nullable=True),
        sa.Column('sharpe', sa.Float(), nullable=True),
        sa.Column('sortino', sa.Float(), nullable=True),
        sa.Column('max_drawdown', sa.Float(), nullable=True),
        sa.Column('var_95', sa.Float(), nullable=True),
        sa.Column('cvar_95', sa.Float(), nullable=True),
        # Weighted fundamentals
        sa.Column('weighted_pe', sa.Float(), nullable=True),
        sa.Column('weighted_forward_pe', sa.Float(), nullable=True),
        sa.Column('weighted_dividend_yield', sa.Float(), nullable=True),
        sa.Column('weighted_beta', sa.Float(), nullable=True),
        # Average fundamentals
        sa.Column('avg_pe', sa.Float(), nullable=True),
        sa.Column('avg_forward_pe', sa.Float(), nullable=True),
        sa.Column('avg_dividend_yield', sa.Float(), nullable=True),
        sa.Column('avg_beta', sa.Float(), nullable=True),
        # Max fundamentals
        sa.Column('max_pe', sa.Float(), nullable=True),
        sa.Column('max_forward_pe', sa.Float(), nullable=True),
        sa.Column('max_dividend_yield', sa.Float(), nullable=True),
        sa.Column('max_beta', sa.Float(), nullable=True),
        # Min fundamentals
        sa.Column('min_pe', sa.Float(), nullable=True),
        sa.Column('min_forward_pe', sa.Float(), nullable=True),
        sa.Column('min_dividend_yield', sa.Float(), nullable=True),
        sa.Column('min_beta', sa.Float(), nullable=True),
        # Counts
        sa.Column('holdings_count', sa.Integer(), default=0),
        sa.Column('priceable_count', sa.Integer(), default=0),
        sa.Column('computed_at', sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        'portfolio_cache_returns',
        sa.Column('id', sa.String(16), primary_key=True),
        sa.Column('portfolio_id', sa.String(16), nullable=False),
        sa.Column('date', sa.String(10), nullable=False),
        sa.Column('cumulative_return', sa.Float(), nullable=False),
        sa.Column('prorated', sa.Boolean(), default=False),
    )
    op.create_index(
        'ix_cache_returns_lookup',
        'portfolio_cache_returns',
        ['portfolio_id', 'prorated', 'date'],
    )


def downgrade() -> None:
    """Drop portfolio cache tables."""
    op.drop_index('ix_cache_returns_lookup', table_name='portfolio_cache_returns')
    op.drop_table('portfolio_cache_returns')
    op.drop_table('portfolio_cache_meta')
