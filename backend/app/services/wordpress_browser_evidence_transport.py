from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import os
from pathlib import Path
import re
import tempfile


INPUT_PREFIX = "browser-evidence-input-"
INPUT_SUFFIX = ".html"
INPUT_LIFETIME = timedelta(minutes=5)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
INPUT_NAME_PATTERN = re.compile(r"browser-evidence-input-[A-Za-z0-9_-]{8,64}\.html")
UTF8_BOM = b"\xef\xbb\xbf"


class BrowserEvidenceTransportError(ValueError):
    """Fail-closed browser-evidence byte transport error with a stable reason code."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class StagedBrowserEvidenceInput:
    path: Path
    sha256: str
    byte_size: int


@dataclass(frozen=True)
class ConsumedBrowserEvidenceInput:
    path: Path
    html: str
    sha256: str
    byte_size: int


def approved_browser_evidence_runtime_root() -> Path:
    """Return the one ignored runtime directory approved for raw capture bytes."""

    configured = os.getenv("ATLAS_BROWSER_EVIDENCE_RUNTIME_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve(strict=False)
    manifest = os.getenv("ATLAS_RELEASE_MANIFEST_PATH", "").strip()
    if manifest:
        return Path(manifest).expanduser().resolve(strict=False).parent
    return Path(__file__).resolve().parents[3] / ".runtime"


def stage_browser_evidence_input(
    dom_bytes: bytes,
    *,
    runtime_root: Path | None = None,
) -> StagedBrowserEvidenceInput:
    """Stage exact browser-produced bytes without text decoding or normalization."""

    if not isinstance(dom_bytes, bytes):
        raise BrowserEvidenceTransportError("browser_evidence_input_bytes_required")
    root = (runtime_root or approved_browser_evidence_runtime_root()).resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="xb",
        prefix=INPUT_PREFIX,
        suffix=INPUT_SUFFIX,
        dir=root,
        delete=False,
    ) as stream:
        stream.write(dom_bytes)
        stream.flush()
        os.fsync(stream.fileno())
        path = Path(stream.name)
    try:
        path.chmod(0o600)
    except OSError:
        remove_browser_evidence_input(path, runtime_root=root)
        raise BrowserEvidenceTransportError("browser_evidence_input_permissions_failed")
    return StagedBrowserEvidenceInput(
        path=path,
        sha256=hashlib.sha256(dom_bytes).hexdigest(),
        byte_size=len(dom_bytes),
    )


def consume_browser_evidence_input(
    input_path: Path,
    expected_sha256: str,
    *,
    runtime_root: Path | None = None,
    now: datetime | None = None,
) -> ConsumedBrowserEvidenceInput:
    """Read and validate exact UTF-8 bytes independently inside the evidence helper."""

    root = (runtime_root or approved_browser_evidence_runtime_root()).resolve(strict=False)
    supplied = Path(input_path)
    if not SHA256_PATTERN.fullmatch(expected_sha256):
        raise BrowserEvidenceTransportError("browser_evidence_input_hash_invalid")
    if supplied.is_symlink():
        raise BrowserEvidenceTransportError("browser_evidence_input_symlink_forbidden")
    try:
        resolved = supplied.resolve(strict=True)
    except OSError as exc:
        raise BrowserEvidenceTransportError("browser_evidence_input_missing") from exc
    if resolved.parent != root or INPUT_NAME_PATTERN.fullmatch(resolved.name) is None:
        raise BrowserEvidenceTransportError("browser_evidence_input_path_unapproved")
    if not resolved.is_file():
        raise BrowserEvidenceTransportError("browser_evidence_input_not_regular_file")
    stat = resolved.stat()
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise BrowserEvidenceTransportError("browser_evidence_transport_clock_invalid")
    modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
    age = current.astimezone(UTC) - modified
    if age < -timedelta(seconds=5) or age > INPUT_LIFETIME:
        raise BrowserEvidenceTransportError("browser_evidence_input_stale")
    raw = resolved.read_bytes()
    consumed_sha256 = hashlib.sha256(raw).hexdigest()
    if consumed_sha256 != expected_sha256:
        raise BrowserEvidenceTransportError("browser_evidence_input_byte_mismatch")
    html = decode_browser_evidence_utf8(raw)
    return ConsumedBrowserEvidenceInput(
        path=resolved,
        html=html,
        sha256=consumed_sha256,
        byte_size=len(raw),
    )


def decode_browser_evidence_utf8(raw: bytes) -> str:
    """Decode strict BOM-free UTF-8; do not normalize Unicode or line endings."""

    if raw.startswith(UTF8_BOM):
        raise BrowserEvidenceTransportError("browser_evidence_input_utf8_bom_forbidden")
    try:
        html = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise BrowserEvidenceTransportError("browser_evidence_input_invalid_utf8") from exc
    if "\ufffd" in html:
        raise BrowserEvidenceTransportError("browser_evidence_input_replacement_character")
    return html


def remove_browser_evidence_input(path: Path, *, runtime_root: Path | None = None) -> None:
    """Remove a raw DOM input and fail closed if it remains on disk."""

    supplied = Path(path)
    root = (runtime_root or approved_browser_evidence_runtime_root()).resolve(strict=False)
    try:
        parent = supplied.parent.resolve(strict=True)
    except OSError as exc:
        raise BrowserEvidenceTransportError("browser_evidence_input_cleanup_path_unapproved") from exc
    if parent != root or INPUT_NAME_PATTERN.fullmatch(supplied.name) is None:
        raise BrowserEvidenceTransportError("browser_evidence_input_cleanup_path_unapproved")
    try:
        supplied.unlink(missing_ok=True)
    except OSError as exc:
        raise BrowserEvidenceTransportError("browser_evidence_input_cleanup_failed") from exc
    if supplied.exists() or supplied.is_symlink():
        raise BrowserEvidenceTransportError("browser_evidence_input_cleanup_failed")
