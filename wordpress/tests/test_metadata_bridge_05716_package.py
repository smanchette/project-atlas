from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path, PurePosixPath
import re
import zipfile


ROOT = Path(__file__).resolve().parents[2]
PREDECESSOR = ROOT / "wordpress/project-atlas-metadata-bridge-0.57.15"
SOURCE = ROOT / "wordpress/project-atlas-metadata-bridge-0.57.16"
BUILDER = ROOT / "wordpress/build_plugin_05716_zip.py"
ZIP = ROOT / "wordpress/dist/project-atlas-metadata-bridge-0.57.16.zip"
PREDECESSOR_ZIP = (
    ROOT / "wordpress/dist/project-atlas-metadata-bridge-0.57.15.zip"
)
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
    "includes/performance-local-v5-page-payload.php",
    "project-atlas-metadata-bridge.php",
}
SEALED_05715_HASHES = {
    "README.md": "29555c9eb0f2d604e29628d6f701c318e72c85f03cbeb4b91beb6638e7e5e793",
    "assets/performance-local-v5.css": "aa5c45c69c7a2ce4998a4af38f1c32ef3483fff2871da210eabd3635d199bbde",
    "assets/performance-local-v5.js": "82928c37ea6ef1e608b4a9232687f97d610ae95edf63e160019c1af21eff2ce4",
    "includes/performance-local-v5-form-delivery.php": "21c03258d41f4015b9e6aa25f91d8f0f3552553bb97e40c7ef14e1d26add7a50",
    "includes/performance-local-v5-page-payload.php": "f2392cfd8663e89d6f9bbf838f6f9cc33d2d531633650d5e66b712c0781e5580",
    "includes/performance-local-v5-renderer.php": "e553de043df2de661ba70210b94536dcb5e9cb83c5952bb022e44832605ee910",
    "project-atlas-metadata-bridge.php": "53eb87eabe9d7b1a6c8bb8362240797d9280a38b9a035d48e2ca9693499ebff2",
    "templates/performance-local-v5-page.php": "84af149dfeea3bb8e3764e78f61533e7e018bb689c28657c5aeeb4f24854add2",
}
SEALED_05715_ZIP = (
    61_297,
    "03600857bdbdba83168ef13e14eebf9b0809b9570bf3512950a912d1b3392946",
)
SEALED_CHECKSUM_PREFIX = (
    3_471,
    "32ec3c0f51653272fa3d4740e0f241d00fe83e3c20e7a09bb9318acf4c01ba4a",
)
SEALED_05716_HASHES = {
    "README.md": "fec17d1896316294717d9902207b635567fba07de121d52a7380d63df1d420dd",
    "assets/performance-local-v5.css": "aa5c45c69c7a2ce4998a4af38f1c32ef3483fff2871da210eabd3635d199bbde",
    "assets/performance-local-v5.js": "82928c37ea6ef1e608b4a9232687f97d610ae95edf63e160019c1af21eff2ce4",
    "includes/performance-local-v5-form-delivery.php": "21c03258d41f4015b9e6aa25f91d8f0f3552553bb97e40c7ef14e1d26add7a50",
    "includes/performance-local-v5-page-payload.php": "60e4c86834de02a118466fcccdd42373709ef83d806d59b11d37dd21ace8aa95",
    "includes/performance-local-v5-renderer.php": "e553de043df2de661ba70210b94536dcb5e9cb83c5952bb022e44832605ee910",
    "project-atlas-metadata-bridge.php": "63b6c0fb3f21c0a86f0e0505e074dfaed5f5c98923948bb61e492cef3415ada7",
    "templates/performance-local-v5-page.php": "84af149dfeea3bb8e3764e78f61533e7e018bb689c28657c5aeeb4f24854add2",
}
SEALED_05716_ZIP = (
    61_804,
    "bf178481649137fb9e08c4697fe39a9286cbc7b6316fc56b725ce5740fb086b1",
)
EXPECTED_05716_ATTRIBUTES = (
    "build_plugin_05716_zip.py text eol=lf",
    "project-atlas-metadata-bridge-0.57.16/** text eol=lf",
    "tests/metadata-bridge-05716-form-configuration.php text eol=lf",
    "tests/metadata-bridge-05716-public-contact-privacy.php text eol=lf",
    "tests/test_metadata_bridge_05716_form_configuration.py text eol=lf",
    "tests/test_metadata_bridge_05716_package.py text eol=lf",
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
    spec = importlib.util.spec_from_file_location("atlas_plugin_05716_builder", BUILDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_05715_source_package_and_checksum_entry_remain_byte_exact() -> None:
    actual = {
        path: _sha256_bytes(content)
        for path, content in _source_files(PREDECESSOR).items()
    }
    assert actual == SEALED_05715_HASHES
    assert PREDECESSOR_ZIP.stat().st_size == SEALED_05715_ZIP[0]
    assert _sha256(PREDECESSOR_ZIP) == SEALED_05715_ZIP[1]
    predecessor_line = (
        f"{SEALED_05715_ZIP[1]}  "
        "wordpress/dist/project-atlas-metadata-bridge-0.57.15.zip\n"
    ).encode("ascii")
    assert CHECKSUMS.read_bytes().count(predecessor_line) == 1


def test_05716_is_exact_eight_file_three_change_successor() -> None:
    predecessor = _source_files(PREDECESSOR)
    successor = _source_files(SOURCE)
    assert tuple(sorted(predecessor)) == tuple(sorted(successor)) == EXPECTED_FILES
    assert {
        path for path in EXPECTED_FILES if predecessor[path] != successor[path]
    } == CHANGED_FILES
    for path in set(EXPECTED_FILES) - CHANGED_FILES:
        assert successor[path] == predecessor[path], path
    assert {
        path: _sha256_bytes(content) for path, content in successor.items()
    } == SEALED_05716_HASHES

    bootstrap = successor["project-atlas-metadata-bridge.php"].decode("utf-8")
    assert "Plugin Name: Project Atlas Metadata Bridge" in bootstrap
    assert "Version: 0.57.16" in bootstrap
    assert "define('ATLAS_METADATA_BRIDGE_VERSION', '0.57.16');" in bootstrap
    assert bootstrap.count("require_once") == 3


def test_05716_builder_inputs_are_exact_without_generating_a_package() -> None:
    builder = _load_builder()
    assert builder.SOURCE == SOURCE
    assert builder.OUTPUT == (
        ROOT / "wordpress/dist/project-atlas-metadata-bridge-0.57.16.zip"
    )
    assert builder.EXPECTED_FILES == EXPECTED_FILES
    assert builder.FIXED_TIMESTAMP == (2026, 9, 4, 0, 0, 0)
    assert builder.ARCHIVE_ROOT == ARCHIVE_ROOT
    assert [relative for relative, _ in builder._source_files()] == list(EXPECTED_FILES)


def test_05716_builder_is_deterministic_portable_and_archive_exact(tmp_path: Path) -> None:
    builder = _load_builder()
    output = tmp_path / ZIP.name
    builder.OUTPUT = output
    first = builder.build().read_bytes()
    second = builder.build().read_bytes()
    assert first == second == ZIP.read_bytes()
    assert len(first) == SEALED_05716_ZIP[0]
    assert _sha256_bytes(first) == SEALED_05716_ZIP[1]

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


def test_05716_checksum_is_one_raw_append_to_sealed_05715_ledger() -> None:
    raw = CHECKSUMS.read_bytes()
    prefix_size, prefix_hash = SEALED_CHECKSUM_PREFIX
    expected_line = (
        f"{SEALED_05716_ZIP[1]}  "
        "wordpress/dist/project-atlas-metadata-bridge-0.57.16.zip\n"
    ).encode("ascii")
    assert len(raw[:prefix_size]) == prefix_size
    assert _sha256_bytes(raw[:prefix_size]) == prefix_hash
    assert raw[prefix_size:] == expected_line
    assert raw.count(expected_line) == 1
    assert ZIP.stat().st_size == SEALED_05716_ZIP[0]
    assert _sha256(ZIP) == SEALED_05716_ZIP[1]


def test_05716_archive_forbids_mail_literals_secrets_and_residue() -> None:
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
    assert re.search(
        r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text
    ) is None
    for pattern in (
        r"-----BEGIN [A-Z ]+PRIVATE KEY-----",
        r"(?i)authorization\s*:\s*(?:basic|bearer)\s+",
        r"(?i)(?:password|passwd|api[_-]?key|client[_-]?secret|access[_-]?token)"
        r"\s*[=:]\s*['\"][^'\"]+",
        r"(?i)https?://[^\s/:@]+:[^\s/@]+@",
    ):
        assert re.search(pattern, text) is None


def test_05716_privacy_delta_is_narrow_and_fail_closed() -> None:
    route = SOURCE.joinpath(
        "includes/performance-local-v5-page-payload.php"
    ).read_text(encoding="utf-8")
    assert "atlas_performance_local_v5_page_payload_final_conversion_index" in route
    assert "($section['key'] ?? null) !== 'final_conversion'" in route
    assert "$candidate_final_index === $prior_final_index" in route
    assert "$candidate_section === $prior_section" in route
    assert "$candidate_body === $prior_body" in route
    assert "$recipient_scan['sections'][$candidate_final_index]['body'] = null" in route
    assert route.index("$has_from && str_contains") < route.index(
        "$recipient_scan['sections'][$candidate_final_index]['body'] = null"
    )

    readme = SOURCE.joinpath("README.md").read_text(encoding="utf-8")
    for expected in (
        "Metadata Bridge 0.57.16",
        "single `final_conversion` section",
        "same list position",
        "complete section records are byte-identical",
        "recipient-only exemptions",
        "prohibited everywhere",
    ):
        assert expected in readme


def test_05716_source_is_regular_contained_private_and_lf_bound() -> None:
    source_root = SOURCE.resolve(strict=True)
    assert not SOURCE.is_symlink()
    files = []
    contents = []
    for path in SOURCE.rglob("*"):
        assert not path.is_symlink(), path
        path.resolve(strict=True).relative_to(source_root)
        if path.is_file():
            files.append(path.relative_to(SOURCE).as_posix())
            content = path.read_bytes()
            contents.append(content)
            assert b"\r\n" not in content, path
    assert tuple(sorted(files)) == EXPECTED_FILES
    assert re.search(
        rb"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
        b"\n".join(contents),
    ) is None

    for path in (
        BUILDER,
        ROOT / "wordpress/tests/metadata-bridge-05716-form-configuration.php",
        ROOT / "wordpress/tests/metadata-bridge-05716-public-contact-privacy.php",
        ROOT / "wordpress/tests/test_metadata_bridge_05716_form_configuration.py",
        ROOT / "wordpress/tests/test_metadata_bridge_05716_package.py",
    ):
        assert b"\r\n" not in path.read_bytes(), path

    attributes = tuple(GITATTRIBUTES.read_text(encoding="utf-8").splitlines())
    for expected in EXPECTED_05716_ATTRIBUTES:
        assert attributes.count(expected) == 1
    start = attributes.index(EXPECTED_05716_ATTRIBUTES[0])
    assert attributes[start:start + len(EXPECTED_05716_ATTRIBUTES)] == (
        EXPECTED_05716_ATTRIBUTES
    )
