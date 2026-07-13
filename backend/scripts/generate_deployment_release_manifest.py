from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
from pathlib import Path
import subprocess

from app.services.wordpress_deployment_release import SOURCE_EXPECTATIONS, canonical_manifest_bytes


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the post-tag Project Atlas deployment release manifest.")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.project_root.resolve(strict=True)
    commit = git(root, "rev-parse", "HEAD")
    tag = SOURCE_EXPECTATIONS.deployment_workflow_version
    if git(root, "rev-list", "-n", "1", tag) != commit:
        raise SystemExit(f"Annotated tag {tag} does not point to HEAD; manifest was not generated.")
    values = {
        "manifest_schema_version": 1,
        "atlas_version": SOURCE_EXPECTATIONS.deployment_workflow_version,
        "atlas_commit": commit,
        "atlas_tag": tag,
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


if __name__ == "__main__":
    main()
