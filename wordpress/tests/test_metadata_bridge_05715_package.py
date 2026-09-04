from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path, PurePosixPath
import re
import zipfile


ROOT = Path(__file__).resolve().parents[2]
PREDECESSOR = ROOT / "wordpress/project-atlas-metadata-bridge-0.57.14"
SOURCE = ROOT / "wordpress/project-atlas-metadata-bridge-0.57.15"
BUILDER = ROOT / "wordpress/build_plugin_05715_zip.py"
ZIP = ROOT / "wordpress/dist/project-atlas-metadata-bridge-0.57.15.zip"
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
    "includes/performance-local-v5-form-delivery.php",
    "includes/performance-local-v5-page-payload.php",
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
SEALED_05714_ZIP = (
    54_054,
    "cfe30d62182efe36aafb9c1e8c91e678fb572a06936b700529c1f9c5531e3490",
)
SEALED_CHECKSUM_PREFIX = (
    3_348,
    "63ee6c7bbae15c3c1c6e81dc16f6910afd2a35f1410dbe1809d48d64ea8e5816",
)
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
EXPECTED_05715_ATTRIBUTES = (
    "build_plugin_05715_zip.py text eol=lf",
    "project-atlas-metadata-bridge-0.57.15/** text eol=lf",
    "tests/metadata-bridge-05715-form-configuration.php text eol=lf",
    "tests/metadata-bridge-05715-public-contact-privacy.php text eol=lf",
    "tests/test_metadata_bridge_05715_form_configuration.py text eol=lf",
    "tests/test_metadata_bridge_05715_package.py text eol=lf",
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
    spec = importlib.util.spec_from_file_location("atlas_plugin_05715_builder", BUILDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _function(source: str, name: str) -> str:
    match = re.search(
        rf"function {re.escape(name)}\([^)]*\)(?:\s*:\s*[^{{]+)?\s*{{", source
    )
    assert match, name
    depth = 1
    index = match.end()
    while depth and index < len(source):
        depth += (source[index] == "{") - (source[index] == "}")
        index += 1
    assert depth == 0, name
    return source[match.start():index]


def test_05714_source_and_package_remain_byte_exact() -> None:
    actual = {
        path: _sha256_bytes(content)
        for path, content in _source_files(PREDECESSOR).items()
    }
    assert actual == SEALED_05714_HASHES
    assert ZIP.parent.joinpath("project-atlas-metadata-bridge-0.57.14.zip").stat().st_size == SEALED_05714_ZIP[0]
    assert _sha256(ZIP.parent / "project-atlas-metadata-bridge-0.57.14.zip") == SEALED_05714_ZIP[1]


def test_05715_is_exact_eight_file_three_change_successor() -> None:
    predecessor = _source_files(PREDECESSOR)
    successor = _source_files(SOURCE)
    assert tuple(sorted(predecessor)) == tuple(sorted(successor)) == EXPECTED_FILES
    assert {path for path in EXPECTED_FILES if predecessor[path] != successor[path]} == CHANGED_FILES
    for path in set(EXPECTED_FILES) - CHANGED_FILES:
        assert successor[path] == predecessor[path], path
    assert {
        path: _sha256_bytes(content) for path, content in successor.items()
    } == SEALED_05715_HASHES

    bootstrap = successor["project-atlas-metadata-bridge.php"].decode("utf-8")
    assert "Version: 0.57.15" in bootstrap
    assert "define('ATLAS_METADATA_BRIDGE_VERSION', '0.57.15');" in bootstrap
    assert bootstrap.count("require_once") == 3


def test_05715_public_contact_derivation_is_exact_v5_page_bound_and_fail_closed() -> None:
    predecessor = PREDECESSOR.joinpath("project-atlas-metadata-bridge.php").read_text(
        encoding="utf-8"
    )
    successor = SOURCE.joinpath("project-atlas-metadata-bridge.php").read_text(
        encoding="utf-8"
    )
    derive = _function(successor, "atlas_metadata_approved_public_contact_email")
    approved = _function(successor, "atlas_metadata_approved_payload")
    assert "get_post(ATLAS_METADATA_POST_ID)" in derive
    assert "ATLAS_PERFORMANCE_LOCAL_V5_META_KEY" in derive
    assert "atlas_performance_local_v5_payload_is_valid($payload)" in derive
    for exact_identity in (
        "drywood-termite-tenting-orlando-fl",
        "generated-page:41",
        "composition:41:v10",
        "19f313d10c024cbc988c7cac63e15bb5e7ea78b14c65af243f41e23f5967af32",
        "website:1",
    ):
        assert exact_identity in derive
    assert "($payload['footer']['contact_email'] ?? null) === $email" in derive
    assert "$public_contact_email = atlas_metadata_approved_public_contact_email();" in approved
    assert "if ($public_contact_email === null) { return []; }" in approved
    assert "'email'=>$public_contact_email" in approved

    email_literal = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
    predecessor_literals = set(email_literal.findall(predecessor))
    successor_literals = set(email_literal.findall(successor))
    assert len(predecessor_literals) == 1
    assert successor_literals == set()


def test_05715_private_admin_contract_and_public_surface_separation() -> None:
    delivery = SOURCE.joinpath(
        "includes/performance-local-v5-form-delivery.php"
    ).read_text(encoding="utf-8")
    render = _function(
        delivery, "atlas_performance_local_v5_form_delivery_admin_render_page"
    )
    handler = _function(
        delivery, "atlas_performance_local_v5_form_delivery_admin_handle_post"
    )
    authorization = _function(
        delivery,
        "atlas_performance_local_v5_form_delivery_admin_request_is_authorized",
    )
    assert "add_options_page(" in delivery
    assert "'manage_options'" in delivery
    assert "admin_post_' . ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_ACTION" in delivery
    assert "admin_post_nopriv" not in delivery
    assert "admin_request_is_authorized($input)" in handler
    assert "($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST'" in authorization
    assert "wp_verify_nonce(" in authorization
    assert "value=\"\"" in render
    assert "_wp_http_referer" not in render
    assert "register_rest_route(" not in render + handler
    for public_file in (
        SOURCE / "assets/performance-local-v5.js",
        SOURCE / "includes/performance-local-v5-renderer.php",
    ):
        text = public_file.read_text(encoding="utf-8").lower()
        assert "recipient_email" not in text
        assert "from_email" not in text
    page_payload = SOURCE.joinpath(
        "includes/performance-local-v5-page-payload.php"
    ).read_text(encoding="utf-8")
    inspect = _function(
        page_payload, "atlas_performance_local_v5_page_payload_inspect"
    ).lower()
    assert "recipient_email" not in inspect
    assert "from_email" not in inspect


def test_05715_source_is_regular_contained_and_has_exact_lf_contract() -> None:
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
    for expected in EXPECTED_05715_ATTRIBUTES:
        assert attributes.count(expected) == 1
    start = attributes.index(EXPECTED_05715_ATTRIBUTES[0])
    assert attributes[start:start + len(EXPECTED_05715_ATTRIBUTES)] == EXPECTED_05715_ATTRIBUTES


def test_05715_builder_is_deterministic_portable_and_archive_exact(tmp_path: Path) -> None:
    builder = _load_builder()
    assert builder.EXPECTED_FILES == EXPECTED_FILES
    assert builder.FIXED_TIMESTAMP == (2026, 9, 3, 0, 0, 0)
    assert builder.ARCHIVE_ROOT == ARCHIVE_ROOT
    output = tmp_path / ZIP.name
    builder.OUTPUT = output
    first = builder.build().read_bytes()
    second = builder.build().read_bytes()
    assert first == second == ZIP.read_bytes()
    assert len(first) == SEALED_05715_ZIP[0]
    assert _sha256_bytes(first) == SEALED_05715_ZIP[1]

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


def test_05715_checksum_is_one_raw_append_to_sealed_05714_ledger() -> None:
    raw = CHECKSUMS.read_bytes()
    prefix_size, prefix_hash = SEALED_CHECKSUM_PREFIX
    expected_line = (
        f"{SEALED_05715_ZIP[1]}  "
        "wordpress/dist/project-atlas-metadata-bridge-0.57.15.zip\n"
    ).encode("ascii")
    assert len(raw[:prefix_size]) == prefix_size
    assert _sha256_bytes(raw[:prefix_size]) == prefix_hash
    assert raw[prefix_size:prefix_size + len(expected_line)] == expected_line
    assert raw.count(expected_line) == 1
    assert ZIP.stat().st_size == SEALED_05715_ZIP[0]
    assert _sha256(ZIP) == SEALED_05715_ZIP[1]


def test_05715_archive_forbids_new_mail_literals_secrets_and_residue() -> None:
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
