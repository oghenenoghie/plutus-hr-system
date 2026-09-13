"""employee documents

Revision ID: 3c5a87d64254
Revises: 0414eddb3643
Create Date: 2026-09-13 00:36:07.173681

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3c5a87d64254'
down_revision: Union[str, Sequence[str], None] = '0414eddb3643'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'employee_documents',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column(
            'category',
            sa.Enum(
                'identification', 'contract', 'certificate', 'offer_letter', 'other',
                name='document_category',
            ),
            nullable=False,
        ),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('storage_url', sa.String(length=2000), nullable=False),
        sa.Column('expiry_date', sa.Date(), nullable=True),
        sa.Column('uploaded_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploaded_by'], ['accounts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_employee_documents_employee_id', 'employee_documents', ['employee_id'])

    op.execute("ALTER TABLE employee_documents ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE employee_documents FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY employee_documents_tenant_isolation ON employee_documents "
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_employee_documents_employee_id', table_name='employee_documents')
    op.drop_table('employee_documents')
    sa.Enum(name='document_category').drop(op.get_bind(), checkfirst=False)
