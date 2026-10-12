"""Shared scaffolding for the inventory API tests."""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.core.db import tenant_session
from app.models import Role
from app.models.inventory import InventoryItemCost, InventoryStockBalance, InventoryStockMovement
from app.services.inventory import get_inventory_settings
from app.services.inventory_accounting import reconciliation as inventory_reconciliation
from app.services.posting import today_lagos
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_org,
    login,
)

API = "/api/v1/inventory"
TODAY = today_lagos().isoformat()


def headers_for(org_id: uuid.UUID, role: Role) -> dict[str, str]:
    email = f"{role.value}-{uuid.uuid4()}@example.com"
    create_account_with_membership(org_id, role, email=email)
    return auth_headers(login(email)["access_token"])


def ok(response: Any, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    return response.json() if response.content else None


class Shop:
    """An org with inventory switched on, one warehouse and one item in PCS."""

    def __init__(self) -> None:
        self.org_id = create_org()
        self.admin = headers_for(self.org_id, Role.ADMIN)
        ok(client.put(f"{API}/settings", headers=self.admin, json={"enabled": True}))
        units = ok(client.get(f"{API}/units", headers=self.admin))
        self.units = {unit["code"]: unit["id"] for unit in units}
        self.warehouse = self.add_warehouse("MAIN")
        self.item = self.add_item("SKU-1")

    def add_warehouse(self, code: str) -> str:
        body = {"code": code, "name": f"{code} store"}
        return str(ok(client.post(f"{API}/warehouses", headers=self.admin, json=body), 201)["id"])

    def add_item(self, sku: str, **extra: Any) -> str:
        body = {"sku": sku, "name": f"Item {sku}", "base_unit_id": self.units["PCS"], **extra}
        return str(ok(client.post(f"{API}/items", headers=self.admin, json=body), 201)["id"])

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
        created = ok(
            client.post(f"{API}/adjustments", headers=headers or self.admin, json=body), 201
        )
        if not post:
            return dict(created)
        if created["requires_approval"]:
            self.approve_adjustment(created["id"], headers=headers)
        return dict(
            ok(
                client.post(
                    f"{API}/adjustments/{created['id']}/post", headers=headers or self.admin
                )
            )
        )

    def approve_adjustment(
        self, adjustment_id: str, *, headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Submits a draft and approves it (D8: write-offs need approval)."""
        headers = headers or self.admin
        ok(client.post(f"{API}/adjustments/{adjustment_id}/submit", headers=headers))
        return dict(
            ok(client.post(f"{API}/adjustments/{adjustment_id}/approve", headers=headers, json={}))
        )

    def line(
        self, quantity: str, cost: int | None = None, item: str | None = None
    ) -> dict[str, Any]:
        line: dict[str, Any] = {"item_id": item or self.item, "quantity": quantity}
        if cost is not None:
            line["unit_cost_minor"] = cost
        return line

    def item_view(self, item: str | None = None) -> dict[str, Any]:
        return dict(ok(client.get(f"{API}/items/{item or self.item}", headers=self.admin)))


def stock_by_warehouse(shop: Shop, item: str | None = None) -> dict[str, Decimal]:
    rows = ok(
        client.get(
            f"{API}/stock",
            headers=shop.admin,
            params={"item_id": item or shop.item, "include_zero": True},
        )
    )
    return {row["warehouse_code"]: Decimal(row["quantity"]) for row in rows}


def assert_projections_match_ledger(org_id: uuid.UUID) -> None:
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

        # Phase 3: an organisation posting to the GL keeps its inventory
        # account equal to its stock value, and goods received not invoiced
        # equal to its unbilled receipt accruals, after every scenario.
        if get_inventory_settings(db, org_id=org_id).post_to_gl:
            report = inventory_reconciliation(db, org_id=org_id)
            assert report["inventory_difference_minor"] == 0, report
            assert report["grni_difference_minor"] == 0, report


class Store(Shop):
    """A Shop with a vendor, a second warehouse and a BOX = 10 PCS item."""

    def __init__(self) -> None:
        super().__init__()
        vendor = ok(client.post("/api/v1/vendors", headers=self.admin, json={"name": "Acme"}), 201)
        self.vendor = str(vendor["id"])
        self.side = self.add_warehouse("SIDE")
        ok(
            client.put(
                f"{API}/items/{self.item}/units",
                headers=self.admin,
                json={"units": [{"unit_id": self.units["BOX"], "factor_to_base": "10"}]},
            )
        )

    def order(
        self,
        lines: list[dict[str, Any]],
        *,
        approve: bool = True,
        issue: bool = True,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        headers = headers or self.admin
        body = {"vendor_id": self.vendor, "order_date": TODAY, "lines": lines}
        po = ok(client.post(f"{API}/purchase-orders", headers=headers, json=body), 201)
        if approve:
            ok(client.post(f"{API}/purchase-orders/{po['id']}/submit", headers=headers))
            po = ok(
                client.post(f"{API}/purchase-orders/{po['id']}/approve", headers=headers, json={})
            )
        if issue:
            po = ok(client.post(f"{API}/purchase-orders/{po['id']}/issue", headers=headers))
        return dict(po)

    def receive(
        self,
        po: dict[str, Any],
        lines: list[dict[str, Any]],
        *,
        post: bool = True,
        warehouse: str | None = None,
    ) -> dict[str, Any]:
        body = {
            "purchase_order_id": po["id"],
            "warehouse_id": warehouse or self.warehouse,
            "receipt_date": TODAY,
            "lines": lines,
        }
        grn = ok(client.post(f"{API}/goods-receipts", headers=self.admin, json=body), 201)
        if post:
            grn = ok(client.post(f"{API}/goods-receipts/{grn['id']}/post", headers=self.admin))
        return dict(grn)

    def po(self, po_id: str) -> dict[str, Any]:
        return dict(ok(client.get(f"{API}/purchase-orders/{po_id}", headers=self.admin)))

    def value(self, item: str | None = None) -> int:
        return int(self.item_view(item)["value_minor"])


def box_line(quantity: str = "10", price: int = 5_000_00, **extra: Any) -> dict[str, Any]:
    return {"quantity": quantity, "unit_price_minor": price, **extra}
