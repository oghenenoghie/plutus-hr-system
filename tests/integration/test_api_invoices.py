from unittest import mock

from reportlab import rl_config

from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_org,
    login_with_mfa,
)


def _admin_headers(org_id, email: str = "invoice-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def _setup(email: str) -> tuple[dict[str, str], str]:
    org_id = create_org()
    headers = _admin_headers(org_id, email=email)
    seeded = client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    assert seeded.status_code == 200, seeded.text
    customer = client.post("/api/v1/customers", headers=headers, json={"name": "Zenith Retail Ltd"})
    assert customer.status_code == 201, customer.text
    return headers, customer.json()["id"]


def _create_invoice(
    headers: dict[str, str], customer_id: str, invoice_number: str = "INV-2001"
) -> dict:
    response = client.post(
        "/api/v1/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_number": invoice_number,
            "issue_date": "2026-09-01",
            "due_date": "2026-09-30",
            "revenue_account_code": "revenue",
            "amount_minor": 800_000_00,
            "description": "September services rendered",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_invoice_lifecycle_draft_to_sent_to_paid_posts_balanced_ledger_entries() -> None:
    headers, customer_id = _setup("invoice-admin1@example.com")
    invoice = _create_invoice(headers, customer_id)
    assert invoice["status"] == "draft"

    sent = client.post(f"/api/v1/invoices/{invoice['id']}/send", headers=headers)
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "sent"

    paid = client.post(f"/api/v1/invoices/{invoice['id']}/pay", headers=headers)
    assert paid.status_code == 200, paid.text
    assert paid.json()["status"] == "paid"
    assert paid.json()["paid_at"] is not None

    trial_balance = client.get("/api/v1/general-ledger/trial-balance", headers=headers)
    by_account = {line["account"]: line for line in trial_balance.json()}
    assert by_account["revenue"]["balance_minor"] == -800_000_00
    assert by_account["accounts_receivable"]["balance_minor"] == 0
    assert by_account["cash"]["balance_minor"] == 800_000_00


def test_invoice_cannot_be_paid_before_being_sent() -> None:
    headers, customer_id = _setup("invoice-admin2@example.com")
    invoice = _create_invoice(headers, customer_id)

    response = client.post(f"/api/v1/invoices/{invoice['id']}/pay", headers=headers)
    assert response.status_code == 400
    assert "sent" in response.json()["detail"]


def test_invoice_cannot_be_sent_twice() -> None:
    headers, customer_id = _setup("invoice-admin3@example.com")
    invoice = _create_invoice(headers, customer_id)

    client.post(f"/api/v1/invoices/{invoice['id']}/send", headers=headers)
    second = client.post(f"/api/v1/invoices/{invoice['id']}/send", headers=headers)
    assert second.status_code == 400


def test_sent_invoice_cannot_be_voided_but_draft_invoice_can() -> None:
    headers, customer_id = _setup("invoice-admin4@example.com")
    invoice = _create_invoice(headers, customer_id)

    client.post(f"/api/v1/invoices/{invoice['id']}/send", headers=headers)
    denied = client.post(f"/api/v1/invoices/{invoice['id']}/void", headers=headers)
    assert denied.status_code == 400

    draft_invoice = _create_invoice(headers, customer_id, invoice_number="INV-2002")
    voided = client.post(f"/api/v1/invoices/{draft_invoice['id']}/void", headers=headers)
    assert voided.status_code == 200
    assert voided.json()["status"] == "void"


def test_invoice_rejects_unknown_revenue_account() -> None:
    headers, customer_id = _setup("invoice-admin5@example.com")

    response = client.post(
        "/api/v1/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_number": "INV-2003",
            "issue_date": "2026-09-01",
            "due_date": "2026-09-30",
            "revenue_account_code": "not_a_real_account",
            "amount_minor": 1_000_00,
        },
    )
    assert response.status_code == 400


def test_invoice_numbers_are_issued_when_left_blank() -> None:
    headers, customer_id = _setup("invoice-autonumber@example.com")

    def create(number: str | None) -> dict:
        body = {
            "customer_id": customer_id,
            "issue_date": "2026-09-01",
            "due_date": "2026-09-30",
            "revenue_account_code": "revenue",
            "amount_minor": 1_000_00,
        }
        if number is not None:
            body["invoice_number"] = number
        response = client.post("/api/v1/invoices", headers=headers, json=body)
        assert response.status_code == 201, response.text
        return response.json()

    assert client.get("/api/v1/invoices/next-number", headers=headers).json() == {
        "invoice_number": "INV-0001"
    }
    assert create(None)["invoice_number"] == "INV-0001"
    assert create("")["invoice_number"] == "INV-0002"
    # A number typed by hand moves the sequence on; one in another form doesn't.
    assert create("INV-0010")["invoice_number"] == "INV-0010"
    assert create("SPECIAL-7")["invoice_number"] == "SPECIAL-7"
    assert client.get("/api/v1/invoices/next-number", headers=headers).json() == {
        "invoice_number": "INV-0011"
    }
    assert create(None)["invoice_number"] == "INV-0011"


def test_customer_address_and_tax_id_print_on_the_invoice() -> None:
    headers, _ = _setup("invoice-address@example.com")
    customer = client.post(
        "/api/v1/customers",
        headers=headers,
        json={"name": "Dangote Stores", "tin": "12345678-0001", "address": "12 Marina\nLagos"},
    )
    assert customer.status_code == 201, customer.text
    assert customer.json()["address"] == "12 Marina\nLagos"
    updated = client.patch(
        f"/api/v1/customers/{customer.json()['id']}",
        headers=headers,
        json={"address": "14 Marina\nLagos Island"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["address"] == "14 Marina\nLagos Island"

    invoice = _create_invoice(headers, customer.json()["id"], invoice_number="INV-ADDR")
    pdf = client.get(f"/api/v1/invoices/{invoice['id']}/pdf", headers=headers)
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")

    vendor = client.post(
        "/api/v1/vendors",
        headers=headers,
        json={"name": "Acme Supplies", "tin": "98765432-0001", "address": "3 Allen Avenue, Ikeja"},
    )
    assert vendor.status_code == 201, vendor.text
    assert vendor.json()["address"] == "3 Allen Avenue, Ikeja"


def _vat_invoice(headers: dict[str, str], customer_id: str, number: str, **vat) -> dict:
    response = client.post(
        "/api/v1/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_number": number,
            "issue_date": "2026-11-01",
            "due_date": "2026-11-30",
            "revenue_account_code": "revenue",
            "amount_minor": 1_000_000_00,
            **vat,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_vat_options_offer_the_standard_rate_exempt_zero_rated_and_other() -> None:
    headers, _ = _setup("invoice-vat-options@example.com")
    options = client.get("/api/v1/invoices/vat-options", headers=headers)
    assert options.status_code == 200, options.text
    body = options.json()
    assert body["country_code"] == "NG"
    assert [(o["treatment"], o["label"], o["rate_ppm"]) for o in body["options"]] == [
        ("standard", "VAT 7.5%", 75_000),
        ("exempt", "VAT exempt", 0),
        ("zero_rated", "Zero-rated", 0),
        ("other", "Other rate", None),
    ]


def test_each_vat_treatment_sets_the_rate_and_the_total() -> None:
    headers, customer_id = _setup("invoice-vat-treatments@example.com")
    standard = _vat_invoice(headers, customer_id, "INV-V1", vat_treatment="standard")
    assert (standard["vat_rate_name"], standard["vat_rate_ppm"]) == ("VAT 7.5%", 75_000)
    assert standard["vat_minor"] == 75_000_00
    assert standard["total_minor"] == 1_075_000_00

    for number, treatment, name in (
        ("INV-V2", "exempt", "VAT exempt"),
        ("INV-V3", "zero_rated", "Zero-rated"),
    ):
        invoice = _vat_invoice(headers, customer_id, number, vat_treatment=treatment)
        assert (invoice["vat_rate_name"], invoice["vat_minor"]) == (name, 0)
        assert invoice["total_minor"] == 1_000_000_00

    # A rate the user names, for a customer taxed elsewhere.
    other = _vat_invoice(
        headers,
        customer_id,
        "INV-V4",
        vat_treatment="other",
        vat_rate_name="Ghana VAT 15%",
        vat_rate_ppm=150_000,
    )
    assert (other["vat_rate_name"], other["vat_minor"]) == ("Ghana VAT 15%", 150_000_00)
    assert other["total_minor"] == 1_150_000_00

    # Without VAT, as before.
    plain = _vat_invoice(headers, customer_id, "INV-V5")
    assert (plain["vat_treatment"], plain["vat_minor"]) == (None, 0)
    assert plain["total_minor"] == 1_000_000_00


def test_other_vat_needs_a_name_and_a_rate() -> None:
    headers, customer_id = _setup("invoice-vat-other@example.com")
    base = {
        "customer_id": customer_id,
        "issue_date": "2026-11-01",
        "due_date": "2026-11-30",
        "revenue_account_code": "revenue",
        "amount_minor": 1_000_00,
        "vat_treatment": "other",
    }
    no_name = client.post(
        "/api/v1/invoices", headers=headers, json={**base, "vat_rate_ppm": 50_000}
    )
    assert no_name.status_code == 400
    assert "name the VAT rate" in no_name.json()["detail"]
    no_rate = client.post(
        "/api/v1/invoices", headers=headers, json={**base, "vat_rate_name": "Kenya VAT"}
    )
    assert no_rate.status_code == 400
    too_high = client.post(
        "/api/v1/invoices",
        headers=headers,
        json={**base, "vat_rate_name": "Wrong", "vat_rate_ppm": 1_500_000},
    )
    assert too_high.status_code == 422


def test_a_vat_invoice_posts_output_vat_and_is_paid_and_credited_in_full() -> None:
    headers, customer_id = _setup("invoice-vat-ledger@example.com")
    invoice = _vat_invoice(headers, customer_id, "INV-VL1", vat_treatment="standard")
    sent = client.post(f"/api/v1/invoices/{invoice['id']}/send", headers=headers)
    assert sent.status_code == 200, sent.text

    def balances() -> dict[str, int]:
        lines = client.get("/api/v1/general-ledger/trial-balance", headers=headers).json()
        return {line["account"]: line["balance_minor"] for line in lines}

    after_send = balances()
    assert after_send["accounts_receivable"] == 1_075_000_00
    assert after_send["revenue"] == -1_000_000_00
    assert after_send["vat_payable"] == -75_000_00

    # What the customer owes is the total, VAT included.
    aging = client.get("/api/v1/reports/ar-aging?as_of=2026-11-15", headers=headers)
    assert aging.status_code == 200, aging.text
    assert [row["amount_minor"] for row in aging.json()] == [1_075_000_00]

    # Credit part of it: income and output VAT come back in proportion.
    credit = client.post(
        f"/api/v1/invoices/{invoice['id']}/credit-notes",
        headers=headers,
        json={
            "credit_note_number": "CN-1",
            "issue_date": "2026-11-10",
            "amount_minor": 107_500_00,
            "reason": "Returned goods",
        },
    )
    assert credit.status_code == 201, credit.text
    after_credit = balances()
    assert after_credit["vat_payable"] == -67_500_00
    assert after_credit["revenue"] == -900_000_00
    assert after_credit["accounts_receivable"] == 967_500_00


def test_the_invoice_prints_our_tin_at_the_top_and_its_vat() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, email="invoice-tin-top@example.com")
    client.put(
        "/api/v1/organisation",
        headers=headers,
        json={"company_tin": "21345678-0001", "rc_number": "RC 1234567"},
    )
    client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    customer = client.post("/api/v1/customers", headers=headers, json={"name": "Accra Imports"})
    invoice = _vat_invoice(
        headers,
        customer.json()["id"],
        "INV-TIN1",
        vat_treatment="other",
        vat_rate_name="Ghana VAT 15%",
        vat_rate_ppm=150_000,
    )
    with mock.patch.object(rl_config, "pageCompression", 0):
        pdf = client.get(f"/api/v1/invoices/{invoice['id']}/pdf", headers=headers)
    assert pdf.status_code == 200
    content = pdf.content
    assert b"INVOICE" in content
    assert b"21345678-0001" in content
    assert b"RC 1234567" in content
    assert b"Ghana VAT 15%" in content
    assert b"1,150,000.00 NGN" in content
