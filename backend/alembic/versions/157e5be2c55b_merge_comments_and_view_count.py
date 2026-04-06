"""merge comments and view_count

Revision ID: 157e5be2c55b
Revises: b2c3d4e5f6g7, c6f4d8e9b1a2
Create Date: 2026-03-30 14:41:06.618785

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '157e5be2c55b'
down_revision: Union[str, Sequence[str], None] = ('b2c3d4e5f6g7', 'c6f4d8e9b1a2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
