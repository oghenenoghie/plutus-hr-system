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
    }
)

DEFAULT_ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "admin": frozenset(Permission),
    "payroll_manager": _PAYROLL_MANAGER_PERMISSIONS,
    # Full Payroll Manager parity per product spec — kept as its own key
    # (not an alias) so an org can override accountant independently via
    # MembershipPermissionOverride without touching payroll_manager.
    "accountant": _PAYROLL_MANAGER_PERMISSIONS,
    "hr_manager": frozenset(
        {
            Permission.EMPLOYEES_VIEW,
            Permission.EMPLOYEES_MANAGE,
            Permission.REPORTS_VIEW,
        }
    ),
    "manager": frozenset({Permission.EMPLOYEES_VIEW, Permission.PERFORMANCE_MANAGE}),
    # Scoped to one department at the query layer (departments.manager_id),
    # not by a narrower permission set here.
    "department_manager": frozenset({Permission.EMPLOYEES_VIEW}),
    # Strictly read-only: only the pure read grants (REPORTS_VIEW, and
    # INVENTORY_VIEW / INVENTORY_VALUATION for stock and its value). Auditor
    # access elsewhere (payroll, compliance, audit log) is wired via
    # require_roles() on GET endpoints specifically, never through a
    # *_MANAGE permission.
    "auditor": frozenset(
        {Permission.REPORTS_VIEW, Permission.INVENTORY_VIEW, Permission.INVENTORY_VALUATION}
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
