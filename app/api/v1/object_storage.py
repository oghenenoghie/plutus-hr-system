from fastapi import APIRouter, HTTPException, Response, status

from app.core.storage import LocalObjectStorage, get_object_storage

router = APIRouter(prefix="/storage", tags=["storage"])


@router.get("/local/{key:path}")
def get_local_object(key: str, exp: int, sig: str) -> Response:
    """Serves LocalObjectStorage's files behind the same signed-URL
    contract a real S3-compatible presigned URL gives — dev/CI only: this
    is a no-op 404 whenever a real bucket is configured, since
    get_object_storage() then never returns a LocalObjectStorage."""
    storage = get_object_storage()
    if not isinstance(storage, LocalObjectStorage):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    if not storage.verify(key, exp, sig):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="link expired or invalid")
    try:
        data = storage.read(key)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found") from exc
    return Response(content=data, media_type="image/webp")
