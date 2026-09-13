from app.models import Role
from tests.integration.api_helpers import (
    auth_headers,
    client,
    create_account_with_membership,
    create_employee,
    create_org,
    login,
)


def test_org_chart_reflects_manager_hierarchy() -> None:
    org_id = create_org()
    ceo_id = create_employee(org_id, employee_number="EMP-CEO")
    manager_id = create_employee(org_id, employee_number="EMP-MGR", manager_id=ceo_id)
    create_employee(org_id, employee_number="EMP-IC", manager_id=manager_id)

    email = "org-chart-viewer@example.com"
    create_account_with_membership(org_id, Role.EMPLOYEE, email=email)
    headers = auth_headers(login(email)["access_token"])

    response = client.get("/api/v1/org-chart", headers=headers)
    assert response.status_code == 200
    tree = response.json()
    assert len(tree) == 1
    root = tree[0]
    assert root["employee_id"] == str(ceo_id)
    assert len(root["reports"]) == 1
    assert root["reports"][0]["employee_id"] == str(manager_id)
    assert len(root["reports"][0]["reports"]) == 1
