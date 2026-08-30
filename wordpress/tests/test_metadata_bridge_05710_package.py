from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path, PurePosixPath
import re
import zipfile


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "wordpress/project-atlas-metadata-bridge-0.57.10"
BUILDER = ROOT / "wordpress/build_plugin_05710_zip.py"
ZIP = ROOT / "wordpress/dist/project-atlas-metadata-bridge-0.57.10.zip"
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_builder():
    spec = importlib.util.spec_from_file_location("atlas_plugin_05710_builder", BUILDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_05710_builder_is_deterministic_portable_and_source_exact(tmp_path: Path) -> None:
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


def test_05710_built_package_has_one_exact_checksum_entry() -> None:
    assert ZIP.is_file()
    lines = CHECKSUMS.read_text(encoding="utf-8").splitlines()
    path = "wordpress/dist/project-atlas-metadata-bridge-0.57.10.zip"
    matching = [line for line in lines if line.endswith(f"  {path}")]
    assert matching == [f"{_sha256(ZIP)}  {path}"]
    assert sum(
        line.endswith("  wordpress/dist/project-atlas-metadata-bridge-0.57.9.zip")
        for line in lines
    ) == 1
    assert any(
        line
        == "67157288e8e941025cd81f1b7bfec8a23cb079aec0dace1aa5fe191087698fda"
        "  wordpress/dist/project-atlas-metadata-bridge-0.57.9.zip"
        for line in lines
    )


def test_05710_archive_forbids_secrets_residue_and_unrelated_files() -> None:
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
