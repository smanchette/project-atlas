from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
from pathlib import Path
import subprocess

from app.services.wordpress_deployment_release import (
    COMMIT_PATTERN,
    RELEASE_PATTERN,
    SOURCE_EXPECTATIONS,
    artifact_sha256,
    canonical_manifest_bytes,
    release_paths,
)


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    ).stdout.strip()


def _validated_release(root: Path, release_version: str, require_synchronized_remote: bool) -> tuple[str, str]:
    if RELEASE_PATTERN.fullmatch(release_version) is None:
        raise SystemExit("Release version must be a v-prefixed semantic version.")
    if git(root, "status", "--porcelain=v1"):
        raise SystemExit("Working tree is dirty; manifest was not generated.")
    commit = git(root, "rev-parse", "HEAD").lower()
    if COMMIT_PATTERN.fullmatch(commit) is None:
        raise SystemExit("HEAD is not a valid full commit SHA; manifest was not generated.")
    try:
        tag_type = git(root, "cat-file", "-t", release_version)
        tag_commit = git(root, "rev-parse", f"{release_version}^{{}}")
    except subprocess.SubprocessError as exc:
        raise SystemExit(f"Annotated tag {release_version} is unavailable; manifest was not generated.") from exc
    if tag_type != "tag":
        raise SystemExit(f"Tag {release_version} is not annotated; manifest was not generated.")
    if tag_commit != commit:
        raise SystemExit(f"Annotated tag {release_version} does not point to HEAD; manifest was not generated.")
    branch = git(root, "symbolic-ref", "--short", "HEAD")
    if require_synchronized_remote:
        try:
            upstream = git(root, "rev-parse", "@{upstream}")
            remote = git(root, "config", f"branch.{branch}.remote")
            remote_branch = git(root, "config", f"branch.{branch}.merge")
            remote_head = git(root, "ls-remote", remote, remote_branch).split("\t", 1)[0]
            remote_tag_lines = git(root, "ls-remote", remote, f"refs/tags/{release_version}^{{}}")
            remote_tag = remote_tag_lines.split("\t", 1)[0]
        except (subprocess.SubprocessError, IndexError) as exc:
            raise SystemExit("Published branch and annotated tag could not be verified remotely.") from exc
        if upstream != commit or remote_head != commit or remote_tag != commit:
            raise SystemExit("Local branch, upstream branch, or remote annotated tag diverges from HEAD.")
    return commit, branch


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a post-publication Project Atlas deployment release manifest.")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--manifest-schema-version", type=int, default=SOURCE_EXPECTATIONS.manifest_schema_version)
    parser.add_argument("--require-synchronized-remote", action="store_true")
    args = parser.parse_args()
    root = args.project_root.resolve(strict=True)
    if args.manifest_schema_version != SOURCE_EXPECTATIONS.manifest_schema_version:
        raise SystemExit("Unsupported runtime manifest schema; manifest was not generated.")
    commit, _ = _validated_release(root, args.release_version, args.require_synchronized_remote)
    artifact, _ = release_paths(root)
    if artifact_sha256(artifact) != SOURCE_EXPECTATIONS.plugin_zip_sha256:
        raise SystemExit("Locked plugin ZIP checksum mismatch; manifest was not generated.")
    values = {
        "manifest_schema_version": SOURCE_EXPECTATIONS.manifest_schema_version,
        "source_compatibility_id": SOURCE_EXPECTATIONS.source_compatibility_id,
        "atlas_version": args.release_version,
        "atlas_commit": commit,
        "atlas_tag": args.release_version,
        "plugin_version": SOURCE_EXPECTATIONS.plugin_version,
        "plugin_zip_filename": SOURCE_EXPECTATIONS.plugin_zip_filename,
        "plugin_zip_sha256": SOURCE_EXPECTATIONS.plugin_zip_sha256,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    payload = canonical_manifest_bytes(values)
    output = args.output.resolve(strict=False)
    approved = (root / ".runtime").resolve(strict=False)
    if output == approved or approved not in output.parents:
        raise SystemExit("Output must be inside the ignored .runtime directory.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    print(f"ATLAS_RELEASE_MANIFEST_PATH={output}")
    print(f"ATLAS_RELEASE_MANIFEST_SHA256={hashlib.sha256(payload).hexdigest()}")
    print(f"ATLAS_EXPECTED_RELEASE_VERSION={args.release_version}")
    print(f"ATLAS_EXPECTED_RELEASE_COMMIT={commit}")
    print(f"ATLAS_EXPECTED_RELEASE_TAG={args.release_version}")


if __name__ == "__main__":
    main()
