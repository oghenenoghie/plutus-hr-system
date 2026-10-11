"""journal entry headers, accounting settings, remittance journal link

Revision ID: 4f1c9a7e2b30
Revises: 9de09a72d28d
Create Date: 2026-10-11 19:10:00.000000

Pure DDL, additive only — no UPDATE or DELETE of any existing row, and no
backfill. A journal that pre-dates journal_entries gets a LEGACY header
lazily, the first time something needs one (app/services/posting.py
ensure_journal_header), so this migration has no dependency on the migration
role being able to bypass row-level security (audit P24).

Deliberately NOT added here: a foreign key from ledger_entries to
journal_entries or to chart_accounts. Several ledger writers (bills,
invoices, credit notes, fixed assets, contractor WHT, manual journals) do
not create a header yet, and a rolling deploy can briefly run old code
against the new schema — either FK would turn that into a hard failure.
It belongs in a follow-up once every writer goes through the posting
service.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4f1c9a7e2b30'
down_revision: Union[str, Sequence[str], None] = '9de09a72d28d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SOURCE_TYPES = (
    'payroll',
    'payroll_disbursement',
    'statutory_accrual',
    'statutory_remittance',
    'expense_claim',
    'expense_reimbursement',
    'expenditure',
    'bill',
    'vendor_payment',
    'contractor_payment',
    'invoice',
    'customer_payment',
    'credit_note',
    'receipt',
    'loan_disbursement',
    'fixed_asset',
    'bank_transaction',
    'manual_journal',
    'opening_balance',
    'reversal',
    'year_end_close',
    'legacy',
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'journal_entries',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('entry_date', sa.Date(), nullable=False),
        sa.Column(
            'source_type',
            sa.Enum(*_SOURCE_TYPES, name='journal_source_type'),
            nullable=False,
        ),
        sa.Column('source_id', sa.UUID(), nullable=True),
        sa.Column('source_event', sa.String(length=64), nullable=False),
        sa.Column('reference', sa.String(length=255), nullable=True),
        sa.Column('description', sa.String(length=500), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='NGN'),
        sa.Column('reversal_of_id', sa.UUID(), nullable=True),
        sa.Column('reversal_reason', sa.String(length=500), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.CheckConstraint(
            'reversal_of_id IS NULL OR reversal_reason IS NOT NULL',
            name='ck_journal_reversal_has_reason',
        ),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['reversal_of_id'], ['journal_entries.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    # A journal can be reversed at most once.
    op.create_index('uq_journal_reversal_of', 'journal_entries', ['reversal_of_id'], unique=True)
    # A business event (this payslip locked, that liability remitted) can be
    # posted at most once. Partial: a journal with no source document (a
    # manual entry, an adopted legacy journal) is exempt.
    op.create_index(
        'uq_journal_source_event',
        'journal_entries',
        ['org_id', 'source_type', 'source_id', 'source_event'],
        unique=True,
        postgresql_where=sa.text('source_id IS NOT NULL'),
    )
    op.create_index(
        'ix_journal_entries_org_entry_date', 'journal_entries', ['org_id', 'entry_date']
    )

    # Same tenant-isolation pattern as every other business table, and
    # append-only like the ledger lines it heads (forbid_update_delete() is
    # created by the payroll-core migration).
    op.execute('ALTER TABLE journal_entries ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE journal_entries FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY journal_entries_tenant_isolation ON journal_entries '
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )
    op.execute(
        'CREATE TRIGGER trg_journal_entries_append_only '
        'BEFORE UPDATE OR DELETE ON journal_entries '
        'FOR EACH ROW EXECUTE FUNCTION forbid_update_delete()'
    )

    # The balance trigger scans ledger_entries by journal_entry_id on every
    # insert, and every report groups by account — neither had an index
    # (audit P18).
    op.create_index('ix_ledger_entries_journal_entry_id', 'ledger_entries', ['journal_entry_id'])
    op.create_index('ix_ledger_entries_org_account', 'ledger_entries', ['org_id', 'account'])

    op.create_table(
        'accounting_settings',
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column(
            'post_statutory_remittances',
            sa.Boolean(),
            server_default=sa.text('false'),
            nullable=False,
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('org_id'),
    )
    op.execute('ALTER TABLE accounting_settings ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE accounting_settings FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY accounting_settings_tenant_isolation ON accounting_settings '
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )

    op.add_column(
        'statutory_liabilities',
        sa.Column('remittance_journal_id', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'fk_statutory_liabilities_remittance_journal',
        'statutory_liabilities',
        'journal_entries',
        ['remittance_journal_id'],
        ['id'],
        ondelete='RESTRICT',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        'fk_statutory_liabilities_remittance_journal', 'statutory_liabilities', type_='foreignkey'
    )
    op.drop_column('statutory_liabilities', 'remittance_journal_id')

    op.drop_table('accounting_settings')

    op.drop_index('ix_ledger_entries_org_account', table_name='ledger_entries')
    op.drop_index('ix_ledger_entries_journal_entry_id', table_name='ledger_entries')

    # The append-only trigger would block nothing here (DROP TABLE is not a
    # row DELETE), but dropping the headers discards the reversal and source
    # links permanently — downgrade only on a database you can afford to lose
    # them from.
    op.drop_table('journal_entries')
    sa.Enum(name='journal_source_type').drop(op.get_bind(), checkfirst=False)
