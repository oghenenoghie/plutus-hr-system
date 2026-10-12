"""Inventory operations API (Phase 2): purchase orders, goods receipts,
stock issues and transfers. See docs/architecture/inventory-integration.md
§14.

Permissions (§7.1, D7): inventory.view to read; inventory.purchase for
orders; inventory.receive for goods receipts; inventory.issue to raise and
post issues; inventory.request to raise issues for a department you head;
inventory.transfer for transfers; inventory.approve to approve or reject any
of them (the organisation's approval workflow then decides which step the
caller may sign). Every endpoint answers 409 until inventory is enabled, and
every change records an audit event.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.v1.inventory_support import (
    ENABLED,
    audit,
    not_found,
    require_any_permission,
    run,
    sees_values,
)
from app.core.deps import get_tenant_db, require_permission
from app.core.security import TokenClaims
from app.domain.permissions import Permission
from app.models.inventory_documents import (
    GoodsReceiptStatus,
    InventoryGoodsReceipt,
    InventoryPurchaseOrder,
    InventoryStockIssue,
    InventoryStockTransfer,
    PurchaseOrderStatus,
    StockIssueStatus,
    StockTransferStatus,
)
from app.schemas.inventory_documents import (
    DecisionIn,
    GoodsReceiptCreate,
    GoodsReceiptOut,
    GoodsReceiptUpdate,
    IssueDepartmentOut,
    PurchaseOrderCreate,
    PurchaseOrderOut,
    ReasonIn,
    StockIssueCreate,
    StockIssueOut,
    StockTransferCreate,
    StockTransferOut,
    TransferDispatchIn,
    TransferReceiveIn,
)
from app.services import inventory_document_queries as views
from app.services import inventory_issues as issues
from app.services import inventory_purchasing as purchasing
from app.services import inventory_transfers as transfers

router = APIRouter(prefix="/inventory", tags=["inventory"], dependencies=ENABLED)

_VIEW = require_permission(Permission.INVENTORY_VIEW)
_PURCHASE = require_permission(Permission.INVENTORY_PURCHASE)
_RECEIVE = require_permission(Permission.INVENTORY_RECEIVE)
_ISSUE = require_permission(Permission.INVENTORY_ISSUE)
_TRANSFER = require_permission(Permission.INVENTORY_TRANSFER)
_APPROVE = require_permission(Permission.INVENTORY_APPROVE)
_RAISE_ISSUE = require_any_permission(Permission.INVENTORY_ISSUE, Permission.INVENTORY_REQUEST)
_READ_ISSUES = require_any_permission(Permission.INVENTORY_VIEW, Permission.INVENTORY_REQUEST)
# An issue has a requesting employee, so its workflow can have direct-manager
# and department-head steps — signed by people who usually hold only
# inventory.request. Either permission reaches the endpoint; the approval
# engine then decides whether this caller may sign the current step.
_DECIDE_ISSUE = require_any_permission(Permission.INVENTORY_APPROVE, Permission.INVENTORY_REQUEST)

# --- purchase orders --------------------------------------------------------


def _po_view(db: Session, order: InventoryPurchaseOrder) -> PurchaseOrderOut:
    return views.purchase_order_views(db, [order], with_lines=True)[0]


def _po_audit(
    db: Session, claims: TokenClaims, action: str, order: InventoryPurchaseOrder, **extra: Any
) -> None:
    audit(
        db,
        claims,
        f"inventory_purchase_order.{action}",
        "inventory_purchase_order",
        order.id,
        {"po_number": order.po_number, "status": order.status.value, **extra},
    )


@router.get("/purchase-orders", response_model=list[PurchaseOrderOut])
def list_purchase_orders(
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_VIEW),
    status_filter: PurchaseOrderStatus | None = Query(default=None, alias="status"),
    vendor_id: uuid.UUID | None = None,
    limit: int = Query(default=200, gt=0, le=500),
) -> list[PurchaseOrderOut]:
    orders = views.list_purchase_orders(db, status=status_filter, vendor_id=vendor_id, limit=limit)
    return views.purchase_order_views(db, orders, with_lines=False)


@router.post(
    "/purchase-orders", response_model=PurchaseOrderOut, status_code=status.HTTP_201_CREATED
)
def create_purchase_order(
    body: PurchaseOrderCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_PURCHASE),
) -> PurchaseOrderOut:
    order = run(
        lambda: purchasing.create_purchase_order(
            db, org_id=claims.org_id, actor_account_id=claims.account_id, body=body
        )
    )
    _po_audit(db, claims, "create", order, lines=len(body.lines))
    return _po_view(db, order)


@router.get("/purchase-orders/{po_id}", response_model=PurchaseOrderOut)
def get_purchase_order(
    po_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_VIEW),
) -> PurchaseOrderOut:
    order = db.get(InventoryPurchaseOrder, po_id)
    if order is None:
        not_found("purchase order")
    assert order is not None
    return _po_view(db, order)


@router.put("/purchase-orders/{po_id}", response_model=PurchaseOrderOut)
def update_purchase_order(
    po_id: uuid.UUID,
    body: PurchaseOrderCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_PURCHASE),
) -> PurchaseOrderOut:
    order = run(lambda: purchasing.update_purchase_order(db, po_id, body))
    _po_audit(db, claims, "update", order, lines=len(body.lines))
    return _po_view(db, order)


@router.delete("/purchase-orders/{po_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_purchase_order(
    po_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_PURCHASE),
) -> Response:
    order = run(lambda: purchasing.delete_purchase_order(db, po_id))
    _po_audit(db, claims, "delete", order)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/purchase-orders/{po_id}/submit", response_model=PurchaseOrderOut)
def submit_purchase_order(
    po_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_PURCHASE),
) -> PurchaseOrderOut:
    order = run(
        lambda: purchasing.submit_purchase_order(db, po_id, actor_account_id=claims.account_id)
    )
    _po_audit(db, claims, "submit", order)
    return _po_view(db, order)


@router.post("/purchase-orders/{po_id}/approve", response_model=PurchaseOrderOut)
def approve_purchase_order(
    po_id: uuid.UUID,
    body: DecisionIn,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_APPROVE),
) -> PurchaseOrderOut:
    order = run(
        lambda: purchasing.decide_purchase_order(
            db, po_id, claims=claims, approve=True, comment=body.comment
        )
    )
    _po_audit(db, claims, "approve", order, comment=body.comment)
    return _po_view(db, order)


@router.post("/purchase-orders/{po_id}/reject", response_model=PurchaseOrderOut)
def reject_purchase_order(
    po_id: uuid.UUID,
    body: DecisionIn,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_APPROVE),
) -> PurchaseOrderOut:
    order = run(
        lambda: purchasing.decide_purchase_order(
            db, po_id, claims=claims, approve=False, comment=body.comment
        )
    )
    _po_audit(db, claims, "reject", order, comment=body.comment)
    return _po_view(db, order)


@router.post("/purchase-orders/{po_id}/issue", response_model=PurchaseOrderOut)
def issue_purchase_order(
    po_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_PURCHASE),
) -> PurchaseOrderOut:
    order = run(
        lambda: purchasing.issue_purchase_order(db, po_id, actor_account_id=claims.account_id)
    )
    _po_audit(db, claims, "issue", order)
    return _po_view(db, order)


@router.post("/purchase-orders/{po_id}/cancel", response_model=PurchaseOrderOut)
def cancel_purchase_order(
    po_id: uuid.UUID,
    body: ReasonIn,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_PURCHASE),
) -> PurchaseOrderOut:
    order = run(
        lambda: purchasing.cancel_purchase_order(
            db, po_id, actor_account_id=claims.account_id, reason=body.reason
        )
    )
    _po_audit(db, claims, "cancel", order, reason=order.close_reason)
    return _po_view(db, order)


@router.post("/purchase-orders/{po_id}/close", response_model=PurchaseOrderOut)
def close_purchase_order(
    po_id: uuid.UUID,
    body: ReasonIn,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_PURCHASE),
) -> PurchaseOrderOut:
    order = run(
        lambda: purchasing.close_purchase_order(
            db, po_id, actor_account_id=claims.account_id, reason=body.reason
        )
    )
    _po_audit(db, claims, "close", order, reason=order.close_reason)
    return _po_view(db, order)


# --- goods receipts ---------------------------------------------------------


def _grn_view(db: Session, grn: InventoryGoodsReceipt, with_value: bool) -> GoodsReceiptOut:
    return views.goods_receipt_views(db, [grn], with_lines=True, with_value=with_value)[0]


def _grn_audit(
    db: Session, claims: TokenClaims, action: str, grn: InventoryGoodsReceipt, **extra: Any
) -> None:
    audit(
        db,
        claims,
        f"inventory_goods_receipt.{action}",
        "inventory_goods_receipt",
        grn.id,
        {"grn_number": grn.grn_number, "status": grn.status.value, **extra},
    )


@router.get("/goods-receipts", response_model=list[GoodsReceiptOut])
def list_goods_receipts(
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_VIEW),
    with_value: bool = Depends(sees_values),
    status_filter: GoodsReceiptStatus | None = Query(default=None, alias="status"),
    purchase_order_id: uuid.UUID | None = None,
    limit: int = Query(default=200, gt=0, le=500),
) -> list[GoodsReceiptOut]:
    receipts = views.list_goods_receipts(
        db, status=status_filter, purchase_order_id=purchase_order_id, limit=limit
    )
    return views.goods_receipt_views(db, receipts, with_lines=False, with_value=with_value)


@router.post("/goods-receipts", response_model=GoodsReceiptOut, status_code=status.HTTP_201_CREATED)
def create_goods_receipt(
    body: GoodsReceiptCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_RECEIVE),
    with_value: bool = Depends(sees_values),
) -> GoodsReceiptOut:
    grn = run(
        lambda: purchasing.create_goods_receipt(
            db, org_id=claims.org_id, actor_account_id=claims.account_id, body=body
        )
    )
    _grn_audit(db, claims, "create", grn, purchase_order_id=str(body.purchase_order_id))
    return _grn_view(db, grn, with_value)


@router.get("/goods-receipts/{grn_id}", response_model=GoodsReceiptOut)
def get_goods_receipt(
    grn_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_VIEW),
    with_value: bool = Depends(sees_values),
) -> GoodsReceiptOut:
    grn = db.get(InventoryGoodsReceipt, grn_id)
    if grn is None:
        not_found("goods receipt")
    assert grn is not None
    return _grn_view(db, grn, with_value)


@router.put("/goods-receipts/{grn_id}", response_model=GoodsReceiptOut)
def update_goods_receipt(
    grn_id: uuid.UUID,
    body: GoodsReceiptUpdate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_RECEIVE),
    with_value: bool = Depends(sees_values),
) -> GoodsReceiptOut:
    grn = run(lambda: purchasing.update_goods_receipt(db, grn_id, body))
    _grn_audit(db, claims, "update", grn)
    return _grn_view(db, grn, with_value)


@router.delete("/goods-receipts/{grn_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goods_receipt(
    grn_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_RECEIVE),
) -> Response:
    grn = run(lambda: purchasing.delete_goods_receipt(db, grn_id))
    _grn_audit(db, claims, "delete", grn)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/goods-receipts/{grn_id}/post", response_model=GoodsReceiptOut)
def post_goods_receipt(
    grn_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_RECEIVE),
    with_value: bool = Depends(sees_values),
) -> GoodsReceiptOut:
    grn = run(lambda: purchasing.post_goods_receipt(db, grn_id, actor_account_id=claims.account_id))
    _grn_audit(db, claims, "post", grn)
    return _grn_view(db, grn, with_value)


@router.post("/goods-receipts/{grn_id}/reverse", response_model=GoodsReceiptOut)
def reverse_goods_receipt(
    grn_id: uuid.UUID,
    body: ReasonIn,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_RECEIVE),
    with_value: bool = Depends(sees_values),
) -> GoodsReceiptOut:
    grn = run(
        lambda: purchasing.reverse_goods_receipt(
            db, grn_id, actor_account_id=claims.account_id, reason=body.reason
        )
    )
    _grn_audit(db, claims, "reverse", grn, reason=grn.reversal_reason)
    return _grn_view(db, grn, with_value)


# --- stock issues -----------------------------------------------------------


def _issue_view(db: Session, issue: InventoryStockIssue, with_value: bool) -> StockIssueOut:
    return views.issue_views(db, [issue], with_lines=True, with_value=with_value)[0]


def _issue_audit(
    db: Session, claims: TokenClaims, action: str, issue: InventoryStockIssue, **extra: Any
) -> None:
    audit(
        db,
        claims,
        f"inventory_stock_issue.{action}",
        "inventory_stock_issue",
        issue.id,
        {"issue_number": issue.issue_number, "status": issue.status.value, **extra},
    )


@router.get("/issues/departments", response_model=list[IssueDepartmentOut])
def list_issue_departments(
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_RAISE_ISSUE),
) -> list[IssueDepartmentOut]:
    return [
        IssueDepartmentOut(id=department.id, name=department.name)
        for department in issues.issue_departments(db, claims)
    ]


@router.get("/issues", response_model=list[StockIssueOut])
def list_issues(
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_READ_ISSUES),
    with_value: bool = Depends(sees_values),
    status_filter: StockIssueStatus | None = Query(default=None, alias="status"),
    warehouse_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    limit: int = Query(default=200, gt=0, le=500),
) -> list[StockIssueOut]:
    scope = issues.issue_scope(db, claims, write=False)
    found = views.list_issues(
        db,
        scope,
        status=status_filter,
        warehouse_id=warehouse_id,
        department_id=department_id,
        limit=limit,
    )
    return views.issue_views(db, found, with_lines=False, with_value=with_value)


@router.post("/issues", response_model=StockIssueOut, status_code=status.HTTP_201_CREATED)
def create_issue(
    body: StockIssueCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_RAISE_ISSUE),
    with_value: bool = Depends(sees_values),
) -> StockIssueOut:
    issue = run(lambda: issues.create_issue(db, claims=claims, body=body))
    _issue_audit(db, claims, "create", issue, lines=len(body.lines))
    return _issue_view(db, issue, with_value)


@router.get("/issues/{issue_id}", response_model=StockIssueOut)
def get_issue(
    issue_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_READ_ISSUES),
    with_value: bool = Depends(sees_values),
) -> StockIssueOut:
    scope = issues.issue_scope(db, claims, write=False)
    issue = run(lambda: issues.get_issue(db, issue_id, scope))
    return _issue_view(db, issue, with_value)


@router.put("/issues/{issue_id}", response_model=StockIssueOut)
def update_issue(
    issue_id: uuid.UUID,
    body: StockIssueCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_RAISE_ISSUE),
    with_value: bool = Depends(sees_values),
) -> StockIssueOut:
    issue = run(lambda: issues.update_issue(db, issue_id, claims=claims, body=body))
    _issue_audit(db, claims, "update", issue, lines=len(body.lines))
    return _issue_view(db, issue, with_value)


@router.delete("/issues/{issue_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_issue(
    issue_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_RAISE_ISSUE),
) -> Response:
    issue = run(lambda: issues.delete_issue(db, issue_id, claims=claims))
    _issue_audit(db, claims, "delete", issue)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/issues/{issue_id}/submit", response_model=StockIssueOut)
def submit_issue(
    issue_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_RAISE_ISSUE),
    with_value: bool = Depends(sees_values),
) -> StockIssueOut:
    issue = run(lambda: issues.submit_issue(db, issue_id, claims=claims))
    _issue_audit(db, claims, "submit", issue)
    return _issue_view(db, issue, with_value)


@router.post("/issues/{issue_id}/approve", response_model=StockIssueOut)
def approve_issue(
    issue_id: uuid.UUID,
    body: DecisionIn,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_DECIDE_ISSUE),
    with_value: bool = Depends(sees_values),
) -> StockIssueOut:
    issue = run(
        lambda: issues.decide_issue(db, issue_id, claims=claims, approve=True, comment=body.comment)
    )
    _issue_audit(db, claims, "approve", issue, comment=body.comment)
    return _issue_view(db, issue, with_value)


@router.post("/issues/{issue_id}/reject", response_model=StockIssueOut)
def reject_issue(
    issue_id: uuid.UUID,
    body: DecisionIn,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_DECIDE_ISSUE),
    with_value: bool = Depends(sees_values),
) -> StockIssueOut:
    issue = run(
        lambda: issues.decide_issue(
            db, issue_id, claims=claims, approve=False, comment=body.comment
        )
    )
    _issue_audit(db, claims, "reject", issue, comment=body.comment)
    return _issue_view(db, issue, with_value)


@router.post("/issues/{issue_id}/cancel", response_model=StockIssueOut)
def cancel_issue(
    issue_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_RAISE_ISSUE),
    with_value: bool = Depends(sees_values),
) -> StockIssueOut:
    issue = run(lambda: issues.cancel_issue(db, issue_id, claims=claims))
    _issue_audit(db, claims, "cancel", issue)
    return _issue_view(db, issue, with_value)


@router.post("/issues/{issue_id}/post", response_model=StockIssueOut)
def post_issue(
    issue_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_ISSUE),
    with_value: bool = Depends(sees_values),
) -> StockIssueOut:
    issue = run(lambda: issues.post_issue(db, issue_id, actor_account_id=claims.account_id))
    _issue_audit(db, claims, "post", issue)
    return _issue_view(db, issue, with_value)


@router.post("/issues/{issue_id}/reverse", response_model=StockIssueOut)
def reverse_issue(
    issue_id: uuid.UUID,
    body: ReasonIn,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_ISSUE),
    with_value: bool = Depends(sees_values),
) -> StockIssueOut:
    issue = run(
        lambda: issues.reverse_issue(
            db, issue_id, actor_account_id=claims.account_id, reason=body.reason
        )
    )
    _issue_audit(db, claims, "reverse", issue, reason=issue.reversal_reason)
    return _issue_view(db, issue, with_value)


# --- transfers --------------------------------------------------------------


def _transfer_view(db: Session, transfer: InventoryStockTransfer) -> StockTransferOut:
    return views.transfer_views(db, [transfer], with_lines=True)[0]


def _transfer_audit(
    db: Session, claims: TokenClaims, action: str, transfer: InventoryStockTransfer, **extra: Any
) -> None:
    audit(
        db,
        claims,
        f"inventory_stock_transfer.{action}",
        "inventory_stock_transfer",
        transfer.id,
        {"transfer_number": transfer.transfer_number, "status": transfer.status.value, **extra},
    )


@router.get("/transfers", response_model=list[StockTransferOut])
def list_transfers(
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_VIEW),
    status_filter: StockTransferStatus | None = Query(default=None, alias="status"),
    warehouse_id: uuid.UUID | None = None,
    limit: int = Query(default=200, gt=0, le=500),
) -> list[StockTransferOut]:
    found = views.list_transfers(db, status=status_filter, warehouse_id=warehouse_id, limit=limit)
    return views.transfer_views(db, found, with_lines=False)


@router.post("/transfers", response_model=StockTransferOut, status_code=status.HTTP_201_CREATED)
def create_transfer(
    body: StockTransferCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_TRANSFER),
) -> StockTransferOut:
    transfer = run(
        lambda: transfers.create_transfer(
            db, org_id=claims.org_id, actor_account_id=claims.account_id, body=body
        )
    )
    _transfer_audit(db, claims, "create", transfer, lines=len(body.lines))
    return _transfer_view(db, transfer)


@router.get("/transfers/{transfer_id}", response_model=StockTransferOut)
def get_transfer(
    transfer_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_VIEW),
) -> StockTransferOut:
    transfer = db.get(InventoryStockTransfer, transfer_id)
    if transfer is None:
        not_found("transfer")
    assert transfer is not None
    return _transfer_view(db, transfer)


@router.put("/transfers/{transfer_id}", response_model=StockTransferOut)
def update_transfer(
    transfer_id: uuid.UUID,
    body: StockTransferCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_TRANSFER),
) -> StockTransferOut:
    transfer = run(lambda: transfers.update_transfer(db, transfer_id, body))
    _transfer_audit(db, claims, "update", transfer, lines=len(body.lines))
    return _transfer_view(db, transfer)


@router.delete("/transfers/{transfer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transfer(
    transfer_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_TRANSFER),
) -> Response:
    transfer = run(lambda: transfers.delete_transfer(db, transfer_id))
    _transfer_audit(db, claims, "delete", transfer)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/transfers/{transfer_id}/submit", response_model=StockTransferOut)
def submit_transfer(
    transfer_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_TRANSFER),
) -> StockTransferOut:
    transfer = run(
        lambda: transfers.submit_transfer(db, transfer_id, actor_account_id=claims.account_id)
    )
    _transfer_audit(db, claims, "submit", transfer)
    return _transfer_view(db, transfer)


@router.post("/transfers/{transfer_id}/approve", response_model=StockTransferOut)
def approve_transfer(
    transfer_id: uuid.UUID,
    body: DecisionIn,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_APPROVE),
) -> StockTransferOut:
    transfer = run(
        lambda: transfers.decide_transfer(
            db, transfer_id, claims=claims, approve=True, comment=body.comment
        )
    )
    _transfer_audit(db, claims, "approve", transfer, comment=body.comment)
    return _transfer_view(db, transfer)


@router.post("/transfers/{transfer_id}/reject", response_model=StockTransferOut)
def reject_transfer(
    transfer_id: uuid.UUID,
    body: DecisionIn,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_APPROVE),
) -> StockTransferOut:
    transfer = run(
        lambda: transfers.decide_transfer(
            db, transfer_id, claims=claims, approve=False, comment=body.comment
        )
    )
    _transfer_audit(db, claims, "reject", transfer, comment=body.comment)
    return _transfer_view(db, transfer)


@router.post("/transfers/{transfer_id}/cancel", response_model=StockTransferOut)
def cancel_transfer(
    transfer_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_TRANSFER),
) -> StockTransferOut:
    transfer = run(
        lambda: transfers.cancel_transfer(db, transfer_id, actor_account_id=claims.account_id)
    )
    _transfer_audit(db, claims, "cancel", transfer)
    return _transfer_view(db, transfer)


@router.post("/transfers/{transfer_id}/dispatch", response_model=StockTransferOut)
def dispatch_transfer(
    transfer_id: uuid.UUID,
    body: TransferDispatchIn,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_TRANSFER),
) -> StockTransferOut:
    transfer = run(
        lambda: transfers.dispatch_transfer(
            db, transfer_id, actor_account_id=claims.account_id, body=body
        )
    )
    _transfer_audit(db, claims, "dispatch", transfer)
    return _transfer_view(db, transfer)


@router.post("/transfers/{transfer_id}/receive", response_model=StockTransferOut)
def receive_transfer(
    transfer_id: uuid.UUID,
    body: TransferReceiveIn,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_TRANSFER),
) -> StockTransferOut:
    transfer = run(
        lambda: transfers.receive_transfer(
            db, transfer_id, actor_account_id=claims.account_id, body=body
        )
    )
    _transfer_audit(db, claims, "receive", transfer, discrepancy_reason=transfer.discrepancy_reason)
    return _transfer_view(db, transfer)
