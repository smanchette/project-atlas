from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path, PurePosixPath
import re
import zipfile


ROOT = Path(__file__).resolve().parents[2]
PREDECESSOR = ROOT / "wordpress/project-atlas-metadata-bridge-0.57.13"
SOURCE = ROOT / "wordpress/project-atlas-metadata-bridge-0.57.14"
BUILDER = ROOT / "wordpress/build_plugin_05714_zip.py"
ZIP = ROOT / "wordpress/dist/project-atlas-metadata-bridge-0.57.14.zip"
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
SEALED_05714_HASHES = {
    "README.md": "e56d51c15decec4d99059efd39b9077859fc60873c120598b9f2685b7715d5f6",
    "assets/performance-local-v5.css": "aa5c45c69c7a2ce4998a4af38f1c32ef3483fff2871da210eabd3635d199bbde",
    "assets/performance-local-v5.js": "82928c37ea6ef1e608b4a9232687f97d610ae95edf63e160019c1af21eff2ce4",
    "includes/performance-local-v5-form-delivery.php": "cf351cc4e9cfbef487263ba67e32edd62cb5ae9e1c58f9b88e71cf7f86aad1be",
    "includes/performance-local-v5-page-payload.php": "4c7571ec1b701c17d173fca928b1c6c8389fb6c834442d019679902da2b60388",
    "includes/performance-local-v5-renderer.php": "e553de043df2de661ba70210b94536dcb5e9cb83c5952bb022e44832605ee910",
    "project-atlas-metadata-bridge.php": "617777ad40c25abb060fd0edc407152174643a6c1870a0b9596cc41e9deca2fd",
    "templates/performance-local-v5-page.php": "84af149dfeea3bb8e3764e78f61533e7e018bb689c28657c5aeeb4f24854add2",
}
SEALED_PACKAGE_LINEAGE = {
    "0.57.9": (47_094, "67157288e8e941025cd81f1b7bfec8a23cb079aec0dace1aa5fe191087698fda", "1759bcc401ad68556ae0a6f0106f77e916719c031c1d41e98ddaccc0fc56ad69"),
    "0.57.10": (52_802, "4b263e1dc373fef32bb8c137bf066e676cdc9b2efcaa54c61690765eaa817845", "5251ba0faf9e155c1f1e9ad7d739f50645217f3db69495657e2b362a0e8ae64d"),
    "0.57.11": (53_142, "38eb127420d1ab7f48500f6410c23af4c425020ba31607aa70ab2a72271b7cfe", "6d8ea038bc89ce236e2a9bbe42a76ac7889a32f3b75a1f49b704f34be4a724f1"),
    "0.57.12": (53_683, "1b5d5cd88fbb22d94a4b2bc3226542ddf33e8a841bd4c27835a2cccd28428a74", "c4d68affd6d55de70dff337bc261a447fafa126ca958c67eb03b88a55972bd30"),
    "0.57.13": (53_901, "19eb24479263fd7651e5b4fbf35c1f10f73ae0581fd806f32f58aa808393417f", "0b4d6c37238f49cd89d2c03596db7443c1190b854aee5d526071e61de1204171"),
}
SEALED_05714_ZIP = (54_054, "cfe30d62182efe36aafb9c1e8c91e678fb572a06936b700529c1f9c5531e3490")
SEALED_CHECKSUM_PREFIX = (3_225, "3d1b609b94b96ace57b7f8519145cd6def601226131a3a1307ca7677b6f123a5")
EXPECTED_05714_ATTRIBUTES = (
    "build_plugin_05714_zip.py text eol=lf",
    "sync_performance_local_v5_css_05714.py text eol=lf",
    "project-atlas-metadata-bridge-0.57.14/** text eol=lf",
    "tests/performance-local-v5-sticky-scroll-regression.js text eol=lf",
    "tests/test_metadata_bridge_05714_package.py text eol=lf",
    "tests/test_metadata_bridge_05714_typography_contract.py text eol=lf",
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


def _source_manifest_sha256(root: Path) -> str:
    rows = []
    for relative, content in sorted(
        _source_files(root).items(), key=lambda item: item[0].casefold()
    ):
        rows.append(f"{relative}\t{len(content)}\t{_sha256_bytes(content)}\n")
    return _sha256_bytes("".join(rows).encode("utf-8"))


def _load_builder():
    spec = importlib.util.spec_from_file_location("atlas_plugin_05714_builder", BUILDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_0579_through_05713_sources_and_packages_remain_byte_exact() -> None:
    raw = CHECKSUMS.read_bytes()
    size, digest = SEALED_CHECKSUM_PREFIX
    assert len(raw) > size
    assert _sha256_bytes(raw[:size]) == digest
    for version, (expected_bytes, expected_zip, expected_source) in SEALED_PACKAGE_LINEAGE.items():
        source = ROOT / "wordpress" / f"project-atlas-metadata-bridge-{version}"
        package = ROOT / "wordpress/dist" / f"project-atlas-metadata-bridge-{version}.zip"
        assert package.stat().st_size == expected_bytes
        assert _sha256(package) == expected_zip
        assert _source_manifest_sha256(source) == expected_source


def test_05714_is_the_exact_eight_file_three_change_successor() -> None:
    predecessor = _source_files(PREDECESSOR)
    successor = _source_files(SOURCE)
    assert tuple(sorted(predecessor)) == tuple(sorted(successor)) == EXPECTED_FILES
    assert {path for path in EXPECTED_FILES if predecessor[path] != successor[path]} == CHANGED_FILES
    for path in set(EXPECTED_FILES) - CHANGED_FILES:
        assert successor[path] == predecessor[path], path
    assert {path: _sha256_bytes(content) for path, content in successor.items()} == SEALED_05714_HASHES

    expected_bootstrap = predecessor["project-atlas-metadata-bridge.php"].replace(
        b"Version: 0.57.13", b"Version: 0.57.14", 1
    ).replace(
        b"define('ATLAS_METADATA_BRIDGE_VERSION', '0.57.13');",
        b"define('ATLAS_METADATA_BRIDGE_VERSION', '0.57.14');",
        1,
    )
    assert successor["project-atlas-metadata-bridge.php"] == expected_bootstrap


def test_05714_source_is_regular_contained_and_has_exact_lf_contract() -> None:
    source_root = SOURCE.resolve(strict=True)
    assert not SOURCE.is_symlink()
    files = []
    for path in SOURCE.rglob("*"):
        assert not path.is_symlink(), path
        path.resolve(strict=True).relative_to(source_root)
        if path.is_file():
            files.append(path.relative_to(SOURCE).as_posix())
    assert tuple(sorted(files)) == EXPECTED_FILES
    attributes = tuple(GITATTRIBUTES.read_text(encoding="utf-8").splitlines())
    for expected in EXPECTED_05714_ATTRIBUTES:
        assert attributes.count(expected) == 1
    start = attributes.index(EXPECTED_05714_ATTRIBUTES[0])
    assert attributes[start:start + len(EXPECTED_05714_ATTRIBUTES)] == EXPECTED_05714_ATTRIBUTES


def test_05714_builder_is_deterministic_portable_and_archive_exact(tmp_path: Path) -> None:
    builder = _load_builder()
    assert builder.EXPECTED_FILES == EXPECTED_FILES
    assert builder.FIXED_TIMESTAMP == (2026, 9, 3, 0, 0, 0)
    assert builder.ARCHIVE_ROOT == ARCHIVE_ROOT
    output = tmp_path / ZIP.name
    builder.OUTPUT = output
    first = builder.build().read_bytes()
    second = builder.build().read_bytes()
    assert first == second == ZIP.read_bytes()
    assert len(first) == SEALED_05714_ZIP[0]
    assert _sha256_bytes(first) == SEALED_05714_ZIP[1]

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
        actual = {name: archive.read(name) for name in names}
    assert names == expected_names
    assert actual == expected_bytes
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
        assert ".." not in path.parts


def test_05714_checksum_is_one_raw_append_to_the_sealed_05713_ledger() -> None:
    raw = CHECKSUMS.read_bytes()
    prefix_size, prefix_hash = SEALED_CHECKSUM_PREFIX
    expected_line = (
        f"{SEALED_05714_ZIP[1]}  "
        "wordpress/dist/project-atlas-metadata-bridge-0.57.14.zip\n"
    ).encode("ascii")
    assert len(raw[:prefix_size]) == prefix_size
    assert _sha256_bytes(raw[:prefix_size]) == prefix_hash
    assert raw[prefix_size:prefix_size + len(expected_line)] == expected_line
    assert raw.count(expected_line) == 1
    assert ZIP.stat().st_size == SEALED_05714_ZIP[0]
    assert _sha256(ZIP) == SEALED_05714_ZIP[1]


def test_05714_archive_forbids_secrets_private_data_and_residue() -> None:
    with zipfile.ZipFile(ZIP) as archive:
        names = archive.namelist()
        contents = b"\n".join(archive.read(name) for name in names)
    normalized_names = "\n".join(names).lower()
    for forbidden in (
        ".git", ".runtime", ".env", "credential", "database", "backup",
        "fixture", "test", "screenshot", "diagnostic",
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
