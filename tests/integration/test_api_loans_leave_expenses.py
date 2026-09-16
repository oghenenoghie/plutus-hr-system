from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_employee,
    create_org,
    login,
    login_with_mfa,
)


def _admin_headers(org_id, email: str = "hr-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.PAYROLL_MANAGER, email=email)
    tokens = login_with_mfa(account_id, email, Role.PAYROLL_MANAGER)
    return auth_headers(tokens["access_token"])


def test_employee_requests_loan_and_admin_can_see_and_cancel_it() -> None:
    org_id = create_org()
    email = "borrower@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    create_employee(org_id, account_id=account_id, employee_number="EMP-700")
    tokens = login(email)
    headers = auth_headers(tokens["access_token"])

    response = client.post(
        "/api/v1/loans/me",
        headers=headers,
        json={"principal_minor": 60000, "num_installments": 3, "start_date": "2026-01-01"},
    )
    assert response.status_code == 201, response.text
    loan = response.json()
    assert loan["status"] == "active"
    assert loan["outstanding_minor"] == 60000
    # 60000 / 3 = 20000 exactly, so the base installment is the full amount.
    assert loan["installment_minor"] == 20000

    admin_headers = _admin_headers(org_id)
    listing = client.get("/api/v1/loans", headers=admin_headers)
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    cancel = client.post(f"/api/v1/loans/{loan['id']}/cancel", headers=admin_headers)
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"


def test_employee_cannot_request_a_second_active_loan() -> None:
    org_id = create_org()
    email = "double-borrower@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    create_employee(org_id, account_id=account_id)
    headers = auth_headers(login(email)["access_token"])

    first = client.post(
        "/api/v1/loans/me",
        headers=headers,
        json={"principal_minor": 10000, "num_installments": 2, "start_date": "2026-01-01"},
    )
    assert first.status_code == 201

    second = client.post(
        "/api/v1/loans/me",
        headers=headers,
        json={"principal_minor": 5000, "num_installments": 1, "start_date": "2026-02-01"},
    )
    assert second.status_code == 400


def test_leave_request_approval_enforces_balance() -> None:
    org_id = create_org()
    email = "leave-taker@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    create_employee(org_id, account_id=account_id, employee_number="EMP-800")
    headers = auth_headers(login(email)["access_token"])

    # annual_leave_entitlement_days defaults to 20 - ask for more than that.
    over_request = client.post(
        "/api/v1/leave-requests/me",
        headers=headers,
        json={
            "leave_type": "annual",
            "start_date": "2026-03-01",
            "end_date": "2026-03-31",
            "days": 25,
        },
    )
    assert over_request.status_code == 201, over_request.text
    request_id = over_request.json()["id"]

    admin_headers = _admin_headers(org_id, email="leave-admin@example.com")
    approval = client.post(f"/api/v1/leave-requests/{request_id}/approve", headers=admin_headers)
    assert approval.status_code == 400
    assert "exceeds" in approval.json()["detail"]

    valid_request = client.post(
        "/api/v1/leave-requests/me",
        headers=headers,
        json={
            "leave_type": "annual",
            "start_date": "2026-04-01",
            "end_date": "2026-04-05",
            "days": 5,
        },
    )
    assert valid_request.status_code == 201
    valid_approval = client.post(
        f"/api/v1/leave-requests/{valid_request.json()['id']}/approve", headers=admin_headers
    )
    assert valid_approval.status_code == 200
    assert valid_approval.json()["status"] == "approved"

    balance = client.get("/api/v1/leave-requests/me/balance", headers=headers)
    assert balance.status_code == 200
    assert balance.json() == {"entitlement_days": 20, "taken_days": 5, "remaining_days": 15}


def test_manager_can_approve_direct_reports_leave_but_not_others() -> None:
    org_id = create_org()
    manager_email = "team-lead@example.com"
    manager_account_id = create_account_with_membership(org_id, Role.MANAGER, email=manager_email)
    manager_id = create_employee(org_id, account_id=manager_account_id, employee_number="MGR-010")

    report_email = "report@example.com"
    report_account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=report_email)
    create_employee(
        org_id, account_id=report_account_id, employee_number="EMP-900", manager_id=manager_id
    )

    outsider_email = "outsider@example.com"
    outsider_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=outsider_email
    )
    create_employee(org_id, account_id=outsider_account_id, employee_number="EMP-901")

    report_headers = auth_headers(login(report_email)["access_token"])
    outsider_headers = auth_headers(login(outsider_email)["access_token"])
    manager_headers = auth_headers(login(manager_email)["access_token"])

    report_request = client.post(
        "/api/v1/leave-requests/me",
        headers=report_headers,
        json={
            "leave_type": "annual",
            "start_date": "2026-05-01",
            "end_date": "2026-05-02",
            "days": 2,
        },
    ).json()
    outsider_request = client.post(
        "/api/v1/leave-requests/me",
        headers=outsider_headers,
        json={
            "leave_type": "annual",
            "start_date": "2026-05-01",
            "end_date": "2026-05-02",
            "days": 2,
        },
    ).json()

    approve_report = client.post(
        f"/api/v1/leave-requests/{report_request['id']}/approve", headers=manager_headers
    )
    assert approve_report.status_code == 200

    approve_outsider = client.post(
        f"/api/v1/leave-requests/{outsider_request['id']}/approve", headers=manager_headers
    )
    assert approve_outsider.status_code == 403


def test_department_manager_can_list_direct_reports_leave_but_not_others() -> None:
    org_id = create_org()
    dept_manager_email = "dept-lead@example.com"
    dept_manager_account_id = create_account_with_membership(
        org_id, Role.DEPARTMENT_MANAGER, email=dept_manager_email
    )
    dept_manager_id = create_employee(
        org_id, account_id=dept_manager_account_id, employee_number="DMGR-010"
    )

    report_email = "dept-report@example.com"
    report_account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=report_email)
    report_id = create_employee(
        org_id, account_id=report_account_id, employee_number="EMP-910", manager_id=dept_manager_id
    )

    outsider_email = "dept-outsider@example.com"
    outsider_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=outsider_email
    )
    create_employee(org_id, account_id=outsider_account_id, employee_number="EMP-911")

    report_headers = auth_headers(login(report_email)["access_token"])
    outsider_headers = auth_headers(login(outsider_email)["access_token"])
    dept_manager_headers = auth_headers(login(dept_manager_email)["access_token"])

    client.post(
        "/api/v1/leave-requests/me",
        headers=report_headers,
        json={
            "leave_type": "annual",
            "start_date": "2026-06-01",
            "end_date": "2026-06-02",
            "days": 2,
        },
    )
    client.post(
        "/api/v1/leave-requests/me",
        headers=outsider_headers,
        json={
            "leave_type": "annual",
            "start_date": "2026-06-01",
            "end_date": "2026-06-02",
            "days": 2,
        },
    )

    listing = client.get("/api/v1/leave-requests", headers=dept_manager_headers)
    assert listing.status_code == 200, listing.text
    assert [row["employee_id"] for row in listing.json()] == [str(report_id)]


def test_expense_submit_approve_reimburse_workflow() -> None:
    org_id = create_org()
    email = "spender@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    create_employee(org_id, account_id=account_id)
    headers = auth_headers(login(email)["access_token"])

    submit = client.post(
        "/api/v1/expenses/me",
        headers=headers,
        json={
            "category": "travel",
            "description": "Client visit taxi fare",
            "amount_minor": 5000,
            "expense_date": "2026-01-15",
        },
    )
    assert submit.status_code == 201, submit.text
    expense_id = submit.json()["id"]
    assert submit.json()["status"] == "pending"

    admin_headers = _admin_headers(org_id, email="expense-admin@example.com")

    # Reimbursing before approval is rejected.
    early_reimburse = client.post(f"/api/v1/expenses/{expense_id}/reimburse", headers=admin_headers)
    assert early_reimburse.status_code == 400

    approve = client.post(f"/api/v1/expenses/{expense_id}/approve", headers=admin_headers)
    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"

    reimburse = client.post(f"/api/v1/expenses/{expense_id}/reimburse", headers=admin_headers)
    assert reimburse.status_code == 200
    assert reimburse.json()["status"] == "reimbursed"

    my_expenses = client.get("/api/v1/expenses/me", headers=headers)
    assert my_expenses.status_code == 200
    assert my_expenses.json()[0]["status"] == "reimbursed"


def test_expense_policy_limit_blocks_submission_over_cap() -> None:
    org_id = create_org()
    admin_headers = _admin_headers(org_id, email="expense-policy-admin@example.com")
    email = "policy-spender@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    create_employee(org_id, account_id=account_id, employee_number="EMP-POLICY")
    headers = auth_headers(login(email)["access_token"])

    set_limit = client.put(
        "/api/v1/expenses/policy-limits/travel",
        headers=admin_headers,
        json={"max_amount_minor": 10_000_00},
    )
    assert set_limit.status_code == 200, set_limit.text
    assert set_limit.json()["max_amount_minor"] == 10_000_00

    over_cap = client.post(
        "/api/v1/expenses/me",
        headers=headers,
        json={
            "category": "travel",
            "description": "Flight to Abuja",
            "amount_minor": 15_000_00,
            "expense_date": "2026-01-15",
        },
    )
    assert over_cap.status_code == 400, over_cap.text

    within_cap = client.post(
        "/api/v1/expenses/me",
        headers=headers,
        json={
            "category": "travel",
            "description": "Taxi fare",
            "amount_minor": 5_000_00,
            "expense_date": "2026-01-15",
            "receipt_url": "https://files.example.com/receipts/taxi.jpg",
            "payment_method": "direct_payment",
        },
    )
    assert within_cap.status_code == 201, within_cap.text
    assert within_cap.json()["receipt_url"] == "https://files.example.com/receipts/taxi.jpg"
    assert within_cap.json()["payment_method"] == "direct_payment"

    # A different category is unaffected by the travel-only limit.
    other_category = client.post(
        "/api/v1/expenses/me",
        headers=headers,
        json={
            "category": "supplies",
            "description": "Laptop stand",
            "amount_minor": 20_000_00,
            "expense_date": "2026-01-15",
        },
    )
    assert other_category.status_code == 201, other_category.text

    listing = client.get("/api/v1/expenses/policy-limits", headers=admin_headers)
    assert listing.status_code == 200
    assert [row["category"] for row in listing.json()] == ["travel"]

    delete = client.delete("/api/v1/expenses/policy-limits/travel", headers=admin_headers)
    assert delete.status_code == 204

    now_allowed = client.post(
        "/api/v1/expenses/me",
        headers=headers,
        json={
            "category": "travel",
            "description": "Flight to Abuja",
            "amount_minor": 15_000_00,
            "expense_date": "2026-01-16",
        },
    )
    assert now_allowed.status_code == 201, now_allowed.text
