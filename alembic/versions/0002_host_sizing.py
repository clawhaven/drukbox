"""per-request host sizing

Revision ID: 0002_host_sizing
Revises: 0001_initial
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = '0002_host_sizing'
down_revision: str | None = '0001_initial'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('hosts', sa.Column('instance_type', sa.Text(), nullable=True))
    op.add_column('hosts', sa.Column('disk_gb', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('hosts', 'disk_gb')
    op.drop_column('hosts', 'instance_type')
