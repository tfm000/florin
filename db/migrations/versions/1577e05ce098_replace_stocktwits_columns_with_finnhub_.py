"""Replace StockTwits columns with Finnhub, ApeWisdom, AlphaVantage

Revision ID: 1577e05ce098
Revises: 7e4d30e77675
Create Date: 2026-04-07 19:21:47.144523

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1577e05ce098'
down_revision: Union[str, Sequence[str], None] = '7e4d30e77675'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('reports', schema=None) as batch_op:
        batch_op.add_column(sa.Column('finnhub_score', sa.Float(), server_default='0.0', nullable=False))
        batch_op.add_column(sa.Column('apewisdom_mentions', sa.Integer(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('alphavantage_sentiment', sa.Float(), server_default='0.0', nullable=False))
        batch_op.drop_column('stocktwits_bearish')
        batch_op.drop_column('stocktwits_bullish')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('reports', schema=None) as batch_op:
        batch_op.add_column(sa.Column('stocktwits_bullish', sa.INTEGER(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('stocktwits_bearish', sa.INTEGER(), server_default='0', nullable=False))
        batch_op.drop_column('alphavantage_sentiment')
        batch_op.drop_column('apewisdom_mentions')
        batch_op.drop_column('finnhub_score')
