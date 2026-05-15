"""Drop finnhub_score column

Revision ID: a6a699d1cea8
Revises: 1577e05ce098
Create Date: 2026-04-07 21:00:31.689814

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a6a699d1cea8"
down_revision: str | Sequence[str] | None = "1577e05ce098"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("reports", schema=None) as batch_op:
        batch_op.drop_column("finnhub_score")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("reports", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("finnhub_score", sa.FLOAT(), server_default="0.0", nullable=False)
        )
