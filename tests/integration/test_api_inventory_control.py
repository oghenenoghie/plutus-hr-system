"""Inventory Phase 4 (stock control): lots and expiry (D9), stocktakes
against a cutoff snapshot (D6), reorder suggestions and the stock reports,
whose totals must agree with the movement ledger and the GL."""

import csv
import io
import threading
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from app.core.db import get_engine, tenant_session
from app.models import Role
from app.services.inventory_adjustments import post_adjustment
from app.services.inventory_posting import _WAREHOUSE_LOCK_CLASS, _warehouse_lock_key
from app.services.posting import today_lagos
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    get_membership_id,
    login,
)
from tests.integration.inventory_helpers import (
    API,
    TODAY,
    Shop,
    Store,
    assert_projections_match_ledger,
    headers_for,
    ok,
    stock_by_warehouse,
)

YESTERDAY = (today_lagos() - timedelta(days=1)).isoformat()


def in_days(days: int) -> str:
    return (today_lagos() + timedelta(days=days)).isoformat()


def lot_item(shop: Shop, sku: str = "SYRUP", *, expiry: bool = True, **extra: Any) -> str:
    return shop.add_item(sku, track_lots=True, track_expiry=expiry, **extra)


def gain(
    shop: Shop, item: str, quantity: str, lot: str | None, expiry: str | None, cost: int = 100
) -> dict[str, Any]:
    line: dict[str, Any] = {"item_id": item, "quantity": quantity, "unit_cost_minor": cost}
    if lot is not None:
        line["lot_number"] = lot
    if expiry is not None:
        line["expiry_date"] = expiry
    return line


def lots(shop: Shop, item: str, warehouse: str | None = None) -> dict[str, Decimal]:
    params = {"item_id": item}
    if warehouse:
        params["warehouse_id"] = warehouse
    rows = ok(client.get(f"{API}/lots", headers=shop.admin, params=params))
    out: dict[str, Decimal] = {}
    for row in rows:
        key = row["lot_number"] if warehouse else f"{row['warehouse_code']}:{row['lot_number']}"
        out[key] = Decimal(row["quantity"])
    return out


def issue(store: Store, item: str, quantity: str, *, post: bool = True) -> Any:
    created = ok(
        client.post(
            f"{API}/issues",
            headers=store.admin,
            json={
                "warehouse_id": store.warehouse,
                "issue_date": TODAY,
                "purpose": "ward use",
                "lines": [{"item_id": item, "quantity": quantity}],
            },
        ),
        201,
    )
    ok(client.post(f"{API}/issues/{created['id']}/submit", headers=store.admin))
    ok(client.post(f"{API}/issues/{created['id']}/approve", headers=store.admin, json={}))
    if not post:
        return created
    return client.post(f"{API}/issues/{created['id']}/post", headers=store.admin)


def journals(shop: Shop, document_type: str, document_id: str) -> list[dict[str, Any]]:
    return list(
        ok(
            client.get(
                f"{API}/journals",
                headers=shop.admin,
                params={"document_type": document_type, "document_id": document_id},
            )
        )
    )


def lines_of(journal: dict[str, Any]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for line in journal["lines"]:
        totals[line["account"]] = (
            totals.get(line["account"], 0) + line["debit_minor"] - line["credit_minor"]
        )
    return totals


# --- lots and expiry (D9) ---------------------------------------------------


def test_lot_flags_are_validated_and_frozen_once_used() -> None:
    shop = Shop()
    expiry_only = client.post(
        f"{API}/items",
        headers=shop.admin,
        json={
            "sku": "X",
            "name": "X",
            "base_unit_id": shop.units["PCS"],
            "track_expiry": True,
        },
    )
    assert expiry_only.status_code == 400
    service = client.post(
        f"{API}/items",
        headers=shop.admin,
        json={
            "sku": "SVC",
            "name": "Cleaning",
            "base_unit_id": shop.units["PCS"],
            "item_type": "service",
            "track_lots": True,
        },
    )
    assert service.status_code == 400

    syrup = lot_item(shop)
    view = shop.item_view(syrup)
    assert view["track_lots"] is True and view["track_expiry"] is True
    # Before any stock moves the flags can still change...
    ok(client.patch(f"{API}/items/{syrup}", headers=shop.admin, json={"track_expiry": False}))
    ok(client.patch(f"{API}/items/{syrup}", headers=shop.admin, json={"track_expiry": True}))
    shop.adjust("opening_balance", [gain(shop, syrup, "5", "L1", in_days(30))])
    # ...afterwards they can't: the lot balances only add up from the start.
    frozen = client.patch(f"{API}/items/{syrup}", headers=shop.admin, json={"track_lots": False})
    assert frozen.status_code == 409
    assert "lot tracking" in frozen.json()["detail"]
    # Renaming is still fine.
    ok(client.patch(f"{API}/items/{syrup}", headers=shop.admin, json={"name": "Cough syrup"}))
    # A plain item refuses lot numbers.
    plain = client.post(
        f"{API}/adjustments",
        headers=shop.admin,
        json={
            "warehouse_id": shop.warehouse,
            "reason": "found",
            "adjustment_date": TODAY,
            "lines": [gain(shop, shop.item, "1", "L1", None)],
        },
    )
    assert plain.status_code == 400
    assert "doesn't track lots" in plain.json()["detail"]


def test_incoming_stock_names_its_lot_and_expiry() -> None:
    store = Store()
    syrup = lot_item(store)

    def draft(line: dict[str, Any]) -> Any:
        return client.post(
            f"{API}/adjustments",
            headers=store.admin,
            json={
                "warehouse_id": store.warehouse,
                "reason": "found",
                "adjustment_date": TODAY,
                "lines": [line],
            },
        )

    assert "enter the lot number" in draft(gain(store, syrup, "1", None, None)).json()["detail"]
    assert "enter its expiry date" in draft(gain(store, syrup, "1", "L1", None)).json()["detail"]
    store.adjust("found", [gain(store, syrup, "4", "L1", in_days(30))])
    # The lot's expiry is fixed when it first arrives.
    clash = draft(gain(store, syrup, "1", "L1", in_days(31)))
    assert clash.status_code == 400
    assert "already recorded" in clash.json()["detail"]
    # Repeating it, or leaving it out, is fine for a known lot.
    store.adjust("found", [gain(store, syrup, "1", "L1", None)])
    assert lots(store, syrup, store.warehouse) == {"L1": Decimal(5)}

    # Goods receipts: the lot is required on accepted stock, created on post.
    po = store.order([{"item_id": syrup, "quantity": "10", "unit_price_minor": 200}])
    line_id = po["lines"][0]["id"]
    missing = client.post(
        f"{API}/goods-receipts",
        headers=store.admin,
        json={
            "purchase_order_id": po["id"],
            "warehouse_id": store.warehouse,
            "receipt_date": TODAY,
            "lines": [{"po_line_id": line_id, "accepted_quantity": "6"}],
        },
    )
    assert missing.status_code == 400
    grn = store.receive(
        po,
        [
            {
                "po_line_id": line_id,
                "accepted_quantity": "6",
                "lot_number": "L2",
                "expiry_date": in_days(90),
            }
        ],
    )
    assert grn["lines"][0]["lot_number"] == "L2"
    assert lots(store, syrup, store.warehouse) == {"L1": Decimal(5), "L2": Decimal(6)}
    movements = ok(
        client.get(f"{API}/movements", headers=store.admin, params={"source_id": grn["id"]})
    )
    assert [m["lot_number"] for m in movements["items"]] == ["L2"]
    assert_projections_match_ledger(store.org_id)


def test_issues_skip_expired_lots_and_write_offs_take_them_first() -> None:
    store = Store()
    syrup = lot_item(store)
    store.adjust(
        "opening_balance",
        [
            gain(store, syrup, "3", "OLD", YESTERDAY),  # already expired
            gain(store, syrup, "4", "SOON", in_days(10)),
            gain(store, syrup, "5", "LATER", in_days(100)),
        ],
    )
    # 6 issued: first-expiry-first-out over the lots still in date.
    assert issue(store, syrup, "6").status_code == 200
    assert lots(store, syrup, store.warehouse) == {"OLD": Decimal(3), "LATER": Decimal(3)}
    # Only 3 usable PCS remain: the expired 3 are never handed out.
    refused = issue(store, syrup, "4")
    assert refused.status_code == 409
    assert "expired" in refused.json()["detail"]

    # An expiry write-off with no lot named takes the expired lot first.
    store.adjust("expiry", [{"item_id": syrup, "quantity": "-3"}])
    assert lots(store, syrup, store.warehouse) == {"LATER": Decimal(3)}
    # Naming a lot takes exactly that lot; an unknown lot is refused.
    unknown = client.post(
        f"{API}/adjustments",
        headers=store.admin,
        json={
            "warehouse_id": store.warehouse,
            "reason": "damage",
            "adjustment_date": TODAY,
            "lines": [{"item_id": syrup, "quantity": "-1", "lot_number": "NOPE"}],
        },
    )
    assert unknown.status_code == 400
    store.adjust("damage", [{"item_id": syrup, "quantity": "-1", "lot_number": "LATER"}])
    assert lots(store, syrup, store.warehouse) == {"LATER": Decimal(2)}
    assert_projections_match_ledger(store.org_id)


def test_transfers_and_reversals_keep_lots_intact() -> None:
    store = Store()
    syrup = lot_item(store)
    store.adjust(
        "opening_balance",
        [gain(store, syrup, "4", "A", in_days(10)), gain(store, syrup, "6", "B", in_days(20))],
    )
    transfer = ok(
        client.post(
            f"{API}/transfers",
            headers=store.admin,
            json={
                "from_warehouse_id": store.warehouse,
                "to_warehouse_id": store.side,
                "transfer_date": TODAY,
                "lines": [{"item_id": syrup, "quantity": "7"}],
            },
        ),
        201,
    )
    dispatched = ok(
        client.post(f"{API}/transfers/{transfer['id']}/dispatch", headers=store.admin, json={})
    )
    assert lots(store, syrup) == {
        "MAIN:B": Decimal(3),
        "IN-TRANSIT:A": Decimal(4),
        "IN-TRANSIT:B": Decimal(3),
    }
    # 6 of 7 arrive: the soonest-expiring lot is received first, and the
    # missing unit is written off from the last.
    ok(
        client.post(
            f"{API}/transfers/{transfer['id']}/receive",
            headers=store.admin,
            json={
                "lines": [{"line_id": dispatched["lines"][0]["id"], "received_quantity_base": "6"}],
                "discrepancy_reason": "one bottle broke",
            },
        )
    )
    assert lots(store, syrup) == {"MAIN:B": Decimal(3), "SIDE:A": Decimal(4), "SIDE:B": Decimal(2)}
    assert_projections_match_ledger(store.org_id)

    # Reversing an adjustment puts back exactly the lots it took.
    damage = store.adjust("damage", [{"item_id": syrup, "quantity": "-2", "lot_number": "B"}])
    assert lots(store, syrup, store.warehouse) == {"B": Decimal(1)}
    ok(
        client.post(
            f"{API}/adjustments/{damage['id']}/reverse",
            headers=store.admin,
            json={"reason": "found behind the shelf"},
        )
    )
    assert lots(store, syrup, store.warehouse) == {"B": Decimal(3)}
    assert_projections_match_ledger(store.org_id)


# --- stocktakes (D6) --------------------------------------------------------


def stocktake(shop: Shop, **extra: Any) -> dict[str, Any]:
    body = {"warehouse_id": shop.warehouse, "count_date": TODAY, **extra}
    return dict(ok(client.post(f"{API}/stocktakes", headers=shop.admin, json=body), 201))


def act(shop: Shop, stocktake_id: str, action: str, **kwargs: Any) -> Any:
    return client.post(f"{API}/stocktakes/{stocktake_id}/{action}", headers=shop.admin, **kwargs)


def count(shop: Shop, take: dict[str, Any], counts: dict[str, str | None]) -> dict[str, Any]:
    """counts: SKU (or SKU:lot) -> counted quantity."""
    by_key = {
        (f"{line['sku']}:{line['lot_number']}" if line["lot_number"] else line["sku"]): line["id"]
        for line in take["lines"]
    }
    body = {"counts": [{"line_id": by_key[k], "counted_quantity": v} for k, v in counts.items()]}
    return dict(
        ok(client.put(f"{API}/stocktakes/{take['id']}/counts", headers=shop.admin, json=body))
    )


def test_stocktake_posts_only_the_variance_against_the_cutoff_snapshot() -> None:
    store = Store()
    store.adjust("opening_balance", [store.line("100", 50)])  # 100 PCS at N0.50
    other = store.add_item("SKU-2")
    store.adjust("opening_balance", [store.line("10", 100, item=other)])

    take = stocktake(store)
    assert take["stocktake_number"] == "STK-000001"
    assert take["status"] == "draft"
    take = ok(act(store, take["id"], "start"))
    assert take["status"] == "counting"
    assert take["cutoff_at"] is not None
    assert [(line["sku"], Decimal(line["expected_quantity"])) for line in take["lines"]] == [
        ("SKU-1", Decimal(100)),
        ("SKU-2", Decimal(10)),
    ]

    # Business carries on after the cutoff: 30 PCS are issued.
    assert issue(store, store.item, "30").status_code == 200

    take = count(store, take, {"SKU-1": "97"})
    assert take["counted_count"] == 1
    uncounted = act(store, take["id"], "submit")
    assert uncounted.status_code == 400
    assert "aren't counted" in uncounted.json()["detail"]
    take = count(store, take, {"SKU-2": "10"})
    assert take["needs_approval"] is True  # stock is missing
    line = next(line for line in take["lines"] if line["sku"] == "SKU-1")
    assert Decimal(line["variance"]) == -3
    assert line["variance_value_minor"] == -150

    take = ok(act(store, take["id"], "submit"))
    assert take["status"] == "pending_approval"
    instance = ok(
        client.get(f"/api/v1/approval-instances/stocktake/{take['id']}", headers=store.admin)
    )
    assert instance is not None
    early = act(store, take["id"], "post")
    assert early.status_code == 409
    take = ok(act(store, take["id"], "approve", json={"comment": "3 PCS damaged"}))
    assert take["status"] == "approved"
    take = ok(act(store, take["id"], "post"))
    assert take["status"] == "posted"

    # 100 - 30 issued after the cutoff - 3 missing at the count = 67: the
    # issue isn't overwritten by the count.
    assert stock_by_warehouse(store) == {"MAIN": Decimal(67)}
    assert take["loss_value_minor"] == 150
    [journal] = journals(store, "stocktake", take["id"])
    assert lines_of(journal) == {"inventory": -150, "inventory_adjustment": 150}
    movements = ok(
        client.get(f"{API}/movements", headers=store.admin, params={"source_id": take["id"]})
    )
    assert [(m["source_number"], m["movement_type"]) for m in movements["items"]] == [
        ("STK-000001", "adjustment_loss")
    ]
    assert_projections_match_ledger(store.org_id)

    # Posted is final.
    assert act(store, take["id"], "cancel").status_code == 409
    assert client.delete(f"{API}/stocktakes/{take['id']}", headers=store.admin).status_code == 409


def test_stocktake_gains_are_valued_and_follow_the_approval_limit() -> None:
    store = Store()
    store.adjust("opening_balance", [store.line("10", 200)])  # average N2
    uncosted = store.add_item("NEW")
    ok(
        client.put(
            f"{API}/settings",
            headers=store.admin,
            json={"adjustment_gain_approval_limit_minor": 1_000},
        )
    )

    take = ok(act(store, stocktake(store)["id"], "start"))
    take = count(store, take, {"SKU-1": "12"})
    assert take["needs_approval"] is False  # N4 found, under the N10 limit
    # Found stock of an item the books don't list here: added at expected 0.
    added = client.post(
        f"{API}/stocktakes/{take['id']}/lines",
        headers=store.admin,
        json={"item_id": uncosted, "counted_quantity": "2"},
    )
    take = ok(added, 201)
    assert take["lines"][-1]["added_during_count"] is True
    # It has no average and no default cost, so it can't be valued.
    refused = act(store, take["id"], "submit")
    assert refused.status_code == 400
    assert "default cost" in refused.json()["detail"]
    ok(
        client.patch(
            f"{API}/items/{uncosted}", headers=store.admin, json={"default_cost_minor": 450}
        )
    )
    take = ok(client.get(f"{API}/stocktakes/{take['id']}", headers=store.admin))
    assert take["needs_approval"] is True  # N4 + N9 = N13, over the N10 limit
    take = ok(act(store, take["id"], "submit"))
    assert take["status"] == "pending_approval"
    ok(act(store, take["id"], "approve", json={}))
    take = ok(act(store, take["id"], "post"))
    assert take["gain_value_minor"] == 400 + 900
    [journal] = journals(store, "stocktake", take["id"])
    assert lines_of(journal) == {"inventory": 1_300, "inventory_adjustment": -1_300}

    # With no variance at all, a count is approved at once and posts nothing.
    clean = ok(act(store, stocktake(store)["id"], "start"))
    clean = count(store, clean, {"SKU-1": "12", "NEW": "2"})
    clean = ok(act(store, clean["id"], "submit"))
    assert clean["status"] == "approved"
    clean = ok(act(store, clean["id"], "post"))
    assert clean["status"] == "posted"
    assert journals(store, "stocktake", clean["id"]) == []
    assert_projections_match_ledger(store.org_id)


def test_stocktake_counts_lots_and_records_found_lots() -> None:
    store = Store()
    syrup = lot_item(store)
    medicine = ok(
        client.post(f"{API}/categories", headers=store.admin, json={"name": "Medicine"}), 201
    )
    ok(
        client.patch(
            f"{API}/items/{syrup}", headers=store.admin, json={"category_id": medicine["id"]}
        )
    )
    store.adjust(
        "opening_balance",
        [gain(store, syrup, "4", "A", in_days(10)), gain(store, syrup, "6", "B", in_days(20))],
    )
    store.adjust("opening_balance", [store.line("5", 100)])  # uncategorised

    take = ok(act(store, stocktake(store, category_id=medicine["id"])["id"], "start"))
    assert [(line["lot_number"], Decimal(line["expected_quantity"])) for line in take["lines"]] == [
        ("A", Decimal(4)),
        ("B", Decimal(6)),
    ]
    # The paper is outside the Medicine scope.
    outside = client.post(
        f"{API}/stocktakes/{take['id']}/lines",
        headers=store.admin,
        json={"item_id": store.item, "counted_quantity": "1"},
    )
    assert outside.status_code == 400
    # A found lot needs its number and, being new, its expiry date.
    no_expiry = client.post(
        f"{API}/stocktakes/{take['id']}/lines",
        headers=store.admin,
        json={"item_id": syrup, "counted_quantity": "2", "lot_number": "C"},
    )
    assert no_expiry.status_code == 400
    take = ok(
        client.post(
            f"{API}/stocktakes/{take['id']}/lines",
            headers=store.admin,
            json={
                "item_id": syrup,
                "counted_quantity": "2",
                "lot_number": "C",
                "expiry_date": in_days(30),
            },
        ),
        201,
    )
    duplicate = client.post(
        f"{API}/stocktakes/{take['id']}/lines",
        headers=store.admin,
        json={"item_id": syrup, "counted_quantity": "1", "lot_number": "A"},
    )
    assert duplicate.status_code == 409
    snapshot_line = take["lines"][0]["id"]
    kept = client.delete(
        f"{API}/stocktakes/{take['id']}/lines/{snapshot_line}", headers=store.admin
    )
    assert kept.status_code == 400

    take = count(store, take, {"SYRUP:A": "4", "SYRUP:B": "5"})
    ok(act(store, take["id"], "submit"))
    ok(act(store, take["id"], "approve", json={}))
    ok(act(store, take["id"], "post"))
    assert lots(store, syrup, store.warehouse) == {
        "A": Decimal(4),
        "B": Decimal(5),
        "C": Decimal(2),
    }
    assert_projections_match_ledger(store.org_id)


def test_stocktake_respects_the_lock_date_and_can_be_cancelled() -> None:
    store = Store()
    store.adjust("opening_balance", [store.line("10", 100)])
    take = stocktake(store, count_date=YESTERDAY)
    ok(
        client.patch(
            "/api/v1/accounting-settings", headers=store.admin, json={"lock_date": YESTERDAY}
        )
    )
    locked = act(store, take["id"], "start")
    assert locked.status_code == 400
    assert "locked period" in locked.json()["detail"]
    future = client.post(
        f"{API}/stocktakes",
        headers=store.admin,
        json={"warehouse_id": store.warehouse, "count_date": in_days(1)},
    )
    assert future.status_code == 400
    cancelled = ok(act(store, take["id"], "cancel"))
    assert cancelled["status"] == "cancelled"
    # Rejected counts are final too.
    rejected = ok(act(store, stocktake(store)["id"], "start"))
    rejected = count(store, rejected, {"SKU-1": "9"})
    ok(act(store, rejected["id"], "submit"))
    rejected = ok(act(store, rejected["id"], "reject", json={"comment": "recount"}))
    assert rejected["status"] == "rejected"
    assert act(store, rejected["id"], "post").status_code == 409
    assert stock_by_warehouse(store) == {"MAIN": Decimal(10)}


def test_stocktake_permissions_and_hidden_values() -> None:
    store = Store()
    store.adjust("opening_balance", [store.line("10", 100)])
    auditor = headers_for(store.org_id, Role.AUDITOR)
    hr = headers_for(store.org_id, Role.HR_MANAGER)
    body = {"warehouse_id": store.warehouse, "count_date": TODAY}
    assert client.post(f"{API}/stocktakes", headers=auditor, json=body).status_code == 403
    assert client.get(f"{API}/stocktakes", headers=hr).status_code == 403

    take = ok(act(store, stocktake(store)["id"], "start"))
    take = count(store, take, {"SKU-1": "8"})
    ok(act(store, take["id"], "submit"))
    assert (
        client.post(f"{API}/stocktakes/{take['id']}/approve", headers=auditor, json={}).status_code
        == 403
    )

    # inventory.view without inventory.valuation: counts yes, values no.
    email = f"keeper-{uuid.uuid4()}@example.com"
    account = create_account_with_membership(store.org_id, Role.ACCOUNTANT, email=email)
    ok(
        client.put(
            f"/api/v1/memberships/{get_membership_id(store.org_id, account)}/permissions/override",
            headers=store.admin,
            json={"permission": "inventory.valuation", "granted": False},
        )
    )
    keeper = auth_headers(login(email)["access_token"])
    seen = ok(client.get(f"{API}/stocktakes/{take['id']}", headers=keeper))
    assert Decimal(seen["lines"][0]["variance"]) == -2
    assert seen["lines"][0]["variance_value_minor"] is None
    assert seen["loss_value_minor"] is None
    assert client.get(f"{API}/reports/valuation", headers=keeper).status_code == 403
    movements = ok(
        client.get(
            f"{API}/reports/movements",
            headers=keeper,
            params={"date_from": TODAY, "date_to": TODAY},
        )
    )
    assert movements["rows"][0]["closing_value_minor"] is None


def test_a_posting_holds_its_warehouse_against_a_snapshot_until_it_commits() -> None:
    """The cutoff lock (D6): while a posting is in flight in a warehouse, a
    stocktake can't take its snapshot there; other postings aren't held up."""
    store = Store()
    draft = store.adjust("opening_balance", [store.line("5", 100)], post=False)
    posted, release = threading.Event(), threading.Event()

    def post() -> None:
        with tenant_session(store.org_id, uuid.uuid4(), "admin") as db:
            post_adjustment(db, uuid.UUID(draft["id"]), actor_account_id=None)
            posted.set()
            release.wait(10)

    worker = threading.Thread(target=post)
    worker.start()
    key = {"c": _WAREHOUSE_LOCK_CLASS, "k": _warehouse_lock_key(uuid.UUID(store.warehouse))}
    try:
        assert posted.wait(10)
        with get_engine().connect() as snapshot:
            exclusive = "SELECT pg_try_advisory_xact_lock(:c, :k)"
            assert snapshot.execute(text(exclusive), key).scalar() is False
            shared = "SELECT pg_try_advisory_xact_lock_shared(:c, :k)"
            assert snapshot.execute(text(shared), key).scalar() is True
            snapshot.rollback()
    finally:
        release.set()
        worker.join()
    with get_engine().connect() as snapshot:
        assert snapshot.execute(text(exclusive), key).scalar() is True
        snapshot.rollback()
    assert stock_by_warehouse(store) == {"MAIN": Decimal(5)}


# --- reorder ----------------------------------------------------------------


def test_reorder_suggestions_count_stock_on_order_and_ignore_expired() -> None:
    store = Store()
    ok(
        client.patch(
            f"{API}/items/{store.item}",
            headers=store.admin,
            json={"reorder_level": "20", "max_level": "50", "preferred_vendor_id": store.vendor},
        )
    )
    syrup = lot_item(store, reorder_level="10")
    store.adjust("opening_balance", [store.line("5", 100)])
    store.adjust(
        "opening_balance",
        [gain(store, syrup, "8", "OLD", YESTERDAY), gain(store, syrup, "4", "NEW", in_days(60))],
    )
    rows = {r["sku"]: r for r in ok(client.get(f"{API}/reorder-suggestions", headers=store.admin))}
    assert Decimal(rows["SKU-1"]["suggested_quantity"]) == 45  # up to max 50
    assert rows["SKU-1"]["preferred_vendor_name"] == "Acme"
    # 12 on hand but 8 expired: 4 usable, so 6 to reach the reorder level.
    assert Decimal(rows["SYRUP"]["expired"]) == 8
    assert Decimal(rows["SYRUP"]["suggested_quantity"]) == 6

    # A box (10 PCS) on order at N30: on order counts as available.
    store.order(
        [
            {
                "item_id": store.item,
                "unit_id": store.units["BOX"],
                "quantity": "1",
                "unit_price_minor": 3_000,
            }
        ]
    )
    rows = {r["sku"]: r for r in ok(client.get(f"{API}/reorder-suggestions", headers=store.admin))}
    assert Decimal(rows["SKU-1"]["on_order"]) == 10
    assert Decimal(rows["SKU-1"]["suggested_quantity"]) == 35
    assert rows["SKU-1"]["last_unit_cost_minor"] == 300  # N30 a box of 10
    assert rows["SKU-1"]["estimated_cost_minor"] == 10_500
    # Another two boxes lift it above its reorder level: no longer suggested.
    store.order(
        [
            {
                "item_id": store.item,
                "unit_id": store.units["BOX"],
                "quantity": "2",
                "unit_price_minor": 3_000,
            }
        ]
    )
    rows = {r["sku"]: r for r in ok(client.get(f"{API}/reorder-suggestions", headers=store.admin))}
    assert "SKU-1" not in rows
    csv_file = client.get(
        f"{API}/reorder-suggestions", headers=store.admin, params={"format": "csv"}
    )
    assert csv_file.status_code == 200
    assert "SYRUP,Item SYRUP" in csv_file.content.decode("utf-8-sig")


# --- reports ----------------------------------------------------------------


def report(shop: Shop, name: str, **params: Any) -> Any:
    return ok(client.get(f"{API}/reports/{name}", headers=shop.admin, params=params))


def test_report_totals_reconcile_to_the_ledger() -> None:
    """The Phase 4 exit criterion: valuation, movement and variance totals
    agree with the movement ledger and with the GL inventory account."""
    store = Store()
    syrup = lot_item(store)
    # Yesterday: opening stock (backdated).
    body = {
        "warehouse_id": store.warehouse,
        "reason": "opening_balance",
        "adjustment_date": YESTERDAY,
        "lines": [store.line("40", 250), gain(store, syrup, "10", "A", in_days(5), cost=1_000)],
    }
    opening = ok(client.post(f"{API}/adjustments", headers=store.admin, json=body), 201)
    ok(client.post(f"{API}/adjustments/{opening['id']}/post", headers=store.admin))
    # Today: a receipt, an issue, a transfer, a damage write-off and a count.
    po = store.order([{"item_id": store.item, "quantity": "20", "unit_price_minor": 400}])
    store.receive(po, [{"po_line_id": po["lines"][0]["id"], "accepted_quantity": "20"}])
    assert issue(store, store.item, "15").status_code == 200
    transfer = ok(
        client.post(
            f"{API}/transfers",
            headers=store.admin,
            json={
                "from_warehouse_id": store.warehouse,
                "to_warehouse_id": store.side,
                "transfer_date": TODAY,
                "lines": [{"item_id": syrup, "quantity": "4"}],
            },
        ),
        201,
    )
    ok(client.post(f"{API}/transfers/{transfer['id']}/dispatch", headers=store.admin, json={}))
    store.adjust("damage", [store.line("-2")])
    take = ok(act(store, stocktake(store)["id"], "start"))
    take = count(store, take, {"SKU-1": "42", "SYRUP:A": "6"})
    ok(act(store, take["id"], "submit"))
    ok(act(store, take["id"], "approve", json={}))
    ok(act(store, take["id"], "post"))

    # Valuation: today, and yesterday from the ledger as it stood then.
    now = report(store, "valuation")
    assert now["gl_balance_minor"] is not None
    assert now["difference_minor"] == 0
    assert now["total_value_minor"] == store.value() + store.value(syrup)
    then = report(store, "valuation", as_of=YESTERDAY)
    assert then["total_value_minor"] == 40 * 250 + 10 * 1_000
    assert then["difference_minor"] == 0
    split = report(store, "valuation", by_warehouse="true")
    assert split["total_value_minor"] == now["total_value_minor"]
    assert {r["warehouse_code"] for r in split["rows"]} == {"MAIN", "IN-TRANSIT"}

    # Movements: opening + movements = closing = today's valuation, per item.
    summary = report(store, "movements", date_from=TODAY, date_to=TODAY)
    rows = {r["sku"]: r for r in summary["rows"]}
    paper = rows["SKU-1"]
    assert Decimal(paper["opening_quantity"]) == 40
    assert Decimal(paper["received"]) == 20
    assert Decimal(paper["issued"]) == -15
    assert Decimal(paper["adjusted"]) == -2 - 1  # damage, then 1 missing at the count
    assert Decimal(paper["closing_quantity"]) == 42
    valued = {r["sku"]: r for r in now["rows"]}
    for sku, row in rows.items():
        assert Decimal(row["closing_quantity"]) == Decimal(valued[sku]["quantity"])
        assert row["closing_value_minor"] == valued[sku]["value_minor"]
    assert sum(r["closing_value_minor"] for r in summary["rows"]) == now["total_value_minor"]

    # Variances: every adjustment and count movement in the period, and its
    # net equals what reached inventory_adjustment in the GL.
    variances = report(store, "variances", date_from=TODAY, date_to=TODAY)
    assert {r["source_number"] for r in variances["rows"]} == {"ADJ-000002", "STK-000001"}
    net = sum(r["value_minor"] for r in variances["rows"])
    assert net == variances["gain_value_minor"] - variances["loss_value_minor"]
    ledger = ok(client.get("/api/v1/general-ledger/trial-balance", headers=store.admin))
    adjustment_account = next(
        line["balance_minor"] for line in ledger if line["account"] == "inventory_adjustment"
    )
    assert adjustment_account == -net
    assert_projections_match_ledger(store.org_id)


def test_expiry_and_outstanding_order_reports() -> None:
    store = Store()
    syrup = lot_item(store)
    store.adjust(
        "opening_balance",
        [
            gain(store, syrup, "2", "GONE", YESTERDAY, cost=500),
            gain(store, syrup, "3", "SOON", in_days(20), cost=500),
            gain(store, syrup, "4", "FAR", in_days(200), cost=500),
        ],
    )
    expiry = report(store, "expiry", within_days=30)
    assert [(r["lot_number"], r["expired"]) for r in expiry["rows"]] == [
        ("GONE", True),
        ("SOON", False),
    ]
    assert expiry["expired_value_minor"] == 1_000
    assert expiry["expiring_value_minor"] == 1_500

    po = store.order([{"item_id": store.item, "quantity": "10", "unit_price_minor": 300}])
    store.receive(po, [{"po_line_id": po["lines"][0]["id"], "accepted_quantity": "4"}])
    outstanding = report(store, "outstanding-orders")
    [row] = outstanding["rows"]
    assert Decimal(row["outstanding"]) == 6
    assert row["outstanding_value_minor"] == 1_800
    assert outstanding["total_value_minor"] == 1_800


def test_reports_export_as_csv_and_pdf() -> None:
    store = Store()
    tricky = store.add_item("=SUM(A1)")
    store.adjust("opening_balance", [store.line("3", 1_234_567, item=tricky)])
    as_csv = client.get(f"{API}/reports/valuation", headers=store.admin, params={"format": "csv"})
    assert as_csv.status_code == 200
    assert as_csv.headers["content-type"].startswith("text/csv")
    assert 'filename="stock-valuation-' in as_csv.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(as_csv.content.decode("utf-8-sig"))))
    assert rows[0] == ["Stock valuation"]
    body = [row for row in rows if row and row[0] == "'=SUM(A1)"]
    assert body, rows  # a formula-looking SKU is neutralised
    assert body[0][-1] == "37,037.01"
    assert ["Total stock value", "", "", "", "", "", "37,037.01"] in rows

    for name, params in [
        ("valuation", {}),
        ("movements", {"date_from": TODAY, "date_to": TODAY}),
        ("variances", {"date_from": TODAY, "date_to": TODAY}),
        ("expiry", {}),
        ("outstanding-orders", {}),
    ]:
        pdf = client.get(
            f"{API}/reports/{name}", headers=store.admin, params={**params, "format": "pdf"}
        )
        assert pdf.status_code == 200, (name, pdf.text)
        assert pdf.headers["content-type"] == "application/pdf"
        assert pdf.content.startswith(b"%PDF")

    take = ok(act(store, stocktake(store)["id"], "start"))
    sheet = client.get(
        f"{API}/stocktakes/{take['id']}/export", headers=store.admin, params={"format": "pdf"}
    )
    assert sheet.status_code == 200 and sheet.content.startswith(b"%PDF")
    events = ok(
        client.get(
            "/api/v1/audit-log",
            headers=store.admin,
            params={"action": "inventory_report.export"},
        )
    )
    assert events
