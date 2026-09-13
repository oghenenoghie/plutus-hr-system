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


def _admin_headers(org_id, email: str = "lifecycle-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.PAYROLL_MANAGER, email=email)
    tokens = login_with_mfa(account_id, email, Role.PAYROLL_MANAGER)
    return auth_headers(tokens["access_token"])


def _create_draft(headers: dict[str, str], **overrides) -> dict:
    body = {
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "frequency": "monthly",
        **overrides,
    }
    if "employee_ids" in body:
        body["employee_ids"] = [str(employee_id) for employee_id in body["employee_ids"]]
    response = client.post("/api/v1/pay-runs", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_full_lifecycle_draft_validate_lock_mark_paid() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id)
    create_employee(org_id, employee_number="EMP-LC-1")

    draft = _create_draft(headers)
    assert draft["status"] == "draft"
    assert draft["locked_at"] is None

    validated = client.post(f"/api/v1/pay-runs/{draft['id']}/validate", headers=headers, json={})
    assert validated.status_code == 200, validated.text
    assert validated.json()["status"] == "validated"

    locked = client.post(f"/api/v1/pay-runs/{draft['id']}/lock", headers=headers)
    assert locked.status_code == 200, locked.text
    body = locked.json()
    assert body["status"] == "locked"
    assert body["locked_at"] is not None
    assert body["employee_count"] == 1

    not_paid_twice = client.post(f"/api/v1/pay-runs/{draft['id']}/lock", headers=headers)
    assert not_paid_twice.status_code == 409

    paid = client.post(f"/api/v1/pay-runs/{draft['id']}/mark-paid", headers=headers)
    assert paid.status_code == 200, paid.text
    assert paid.json()["disbursed_at"] is not None


def test_discard_draft_and_validated_runs_but_not_locked() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="lifecycle-admin2@example.com")
    create_employee(org_id, employee_number="EMP-LC-2")

    draft = _create_draft(headers)
    discarded = client.post(f"/api/v1/pay-runs/{draft['id']}/discard", headers=headers)
    assert discarded.status_code == 204
    assert client.get(f"/api/v1/pay-runs/{draft['id']}", headers=headers).status_code == 404

    draft2 = _create_draft(headers, period_start="2026-02-01", period_end="2026-02-28")
    client.post(f"/api/v1/pay-runs/{draft2['id']}/validate", headers=headers, json={})
    discarded2 = client.post(f"/api/v1/pay-runs/{draft2['id']}/discard", headers=headers)
    assert discarded2.status_code == 204

    draft3 = _create_draft(headers, period_start="2026-03-01", period_end="2026-03-31")
    client.post(f"/api/v1/pay-runs/{draft3['id']}/validate", headers=headers, json={})
    client.post(f"/api/v1/pay-runs/{draft3['id']}/lock", headers=headers)
    not_discardable = client.post(f"/api/v1/pay-runs/{draft3['id']}/discard", headers=headers)
    assert not_discardable.status_code == 409


def test_reverse_locked_run_restores_loan_and_posts_correcting_ledger_entries() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="lifecycle-admin3@example.com")
    employee_email = "loanee@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    employee_id = create_employee(
        org_id, account_id=employee_account_id, employee_number="EMP-LC-3"
    )

    employee_headers = auth_headers(login(employee_email)["access_token"])
    loan = client.post(
        "/api/v1/loans/me",
        headers=employee_headers,
        json={"principal_minor": 50_000_00, "num_installments": 1, "start_date": "2026-01-01"},
    )
    assert loan.status_code == 201, loan.text
    loan_id = loan.json()["id"]

    draft = _create_draft(headers, employee_ids=[employee_id])
    client.post(f"/api/v1/pay-runs/{draft['id']}/validate", headers=headers, json={})
    locked = client.post(f"/api/v1/pay-runs/{draft['id']}/lock", headers=headers)
    assert locked.status_code == 200, locked.text

    paid_off = client.get(f"/api/v1/loans/{loan_id}", headers=headers)
    assert paid_off.json()["status"] == "paid_off"
    assert paid_off.json()["outstanding_minor"] == 0

    entries_before = client.get(
        "/api/v1/general-ledger/entries", headers=headers, params={"pay_run_id": draft["id"]}
    ).json()
    assert entries_before, "expected the locked run's own postings"

    reversed_run = client.post(f"/api/v1/pay-runs/{draft['id']}/reverse", headers=headers)
    assert reversed_run.status_code == 200, reversed_run.text
    assert reversed_run.json()["status"] == "reversed"
    assert reversed_run.json()["reversed_at"] is not None

    restored = client.get(f"/api/v1/loans/{loan_id}", headers=headers)
    assert restored.json()["status"] == "active"
    assert restored.json()["outstanding_minor"] == 50_000_00

    entries_after = client.get(
        "/api/v1/general-ledger/entries", headers=headers, params={"pay_run_id": draft["id"]}
    ).json()
    # The original postings plus one mirrored reversal for each.
    assert len(entries_after) == 2 * len(entries_before)
    assert sum(e["debit_minor"] for e in entries_after) == sum(
        e["credit_minor"] for e in entries_after
    )

    cannot_reverse_twice = client.post(f"/api/v1/pay-runs/{draft['id']}/reverse", headers=headers)
    assert cannot_reverse_twice.status_code == 409


def test_reversed_run_no_longer_counts_toward_cumulative_paye() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="lifecycle-admin4@example.com")
    # High pay so PAYE is nonzero and a second period's cumulative
    # calculation would visibly differ if run1 were still being counted.
    employee_id = create_employee(
        org_id,
        employee_number="EMP-LC-4",
        basic_minor=900_000_00,
        housing_minor=450_000_00,
        transport_minor=150_000_00,
    )

    draft1 = _create_draft(headers, employee_ids=[employee_id])
    client.post(f"/api/v1/pay-runs/{draft1['id']}/validate", headers=headers, json={})
    client.post(f"/api/v1/pay-runs/{draft1['id']}/lock", headers=headers)
    run1_payslip = client.get(f"/api/v1/pay-runs/{draft1['id']}/payslips", headers=headers).json()[
        0
    ]

    reverse_response = client.post(f"/api/v1/pay-runs/{draft1['id']}/reverse", headers=headers)
    assert reverse_response.status_code == 200, reverse_response.text

    draft2 = _create_draft(
        headers, period_start="2026-02-01", period_end="2026-02-28", employee_ids=[employee_id]
    )
    client.post(f"/api/v1/pay-runs/{draft2['id']}/validate", headers=headers, json={})
    client.post(f"/api/v1/pay-runs/{draft2['id']}/lock", headers=headers)
    run2_payslip = client.get(f"/api/v1/pay-runs/{draft2['id']}/payslips", headers=headers).json()[
        0
    ]

    # If run1 still counted, run2's cumulative chargeable income would be
    # roughly double a lone first period's instead of matching it exactly.
    assert (
        run2_payslip["cumulative_chargeable_income_minor"]
        == (run1_payslip["cumulative_chargeable_income_minor"])
    )
    assert run2_payslip["paye_minor"] == run1_payslip["paye_minor"]


def test_gross_swing_blocks_validate_until_acknowledged() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="lifecycle-admin5@example.com")
    employee_id = create_employee(org_id, employee_number="EMP-LC-5")

    draft1 = _create_draft(headers, employee_ids=[employee_id])
    client.post(f"/api/v1/pay-runs/{draft1['id']}/validate", headers=headers, json={})
    client.post(f"/api/v1/pay-runs/{draft1['id']}/lock", headers=headers)

    give_raise = client.patch(
        f"/api/v1/employees/{employee_id}", headers=headers, json={"basic_minor": 900_000_00}
    )
    assert give_raise.status_code == 200, give_raise.text

    draft2 = _create_draft(
        headers, period_start="2026-02-01", period_end="2026-02-28", employee_ids=[employee_id]
    )
    blocked = client.post(f"/api/v1/pay-runs/{draft2['id']}/validate", headers=headers, json={})
    assert blocked.status_code == 409, blocked.text

    flags = client.get(f"/api/v1/pay-runs/{draft2['id']}/variance-flags", headers=headers).json()
    assert len(flags) == 1
    assert flags[0]["flag_type"] == "gross_swing"
    assert flags[0]["acknowledged"] is False

    overridden = client.post(
        f"/api/v1/pay-runs/{draft2['id']}/validate",
        headers=headers,
        json={"override_variance": True},
    )
    assert overridden.status_code == 200, overridden.text

    flags_after = client.get(
        f"/api/v1/pay-runs/{draft2['id']}/variance-flags", headers=headers
    ).json()
    assert flags_after[0]["acknowledged"] is True

    locked = client.post(f"/api/v1/pay-runs/{draft2['id']}/lock", headers=headers)
    assert locked.status_code == 200, locked.text


def test_employee_missing_from_run_is_flagged() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="lifecycle-admin6@example.com")
    employee_id = create_employee(org_id, employee_number="EMP-LC-6A")
    other_employee_id = create_employee(org_id, employee_number="EMP-LC-6B")

    draft1 = _create_draft(headers, employee_ids=[employee_id, other_employee_id])
    client.post(f"/api/v1/pay-runs/{draft1['id']}/validate", headers=headers, json={})
    client.post(f"/api/v1/pay-runs/{draft1['id']}/lock", headers=headers)

    draft2 = _create_draft(
        headers,
        period_start="2026-02-01",
        period_end="2026-02-28",
        employee_ids=[employee_id],
    )
    blocked = client.post(f"/api/v1/pay-runs/{draft2['id']}/validate", headers=headers, json={})
    assert blocked.status_code == 409

    flags = client.get(f"/api/v1/pay-runs/{draft2['id']}/variance-flags", headers=headers).json()
    assert len(flags) == 1
    assert flags[0]["flag_type"] == "employee_missing"
    assert flags[0]["employee_id"] == str(other_employee_id)
