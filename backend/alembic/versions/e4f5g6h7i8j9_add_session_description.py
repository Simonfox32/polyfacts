"""add session description"""

from alembic import op
import sqlalchemy as sa

revision = "e4f5g6h7i8j9"
down_revision = "d3e4f5g6h7i8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sessions", sa.Column("description", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("sessions", "description")
