"""enhance transaction review

Revision ID: a52f9b88d8f0
Revises: 6e7d98ac5b9d
Create Date: 2026-06-21 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a52f9b88d8f0'
down_revision: Union[str, None] = '6e7d98ac5b9d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add columns to transactions table
    op.add_column('transactions', sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('transactions', sa.Column('assigned_analyst', sa.String(length=255), nullable=True))
    
    # 2. Update enum values or type in postgres/sqlite.
    bind = op.get_bind()
    dialect_name = bind.dialect.name
    
    if dialect_name == "postgresql":
        # Add new roles to userrole
        # Run in autocommit mode since ALTER TYPE ... ADD VALUE cannot be executed in transaction block in PG
        op.execute("COMMIT")
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'fraud_analyst'")
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'staff'")
        # Re-start transaction since alembic expects one
        op.execute("BEGIN")

        # Create new enum type, cast column, drop old enum type
        op.execute("ALTER TYPE transactionstatus RENAME TO transactionstatus_old")
        # Create new type
        op.execute("CREATE TYPE transactionstatus AS ENUM ('PENDING', 'APPROVED', 'REJECTED', 'FLAGGED')")
        # Update column to use new type (with capitalization mapping)
        op.execute(
            "ALTER TABLE transactions ALTER COLUMN status TYPE transactionstatus USING "
            "CASE "
            "  WHEN status::text = 'pending' THEN 'PENDING'::transactionstatus "
            "  WHEN status::text = 'approved' THEN 'APPROVED'::transactionstatus "
            "  WHEN status::text = 'rejected' THEN 'REJECTED'::transactionstatus "
            "  WHEN status::text = 'flagged' THEN 'FLAGGED'::transactionstatus "
            "  ELSE 'PENDING'::transactionstatus "
            "END"
        )
        op.execute("DROP TYPE transactionstatus_old")

    else:
        # SQLite or other: just update values since they are text/varchar
        op.execute("UPDATE transactions SET status = 'PENDING' WHERE status = 'pending'")
        op.execute("UPDATE transactions SET status = 'APPROVED' WHERE status = 'approved'")
        op.execute("UPDATE transactions SET status = 'REJECTED' WHERE status = 'rejected'")
        op.execute("UPDATE transactions SET status = 'FLAGGED' WHERE status = 'flagged'")


def downgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name
    
    if dialect_name == "postgresql":
        op.execute("ALTER TYPE transactionstatus RENAME TO transactionstatus_old")
        op.execute("CREATE TYPE transactionstatus AS ENUM ('pending', 'approved', 'rejected', 'flagged')")
        op.execute(
            "ALTER TABLE transactions ALTER COLUMN status TYPE transactionstatus USING "
            "CASE "
            "  WHEN status::text = 'PENDING' THEN 'pending'::transactionstatus "
            "  WHEN status::text = 'APPROVED' THEN 'approved'::transactionstatus "
            "  WHEN status::text = 'REJECTED' THEN 'rejected'::transactionstatus "
            "  WHEN status::text = 'FLAGGED' THEN 'flagged'::transactionstatus "
            "  ELSE 'pending'::transactionstatus "
            "END"
        )
        op.execute("DROP TYPE transactionstatus_old")
    else:
        op.execute("UPDATE transactions SET status = 'pending' WHERE status = 'PENDING'")
        op.execute("UPDATE transactions SET status = 'approved' WHERE status = 'APPROVED'")
        op.execute("UPDATE transactions SET status = 'rejected' WHERE status = 'REJECTED'")
        op.execute("UPDATE transactions SET status = 'flagged' WHERE status = 'FLAGGED'")

    op.drop_column('transactions', 'assigned_analyst')
    op.drop_column('transactions', 'reviewed_at')
