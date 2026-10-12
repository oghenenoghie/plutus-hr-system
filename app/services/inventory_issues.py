"""Stock issues: stock handed out for consumption.

Lifecycle: draft -> (submit) -> pending_approval -> approved | rejected;
approved -> posted -> reversed; anything not yet posted can be cancelled.
When the organisation has issue approval switched off, submitting approves
at once and a draft can be posted directly. Approval runs through the
shared engine (request type stock_issue); the requesting employee resolves
direct-manager and department-head steps.

Who can do what (D7): holders of inventory.issue work on any issue and are
the only ones who post or reverse. Holders of only inventory.request (by
default department managers) can raise, edit, submit and cancel issues for
departments they head, and see only those.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import TokenClaims
from app.domain.permissions import Permission
from app.models.approval import ApprovalRequestType
from app.models.department import Department
from app.models.employee import Employee
from app.models.inventory import StockMovementType, StockSourceType
from app.models.inventory_documents import (
    InventoryStockIssue,
    InventoryStockIssueLine,
    StockIssueStatus,
)
from app.schemas.inventory_documents import StockIssueCreate
from app.services import inventory_accounting as accounting
from app.services.inventory import InventoryNotFound, get_inventory_settings, owned
from app.services.inventory_common import (
    DocumentKind,
    clean_reason,
    lock,
    next_document_number,
    open_approval,
    record_decision,
    require_not_future,
    require_operational_warehouse,
    require_status,
    resolve_quantity,
    reversal_plan,
    stamp,
)
from app.services.inventory_posting import PlannedMovement, post_movements
from app.services.permissions import account_has_permission
from app.services.posting import today_lagos

_S = StockIssueStatus


@dataclass(frozen=True)
class IssueScope:
    """Which issues the caller may see or change."""

    everything: bool
    employee_id: uuid.UUID | None  # the caller's own employee record
    department_ids: frozenset[uuid.UUID]  # departments the caller heads

    def covers(self, issue: InventoryStockIssue) -> bool:
        return self.everything or (
            issue.department_id is not None and issue.department_id in self.department_ids
        )


def issue_scope(db: Session, claims: TokenClaims, *, write: bool) -> IssueScope:
    def has(permission: Permission) -> bool:
        return account_has_permission(
            db, org_id=claims.org_id, account_id=claims.account_id, permission=permission
        )

    everything = has(Permission.INVENTORY_ISSUE) or (not write and has(Permission.INVENTORY_VIEW))
    employee = db.scalar(
        select(Employee).where(
            Employee.account_id == claims.account_id, Employee.org_id == claims.org_id
        )
    )
    departments: frozenset[uuid.UUID] = frozenset()
    if employee is not None and has(Permission.INVENTORY_REQUEST):
        departments = frozenset(
            db.scalars(
                select(Department.id).where(
                    Department.org_id == claims.org_id, Department.manager_id == employee.id
                )
            )
        )
    return IssueScope(
        everything=everything,
        employee_id=employee.id if employee is not None else None,
        department_ids=departments,
    )


def issue_departments(db: Session, claims: TokenClaims) -> list[Department]:
    """Departments the caller can raise an issue for."""
    scope = issue_scope(db, claims, write=True)
    query = select(Department).where(Department.org_id == claims.org_id).order_by(Department.name)
    if not scope.everything:
        query = query.where(Department.id.in_(scope.department_ids))
    return list(db.scalars(query))


def get_issue(db: Session, issue_id: uuid.UUID, scope: IssueScope) -> InventoryStockIssue:
    issue = db.get(InventoryStockIssue, issue_id)
    if issue is None or not scope.covers(issue):
        raise InventoryNotFound("stock issue not found")
    return issue


def _lock_issue(db: Session, issue_id: uuid.UUID, scope: IssueScope) -> InventoryStockIssue:
    issue = lock(db, InventoryStockIssue, issue_id, "stock issue")
    if not scope.covers(issue):
        raise InventoryNotFound("stock issue not found")
    return issue


def issue_lines(db: Session, issue_id: uuid.UUID) -> list[InventoryStockIssueLine]:
    return list(
        db.scalars(
            select(InventoryStockIssueLine)
            .where(InventoryStockIssueLine.issue_id == issue_id)
            .order_by(InventoryStockIssueLine.line_no)
        )
    )


def _apply_header(
    db: Session,
    issue: InventoryStockIssue,
    body: StockIssueCreate,
    scope: IssueScope,
) -> None:
    require_operational_warehouse(db, body.warehouse_id)
    require_not_future(body.issue_date, "a stock issue")
    if (
        body.department_id is not None
        and owned(db, Department, body.department_id, issue.org_id) is None
    ):
        raise InventoryNotFound("department not found")
    if not scope.everything:
        if body.department_id is None or body.department_id not in scope.department_ids:
            raise PermissionError("you can only request stock for a department you head")
        requester = scope.employee_id
    else:
        requester = body.requested_by_employee_id or scope.employee_id
        if body.requested_by_employee_id is not None and (
            owned(db, Employee, body.requested_by_employee_id, issue.org_id) is None
        ):
            raise InventoryNotFound("employee not found")
    issue.warehouse_id = body.warehouse_id
    issue.department_id = body.department_id
    issue.requested_by_employee_id = requester
    issue.issue_date = body.issue_date
    issue.purpose = body.purpose.strip()
    issue.notes = body.notes
    if not issue.purpose:
        raise ValueError("say what the stock is for")


def _write_lines(db: Session, issue: InventoryStockIssue, body: StockIssueCreate) -> None:
    for line_no, line in enumerate(body.lines, start=1):
        resolved = resolve_quantity(
            db, line_no=line_no, item_id=line.item_id, unit_id=line.unit_id, quantity=line.quantity
        )
        db.add(
            InventoryStockIssueLine(
                org_id=issue.org_id,
                issue_id=issue.id,
                line_no=line_no,
                item_id=resolved.item.id,
                unit_id=resolved.unit.id,
                quantity=resolved.quantity,
                notes=line.notes,
            )
        )


def create_issue(
    db: Session, *, claims: TokenClaims, body: StockIssueCreate
) -> InventoryStockIssue:
    scope = issue_scope(db, claims, write=True)
    if not scope.everything and not scope.department_ids:
        raise PermissionError("you can only request stock for a department you head")
    issue = InventoryStockIssue(id=uuid.uuid4(), org_id=claims.org_id, status=_S.DRAFT)
    _apply_header(db, issue, body, scope)
    issue.issue_number = next_document_number(db, claims.org_id, DocumentKind.ISSUE)
    issue.created_by = claims.account_id
    db.add(issue)
    db.flush()
    _write_lines(db, issue, body)
    db.flush()
    return issue


def update_issue(
    db: Session, issue_id: uuid.UUID, *, claims: TokenClaims, body: StockIssueCreate
) -> InventoryStockIssue:
    scope = issue_scope(db, claims, write=True)
    issue = _lock_issue(db, issue_id, scope)
    require_status(issue, issue.issue_number, _S.DRAFT, action="edited")
    _apply_header(db, issue, body, scope)
    for old in issue_lines(db, issue.id):
        db.delete(old)
    db.flush()
    _write_lines(db, issue, body)
    db.flush()
    return issue


def delete_issue(db: Session, issue_id: uuid.UUID, *, claims: TokenClaims) -> InventoryStockIssue:
    issue = _lock_issue(db, issue_id, issue_scope(db, claims, write=True))
    require_status(issue, issue.issue_number, _S.DRAFT, _S.REJECTED, action="deleted")
    db.delete(issue)
    db.flush()
    return issue


def submit_issue(db: Session, issue_id: uuid.UUID, *, claims: TokenClaims) -> InventoryStockIssue:
    issue = _lock_issue(db, issue_id, issue_scope(db, claims, write=True))
    require_status(issue, issue.issue_number, _S.DRAFT, action="submitted")
    if not issue_lines(db, issue.id):
        raise ValueError(f"{issue.issue_number} has no lines")
    stamp(issue, "submitted", claims.account_id)
    if get_inventory_settings(db, org_id=issue.org_id).require_issue_approval:
        issue.status = _S.PENDING_APPROVAL
        open_approval(
            db,
            org_id=issue.org_id,
            request_type=ApprovalRequestType.STOCK_ISSUE,
            request_id=issue.id,
            requester_employee_id=issue.requested_by_employee_id,
        )
    else:
        issue.status = _S.APPROVED
        stamp(issue, "decided", None)
    db.flush()
    return issue


def decide_issue(
    db: Session,
    issue_id: uuid.UUID,
    *,
    claims: TokenClaims,
    approve: bool,
    comment: str | None = None,
) -> InventoryStockIssue:
    issue = lock(db, InventoryStockIssue, issue_id, "stock issue")
    require_status(
        issue,
        issue.issue_number,
        _S.PENDING_APPROVAL,
        action="approved" if approve else "rejected",
    )
    if record_decision(
        db,
        claims=claims,
        request_type=ApprovalRequestType.STOCK_ISSUE,
        request_id=issue.id,
        requester_employee_id=issue.requested_by_employee_id,
        approve=approve,
        comment=comment,
    ):
        issue.status = _S.APPROVED if approve else _S.REJECTED
        stamp(issue, "decided", None)
    db.flush()
    return issue


def cancel_issue(db: Session, issue_id: uuid.UUID, *, claims: TokenClaims) -> InventoryStockIssue:
    issue = _lock_issue(db, issue_id, issue_scope(db, claims, write=True))
    require_status(
        issue,
        issue.issue_number,
        _S.DRAFT,
        _S.PENDING_APPROVAL,
        _S.APPROVED,
        action="cancelled",
    )
    issue.status = _S.CANCELLED
    stamp(issue, "cancelled", claims.account_id)
    db.flush()
    return issue


def post_issue(
    db: Session, issue_id: uuid.UUID, *, actor_account_id: uuid.UUID | None
) -> InventoryStockIssue:
    """Takes the stock out of the warehouse at the items' average cost."""
    issue = lock(db, InventoryStockIssue, issue_id, "stock issue")
    require_status(issue, issue.issue_number, _S.DRAFT, _S.APPROVED, action="posted")
    if (
        issue.status == _S.DRAFT
        and get_inventory_settings(db, org_id=issue.org_id).require_issue_approval
    ):
        raise ValueError(
            f"{issue.issue_number} needs approval before it can be posted: submit it for approval"
        )
    require_operational_warehouse(db, issue.warehouse_id)
    require_not_future(issue.issue_date, "a stock issue")
    lines = issue_lines(db, issue.id)
    if not lines:
        raise ValueError(f"{issue.issue_number} has no lines")
    planned = []
    for line in lines:
        resolved = resolve_quantity(
            db,
            line_no=line.line_no,
            item_id=line.item_id,
            unit_id=line.unit_id,
            quantity=line.quantity,
        )
        planned.append(
            PlannedMovement(
                source_line_id=line.id,
                item_id=line.item_id,
                warehouse_id=issue.warehouse_id,
                quantity_base=-resolved.quantity_base,
                movement_type=StockMovementType.ISSUE,
                reason=issue.purpose,
            )
        )
    movements = post_movements(
        db,
        org_id=issue.org_id,
        entry_date=issue.issue_date,
        source_type=StockSourceType.STOCK_ISSUE,
        source_id=issue.id,
        planned=planned,
        actor_account_id=actor_account_id,
    )
    accounting.post_issue_journal(
        db,
        org_id=issue.org_id,
        issue_id=issue.id,
        issue_number=issue.issue_number,
        purpose=issue.purpose,
        entry_date=issue.issue_date,
        movements=movements,
        actor_account_id=actor_account_id,
    )
    issue.status = _S.POSTED
    stamp(issue, "posted", actor_account_id)
    db.flush()
    return issue


def reverse_issue(
    db: Session, issue_id: uuid.UUID, *, actor_account_id: uuid.UUID | None, reason: str
) -> InventoryStockIssue:
    """Brings issued stock back, at the value it left at (e.g. issued to
    the wrong department, or returned unused)."""
    reason = clean_reason(reason, "reverse an issue")
    issue = lock(db, InventoryStockIssue, issue_id, "stock issue")
    require_status(issue, issue.issue_number, _S.POSTED, action="reversed")
    movements = post_movements(
        db,
        org_id=issue.org_id,
        entry_date=today_lagos(),
        source_type=StockSourceType.STOCK_ISSUE,
        source_id=issue.id,
        planned=reversal_plan(
            db, source_type=StockSourceType.STOCK_ISSUE, source_id=issue.id, reason=reason
        ),
        actor_account_id=actor_account_id,
    )
    accounting.post_reversal_journal(
        db,
        org_id=issue.org_id,
        stock_source=StockSourceType.STOCK_ISSUE,
        source_id=issue.id,
        document_number=issue.issue_number,
        posted_at=issue.posted_at,
        reason=reason,
        movements=movements,
        actor_account_id=actor_account_id,
    )
    issue.status = _S.REVERSED
    issue.reversal_reason = reason
    stamp(issue, "reversed", actor_account_id)
    db.flush()
    return issue
