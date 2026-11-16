"""employee documents uploaded to the app's own storage

Revision ID: d4a8b2e6f1c3
Revises: c9e6a1f4d3b5
Create Date: 2026-11-16 09:00:00.000000

An employee document can now be a file uploaded from the person's computer
or phone, kept in the app's object storage under storage_key with its name,
type and size, rather than only a link to a file stored elsewhere. So
storage_url becomes optional, and a document must have one or the other.
Existing documents keep their link.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4a8b2e6f1c3"
down_revision: Union[str, Sequence[str], None] = "c9e6a1f4d3b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "employee_documents", sa.Column("storage_key", sa.String(length=500), nullable=True)
    )
    op.add_column(
        "employee_documents", sa.Column("file_name", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "employee_documents", sa.Column("content_type", sa.String(length=100), nullable=True)
    )
    op.add_column("employee_documents", sa.Column("size_bytes", sa.BigInteger(), nullable=True))
    op.alter_column(
        "employee_documents", "storage_url", existing_type=sa.String(length=2000), nullable=True
    )
    op.create_check_constraint(
        "ck_employee_documents_has_file",
        "employee_documents",
        "storage_url IS NOT NULL OR storage_key IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_employee_documents_has_file", "employee_documents", type_="check")
    # Uploaded documents keep their row (and their file in storage), with no
    # link the old schema can follow.
    op.execute("UPDATE employee_documents SET storage_url = '' WHERE storage_url IS NULL")
    op.alter_column(
        "employee_documents", "storage_url", existing_type=sa.String(length=2000), nullable=False
    )
    op.drop_column("employee_documents", "size_bytes")
    op.drop_column("employee_documents", "content_type")
    op.drop_column("employee_documents", "file_name")
    op.drop_column("employee_documents", "storage_key")
