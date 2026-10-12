"""Inventory Phase 1 end to end: settings, master data, adjustments posted to
the stock ledger, reversal, negative-stock protection, permissions, tenant
isolation and concurrent posting."""

import threading
import uuid
from datetime import timedelta
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
    InventoryItemCost,
    InventoryStockBalance,
    InventoryStockMovement,
)
from app.schemas.inventory import AdjustmentCreate, AdjustmentLineIn
from app.services import inventory_queries
from app.services.inventory import InventoryNotFound, get_item
from app.services.inventory_posting import create_adjustment, post_adjustment
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

API = "/api/v1/inventory"
TODAY = today_lagos().isoformat()


def _headers(org_id: uuid.UUID, role: Role) -> dict[str, str]:
    email = f"{role.value}-{uuid.uuid4()}@example.com"
    create_account_with_membership(org_id, role, email=email)
    return auth_headers(login(email)["access_token"])


def _ok(response: Any, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    return response.json() if response.content else None


class Shop:
    """An org with inventory switched on, one warehouse and one item in PCS."""

    def __init__(self) -> None:
        self.org_id = create_org()
        self.admin = _headers(self.org_id, Role.ADMIN)
        _ok(client.put(f"{API}/settings", headers=self.admin, json={"enabled": True}))
        units = _ok(client.get(f"{API}/units", headers=self.admin))
        self.units = {unit["code"]: unit["id"] for unit in units}
        self.warehouse = self.add_warehouse("MAIN")
        self.item = self.add_item("SKU-1")

    def add_warehouse(self, code: str) -> str:
        body = {"code": code, "name": f"{code} store"}
        return str(_ok(client.post(f"{API}/warehouses", headers=self.admin, json=body), 201)["id"])

    def add_item(self, sku: str, **extra: Any) -> str:
        body = {"sku": sku, "name": f"Item {sku}", "base_unit_id": self.units["PCS"], **extra}
        return str(_ok(client.post(f"{API}/items", headers=self.admin, json=body), 201)["id"])

    def adjust(
        self,
        reason: str,
        lines: list[dict[str, Any]],
        *,
        warehouse: str | None = None,
        post: bool = True,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        body = {
            "warehouse_id": warehouse or self.warehouse,
            "reason": reason,
            "adjustment_date": TODAY,
            "lines": lines,
        }
        created = _ok(
            client.post(f"{API}/adjustments", headers=headers or self.admin, json=body), 201
        )
        if not post:
            return dict(created)
        return dict(
            _ok(
                client.post(
                    f"{API}/adjustments/{created['id']}/post", headers=headers or self.admin
                )
            )
        )

    def line(
        self, quantity: str, cost: int | None = None, item: str | None = None
    ) -> dict[str, Any]:
        line: dict[str, Any] = {"item_id": item or self.item, "quantity": quantity}
        if cost is not None:
            line["unit_cost_minor"] = cost
        return line

    def item_view(self, item: str | None = None) -> dict[str, Any]:
        return dict(_ok(client.get(f"{API}/items/{item or self.item}", headers=self.admin)))


def _stock(shop: Shop, item: str | None = None) -> dict[str, Decimal]:
    rows = _ok(
        client.get(
            f"{API}/stock",
            headers=shop.admin,
            params={"item_id": item or shop.item, "include_zero": True},
        )
    )
    return {row["warehouse_code"]: Decimal(row["quantity"]) for row in rows}


# --- settings ---------------------------------------------------------------


def test_module_is_off_until_enabled_and_enabling_seeds_units() -> None:
    org_id = create_org()
    admin = _headers(org_id, Role.ADMIN)

    settings = _ok(client.get(f"{API}/settings", headers=admin))
    assert settings == {"enabled": False, "costing_method": "weighted_average"}
    assert client.get(f"{API}/items", headers=admin).status_code == 409
    summary = _ok(client.get(f"{API}/summary", headers=admin))
    assert summary["enabled"] is False and summary["tracked_items"] == 0

    _ok(client.put(f"{API}/settings", headers=admin, json={"enabled": True}))
    _ok(client.put(f"{API}/settings", headers=admin, json={"enabled": True}))  # idempotent
    codes = [unit["code"] for unit in _ok(client.get(f"{API}/units", headers=admin))]
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

    parent = _ok(client.post(f"{API}/categories", headers=admin, json={"name": "Stationery"}), 201)
    child = _ok(
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
    item = _ok(units)
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
    assert _ok(renamed)["name"] == "Renamed"
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
    assert _stock(shop) == {"MAIN": Decimal(36)}

    # Posting is one-way: a posted document can't be posted, edited or
    # deleted again.
    assert (
        client.post(f"{API}/adjustments/{loss['id']}/post", headers=shop.admin).status_code == 409
    )
    assert client.delete(f"{API}/adjustments/{loss['id']}", headers=shop.admin).status_code == 409

    reversed_ = _ok(
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

    movements = _ok(client.get(f"{API}/movements", headers=shop.admin))
    assert movements["total"] == 4
    reversal = movements["items"][0]
    assert reversal["movement_type"] == "reversal"
    assert reversal["source_number"] == loss["adjustment_number"]
    assert Decimal(reversal["quantity"]) == 4 and reversal["value_minor"] == 700_00

    _assert_projections_match_ledger(shop.org_id)


def test_unit_conversion_and_whole_number_rules() -> None:
    shop = Shop()
    _ok(
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
    refused = client.post(f"{API}/adjustments/{draft['id']}/post", headers=shop.admin)
    assert refused.status_code == 409
    assert "not enough SKU-1 in MAIN: 5 PCS available, 6 PCS needed" in refused.json()["detail"]

    # Nothing was written and the draft is still a draft.
    assert _stock(shop) == {"MAIN": Decimal(5), "SIDE": Decimal(5)}
    detail = _ok(client.get(f"{API}/adjustments/{draft['id']}", headers=shop.admin))
    assert detail["status"] == "draft"
    _assert_projections_match_ledger(shop.org_id)


def test_reversal_refused_when_the_stock_it_added_has_been_used() -> None:
    shop = Shop()
    opening = shop.adjust("opening_balance", [shop.line("5", 100)])
    shop.adjust("write_off", [shop.line("-3")])
    refused = client.post(
        f"{API}/adjustments/{opening['id']}/reverse", headers=shop.admin, json={"reason": "oops"}
    )
    assert refused.status_code == 409
    assert _stock(shop) == {"MAIN": Decimal(2)}


def test_drafts_can_be_edited_and_deleted() -> None:
    shop = Shop()
    draft = shop.adjust("found", [shop.line("2", 100)], post=False)
    assert draft["status"] == "draft" and draft["line_count"] == 1
    assert _stock(shop) == {}

    edited = _ok(
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

    _ok(client.delete(f"{API}/adjustments/{draft['id']}", headers=shop.admin), 204)
    assert client.get(f"{API}/adjustments/{draft['id']}", headers=shop.admin).status_code == 404


def test_summary_counts_and_low_stock() -> None:
    shop = Shop()
    low = shop.add_item("LOW", reorder_level="10")
    shop.add_item("EMPTY")
    shop.adjust("opening_balance", [shop.line("50", 10), shop.line("4", 10, item=low)])
    shop.adjust("found", [shop.line("1", 10)], post=False)

    summary = _ok(client.get(f"{API}/summary", headers=shop.admin))
    assert summary["enabled"] is True
    assert summary["tracked_items"] == 3
    assert summary["out_of_stock"] == 1
    assert summary["low_stock"] == 1
    assert summary["active_warehouses"] == 1
    assert summary["draft_adjustments"] == 1
    assert summary["total_value_minor"] == 540
    assert len(summary["recent_movements"]) == 2


# --- permissions ------------------------------------------------------------


def test_permissions_gate_reads_writes_and_values() -> None:
    shop = Shop()
    shop.adjust("opening_balance", [shop.line("10", 100)])

    employee = _headers(shop.org_id, Role.EMPLOYEE)
    hr_manager = _headers(shop.org_id, Role.HR_MANAGER)
    for headers in (employee, hr_manager):
        assert client.get(f"{API}/items", headers=headers).status_code == 403
        assert client.get(f"{API}/summary", headers=headers).status_code == 403

    # The auditor reads everything, values included, but changes nothing.
    auditor = _headers(shop.org_id, Role.AUDITOR)
    assert shop.item_view() == _ok(client.get(f"{API}/items/{shop.item}", headers=auditor))
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
    accountant = _headers(shop.org_id, Role.ACCOUNTANT)
    posted = shop.adjust("found", [shop.line("1", 100)], headers=accountant)
    assert posted["status"] == "posted"

    # Revoking inventory.valuation hides values and costs but not quantities.
    email = f"viewer-{uuid.uuid4()}@example.com"
    viewer_id = create_account_with_membership(shop.org_id, Role.PAYROLL_MANAGER, email=email)
    membership_id = get_membership_id(shop.org_id, viewer_id)
    _ok(
        client.put(
            f"/api/v1/memberships/{membership_id}/permissions/override",
            headers=shop.admin,
            json={"permission": "inventory.valuation", "granted": False},
        )
    )
    viewer = auth_headers(login(email)["access_token"])
    item = _ok(client.get(f"{API}/items/{shop.item}", headers=viewer))
    assert Decimal(item["quantity_on_hand"]) == 11
    assert item["value_minor"] is None and item["average_cost_minor"] is None
    movement = _ok(client.get(f"{API}/movements", headers=viewer))["items"][0]
    assert movement["value_minor"] is None and movement["unit_cost_minor"] is None
    assert _ok(client.get(f"{API}/summary", headers=viewer))["total_value_minor"] is None
    stock = _ok(client.get(f"{API}/stock", headers=viewer))
    assert stock[0]["value_minor"] is None

    # And an employee granted inventory.view can read but not see values.
    granted_email = f"granted-{uuid.uuid4()}@example.com"
    granted_id = create_account_with_membership(shop.org_id, Role.EMPLOYEE, email=granted_email)
    _ok(
        client.put(
            f"/api/v1/memberships/{get_membership_id(shop.org_id, granted_id)}/permissions/override",
            headers=shop.admin,
            json={"permission": "inventory.view", "granted": True},
        )
    )
    granted = auth_headers(login(granted_email)["access_token"])
    assert _ok(client.get(f"{API}/items/{shop.item}", headers=granted))["value_minor"] is None


# --- tenancy ----------------------------------------------------------------


def test_another_organisation_cannot_see_or_use_inventory_records() -> None:
    shop = Shop()
    shop.adjust("opening_balance", [shop.line("10", 100)])
    other = Shop()

    assert client.get(f"{API}/items/{shop.item}", headers=other.admin).status_code == 404
    assert [i["sku"] for i in _ok(client.get(f"{API}/items", headers=other.admin))] == ["SKU-1"]
    assert _ok(client.get(f"{API}/movements", headers=other.admin))["total"] == 0
    assert _ok(client.get(f"{API}/stock", headers=other.admin)) == []

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
    assert _stock(shop) == {"MAIN": Decimal(4)}
    _assert_projections_match_ledger(shop.org_id)


def _assert_projections_match_ledger(org_id: uuid.UUID) -> None:
    """Both projections equal the sum of the append-only movements."""
    with tenant_session(org_id, uuid.uuid4(), "admin") as db:
        ledger = {
            (item_id, warehouse_id): quantity
            for item_id, warehouse_id, quantity in db.execute(
                select(
                    InventoryStockMovement.item_id,
                    InventoryStockMovement.warehouse_id,
                    func.sum(InventoryStockMovement.quantity_base),
                ).group_by(InventoryStockMovement.item_id, InventoryStockMovement.warehouse_id)
            ).tuples()
        }
        balances = {
            (row.item_id, row.warehouse_id): row.quantity_base
            for row in db.scalars(select(InventoryStockBalance))
        }
        assert {k: v for k, v in balances.items() if v != 0 or k in ledger} == ledger

        values = dict(
            db.execute(
                select(
                    InventoryStockMovement.item_id, func.sum(InventoryStockMovement.value_minor)
                ).group_by(InventoryStockMovement.item_id)
            )
            .tuples()
            .all()
        )
        for pool in db.scalars(select(InventoryItemCost)):
            assert pool.value_minor == values.get(pool.item_id, 0)
            assert pool.quantity_base == sum(
                q for (item_id, _), q in ledger.items() if item_id == pool.item_id
            )
