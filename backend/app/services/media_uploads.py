from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError, features

from app.core.config import Settings


ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
FORMAT_EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
THUMBNAIL_SIZE = (480, 480)
OPTIMIZED_SIZE = (1920, 1920)


@dataclass(frozen=True)
class StoredMedia:
    original_filename: str
    stored_filename: str
    asset_url: str
    thumbnail_url: str
    optimized_url: str


def ensure_media_directories(settings: Settings) -> Path:
    root = settings.media_root.resolve()
    for child in ("originals", "optimized", "thumbnails"):
        (root / child).mkdir(parents=True, exist_ok=True)
    return root


async def store_uploaded_image(upload: UploadFile, settings: Settings) -> StoredMedia:
    if upload.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Only JPEG, PNG, and WebP images are accepted")

    payload = await upload.read(settings.media_max_upload_bytes + 1)
    if len(payload) > settings.media_max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Image exceeds the {settings.media_max_upload_bytes // (1024 * 1024)} MB upload limit",
        )
    if not payload:
        raise HTTPException(status_code=422, detail="Uploaded image is empty")

    image_format, width, height = _inspect_image(payload)
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
        original_filename=Path(upload.filename or "upload").name,
        stored_filename=stored_filename,
        asset_url=f"{public_base}/optimized/{optimized_filename}",
        thumbnail_url=f"{public_base}/thumbnails/{thumbnail_filename}",
        optimized_url=f"{public_base}/optimized/{optimized_filename}",
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


def _inspect_image(payload: bytes) -> tuple[str, int, int]:
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
