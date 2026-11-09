"""Create the users table. Safe: only adds things."""

import sqlalchemy as sa
from alembic import op


def upgrade() -> None:
    op.create_table("users", sa.Column("id", sa.Integer(), primary_key=True))


def downgrade() -> None:
    op.drop_table("users")
