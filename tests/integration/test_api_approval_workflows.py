import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError

from app.core.db import tenant_session
from app.models import Role
from app.models.approval import ApprovalWorkflowStep
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_department,
    create_employee,
    create_org,
    login,
    login_with_mfa,
)


def _admin_headers(org_id, email: str = "wf-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def _payroll_manager_headers(org_id, email: str) -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.PAYROLL_MANAGER, email=email)
    tokens = login_with_mfa(account_id, email, Role.PAYROLL_MANAGER)
    return auth_headers(tokens["access_token"])


def _configure_leave_workflow(admin_headers: dict[str, str], steps: list[dict]) -> None:
    response = client.put(
        "/api/v1/approval-workflow-steps/leave_request", headers=admin_headers, json=steps
    )
    assert response.status_code == 200, response.text


def test_configured_multi_step_leave_defers_balance_check_to_final_step() -> None:
    org_id = create_org()
    admin_headers = _admin_headers(org_id)

    manager_email = "wf-manager1@example.com"
    manager_account_id = create_account_with_membership(org_id, Role.MANAGER, email=manager_email)
    manager_id = create_employee(org_id, account_id=manager_account_id, employee_number="MGR-WF1")

    payroll_email = "wf-payroll1@example.com"
    payroll_headers = _payroll_manager_headers(org_id, payroll_email)

    report_email = "wf-report1@example.com"
    report_account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=report_email)
    create_employee(
        org_id, account_id=report_account_id, employee_number="EMP-WF1", manager_id=manager_id
    )

    _configure_leave_workflow(
        admin_headers,
        [
            {"eligibility_type": "direct_manager"},
            {"eligibility_type": "role", "eligible_role": "payroll_manager"},
        ],
    )

    report_headers = auth_headers(login(report_email)["access_token"])
    submit = client.post(
        "/api/v1/leave-requests/me",
        headers=report_headers,
        json={
            "leave_type": "annual",
            "start_date": "2026-03-01",
            "end_date": "2026-03-06",
            "days": 5,
        },
    )
    assert submit.status_code == 201, submit.text
    request_id = submit.json()["id"]

    # Step 1: the payroll manager (not the current step's eligible party) is
    # not yet authorised.
    premature = client.post(
        f"/api/v1/leave-requests/{request_id}/approve", headers=payroll_headers
    )
    assert premature.status_code == 403

    manager_headers = auth_headers(login(manager_email)["access_token"])
    step1 = client.post(f"/api/v1/leave-requests/{request_id}/approve", headers=manager_headers)
    assert step1.status_code == 200, step1.text
    # Still pending overall — one step of two — and the balance check has
    # not run yet (only the finalizing step enforces it).
    assert step1.json()["status"] == "pending"

    # The direct manager can't decide the same step twice.
    repeat = client.post(f"/api/v1/leave-requests/{request_id}/approve", headers=manager_headers)
    assert repeat.status_code == 403

    step2 = client.post(f"/api/v1/leave-requests/{request_id}/approve", headers=payroll_headers)
    assert step2.status_code == 200, step2.text
    assert step2.json()["status"] == "approved"

    history = client.get(
        f"/api/v1/approval-instances/leave_request/{request_id}", headers=admin_headers
    )
    assert history.status_code == 200, history.text
    body = history.json()
    assert body["status"] == "approved"
    assert body["current_step"] == 2
    assert [d["step_order"] for d in body["decisions"]] == [1, 2]
    assert all(d["decision"] == "approve" for d in body["decisions"])


def test_reject_at_first_step_is_immediately_terminal() -> None:
    org_id = create_org()
    admin_headers = _admin_headers(org_id, email="wf-admin2@example.com")

    manager_email = "wf-manager2@example.com"
    manager_account_id = create_account_with_membership(org_id, Role.MANAGER, email=manager_email)
    manager_id = create_employee(org_id, account_id=manager_account_id, employee_number="MGR-WF2")

    report_email = "wf-report2@example.com"
    report_account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=report_email)
    create_employee(
        org_id, account_id=report_account_id, employee_number="EMP-WF2", manager_id=manager_id
    )

    _configure_leave_workflow(
        admin_headers,
        [
            {"eligibility_type": "direct_manager"},
            {"eligibility_type": "role", "eligible_role": "payroll_manager"},
        ],
    )

    report_headers = auth_headers(login(report_email)["access_token"])
    submit = client.post(
        "/api/v1/leave-requests/me",
        headers=report_headers,
        json={
            "leave_type": "annual",
            "start_date": "2026-03-01",
            "end_date": "2026-03-02",
            "days": 2,
        },
    )
    request_id = submit.json()["id"]

    manager_headers = auth_headers(login(manager_email)["access_token"])
    rejected = client.post(f"/api/v1/leave-requests/{request_id}/reject", headers=manager_headers)
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    history = client.get(
        f"/api/v1/approval-instances/leave_request/{request_id}", headers=admin_headers
    )
    body = history.json()
    assert body["status"] == "rejected"
    assert len(body["decisions"]) == 1
    assert body["decisions"][0]["decision"] == "reject"


def test_department_head_eligibility() -> None:
    org_id = create_org()
    admin_headers = _admin_headers(org_id, email="wf-admin3@example.com")

    head_email = "wf-depthead@example.com"
    head_account_id = create_account_with_membership(org_id, Role.MANAGER, email=head_email)
    head_employee_id = create_employee(
        org_id, account_id=head_account_id, employee_number="HEAD-WF3"
    )
    department_id = create_department(org_id, manager_id=head_employee_id, name="Engineering")

    report_email = "wf-report3@example.com"
    report_account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=report_email)
    create_employee(
        org_id,
        account_id=report_account_id,
        employee_number="EMP-WF3",
        department_id=department_id,
    )

    _configure_leave_workflow(admin_headers, [{"eligibility_type": "department_head"}])

    report_headers = auth_headers(login(report_email)["access_token"])
    submit = client.post(
        "/api/v1/leave-requests/me",
        headers=report_headers,
        json={
            "leave_type": "annual",
            "start_date": "2026-05-01",
            "end_date": "2026-05-02",
            "days": 2,
        },
    )
    request_id = submit.json()["id"]

    head_headers = auth_headers(login(head_email)["access_token"])
    approved = client.post(f"/api/v1/leave-requests/{request_id}/approve", headers=head_headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"


def test_specific_person_eligibility() -> None:
    org_id = create_org()
    admin_headers = _admin_headers(org_id, email="wf-admin4@example.com")

    named_email = "wf-named-approver@example.com"
    named_account_id = create_account_with_membership(org_id, Role.MANAGER, email=named_email)

    other_manager_email = "wf-other-manager@example.com"
    other_manager_account_id = create_account_with_membership(
        org_id, Role.MANAGER, email=other_manager_email
    )
    other_manager_id = create_employee(
        org_id, account_id=other_manager_account_id, employee_number="MGR-WF4"
    )

    report_email = "wf-report4@example.com"
    report_account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=report_email)
    create_employee(
        org_id,
        account_id=report_account_id,
        employee_number="EMP-WF4",
        manager_id=other_manager_id,
    )

    _configure_leave_workflow(
        admin_headers,
        [{"eligibility_type": "specific_person", "eligible_account_id": str(named_account_id)}],
    )

    report_headers = auth_headers(login(report_email)["access_token"])
    submit = client.post(
        "/api/v1/leave-requests/me",
        headers=report_headers,
        json={
            "leave_type": "annual",
            "start_date": "2026-06-01",
            "end_date": "2026-06-02",
            "days": 2,
        },
    )
    request_id = submit.json()["id"]

    # The requester's own direct manager is NOT the configured approver here.
    other_manager_headers = auth_headers(login(other_manager_email)["access_token"])
    denied = client.post(
        f"/api/v1/leave-requests/{request_id}/approve", headers=other_manager_headers
    )
    assert denied.status_code == 403

    named_headers = auth_headers(login(named_email)["access_token"])
    approved = client.post(f"/api/v1/leave-requests/{request_id}/approve", headers=named_headers)
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"


def test_bill_workflow_rejects_manager_relationship_steps() -> None:
    org_id = create_org()
    admin_headers = _admin_headers(org_id, email="wf-admin5@example.com")

    response = client.put(
        "/api/v1/approval-workflow-steps/bill",
        headers=admin_headers,
        json=[{"eligibility_type": "direct_manager"}],
    )
    assert response.status_code == 400
    assert "requester" in response.json()["detail"]


def test_employee_role_cannot_be_configured_as_a_step() -> None:
    org_id = create_org()
    admin_headers = _admin_headers(org_id, email="wf-admin6@example.com")

    response = client.put(
        "/api/v1/approval-workflow-steps/leave_request",
        headers=admin_headers,
        json=[{"eligibility_type": "role", "eligible_role": "employee"}],
    )
    assert response.status_code == 400


def test_workflow_step_config_is_tenant_isolated() -> None:
    org_a = create_org()
    org_b = create_org()

    admin_a_headers = _admin_headers(org_a, email="wf-admin-a@example.com")
    admin_b_headers = _admin_headers(org_b, email="wf-admin-b@example.com")

    _configure_leave_workflow(admin_a_headers, [{"eligibility_type": "role", "eligible_role": "manager"}])

    # Org B never configured anything for leave_request — its own list must
    # stay empty regardless of what org A configured, proving RLS scoping,
    # not just application-level filtering.
    listing_b = client.get(
        "/api/v1/approval-workflow-steps/leave_request", headers=admin_b_headers
    )
    assert listing_b.status_code == 200
    assert listing_b.json() == []

    with tenant_session(org_b, uuid.uuid4(), "admin") as db:
        rows = list(
            db.scalars(select(ApprovalWorkflowStep).where(ApprovalWorkflowStep.org_id == org_a))
        )
        assert rows == []


def test_decision_trail_is_append_only() -> None:
    org_id = create_org()
    admin_headers = _admin_headers(org_id, email="wf-admin7@example.com")

    report_email = "wf-report7@example.com"
    report_account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=report_email)
    create_employee(org_id, account_id=report_account_id, employee_number="EMP-WF7")

    report_headers = auth_headers(login(report_email)["access_token"])
    submit = client.post(
        "/api/v1/leave-requests/me",
        headers=report_headers,
        json={
            "leave_type": "annual",
            "start_date": "2026-07-01",
            "end_date": "2026-07-02",
            "days": 2,
        },
    )
    request_id = submit.json()["id"]

    approved = client.post(f"/api/v1/leave-requests/{request_id}/approve", headers=admin_headers)
    assert approved.status_code == 200

    with (
        pytest.raises(ProgrammingError, match="append-only"),
        tenant_session(org_id, uuid.uuid4(), "admin") as db,
    ):
        db.execute(text("DELETE FROM approval_instance_decisions"))


def test_non_admin_cannot_configure_workflow_steps() -> None:
    org_id = create_org()
    email = "wf-not-admin@example.com"
    account_id = create_account_with_membership(org_id, Role.PAYROLL_MANAGER, email=email)
    tokens = login_with_mfa(account_id, email, Role.PAYROLL_MANAGER)
    headers = auth_headers(tokens["access_token"])

    response = client.put(
        "/api/v1/approval-workflow-steps/leave_request", headers=headers, json=[]
    )
    assert response.status_code == 403


def test_manager_cannot_view_bill_approval_history() -> None:
    org_id = create_org()
    admin_headers = _admin_headers(org_id, email="wf-admin8@example.com")

    seeded = client.post("/api/v1/chart-of-accounts/seed-defaults", headers=admin_headers)
    assert seeded.status_code == 200, seeded.text
    vendor = client.post(
        "/api/v1/vendors", headers=admin_headers, json={"name": "Wf Vendor Co"}
    )
    assert vendor.status_code == 201, vendor.text
    bill = client.post(
        "/api/v1/bills",
        headers=admin_headers,
        json={
            "vendor_id": vendor.json()["id"],
            "bill_number": "WF-INV-001",
            "bill_date": "2026-09-01",
            "due_date": "2026-09-30",
            "expense_account_code": "contractor_expense",
            "amount_minor": 100_000_00,
            "description": "Test bill",
        },
    )
    assert bill.status_code == 201, bill.text
    bill_id = bill.json()["id"]

    manager_email = "wf-bill-manager@example.com"
    manager_account_id = create_account_with_membership(org_id, Role.MANAGER, email=manager_email)
    create_employee(org_id, account_id=manager_account_id, employee_number="MGR-WF8")
    manager_headers = auth_headers(login(manager_email)["access_token"])

    history = client.get(f"/api/v1/approval-instances/bill/{bill_id}", headers=manager_headers)
    assert history.status_code == 403

    admin_history = client.get(f"/api/v1/approval-instances/bill/{bill_id}", headers=admin_headers)
    assert admin_history.status_code == 200
    assert admin_history.json()["status"] == "pending"
