"""credit notes

Revision ID: 4e7853be4383
Revises: 899b1d0ab7f7
Create Date: 2026-09-13 01:05:25.409955

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4e7853be4383'
down_revision: Union[str, Sequence[str], None] = '899b1d0ab7f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'credit_notes',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('invoice_id', sa.UUID(), nullable=False),
        sa.Column('credit_note_number', sa.String(length=64), nullable=False),
        sa.Column('issue_date', sa.Date(), nullable=False),
        sa.Column('amount_minor', sa.BigInteger(), nullable=False),
        sa.Column('reason', sa.String(length=500), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'credit_note_number', name='uq_credit_note_org_number'),
    )
    op.create_index('ix_credit_notes_invoice_id', 'credit_notes', ['invoice_id'])

    op.execute("ALTER TABLE credit_notes ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE credit_notes FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY credit_notes_tenant_isolation ON credit_notes "
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )

    # Append-only, same discipline as ledger_entries/wht_payments: a posted
    # financial event is never edited or deleted, only ever corrected by a
    # new one.
    op.execute(
        "CREATE TRIGGER trg_credit_notes_append_only "
        "BEFORE UPDATE OR DELETE ON credit_notes "
        "FOR EACH ROW EXECUTE FUNCTION forbid_update_delete()"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_credit_notes_invoice_id', table_name='credit_notes')
    op.drop_table('credit_notes')
