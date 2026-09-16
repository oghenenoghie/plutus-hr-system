"""Pure image processing for employee photo uploads — no I/O, no DB, no
FastAPI, per this repo's "keep the domain pure" convention. Encodes the
python-engineering.md "Employee photos" contract: validate the decoded
image (never trust the declared content-type), strip EXIF, square-crop
and re-encode to WebP at one canonical size plus a thumbnail, cap the
input size.
"""

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
PHOTO_SIZE = 512
THUMBNAIL_SIZE = 128
_WEBP_QUALITY = 85


class InvalidPhotoError(ValueError):
    pass


@dataclass(frozen=True)
class ProcessedPhoto:
    full_webp: bytes
    thumbnail_webp: bytes


def _square_crop(image: Image.Image) -> Image.Image:
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    return image.crop((left, top, left + side, top + side))


def _strip_metadata(image: Image.Image) -> Image.Image:
    # A fresh Image built from just the pixel data carries none of the
    # source's .info (EXIF GPS/timestamps included) — re-encoding through
    # .convert() alone is not reliable for this across Pillow versions.
    clean = Image.new("RGB", image.size)
    clean.paste(image)
    return clean


def _encode_webp(image: Image.Image, *, size: int) -> bytes:
    resized = image.resize((size, size), Image.Resampling.LANCZOS)
    buffer = BytesIO()
    resized.save(buffer, format="WEBP", quality=_WEBP_QUALITY)
    return buffer.getvalue()


def process_employee_photo(raw: bytes) -> ProcessedPhoto:
    """Raises InvalidPhotoError for anything too large, undecodable, or
    otherwise not a real image — the caller (an upload endpoint) turns
    that into a 400, never a 500."""
    if not raw:
        raise InvalidPhotoError("no file uploaded")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise InvalidPhotoError("photo exceeds the 8MB upload limit")

    try:
        with Image.open(BytesIO(raw)) as probe:
            probe.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise InvalidPhotoError("file is not a valid image") from exc

    try:
        with Image.open(BytesIO(raw)) as image:
            # Respects EXIF orientation (a sideways phone photo) before the
            # EXIF itself gets dropped below — otherwise the crop would be
            # taken from the wrong axis.
            oriented = ImageOps.exif_transpose(image)
            if oriented is None:
                oriented = image
            cropped = _square_crop(oriented.convert("RGB"))
            clean = _strip_metadata(cropped)
            full_webp = _encode_webp(clean, size=PHOTO_SIZE)
            thumbnail_webp = _encode_webp(clean, size=THUMBNAIL_SIZE)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise InvalidPhotoError("file is not a valid image") from exc

    return ProcessedPhoto(full_webp=full_webp, thumbnail_webp=thumbnail_webp)
