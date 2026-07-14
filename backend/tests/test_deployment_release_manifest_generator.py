from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from app.services import wordpress_deployment_release as release
from scripts import generate_deployment_release_manifest as generator


def test_generator_requires_clean_head_annotated_tag_and_matching_commit(monkeypatch, tmp_path):
    root = tmp_path
    commit = "a" * 40
    state = {"dirty": False, "type": "tag", "tag_commit": commit}

    def fake_git(_root, *args):
        values = {
            ("status", "--porcelain=v1"): "dirty" if state["dirty"] else "",
            ("rev-parse", "HEAD"): commit,
            ("cat-file", "-t", "v0.59.8"): state["type"],
            ("rev-parse", "v0.59.8^{}"): state["tag_commit"],
            ("symbolic-ref", "--short", "HEAD"): "main",
        }
        return values[args]

    monkeypatch.setattr(generator, "git", fake_git)
    commit, branch = generator._validated_release(root, "v0.59.8", False)
    assert commit == "a" * 40 and branch == "main"
    state["dirty"] = True
    with pytest.raises(SystemExit, match="dirty"):
        generator._validated_release(root, "v0.59.8", False)
    state.update(dirty=False, type="commit")
    with pytest.raises(SystemExit, match="not annotated"):
        generator._validated_release(root, "v0.59.8", False)
    state.update(type="tag", tag_commit="b" * 40)
    with pytest.raises(SystemExit, match="does not point to HEAD"):
        generator._validated_release(root, "v0.59.8", False)


def test_generator_rejects_malformed_or_stale_release_version(monkeypatch, tmp_path):
    root = tmp_path
    with pytest.raises(SystemExit, match="semantic version"):
        generator._validated_release(root, "release", False)
    def missing_tag(_root, *args):
        if args == ("status", "--porcelain=v1"):
            return ""
        if args == ("rev-parse", "HEAD"):
            return "a" * 40
        raise subprocess.CalledProcessError(1, ["git", *args])
    monkeypatch.setattr(generator, "git", missing_tag)
    with pytest.raises(SystemExit, match="unavailable"):
        generator._validated_release(root, "v0.59.6", False)


def test_generator_rejects_remote_divergence(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    commit = "a" * 40

    def fake_git(_root, *args):
        mapping = {
            ("status", "--porcelain=v1"): "",
            ("rev-parse", "HEAD"): commit,
            ("cat-file", "-t", "v0.59.8"): "tag",
            ("rev-parse", "v0.59.8^{}"): commit,
            ("symbolic-ref", "--short", "HEAD"): "main",
            ("rev-parse", "@{upstream}"): "b" * 40,
            ("config", "branch.main.remote"): "origin",
            ("config", "branch.main.merge"): "refs/heads/main",
            ("ls-remote", "origin", "refs/heads/main"): f"{commit}\trefs/heads/main",
            ("ls-remote", "origin", "refs/tags/v0.59.8^{}"): f"{commit}\trefs/tags/v0.59.8^{{}}",
        }
        return mapping[args]

    monkeypatch.setattr(generator, "git", fake_git)
    with pytest.raises(SystemExit, match="diverges"):
        generator._validated_release(root, "v0.59.8", True)


def test_generator_builds_schema_two_manifest_without_commit_self_reference(monkeypatch, tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    artifact = root / "wordpress/dist/project-atlas-metadata-bridge-0.57.4.zip"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"test")
    commit = "a" * 40
    monkeypatch.setattr(generator, "_validated_release", lambda *_: (commit, "main"))
    monkeypatch.setattr(generator, "release_paths", lambda *_: (artifact, root / "wordpress/project-atlas-metadata-bridge"))
    monkeypatch.setattr(generator, "artifact_sha256", lambda *_: release.SOURCE_EXPECTATIONS.plugin_zip_sha256)
    output = root / ".runtime/atlas-release.json"
    monkeypatch.setattr(sys, "argv", ["generator", "--project-root", str(root), "--output", str(output), "--release-version", "v0.59.8"])
    generator.main()
    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert manifest == {
        "manifest_schema_version": 2,
        "source_compatibility_id": "project-atlas-release-identity-v0.59.8",
        "atlas_version": "v0.59.8",
        "atlas_commit": commit,
        "atlas_tag": "v0.59.8",
        "plugin_version": "0.57.4",
        "plugin_zip_filename": "project-atlas-metadata-bridge-0.57.4.zip",
        "plugin_zip_sha256": release.SOURCE_EXPECTATIONS.plugin_zip_sha256,
        "generated_at": manifest["generated_at"],
    }


def test_generator_rejects_unsupported_schema_and_plugin_mismatch(monkeypatch, tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    output = root / ".runtime/atlas-release.json"
    monkeypatch.setattr(sys, "argv", ["generator", "--project-root", str(root), "--output", str(output), "--release-version", "v0.59.8", "--manifest-schema-version", "1"])
    with pytest.raises(SystemExit, match="Unsupported"):
        generator.main()
    assert not output.exists()

    artifact = root / "artifact.zip"
    artifact.write_bytes(b"wrong")
    monkeypatch.setattr(generator, "_validated_release", lambda *_: ("a" * 40, "main"))
    monkeypatch.setattr(generator, "release_paths", lambda *_: (artifact, root))
    monkeypatch.setattr(generator, "artifact_sha256", lambda *_: "0" * 64)
    monkeypatch.setattr(sys, "argv", ["generator", "--project-root", str(root), "--output", str(output), "--release-version", "v0.59.8"])
    with pytest.raises(SystemExit, match="plugin ZIP checksum"):
        generator.main()
    assert not output.exists()
