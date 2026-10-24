import enum


class Permission(str, enum.Enum):
    EMPLOYEES_VIEW = "employees.view"
    EMPLOYEES_MANAGE = "employees.manage"
    PAYROLL_RUN = "payroll.run"
    PAYROLL_APPROVE = "payroll.approve"
    ACCOUNTING_MANAGE = "accounting.manage"
    RECRUITMENT_MANAGE = "recruitment.manage"
    PERFORMANCE_MANAGE = "performance.manage"
    REPORTS_VIEW = "reports.view"
    SETTINGS_MANAGE = "settings.manage"
    # Inventory (docs/architecture/inventory-integration.md §7.1). The first
    # module enforced through require_permission rather than require_roles.
    INVENTORY_VIEW = "inventory.view"
    INVENTORY_MANAGE = "inventory.manage"  # items, units, warehouses, settings
    INVENTORY_ADJUST = "inventory.adjust"  # create, post and reverse adjustments
    INVENTORY_VALUATION = "inventory.valuation"  # see stock values and costs
    # Phase 2 (§7.1, D7).
    INVENTORY_PURCHASE = "inventory.purchase"  # create and submit purchase orders
    INVENTORY_APPROVE = "inventory.approve"  # approve POs, adjustments, issues, transfers
    INVENTORY_RECEIVE = "inventory.receive"  # goods receipts
    INVENTORY_ISSUE = "inventory.issue"  # create and post stock issues
    INVENTORY_TRANSFER = "inventory.transfer"  # create, dispatch and receive transfers
    # Ask for stock for a department you head; never posts anything.
    INVENTORY_REQUEST = "inventory.request"
    # Analytics & Insights (docs/analytics-security.md). analytics.view opens
    # the section; each dashboard also needs its own permission, and exports
    # need analytics.reports.export on top of the dashboard's.
    ANALYTICS_VIEW = "analytics.view"
    ANALYTICS_WORKFORCE_VIEW = "analytics.workforce.view"
    ANALYTICS_PAYROLL_VIEW = "analytics.payroll.view"
    ANALYTICS_ATTENDANCE_VIEW = "analytics.attendance.view"
    ANALYTICS_LEAVE_VIEW = "analytics.leave.view"
    ANALYTICS_RECRUITMENT_VIEW = "analytics.recruitment.view"
    ANALYTICS_PERFORMANCE_VIEW = "analytics.performance.view"
    ANALYTICS_COMPLIANCE_VIEW = "analytics.compliance.view"
    ANALYTICS_FINANCIAL_VIEW = "analytics.financial.view"
    ANALYTICS_REPORTS_EXPORT = "analytics.reports.export"


# Keyed by Role.value (a plain str) rather than the Role enum itself — this
# module stays decoupled from app.models.membership entirely (Role is
# pervasively referenced from there already, across JWT claims and
# require_roles(), and app.models.membership_permission_override imports
# Permission from this very module, so importing Role back here would be
# circular). Every caller passes membership.role.value / claims.role,
# already a plain string throughout this codebase's auth layer.
_PAYROLL_MANAGER_PERMISSIONS = frozenset(
    {
        Permission.EMPLOYEES_VIEW,
        Permission.EMPLOYEES_MANAGE,
        Permission.PAYROLL_RUN,
        Permission.PAYROLL_APPROVE,
        Permission.ACCOUNTING_MANAGE,
        Permission.REPORTS_VIEW,
        Permission.INVENTORY_VIEW,
        Permission.INVENTORY_MANAGE,
        Permission.INVENTORY_ADJUST,
        Permission.INVENTORY_VALUATION,
        Permission.INVENTORY_PURCHASE,
        Permission.INVENTORY_APPROVE,
        Permission.INVENTORY_RECEIVE,
        Permission.INVENTORY_ISSUE,
        Permission.INVENTORY_TRANSFER,
        Permission.INVENTORY_REQUEST,
        Permission.ANALYTICS_VIEW,
        Permission.ANALYTICS_WORKFORCE_VIEW,
        Permission.ANALYTICS_PAYROLL_VIEW,
        Permission.ANALYTICS_ATTENDANCE_VIEW,
        Permission.ANALYTICS_LEAVE_VIEW,
        Permission.ANALYTICS_RECRUITMENT_VIEW,
        Permission.ANALYTICS_PERFORMANCE_VIEW,
        Permission.ANALYTICS_COMPLIANCE_VIEW,
        Permission.ANALYTICS_FINANCIAL_VIEW,
        Permission.ANALYTICS_REPORTS_EXPORT,
    }
)

# Each analytics.* default mirrors what the role can already read through
# the source module's own API (docs/analytics-security.md §2), so analytics
# never shows a role an aggregate of data it couldn't otherwise see.
DEFAULT_ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "admin": frozenset(Permission),
    "payroll_manager": _PAYROLL_MANAGER_PERMISSIONS,
    # Full Payroll Manager parity per product spec — kept as its own key
    # (not an alias) so an org can override accountant independently via
    # MembershipPermissionOverride without touching payroll_manager.
    "accountant": _PAYROLL_MANAGER_PERMISSIONS,
    # Workforce, attendance and leave only: an HR manager's view of
    # employees is always compensation-masked, and the recruitment,
    # performance, payroll and accounting APIs don't admit the role.
    "hr_manager": frozenset(
        {
            Permission.EMPLOYEES_VIEW,
            Permission.EMPLOYEES_MANAGE,
            Permission.REPORTS_VIEW,
            Permission.ANALYTICS_VIEW,
            Permission.ANALYTICS_WORKFORCE_VIEW,
            Permission.ANALYTICS_ATTENDANCE_VIEW,
            Permission.ANALYTICS_LEAVE_VIEW,
            Permission.ANALYTICS_REPORTS_EXPORT,
        }
    ),
    "manager": frozenset({Permission.EMPLOYEES_VIEW, Permission.PERFORMANCE_MANAGE}),
    # Scoped to one department at the query layer (departments.manager_id),
    # not by a narrower permission set here. inventory.request likewise only
    # reaches the departments they head.
    # Analytics for a department manager is likewise limited to the
    # departments they head (app/services/analytics/access.py): workforce
    # and leave, the two modules the role can read today, and no export.
    "department_manager": frozenset(
        {
            Permission.EMPLOYEES_VIEW,
            Permission.INVENTORY_REQUEST,
            Permission.ANALYTICS_VIEW,
            Permission.ANALYTICS_WORKFORCE_VIEW,
            Permission.ANALYTICS_LEAVE_VIEW,
        }
    ),
    # Strictly read-only: only the pure read grants (REPORTS_VIEW, and
    # INVENTORY_VIEW / INVENTORY_VALUATION for stock and its value). Auditor
    # access elsewhere (payroll, compliance, audit log) is wired via
    # require_roles() on GET endpoints specifically, never through a
    # *_MANAGE permission.
    # Analytics is read-only, so the auditor gets every dashboard whose
    # source it already reads; not financial, since the ledger and
    # statements APIs don't admit the role.
    "auditor": frozenset(
        {
            Permission.REPORTS_VIEW,
            Permission.INVENTORY_VIEW,
            Permission.INVENTORY_VALUATION,
            Permission.ANALYTICS_VIEW,
            Permission.ANALYTICS_WORKFORCE_VIEW,
            Permission.ANALYTICS_PAYROLL_VIEW,
            Permission.ANALYTICS_ATTENDANCE_VIEW,
            Permission.ANALYTICS_LEAVE_VIEW,
            Permission.ANALYTICS_RECRUITMENT_VIEW,
            Permission.ANALYTICS_PERFORMANCE_VIEW,
            Permission.ANALYTICS_COMPLIANCE_VIEW,
            Permission.ANALYTICS_REPORTS_EXPORT,
        }
    ),
    "employee": frozenset(),
}


def resolve_permissions(role: str, overrides: dict[Permission, bool]) -> frozenset[Permission]:
    """A role's default permission set, with per-membership overrides
    layered on top — an override can grant a permission the role
    wouldn't normally have, or revoke one it would. This is the
    fine-grained half of RBAC in this codebase: the coarse Role still
    decides a membership's starting point (and every existing
    require_roles() check keeps working unchanged), but an org can adjust
    an individual membership's exact permissions from there without
    inventing a new role for every exception.
    """
    base = set(DEFAULT_ROLE_PERMISSIONS.get(role, frozenset()))
    for permission, granted in overrides.items():
        if granted:
            base.add(permission)
        else:
            base.discard(permission)
    return frozenset(base)
