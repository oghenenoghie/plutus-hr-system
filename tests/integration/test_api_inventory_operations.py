"""Inventory Phase 2 end to end: purchase orders and goods receipts, stock
issues (including department requests), transfers through the in-transit
location, adjustment approval (D8), the approval engine, permissions,
tenancy and concurrent receipts."""

import threading
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.core.db import tenant_session
from app.models import Department, Role
from app.models.inventory import InventoryStockMovement, StockMovementType
from app.services.inventory import InventoryConflict
from app.services.inventory_purchasing import post_goods_receipt
from app.services.posting import today_lagos
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_employee,
    get_membership_id,
    login,
)
from tests.integration.inventory_helpers import (
    API,
    TODAY,
    Store,
    assert_projections_match_ledger,
    headers_for,
    ok,
    stock_by_warehouse,
)
from tests.integration.inventory_helpers import box_line as _box_line

# --- purchase orders and receipts -------------------------------------------


def test_order_approve_issue_and_receive_in_parts() -> None:
    store = Store()
    service = store.add_item("SVC-1", item_type="service")
    po = store.order(
        [
            {
                "item_id": store.item,
                "unit_id": store.units["BOX"],
                **_box_line("10", 5_000_00, discount_minor=1_000_00, tax_minor=3_675_00),
            },
            {"item_id": service, "quantity": "1", "unit_price_minor": 20_000_00},
        ]
    )
    assert po["po_number"] == "PO-000001"
    assert po["status"] == "issued"
    # 10 boxes x N5,000 = N50,000 less N1,000 discount = N49,000 net, + tax.
    assert po["subtotal_minor"] == 49_000_00 + 20_000_00
    assert po["tax_minor"] == 3_675_00
    stock_line, service_line = po["lines"]
    assert Decimal(stock_line["quantity_base"]) == 100

    # Receive 4 boxes accepted, 1 rejected; the service is received too.
    first = store.receive(
        po,
        [
            {
                "po_line_id": stock_line["id"],
                "accepted_quantity": "4",
                "rejected_quantity": "1",
                "rejection_reason": "crushed",
            },
            {"po_line_id": service_line["id"], "accepted_quantity": "1"},
        ],
    )
    assert first["grn_number"] == "GRN-000001"
    assert first["status"] == "posted"
    # Stock enters at the net price: 4/10 of N49,000.
    assert first["value_minor"] == 19_600_00
    assert stock_by_warehouse(store) == {"MAIN": Decimal(40)}
    po = store.po(po["id"])
    assert po["status"] == "partially_received"
    assert Decimal(po["lines"][0]["outstanding_quantity_base"]) == 60  # rejected doesn't count
    assert Decimal(po["lines"][1]["outstanding_quantity_base"]) == 0
    assert [r["grn_number"] for r in po["receipts"]] == ["GRN-000001"]

    # More than the 6 boxes outstanding is refused (0% tolerance, D4).
    over = client.post(
        f"{API}/goods-receipts",
        headers=store.admin,
        json={
            "purchase_order_id": po["id"],
            "warehouse_id": store.warehouse,
            "receipt_date": TODAY,
            "lines": [{"po_line_id": stock_line["id"], "accepted_quantity": "7"}],
        },
    )
    assert over.status_code == 409
    assert "60 PCS left" in over.json()["detail"]

    store.receive(po, [{"po_line_id": stock_line["id"], "accepted_quantity": "6"}])
    assert store.po(po["id"])["status"] == "received"
    assert store.value() == 49_000_00
    assert_projections_match_ledger(store.org_id)


def test_receipt_reversal_reopens_the_order_and_short_close() -> None:
    store = Store()
    po = store.order([{"item_id": store.item, **_box_line("100", 1_000)}])
    line = po["lines"][0]
    grn = store.receive(po, [{"po_line_id": line["id"], "accepted_quantity": "100"}])
    assert store.po(po["id"])["status"] == "received"

    reversed_ = ok(
        client.post(
            f"{API}/goods-receipts/{grn['id']}/reverse",
            headers=store.admin,
            json={"reason": "wrong delivery"},
        )
    )
    assert reversed_["status"] == "reversed"
    assert store.po(po["id"])["status"] == "issued"
    assert stock_by_warehouse(store) == {"MAIN": Decimal(0)}

    store.receive(po, [{"po_line_id": line["id"], "accepted_quantity": "30"}])
    closed = ok(
        client.post(
            f"{API}/purchase-orders/{po['id']}/close",
            headers=store.admin,
            json={"reason": "vendor out of stock"},
        )
    )
    assert closed["status"] == "closed"
    # A closed order takes no more receipts.
    refused = client.post(
        f"{API}/goods-receipts",
        headers=store.admin,
        json={
            "purchase_order_id": po["id"],
            "warehouse_id": store.warehouse,
            "receipt_date": TODAY,
            "lines": [{"po_line_id": line["id"], "accepted_quantity": "1"}],
        },
    )
    assert refused.status_code == 409
    assert_projections_match_ledger(store.org_id)


def test_over_receipt_tolerance_setting() -> None:
    store = Store()
    ok(client.put(f"{API}/settings", headers=store.admin, json={"over_receipt_tolerance_bp": 1000}))
    po = store.order([{"item_id": store.item, **_box_line("10", 100)}])
    line = po["lines"][0]["id"]
    store.receive(po, [{"po_line_id": line, "accepted_quantity": "11"}])  # 10% over is fine
    more = client.post(
        f"{API}/goods-receipts",
        headers=store.admin,
        json={
            "purchase_order_id": po["id"],
            "warehouse_id": store.warehouse,
            "receipt_date": TODAY,
            "lines": [{"po_line_id": line, "accepted_quantity": "1"}],
        },
    )
    assert more.status_code == 409


def test_purchase_order_rules() -> None:
    store = Store()
    draft = store.order(
        [{"item_id": store.item, **_box_line("2", 100)}], approve=False, issue=False
    )
    # Not issued: nothing can be received yet.
    refused = client.post(
        f"{API}/goods-receipts",
        headers=store.admin,
        json={
            "purchase_order_id": draft["id"],
            "warehouse_id": store.warehouse,
            "receipt_date": TODAY,
            "lines": [{"po_line_id": draft["lines"][0]["id"], "accepted_quantity": "1"}],
        },
    )
    assert refused.status_code == 409
    # A draft can be edited and deleted; posting-style actions are refused.
    edited = ok(
        client.put(
            f"{API}/purchase-orders/{draft['id']}",
            headers=store.admin,
            json={
                "vendor_id": store.vendor,
                "order_date": TODAY,
                "lines": [{"item_id": store.item, **_box_line("3", 100)}],
            },
        )
    )
    assert Decimal(edited["lines"][0]["quantity"]) == 3
    assert (
        client.post(f"{API}/purchase-orders/{draft['id']}/issue", headers=store.admin).status_code
        == 409
    )
    ok(client.delete(f"{API}/purchase-orders/{draft['id']}", headers=store.admin), 204)

    # A discount larger than the line is refused, as is an expected date
    # before the order.
    bad = client.post(
        f"{API}/purchase-orders",
        headers=store.admin,
        json={
            "vendor_id": store.vendor,
            "order_date": TODAY,
            "lines": [{"item_id": store.item, **_box_line("1", 100, discount_minor=101)}],
        },
    )
    assert bad.status_code == 400
    early = client.post(
        f"{API}/purchase-orders",
        headers=store.admin,
        json={
            "vendor_id": store.vendor,
            "order_date": TODAY,
            "expected_date": (today_lagos() - timedelta(days=1)).isoformat(),
            "lines": [{"item_id": store.item, **_box_line("1", 100)}],
        },
    )
    assert early.status_code == 400

    # An issued order with nothing received can be cancelled; one with
    # receipts can't.
    po = store.order([{"item_id": store.item, **_box_line("5", 100)}])
    cancelled = ok(
        client.post(
            f"{API}/purchase-orders/{po['id']}/cancel",
            headers=store.admin,
            json={"reason": "duplicate"},
        )
    )
    assert cancelled["status"] == "cancelled"
    received = store.order([{"item_id": store.item, **_box_line("5", 100)}])
    store.receive(received, [{"po_line_id": received["lines"][0]["id"], "accepted_quantity": "1"}])
    assert (
        client.post(
            f"{API}/purchase-orders/{received['id']}/cancel",
            headers=store.admin,
            json={"reason": "late"},
        ).status_code
        == 409
    )


def test_concurrent_receipts_cannot_receive_the_same_quantity_twice() -> None:
    """Two drafts each receiving the whole order, posted at the same moment:
    the order's lock serialises them, so the second finds nothing left."""
    store = Store()
    po = store.order([{"item_id": store.item, **_box_line("10", 100)}])
    line = po["lines"][0]["id"]
    drafts = [
        store.receive(po, [{"po_line_id": line, "accepted_quantity": "10"}], post=False)["id"]
        for _ in range(2)
    ]

    actor = uuid.uuid4()
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def post(grn_id: str) -> None:
        try:
            with tenant_session(store.org_id, actor, "admin") as db:
                barrier.wait(timeout=10)
                post_goods_receipt(db, uuid.UUID(grn_id), actor_account_id=actor)
            outcomes.append("posted")
        except InventoryConflict:
            outcomes.append("refused")

    threads = [threading.Thread(target=post, args=(draft,)) for draft in drafts]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(outcomes) == ["posted", "refused"]
    assert stock_by_warehouse(store) == {"MAIN": Decimal(10)}
    assert store.po(po["id"])["status"] == "received"
    assert_projections_match_ledger(store.org_id)


# --- issues -----------------------------------------------------------------


def _issue_body(store: Store, quantity: str = "3", **extra: Any) -> dict[str, Any]:
    return {
        "warehouse_id": store.warehouse,
        "issue_date": TODAY,
        "purpose": "office use",
        "lines": [{"item_id": store.item, "quantity": quantity}],
        **extra,
    }


def test_issue_needs_approval_then_posts_at_average_and_reverses() -> None:
    store = Store()
    store.adjust("opening_balance", [store.line("10", 100)])
    issue = ok(client.post(f"{API}/issues", headers=store.admin, json=_issue_body(store)), 201)
    assert issue["issue_number"] == "ISS-000001"

    # Issue approval is on by default: a draft can't be posted directly.
    assert client.post(f"{API}/issues/{issue['id']}/post", headers=store.admin).status_code == 400
    submitted = ok(client.post(f"{API}/issues/{issue['id']}/submit", headers=store.admin))
    assert submitted["status"] == "pending_approval"
    approved = ok(client.post(f"{API}/issues/{issue['id']}/approve", headers=store.admin, json={}))
    assert approved["status"] == "approved"
    posted = ok(client.post(f"{API}/issues/{issue['id']}/post", headers=store.admin))
    assert posted["status"] == "posted"
    assert posted["value_minor"] == -300
    assert stock_by_warehouse(store) == {"MAIN": Decimal(7)}

    reversed_ = ok(
        client.post(
            f"{API}/issues/{issue['id']}/reverse",
            headers=store.admin,
            json={"reason": "returned unused"},
        )
    )
    assert reversed_["status"] == "reversed"
    assert stock_by_warehouse(store) == {"MAIN": Decimal(10)}
    assert store.value() == 1000

    # With issue approval switched off, submitting approves at once and a
    # draft posts directly.
    ok(client.put(f"{API}/settings", headers=store.admin, json={"require_issue_approval": False}))
    direct = ok(client.post(f"{API}/issues", headers=store.admin, json=_issue_body(store)), 201)
    ok(client.post(f"{API}/issues/{direct['id']}/post", headers=store.admin))
    too_much = ok(
        client.post(f"{API}/issues", headers=store.admin, json=_issue_body(store, "100")), 201
    )
    refused = client.post(f"{API}/issues/{too_much['id']}/post", headers=store.admin)
    assert refused.status_code == 409
    assert_projections_match_ledger(store.org_id)


def test_department_manager_requests_stock_for_their_own_department() -> None:
    store = Store()
    store.adjust("opening_balance", [store.line("10", 100)])
    email = f"head-{uuid.uuid4()}@example.com"
    account = create_account_with_membership(store.org_id, Role.DEPARTMENT_MANAGER, email=email)
    head = create_employee(store.org_id, account_id=account, employee_number="EMP-HEAD")
    other_head = create_employee(store.org_id, employee_number="EMP-OTHER")
    own_department = uuid.uuid4()
    other_department = uuid.uuid4()
    with tenant_session(store.org_id, uuid.uuid4(), "admin") as db:
        db.add(Department(id=own_department, org_id=store.org_id, name="Ops", manager_id=head))
        db.add(
            Department(
                id=other_department, org_id=store.org_id, name="Sales", manager_id=other_head
            )
        )
    manager = auth_headers(login(email)["access_token"])

    departments = ok(client.get(f"{API}/issues/departments", headers=manager))
    assert [d["name"] for d in departments] == ["Ops"]
    # The catalogue is readable (to pick items), master data is not.
    assert client.get(f"{API}/items", headers=manager).status_code == 200
    assert client.get(f"{API}/stock", headers=manager).status_code == 403

    request = ok(
        client.post(
            f"{API}/issues",
            headers=manager,
            json=_issue_body(store, department_id=str(own_department)),
        ),
        201,
    )
    assert request["requested_by_employee_id"] == str(head)
    elsewhere = client.post(
        f"{API}/issues",
        headers=manager,
        json=_issue_body(store, department_id=str(other_department)),
    )
    assert elsewhere.status_code == 403
    no_department = client.post(f"{API}/issues", headers=manager, json=_issue_body(store))
    assert no_department.status_code == 403

    ok(client.post(f"{API}/issues/{request['id']}/submit", headers=manager))
    # A requester can't approve or post.
    assert (
        client.post(f"{API}/issues/{request['id']}/approve", headers=manager, json={}).status_code
        == 403
    )
    ok(client.post(f"{API}/issues/{request['id']}/approve", headers=store.admin, json={}))
    assert client.post(f"{API}/issues/{request['id']}/post", headers=manager).status_code == 403
    ok(client.post(f"{API}/issues/{request['id']}/post", headers=store.admin))

    # They see only their department's issues.
    admin_issue = ok(
        client.post(
            f"{API}/issues",
            headers=store.admin,
            json=_issue_body(store, department_id=str(other_department)),
        ),
        201,
    )
    seen = [i["id"] for i in ok(client.get(f"{API}/issues", headers=manager))]
    assert seen == [request["id"]]
    assert client.get(f"{API}/issues/{admin_issue['id']}", headers=manager).status_code == 404
    history = ok(
        client.get(f"/api/v1/approval-instances/stock_issue/{request['id']}", headers=manager)
    )
    assert history["status"] == "approved"


def test_department_head_signs_a_stock_issue_step() -> None:
    """A department-head step is signed by the head, who holds only
    inventory.request — the approval engine, not the endpoint, decides."""
    store = Store()
    store.adjust("opening_balance", [store.line("10", 100)])
    email = f"head-{uuid.uuid4()}@example.com"
    account = create_account_with_membership(store.org_id, Role.DEPARTMENT_MANAGER, email=email)
    head = create_employee(store.org_id, account_id=account, employee_number="EMP-HEAD")
    department = uuid.uuid4()
    with tenant_session(store.org_id, uuid.uuid4(), "admin") as db:
        db.add(Department(id=department, org_id=store.org_id, name="Ops", manager_id=head))
    staff = create_employee(store.org_id, employee_number="EMP-STAFF", department_id=department)
    ok(
        client.put(
            "/api/v1/approval-workflow-steps/stock_issue",
            headers=store.admin,
            json=[{"eligibility_type": "department_head"}],
        )
    )
    issue = ok(
        client.post(
            f"{API}/issues",
            headers=store.admin,
            json=_issue_body(
                store, department_id=str(department), requested_by_employee_id=str(staff)
            ),
        ),
        201,
    )
    ok(client.post(f"{API}/issues/{issue['id']}/submit", headers=store.admin))
    # The step belongs to the requester's department head, not the admin.
    assert (
        client.post(f"{API}/issues/{issue['id']}/approve", headers=store.admin, json={}).status_code
        == 403
    )
    # An employee with neither permission can't reach the endpoint at all.
    outsider = headers_for(store.org_id, Role.EMPLOYEE)
    assert (
        client.post(f"{API}/issues/{issue['id']}/approve", headers=outsider, json={}).status_code
        == 403
    )
    manager = auth_headers(login(email)["access_token"])
    approved = ok(
        client.post(
            f"{API}/issues/{issue['id']}/approve", headers=manager, json={"comment": "fine"}
        )
    )
    assert approved["status"] == "approved"
    # Posting stays with inventory.issue holders.
    assert client.post(f"{API}/issues/{issue['id']}/post", headers=manager).status_code == 403
    ok(client.post(f"{API}/issues/{issue['id']}/post", headers=store.admin))


# --- transfers --------------------------------------------------------------


def test_transfer_through_transit_with_a_shortfall() -> None:
    store = Store()
    store.adjust("opening_balance", [store.line("10", 100)])
    value_before = store.value()
    transfer = ok(
        client.post(
            f"{API}/transfers",
            headers=store.admin,
            json={
                "from_warehouse_id": store.warehouse,
                "to_warehouse_id": store.side,
                "transfer_date": TODAY,
                "lines": [{"item_id": store.item, "quantity": "6"}],
            },
        ),
        201,
    )
    assert transfer["transfer_number"] == "TRF-000001"
    # Transfer approval is off by default: dispatch straight from draft.
    dispatched = ok(
        client.post(f"{API}/transfers/{transfer['id']}/dispatch", headers=store.admin, json={})
    )
    assert dispatched["status"] == "in_transit"
    assert stock_by_warehouse(store) == {
        "MAIN": Decimal(4),
        "IN-TRANSIT": Decimal(6),
    }
    assert store.value() == value_before  # moving stock never changes its value

    line = dispatched["lines"][0]
    no_reason = client.post(
        f"{API}/transfers/{transfer['id']}/receive",
        headers=store.admin,
        json={"lines": [{"line_id": line["id"], "received_quantity_base": "5"}]},
    )
    assert no_reason.status_code == 400
    too_many = client.post(
        f"{API}/transfers/{transfer['id']}/receive",
        headers=store.admin,
        json={"lines": [{"line_id": line["id"], "received_quantity_base": "7"}]},
    )
    assert too_many.status_code == 400

    received = ok(
        client.post(
            f"{API}/transfers/{transfer['id']}/receive",
            headers=store.admin,
            json={
                "lines": [{"line_id": line["id"], "received_quantity_base": "5"}],
                "discrepancy_reason": "one carton broken in transit",
            },
        )
    )
    assert received["status"] == "received"
    assert Decimal(received["lines"][0]["received_quantity_base"]) == 5
    assert stock_by_warehouse(store) == {
        "MAIN": Decimal(4),
        "IN-TRANSIT": Decimal(0),
        "SIDE": Decimal(5),
    }
    assert store.value() == value_before - 100  # only the lost unit leaves the books

    # The in-transit location is hidden from pickers and can't be used.
    codes = [w["code"] for w in ok(client.get(f"{API}/warehouses", headers=store.admin))]
    assert "IN-TRANSIT" not in codes
    with tenant_session(store.org_id, uuid.uuid4(), "admin") as db:
        losses = list(
            db.scalars(
                select(InventoryStockMovement).where(
                    InventoryStockMovement.movement_type == StockMovementType.ADJUSTMENT_LOSS
                )
            )
        )
    assert len(losses) == 1 and losses[0].reason == "transit loss: one carton broken in transit"
    assert_projections_match_ledger(store.org_id)


def test_transfer_rules() -> None:
    store = Store()
    store.adjust("opening_balance", [store.line("2", 100)])
    same = client.post(
        f"{API}/transfers",
        headers=store.admin,
        json={
            "from_warehouse_id": store.warehouse,
            "to_warehouse_id": store.warehouse,
            "transfer_date": TODAY,
            "lines": [{"item_id": store.item, "quantity": "1"}],
        },
    )
    assert same.status_code == 400
    big = ok(
        client.post(
            f"{API}/transfers",
            headers=store.admin,
            json={
                "from_warehouse_id": store.warehouse,
                "to_warehouse_id": store.side,
                "transfer_date": TODAY,
                "lines": [{"item_id": store.item, "quantity": "5"}],
            },
        ),
        201,
    )
    short = client.post(f"{API}/transfers/{big['id']}/dispatch", headers=store.admin, json={})
    assert short.status_code == 409
    assert ok(client.get(f"{API}/transfers/{big['id']}", headers=store.admin))["status"] == "draft"

    # With approval switched on, a draft must be submitted and approved.
    ok(client.put(f"{API}/settings", headers=store.admin, json={"require_transfer_approval": True}))
    small = ok(
        client.post(
            f"{API}/transfers",
            headers=store.admin,
            json={
                "from_warehouse_id": store.warehouse,
                "to_warehouse_id": store.side,
                "transfer_date": TODAY,
                "lines": [{"item_id": store.item, "quantity": "1"}],
            },
        ),
        201,
    )
    assert (
        client.post(
            f"{API}/transfers/{small['id']}/dispatch", headers=store.admin, json={}
        ).status_code
        == 400
    )
    ok(client.post(f"{API}/transfers/{small['id']}/submit", headers=store.admin))
    ok(client.post(f"{API}/transfers/{small['id']}/approve", headers=store.admin, json={}))
    ok(client.post(f"{API}/transfers/{small['id']}/dispatch", headers=store.admin, json={}))
    assert (
        client.post(f"{API}/transfers/{small['id']}/cancel", headers=store.admin).status_code == 409
    )

    summary = ok(client.get(f"{API}/summary", headers=store.admin))
    assert summary["transfers_in_transit"] == 1
    assert summary["active_warehouses"] == 2


# --- adjustment approval (D8) -----------------------------------------------


def test_write_offs_need_approval_and_gains_follow_the_limit() -> None:
    store = Store()
    store.adjust("opening_balance", [store.line("10", 100)])
    write_off = store.adjust("write_off", [store.line("-1")], post=False)
    assert write_off["requires_approval"] is True
    direct = client.post(f"{API}/adjustments/{write_off['id']}/post", headers=store.admin)
    assert direct.status_code == 400
    ok(client.post(f"{API}/adjustments/{write_off['id']}/submit", headers=store.admin))
    rejected = ok(
        client.post(
            f"{API}/adjustments/{write_off['id']}/reject",
            headers=store.admin,
            json={"comment": "count again"},
        )
    )
    assert rejected["status"] == "rejected"
    assert (
        client.post(f"{API}/adjustments/{write_off['id']}/post", headers=store.admin).status_code
        == 409
    )
    ok(client.delete(f"{API}/adjustments/{write_off['id']}", headers=store.admin), 204)

    # Gains post freely until a limit is set; then a gain at the limit needs
    # approval and one below it doesn't.
    ok(
        client.put(
            f"{API}/settings",
            headers=store.admin,
            json={"adjustment_gain_approval_limit_minor": 1_000},
        )
    )
    big = store.adjust("found", [store.line("10", 100)], post=False)
    small = store.adjust("found", [store.line("9", 100)], post=False)
    assert big["requires_approval"] is True
    assert small["requires_approval"] is False
    ok(client.post(f"{API}/adjustments/{small['id']}/post", headers=store.admin))

    summary = ok(client.get(f"{API}/summary", headers=store.admin))
    assert summary["pending_approvals"] == 0
    ok(client.post(f"{API}/adjustments/{big['id']}/submit", headers=store.admin))
    assert ok(client.get(f"{API}/summary", headers=store.admin))["pending_approvals"] == 1


def test_configured_workflow_steps_apply_to_purchase_orders() -> None:
    store = Store()
    ok(
        client.put(
            "/api/v1/approval-workflow-steps/purchase_order",
            headers=store.admin,
            json=[
                {"eligibility_type": "role", "eligible_role": "accountant"},
                {"eligibility_type": "role", "eligible_role": "admin"},
            ],
        )
    )
    accountant = headers_for(store.org_id, Role.ACCOUNTANT)
    po = store.order([{"item_id": store.item, **_box_line("1", 100)}], approve=False, issue=False)
    ok(client.post(f"{API}/purchase-orders/{po['id']}/submit", headers=store.admin))
    # Step 1 is the accountant's: the admin can't sign it.
    assert (
        client.post(
            f"{API}/purchase-orders/{po['id']}/approve", headers=store.admin, json={}
        ).status_code
        == 403
    )
    step_one = ok(
        client.post(
            f"{API}/purchase-orders/{po['id']}/approve",
            headers=accountant,
            json={"comment": "budget ok"},
        )
    )
    assert step_one["status"] == "pending_approval"
    final = ok(
        client.post(f"{API}/purchase-orders/{po['id']}/approve", headers=store.admin, json={})
    )
    assert final["status"] == "approved"
    history = ok(
        client.get(f"/api/v1/approval-instances/purchase_order/{po['id']}", headers=accountant)
    )
    assert [d["comment"] for d in history["decisions"]] == ["budget ok", None]

    # Manager-relationship steps make no sense for a purchase order.
    bad = client.put(
        "/api/v1/approval-workflow-steps/purchase_order",
        headers=store.admin,
        json=[{"eligibility_type": "direct_manager"}],
    )
    assert bad.status_code == 400


# --- permissions and tenancy ------------------------------------------------


def test_phase_two_permissions() -> None:
    store = Store()
    po = store.order([{"item_id": store.item, **_box_line("1", 100)}], approve=False, issue=False)
    ok(client.post(f"{API}/purchase-orders/{po['id']}/submit", headers=store.admin))

    auditor = headers_for(store.org_id, Role.AUDITOR)
    assert client.get(f"{API}/purchase-orders/{po['id']}", headers=auditor).status_code == 200
    assert (
        client.post(
            f"{API}/purchase-orders",
            headers=auditor,
            json={"vendor_id": store.vendor, "order_date": TODAY, "lines": []},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{API}/purchase-orders/{po['id']}/approve", headers=auditor, json={}
        ).status_code
        == 403
    )
    hr = headers_for(store.org_id, Role.HR_MANAGER)
    assert client.get(f"{API}/purchase-orders", headers=hr).status_code == 403
    assert client.get(f"{API}/issues", headers=hr).status_code == 403

    # Revoking inventory.approve from an accountant stops them approving.
    email = f"acct-{uuid.uuid4()}@example.com"
    account = create_account_with_membership(store.org_id, Role.ACCOUNTANT, email=email)
    ok(
        client.put(
            f"/api/v1/memberships/{get_membership_id(store.org_id, account)}/permissions/override",
            headers=store.admin,
            json={"permission": "inventory.approve", "granted": False},
        )
    )
    accountant = auth_headers(login(email)["access_token"])
    assert (
        client.post(
            f"{API}/purchase-orders/{po['id']}/approve", headers=accountant, json={}
        ).status_code
        == 403
    )
    assert (
        client.get(f"/api/v1/approval-instances/purchase_order/{po['id']}", headers=hr).status_code
        == 403
    )


def test_operations_documents_are_isolated_between_organisations() -> None:
    store = Store()
    store.adjust("opening_balance", [store.line("5", 100)])
    po = store.order([{"item_id": store.item, **_box_line("1", 100)}])
    issue = ok(client.post(f"{API}/issues", headers=store.admin, json=_issue_body(store, "1")), 201)
    transfer = ok(
        client.post(
            f"{API}/transfers",
            headers=store.admin,
            json={
                "from_warehouse_id": store.warehouse,
                "to_warehouse_id": store.side,
                "transfer_date": TODAY,
                "lines": [{"item_id": store.item, "quantity": "1"}],
            },
        ),
        201,
    )
    other = Store()
    for path in (
        f"purchase-orders/{po['id']}",
        f"issues/{issue['id']}",
        f"transfers/{transfer['id']}",
    ):
        assert client.get(f"{API}/{path}", headers=other.admin).status_code == 404
    assert ok(client.get(f"{API}/purchase-orders", headers=other.admin)) == []
    # Receiving against another organisation's order, or ordering from its
    # vendor, finds nothing.
    foreign_receipt = client.post(
        f"{API}/goods-receipts",
        headers=other.admin,
        json={
            "purchase_order_id": po["id"],
            "warehouse_id": other.warehouse,
            "receipt_date": TODAY,
            "lines": [{"po_line_id": po["lines"][0]["id"], "accepted_quantity": "1"}],
        },
    )
    assert foreign_receipt.status_code == 404
    foreign_vendor = client.post(
        f"{API}/purchase-orders",
        headers=other.admin,
        json={
            "vendor_id": store.vendor,
            "order_date": TODAY,
            "lines": [{"item_id": other.item, **_box_line("1", 100)}],
        },
    )
    assert foreign_vendor.status_code == 404
