"""Inventory accounting (Phase 3, docs/architecture/inventory-integration.md
§15): switching GL posting on, the inventory ↔ GL reconciliation, and the
journals a document posted. Values are financial, so reading them needs
inventory.valuation; switching posting on is a financial-control decision
and needs accounting.manage as well as inventory.manage."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.v1.inventory_support import ENABLED, audit, run
from app.core.deps import get_tenant_db, require_permission
from app.core.security import TokenClaims
from app.domain.permissions import Permission
from app.models.journal_entry import JournalSourceType
from app.schemas.general_ledger import JournalEntryOut
from app.schemas.inventory import InventorySettingsOut
from app.schemas.inventory_accounting import InventoryDocumentType, InventoryReconciliationOut
from app.services import inventory_accounting as accounting
from app.services.general_ledger import get_journal
from app.services.inventory_common import lock_settings
from app.services.permissions import account_has_permission

router = APIRouter(prefix="/inventory", tags=["inventory"], dependencies=ENABLED)

_VALUATION = require_permission(Permission.INVENTORY_VALUATION)
_MANAGE = require_permission(Permission.INVENTORY_MANAGE)


@router.post("/accounting/start", response_model=InventorySettingsOut)
def start_accounting(
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> object:
    """For an organisation that moved stock before inventory accounting
    existed: posts the stock it holds as an opening balance and journals
    every document from now on. One-way."""
    if not account_has_permission(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        permission=Permission.ACCOUNTING_MANAGE,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="requires permission: accounting.manage",
        )

    def start() -> object:
        settings = lock_settings(db, claims.org_id)
        journal = accounting.start_gl_posting(
            db, settings=settings, actor_account_id=claims.account_id
        )
        audit(
            db,
            claims,
            "inventory_settings.start_accounting",
            "inventory_settings",
            claims.org_id,
            {
                "opening_journal_id": str(journal.id) if journal else None,
                "opening_value_minor": accounting.stock_value_minor(db, org_id=claims.org_id),
            },
        )
        return settings

    return run(start)


@router.get("/reconciliation", response_model=InventoryReconciliationOut)
def reconciliation(
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_VALUATION),
) -> InventoryReconciliationOut:
    return InventoryReconciliationOut(**accounting.reconciliation(db, org_id=claims.org_id))


@router.get("/journals", response_model=list[JournalEntryOut])
def document_journals(
    document_type: InventoryDocumentType = Query(),
    document_id: uuid.UUID = Query(),
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_VALUATION),
) -> list[JournalEntryOut]:
    """Every journal one inventory document posted, with its reversals."""
    ids = accounting.document_journal_ids(
        db,
        org_id=claims.org_id,
        source_type=JournalSourceType(document_type.value),
        source_id=document_id,
    )
    return [
        get_journal(db, org_id=claims.org_id, journal_entry_id=journal_id) for journal_id in ids
    ]
