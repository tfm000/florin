"""add thinking_mode to llm_models

Revision ID: 22c6fafccec1
Revises: a6a699d1cea8
Create Date: 2026-04-07 21:13:28.062481

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "22c6fafccec1"
down_revision: str | Sequence[str] | None = "a6a699d1cea8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add thinking_mode column to llm_models table."""
    with op.batch_alter_table("llm_models", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("thinking_mode", sa.String(length=10), nullable=True),
        )


def downgrade() -> None:
    """Remove thinking_mode column from llm_models table."""
    with op.batch_alter_table("llm_models", schema=None) as batch_op:
        batch_op.drop_column("thinking_mode")
