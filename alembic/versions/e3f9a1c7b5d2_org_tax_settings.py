"""org tax settings

Revision ID: e3f9a1c7b5d2
Revises: d2b7e4a9c615
Create Date: 2026-10-27 08:00:00.000000

The figures an organisation enters itself for its country's payroll rules
(Tax Settings, app/compliance/engine/settings.py): those the sources behind
The Gambia's, Rwanda's, Kenya's, Ghana's and Côte d'Ivoire's rules didn't
settle. Each row is one value from a date, with who entered it.
Tenant-isolated and append-only: a change is a new row, so what each pay run
used stays on record.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3f9a1c7b5d2"
down_revision: Union[str, Sequence[str], None] = "d2b7e4a9c615"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "org_tax_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.String(length=64), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("entered_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("length(value) > 0", name="ck_org_tax_settings_value"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entered_by"], ["accounts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_org_tax_settings_lookup",
        "org_tax_settings",
        ["org_id", "country_code", "key", "effective_from"],
    )
    op.execute("ALTER TABLE org_tax_settings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE org_tax_settings FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY org_tax_settings_tenant_isolation ON org_tax_settings "
        "USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
    )
    op.execute(
        "CREATE TRIGGER trg_org_tax_settings_append_only "
        "BEFORE UPDATE OR DELETE ON org_tax_settings "
        "FOR EACH ROW EXECUTE FUNCTION forbid_update_delete()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_org_tax_settings_append_only ON org_tax_settings")
    op.drop_index("ix_org_tax_settings_lookup", table_name="org_tax_settings")
    op.drop_table("org_tax_settings")
