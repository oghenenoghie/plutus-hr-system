"""VAT on vendor bills (the same choices as an invoice) and the monthly VAT
report: output VAT on invoices sent, less credit notes, against input VAT on
bills approved, netted to what is owed or carried forward."""

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


def _setup(email: str, *, tin: str | None = None) -> tuple[dict[str, str], str, str]:
    org_id = create_org()
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    headers = auth_headers(login_with_mfa(account_id, email, Role.ADMIN)["access_token"])
    if tin:
        client.put("/api/v1/organisation", headers=headers, json={"company_tin": tin})
    seeded = client.post("/api/v1/chart-of-accounts/seed-defaults", headers=headers)
    assert seeded.status_code == 200, seeded.text
    customer = client.post("/api/v1/customers", headers=headers, json={"name": "Zenith Retail"})
    vendor = client.post("/api/v1/vendors", headers=headers, json={"name": "Acme Supplies"})
    return headers, customer.json()["id"], vendor.json()["id"]


def _bill(
    headers: dict[str, str],
    vendor_id: str,
    number: str,
    *,
    amount: int = 400_000_00,
    bill_date: str = "2026-11-05",
    approve: bool = True,
    **vat,
) -> dict:
    created = client.post(
        "/api/v1/bills",
        headers=headers,
        json={
            "vendor_id": vendor_id,
            "bill_number": number,
            "bill_date": bill_date,
            "due_date": "2026-12-31",
            "expense_account_code": "contractor_expense",
            "amount_minor": amount,
            **vat,
        },
    )
    assert created.status_code == 201, created.text
    bill = created.json()
    if approve:
        approved = client.post(f"/api/v1/bills/{bill['id']}/approve", headers=headers)
        assert approved.status_code == 200, approved.text
        bill = approved.json()
    return bill


def _invoice(
    headers: dict[str, str],
    customer_id: str,
    number: str,
    *,
    amount: int,
    issue_date: str = "2026-11-03",
    send: bool = True,
    **vat,
) -> dict:
    created = client.post(
        "/api/v1/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_number": number,
            "issue_date": issue_date,
            "due_date": "2026-12-31",
            "revenue_account_code": "revenue",
            "amount_minor": amount,
            **vat,
        },
    )
    assert created.status_code == 201, created.text
    invoice = created.json()
    if send:
        sent = client.post(f"/api/v1/invoices/{invoice['id']}/send", headers=headers)
        assert sent.status_code == 200, sent.text
    return invoice


def test_bill_vat_options_and_each_treatment_sets_the_rate_and_total() -> None:
    headers, _, vendor_id = _setup("bill-vat-options@example.com")
    options = client.get("/api/v1/bills/vat-options", headers=headers)
    assert options.status_code == 200, options.text
    assert [(o["treatment"], o["label"]) for o in options.json()["options"]] == [
        ("standard", "VAT 7.5%"),
        ("exempt", "VAT exempt"),
        ("zero_rated", "Zero-rated"),
        ("other", "Other rate"),
    ]

    standard = _bill(headers, vendor_id, "B-1", approve=False, vat_treatment="standard")
    assert (standard["vat_rate_name"], standard["vat_rate_ppm"]) == ("VAT 7.5%", 75_000)
    assert (standard["vat_minor"], standard["total_minor"]) == (30_000_00, 430_000_00)
    assert standard["net_payable_minor"] == 430_000_00
    exempt = _bill(headers, vendor_id, "B-2", approve=False, vat_treatment="exempt")
    assert (exempt["vat_rate_name"], exempt["vat_minor"]) == ("VAT exempt", 0)
    other = _bill(
        headers,
        vendor_id,
        "B-3",
        approve=False,
        vat_treatment="other",
        vat_rate_name="Ghana VAT 15%",
        vat_rate_ppm=150_000,
    )
    assert (other["vat_rate_name"], other["vat_minor"]) == ("Ghana VAT 15%", 60_000_00)
    # Left out, no VAT, as before.
    plain = _bill(headers, vendor_id, "B-4", approve=False)
    assert (plain["vat_treatment"], plain["vat_minor"], plain["total_minor"]) == (
        None,
        0,
        400_000_00,
    )

    unnamed = client.post(
        "/api/v1/bills",
        headers=headers,
        json={
            "vendor_id": vendor_id,
            "bill_number": "B-5",
            "bill_date": "2026-11-05",
            "due_date": "2026-11-30",
            "expense_account_code": "contractor_expense",
            "amount_minor": 100_000_00,
            "vat_treatment": "other",
            "vat_rate_ppm": 150_000,
        },
    )
    assert unnamed.status_code == 400
    mismatched = client.post(
        "/api/v1/bills",
        headers=headers,
        json={
            "vendor_id": vendor_id,
            "bill_number": "B-6",
            "bill_date": "2026-11-05",
            "due_date": "2026-11-30",
            "expense_account_code": "contractor_expense",
            "amount_minor": 100_000_00,
            "vat_treatment": "standard",
            "vat_minor": 1_00,
        },
    )
    assert mismatched.status_code == 400
    assert "rate" in mismatched.json()["detail"]


def test_a_standard_rated_bill_posts_input_vat_and_withholds_tax_on_the_net() -> None:
    headers, _, vendor_id = _setup("bill-vat-wht@example.com")
    bill = _bill(
        headers,
        vendor_id,
        "B-W1",
        amount=100_000_00,
        vat_treatment="standard",
        wht_category="services",
    )
    assert bill["vat_minor"] == 7_500_00
    lines = client.get("/api/v1/general-ledger/trial-balance", headers=headers).json()
    balances = {line["account"]: line["balance_minor"] for line in lines}
    assert balances["vat_receivable"] == 7_500_00
    assert balances["contractor_expense"] == 100_000_00
    # The payable is the total less tax withheld, which is worked out on the
    # amount before VAT.
    assert bill["net_payable_minor"] == 107_500_00 - bill["wht_amount_minor"]
    assert balances["accounts_payable"] == -bill["net_payable_minor"]


def test_the_monthly_vat_report_nets_output_vat_against_input_vat() -> None:
    headers, customer_id, vendor_id = _setup("vat-report@example.com", tin="21345678-0001")
    standard = _invoice(
        headers, customer_id, "INV-1", amount=1_000_000_00, vat_treatment="standard"
    )
    _invoice(headers, customer_id, "INV-2", amount=200_000_00, vat_treatment="exempt")
    _invoice(headers, customer_id, "INV-3", amount=300_000_00, vat_treatment="zero_rated")
    # Not counted: a draft, and an invoice sent in October.
    _invoice(headers, customer_id, "INV-4", amount=50_000_00, vat_treatment="standard", send=False)
    _invoice(
        headers,
        customer_id,
        "INV-5",
        amount=80_000_00,
        issue_date="2026-10-20",
        vat_treatment="standard",
    )
    credit = client.post(
        f"/api/v1/invoices/{standard['id']}/credit-notes",
        headers=headers,
        json={
            "credit_note_number": "CN-1",
            "issue_date": "2026-11-10",
            "amount_minor": 107_500_00,
            "reason": "Returned goods",
        },
    )
    assert credit.status_code == 201, credit.text

    _bill(headers, vendor_id, "B-1", vat_treatment="standard")  # VAT 30,000
    _bill(
        headers,
        vendor_id,
        "B-2",
        amount=100_000_00,
        vat_treatment="other",
        vat_rate_name="Ghana VAT 15%",
        vat_rate_ppm=150_000,
    )  # VAT 15,000
    _bill(headers, vendor_id, "B-3", vat_treatment="standard", approve=False)  # draft
    _bill(headers, vendor_id, "B-4", bill_date="2026-10-31", vat_treatment="standard")

    response = client.get(
        "/api/v1/financial-statements/vat-report?year=2026&month=11", headers=headers
    )
    assert response.status_code == 200, response.text
    report = response.json()
    assert (report["period_start"], report["period_end"]) == ("2026-11-01", "2026-11-30")
    assert [
        (g["label"], g["document_count"], g["net_minor"], g["vat_minor"])
        for g in report["output_groups"]
    ] == [
        ("VAT 7.5%", 1, 1_000_000_00, 75_000_00),
        ("Zero-rated", 1, 300_000_00, 0),
        ("VAT exempt", 1, 200_000_00, 0),
    ]
    assert report["vat_charged_minor"] == 75_000_00
    assert (report["credit_note_count"], report["credit_note_vat_minor"]) == (1, 7_500_00)
    assert report["credit_note_net_minor"] == 100_000_00
    assert report["output_vat_minor"] == 67_500_00
    assert [(g["label"], g["vat_minor"]) for g in report["input_groups"]] == [
        ("VAT 7.5%", 30_000_00),
        ("Ghana VAT 15%", 15_000_00),
    ]
    assert report["input_vat_minor"] == 45_000_00
    assert report["net_vat_minor"] == 22_500_00
    assert report["position"] == "payable"
    assert (report["draft_invoice_count"], report["draft_bill_count"]) == (1, 1)
    kinds = [(d["kind"], d["number"], d["vat_minor"]) for d in report["documents"]]
    assert ("credit_note", "CN-1", -7_500_00) in kinds
    assert len(kinds) == 6

    # October: only what is dated in October.
    october = client.get(
        "/api/v1/financial-statements/vat-report?year=2026&month=10", headers=headers
    ).json()
    assert october["output_vat_minor"] == 6_000_00
    assert october["input_vat_minor"] == 30_000_00
    assert (october["net_vat_minor"], october["position"]) == (-24_000_00, "refundable")

    with mock.patch.object(rl_config, "pageCompression", 0):
        pdf = client.get(
            "/api/v1/financial-statements/vat-report/pdf?year=2026&month=11", headers=headers
        )
    assert pdf.status_code == 200, pdf.text
    assert pdf.headers["content-type"] == "application/pdf"
    assert 'filename="vat-report-2026-11.pdf"' in pdf.headers["content-disposition"]
    for text in (
        b"VAT Report",
        b"November 2026",
        b"21345678-0001",
        b"Net VAT payable",
        b"22,500.00 NGN",
        b"Ghana VAT 15%",
        b"CN-1",
    ):
        assert text in pdf.content, text


def test_the_vat_report_refuses_a_month_out_of_range() -> None:
    headers, _, _ = _setup("vat-report-range@example.com")
    bad = client.get("/api/v1/financial-statements/vat-report?year=2026&month=13", headers=headers)
    assert bad.status_code == 400
    empty = client.get("/api/v1/financial-statements/vat-report?year=2026&month=1", headers=headers)
    assert empty.status_code == 200
    assert (empty.json()["net_vat_minor"], empty.json()["position"]) == (0, "nil")
