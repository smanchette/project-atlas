from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import hmac
import json
import os
from pathlib import Path, PurePath
import re
import subprocess
from typing import Any, Mapping
import zlib


class DeploymentReleaseError(RuntimeError):
    """A safe, operator-actionable deployment release validation error."""


@dataclass(frozen=True)
class DeploymentSourceExpectations:
    deployment_workflow_version: str
    plugin_version: str
    plugin_zip_filename: str
    plugin_zip_sha256: str
    plugin_source_sha256: str
    plugin_slug: str
    plugin_entry_path: str
    artifact_relative_path: str
    source_relative_path: str

    def identity(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class RuntimeReleaseIdentity:
    manifest_schema_version: int
    atlas_version: str
    atlas_commit: str
    atlas_tag: str
    plugin_version: str
    plugin_zip_filename: str
    plugin_zip_sha256: str
    generated_at: str
    manifest_sha256: str
    verification_source: str
    git_metadata_available: bool

    def identity(self) -> dict[str, Any]:
        return asdict(self)


SOURCE_EXPECTATIONS = DeploymentSourceExpectations(
    deployment_workflow_version="v0.59.4",
    plugin_version="0.57.4",
    plugin_zip_filename="project-atlas-metadata-bridge-0.57.4.zip",
    plugin_zip_sha256="939412e6e80e8344d95274444fda65b6122fe0c8249a2ced0a8582a418c4e232",
    plugin_source_sha256="5b33659b9fab81ff5aa6d6c8e0d5b89037b5d62fa454e0939f9b3ca91d32cab2",
    plugin_slug="project-atlas-metadata-bridge",
    plugin_entry_path="project-atlas-metadata-bridge/project-atlas-metadata-bridge.php",
    artifact_relative_path="wordpress/dist/project-atlas-metadata-bridge-0.57.4.zip",
    source_relative_path="wordpress/project-atlas-metadata-bridge",
)
MANIFEST_FIELDS = {
    "manifest_schema_version",
    "atlas_version",
    "atlas_commit",
    "atlas_tag",
    "plugin_version",
    "plugin_zip_filename",
    "plugin_zip_sha256",
    "generated_at",
}
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def _is_filesystem_root(path: Path) -> bool:
    return path == Path(path.anchor)


def _contained(root: Path, relative: str) -> Path:
    pure = PurePath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise DeploymentReleaseError("Deployment release path contains an unsafe segment.")
    candidate = (root / relative).resolve(strict=False)
    if candidate == root or root not in candidate.parents:
        raise DeploymentReleaseError("Deployment release path escapes the approved Atlas program root.")
    return candidate


def resolve_program_root(
    environ: Mapping[str, str] | None = None,
    *,
    module_file: str | Path | None = None,
    container_root: str | Path = "/atlas-program",
) -> Path:
    env = os.environ if environ is None else environ
    configured = env.get("ATLAS_PROGRAM_ROOT", "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        if not candidate.is_absolute():
            raise DeploymentReleaseError("ATLAS_PROGRAM_ROOT must be an absolute path.")
    else:
        mounted = Path(container_root)
        candidate = mounted if mounted.is_dir() else Path(module_file or __file__).resolve(strict=False).parents[3]
    root = candidate.resolve(strict=False)
    if _is_filesystem_root(root):
        raise DeploymentReleaseError("Atlas program root cannot be a filesystem root.")
    if not root.is_dir():
        raise DeploymentReleaseError("Configured Atlas program root does not exist or is not a directory.")
    artifact = _contained(root, SOURCE_EXPECTATIONS.artifact_relative_path)
    source = _contained(root, SOURCE_EXPECTATIONS.source_relative_path)
    if artifact.parent.name != "dist" or source.parent.name != "wordpress" or not (root / "wordpress").is_dir():
        raise DeploymentReleaseError("Configured path is not an approved Project Atlas program root.")
    return root


def release_paths(root: Path) -> tuple[Path, Path]:
    resolved = root.resolve(strict=False)
    return _contained(resolved, SOURCE_EXPECTATIONS.artifact_relative_path), _contained(resolved, SOURCE_EXPECTATIONS.source_relative_path)


def readiness_diagnostics(environ: Mapping[str, str] | None = None) -> dict[str, object]:
    root = resolve_program_root(environ)
    artifact, source = release_paths(root)
    return {
        "resolved_program_root": str(root),
        "artifact_relative_path": SOURCE_EXPECTATIONS.artifact_relative_path,
        "artifact_exists": artifact.is_file(),
        "source_directory_exists": source.is_dir(),
    }


def artifact_sha256(path: Path) -> str:
    if not path.is_file():
        raise DeploymentReleaseError(f"Locked deployment artifact is missing: {SOURCE_EXPECTATIONS.artifact_relative_path}")
    value = hashlib.sha256(path.read_bytes()).hexdigest()
    if not value:
        raise DeploymentReleaseError("Deployment artifact checksum generation failed.")
    return value


def _manifest_path(root: Path, environ: Mapping[str, str]) -> Path:
    configured = environ.get("ATLAS_RELEASE_MANIFEST_PATH", "").strip()
    if not configured:
        raise DeploymentReleaseError("release_identity_unavailable: ATLAS_RELEASE_MANIFEST_PATH is required.")
    candidate = Path(configured)
    if not candidate.is_absolute():
        raise DeploymentReleaseError("release_identity_unavailable: release manifest path must be absolute.")
    resolved = candidate.resolve(strict=False)
    approved_roots = [(root / ".runtime").resolve(strict=False), Path("/atlas-runtime").resolve(strict=False)]
    if not any(resolved != approved and approved in resolved.parents for approved in approved_roots):
        raise DeploymentReleaseError("release_identity_unavailable: release manifest is outside an approved runtime directory.")
    return resolved


def _load_manifest(root: Path, environ: Mapping[str, str]) -> tuple[dict[str, Any], str]:
    expected_sha = environ.get("ATLAS_RELEASE_MANIFEST_SHA256", "").strip().lower()
    if not SHA256_PATTERN.fullmatch(expected_sha):
        raise DeploymentReleaseError("release_identity_unavailable: a valid external manifest SHA-256 is required.")
    path = _manifest_path(root, environ)
    if not path.is_file() or path.is_symlink():
        raise DeploymentReleaseError("release_identity_unavailable: release manifest file is missing or unsafe.")
    payload = path.read_bytes()
    if len(payload) > 16_384:
        raise DeploymentReleaseError("release_identity_unavailable: release manifest is too large.")
    actual_sha = hashlib.sha256(payload).hexdigest()
    if not hmac.compare_digest(actual_sha, expected_sha):
        raise DeploymentReleaseError("release_identity_unavailable: release manifest checksum mismatch.")
    try:
        manifest = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeploymentReleaseError("release_identity_unavailable: release manifest is not valid JSON.") from exc
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_FIELDS:
        raise DeploymentReleaseError("release_identity_unavailable: release manifest schema is invalid.")
    return manifest, actual_sha


def _validate_manifest_values(manifest: dict[str, Any]) -> None:
    try:
        generated = datetime.fromisoformat(str(manifest["generated_at"]))
    except ValueError as exc:
        raise DeploymentReleaseError("release_identity_unavailable: generated timestamp is invalid.") from exc
    valid = (
        manifest["manifest_schema_version"] == 1
        and manifest["atlas_version"] == SOURCE_EXPECTATIONS.deployment_workflow_version
        and manifest["atlas_tag"] == manifest["atlas_version"]
        and COMMIT_PATTERN.fullmatch(str(manifest["atlas_commit"])) is not None
        and manifest["plugin_version"] == SOURCE_EXPECTATIONS.plugin_version
        and manifest["plugin_zip_filename"] == SOURCE_EXPECTATIONS.plugin_zip_filename
        and manifest["plugin_zip_sha256"] == SOURCE_EXPECTATIONS.plugin_zip_sha256
        and generated.tzinfo is not None
    )
    if not valid:
        raise DeploymentReleaseError("release_identity_unavailable: release manifest values do not match source expectations.")


def _packed_ref(git_dir: Path, name: str) -> tuple[str | None, str | None]:
    packed = git_dir / "packed-refs"
    if not packed.is_file():
        return None, None
    lines = packed.read_text(encoding="utf-8", errors="strict").splitlines()
    for index, line in enumerate(lines):
        if line.startswith(("#", "^")) or " " not in line:
            continue
        value, ref_name = line.split(" ", 1)
        if ref_name == name:
            peeled = lines[index + 1][1:] if index + 1 < len(lines) and lines[index + 1].startswith("^") else None
            return value, peeled
    return None, None


def _git_identity(root: Path, tag: str) -> tuple[str, str]:
    git_dir = root / ".git"

    def read_ref(name: str) -> tuple[str, str | None]:
        loose = git_dir / Path(name)
        if loose.is_file():
            return loose.read_text(encoding="ascii").strip(), None
        value, peeled = _packed_ref(git_dir, name)
        if value:
            return value, peeled
        raise DeploymentReleaseError(f"Git reference is unavailable: {name}")

    try:
        head_text = (git_dir / "HEAD").read_text(encoding="ascii").strip()
        head = read_ref(head_text[5:])[0] if head_text.startswith("ref: ") else head_text
        tag_object, packed_peeled = read_ref(f"refs/tags/{tag}")
        if packed_peeled:
            tag_commit = packed_peeled
        else:
            object_path = git_dir / "objects" / tag_object[:2] / tag_object[2:]
            if object_path.is_file():
                decoded = zlib.decompress(object_path.read_bytes())
                _, body = decoded.split(b"\x00", 1)
                kind, tag_commit = body.splitlines()[0].decode("ascii").split(" ", 1)
                if kind != "object":
                    raise ValueError("invalid annotated tag")
            else:
                tag_commit = tag_object
        return head, tag_commit
    except (OSError, UnicodeError, ValueError, zlib.error, DeploymentReleaseError):
        try:
            head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True, timeout=5).stdout.strip()
            tag_commit = subprocess.run(["git", "-C", str(root), "rev-list", "-n", "1", tag], check=True, capture_output=True, text=True, timeout=5).stdout.strip()
            return head, tag_commit
        except (OSError, subprocess.SubprocessError) as exc:
            raise DeploymentReleaseError("release_identity_unavailable: Git metadata could not be validated.") from exc


def verify_runtime_release_identity(
    root: Path,
    environ: Mapping[str, str] | None = None,
) -> RuntimeReleaseIdentity:
    env = os.environ if environ is None else environ
    manifest, manifest_sha = _load_manifest(root, env)
    _validate_manifest_values(manifest)
    git_available = (root / ".git").exists()
    if git_available:
        head, tag_commit = _git_identity(root, str(manifest["atlas_tag"]))
        if head != manifest["atlas_commit"] or tag_commit != manifest["atlas_commit"]:
            raise DeploymentReleaseError("release_identity_unavailable: runtime commit or tag does not match Git HEAD.")
        source = "git_and_checksum_verified_manifest"
    else:
        source = "checksum_verified_manifest"
    return RuntimeReleaseIdentity(
        **manifest,
        manifest_sha256=manifest_sha,
        verification_source=source,
        git_metadata_available=git_available,
    )


def canonical_manifest_bytes(values: Mapping[str, Any]) -> bytes:
    if set(values) != MANIFEST_FIELDS:
        raise DeploymentReleaseError("Release manifest generator received an invalid schema.")
    return (json.dumps(dict(values), sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
