"""add claim reactions"""

from alembic import op
import sqlalchemy as sa

revision = "d3e4f5g6h7i8"
down_revision = "157e5be2c55b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "claim_reactions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("claim_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("reaction", sa.String(10), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "claim_id", name="uq_user_claim_reaction"),
    )


def downgrade():
    op.drop_table("claim_reactions")
