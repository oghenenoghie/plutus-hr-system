import uuid

from fastapi.testclient import TestClient
from pyotp import TOTP
from sqlalchemy import select

from app.core.db import get_session_factory, tenant_session
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models import Account, Employee, EmployeeLoginCode, Membership, Organisation, Role
from app.models.employee import EmploymentType

client = TestClient(app)


def _create_org_with_member(email: str, password: str, role: Role) -> uuid.UUID:
    org_id = uuid.uuid4()
    account_id = uuid.uuid4()
    with tenant_session(org_id, account_id, role.value) as db:
        db.add(Organisation(id=org_id, name="Test Co"))

    session = get_session_factory()()
    try:
        session.add(Account(id=account_id, email=email, password_hash=hash_password(password)))
        session.add(Membership(account_id=account_id, org_id=org_id, role=role))
        session.commit()
    finally:
        session.close()
    return org_id


def test_login_and_me_for_single_org_employee() -> None:
    org_id = _create_org_with_member("employee@example.com", "s3cret-pass", Role.EMPLOYEE)

    response = client.post(
        "/api/v1/auth/login",
        json={"identifier": "employee@example.com", "password": "s3cret-pass"},
    )
    assert response.status_code == 200
    tokens = response.json()

    me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.status_code == 200
    body = me.json()
    assert body["org_id"] == str(org_id)
    assert body["role"] == "employee"
    assert body["org_name"] == "Test Co"


def test_login_rejects_wrong_password() -> None:
    _create_org_with_member("wrongpass@example.com", "s3cret-pass", Role.EMPLOYEE)

    response = client.post(
        "/api/v1/auth/login", json={"identifier": "wrongpass@example.com", "password": "nope"}
    )
    assert response.status_code == 401


def test_admin_login_requires_totp() -> None:
    _create_org_with_member("admin@example.com", "s3cret-pass", Role.ADMIN)

    response = client.post(
        "/api/v1/auth/login", json={"identifier": "admin@example.com", "password": "s3cret-pass"}
    )
    assert response.status_code == 401
    assert "TOTP" in response.json()["detail"]


def test_admin_can_enroll_totp_then_login() -> None:
    # Logging in as an admin before TOTP is enabled is refused (see the test
    # above), so there's no login-issued token to enroll with yet. A real
    # bootstrap would use a one-time invite link; here we mint the token
    # directly to drive the enrollment endpoints under test.
    org_id = _create_org_with_member("admin2@example.com", "s3cret-pass", Role.ADMIN)

    session = get_session_factory()()
    try:
        account_id = session.scalar(select(Account.id).where(Account.email == "admin2@example.com"))
        assert account_id is not None
    finally:
        session.close()

    bootstrap_token = create_access_token(account_id, org_id, Role.ADMIN.value)
    setup = client.post(
        "/api/v1/auth/totp/setup", headers={"Authorization": f"Bearer {bootstrap_token}"}
    )
    assert setup.status_code == 200
    secret = setup.json()["secret"]

    verify = client.post(
        "/api/v1/auth/totp/verify",
        json={"code": TOTP(secret).now()},
        headers={"Authorization": f"Bearer {bootstrap_token}"},
    )
    assert verify.status_code == 204

    response = client.post(
        "/api/v1/auth/login",
        json={
            "identifier": "admin2@example.com",
            "password": "s3cret-pass",
            "totp_code": TOTP(secret).now(),
        },
    )
    assert response.status_code == 200


def test_login_by_employee_code() -> None:
    org_id = _create_org_with_member("coded@example.com", "s3cret-pass", Role.EMPLOYEE)

    session = get_session_factory()()
    try:
        account_id = session.scalar(select(Account.id).where(Account.email == "coded@example.com"))
        assert account_id is not None
    finally:
        session.close()

    employee_id = uuid.uuid4()
    with tenant_session(org_id, account_id, Role.EMPLOYEE.value) as db:
        db.add(
            Employee(
                id=employee_id,
                org_id=org_id,
                account_id=account_id,
                employee_number="EMP-1",
                login_code="ABCD2345",
                full_name="Coded Employee",
                state_of_residence="Lagos",
                employment_type=EmploymentType.PERMANENT,
                date_of_joining="2026-01-01",
                basic_minor=0,
                housing_minor=0,
                transport_minor=0,
            )
        )

    session = get_session_factory()()
    try:
        session.add(
            EmployeeLoginCode(login_code="ABCD2345", account_id=account_id, employee_id=employee_id)
        )
        session.commit()
    finally:
        session.close()

    response = client.post(
        "/api/v1/auth/login", json={"identifier": "ABCD2345", "password": "s3cret-pass"}
    )
    assert response.status_code == 200
    tokens = response.json()

    me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["org_id"] == str(org_id)


def test_login_rejects_unknown_code() -> None:
    response = client.post(
        "/api/v1/auth/login", json={"identifier": "ZZZZ9999", "password": "whatever"}
    )
    assert response.status_code == 401
