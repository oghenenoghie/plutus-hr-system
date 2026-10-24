"""Who may see which analytics, and over which employees.

Resolved once per request from the caller's membership: their effective
permissions (role defaults plus per-membership overrides) and, for a
department manager, the departments they head. Every section service takes
the resulting AnalyticsAccess and limits its queries with it; the API layer
refuses a section the caller lacks before any query runs.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import TokenClaims
from app.domain.permissions import Permission
from app.models.branch import Branch
from app.models.department import Department
from app.models.employee import Employee
from app.models.membership import Membership, Role
from app.schemas.analytics import Section
from app.services.analytics.filters import AnalyticsFilters, FilterError
from app.services.permissions import effective_permissions

SECTION_PERMISSIONS: dict[Section, Permission] = {
    Section.WORKFORCE: Permission.ANALYTICS_WORKFORCE_VIEW,
    Section.PAYROLL: Permission.ANALYTICS_PAYROLL_VIEW,
    Section.ATTENDANCE: Permission.ANALYTICS_ATTENDANCE_VIEW,
    Section.LEAVE: Permission.ANALYTICS_LEAVE_VIEW,
    Section.RECRUITMENT: Permission.ANALYTICS_RECRUITMENT_VIEW,
    Section.PERFORMANCE: Permission.ANALYTICS_PERFORMANCE_VIEW,
    Section.COMPLIANCE: Permission.ANALYTICS_COMPLIANCE_VIEW,
    Section.FINANCIAL: Permission.ANALYTICS_FINANCIAL_VIEW,
}

# The roles that can already open the payroll register (one line per
# employee with their pay): app/api/v1/payroll_reports.py. Anyone else who is
# granted payroll analytics sees small groups suppressed and no payslip rows.
INDIVIDUAL_PAY_ROLES = frozenset(
    {Role.ADMIN.value, Role.PAYROLL_MANAGER.value, Role.ACCOUNTANT.value, Role.AUDITOR.value}
)


class AccessDenied(Exception):
    """The caller may not see this; the API answers 403 with the message."""


@dataclass(frozen=True)
class AnalyticsAccess:
    org_id: uuid.UUID
    account_id: uuid.UUID
    role: str
    permissions: frozenset[Permission]
    # None: the whole organisation. A tuple: only employees in these
    # departments (a department manager's; empty if they head none).
    department_scope: tuple[uuid.UUID, ...] | None

    @property
    def can_view(self) -> bool:
        return Permission.ANALYTICS_VIEW in self.permissions

    @property
    def can_export(self) -> bool:
        return self.can_view and Permission.ANALYTICS_REPORTS_EXPORT in self.permissions

    @property
    def can_view_individual_pay(self) -> bool:
        return self.role in INDIVIDUAL_PAY_ROLES

    def can(self, section: Section) -> bool:
        return self.can_view and SECTION_PERMISSIONS[section] in self.permissions

    def require(self, section: Section) -> None:
        if not self.can_view:
            raise AccessDenied(f"requires permission: {Permission.ANALYTICS_VIEW.value}")
        if not self.can(section):
            raise AccessDenied(f"requires permission: {SECTION_PERMISSIONS[section].value}")

    def require_export(self) -> None:
        if not self.can_export:
            raise AccessDenied(f"requires permission: {Permission.ANALYTICS_REPORTS_EXPORT.value}")


def resolve_access(db: Session, claims: TokenClaims) -> AnalyticsAccess:
    membership = db.scalar(
        select(Membership).where(
            Membership.org_id == claims.org_id, Membership.account_id == claims.account_id
        )
    )
    permissions = effective_permissions(db, membership) if membership is not None else frozenset()

    scope: tuple[uuid.UUID, ...] | None = None
    if claims.role == Role.DEPARTMENT_MANAGER.value:
        head = db.scalar(select(Employee.id).where(Employee.account_id == claims.account_id))
        scope = (
            tuple(
                db.scalars(
                    select(Department.id)
                    .where(Department.org_id == claims.org_id, Department.manager_id == head)
                    .order_by(Department.name)
                )
            )
            if head is not None
            else ()
        )
    return AnalyticsAccess(
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        permissions=frozenset(permissions),
        department_scope=scope,
    )


def scoped_filters(
    db: Session, access: AnalyticsAccess, filters: AnalyticsFilters
) -> AnalyticsFilters:
    """Checks the department and location IDs exist in this organisation
    (row-level security already hides any other organisation's, so a
    foreign ID reads as unknown) and narrows a department manager to the
    departments they head. Raises FilterError (422) or AccessDenied (403).
    """
    if filters.department_ids:
        known = db.scalar(
            select(func.count())
            .select_from(Department)
            .where(Department.org_id == access.org_id, Department.id.in_(filters.department_ids))
        )
        if known != len(filters.department_ids):
            raise FilterError("unknown department")
    if filters.location_ids:
        known = db.scalar(
            select(func.count())
            .select_from(Branch)
            .where(Branch.org_id == access.org_id, Branch.id.in_(filters.location_ids))
        )
        if known != len(filters.location_ids):
            raise FilterError("unknown location")

    if access.department_scope is None:
        return filters
    if not access.department_scope:
        raise AccessDenied("you don't head any department, so there is nothing to show")
    outside = set(filters.department_ids) - set(access.department_scope)
    if outside:
        raise AccessDenied("you can only see the departments you head")
    if filters.department_ids:
        return filters
    return AnalyticsFilters(
        date_from=filters.date_from,
        date_to=filters.date_to,
        compare=filters.compare,
        department_ids=access.department_scope,
        location_ids=filters.location_ids,
        employment_types=filters.employment_types,
        statuses=filters.statuses,
        payroll_status=filters.payroll_status,
        country=filters.country,
    )
