from io import BytesIO

import pytest
from PIL import Image

from app.domain.employee_photo import (
    MAX_UPLOAD_BYTES,
    PHOTO_SIZE,
    THUMBNAIL_SIZE,
    InvalidPhotoError,
    process_employee_photo,
)


def _jpeg_bytes(*, width: int, height: int) -> bytes:
    image = Image.new("RGB", (width, height), color=(200, 50, 50))
    buffer = BytesIO()
    # A real EXIF block, so the "strips EXIF" behaviour has something to
    # actually strip rather than trivially passing.
    exif = Image.Exif()
    exif[0x0110] = "Test Camera"  # Model tag
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def test_process_employee_photo_square_crops_and_resizes() -> None:
    processed = process_employee_photo(_jpeg_bytes(width=800, height=600))

    full = Image.open(BytesIO(processed.full_webp))
    assert full.size == (PHOTO_SIZE, PHOTO_SIZE)
    assert full.format == "WEBP"

    thumb = Image.open(BytesIO(processed.thumbnail_webp))
    assert thumb.size == (THUMBNAIL_SIZE, THUMBNAIL_SIZE)


def test_process_employee_photo_strips_exif() -> None:
    processed = process_employee_photo(_jpeg_bytes(width=400, height=400))
    full = Image.open(BytesIO(processed.full_webp))
    assert full.getexif() == {}


def test_process_employee_photo_rejects_oversized_upload() -> None:
    with pytest.raises(InvalidPhotoError, match="8MB"):
        process_employee_photo(b"0" * (MAX_UPLOAD_BYTES + 1))


def test_process_employee_photo_rejects_empty_upload() -> None:
    with pytest.raises(InvalidPhotoError):
        process_employee_photo(b"")


def test_process_employee_photo_rejects_non_image_bytes() -> None:
    # Not a real image, whatever content-type a caller might have claimed —
    # process_employee_photo validates the decoded bytes, never a
    # declared MIME type.
    with pytest.raises(InvalidPhotoError, match="not a valid image"):
        process_employee_photo(b"this is definitely not an image" * 10)
