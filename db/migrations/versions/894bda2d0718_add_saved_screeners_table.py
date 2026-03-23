"""add_saved_screeners_table

Revision ID: 894bda2d0718
Revises: 28887d027e99
Create Date: 2026-03-23 11:39:28.855709

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '894bda2d0718'
down_revision: Union[str, Sequence[str], None] = '28887d027e99'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('saved_screeners',
    sa.Column('id', sa.String(length=16), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('filters_json', sa.Text(), nullable=False),
    sa.Column('sort_by', sa.String(length=50), nullable=False),
    sa.Column('sort_asc', sa.Boolean(), nullable=False),
    sa.Column('is_alert_active', sa.Boolean(), nullable=False),
    sa.Column('max_alerts_per_day', sa.Integer(), nullable=False),
    sa.Column('alerts_sent_today', sa.Integer(), nullable=False),
    sa.Column('include_llm_report', sa.Boolean(), nullable=False),
    sa.Column('last_run_at', sa.DateTime(), nullable=True),
    sa.Column('run_interval_seconds', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('saved_screeners')
