"""drop fraud detector columns from reports

Revision ID: 6302d4752f03
Revises: 22c6fafccec1
Create Date: 2026-04-07 21:45:56.954934

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6302d4752f03"
down_revision: str | Sequence[str] | None = "22c6fafccec1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove unused fraud detector columns from reports table."""
    with op.batch_alter_table("reports", schema=None) as batch_op:
        batch_op.drop_column("fraud_flags")
        batch_op.drop_column("fraud_risk_level")
        batch_op.drop_column("fraud_risk_score")


def downgrade() -> None:
    """Re-add fraud detector columns to reports table."""
    with op.batch_alter_table("reports", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("fraud_risk_score", sa.FLOAT(), server_default="0.0", nullable=False)
        )
        batch_op.add_column(
            sa.Column(
                "fraud_risk_level", sa.VARCHAR(length=10), server_default="LOW", nullable=False
            )
        )
        batch_op.add_column(
            sa.Column("fraud_flags", sa.TEXT(), server_default="[]", nullable=False)
        )
