"""Shared fixtures for API-layer integration tests (tests that drive the
FastAPI app via TestClient rather than calling services directly). Kept
separate from tests/integration/test_auth_flow.py's private helpers since
every API test file needs the same org+account+employee scaffolding.
"""

import uuid
from datetime import date

from fastapi.testclient import TestClient
from pyotp import TOTP
from sqlalchemy import select

from app.core.db import get_session_factory, tenant_session
from app.core.security import TokenClaims, create_access_token, decode_token, hash_password
from app.domain.payroll.frequency import PayFrequency
from app.main import app
from app.models import Account, Employee, EmploymentType, Membership, Organisation, Role
from app.models.membership import MFA_REQUIRED_ROLES

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


def login(email: str, password: str = DEFAULT_PASSWORD) -> dict[str, str]:
    """For roles outside MFA_REQUIRED_ROLES (membership.py) — ADMIN and
    PAYROLL_MANAGER need login_with_mfa instead, since a bare login attempt
    for those roles is refused until TOTP is enrolled."""
    response = client.post("/api/v1/auth/login", json={"identifier": email, "password": password})
    assert response.status_code == 200, response.text
    tokens: dict[str, str] = response.json()
    return tokens


def login_with_mfa(
    account_id: uuid.UUID, email: str, role: Role, *, password: str = DEFAULT_PASSWORD
) -> dict[str, str]:
    """Bootstraps TOTP enrollment (via a directly-minted token, same as
    tests/integration/test_auth_flow.py) then logs in for real — required
    for ADMIN/PAYROLL_MANAGER, MFA_REQUIRED_ROLES in membership.py."""
    assert role in MFA_REQUIRED_ROLES
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

    response = client.post(
        "/api/v1/auth/login",
        json={"identifier": email, "password": password, "totp_code": code},
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
                basic_minor=basic_minor,
                housing_minor=housing_minor,
                transport_minor=transport_minor,
                pay_frequency=PayFrequency.MONTHLY,
            )
        )
    return employee_id
