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


def _admin_headers(org_id, email: str = "notify-admin@example.com") -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def test_broadcast_reaches_every_org_member_and_can_be_read() -> None:
    org_id = create_org()
    admin_headers = _admin_headers(org_id)

    employee_email = "notify-employee@example.com"
    employee_account_id = create_account_with_membership(
        org_id, Role.EMPLOYEE, email=employee_email
    )
    create_employee(org_id, account_id=employee_account_id, employee_number="EMP-800")

    broadcast = client.post(
        "/api/v1/notifications/broadcast",
        headers=admin_headers,
        json={
            "title": "Payroll cutoff moved",
            "body": "Submit changes by Friday.",
            "link": "/payroll",
        },
    )
    assert broadcast.status_code == 201, broadcast.text
    assert len(broadcast.json()) == 2

    employee_headers = auth_headers(login(employee_email)["access_token"])
    mine = client.get("/api/v1/notifications/me", headers=employee_headers)
    assert mine.status_code == 200
    assert len(mine.json()) == 1
    notification = mine.json()[0]
    assert notification["title"] == "Payroll cutoff moved"
    assert notification["read_at"] is None

    unread = client.get("/api/v1/notifications/me/unread-count", headers=employee_headers)
    assert unread.status_code == 200
    assert unread.json()["unread_count"] == 1

    marked = client.post(
        f"/api/v1/notifications/me/{notification['id']}/read", headers=employee_headers
    )
    assert marked.status_code == 200
    assert marked.json()["read_at"] is not None

    unread_after = client.get("/api/v1/notifications/me/unread-count", headers=employee_headers)
    assert unread_after.json()["unread_count"] == 0


def test_read_all_clears_unread_count() -> None:
    org_id = create_org()
    admin_headers = _admin_headers(org_id, email="notify-admin2@example.com")

    for i in range(3):
        client.post(
            "/api/v1/notifications/broadcast",
            headers=admin_headers,
            json={"title": f"Announcement {i}"},
        )

    unread_before = client.get("/api/v1/notifications/me/unread-count", headers=admin_headers)
    assert unread_before.json()["unread_count"] == 3

    read_all = client.post("/api/v1/notifications/me/read-all", headers=admin_headers)
    assert read_all.status_code == 204

    unread_after = client.get("/api/v1/notifications/me/unread-count", headers=admin_headers)
    assert unread_after.json()["unread_count"] == 0


def test_account_cannot_read_or_see_another_accounts_notification() -> None:
    org_id = create_org()
    admin_headers = _admin_headers(org_id, email="notify-admin3@example.com")

    outsider_email = "notify-outsider@example.com"
    create_account_with_membership(org_id, Role.EMPLOYEE, email=outsider_email)
    outsider_headers = auth_headers(login(outsider_email)["access_token"])

    client.post(
        "/api/v1/notifications/broadcast", headers=admin_headers, json={"title": "For admins only"}
    )
    admin_notification_id = client.get("/api/v1/notifications/me", headers=admin_headers).json()[0][
        "id"
    ]

    denied = client.post(
        f"/api/v1/notifications/me/{admin_notification_id}/read", headers=outsider_headers
    )
    assert denied.status_code == 404

    outsider_list = client.get("/api/v1/notifications/me", headers=outsider_headers)
    assert outsider_list.status_code == 200
    assert len(outsider_list.json()) == 1
    assert outsider_list.json()[0]["id"] != admin_notification_id


def test_manager_cannot_broadcast() -> None:
    org_id = create_org()
    email = "notify-manager@example.com"
    account_id = create_account_with_membership(org_id, Role.MANAGER, email=email)
    create_employee(org_id, account_id=account_id, employee_number="EMP-801")
    headers = auth_headers(login(email)["access_token"])

    response = client.post(
        "/api/v1/notifications/broadcast", headers=headers, json={"title": "Should not work"}
    )
    assert response.status_code == 403
