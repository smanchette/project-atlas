from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path, PurePosixPath
import re
import zipfile


ROOT = Path(__file__).resolve().parents[2]
SOURCE_05710 = ROOT / "wordpress/project-atlas-metadata-bridge-0.57.10"
SOURCE_0579 = ROOT / "wordpress/project-atlas-metadata-bridge-0.57.9"
SOURCE = ROOT / "wordpress/project-atlas-metadata-bridge-0.57.11"
BUILDER = ROOT / "wordpress/build_plugin_05711_zip.py"
ZIP = ROOT / "wordpress/dist/project-atlas-metadata-bridge-0.57.11.zip"
CHECKSUMS = ROOT / "wordpress/checksums.sha256"
ARCHIVE_ROOT = "project-atlas-metadata-bridge"
EXPECTED_FILES = {
    "README.md",
    "assets/performance-local-v5.css",
    "assets/performance-local-v5.js",
    "includes/performance-local-v5-form-delivery.php",
    "includes/performance-local-v5-page-payload.php",
    "includes/performance-local-v5-renderer.php",
    "project-atlas-metadata-bridge.php",
    "templates/performance-local-v5-page.php",
}
SEALED_05710_HASHES = {
    "README.md": "5e778ed37ff18d74ac7255e249e7f6045a03bab3fd1243576cb845fe628f21ba",
    "assets/performance-local-v5.css": "3a227011edb8dcd56e6a30ba701dddc488c7bb1b3c5556530c49cb4b39a4445e",
    "assets/performance-local-v5.js": "82928c37ea6ef1e608b4a9232687f97d610ae95edf63e160019c1af21eff2ce4",
    "includes/performance-local-v5-form-delivery.php": "cf351cc4e9cfbef487263ba67e32edd62cb5ae9e1c58f9b88e71cf7f86aad1be",
    "includes/performance-local-v5-page-payload.php": "4c7571ec1b701c17d173fca928b1c6c8389fb6c834442d019679902da2b60388",
    "includes/performance-local-v5-renderer.php": "90cd58beb60b460b277c824e220e1e7f943ee6564f45dd08bd3e8993f94f2c96",
    "project-atlas-metadata-bridge.php": "daa816f4eb85579ddc3c0ad5cc5fb212cf414effaf9970e5494dbbdbccc61777",
    "templates/performance-local-v5-page.php": "84af149dfeea3bb8e3764e78f61533e7e018bb689c28657c5aeeb4f24854add2",
}
SEALED_0579_HASHES = {
    "README.md": "89c523814c5c40057e74146f1676a063985b49cbef5fc1f4fafa1c86753556fd",
    "assets/performance-local-v5.css": "3a227011edb8dcd56e6a30ba701dddc488c7bb1b3c5556530c49cb4b39a4445e",
    "assets/performance-local-v5.js": "82928c37ea6ef1e608b4a9232687f97d610ae95edf63e160019c1af21eff2ce4",
    "includes/performance-local-v5-form-delivery.php": "cf351cc4e9cfbef487263ba67e32edd62cb5ae9e1c58f9b88e71cf7f86aad1be",
    "includes/performance-local-v5-renderer.php": "90cd58beb60b460b277c824e220e1e7f943ee6564f45dd08bd3e8993f94f2c96",
    "project-atlas-metadata-bridge.php": "04442109ab766ea808b79afd63b4c83385e9d873996db781c5c800d3b3f93938",
    "templates/performance-local-v5-page.php": "84af149dfeea3bb8e3764e78f61533e7e018bb689c28657c5aeeb4f24854add2",
}
SEALED_PREDECESSOR_PACKAGES = {
    "project-atlas-metadata-bridge-0.57.9.zip": (
        47_094,
        "67157288e8e941025cd81f1b7bfec8a23cb079aec0dace1aa5fe191087698fda",
    ),
    "project-atlas-metadata-bridge-0.57.10.zip": (
        52_802,
        "4b263e1dc373fef32bb8c137bf066e676cdc9b2efcaa54c61690765eaa817845",
    ),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_builder():
    spec = importlib.util.spec_from_file_location("atlas_plugin_05711_builder", BUILDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_05710_source_remains_byte_exact() -> None:
    actual = {
        path.relative_to(SOURCE_05710).as_posix(): _sha256(path)
        for path in SOURCE_05710.rglob("*")
        if path.is_file()
    }
    assert actual == SEALED_05710_HASHES


def test_0579_source_and_predecessor_packages_remain_byte_exact() -> None:
    actual = {
        path.relative_to(SOURCE_0579).as_posix(): _sha256(path)
        for path in SOURCE_0579.rglob("*")
        if path.is_file()
    }
    assert actual == SEALED_0579_HASHES
    for filename, (expected_size, expected_sha256) in (
        SEALED_PREDECESSOR_PACKAGES.items()
    ):
        path = ROOT / "wordpress/dist" / filename
        assert path.stat().st_size == expected_size
        assert _sha256(path) == expected_sha256


def test_05711_changes_only_version_readme_and_asset_path_validator() -> None:
    old_files = {
        path.relative_to(SOURCE_05710).as_posix(): path.read_bytes()
        for path in SOURCE_05710.rglob("*")
        if path.is_file()
    }
    new_files = {
        path.relative_to(SOURCE).as_posix(): path.read_bytes()
        for path in SOURCE.rglob("*")
        if path.is_file()
    }
    assert set(old_files) == set(new_files) == EXPECTED_FILES
    assert {
        relative
        for relative in EXPECTED_FILES
        if old_files[relative] != new_files[relative]
    } == {
        "README.md",
        "includes/performance-local-v5-renderer.php",
        "project-atlas-metadata-bridge.php",
    }
    for relative in (
        "assets/performance-local-v5.css",
        "assets/performance-local-v5.js",
        "includes/performance-local-v5-form-delivery.php",
        "includes/performance-local-v5-page-payload.php",
        "templates/performance-local-v5-page.php",
    ):
        assert new_files[relative] == old_files[relative], relative

    bootstrap = new_files["project-atlas-metadata-bridge.php"].decode("utf-8")
    assert "Version: 0.57.11" in bootstrap
    assert "define('ATLAS_METADATA_BRIDGE_VERSION', '0.57.11');" in bootstrap
    assert bootstrap.count("require_once") == 3


def test_05711_builder_is_deterministic_portable_and_source_exact(tmp_path: Path) -> None:
    builder = _load_builder()
    output = tmp_path / ZIP.name
    builder.OUTPUT = output
    first = builder.build()
    first_bytes = first.read_bytes()
    second = builder.build()
    assert first == second == output
    assert second.read_bytes() == first_bytes

    source_files = {
        path.relative_to(SOURCE).as_posix(): path.read_bytes()
        for path in SOURCE.rglob("*")
        if path.is_file()
    }
    assert set(source_files) == EXPECTED_FILES
    expected = {
        f"{ARCHIVE_ROOT}/{relative}": content
        for relative, content in source_files.items()
    }
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        actual = {name: archive.read(name) for name in names if not name.endswith("/")}
        timestamps = {archive.getinfo(name).date_time for name in names}
        modes = {archive.getinfo(name).external_attr >> 16 for name in names}
    assert actual == expected
    assert len(names) == len(set(names)) == len(EXPECTED_FILES)
    assert timestamps == {builder.FIXED_TIMESTAMP}
    assert modes == {0o100644}
    assert {PurePosixPath(name).parts[0] for name in names} == {ARCHIVE_ROOT}
    assert all("\\" not in name for name in names)
    assert all(not name.startswith(("/", "\\")) for name in names)
    assert all(".." not in PurePosixPath(name).parts for name in names)


def test_05711_built_package_has_one_exact_append_only_checksum_entry() -> None:
    assert ZIP.is_file()
    lines = CHECKSUMS.read_text(encoding="utf-8").splitlines()
    path = "wordpress/dist/project-atlas-metadata-bridge-0.57.11.zip"
    matching = [line for line in lines if line.endswith(f"  {path}")]
    assert matching == [f"{_sha256(ZIP)}  {path}"]
    assert sum(
        line.endswith("  wordpress/dist/project-atlas-metadata-bridge-0.57.10.zip")
        for line in lines
    ) == 1
    assert (
        "4b263e1dc373fef32bb8c137bf066e676cdc9b2efcaa54c61690765eaa817845"
        "  wordpress/dist/project-atlas-metadata-bridge-0.57.10.zip"
    ) in lines
    assert lines.index(matching[0]) == lines.index(
        "4b263e1dc373fef32bb8c137bf066e676cdc9b2efcaa54c61690765eaa817845"
        "  wordpress/dist/project-atlas-metadata-bridge-0.57.10.zip"
    ) + 1


def test_05711_archive_forbids_secrets_residue_and_unrelated_files() -> None:
    with zipfile.ZipFile(ZIP) as archive:
        names = archive.namelist()
        contents = b"\n".join(archive.read(name) for name in names)
    normalized_names = "\n".join(names).lower()
    for forbidden in (
        ".git",
        ".runtime",
        ".env",
        "credential",
        "database",
        "backup",
        "fixture",
        "test",
    ):
        assert forbidden not in normalized_names
    text = contents.decode("utf-8")
    for pattern in (
        r"-----BEGIN [A-Z ]+PRIVATE KEY-----",
        r"(?i)authorization\s*:\s*basic\s+",
        r"(?i)(?:password|api[_-]?key|client[_-]?secret)\s*[=:]\s*['\"][^'\"]+",
    ):
        assert re.search(pattern, text) is None
