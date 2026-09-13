from app.domain.permissions import Permission, resolve_permissions


def test_admin_has_every_permission_by_default() -> None:
    permissions = resolve_permissions("admin", {})
    assert permissions == frozenset(Permission)


def test_employee_has_no_permissions_by_default() -> None:
    assert resolve_permissions("employee", {}) == frozenset()


def test_override_can_grant_a_permission_beyond_the_role_default() -> None:
    permissions = resolve_permissions("employee", {Permission.REPORTS_VIEW: True})
    assert Permission.REPORTS_VIEW in permissions


def test_override_can_revoke_a_permission_the_role_would_normally_have() -> None:
    permissions = resolve_permissions("manager", {Permission.EMPLOYEES_VIEW: False})
    assert Permission.EMPLOYEES_VIEW not in permissions
    assert Permission.PERFORMANCE_MANAGE in permissions
