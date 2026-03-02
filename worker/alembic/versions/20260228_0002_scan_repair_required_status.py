"""Allow repair_required status for artifact integrity hardening."""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260228_0002"
down_revision = "20260224_0001"
branch_labels = None
depends_on = None


# Extend scans.status check constraint to allow repair_required.
def upgrade() -> None:
    op.execute("ALTER TABLE scans DROP CONSTRAINT IF EXISTS scans_status_chk;")
    op.execute(
        """
        ALTER TABLE scans
        ADD CONSTRAINT scans_status_chk
        CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled', 'repair_required'));
        """
    )


# Revert status constraint and remap repair_required rows to failed.
def downgrade() -> None:
    op.execute(
        """
        UPDATE scans
        SET status = 'failed',
            error = COALESCE(error, 'downgraded: repair_required status removed')
        WHERE status = 'repair_required';
        """
    )
    op.execute("ALTER TABLE scans DROP CONSTRAINT IF EXISTS scans_status_chk;")
    op.execute(
        """
        ALTER TABLE scans
        ADD CONSTRAINT scans_status_chk
        CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled'));
        """
    )
