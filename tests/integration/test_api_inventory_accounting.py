"""Inventory Phase 3 end to end: the journals inventory documents post, cost
variances on reversal, bills clearing goods received not invoiced (D2), the
lock date (D13), category expense accounts (D18), switching accounting on
for an organisation that already holds stock, failure rollback,
permissions and tenancy. Every scenario ends with the GL reconciled to the
stock ledger (assert_projections_match_ledger checks it)."""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, update

from app.core.db import tenant_session
from app.models import Role
from app.models.inventory import InventorySettings, InventoryStockMovement
from app.models.inventory_documents import InventoryGoodsReceipt
from app.models.ledger import LedgerEntry
from app.services.posting import today_lagos
from tests.integration.api_helpers import client
from tests.integration.inventory_helpers import (
    API,
    TODAY,
    Store,
    assert_projections_match_ledger,
    box_line,
    headers_for,
    ok,
    stock_by_warehouse,
)

YESTERDAY = (today_lagos() - timedelta(days=1)).isoformat()


def gl(org_id: uuid.UUID, account: str) -> int:
    """Debits less credits on one account."""
    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        return int(
            db.scalar(
                select(
                    func.coalesce(func.sum(LedgerEntry.debit_minor - LedgerEntry.credit_minor), 0)
                ).where(LedgerEntry.org_id == org_id, LedgerEntry.account == account)
            )
        )


def journals(store: Store, document_type: str, document_id: str) -> list[dict[str, Any]]:
    return list(
        ok(
            client.get(
                f"{API}/journals",
                headers=store.admin,
                params={"document_type": document_type, "document_id": document_id},
            )
        )
    )


def lines_of(journal: dict[str, Any]) -> dict[str, int]:
    """account -> debit less credit, for one journal."""
    totals: dict[str, int] = {}
    for line in journal["lines"]:
        totals[line["account"]] = (
            totals.get(line["account"], 0) + line["debit_minor"] - line["credit_minor"]
        )
    return totals


def reconciliation(store: Store) -> dict[str, Any]:
    return dict(ok(client.get(f"{API}/reconciliation", headers=store.admin)))


def receive_boxes(store: Store, boxes: str, price: int, **extra: Any) -> dict[str, Any]:
    po = store.order(
        [{"item_id": store.item, "unit_id": store.units["BOX"], **box_line(boxes, price, **extra)}]
    )
    return store.receive(po, [{"po_line_id": po["lines"][0]["id"], "accepted_quantity": boxes}])


def add_expense_account(store: Store, code: str) -> None:
    ok(
        client.post(
            "/api/v1/chart-of-accounts",
            headers=store.admin,
            json={"code": code, "name": code.replace("_", " ").title(), "type": "expense"},
        ),
        201,
    )


# --- the journals ----------------------------------------------------------------


def test_each_document_posts_its_journal() -> None:
    store = Store()
    add_expense_account(store, "office_supplies")
    office = ok(
        client.post(
            f"{API}/categories",
            headers=store.admin,
            json={"name": "Office", "expense_account_code": "office_supplies"},
        ),
        201,
    )
    paper = ok(
        client.post(
            f"{API}/categories",
            headers=store.admin,
            json={"name": "Paper", "parent_id": office["id"]},
        ),
        201,
    )
    ok(
        client.patch(
            f"{API}/items/{store.item}", headers=store.admin, json={"category_id": paper["id"]}
        )
    )
    loose = store.add_item("SKU-2", default_cost_minor=1_000)

    # Receipt: 10 boxes (100 PCS) at N500 a box, N1,000 off: N4,000 net.
    grn = receive_boxes(store, "10", 500_00, discount_minor=1_000_00)
    [posted] = journals(store, "goods_receipt", grn["id"])
    assert posted["source_event"] == "posted"
    assert posted["reference"] == grn["grn_number"]
    assert lines_of(posted) == {"inventory": 4_000_00, "grni": -4_000_00}

    # Opening balance and a write-off.
    opening = store.adjust("opening_balance", [store.line("50", 10_00, item=loose)])
    [opening_journal] = journals(store, "stock_adjustment", opening["id"])
    assert lines_of(opening_journal) == {
        "inventory": 500_00,
        "inventory_opening_balance": -500_00,
    }
    damage = store.adjust("damage", [store.line("-5", item=loose)])
    [damage_journal] = journals(store, "stock_adjustment", damage["id"])
    assert lines_of(damage_journal) == {"inventory": -50_00, "inventory_adjustment": 50_00}

    # Issue: paper inherits Office's account (D18); the loose item has no
    # category, so it falls back to inventory_consumption.
    issue = ok(
        client.post(
            f"{API}/issues",
            headers=store.admin,
            json={
                "warehouse_id": store.warehouse,
                "issue_date": TODAY,
                "purpose": "office use",
                "lines": [
                    {"item_id": store.item, "quantity": "10"},
                    {"item_id": loose, "quantity": "5"},
                ],
            },
        ),
        201,
    )
    ok(client.post(f"{API}/issues/{issue['id']}/submit", headers=store.admin))
    ok(client.post(f"{API}/issues/{issue['id']}/approve", headers=store.admin, json={}))
    ok(client.post(f"{API}/issues/{issue['id']}/post", headers=store.admin))
    [issue_journal] = journals(store, "stock_issue", issue["id"])
    assert lines_of(issue_journal) == {
        "inventory": -(400_00 + 50_00),
        "office_supplies": 400_00,  # 10 PCS at N40
        "inventory_consumption": 50_00,  # 5 PCS at N10
    }

    # A transfer is value-neutral: only its transit loss reaches the GL.
    transfer = ok(
        client.post(
            f"{API}/transfers",
            headers=store.admin,
            json={
                "from_warehouse_id": store.warehouse,
                "to_warehouse_id": store.side,
                "transfer_date": TODAY,
                "lines": [{"item_id": store.item, "quantity": "20"}],
            },
        ),
        201,
    )
    dispatched = ok(
        client.post(f"{API}/transfers/{transfer['id']}/dispatch", headers=store.admin, json={})
    )
    assert journals(store, "stock_transfer", transfer["id"]) == []
    line_id = dispatched["lines"][0]["id"]
    ok(
        client.post(
            f"{API}/transfers/{transfer['id']}/receive",
            headers=store.admin,
            json={
                "lines": [{"line_id": line_id, "received_quantity_base": "18"}],
                "discrepancy_reason": "two reams soaked",
            },
        )
    )
    [loss] = journals(store, "stock_transfer", transfer["id"])
    assert loss["source_event"] == "transit_loss"
    assert lines_of(loss) == {"inventory": -80_00, "inventory_adjustment": 80_00}

    report = reconciliation(store)
    assert report["post_to_gl"] is True
    assert (
        report["stock_value_minor"]
        == gl(store.org_id, "inventory")
        == store.value() + store.value(loose)
    )
    assert report["inventory_difference_minor"] == 0
    assert report["unbilled_receipts"] == 1
    assert report["unbilled_receipts_minor"] == report["gl_grni_minor"] == 4_000_00
    assert_projections_match_ledger(store.org_id)


def test_reversal_mirrors_the_journal_and_books_the_cost_variance() -> None:
    store = Store()
    first = receive_boxes(store, "10", 1_000_00)  # 100 PCS at N100
    receive_boxes(store, "10", 2_000_00)  # 100 PCS at N200: average N150
    assert store.value() == 30_000_00

    # Reversing the first receipt takes 100 PCS out at today's N150 average,
    # not the N100 they came in at.
    ok(
        client.post(
            f"{API}/goods-receipts/{first['id']}/reverse",
            headers=store.admin,
            json={"reason": "wrong delivery"},
        )
    )
    posted, variance, reversal = journals(store, "goods_receipt", first["id"])
    assert posted["source_event"] == "posted"
    assert reversal["reversal_of_id"] == posted["id"]
    assert reversal["reversal_reason"] == "wrong delivery"
    assert lines_of(reversal) == {"inventory": -10_000_00, "grni": 10_000_00}
    assert variance["source_event"] == "reversal_variance"
    assert lines_of(variance) == {"inventory": -5_000_00, "inventory_adjustment": 5_000_00}
    assert store.value() == 15_000_00 == gl(store.org_id, "inventory")
    # The first receipt's accrual is gone with it.
    assert gl(store.org_id, "grni") == -20_000_00
    assert_projections_match_ledger(store.org_id)


# --- bills and goods received not invoiced (D2) ---------------------------------


def _bill(store: Store, grn: dict[str, Any] | None, amount: int, **extra: Any) -> Any:
    body = {
        "vendor_id": store.vendor,
        "bill_number": f"INV-{uuid.uuid4().hex[:8]}",
        "bill_date": TODAY,
        "due_date": TODAY,
        "expense_account_code": "purchase_price_variance",
        "amount_minor": amount,
        **extra,
    }
    if grn is not None:
        body["goods_receipt_id"] = grn["id"]
    return client.post("/api/v1/bills", headers=store.admin, json=body)


def test_a_bill_for_a_receipt_clears_its_accrual() -> None:
    store = Store()
    ok(client.post("/api/v1/chart-of-accounts/seed-defaults", headers=store.admin))
    add_expense_account(store, "purchase_price_variance")
    grn = receive_boxes(store, "10", 1_000_00)  # accrues N10,000
    listed = ok(
        client.get(
            f"{API}/goods-receipts",
            headers=store.admin,
            params={"vendor_id": store.vendor, "unbilled": True},
        )
    )
    assert [r["id"] for r in listed] == [grn["id"]]
    assert listed[0]["accrued_minor"] == 10_000_00

    # The vendor invoices N10,300 plus N772.50 VAT: N300 over the order.
    bill = ok(_bill(store, grn, 10_300_00, vat_minor=772_50), 201)
    assert bill["goods_receipt_id"] == grn["id"]
    assert (
        ok(client.get(f"{API}/goods-receipts", headers=store.admin, params={"unbilled": True}))
        == []
    )
    # A second bill for the same receipt is refused, as is reversing it.
    assert _bill(store, grn, 10_000_00).status_code == 400
    reverse = client.post(
        f"{API}/goods-receipts/{grn['id']}/reverse", headers=store.admin, json={"reason": "x"}
    )
    assert reverse.status_code == 409
    assert "void the bill first" in reverse.json()["detail"]

    ok(client.post(f"/api/v1/bills/{bill['id']}/approve", headers=store.admin))
    assert gl(store.org_id, "grni") == 0
    assert gl(store.org_id, "purchase_price_variance") == 300_00
    assert gl(store.org_id, "vat_receivable") == 772_50
    assert gl(store.org_id, "accounts_payable") == -(10_300_00 + 772_50)
    report = reconciliation(store)
    assert report["unbilled_receipts"] == 0
    assert report["grni_difference_minor"] == 0
    reverse = client.post(
        f"{API}/goods-receipts/{grn['id']}/reverse", headers=store.admin, json={"reason": "x"}
    )
    assert reverse.status_code == 409
    assert_projections_match_ledger(store.org_id)


def test_a_bill_under_the_accrual_credits_the_difference() -> None:
    store = Store()
    ok(client.post("/api/v1/chart-of-accounts/seed-defaults", headers=store.admin))
    add_expense_account(store, "purchase_price_variance")
    grn = receive_boxes(store, "10", 1_000_00)
    bill = ok(_bill(store, grn, 9_800_00), 201)
    ok(client.post(f"/api/v1/bills/{bill['id']}/approve", headers=store.admin))
    assert gl(store.org_id, "grni") == 0
    assert gl(store.org_id, "purchase_price_variance") == -200_00
    assert gl(store.org_id, "accounts_payable") == -9_800_00
    assert_projections_match_ledger(store.org_id)


def test_bill_links_are_checked() -> None:
    store = Store()
    ok(client.post("/api/v1/chart-of-accounts/seed-defaults", headers=store.admin))
    add_expense_account(store, "purchase_price_variance")
    po = store.order([{"item_id": store.item, **box_line("10", 1_000)}])
    draft = store.receive(
        po, [{"po_line_id": po["lines"][0]["id"], "accepted_quantity": "1"}], post=False
    )
    refused = _bill(store, draft, 1_000)
    assert refused.status_code == 400 and "not posted" in refused.json()["detail"]

    other_vendor = ok(
        client.post("/api/v1/vendors", headers=store.admin, json={"name": "Other"}), 201
    )
    grn = ok(client.post(f"{API}/goods-receipts/{draft['id']}/post", headers=store.admin))
    refused = _bill(store, grn, 1_000, vendor_id=other_vendor["id"])
    assert refused.status_code == 400 and "different vendor" in refused.json()["detail"]

    # Another organisation's receipt can't be linked at all.
    stranger = Store()
    ok(client.post("/api/v1/chart-of-accounts/seed-defaults", headers=stranger.admin))
    add_expense_account(stranger, "purchase_price_variance")
    refused = client.post(
        "/api/v1/bills",
        headers=stranger.admin,
        json={
            "vendor_id": stranger.vendor,
            "bill_number": "X-1",
            "bill_date": TODAY,
            "due_date": TODAY,
            "expense_account_code": "purchase_price_variance",
            "amount_minor": 1_000,
            "goods_receipt_id": grn["id"],
        },
    )
    assert refused.status_code == 400 and "not found" in refused.json()["detail"]

    # Voiding a draft bill frees the receipt again.
    bill = ok(_bill(store, grn, 1_000), 201)
    ok(client.post(f"/api/v1/bills/{bill['id']}/void", headers=store.admin))
    ok(_bill(store, grn, 1_000), 201)


# --- the lock date (D13) -----------------------------------------------------------


def test_nothing_posts_into_a_locked_period() -> None:
    store = Store()
    ok(
        client.patch(
            "/api/v1/accounting-settings", headers=store.admin, json={"lock_date": YESTERDAY}
        )
    )
    settings = ok(client.get("/api/v1/accounting-settings", headers=store.admin))
    assert settings["lock_date"] == YESTERDAY
    future = client.patch(
        "/api/v1/accounting-settings",
        headers=store.admin,
        json={"lock_date": (today_lagos() + timedelta(days=1)).isoformat()},
    )
    assert future.status_code == 400

    # A backdated adjustment is refused before any stock moves.
    backdated = ok(
        client.post(
            f"{API}/adjustments",
            headers=store.admin,
            json={
                "warehouse_id": store.warehouse,
                "reason": "opening_balance",
                "adjustment_date": YESTERDAY,
                "lines": [store.line("10", 100)],
            },
        ),
        201,
    )
    refused = client.post(f"{API}/adjustments/{backdated['id']}/post", headers=store.admin)
    assert refused.status_code == 400
    assert "locked period" in refused.json()["detail"]
    assert stock_by_warehouse(store) == {}

    # Today is open.
    store.adjust("opening_balance", [store.line("10", 100)])

    # The lock binds every journal writer: locking today stops a manual
    # journal too, and clearing the lock lets it through.
    ok(client.patch("/api/v1/accounting-settings", headers=store.admin, json={"lock_date": TODAY}))
    manual = {
        "description": "reclass",
        "lines": [
            {"account_code": "inventory_adjustment", "debit_minor": 100},
            {"account_code": "inventory_opening_balance", "credit_minor": 100},
        ],
    }
    blocked = client.post(
        "/api/v1/general-ledger/journal-entries", headers=store.admin, json=manual
    )
    assert blocked.status_code == 400 and "locked period" in blocked.json()["detail"]
    ok(client.patch("/api/v1/accounting-settings", headers=store.admin, json={"lock_date": None}))
    ok(client.post("/api/v1/general-ledger/journal-entries", headers=store.admin, json=manual), 201)
    ok(client.post(f"{API}/adjustments/{backdated['id']}/post", headers=store.admin))
    assert_projections_match_ledger(store.org_id)


# --- failure rollback ---------------------------------------------------------------


def test_a_refused_journal_leaves_stock_untouched() -> None:
    store = Store()
    accounts = ok(client.get("/api/v1/chart-of-accounts", headers=store.admin))
    inventory = next(a for a in accounts if a["code"] == "inventory")
    ok(
        client.patch(
            f"/api/v1/chart-of-accounts/{inventory['id']}",
            headers=store.admin,
            json={"is_active": False},
        )
    )
    po = store.order([{"item_id": store.item, **box_line("10", 1_000)}])
    grn = store.receive(
        po, [{"po_line_id": po["lines"][0]["id"], "accepted_quantity": "10"}], post=False
    )
    refused = client.post(f"{API}/goods-receipts/{grn['id']}/post", headers=store.admin)
    assert refused.status_code == 400
    assert "inactive" in refused.json()["detail"]

    # Nothing of the posting survived: no movement, no journal, the receipt
    # is still a draft and the order still has everything outstanding.
    with tenant_session(store.org_id, uuid.uuid4(), "admin") as db:
        assert db.scalar(select(func.count()).select_from(InventoryStockMovement)) == 0
        assert db.get(InventoryGoodsReceipt, uuid.UUID(grn["id"])).status.value == "draft"
    assert journals(store, "goods_receipt", grn["id"]) == []
    assert store.po(po["id"])["status"] == "issued"

    ok(
        client.patch(
            f"/api/v1/chart-of-accounts/{inventory['id']}",
            headers=store.admin,
            json={"is_active": True},
        )
    )
    ok(client.post(f"{API}/goods-receipts/{grn['id']}/post", headers=store.admin))
    assert_projections_match_ledger(store.org_id)


# --- switching accounting on for existing stock ------------------------------------


def _pre_phase_three(store: Store) -> None:
    """Makes the store look like an organisation that started inventory
    before Phase 3: GL posting off."""
    with tenant_session(store.org_id, uuid.uuid4(), "admin") as db:
        db.execute(
            update(InventorySettings)
            .where(InventorySettings.org_id == store.org_id)
            .values(post_to_gl=False, gl_started_at=None)
        )


def test_starting_accounting_posts_the_opening_balance() -> None:
    store = Store()
    ok(client.post("/api/v1/chart-of-accounts/seed-defaults", headers=store.admin))
    add_expense_account(store, "purchase_price_variance")
    _pre_phase_three(store)
    before = store.adjust("opening_balance", [store.line("100", 1_000)])
    grn = receive_boxes(store, "10", 2_000_00)
    assert gl(store.org_id, "inventory") == 0
    report = reconciliation(store)
    assert report["post_to_gl"] is False
    # 100 PCS at N10 plus 10 boxes at N2,000, none of it on the books yet.
    assert report["stock_value_minor"] == store.value() == 1_000_00 + 20_000_00
    assert report["inventory_difference_minor"] == -report["stock_value_minor"]

    # Starting needs accounting.manage as well as inventory.manage.
    auditor = headers_for(store.org_id, Role.AUDITOR)
    assert client.post(f"{API}/accounting/start", headers=auditor).status_code == 403
    started = ok(client.post(f"{API}/accounting/start", headers=store.admin))
    assert started["post_to_gl"] is True and started["gl_started_at"] is not None
    assert client.post(f"{API}/accounting/start", headers=store.admin).status_code == 400

    stock_value = store.value()
    assert gl(store.org_id, "inventory") == stock_value
    assert gl(store.org_id, "inventory_opening_balance") == -stock_value
    report = reconciliation(store)
    assert report["inventory_difference_minor"] == 0
    # A receipt from before the start accrued nothing, so it can't clear
    # goods received not invoiced; it is billed without a link.
    assert report["unbilled_receipts"] == 0 and report["gl_grni_minor"] == 0
    refused = _bill(store, grn, 20_000_00)
    assert refused.status_code == 400 and "accrued nothing" in refused.json()["detail"]

    # Reversing a document from before the start goes back through the
    # opening balance it was brought on with.
    ok(
        client.post(
            f"{API}/adjustments/{before['id']}/reverse",
            headers=store.admin,
            json={"reason": "double counted"},
        )
    )
    [reversed_] = journals(store, "stock_adjustment", before["id"])
    assert reversed_["source_event"] == "reversed"
    assert set(lines_of(reversed_)) == {"inventory", "inventory_opening_balance"}
    assert gl(store.org_id, "inventory") == store.value()
    assert_projections_match_ledger(store.org_id)


# --- categories, permissions and tenancy ----------------------------------------------


def test_category_accounts_must_be_active_expense_accounts() -> None:
    store = Store()
    for code, why in (("nope", "not an expense account"), ("inventory", "not an expense account")):
        refused = client.post(
            f"{API}/categories",
            headers=store.admin,
            json={"name": f"Cat {code}", "expense_account_code": code},
        )
        assert refused.status_code == 400 and why in refused.json()["detail"]
    category = ok(
        client.post(
            f"{API}/categories",
            headers=store.admin,
            json={"name": "Cleaning", "expense_account_code": "inventory_consumption"},
        ),
        201,
    )
    assert category["expense_account_code"] == "inventory_consumption"
    cleared = ok(
        client.patch(
            f"{API}/categories/{category['id']}",
            headers=store.admin,
            json={"expense_account_code": None},
        )
    )
    assert cleared["expense_account_code"] is None


def test_accounting_reads_need_valuation_and_stay_in_the_org() -> None:
    store = Store()
    grn = receive_boxes(store, "1", 1_000)
    manager = headers_for(store.org_id, Role.DEPARTMENT_MANAGER)
    params = {"document_type": "goods_receipt", "document_id": grn["id"]}
    assert client.get(f"{API}/reconciliation", headers=manager).status_code == 403
    assert client.get(f"{API}/journals", headers=manager, params=params).status_code == 403
    auditor = headers_for(store.org_id, Role.AUDITOR)  # holds inventory.valuation
    assert len(ok(client.get(f"{API}/journals", headers=auditor, params=params))) == 1

    stranger = Store()
    assert ok(client.get(f"{API}/journals", headers=stranger.admin, params=params)) == []
    assert reconciliation(stranger)["stock_value_minor"] == 0
