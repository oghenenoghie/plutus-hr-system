"""Inventory Phase 1 end to end: settings, master data, adjustments posted to
the stock ledger, reversal, negative-stock protection, permissions, tenant
isolation and concurrent posting."""

import threading
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.db import SESSION_ORG_KEY, tenant_session
from app.domain.inventory.costing import InsufficientStockError
from app.models import Role
from app.models.audit_log import AuditLog
from app.models.inventory import (
    InventoryAdjustmentReason,
    InventoryStockMovement,
)
from app.schemas.inventory import AdjustmentCreate, AdjustmentLineIn
from app.services import inventory_queries
from app.services.inventory import InventoryNotFound, get_item
from app.services.inventory_adjustments import create_adjustment, post_adjustment
from app.services.posting import today_lagos
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_org,
    get_membership_id,
    login,
)
from tests.integration.conftest import ADMIN_DATABASE_URL
from tests.integration.inventory_helpers import (
    API,
    TODAY,
    Shop,
    assert_projections_match_ledger,
    headers_for,
    ok,
    stock_by_warehouse,
)

# --- settings ---------------------------------------------------------------


def test_module_is_off_until_enabled_and_enabling_seeds_units() -> None:
    org_id = create_org()
    admin = headers_for(org_id, Role.ADMIN)

    settings = ok(client.get(f"{API}/settings", headers=admin))
    # A new organisation posts to the GL from its first document (Phase 3).
    assert settings.pop("gl_started_at") is not None
    assert settings == {
        "enabled": False,
        "costing_method": "weighted_average",
        "over_receipt_tolerance_bp": 0,
        "adjustment_gain_approval_limit_minor": None,
        "require_issue_approval": True,
        "require_transfer_approval": False,
        "post_to_gl": True,
    }
    assert client.get(f"{API}/items", headers=admin).status_code == 409
    summary = ok(client.get(f"{API}/summary", headers=admin))
    assert summary["enabled"] is False and summary["tracked_items"] == 0

    ok(client.put(f"{API}/settings", headers=admin, json={"enabled": True}))
    ok(client.put(f"{API}/settings", headers=admin, json={"enabled": True}))  # idempotent
    codes = [unit["code"] for unit in ok(client.get(f"{API}/units", headers=admin))]
    assert codes == ["BOX", "KG", "L", "M", "PCS"]

    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        actions = list(
            db.scalars(select(AuditLog.action).where(AuditLog.entity_type == "inventory_settings"))
        )
    assert actions == ["inventory_settings.update", "inventory_settings.update"]


# --- master data ------------------------------------------------------------


def test_master_data_rules() -> None:
    shop = Shop()
    admin = shop.admin

    duplicate = client.post(
        f"{API}/items",
        headers=admin,
        json={"sku": "SKU-1", "name": "Again", "base_unit_id": shop.units["PCS"]},
    )
    assert duplicate.status_code == 409

    bad_levels = client.post(
        f"{API}/items",
        headers=admin,
        json={
            "sku": "SKU-2",
            "name": "Levels",
            "base_unit_id": shop.units["PCS"],
            "reorder_level": "10",
            "max_level": "5",
        },
    )
    assert bad_levels.status_code == 400

    parent = ok(client.post(f"{API}/categories", headers=admin, json={"name": "Stationery"}), 201)
    child = ok(
        client.post(
            f"{API}/categories", headers=admin, json={"name": "Paper", "parent_id": parent["id"]}
        ),
        201,
    )
    cycle = client.patch(
        f"{API}/categories/{parent['id']}", headers=admin, json={"parent_id": child["id"]}
    )
    assert cycle.status_code == 400

    # A carton of 24 pieces; the base unit can't double as an alternative.
    units = client.put(
        f"{API}/items/{shop.item}/units",
        headers=admin,
        json={"units": [{"unit_id": shop.units["BOX"], "factor_to_base": "24"}]},
    )
    item = ok(units)
    assert [(u["unit_code"], Decimal(u["factor_to_base"])) for u in item["units"]] == [
        ("BOX", Decimal(24))
    ]
    clash = client.put(
        f"{API}/items/{shop.item}/units",
        headers=admin,
        json={"units": [{"unit_id": shop.units["PCS"], "factor_to_base": "1"}]},
    )
    assert clash.status_code == 400

    # Once stock has moved, the item's type and base unit are frozen, and so
    # is whether its unit allows fractions.
    shop.adjust("opening_balance", [shop.line("5", 100)])
    frozen = client.patch(
        f"{API}/items/{shop.item}", headers=admin, json={"base_unit_id": shop.units["KG"]}
    )
    assert frozen.status_code == 409
    renamed = client.patch(f"{API}/items/{shop.item}", headers=admin, json={"name": "Renamed"})
    assert ok(renamed)["name"] == "Renamed"
    fraction = client.patch(
        f"{API}/units/{shop.units['PCS']}", headers=admin, json={"allows_fraction": True}
    )
    assert fraction.status_code == 409

    # A warehouse holding stock can't be deactivated.
    deactivate = client.patch(
        f"{API}/warehouses/{shop.warehouse}", headers=admin, json={"is_active": False}
    )
    assert deactivate.status_code == 409


# --- posting ----------------------------------------------------------------


def test_adjustments_move_stock_at_weighted_average_and_reverse_cleanly() -> None:
    shop = Shop()

    opening = shop.adjust("opening_balance", [shop.line("10", 100_00)])
    assert opening["adjustment_number"] == "ADJ-000001"
    assert opening["status"] == "posted"
    assert opening["value_minor"] == 1_000_00

    found = shop.adjust("found", [shop.line("30", 200_00)])
    assert found["adjustment_number"] == "ADJ-000002"
    item = shop.item_view()
    assert Decimal(item["quantity_on_hand"]) == 40
    assert item["value_minor"] == 7_000_00
    assert item["average_cost_minor"] == 175_00

    loss = shop.adjust("loss", [shop.line("-4")])
    assert loss["value_minor"] == -700_00  # 4 x the N175 average
    assert stock_by_warehouse(shop) == {"MAIN": Decimal(36)}

    # Posting is one-way: a posted document can't be posted, edited or
    # deleted again.
    assert (
        client.post(f"{API}/adjustments/{loss['id']}/post", headers=shop.admin).status_code == 409
    )
    assert client.delete(f"{API}/adjustments/{loss['id']}", headers=shop.admin).status_code == 409

    reversed_ = ok(
        client.post(
            f"{API}/adjustments/{loss['id']}/reverse",
            headers=shop.admin,
            json={"reason": "count error"},
        )
    )
    assert reversed_["status"] == "reversed"
    assert reversed_["reversal_reason"] == "count error"
    item = shop.item_view()
    assert Decimal(item["quantity_on_hand"]) == 40
    assert item["value_minor"] == 7_000_00  # the loss came back at the value it left at
    again = client.post(
        f"{API}/adjustments/{loss['id']}/reverse", headers=shop.admin, json={"reason": "twice"}
    )
    assert again.status_code == 409

    movements = ok(client.get(f"{API}/movements", headers=shop.admin))
    assert movements["total"] == 4
    reversal = movements["items"][0]
    assert reversal["movement_type"] == "reversal"
    assert reversal["source_number"] == loss["adjustment_number"]
    assert Decimal(reversal["quantity"]) == 4 and reversal["value_minor"] == 700_00

    assert_projections_match_ledger(shop.org_id)


def test_unit_conversion_and_whole_number_rules() -> None:
    shop = Shop()
    ok(
        client.put(
            f"{API}/items/{shop.item}/units",
            headers=shop.admin,
            json={"units": [{"unit_id": shop.units["BOX"], "factor_to_base": "24"}]},
        )
    )
    # 2 cartons at N2,400 each = 48 pieces worth N4,800.
    shop.adjust("opening_balance", [{**shop.line("2", 2_400_00), "unit_id": shop.units["BOX"]}])
    item = shop.item_view()
    assert Decimal(item["quantity_on_hand"]) == 48
    assert item["value_minor"] == 4_800_00
    assert item["average_cost_minor"] == 100_00

    half = client.post(
        f"{API}/adjustments",
        headers=shop.admin,
        json={
            "warehouse_id": shop.warehouse,
            "reason": "damage",
            "adjustment_date": TODAY,
            "lines": [shop.line("-0.5")],
        },
    )
    assert half.status_code == 400
    assert "PCS does not allow fractional" in half.json()["detail"]

    # A KG item takes fractions; a decrease must not carry a cost.
    flour = shop.add_item("FLOUR", base_unit_id=shop.units["KG"], default_cost_minor=50_00)
    shop.adjust("opening_balance", [shop.line("12.5", item=flour)])  # default cost applies
    assert shop.item_view(flour)["value_minor"] == 625_00
    priced_decrease = client.post(
        f"{API}/adjustments",
        headers=shop.admin,
        json={
            "warehouse_id": shop.warehouse,
            "reason": "correction",
            "adjustment_date": TODAY,
            "lines": [shop.line("-1", 50_00, item=flour)],
        },
    )
    assert priced_decrease.status_code == 400


def test_reason_direction_cost_and_date_rules() -> None:
    shop = Shop()

    def attempt(reason: str, line: dict[str, Any], day: str = TODAY) -> int:
        return int(
            client.post(
                f"{API}/adjustments",
                headers=shop.admin,
                json={
                    "warehouse_id": shop.warehouse,
                    "reason": reason,
                    "adjustment_date": day,
                    "lines": [line],
                },
            ).status_code
        )

    assert attempt("damage", shop.line("3", 100)) == 400  # damage only removes
    assert attempt("opening_balance", shop.line("-3")) == 400  # opening only adds
    assert attempt("found", shop.line("3")) == 400  # no cost and no default cost
    tomorrow = (today_lagos() + timedelta(days=1)).isoformat()
    assert attempt("found", shop.line("3", 100), tomorrow) == 400
    assert attempt("found", shop.line("0", 100)) == 400

    service = shop.add_item("SVC", item_type="service")
    assert attempt("found", shop.line("1", 100, item=service)) == 400


def test_stock_can_never_go_negative() -> None:
    shop = Shop()
    second = shop.add_warehouse("SIDE")
    shop.adjust("opening_balance", [shop.line("5", 100)])
    shop.adjust("opening_balance", [shop.line("5", 100)], warehouse=second)

    # 10 on hand across both warehouses, but only 5 in MAIN.
    draft = shop.adjust("loss", [shop.line("-6")], post=False)
    shop.approve_adjustment(draft["id"])
    refused = client.post(f"{API}/adjustments/{draft['id']}/post", headers=shop.admin)
    assert refused.status_code == 409
    assert "not enough SKU-1 in MAIN: 5 PCS available, 6 PCS needed" in refused.json()["detail"]

    # Nothing was written and the adjustment is still waiting to be posted.
    assert stock_by_warehouse(shop) == {"MAIN": Decimal(5), "SIDE": Decimal(5)}
    detail = ok(client.get(f"{API}/adjustments/{draft['id']}", headers=shop.admin))
    assert detail["status"] == "approved"
    assert_projections_match_ledger(shop.org_id)


def test_reversal_refused_when_the_stock_it_added_has_been_used() -> None:
    shop = Shop()
    opening = shop.adjust("opening_balance", [shop.line("5", 100)])
    shop.adjust("write_off", [shop.line("-3")])
    refused = client.post(
        f"{API}/adjustments/{opening['id']}/reverse", headers=shop.admin, json={"reason": "oops"}
    )
    assert refused.status_code == 409
    assert stock_by_warehouse(shop) == {"MAIN": Decimal(2)}


def test_drafts_can_be_edited_and_deleted() -> None:
    shop = Shop()
    draft = shop.adjust("found", [shop.line("2", 100)], post=False)
    assert draft["status"] == "draft" and draft["line_count"] == 1
    assert stock_by_warehouse(shop) == {}

    edited = ok(
        client.put(
            f"{API}/adjustments/{draft['id']}",
            headers=shop.admin,
            json={
                "warehouse_id": shop.warehouse,
                "reason": "found",
                "adjustment_date": TODAY,
                "lines": [shop.line("3", 100), shop.line("4", 50, item=shop.add_item("SKU-9"))],
            },
        )
    )
    assert edited["line_count"] == 2
    assert [Decimal(line["quantity"]) for line in edited["lines"]] == [3, 4]

    ok(client.delete(f"{API}/adjustments/{draft['id']}", headers=shop.admin), 204)
    assert client.get(f"{API}/adjustments/{draft['id']}", headers=shop.admin).status_code == 404


def test_summary_counts_and_lowstock_by_warehouse() -> None:
    shop = Shop()
    low = shop.add_item("LOW", reorder_level="10")
    shop.add_item("EMPTY")
    shop.adjust("opening_balance", [shop.line("50", 10), shop.line("4", 10, item=low)])
    shop.adjust("found", [shop.line("1", 10)], post=False)

    summary = ok(client.get(f"{API}/summary", headers=shop.admin))
    assert summary["enabled"] is True
    assert summary["tracked_items"] == 3
    assert summary["out_of_stock"] == 1
    assert summary["low_stock"] == 1
    assert summary["active_warehouses"] == 1
    assert summary["draft_adjustments"] == 1
    assert summary["total_value_minor"] == 540
    assert len(summary["recent_movements"]) == 2


def test_movement_pages_join_up_newest_first() -> None:
    """The list is newest first by entry date, then posting time; its pages
    join up into exactly that list. The overview's feed is by posting time,
    so a backdated document still shows there first. (Both pick their page
    before joining items and warehouses, Phase 5.)"""
    shop = Shop()
    today = date.fromisoformat(TODAY)
    # Posted in this order, dated today, 3, 1, 3 and 2 days ago.
    for days_ago, quantity in ((0, "1"), (3, "2"), (1, "3"), (3, "4"), (2, "5")):
        body = {
            "warehouse_id": shop.warehouse,
            "reason": "opening_balance",
            "adjustment_date": (today - timedelta(days=days_ago)).isoformat(),
            "lines": [shop.line(quantity, 100)],
        }
        created = ok(client.post(f"{API}/adjustments", headers=shop.admin, json=body), 201)
        ok(client.post(f"{API}/adjustments/{created['id']}/post", headers=shop.admin))

    everything = ok(client.get(f"{API}/movements", headers=shop.admin))
    assert everything["total"] == 5
    assert [Decimal(m["quantity"]) for m in everything["items"]] == [1, 3, 5, 4, 2]
    assert {m["sku"] for m in everything["items"]} == {"SKU-1"}
    pages = [
        ok(client.get(f"{API}/movements", headers=shop.admin, params={"limit": 2, "offset": n}))
        for n in (0, 2, 4)
    ]
    assert [page["total"] for page in pages] == [5, 5, 5]
    assert [len(page["items"]) for page in pages] == [2, 2, 1]
    assert [m["id"] for page in pages for m in page["items"]] == [
        m["id"] for m in everything["items"]
    ]

    recent = ok(client.get(f"{API}/summary", headers=shop.admin))["recent_movements"]
    assert [Decimal(m["quantity"]) for m in recent] == [5, 4, 3, 2, 1]


# --- permissions ------------------------------------------------------------


def test_permissions_gate_reads_writes_and_values() -> None:
    shop = Shop()
    shop.adjust("opening_balance", [shop.line("10", 100)])

    employee = headers_for(shop.org_id, Role.EMPLOYEE)
    hr_manager = headers_for(shop.org_id, Role.HR_MANAGER)
    for headers in (employee, hr_manager):
        assert client.get(f"{API}/items", headers=headers).status_code == 403
        assert client.get(f"{API}/summary", headers=headers).status_code == 403

    # The auditor reads everything, values included, but changes nothing.
    auditor = headers_for(shop.org_id, Role.AUDITOR)
    assert shop.item_view() == ok(client.get(f"{API}/items/{shop.item}", headers=auditor))
    assert (
        client.post(
            f"{API}/warehouses", headers=auditor, json={"code": "X", "name": "X"}
        ).status_code
        == 403
    )
    assert (
        client.put(f"{API}/settings", headers=auditor, json={"enabled": False}).status_code == 403
    )
    assert (
        client.post(
            f"{API}/adjustments",
            headers=auditor,
            json={
                "warehouse_id": shop.warehouse,
                "reason": "found",
                "adjustment_date": TODAY,
                "lines": [shop.line("1", 1)],
            },
        ).status_code
        == 403
    )

    # The accountant adjusts stock.
    accountant = headers_for(shop.org_id, Role.ACCOUNTANT)
    posted = shop.adjust("found", [shop.line("1", 100)], headers=accountant)
    assert posted["status"] == "posted"

    # Revoking inventory.valuation hides values and costs but not quantities.
    email = f"viewer-{uuid.uuid4()}@example.com"
    viewer_id = create_account_with_membership(shop.org_id, Role.PAYROLL_MANAGER, email=email)
    membership_id = get_membership_id(shop.org_id, viewer_id)
    ok(
        client.put(
            f"/api/v1/memberships/{membership_id}/permissions/override",
            headers=shop.admin,
            json={"permission": "inventory.valuation", "granted": False},
        )
    )
    viewer = auth_headers(login(email)["access_token"])
    item = ok(client.get(f"{API}/items/{shop.item}", headers=viewer))
    assert Decimal(item["quantity_on_hand"]) == 11
    assert item["value_minor"] is None and item["average_cost_minor"] is None
    movement = ok(client.get(f"{API}/movements", headers=viewer))["items"][0]
    assert movement["value_minor"] is None and movement["unit_cost_minor"] is None
    assert ok(client.get(f"{API}/summary", headers=viewer))["total_value_minor"] is None
    stock = ok(client.get(f"{API}/stock", headers=viewer))
    assert stock[0]["value_minor"] is None

    # And an employee granted inventory.view can read but not see values.
    granted_email = f"granted-{uuid.uuid4()}@example.com"
    granted_id = create_account_with_membership(shop.org_id, Role.EMPLOYEE, email=granted_email)
    ok(
        client.put(
            f"/api/v1/memberships/{get_membership_id(shop.org_id, granted_id)}/permissions/override",
            headers=shop.admin,
            json={"permission": "inventory.view", "granted": True},
        )
    )
    granted = auth_headers(login(granted_email)["access_token"])
    assert ok(client.get(f"{API}/items/{shop.item}", headers=granted))["value_minor"] is None


# --- tenancy ----------------------------------------------------------------


def test_another_organisation_cannot_see_or_use_inventory_records() -> None:
    shop = Shop()
    shop.adjust("opening_balance", [shop.line("10", 100)])
    other = Shop()

    assert client.get(f"{API}/items/{shop.item}", headers=other.admin).status_code == 404
    assert [i["sku"] for i in ok(client.get(f"{API}/items", headers=other.admin))] == ["SKU-1"]
    assert ok(client.get(f"{API}/movements", headers=other.admin))["total"] == 0
    assert ok(client.get(f"{API}/stock", headers=other.admin)) == []

    # Referencing the first org's item or warehouse resolves to nothing.
    foreign_item = client.post(
        f"{API}/adjustments",
        headers=other.admin,
        json={
            "warehouse_id": other.warehouse,
            "reason": "found",
            "adjustment_date": TODAY,
            "lines": [shop.line("1", 100)],
        },
    )
    assert foreign_item.status_code == 404
    foreign_warehouse = client.post(
        f"{API}/adjustments",
        headers=other.admin,
        json={
            "warehouse_id": shop.warehouse,
            "reason": "found",
            "adjustment_date": TODAY,
            "lines": [other.line("1", 100)],
        },
    )
    assert foreign_warehouse.status_code == 404
    assert (
        client.patch(
            f"{API}/items/{shop.item}", headers=other.admin, json={"name": "hijack"}
        ).status_code
        == 404
    )


def test_org_scoping_holds_on_a_role_that_bypasses_rls() -> None:
    """A superuser connection ignores RLS (the desktop's embedded database
    runs as one). Inventory queries repeat the org filter themselves, so a
    session scoped to one org still sees only that org's records."""
    first = Shop()
    first.adjust("opening_balance", [first.line("10", 100)])
    second = Shop()
    second.adjust("opening_balance", [second.line("3", 700)])

    engine = create_engine(ADMIN_DATABASE_URL)
    try:
        with Session(engine) as db:
            # Sanity: this connection really does bypass RLS.
            assert db.scalar(select(func.count()).select_from(InventoryStockMovement)) >= 2

            db.info[SESSION_ORG_KEY] = second.org_id
            items = inventory_queries.list_items(db)
            assert [item.id for item in items] == [uuid.UUID(second.item)]
            with pytest.raises(InventoryNotFound):
                get_item(db, uuid.UUID(first.item))

            summary = inventory_queries.inventory_summary(db, enabled=True, with_value=True)
            assert summary.tracked_items == 1
            assert summary.total_value_minor == 2_100
            assert [m.item_id for m in summary.recent_movements] == [uuid.UUID(second.item)]

            page = inventory_queries.movement_page(db, with_value=True)
            assert page.total == 1
            stock = inventory_queries.stock_rows(db, with_value=True)
            assert [(row.sku, row.quantity) for row in stock] == [("SKU-1", Decimal(3))]
    finally:
        engine.dispose()


# --- ledger integrity -------------------------------------------------------


def test_stock_movements_are_append_only() -> None:
    shop = Shop()
    shop.adjust("opening_balance", [shop.line("1", 100)])
    for statement in (
        "UPDATE inventory_stock_movements SET reason = 'x'",
        "DELETE FROM inventory_stock_movements",
    ):
        with (
            pytest.raises(DBAPIError, match="append-only"),
            tenant_session(shop.org_id, uuid.uuid4(), "admin") as db,
        ):
            db.execute(text(statement))


def test_concurrent_postings_cannot_oversell() -> None:
    """Two removals of 6 from 10 on hand, posted at the same moment from two
    connections: the row locks serialise them, so exactly one succeeds."""
    shop = Shop()
    shop.adjust("opening_balance", [shop.line("10", 100)])
    actor = uuid.uuid4()
    drafts = []
    for _ in range(2):
        with tenant_session(shop.org_id, actor, "admin") as db:
            drafts.append(
                create_adjustment(
                    db,
                    org_id=shop.org_id,
                    actor_account_id=actor,
                    body=AdjustmentCreate(
                        warehouse_id=uuid.UUID(shop.warehouse),
                        reason=InventoryAdjustmentReason.LOSS,
                        adjustment_date=today_lagos(),
                        lines=[
                            AdjustmentLineIn(item_id=uuid.UUID(shop.item), quantity=Decimal(-6))
                        ],
                    ),
                ).id
            )

    for draft in drafts:
        shop.approve_adjustment(str(draft))

    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def post(adjustment_id: uuid.UUID) -> None:
        try:
            with tenant_session(shop.org_id, actor, "admin") as db:
                barrier.wait(timeout=10)
                post_adjustment(db, adjustment_id, actor_account_id=actor)
            outcomes.append("posted")
        except InsufficientStockError:
            outcomes.append("refused")

    threads = [threading.Thread(target=post, args=(draft,)) for draft in drafts]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(outcomes) == ["posted", "refused"]
    assert stock_by_warehouse(shop) == {"MAIN": Decimal(4)}
    assert_projections_match_ledger(shop.org_id)
