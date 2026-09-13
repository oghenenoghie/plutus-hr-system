"""bank statement lines

Revision ID: 72ae442129b3
Revises: 4e7853be4383
Create Date: 2026-09-13 01:11:27.310525

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '72ae442129b3'
down_revision: Union[str, Sequence[str], None] = '4e7853be4383'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'bank_statement_lines',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('account_code', sa.String(length=64), nullable=False),
        sa.Column('transaction_date', sa.Date(), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=False),
        sa.Column('amount_minor', sa.BigInteger(), nullable=False),
        sa.Column('external_reference', sa.String(length=255), nullable=True),
        sa.Column('matched_ledger_entry_id', sa.UUID(), nullable=True),
        sa.Column('matched_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('matched_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['matched_ledger_entry_id'], ['ledger_entries.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['matched_by'], ['accounts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_bank_statement_lines_org_account',
        'bank_statement_lines',
        ['org_id', 'account_code'],
    )

    op.execute("ALTER TABLE bank_statement_lines ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE bank_statement_lines FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY bank_statement_lines_tenant_isolation ON bank_statement_lines "
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_bank_statement_lines_org_account', table_name='bank_statement_lines')
    op.drop_table('bank_statement_lines')
