from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path, PurePosixPath
import re
import zipfile


ROOT = Path(__file__).resolve().parents[2]
SOURCE_05711 = ROOT / "wordpress/project-atlas-metadata-bridge-0.57.11"
SOURCE = ROOT / "wordpress/project-atlas-metadata-bridge-0.57.12"
BUILDER = ROOT / "wordpress/build_plugin_05712_zip.py"
ZIP = ROOT / "wordpress/dist/project-atlas-metadata-bridge-0.57.12.zip"
CHECKSUMS = ROOT / "wordpress/checksums.sha256"
GITATTRIBUTES = ROOT / "wordpress/.gitattributes"
ARCHIVE_ROOT = "project-atlas-metadata-bridge"
EXPECTED_FILES = (
    "README.md",
    "assets/performance-local-v5.css",
    "assets/performance-local-v5.js",
    "includes/performance-local-v5-form-delivery.php",
    "includes/performance-local-v5-page-payload.php",
    "includes/performance-local-v5-renderer.php",
    "project-atlas-metadata-bridge.php",
    "templates/performance-local-v5-page.php",
)
CHANGED_FILES = {
    "README.md",
    "assets/performance-local-v5.css",
    "project-atlas-metadata-bridge.php",
}
SEALED_05711_HASHES = {
    "README.md": "dda5728950f80cc2c0d5be6f9ba5602de5db20a42724c09b08969eec24268cec",
    "assets/performance-local-v5.css": "3a227011edb8dcd56e6a30ba701dddc488c7bb1b3c5556530c49cb4b39a4445e",
    "assets/performance-local-v5.js": "82928c37ea6ef1e608b4a9232687f97d610ae95edf63e160019c1af21eff2ce4",
    "includes/performance-local-v5-form-delivery.php": "cf351cc4e9cfbef487263ba67e32edd62cb5ae9e1c58f9b88e71cf7f86aad1be",
    "includes/performance-local-v5-page-payload.php": "4c7571ec1b701c17d173fca928b1c6c8389fb6c834442d019679902da2b60388",
    "includes/performance-local-v5-renderer.php": "e553de043df2de661ba70210b94536dcb5e9cb83c5952bb022e44832605ee910",
    "project-atlas-metadata-bridge.php": "c9a7c411b0bb57e06f9705c9a20ed29c14524cd489046082c3116a585be06453",
    "templates/performance-local-v5-page.php": "84af149dfeea3bb8e3764e78f61533e7e018bb689c28657c5aeeb4f24854add2",
}
SEALED_05712_CSS_SHA256 = (
    "b0834b9e8fde7dee64d645fe831a8e862736006a15b21b0e7cf8b14e15fe49e3"
)
SEALED_05712_README_SHA256 = (
    "c30eac425aa25a6a301f36e387c1815b05f789d1b806861c42b8ef05910f1acb"
)
SEALED_05712_BOOTSTRAP_SHA256 = (
    "bf911878c1cf4e0e1ba1bcd6707a942dabd04f1a0a40a7e2843296a6a65ac9c2"
)
SEALED_PREDECESSOR_PACKAGES = {
    "project-atlas-metadata-bridge-0.57.9.zip": (
        47_094,
        "67157288e8e941025cd81f1b7bfec8a23cb079aec0dace1aa5fe191087698fda",
    ),
    "project-atlas-metadata-bridge-0.57.10.zip": (
        52_802,
        "4b263e1dc373fef32bb8c137bf066e676cdc9b2efcaa54c61690765eaa817845",
    ),
    "project-atlas-metadata-bridge-0.57.11.zip": (
        53_142,
        "38eb127420d1ab7f48500f6410c23af4c425020ba31607aa70ab2a72271b7cfe",
    ),
}
SEALED_CHECKSUM_PREFIX_CANONICAL_SIZE = 2_979
SEALED_CHECKSUM_PREFIX_CANONICAL_SHA256 = (
    "914a4c0423b888f714a25b82eff97c91e089123a5caf451b2729ce332d5ed247"
)
EXPECTED_LF_ATTRIBUTES = (
    ".gitattributes text eol=lf",
    "checksums.sha256 text eol=lf",
    "build_plugin_05712_zip.py text eol=lf",
    "sync_performance_local_v5_css_05712.py text eol=lf",
    "project-atlas-metadata-bridge-0.57.12/** text eol=lf",
    "tests/test_metadata_bridge_05712_package.py text eol=lf",
    "tests/test_metadata_bridge_05712_sticky_contract.py text eol=lf",
)


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _source_files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _load_builder():
    spec = importlib.util.spec_from_file_location("atlas_plugin_05712_builder", BUILDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_05711_source_and_all_predecessor_packages_remain_byte_exact() -> None:
    actual = {
        relative: _sha256_bytes(content)
        for relative, content in _source_files(SOURCE_05711).items()
    }
    assert actual == SEALED_05711_HASHES
    for filename, (expected_size, expected_sha256) in SEALED_PREDECESSOR_PACKAGES.items():
        package = ROOT / "wordpress/dist" / filename
        assert package.stat().st_size == expected_size
        assert _sha256(package) == expected_sha256


def test_05712_is_the_exact_eight_file_successor_with_only_three_changed_files() -> None:
    predecessor = _source_files(SOURCE_05711)
    successor = _source_files(SOURCE)
    assert tuple(sorted(predecessor)) == tuple(sorted(successor)) == EXPECTED_FILES
    assert {
        relative
        for relative in EXPECTED_FILES
        if predecessor[relative] != successor[relative]
    } == CHANGED_FILES
    for relative in set(EXPECTED_FILES) - CHANGED_FILES:
        assert successor[relative] == predecessor[relative], relative

    bootstrap = successor["project-atlas-metadata-bridge.php"].decode("utf-8")
    assert "Version: 0.57.12" in bootstrap
    assert "define('ATLAS_METADATA_BRIDGE_VERSION', '0.57.12');" in bootstrap
    assert "Version: 0.57.11" not in bootstrap
    assert "define('ATLAS_METADATA_BRIDGE_VERSION', '0.57.11');" not in bootstrap
    assert bootstrap.count("require_once") == 3
    assert _sha256(SOURCE / "assets/performance-local-v5.css") == SEALED_05712_CSS_SHA256
    assert _sha256(SOURCE / "README.md") == SEALED_05712_README_SHA256
    assert (
        _sha256(SOURCE / "project-atlas-metadata-bridge.php")
        == SEALED_05712_BOOTSTRAP_SHA256
    )

    expected_bootstrap = predecessor["project-atlas-metadata-bridge.php"].replace(
        b"Version: 0.57.11",
        b"Version: 0.57.12",
        1,
    ).replace(
        b"define('ATLAS_METADATA_BRIDGE_VERSION', '0.57.11');",
        b"define('ATLAS_METADATA_BRIDGE_VERSION', '0.57.12');",
        1,
    )
    assert successor["project-atlas-metadata-bridge.php"] == expected_bootstrap


def test_05712_source_inventory_is_regular_contained_and_symbolic_link_free() -> None:
    source_root = SOURCE.resolve(strict=True)
    assert not SOURCE.is_symlink()
    files: list[str] = []
    for path in SOURCE.rglob("*"):
        assert not path.is_symlink(), path
        path.resolve(strict=True).relative_to(source_root)
        if path.is_file():
            files.append(path.relative_to(SOURCE).as_posix())
    assert tuple(sorted(files)) == EXPECTED_FILES


def test_05712_build_inputs_have_an_exact_lf_checkout_contract() -> None:
    assert tuple(GITATTRIBUTES.read_text(encoding="utf-8").splitlines()) == (
        EXPECTED_LF_ATTRIBUTES
    )


def test_05712_builder_is_deterministic_portable_and_actual_archive_exact(
    tmp_path: Path,
) -> None:
    builder = _load_builder()
    assert builder.EXPECTED_FILES == EXPECTED_FILES
    assert builder.FIXED_TIMESTAMP == (2026, 9, 1, 0, 0, 0)
    assert builder.ARCHIVE_ROOT == ARCHIVE_ROOT

    output = tmp_path / ZIP.name
    builder.OUTPUT = output
    first = builder.build()
    first_bytes = first.read_bytes()
    second = builder.build()
    second_bytes = second.read_bytes()
    assert first == second == output
    assert first_bytes == second_bytes == ZIP.read_bytes()

    expected_names = [f"{ARCHIVE_ROOT}/{relative}" for relative in EXPECTED_FILES]
    expected_bytes = {
        f"{ARCHIVE_ROOT}/{relative}": content
        for relative, content in _source_files(SOURCE).items()
    }
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert archive.comment == b""
        infos = archive.infolist()
        names = [info.filename for info in infos]
        actual_bytes = {name: archive.read(name) for name in names}
    assert names == expected_names
    assert len(names) == len(set(names)) == len(EXPECTED_FILES)
    assert actual_bytes == expected_bytes
    for info in infos:
        assert info.date_time == builder.FIXED_TIMESTAMP
        assert info.create_system == 3
        assert info.compress_type == zipfile.ZIP_DEFLATED
        assert info.external_attr >> 16 == 0o100644
        assert info.extra == b""
        assert info.comment == b""
        assert not info.is_dir()
        path = PurePosixPath(info.filename)
        assert path.parts[0] == ARCHIVE_ROOT
        assert "\\" not in info.filename
        assert not info.filename.startswith(("/", "\\"))
        assert ".." not in path.parts


def test_05712_checksum_is_one_exact_append_to_the_sealed_canonical_prefix() -> None:
    assert ZIP.is_file()
    archive_path = "wordpress/dist/project-atlas-metadata-bridge-0.57.12.zip"
    expected_line = f"{_sha256(ZIP)}  {archive_path}"
    lines = CHECKSUMS.read_text(encoding="utf-8").splitlines()
    assert lines[-1] == expected_line
    assert lines.count(expected_line) == 1
    canonical_prefix = ("\n".join(lines[:-1]) + "\n").encode("utf-8")
    assert len(canonical_prefix) == SEALED_CHECKSUM_PREFIX_CANONICAL_SIZE
    assert _sha256_bytes(canonical_prefix) == SEALED_CHECKSUM_PREFIX_CANONICAL_SHA256


def test_05712_archive_forbids_secrets_residue_and_unrelated_files() -> None:
    with zipfile.ZipFile(ZIP) as archive:
        assert archive.testzip() is None
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
        "screenshot",
        "diagnostic",
    ):
        assert forbidden not in normalized_names
    text = contents.decode("utf-8")
    for pattern in (
        r"-----BEGIN [A-Z ]+PRIVATE KEY-----",
        r"(?i)authorization\s*:\s*(?:basic|bearer)\s+",
        r"(?i)(?:password|passwd|api[_-]?key|client[_-]?secret|access[_-]?token)"
        r"\s*[=:]\s*['\"][^'\"]+",
        r"(?i)https?://[^\s/:@]+:[^\s/@]+@",
    ):
        assert re.search(pattern, text) is None
