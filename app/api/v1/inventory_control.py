"""Inventory stock control (Phase 4, docs/architecture/inventory-integration.md
§16): lots, stocktakes, reorder suggestions and the stock reports, each
report also downloadable as CSV or PDF.

Permissions: inventory.view to read; inventory.adjust to run a stocktake;
inventory.approve to approve one; the valuation report needs
inventory.valuation, and every other report leaves values out for callers
without it.
"""

import enum
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.v1.inventory_support import ENABLED, audit, changes, run, sees_values
from app.core.deps import get_tenant_db, require_permission
from app.core.security import TokenClaims
from app.domain.permissions import Permission
from app.models.inventory_control import InventoryStocktake, StocktakeStatus
from app.models.organisation import Organisation
from app.schemas.inventory_control import (
    ExpiryReportOut,
    LotStockOut,
    MovementSummaryOut,
    OutstandingOrdersOut,
    ReorderSuggestionOut,
    StocktakeCountsIn,
    StocktakeCreate,
    StocktakeLineAdd,
    StocktakeOut,
    ValuationReportOut,
    VarianceReportOut,
)
from app.schemas.inventory_documents import DecisionIn
from app.services import inventory_control_queries as queries
from app.services import inventory_report_export as export
from app.services import inventory_stocktakes as stocktakes
from app.services.jurisdiction import organisation_currency
from app.services.posting import today_lagos

router = APIRouter(prefix="/inventory", tags=["inventory"], dependencies=ENABLED)

_VIEW = require_permission(Permission.INVENTORY_VIEW)
_ADJUST = require_permission(Permission.INVENTORY_ADJUST)
_APPROVE = require_permission(Permission.INVENTORY_APPROVE)
_VALUATION = require_permission(Permission.INVENTORY_VALUATION)


class ReportFormat(str, enum.Enum):
    JSON = "json"
    CSV = "csv"
    PDF = "pdf"


def _currency(db: Session, claims: TokenClaims) -> str:
    return organisation_currency(db, claims.org_id)


def _download(
    db: Session,
    claims: TokenClaims,
    table: export.ReportTable,
    fmt: ReportFormat,
    report: str,
) -> Response:
    if fmt == ReportFormat.CSV:
        content, media_type, extension = export.to_csv(table), "text/csv; charset=utf-8", "csv"
    else:
        organisation = db.get(Organisation, claims.org_id)
        content = export.to_pdf(
            table, organisation_name=organisation.name if organisation else "Inventory"
        )
        media_type, extension = "application/pdf", "pdf"
    audit(
        db,
        claims,
        "inventory_report.export",
        "inventory_report",
        None,
        {"report": report, "format": fmt.value, "rows": len(table.rows)},
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{table.filename}.{extension}"'},
    )


# --- lots -------------------------------------------------------------------


@router.get("/lots", response_model=list[LotStockOut])
def list_lots(
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_VIEW),
    with_value: bool = Depends(sees_values),
    item_id: uuid.UUID | None = None,
    warehouse_id: uuid.UUID | None = None,
) -> list[LotStockOut]:
    """Lots holding stock, soonest expiry first."""
    return queries.lot_stock(db, item_id=item_id, warehouse_id=warehouse_id, with_value=with_value)


# --- stocktakes -------------------------------------------------------------


def _view(db: Session, stocktake: InventoryStocktake, with_value: bool) -> StocktakeOut:
    return queries.stocktake_views(db, [stocktake], with_lines=True, with_value=with_value)[0]


def _audit_stocktake(
    db: Session, claims: TokenClaims, action: str, stocktake: InventoryStocktake, **extra: object
) -> None:
    audit(
        db,
        claims,
        f"inventory_stocktake.{action}",
        "inventory_stocktake",
        stocktake.id,
        {
            "stocktake_number": stocktake.stocktake_number,
            "status": stocktake.status.value,
            **extra,
        },
    )


@router.get("/stocktakes", response_model=list[StocktakeOut])
def list_stocktakes(
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_VIEW),
    with_value: bool = Depends(sees_values),
    status_filter: StocktakeStatus | None = Query(default=None, alias="status"),
    warehouse_id: uuid.UUID | None = None,
    limit: int = Query(default=200, gt=0, le=500),
) -> list[StocktakeOut]:
    rows = queries.list_stocktakes(db, status=status_filter, warehouse_id=warehouse_id, limit=limit)
    return queries.stocktake_views(db, rows, with_lines=False, with_value=with_value)


@router.post("/stocktakes", response_model=StocktakeOut, status_code=status.HTTP_201_CREATED)
def create_stocktake(
    body: StocktakeCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_ADJUST),
    with_value: bool = Depends(sees_values),
) -> StocktakeOut:
    stocktake = run(
        lambda: stocktakes.create_stocktake(
            db, org_id=claims.org_id, actor_account_id=claims.account_id, body=body
        )
    )
    _audit_stocktake(db, claims, "create", stocktake, changes=changes(body))
    return _view(db, stocktake, with_value)


@router.get("/stocktakes/{stocktake_id}", response_model=StocktakeOut)
def get_stocktake(
    stocktake_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_VIEW),
    with_value: bool = Depends(sees_values),
) -> StocktakeOut:
    return _view(db, run(lambda: stocktakes.get_stocktake(db, stocktake_id)), with_value)


@router.get("/stocktakes/{stocktake_id}/export")
def export_stocktake(
    stocktake_id: uuid.UUID,
    fmt: ReportFormat = Query(default=ReportFormat.PDF, alias="format"),
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_VIEW),
    with_value: bool = Depends(sees_values),
) -> Response:
    """The count sheet, or once counted the variance sheet."""
    if fmt == ReportFormat.JSON:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="choose csv or pdf")
    view = _view(db, run(lambda: stocktakes.get_stocktake(db, stocktake_id)), with_value)
    return _download(
        db,
        claims,
        export.stocktake_table(view, with_value=with_value, currency=_currency(db, claims)),
        fmt,
        "stocktake",
    )


@router.put("/stocktakes/{stocktake_id}", response_model=StocktakeOut)
def update_stocktake(
    stocktake_id: uuid.UUID,
    body: StocktakeCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_ADJUST),
    with_value: bool = Depends(sees_values),
) -> StocktakeOut:
    stocktake = run(lambda: stocktakes.update_stocktake(db, stocktake_id, body))
    _audit_stocktake(db, claims, "update", stocktake, changes=changes(body))
    return _view(db, stocktake, with_value)


@router.delete("/stocktakes/{stocktake_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_stocktake(
    stocktake_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_ADJUST),
) -> Response:
    stocktake = run(lambda: stocktakes.delete_stocktake(db, stocktake_id))
    audit(
        db,
        claims,
        "inventory_stocktake.delete",
        "inventory_stocktake",
        stocktake_id,
        {"stocktake_number": stocktake.stocktake_number},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/stocktakes/{stocktake_id}/start", response_model=StocktakeOut)
def start_stocktake(
    stocktake_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_ADJUST),
    with_value: bool = Depends(sees_values),
) -> StocktakeOut:
    stocktake = run(
        lambda: stocktakes.start_stocktake(db, stocktake_id, actor_account_id=claims.account_id)
    )
    _audit_stocktake(
        db,
        claims,
        "start",
        stocktake,
        cutoff_at=stocktake.cutoff_at.isoformat() if stocktake.cutoff_at else None,
    )
    return _view(db, stocktake, with_value)


@router.put("/stocktakes/{stocktake_id}/counts", response_model=StocktakeOut)
def record_counts(
    stocktake_id: uuid.UUID,
    body: StocktakeCountsIn,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_ADJUST),
    with_value: bool = Depends(sees_values),
) -> StocktakeOut:
    stocktake = run(lambda: stocktakes.record_counts(db, stocktake_id, body))
    _audit_stocktake(db, claims, "count", stocktake, lines=len(body.counts))
    return _view(db, stocktake, with_value)


@router.post(
    "/stocktakes/{stocktake_id}/lines",
    response_model=StocktakeOut,
    status_code=status.HTTP_201_CREATED,
)
def add_stocktake_line(
    stocktake_id: uuid.UUID,
    body: StocktakeLineAdd,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_ADJUST),
    with_value: bool = Depends(sees_values),
) -> StocktakeOut:
    line = run(lambda: stocktakes.add_line(db, stocktake_id, body))
    stocktake = stocktakes.get_stocktake(db, stocktake_id)
    _audit_stocktake(db, claims, "add_line", stocktake, line_no=line.line_no, **changes(body))
    return _view(db, stocktake, with_value)


@router.delete("/stocktakes/{stocktake_id}/lines/{line_id}", response_model=StocktakeOut)
def remove_stocktake_line(
    stocktake_id: uuid.UUID,
    line_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_ADJUST),
    with_value: bool = Depends(sees_values),
) -> StocktakeOut:
    stocktake = run(lambda: stocktakes.remove_line(db, stocktake_id, line_id))
    _audit_stocktake(db, claims, "remove_line", stocktake, line_id=str(line_id))
    return _view(db, stocktake, with_value)


@router.post("/stocktakes/{stocktake_id}/submit", response_model=StocktakeOut)
def submit_stocktake(
    stocktake_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_ADJUST),
    with_value: bool = Depends(sees_values),
) -> StocktakeOut:
    stocktake = run(
        lambda: stocktakes.submit_stocktake(db, stocktake_id, actor_account_id=claims.account_id)
    )
    _audit_stocktake(db, claims, "submit", stocktake)
    return _view(db, stocktake, with_value)


def _decide(
    db: Session, claims: TokenClaims, stocktake_id: uuid.UUID, body: DecisionIn, approve: bool
) -> InventoryStocktake:
    stocktake = run(
        lambda: stocktakes.decide_stocktake(
            db, stocktake_id, claims=claims, approve=approve, comment=body.comment
        )
    )
    _audit_stocktake(
        db, claims, "approve" if approve else "reject", stocktake, comment=body.comment
    )
    return stocktake


@router.post("/stocktakes/{stocktake_id}/approve", response_model=StocktakeOut)
def approve_stocktake(
    stocktake_id: uuid.UUID,
    body: DecisionIn,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_APPROVE),
    with_value: bool = Depends(sees_values),
) -> StocktakeOut:
    return _view(db, _decide(db, claims, stocktake_id, body, approve=True), with_value)


@router.post("/stocktakes/{stocktake_id}/reject", response_model=StocktakeOut)
def reject_stocktake(
    stocktake_id: uuid.UUID,
    body: DecisionIn,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_APPROVE),
    with_value: bool = Depends(sees_values),
) -> StocktakeOut:
    return _view(db, _decide(db, claims, stocktake_id, body, approve=False), with_value)


@router.post("/stocktakes/{stocktake_id}/post", response_model=StocktakeOut)
def post_stocktake(
    stocktake_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_ADJUST),
    with_value: bool = Depends(sees_values),
) -> StocktakeOut:
    stocktake = run(
        lambda: stocktakes.post_stocktake(db, stocktake_id, actor_account_id=claims.account_id)
    )
    _audit_stocktake(db, claims, "post", stocktake)
    return _view(db, stocktake, with_value)


@router.post("/stocktakes/{stocktake_id}/cancel", response_model=StocktakeOut)
def cancel_stocktake(
    stocktake_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_ADJUST),
    with_value: bool = Depends(sees_values),
) -> StocktakeOut:
    stocktake = run(
        lambda: stocktakes.cancel_stocktake(db, stocktake_id, actor_account_id=claims.account_id)
    )
    _audit_stocktake(db, claims, "cancel", stocktake)
    return _view(db, stocktake, with_value)


# --- reorder ----------------------------------------------------------------


@router.get("/reorder-suggestions", response_model=list[ReorderSuggestionOut])
def reorder_suggestions(
    fmt: ReportFormat = Query(default=ReportFormat.JSON, alias="format"),
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_VIEW),
    with_value: bool = Depends(sees_values),
) -> list[ReorderSuggestionOut] | Response:
    rows = queries.reorder_suggestions(db, with_value=with_value)
    if fmt == ReportFormat.JSON:
        return rows
    return _download(
        db,
        claims,
        export.reorder_table(rows, with_value=with_value, currency=_currency(db, claims)),
        fmt,
        "reorder_suggestions",
    )


# --- reports ----------------------------------------------------------------


@router.get("/reports/valuation", response_model=ValuationReportOut)
def valuation_report(
    as_of: date | None = None,
    by_warehouse: bool = False,
    warehouse_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    fmt: ReportFormat = Query(default=ReportFormat.JSON, alias="format"),
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_VALUATION),
) -> ValuationReportOut | Response:
    """Stock value at the end of a day, rebuilt from the movement ledger,
    beside the inventory account's balance on the same date."""
    report = queries.valuation_report(
        db,
        org_id=claims.org_id,
        as_of=as_of or today_lagos(),
        by_warehouse=by_warehouse or warehouse_id is not None,
        warehouse_id=warehouse_id,
        category_id=category_id,
    )
    if fmt == ReportFormat.JSON:
        return report
    return _download(
        db, claims, export.valuation_table(report, currency=_currency(db, claims)), fmt, "valuation"
    )


@router.get("/reports/movements", response_model=MovementSummaryOut)
def movement_summary(
    date_from: date,
    date_to: date,
    warehouse_id: uuid.UUID | None = None,
    fmt: ReportFormat = Query(default=ReportFormat.JSON, alias="format"),
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_VIEW),
    with_value: bool = Depends(sees_values),
) -> MovementSummaryOut | Response:
    report = run(
        lambda: queries.movement_summary(
            db,
            date_from=date_from,
            date_to=date_to,
            warehouse_id=warehouse_id,
            with_value=with_value,
        )
    )
    if fmt == ReportFormat.JSON:
        return report
    return _download(
        db,
        claims,
        export.movement_table(report, with_value=with_value, currency=_currency(db, claims)),
        fmt,
        "movements",
    )


@router.get("/reports/variances", response_model=VarianceReportOut)
def variance_report(
    date_from: date,
    date_to: date,
    warehouse_id: uuid.UUID | None = None,
    fmt: ReportFormat = Query(default=ReportFormat.JSON, alias="format"),
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_VIEW),
    with_value: bool = Depends(sees_values),
) -> VarianceReportOut | Response:
    report = run(
        lambda: queries.variance_report(
            db,
            date_from=date_from,
            date_to=date_to,
            warehouse_id=warehouse_id,
            with_value=with_value,
        )
    )
    if fmt == ReportFormat.JSON:
        return report
    return _download(
        db,
        claims,
        export.variance_table(report, with_value=with_value, currency=_currency(db, claims)),
        fmt,
        "variances",
    )


@router.get("/reports/expiry", response_model=ExpiryReportOut)
def expiry_report(
    within_days: int = Query(default=30, ge=0, le=3650),
    fmt: ReportFormat = Query(default=ReportFormat.JSON, alias="format"),
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_VIEW),
    with_value: bool = Depends(sees_values),
) -> ExpiryReportOut | Response:
    report = queries.expiry_report(db, within_days=within_days, with_value=with_value)
    if fmt == ReportFormat.JSON:
        return report
    return _download(
        db,
        claims,
        export.expiry_table(report, with_value=with_value, currency=_currency(db, claims)),
        fmt,
        "expiry",
    )


@router.get("/reports/outstanding-orders", response_model=OutstandingOrdersOut)
def outstanding_orders(
    fmt: ReportFormat = Query(default=ReportFormat.JSON, alias="format"),
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_VIEW),
) -> OutstandingOrdersOut | Response:
    report = queries.outstanding_orders(db)
    if fmt == ReportFormat.JSON:
        return report
    return _download(
        db,
        claims,
        export.outstanding_table(report, currency=_currency(db, claims)),
        fmt,
        "outstanding_orders",
    )
