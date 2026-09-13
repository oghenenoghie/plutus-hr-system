"""document templates and generated documents

Revision ID: e892ece863b5
Revises: 3f24a0b209e6
Create Date: 2026-09-13 01:42:44.804059

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e892ece863b5'
down_revision: Union[str, Sequence[str], None] = '3f24a0b209e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_DOCUMENT_TYPES = (
    'offer_letter', 'confirmation_letter', 'employment_contract', 'salary_certificate', 'other'
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'document_templates',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column(
            'document_type', sa.Enum(*_DOCUMENT_TYPES, name='document_template_type'), nullable=False
        ),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('body_template', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'generated_documents',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('template_id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column(
            'document_type', sa.Enum(*_DOCUMENT_TYPES, name='generated_document_type'), nullable=False
        ),
        sa.Column('rendered_content', sa.Text(), nullable=False),
        sa.Column(
            'status',
            sa.Enum('draft', 'sent_for_signature', 'signed', name='generated_document_status'),
            nullable=False,
        ),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('signed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('signed_by_name', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['template_id'], ['document_templates.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_generated_documents_employee_id', 'generated_documents', ['employee_id']
    )

    for table in ('document_templates', 'generated_documents'):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_generated_documents_employee_id', table_name='generated_documents')
    op.drop_table('generated_documents')
    op.drop_table('document_templates')
    sa.Enum(name='generated_document_status').drop(op.get_bind(), checkfirst=False)
    sa.Enum(name='generated_document_type').drop(op.get_bind(), checkfirst=False)
    sa.Enum(name='document_template_type').drop(op.get_bind(), checkfirst=False)
