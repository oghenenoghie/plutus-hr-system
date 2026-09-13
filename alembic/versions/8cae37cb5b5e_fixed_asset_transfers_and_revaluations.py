"""fixed asset transfers and revaluations

Revision ID: 8cae37cb5b5e
Revises: 72ae442129b3
Create Date: 2026-09-13 01:18:19.373289

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8cae37cb5b5e'
down_revision: Union[str, Sequence[str], None] = '72ae442129b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('fixed_assets', sa.Column('department_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_fixed_assets_department_id',
        'fixed_assets',
        'departments',
        ['department_id'],
        ['id'],
        ondelete='SET NULL',
    )

    op.create_table(
        'fixed_asset_transfers',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('fixed_asset_id', sa.UUID(), nullable=False),
        sa.Column('from_department_id', sa.UUID(), nullable=True),
        sa.Column('to_department_id', sa.UUID(), nullable=True),
        sa.Column('transfer_date', sa.Date(), nullable=False),
        sa.Column('note', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['fixed_asset_id'], ['fixed_assets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['from_department_id'], ['departments.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['to_department_id'], ['departments.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_fixed_asset_transfers_fixed_asset_id', 'fixed_asset_transfers', ['fixed_asset_id']
    )

    op.create_table(
        'fixed_asset_revaluations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('fixed_asset_id', sa.UUID(), nullable=False),
        sa.Column('revaluation_date', sa.Date(), nullable=False),
        sa.Column('old_book_value_minor', sa.BigInteger(), nullable=False),
        sa.Column('new_book_value_minor', sa.BigInteger(), nullable=False),
        sa.Column('reason', sa.String(length=500), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['fixed_asset_id'], ['fixed_assets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_fixed_asset_revaluations_fixed_asset_id',
        'fixed_asset_revaluations',
        ['fixed_asset_id'],
    )

    for table in ('fixed_asset_transfers', 'fixed_asset_revaluations'):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
        )
        # Append-only: a correction is a new row, never an edit to a prior one.
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_update_delete()"
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        'ix_fixed_asset_revaluations_fixed_asset_id', table_name='fixed_asset_revaluations'
    )
    op.drop_table('fixed_asset_revaluations')
    op.drop_index('ix_fixed_asset_transfers_fixed_asset_id', table_name='fixed_asset_transfers')
    op.drop_table('fixed_asset_transfers')
    op.drop_constraint('fk_fixed_assets_department_id', 'fixed_assets', type_='foreignkey')
    op.drop_column('fixed_assets', 'department_id')
