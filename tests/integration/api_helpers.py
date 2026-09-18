"""Shared fixtures for API-layer integration tests (tests that drive the
FastAPI app via TestClient rather than calling services directly). Kept
separate from tests/integration/test_auth_flow.py's private helpers since
every API test file needs the same org+account+employee scaffolding.
"""

import uuid
from datetime import date
from typing import Any

from fastapi.testclient import TestClient
from pyotp import TOTP
from sqlalchemy import select

from app.core.db import get_session_factory, tenant_session
from app.core.security import TokenClaims, create_access_token, decode_token, hash_password
from app.domain.payroll.frequency import PayFrequency
from app.main import app
from app.models import Account, Department, Employee, EmploymentType, Membership, Organisation, Role

client = TestClient(app)

DEFAULT_PASSWORD = "s3cret-pass"


def create_org() -> uuid.UUID:
    org_id = uuid.uuid4()
    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        db.add(Organisation(id=org_id, name="Test Co"))
    return org_id


def create_account_with_membership(
    org_id: uuid.UUID, role: Role, *, email: str | None = None, password: str = DEFAULT_PASSWORD
) -> uuid.UUID:
    account_id = uuid.uuid4()
    email = email or f"{role.value}-{account_id}@example.com"
    session = get_session_factory()()
    try:
        session.add(Account(id=account_id, email=email, password_hash=hash_password(password)))
        session.add(Membership(account_id=account_id, org_id=org_id, role=role))
        session.commit()
    finally:
        session.close()
    return account_id


def get_membership_id(org_id: uuid.UUID, account_id: uuid.UUID) -> uuid.UUID:
    session = get_session_factory()()
    try:
        membership_id = session.scalar(
            select(Membership.id).where(
                Membership.org_id == org_id, Membership.account_id == account_id
            )
        )
    finally:
        session.close()
    assert membership_id is not None
    return membership_id


def login(email: str, password: str = DEFAULT_PASSWORD) -> dict[str, str]:
    """Plain login — works for any role, since MFA is opt-in (never a login
    precondition). Use login_with_mfa instead when a test specifically
    wants to exercise the TOTP-enrolled login path."""
    response = client.post("/api/v1/auth/login", json={"identifier": email, "password": password})
    assert response.status_code == 200, response.text
    tokens: dict[str, str] = response.json()
    return tokens


def login_with_mfa(
    account_id: uuid.UUID, email: str, role: Role, *, password: str = DEFAULT_PASSWORD
) -> dict[str, str]:
    """Bootstraps TOTP enrollment (via a directly-minted token, same as
    tests/integration/test_auth_flow.py) then logs in for real — for
    exercising the opt-in TOTP-enrolled login path for any role."""
    session = get_session_factory()()
    try:
        org_id = session.scalar(
            select(Membership.org_id).where(Membership.account_id == account_id)
        )
    finally:
        session.close()
    assert org_id is not None

    bootstrap_token = create_access_token(account_id, org_id, role.value)
    setup = client.post("/api/v1/auth/totp/setup", headers=auth_headers(bootstrap_token))
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    # Computed once and reused below: two separate TOTP.now() calls can
    # straddle a 30s window boundary and produce different codes, which
    # verify_totp (no replay protection) would then reject as invalid.
    code = TOTP(secret).now()
    verify = client.post(
        "/api/v1/auth/totp/verify",
        json={"code": code},
        headers=auth_headers(bootstrap_token),
    )
    assert verify.status_code == 204, verify.text

    # Enrollment (setup+verify) is already committed at this point, so a
    # retry here only needs a fresh code, never re-enrollment. One retry
    # covers the same 30s-window race the comment above documents: if the
    # window rolled over between minting `code` and this call reaching the
    # server, a freshly generated code is guaranteed to land inside the
    # current window.
    response = client.post(
        "/api/v1/auth/login",
        json={"identifier": email, "password": password, "totp_code": code},
    )
    if response.status_code != 200:
        response = client.post(
            "/api/v1/auth/login",
            json={"identifier": email, "password": password, "totp_code": TOTP(secret).now()},
        )
    assert response.status_code == 200, response.text
    tokens: dict[str, str] = response.json()
    return tokens


def claims_from_tokens(tokens: dict[str, str]) -> TokenClaims:
    return decode_token(tokens["access_token"], expected_type="access")


def auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def create_employee(
    org_id: uuid.UUID,
    *,
    account_id: uuid.UUID | None = None,
    employee_number: str = "EMP-001",
    manager_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    basic_minor: int = 300_000_00,
    housing_minor: int = 150_000_00,
    transport_minor: int = 50_000_00,
    tin: str = "12345678-0001",
    email: str | None = None,
) -> uuid.UUID:
    employee_id = uuid.uuid4()
    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        db.add(
            Employee(
                id=employee_id,
                org_id=org_id,
                account_id=account_id,
                employee_number=employee_number,
                full_name="Test Employee",
                state_of_residence="Lagos",
                employment_type=EmploymentType.PERMANENT,
                date_of_joining=date(2025, 1, 1),
                tin=tin,
                email=email,
                manager_id=manager_id,
                department_id=department_id,
                basic_minor=basic_minor,
                housing_minor=housing_minor,
                transport_minor=transport_minor,
                pay_frequency=PayFrequency.MONTHLY,
            )
        )
    return employee_id


def create_and_lock_pay_run(
    headers: dict[str, str],
    *,
    period_start: str = "2026-01-01",
    period_end: str = "2026-01-31",
    frequency: str = "monthly",
    employee_ids: list[uuid.UUID] | None = None,
) -> dict[str, Any]:
    """Drives a pay run through its full draft -> validated -> locked
    lifecycle the way a real caller would — most API tests only care that a
    run ends up locked (payslips/ledger/liabilities persisted), not about
    exercising the lifecycle itself, so this collapses the three calls into
    one.
    """
    body: dict[str, Any] = {
        "period_start": period_start,
        "period_end": period_end,
        "frequency": frequency,
    }
    if employee_ids is not None:
        body["employee_ids"] = [str(employee_id) for employee_id in employee_ids]

    created = client.post("/api/v1/pay-runs", headers=headers, json=body)
    assert created.status_code == 201, created.text
    pay_run_id = created.json()["id"]

    validated = client.post(f"/api/v1/pay-runs/{pay_run_id}/validate", headers=headers, json={})
    assert validated.status_code == 200, validated.text

    locked = client.post(f"/api/v1/pay-runs/{pay_run_id}/lock", headers=headers)
    assert locked.status_code == 200, locked.text
    result: dict[str, Any] = locked.json()
    return result


def create_department(
    org_id: uuid.UUID, *, manager_id: uuid.UUID | None = None, name: str = "Test Dept"
) -> uuid.UUID:
    department_id = uuid.uuid4()
    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        db.add(Department(id=department_id, org_id=org_id, name=name, manager_id=manager_id))
    return department_id
