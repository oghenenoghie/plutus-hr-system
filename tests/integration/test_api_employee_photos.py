from io import BytesIO
from urllib.parse import urlsplit

from PIL import Image

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


def _admin_headers(org_id, email: str) -> dict[str, str]:
    account_id = create_account_with_membership(org_id, Role.ADMIN, email=email)
    tokens = login_with_mfa(account_id, email, Role.ADMIN)
    return auth_headers(tokens["access_token"])


def _fake_jpeg() -> bytes:
    image = Image.new("RGB", (300, 200), color=(10, 200, 30))
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def _local_url_path(absolute_url: str) -> str:
    """The signed URL is absolute (http://testserver/api/v1/...) since a
    real <img src> needs a full URL — TestClient only routes paths, so
    strip down to path+query for the follow-up GET."""
    parts = urlsplit(absolute_url)
    return f"{parts.path}?{parts.query}"


def test_upload_employee_photo_requires_consent() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, "photo-admin1@example.com")
    employee_id = create_employee(org_id, employee_number="EMP-PHOTO1")

    response = client.post(
        f"/api/v1/employees/{employee_id}/photo",
        headers=headers,
        files={"file": ("photo.jpg", _fake_jpeg(), "image/jpeg")},
        data={"consent": "false"},
    )
    assert response.status_code == 400, response.text
    assert "consent" in response.json()["detail"]


def test_upload_employee_photo_rejects_non_image_bytes() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, "photo-admin2@example.com")
    employee_id = create_employee(org_id, employee_number="EMP-PHOTO2")

    response = client.post(
        f"/api/v1/employees/{employee_id}/photo",
        headers=headers,
        files={"file": ("not-a-photo.jpg", b"definitely not an image", "image/jpeg")},
        data={"consent": "true"},
    )
    assert response.status_code == 400, response.text
    assert "not a valid image" in response.json()["detail"]


def test_upload_and_fetch_and_delete_employee_photo() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, "photo-admin3@example.com")
    employee_id = create_employee(org_id, employee_number="EMP-PHOTO3")

    before = client.get(f"/api/v1/employees/{employee_id}", headers=headers)
    assert before.status_code == 200, before.text
    assert before.json()["photo_url"] is None
    assert before.json()["photo_thumbnail_url"] is None

    upload = client.post(
        f"/api/v1/employees/{employee_id}/photo",
        headers=headers,
        files={"file": ("photo.jpg", _fake_jpeg(), "image/jpeg")},
        data={"consent": "true"},
    )
    assert upload.status_code == 200, upload.text
    body = upload.json()
    assert body["photo_url"] is not None
    assert body["photo_thumbnail_url"] is not None
    assert body["photo_url"] != body["photo_thumbnail_url"]

    fetched = client.get(_local_url_path(body["photo_url"]))
    assert fetched.status_code == 200, fetched.text
    assert fetched.headers["content-type"] == "image/webp"
    round_tripped = Image.open(BytesIO(fetched.content))
    assert round_tripped.format == "WEBP"
    assert round_tripped.size == (512, 512)

    thumb_fetched = client.get(_local_url_path(body["photo_thumbnail_url"]))
    assert thumb_fetched.status_code == 200, thumb_fetched.text
    thumb_image = Image.open(BytesIO(thumb_fetched.content))
    assert thumb_image.size == (128, 128)

    # A tampered signature must not be honoured.
    tampered = _local_url_path(body["photo_url"]).replace("sig=", "sig=tampered")
    tampered_response = client.get(tampered)
    assert tampered_response.status_code == 403

    deleted = client.delete(f"/api/v1/employees/{employee_id}/photo", headers=headers)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["photo_url"] is None

    gone = client.get(_local_url_path(body["photo_url"]))
    assert gone.status_code == 404


def test_reuploading_a_photo_replaces_it() -> None:
    org_id = create_org()
    headers = _admin_headers(org_id, "photo-admin4@example.com")
    employee_id = create_employee(org_id, employee_number="EMP-PHOTO4")

    first = client.post(
        f"/api/v1/employees/{employee_id}/photo",
        headers=headers,
        files={"file": ("photo.jpg", _fake_jpeg(), "image/jpeg")},
        data={"consent": "true"},
    )
    assert first.status_code == 200, first.text
    first_url = first.json()["photo_url"]

    second = client.post(
        f"/api/v1/employees/{employee_id}/photo",
        headers=headers,
        files={"file": ("photo2.jpg", _fake_jpeg(), "image/jpeg")},
        data={"consent": "true"},
    )
    assert second.status_code == 200, second.text
    second_url = second.json()["photo_url"]

    assert first_url != second_url
    # The old version's object is gone, not just unreferenced.
    old_object = client.get(_local_url_path(first_url))
    assert old_object.status_code == 404


def test_employee_self_service_photo_upload() -> None:
    org_id = create_org()
    admin_headers = _admin_headers(org_id, "photo-admin5@example.com")
    employee_email = "photo-employee5@example.com"
    account_id = create_account_with_membership(org_id, Role.EMPLOYEE, email=employee_email)
    create_employee(org_id, employee_number="EMP-PHOTO5", account_id=account_id)

    tokens = login(employee_email)
    headers = auth_headers(tokens["access_token"])

    response = client.post(
        "/api/v1/employees/me/photo",
        headers=headers,
        files={"file": ("selfie.jpg", _fake_jpeg(), "image/jpeg")},
        data={"consent": "true"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["photo_url"] is not None

    # An admin can see it too, via the normal employee record.
    admin_view = client.get("/api/v1/employees", headers=admin_headers)
    assert admin_view.status_code == 200
    [record] = [e for e in admin_view.json() if e["employee_number"] == "EMP-PHOTO5"]
    assert record["photo_url"] is not None
