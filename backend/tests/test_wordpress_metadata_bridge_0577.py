from __future__ import annotations

import hashlib
from pathlib import PurePosixPath
import re
import zipfile

from app.services.wordpress_deployment_release import SOURCE_EXPECTATIONS, resolve_program_root


ROOT = resolve_program_root()
SOURCE = ROOT / "wordpress/project-atlas-metadata-bridge-0.57.7"
PHP = SOURCE / "project-atlas-metadata-bridge.php"
ZIP = ROOT / "wordpress/dist/project-atlas-metadata-bridge-0.57.7.zip"


def _function(source: str, name: str) -> str:
    match = re.search(rf"function {re.escape(name)}\([^)]*\)(?:\s*:\s*[^{{]+)?\s*{{", source)
    assert match, f"missing {name}"
    depth = 1
    index = match.end()
    while depth and index < len(source):
        depth += (source[index] == "{") - (source[index] == "}")
        index += 1
    assert depth == 0
    return source[match.start():index]


def test_0577_release_identity_and_portable_zip_are_exact():
    assert SOURCE_EXPECTATIONS.plugin_version == "0.57.7"
    assert SOURCE_EXPECTATIONS.plugin_zip_sha256 == "ada4d97ea627a148d07fda809c1776a91a87d7a7e4957de3bece423a9bb80a62"
    assert hashlib.sha256(ZIP.read_bytes()).hexdigest() == SOURCE_EXPECTATIONS.plugin_zip_sha256
    with zipfile.ZipFile(ZIP) as archive:
        names = archive.namelist()
        actual = {name: archive.read(name) for name in names if not name.endswith("/")}
    expected = {
        f"project-atlas-metadata-bridge/{path.relative_to(SOURCE).as_posix()}": path.read_bytes()
        for path in SOURCE.rglob("*") if path.is_file()
    }
    assert actual == expected
    assert len(names) == len(set(names)) == 2
    assert all("\\" not in name and ".." not in PurePosixPath(name).parts for name in names)


def test_pure_renderer_is_query_context_independent_and_deterministic():
    source = PHP.read_text(encoding="utf-8")
    renderer = _function(source, "atlas_metadata_head_markup_from_snapshot")
    for forbidden in (
        "is_page(", "is_admin(", "wp_doing_ajax(", "wp_doing_cron(",
        "is_feed(", "is_search(", "is_archive(", "is_preview(", "REST_REQUEST",
        "get_post_meta(", "get_option(", "update_", "delete_", "wp_remote_",
    ):
        assert forbidden not in renderer
    assert "atlas_metadata_validate_payload" in renderer
    assert "atlas_metadata_hash" in renderer
    assert "(string) $snapshot['revision'] !== '1'" in renderer
    assert "!$snapshot['enabled_metadata_state']" in renderer
    assert "meta name=\"description\"" in renderer
    assert "application/ld+json" in renderer
    assert "JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE" in renderer


def test_public_wrapper_is_strict_and_rest_preview_calls_pure_renderer_directly():
    source = PHP.read_text(encoding="utf-8")
    public_guard = _function(source, "atlas_metadata_public_request_is_page_8")
    wrapper = _function(source, "atlas_metadata_head_markup")
    preview = _function(source, "atlas_metadata_rendering_preview")
    for required in (
        "!is_admin()", "!wp_doing_ajax()", "!wp_doing_cron()", "REST_REQUEST",
        "WP_CLI", "!is_feed()", "!is_search()", "!is_archive()", "!is_preview()",
        "is_page(ATLAS_METADATA_POST_ID)",
    ):
        assert required in public_guard
    assert "atlas_metadata_public_request_is_page_8()" in wrapper
    assert "atlas_metadata_head_markup_from_snapshot(atlas_metadata_snapshot())" in wrapper
    assert "get_post(ATLAS_METADATA_POST_ID)" in preview
    assert "atlas_metadata_head_markup_from_snapshot($snapshot)" in preview
    assert "atlas_metadata_head_markup()" not in preview
    assert "is_page(" not in preview
    assert "'read_only' => true" in preview
    for forbidden in ("update_", "delete_", "wp_remote_", "client.post", "wp_insert", "wp_update"):
        assert forbidden not in preview


def test_preview_failure_contract_and_public_hook_remain_narrow():
    source = PHP.read_text(encoding="utf-8")
    preview = _function(source, "atlas_metadata_rendering_preview")
    assert "atlas_post_changed" in preview
    assert "atlas_rendering_preview_unavailable" in preview
    assert "['status' => 409]" in preview
    hook = source[source.index("add_action('wp_head'"):]
    assert "echo atlas_metadata_head_markup();" in hook
    assert "}, 20);" in hook
    assert "Version: 0.57.7" in source
    assert "ATLAS_METADATA_BRIDGE_VERSION', '0.57.7'" in source
