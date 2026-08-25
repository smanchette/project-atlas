from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path, PurePosixPath
import re
import zipfile

from app.services.wordpress_deployment_release import SOURCE_EXPECTATIONS, resolve_program_root


ROOT = resolve_program_root()
SOURCE_0577 = ROOT / "wordpress/project-atlas-metadata-bridge-0.57.7"
SOURCE = ROOT / "wordpress/project-atlas-metadata-bridge-0.57.8"
MAIN_0577 = SOURCE_0577 / "project-atlas-metadata-bridge.php"
MAIN = SOURCE / "project-atlas-metadata-bridge.php"
MODULE = SOURCE / "includes/performance-local-v5-renderer.php"
TEMPLATE = SOURCE / "templates/performance-local-v5-page.php"
STYLESHEET = SOURCE / "assets/performance-local-v5.css"
SCRIPT = SOURCE / "assets/performance-local-v5.js"
README = SOURCE / "README.md"
BUILDER = ROOT / "wordpress/build_plugin_0578_zip.py"
ZIP = ROOT / "wordpress/dist/project-atlas-metadata-bridge-0.57.8.zip"

PRESERVED_0577_HASHES = {
    "project-atlas-metadata-bridge.php": "3ee9c323103190e182970ee71631720814cc1d3590629fefb1f044cb6b1bcc5f",
    "README.md": "6bce8d206ef1670eb57f0b7039885d754cd2537714f5cdb396b58f0a8eb20881",
    "../dist/project-atlas-metadata-bridge-0.57.7.zip": "ada4d97ea627a148d07fda809c1776a91a87d7a7e4957de3bece423a9bb80a62",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _function(source: str, name: str) -> str:
    match = re.search(rf"function {re.escape(name)}\([^)]*\)(?:\s*:\s*[^{{]+)?\s*{{", source)
    assert match, f"missing {name}"
    depth = 1
    index = match.end()
    while depth and index < len(source):
        depth += (source[index] == "{") - (source[index] == "}")
        index += 1
    assert depth == 0, f"unbalanced function {name}"
    return source[match.start():index]


def _load_builder():
    spec = importlib.util.spec_from_file_location("atlas_plugin_0578_builder", BUILDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_0578_is_an_append_only_semantic_successor_and_0577_is_unchanged() -> None:
    assert _sha256(MAIN_0577) == PRESERVED_0577_HASHES["project-atlas-metadata-bridge.php"]
    assert _sha256(SOURCE_0577 / "README.md") == PRESERVED_0577_HASHES["README.md"]
    assert _sha256(ROOT / "wordpress/dist/project-atlas-metadata-bridge-0.57.7.zip") == (
        PRESERVED_0577_HASHES["../dist/project-atlas-metadata-bridge-0.57.7.zip"]
    )

    old = MAIN_0577.read_text(encoding="utf-8")
    expected = old.replace(
        "Description: Guarded Orlando-only metadata rendering bridge for Project Atlas.",
        "Description: Guarded metadata bridge with a local-only Performance Local V5 rehearsal renderer.",
    ).replace("0.57.7", "0.57.8")
    anchor = "define('ATLAS_METADATA_CANONICAL_URL', 'https://www.drywoodtenting.com/drywood-termite-tenting-orlando-fl/');"
    expected = expected.replace(
        anchor,
        anchor + "\n\nrequire_once __DIR__ . '/includes/performance-local-v5-renderer.php';",
    )
    assert MAIN.read_text(encoding="utf-8") == expected
    assert MAIN.read_text(encoding="utf-8").count("require_once") == 1

    release_source = (ROOT / "backend/app/services/wordpress_deployment_release.py").read_text(encoding="utf-8")
    assert SOURCE_EXPECTATIONS.plugin_version == "0.57.7"
    assert 'plugin_version="0.57.7"' in release_source
    assert "0.57.8" not in release_source


def test_local_only_payload_gates_template_and_assets_without_a_new_route() -> None:
    source = MODULE.read_text(encoding="utf-8")
    current_payload = _function(source, "atlas_performance_local_v5_current_payload")
    template_filter = _function(source, "atlas_performance_local_v5_template_include")
    enqueue = _function(source, "atlas_performance_local_v5_enqueue_assets")
    validator = _function(source, "atlas_performance_local_v5_validate_payload")

    assert "wp_get_environment_type() === 'local'" in source
    assert "ATLAS_PERFORMANCE_LOCAL_V5_META_KEY" in source
    assert "_project_atlas_performance_local_v5_v1" in source
    assert "'show_in_rest' => false" in source
    assert "atlas_performance_local_v5_public_page_request()" in current_payload
    assert "atlas_performance_local_v5_payload_is_valid($payload)" in current_payload
    assert "atlas_performance_local_v5_current_payload() === null" in template_filter
    assert "ATLAS_PERFORMANCE_LOCAL_V5_TEMPLATE" in template_filter
    assert "atlas_performance_local_v5_current_payload() === null" in enqueue
    assert "performance-local-v5.css" in enqueue and "performance-local-v5.js" in enqueue
    assert "rehearsal_only" in validator and "!== true" in validator
    assert "project-atlas-performance-local-v5-wordpress@1" in source
    assert all(surface in validator for surface in ("city_service", "estimate", "special_demo"))

    for forbidden in (
        "register_rest_route",
        "wp_mail",
        "wp_remote_",
        "update_post_meta",
        "add_post_meta",
        "delete_post_meta",
        "wp_insert_post",
        "wp_update_post",
    ):
        assert forbidden not in source


def test_renderer_is_generic_and_special_map_and_form_are_inert() -> None:
    sources = {
        "module": MODULE.read_text(encoding="utf-8"),
        "template": TEMPLATE.read_text(encoding="utf-8"),
        "script": SCRIPT.read_text(encoding="utf-8"),
    }
    joined = "\n".join(sources.values()).lower()
    for forbidden in (
        "page 41",
        "page41",
        "orlando",
        "flo-zone",
        "drywoodtenting.com",
        "theme_lab",
        "theme-lab",
        "wordpress_post_id",
        "https://",
        "http://",
    ):
        assert forbidden not in joined

    module = sources["module"]
    render_form = _function(module, "atlas_performance_local_v5_render_form")
    render_map = _function(module, "atlas_performance_local_v5_render_location_map")
    assert "DEMO SPECIAL — NOT SITE CONTENT" in module
    assert "DEMO MAP — NOT SITE CONTENT" in module
    assert "!in_array(count($value['fields']), [5, 6], true)" in module
    assert "email_address" in module
    assert "readonly" in render_form and "disabled" in render_form
    assert "data-atlas-v5-inert-form" in render_form
    assert not re.search(r"<form[^>]+\b(?:action|method)=", render_form, re.IGNORECASE | re.DOTALL)
    assert not re.search(r"<(?:input|textarea)[^>]+\bname=", render_form, re.IGNORECASE | re.DOTALL)
    assert "<iframe" not in render_map.lower()
    assert "embed_src" not in render_map
    assert "wp_head();" in sources["template"] and "wp_footer();" in sources["template"]
    assert "get_header(" not in sources["template"] and "get_footer(" not in sources["template"]
    assert sources["template"].count("<title>") == 1
    assert "remove_action('wp_head', '_wp_render_title_tag', 1);" in sources["template"]
    assert "$atlas_v5_payload['page']['meta_title']" in sources["template"]
    assert "project-atlas-v5-template" in sources["template"]
    assert "projectAtlasV5Root" in module
    assert 'class="previewBrandLogo"' in module
    assert 'class="previewFooterLogo"' in module
    assert "data-atlas-v5-back-to-top hidden" in module

    script = sources["script"]
    for forbidden in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon", "serviceWorker"):
        assert forbidden not in script
    assert "preventDefault()" in script
    assert 'root.setAttribute("data-v5-menu-open", value)' in script
    assert 'legacySite.setAttribute("data-mobile-menu-open", value)' in script
    assert 'header.setAttribute("data-v5-menu-open", value)' in script
    assert "setMenuState(true)" in script and "setMenuState(false)" in script
    assert 'element.closest("[hidden]")' in script
    assert "element.getClientRects().length > 0" in script
    assert "Math.max(480, window.innerHeight * 0.75)" in script
    assert 'window.addEventListener("scroll", updateBackToTop' in script
    assert "backToTop.hidden =" in script
    assert "footer.getBoundingClientRect().top <= window.innerHeight" in script


def test_exact_contract_markers_and_fail_closed_optional_modules_are_present() -> None:
    source = MODULE.read_text(encoding="utf-8")
    exact_record = _function(source, "atlas_performance_local_v5_exact_record")
    optional_modules = _function(source, "atlas_performance_local_v5_optional_modules")
    render_review = _function(source, "atlas_performance_local_v5_render_review_trust")
    render_location = _function(source, "atlas_performance_local_v5_render_location_map")
    top_keys = (
        "schema_version", "surface", "rehearsal_only", "payload_identity", "website",
        "navigation", "page", "sticky_action", "hero", "sections", "related_pages",
        "faq", "optional_modules", "form", "conditional", "footer", "theme",
    )
    assert "array_keys($value)" in exact_record and "$actual === $expected_keys" in exact_record
    assert all(f"'{key}'" in source for key in top_keys)
    assert "local_rehearsal" in source
    assert "theme_lab_demo" not in source
    assert "=== null || atlas_performance_local_v5_review_trust" in optional_modules
    assert "=== null || atlas_performance_local_v5_location_map" in optional_modules
    assert "if ($module === null) { return; }" in render_review
    assert "if ($module === null) { return; }" in render_location


def test_city_service_final_conversion_is_single_source_driven_and_rendered_last() -> None:
    source = MODULE.read_text(encoding="utf-8")
    validator = _function(source, "atlas_performance_local_v5_validate_payload")
    sections = _function(source, "atlas_performance_local_v5_render_sections")
    final = _function(source, "atlas_performance_local_v5_render_final_conversion")
    city = _function(source, "atlas_performance_local_v5_render_city_service")

    assert "$final_conversion_count !== 1" in validator
    assert "Final conversion cannot contain detached media." in validator
    assert "if ($section['key'] === 'final_conversion') { continue; }" in sections
    assert 'class="performanceLocalFinalCta"' in final
    assert "$section['heading']" in final and "$section['body']" in final
    assert "$website['phone_href']" in final and "$website['phone_display']" in final
    assert "'mailto:' . $website['contact_email']" in final
    assert "atlas_performance_local_v5_render_form($payload['form'], true)" in final

    order = [
        city.index("atlas_performance_local_v5_render_sections"),
        city.index("atlas_performance_local_v5_render_related_pages"),
        city.index("atlas_performance_local_v5_render_faq"),
        city.index("atlas_performance_local_v5_render_location_map"),
        city.index("atlas_performance_local_v5_render_final_conversion"),
    ]
    assert order == sorted(order)
    assert city.count("performanceLocalFinalCta") == 0


def test_header_navigation_deduplicates_utility_by_exact_primary_href() -> None:
    source = MODULE.read_text(encoding="utf-8")
    navigation = _function(source, "atlas_performance_local_v5_navigation_tree")

    assert "$primary_hrefs[$item['href']] = true" in navigation
    assert "if (isset($primary_hrefs[$item['href']])) { continue; }" in navigation
    assert navigation.index("foreach ($navigation['primary']") < navigation.index("foreach ($navigation['utility']")
    assert "strtolower" not in navigation and "levenshtein" not in navigation


def test_city_hero_uses_only_the_validated_governed_phone_with_an_icon() -> None:
    source = MODULE.read_text(encoding="utf-8")
    hero_call = _function(source, "atlas_performance_local_v5_render_hero_call")
    hero = _function(source, "atlas_performance_local_v5_render_hero")

    assert "atlas_performance_local_v5_text($website['phone_display'], 80)" in hero_call
    assert "atlas_performance_local_v5_tel_href($website['phone_href'])" in hero_call
    assert "$phone_display = $website['phone_display']" in hero_call
    assert "$phone_href = $website['phone_href']" in hero_call
    assert 'class="performanceLocalButton performanceLocalPhone"' in hero_call
    assert '<svg width="18" height="18"' in hero_call and 'aria-hidden="true"' in hero_call
    assert "esc_url($phone_href)" in hero_call
    assert "esc_html('Call ' . $phone_display)" in hero_call
    assert "return;" in hero_call
    assert "atlas_performance_local_v5_render_hero_call($payload['website'] ?? null)" in hero
    assert "$hero['call_action']['label']" not in hero
    assert "$hero['call_action']['href']" not in hero
    assert "$hero['estimate_action']['label']" in hero
    assert "$hero['estimate_action']['href']" in hero


def test_all_surfaces_share_mobile_navigation_without_changing_desktop_classes() -> None:
    source = MODULE.read_text(encoding="utf-8")
    trigger = _function(source, "atlas_performance_local_v5_render_mobile_menu_trigger")
    drawer = _function(source, "atlas_performance_local_v5_render_mobile_drawer")
    header = _function(source, "atlas_performance_local_v5_render_header")
    city = _function(source, "atlas_performance_local_v5_render_city_service")
    estimate = _function(source, "atlas_performance_local_v5_render_estimate")
    special = _function(source, "atlas_performance_local_v5_render_special")

    assert "performanceLocalMobileNavigation" in trigger
    assert "performanceLocalMenuTrigger" in trigger
    assert "performanceLocalV5MenuTrigger" in trigger
    assert "performanceLocalV5HeaderActions" not in trigger
    assert "data-atlas-v5-menu-toggle" in trigger
    assert "performanceLocalDrawerBackdrop" in drawer
    assert "performanceLocalV5DrawerBackdrop" in drawer
    assert "performanceLocalDrawer" in drawer
    assert "performanceLocalV5Drawer" in drawer
    assert "data-atlas-v5-mobile-nav" in drawer
    assert "data-atlas-v5-menu-close" in drawer
    assert "<?php if ($legacy): ?>" in drawer
    assert drawer.count('data-atlas-v5-menu-close') == 2

    for unchanged_desktop_class in (
        "performanceLocalHeader", "performanceLocalV5Header",
        "performanceLocalContainer performanceLocalHeaderInner",
        "performanceLocalV5Container performanceLocalV5HeaderInner",
        "performanceLocalBrand", "performanceLocalV5Brand",
        "performanceLocalDesktopNavigation", "performanceLocalV5DesktopNav",
    ):
        assert unchanged_desktop_class in header
    assert "atlas_performance_local_v5_render_mobile_menu_trigger($payload, $legacy)" in header
    assert "atlas_performance_local_v5_render_mobile_drawer($website, $tree, $legacy)" in header
    assert "performanceLocalV5HeaderActions" not in header
    assert "atlas_performance_local_v5_render_header($payload, true)" in city
    assert "atlas_performance_local_v5_render_header($payload, false)" in estimate
    assert "atlas_performance_local_v5_render_header($payload, false)" in special


def test_location_map_supports_only_null_city_area_and_local_business_location() -> None:
    source = MODULE.read_text(encoding="utf-8")
    validator = _function(source, "atlas_performance_local_v5_location_map")
    optional = _function(source, "atlas_performance_local_v5_optional_modules")
    renderer = _function(source, "atlas_performance_local_v5_render_location_map")
    payload_validator = _function(source, "atlas_performance_local_v5_validate_payload")

    assert "city_service_area" in validator and "business_location" in validator
    assert all(
        f"'{key}'" in validator
        for key in (
            "approved_location_name", "address_lines", "description", "phone_action",
            "directions_action", "map_title", "embed_src", "demo_label", "presentation",
        )
    )
    assert "target_city" in validator and "target_state" in validator
    assert "atlas_performance_local_v5_tel_href" in validator
    assert "atlas_performance_local_v5_internal_href" in validator
    assert "$value['embed_src'] !== null" in validator
    assert "ATLAS_PERFORMANCE_LOCAL_V5_MAP_MARKER" in validator
    assert "local_rehearsal" in validator
    assert "business_location" in payload_validator
    assert "differs from the governed website phone" in payload_validator
    assert "=== null || atlas_performance_local_v5_location_map" in optional

    assert "$module['approved_location_name']" in renderer
    assert "$module['address_lines']" in renderer and "<address>" in renderer
    assert "$module['phone_action']" in renderer
    assert "$module['directions_action']" in renderer
    assert "<iframe" not in renderer.lower() and "embed_src" not in renderer


def test_0578_builder_is_deterministic_portable_and_byte_exact() -> None:
    builder = _load_builder()
    first = builder.build()
    first_hash = _sha256(first)
    second = builder.build()
    assert first == second == ZIP
    assert _sha256(second) == first_hash

    expected = {
        f"project-atlas-metadata-bridge/{path.relative_to(SOURCE).as_posix()}": path.read_bytes()
        for path in SOURCE.rglob("*")
        if path.is_file()
    }
    with zipfile.ZipFile(ZIP) as archive:
        names = archive.namelist()
        actual = {name: archive.read(name) for name in names if not name.endswith("/")}
        timestamps = {archive.getinfo(name).date_time for name in names}
        modes = {archive.getinfo(name).external_attr >> 16 for name in names}

    assert actual == expected
    assert len(names) == len(set(names))
    assert timestamps == {(2026, 8, 24, 0, 0, 0)}
    assert modes == {0o100644}
    assert all("\\" not in name for name in names)
    assert all(not name.startswith(("/", "\\")) for name in names)
    assert all(".." not in PurePosixPath(name).parts for name in names)
    assert {PurePosixPath(name).parts[0] for name in names} == {"project-atlas-metadata-bridge"}
    assert {
        "project-atlas-metadata-bridge/project-atlas-metadata-bridge.php",
        "project-atlas-metadata-bridge/includes/performance-local-v5-renderer.php",
        "project-atlas-metadata-bridge/templates/performance-local-v5-page.php",
        "project-atlas-metadata-bridge/assets/performance-local-v5.css",
        "project-atlas-metadata-bridge/assets/performance-local-v5.js",
        "project-atlas-metadata-bridge/README.md",
    }.issubset(actual)


def test_readme_keeps_0578_rehearsal_only_and_production_release_blocked() -> None:
    readme = README.read_text(encoding="utf-8")
    assert "append-only local rehearsal successor" in readme
    assert "rehearsal_only" in readme
    assert "registers no REST route" in readme
    assert "sends no mail" in readme
    assert "stores no submission data" in readme
    assert "production deployment release remains locked" in readme
    assert "0.57.7" in readme
