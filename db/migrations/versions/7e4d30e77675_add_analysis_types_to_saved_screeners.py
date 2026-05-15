"""add analysis_types to saved_screeners

Revision ID: 7e4d30e77675
Revises: 35275979bf12
Create Date: 2026-03-24 00:25:00.171509

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7e4d30e77675"
down_revision: str | Sequence[str] | None = "35275979bf12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("saved_screeners", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "analysis_types",
                sa.Text(),
                nullable=False,
                server_default='["announcement", "sentiment"]',
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("saved_screeners", schema=None) as batch_op:
        batch_op.drop_column("analysis_types")
