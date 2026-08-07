from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError, features

from app.core.config import Settings


ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
FORMAT_EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
FORMAT_CONTENT_TYPES = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}
EXTENSION_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
THUMBNAIL_SIZE = (480, 480)
OPTIMIZED_SIZE = (1920, 1920)


@dataclass(frozen=True)
class StoredMedia:
    original_filename: str
    stored_filename: str
    asset_url: str
    thumbnail_url: str
    optimized_url: str
    mime_type: str
    file_size: int
    width: int
    height: int
    checksum_sha256: str


@dataclass(frozen=True)
class ManagedOriginalIdentity:
    """Observed identity of one managed original, re-read from durable storage."""

    stored_filename: str
    mime_type: str
    file_size: int
    width: int
    height: int
    checksum_sha256: str


def ensure_media_directories(settings: Settings) -> Path:
    root = settings.media_root.resolve()
    for child in ("originals", "optimized", "thumbnails"):
        (root / child).mkdir(parents=True, exist_ok=True)
    return root


async def store_uploaded_image(upload: UploadFile, settings: Settings) -> StoredMedia:
    original_filename = upload.filename or ""
    if not is_safe_image_filename(original_filename):
        raise HTTPException(status_code=422, detail="Uploaded image filename is unsafe")

    if upload.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Only JPEG, PNG, and WebP images are accepted")
    extension_content_type = EXTENSION_CONTENT_TYPES.get(Path(original_filename).suffix.lower())
    if extension_content_type is None:
        raise HTTPException(status_code=415, detail="Uploaded image filename has an unsupported extension")
    if extension_content_type != upload.content_type:
        raise HTTPException(status_code=415, detail="Uploaded image filename extension and MIME type do not match")

    payload = await upload.read(settings.media_max_upload_bytes + 1)
    if len(payload) > settings.media_max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Image exceeds the {settings.media_max_upload_bytes // (1024 * 1024)} MB upload limit",
        )
    if not payload:
        raise HTTPException(status_code=422, detail="Uploaded image is empty")

    image_format, width, height = inspect_image_payload(payload)
    detected_content_type = FORMAT_CONTENT_TYPES[image_format]
    if detected_content_type != upload.content_type:
        raise HTTPException(status_code=415, detail="Uploaded image MIME type does not match its file signature")
    if width * height > settings.media_max_pixels:
        raise HTTPException(status_code=413, detail="Image dimensions exceed the configured pixel limit")

    root = ensure_media_directories(settings)
    identifier = uuid4().hex
    original_extension = FORMAT_EXTENSIONS[image_format]
    stored_filename = f"{identifier}{original_extension}"
    original_path = root / "originals" / stored_filename
    generated_paths: list[Path] = []

    try:
        original_path.write_bytes(payload)
        generated_paths.append(original_path)
        with Image.open(BytesIO(payload)) as opened:
            source = ImageOps.exif_transpose(opened)
            output_extension = ".webp" if features.check("webp") else ".jpg"
            optimized_filename = f"{identifier}-optimized{output_extension}"
            thumbnail_filename = f"{identifier}-thumbnail{output_extension}"
            optimized_path = root / "optimized" / optimized_filename
            thumbnail_path = root / "thumbnails" / thumbnail_filename

            _save_variant(source, optimized_path, OPTIMIZED_SIZE, output_extension, quality=82)
            generated_paths.append(optimized_path)
            _save_variant(source, thumbnail_path, THUMBNAIL_SIZE, output_extension, quality=76)
            generated_paths.append(thumbnail_path)
    except Exception:
        for path in generated_paths:
            path.unlink(missing_ok=True)
        raise

    public_base = settings.media_public_url.rstrip("/")
    return StoredMedia(
        original_filename=original_filename,
        stored_filename=stored_filename,
        asset_url=f"{public_base}/optimized/{optimized_filename}",
        thumbnail_url=f"{public_base}/thumbnails/{thumbnail_filename}",
        optimized_url=f"{public_base}/optimized/{optimized_filename}",
        mime_type=detected_content_type,
        file_size=len(payload),
        width=width,
        height=height,
        checksum_sha256=sha256(payload).hexdigest(),
    )


def inspect_managed_original(stored_filename: str, settings: Settings) -> ManagedOriginalIdentity:
    """Re-read a managed original and return its independently observed identity.

    This intentionally does not create media directories. Approval must fail closed when
    durable storage is missing or when a stored filename escapes the managed originals
    directory.
    """

    if not is_safe_image_filename(stored_filename):
        raise HTTPException(status_code=422, detail="Managed original filename is unsafe")
    extension_content_type = EXTENSION_CONTENT_TYPES.get(Path(stored_filename).suffix.lower())
    if extension_content_type is None:
        raise HTTPException(status_code=415, detail="Managed original filename has an unsupported extension")

    root = settings.media_root.resolve()
    originals_root = (root / "originals").resolve()
    original_path = (originals_root / stored_filename).resolve()
    if original_path.parent != originals_root or not original_path.is_relative_to(originals_root):
        raise HTTPException(status_code=422, detail="Managed original filename is unsafe")
    if not original_path.is_file():
        raise HTTPException(status_code=409, detail="Managed original is missing")

    try:
        recorded_size = original_path.stat().st_size
        if recorded_size > settings.media_max_upload_bytes:
            raise HTTPException(status_code=413, detail="Managed original exceeds the configured upload size limit")
        with original_path.open("rb") as managed_file:
            payload = managed_file.read(settings.media_max_upload_bytes + 1)
    except HTTPException:
        raise
    except OSError as exc:
        raise HTTPException(status_code=409, detail="Managed original could not be read") from exc
    if len(payload) > settings.media_max_upload_bytes:
        raise HTTPException(status_code=413, detail="Managed original exceeds the configured upload size limit")
    if not payload:
        raise HTTPException(status_code=409, detail="Managed original is empty")
    if len(payload) != recorded_size:
        raise HTTPException(status_code=409, detail="Managed original changed while it was being inspected")

    image_format, width, height = inspect_image_payload(payload)
    detected_content_type = FORMAT_CONTENT_TYPES[image_format]
    if detected_content_type != extension_content_type:
        raise HTTPException(status_code=415, detail="Managed original filename extension does not match its file signature")
    if width * height > settings.media_max_pixels:
        raise HTTPException(status_code=413, detail="Managed original dimensions exceed the configured pixel limit")

    return ManagedOriginalIdentity(
        stored_filename=stored_filename,
        mime_type=detected_content_type,
        file_size=len(payload),
        width=width,
        height=height,
        checksum_sha256=sha256(payload).hexdigest(),
    )


def managed_original_contains_gps(stored_filename: str, settings: Settings) -> bool:
    """Return whether an intact managed original contains an EXIF GPS directory.

    The check deliberately reports presence only. It neither copies location values into
    Atlas nor treats their presence as authorization to retain or use them. Callers must
    record a separate, explicit operator decision before any verified GPS data can become
    governed media metadata.
    """

    # Reuse the complete fail-closed binary/path validation before opening the original
    # for metadata inspection.
    inspect_managed_original(stored_filename, settings)
    originals_root = (settings.media_root.resolve() / "originals").resolve()
    original_path = (originals_root / stored_filename).resolve()
    if original_path.parent != originals_root or not original_path.is_relative_to(originals_root):
        raise HTTPException(status_code=422, detail="Managed original filename is unsafe")
    try:
        with Image.open(original_path) as image:
            exif = image.getexif()
            if not exif or 34853 not in exif:  # 34853 is the EXIF GPSInfo tag.
                return False
            try:
                gps_values = exif.get_ifd(34853)
            except (KeyError, TypeError, ValueError, SyntaxError):
                return True
            return bool(gps_values) or exif.get(34853) is not None
    except HTTPException:
        raise
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise HTTPException(
            status_code=409,
            detail="Managed original metadata could not be inspected",
        ) from exc


def is_safe_image_filename(filename: str) -> bool:
    return bool(
        filename
        and filename == filename.strip()
        and filename not in {".", ".."}
        and "/" not in filename
        and "\\" not in filename
        and "\x00" not in filename
        and all(ord(character) >= 32 and ord(character) != 127 for character in filename)
        and Path(filename).name == filename
    )


def remove_stored_media_files(stored: StoredMedia, settings: Settings) -> None:
    root = settings.media_root.resolve()
    candidates = [
        root / "originals" / stored.stored_filename,
        _url_to_managed_path(stored.optimized_url, root),
        _url_to_managed_path(stored.thumbnail_url, root),
    ]
    for path in candidates:
        if path is not None and path.is_relative_to(root):
            path.unlink(missing_ok=True)


def inspect_image_payload(payload: bytes) -> tuple[str, int, int]:
    try:
        with Image.open(BytesIO(payload)) as image:
            image.verify()
        with Image.open(BytesIO(payload)) as image:
            image_format = (image.format or "").upper()
            if image_format not in FORMAT_EXTENSIONS:
                raise HTTPException(status_code=415, detail="Unsupported image encoding")
            return image_format, image.width, image.height
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise HTTPException(status_code=415, detail="File content is not a valid image") from exc


def _save_variant(
    source: Image.Image,
    destination: Path,
    max_size: tuple[int, int],
    extension: str,
    *,
    quality: int,
) -> None:
    variant = source.copy()
    variant.thumbnail(max_size, Image.Resampling.LANCZOS)
    if extension == ".webp":
        mode = "RGBA" if "A" in variant.getbands() else "RGB"
        variant.convert(mode).save(destination, format="WEBP", quality=quality, method=6)
        return

    if "A" in variant.getbands():
        background = Image.new("RGB", variant.size, "white")
        background.paste(variant, mask=variant.getchannel("A"))
        variant = background
    else:
        variant = variant.convert("RGB")
    variant.save(destination, format="JPEG", quality=quality, optimize=True)


def _url_to_managed_path(url: str, root: Path) -> Path | None:
    marker = "/media/"
    if marker not in url:
        return None
    relative = url.split(marker, 1)[1]
    return root / Path(relative)
