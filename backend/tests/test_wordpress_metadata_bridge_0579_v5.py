from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path, PurePosixPath
import re
import zipfile

from app.services.wordpress_deployment_release import SOURCE_EXPECTATIONS, resolve_program_root


ROOT = resolve_program_root()
SOURCE_0578 = ROOT / "wordpress/project-atlas-metadata-bridge-0.57.8"
SOURCE = ROOT / "wordpress/project-atlas-metadata-bridge-0.57.9"
MAIN = SOURCE / "project-atlas-metadata-bridge.php"
RENDERER = SOURCE / "includes/performance-local-v5-renderer.php"
DELIVERY = SOURCE / "includes/performance-local-v5-form-delivery.php"
TEMPLATE = SOURCE / "templates/performance-local-v5-page.php"
STYLESHEET = SOURCE / "assets/performance-local-v5.css"
SCRIPT = SOURCE / "assets/performance-local-v5.js"
README = SOURCE / "README.md"
BUILDER = ROOT / "wordpress/build_plugin_0579_zip.py"
ZIP = ROOT / "wordpress/dist/project-atlas-metadata-bridge-0.57.9.zip"

PRESERVED_0578_HASHES = {
    "project-atlas-metadata-bridge.php": "7bc5b89db94860cbe4406211ff2db5e9fdd4e12bc490740f560f1ec28bc140e8",
    "includes/performance-local-v5-renderer.php": "8a5dbd29e97c68117b7e95b83a908f5a2ac8318aee21eea341b2623d2edae9a8",
    "templates/performance-local-v5-page.php": "84af149dfeea3bb8e3764e78f61533e7e018bb689c28657c5aeeb4f24854add2",
    "assets/performance-local-v5.css": "a7cc1128879fa0d5bd1d335991159967a07a0ef6cda1ff4500d3a1eec47dcea7",
    "assets/performance-local-v5.js": "be3f1d4684d01f15e97d99cc5d073ea1b12199502697c4407282eed9b4d4858e",
    "README.md": "6df391bfe24f903b93587bd5da792d129f48101c624f4977291d560ccb93fca6",
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
    assert depth == 0, f"unbalanced {name}"
    return source[match.start():index]


def _load_builder():
    spec = importlib.util.spec_from_file_location("atlas_plugin_0579_builder", BUILDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_0579_is_append_only_and_every_0578_package_byte_is_preserved() -> None:
    assert {path.relative_to(SOURCE_0578).as_posix() for path in SOURCE_0578.rglob("*") if path.is_file()} == set(PRESERVED_0578_HASHES)
    for relative, expected in PRESERVED_0578_HASHES.items():
        assert _sha256(SOURCE_0578 / relative) == expected


def test_0579_package_identity_and_contained_module_are_exact() -> None:
    main = MAIN.read_text(encoding="utf-8")
    assert "Version: 0.57.9" in main
    assert "define('ATLAS_METADATA_BRIDGE_VERSION', '0.57.9');" in main
    assert main.count("require_once") == 2
    assert "require_once __DIR__ . '/includes/performance-local-v5-renderer.php';" in main
    assert "require_once __DIR__ . '/includes/performance-local-v5-form-delivery.php';" in main
    assert DELIVERY.is_file()
    assert SOURCE_EXPECTATIONS.plugin_version == "0.57.7"


def test_all_unchanged_renderer_functions_and_template_remain_byte_exact() -> None:
    old = (SOURCE_0578 / "includes/performance-local-v5-renderer.php").read_text(encoding="utf-8")
    new = RENDERER.read_text(encoding="utf-8")
    old_names = set(re.findall(r"function (atlas_performance_local_v5_[a-z0-9_]+)\(", old))
    new_names = set(re.findall(r"function (atlas_performance_local_v5_[a-z0-9_]+)\(", new))
    assert old_names == new_names
    changed = {
        "atlas_performance_local_v5_runtime_files",
        "atlas_performance_local_v5_website",
        "atlas_performance_local_v5_footer",
        "atlas_performance_local_v5_render_final_conversion",
        "atlas_performance_local_v5_render_form",
        "atlas_performance_local_v5_render_footer",
    }
    for name in sorted(old_names - changed):
        assert _function(new, name) == _function(old, name), name
    assert TEMPLATE.read_bytes() == (SOURCE_0578 / "templates/performance-local-v5-page.php").read_bytes()


def test_inert_form_branch_retains_the_0578_runtime_contract_in_one_template() -> None:
    new = _function(RENDERER.read_text(encoding="utf-8"), "atlas_performance_local_v5_render_form")
    assert new.count("<form") == 1
    assert new.count("foreach ($form['fields'] as $field)") == 1
    for value in (
        "data-atlas-v5-inert-form", 'data-preview-only="true"',
        'data-provider-state="disabled"', 'data-provider-configured="false"',
        'data-collects-data="false"', 'data-controls-read-only="true"',
        "readonly disabled", '<button type="submit" disabled>',
    ):
        assert value in new
    assert "<?php if ($active): ?>name=" in new
    assert "<?php if (!$active): ?>readonly disabled<?php endif; ?>" in new
    assert "<?php if (!$active): ?><p class=\"performanceLocalV5FormNotice" in new
    assert 'action="<?php echo esc_url($delivery[\'endpoint\']); ?>"' in new
    assert 'method="post"' in new
    assert "name=\"atlas_v5_token\"" not in new
    for key, purpose in (("name", "name"), ("phone", "tel"), ("postal-code", "postal-code"), ("email", "email")):
        assert f"'{key}' => '{purpose}'" in new


def test_runtime_checksum_binds_the_delivery_module_and_all_existing_runtime_files() -> None:
    source = RENDERER.read_text(encoding="utf-8")
    runtime = _function(source, "atlas_performance_local_v5_runtime_files")
    assert "ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_MODULE" in runtime
    for identity in (
        "ATLAS_PERFORMANCE_LOCAL_V5_PLUGIN_FILE",
        "ATLAS_PERFORMANCE_LOCAL_V5_TEMPLATE",
        "ATLAS_PERFORMANCE_LOCAL_V5_STYLESHEET",
        "ATLAS_PERFORMANCE_LOCAL_V5_SCRIPT",
    ):
        assert identity in runtime


def test_delivery_module_is_generic_and_contains_no_site_or_provider_identity() -> None:
    source = DELIVERY.read_text(encoding="utf-8").lower()
    for forbidden in (
        "flo-zone", "drywoodtenting.com", "gorilladesk", "atlasops360",
        "smtp", "oauth", "api_key", "private_key", "844", "page 41",
    ):
        assert forbidden not in source
    assert "wp_mail(" in source
    assert "register_rest_route(" in source
    assert "project-atlas/v4" in source


def test_form_client_is_contained_same_origin_and_nonpersistent() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "window.fetch(endpoint.href" in source
    assert 'endpoint.origin !== window.location.origin' in source
    assert 'typeof endpointValue !== "string" || endpointValue.trim() === ""' in source
    assert "response.ok && response.status === 200" in source
    assert "result.ok === true" in source
    assert 'keys !== "message,ok,state"' in source
    assert 'control.value === requestBody.fields[key]' in source
    assert 'credentials: "same-origin"' in source
    assert 'cache: "no-store"' in source
    assert 'redirect: "error"' in source
    assert "window.crypto.getRandomValues" in source
    for forbidden in (
        "localStorage", "sessionStorage", "indexedDB", "document.cookie",
        "sendBeacon", "WebSocket", "XMLHttpRequest", "console.", "http://", "https://",
    ):
        assert forbidden not in source


def test_css_changes_are_only_the_contained_0579_delivery_and_presentation_states() -> None:
    old = (SOURCE_0578 / "assets/performance-local-v5.css").read_text(encoding="utf-8")
    new = STYLESHEET.read_text(encoding="utf-8")
    delivery_addition = """.performanceLocalV5FormHoneypot {
  position: absolute !important;
  width: 1px !important;
  height: 1px !important;
  margin: -1px !important;
  padding: 0 !important;
  overflow: hidden !important;
  clip: rect(0 0 0 0) !important;
  clip-path: inset(50%) !important;
  border: 0 !important;
  white-space: nowrap !important;
}

.performanceLocalV5Form[data-atlas-v5-active-form] button:not(:disabled) {
  background: var(--plv5-forest);
  color: #fff;
  cursor: pointer;
}

.performanceLocalV5Form[data-atlas-v5-active-form] button:not(:disabled):hover {
  background: var(--plv5-forest-deep);
}

.performanceLocalV5Form[data-atlas-v5-active-form] button:focus-visible {
  outline: 3px solid var(--plv5-lime);
  outline-offset: 3px;
}

.performanceLocalV5Form[data-atlas-v5-active-form] [data-field-key][aria-invalid="true"] {
  border-color: #a23b2a;
  background: #fff8f6;
  box-shadow: 0 0 0 2px color-mix(in srgb, #a23b2a 22%, transparent);
  scroll-margin-top: 180px;
}

.performanceLocalV5Form[data-atlas-v5-active-form] .performanceLocalV5FieldError {
  color: #842c20;
  font-size: 0.78rem;
  font-weight: 800;
  line-height: 1.35;
}

"""
    presentation_marker = "/* WordPress-only City-Service form presentation hardening for 0.57.9. */"
    assert new.count(delivery_addition) == 1
    assert new.count(presentation_marker) == 1
    presentation_index = new.index(presentation_marker)
    presentation = new[presentation_index:]
    assert hashlib.sha256(presentation.encode("utf-8")).hexdigest() == (
        "bfdba3e757e63c791d5f182bcd9a6e0f931dbbd6f04246c280858a936d1f4207"
    )
    assert new[:presentation_index].replace(delivery_addition, "").rstrip("\n") == old.rstrip("\n")


def test_city_service_final_form_has_scoped_geometry_and_contrast_hardening() -> None:
    css = STYLESHEET.read_text(encoding="utf-8")
    scope = (
        "body.project-atlas-v5-template "
        ".projectAtlasV5Root.performanceLocalV5CityServicePreview "
        ".performanceLocalFinalCta"
    )

    assert f"""{scope} .performanceLocalV5Form {{
  display: grid;
  width: 100%;
  grid-template-columns: minmax(0, 1fr);
}}""" in css
    assert f"""{scope} .performanceLocalV5FormGrid {{
  width: 100%;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}}""" in css
    assert f"""@media (max-width: 900px) {{
  {scope} .performanceLocalV5FormGrid {{
    grid-template-columns: minmax(0, 1fr);
  }}""" in css
    assert f"""{scope} .performanceLocalV5Form :where(input:not([type="hidden"]), textarea) {{
  background: #f8faf8;
  color: #17231c;
  caret-color: #17231c;
  -webkit-text-fill-color: #17231c;
}}""" in css
    assert f"""{scope} .performanceLocalV5Form :where(input:not([type="hidden"]), textarea)::placeholder {{
  color: #59675f;
  opacity: 1;
}}""" in css
    assert all(value in css for value in (
        f"{scope} .performanceLocalV5Form input:-webkit-autofill",
        "box-shadow: 0 0 0 1000px #f8faf8 inset;",
        f"{scope} .performanceLocalV5Form[data-atlas-v5-active-form] > button[data-atlas-v5-form-submit]:not(:disabled)",
        "border: 2px solid var(--plv5-lime);",
        "color: var(--plv5-lime-foreground);",
        f"{scope} .performanceLocalV5Form[data-atlas-v5-active-form] .performanceLocalV5FieldError",
        "background: #fff0ee;",
        "color: #842c20;",
    ))


def test_back_to_top_avoids_forms_and_is_noninteractive_while_hidden() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    assert all(value in script for value in (
        'root.querySelectorAll("[data-atlas-v5-inert-form], [data-atlas-v5-active-form]")',
        "var backToTopIntersectsForm = function ()",
        "form.getBoundingClientRect()",
        "bounds.right >= collisionLeft",
        "bounds.bottom >= collisionTop",
        "var formCollision = backToTopIntersectsForm();",
        "setBackToTopHidden(belowThreshold || menuOpen || formFocused || formCollision || Boolean(footerReached));",
        'backToTop.setAttribute("aria-hidden", "true")',
        "document.activeElement === backToTop",
        "backToTop.blur()",
        'backToTop.removeAttribute("aria-hidden")',
    ))


def test_0579_builder_is_deterministic_portable_and_byte_exact(tmp_path: Path) -> None:
    builder = _load_builder()
    output = tmp_path / "project-atlas-metadata-bridge-0.57.9.zip"
    builder.OUTPUT = output
    first = builder.build()
    first_hash = _sha256(first)
    second = builder.build()
    assert first == second == output
    assert _sha256(second) == first_hash
    expected = {
        f"project-atlas-metadata-bridge/{path.relative_to(SOURCE).as_posix()}": path.read_bytes()
        for path in SOURCE.rglob("*")
        if path.is_file()
    }
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        actual = {name: archive.read(name) for name in names if not name.endswith("/")}
        timestamps = {archive.getinfo(name).date_time for name in names}
        modes = {archive.getinfo(name).external_attr >> 16 for name in names}
    assert actual == expected
    assert len(names) == len(set(names))
    assert timestamps == {(2026, 8, 25, 0, 0, 0)}
    assert modes == {0o100644}
    assert all("\\" not in name for name in names)
    assert all(not name.startswith(("/", "\\")) for name in names)
    assert all(".." not in PurePosixPath(name).parts for name in names)


def test_readme_keeps_local_renderer_and_production_activation_blocked() -> None:
    readme = README.read_text(encoding="utf-8")
    assert "append-only rehearsal successor to 0.57.8" in readme
    assert "does not seed or enable delivery" in readme
    assert "local-rehearsal-only" in readme
    assert "does not authorize installation on production" in readme
    assert "publication" in readme and "deployment" in readme


def test_public_contact_and_private_delivery_roles_remain_separate() -> None:
    public_contact = "public-contact@atlas-v5-site.localhost"
    private_recipient = "private-inbox@atlas-v5-mail.localhost"
    private_from = "no-reply@atlas-v5-site.localhost"
    assert len({public_contact, private_recipient, private_from}) == 3

    renderer = RENDERER.read_text(encoding="utf-8")
    delivery = DELIVERY.read_text(encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8")
    render_context = _function(delivery, "atlas_performance_local_v5_form_delivery_render_context")

    assert "$value['contact_email'] === null" in renderer
    assert "$website['contact_email'] !== null" in renderer
    assert "$footer['contact_email'] !== null" in renderer
    assert all(key not in renderer + script + render_context for key in ("recipient_email", "from_email"))
    assert all(value not in renderer + delivery + script for value in (public_contact, private_recipient, private_from))
    assert "atlas_performance_local_v5_form_delivery_expected_origin()" in delivery
    assert "$website_origin[1]" in delivery


def test_validation_and_mail_failure_have_distinct_accessible_client_states() -> None:
    delivery = DELIVERY.read_text(encoding="utf-8")
    renderer = RENDERER.read_text(encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8")
    submit = _function(delivery, "atlas_performance_local_v5_form_delivery_submit")

    assert "Please check the highlighted fields and try again." in delivery
    assert "ATLAS_PERFORMANCE_LOCAL_V5_FORM_VALIDATION_MESSAGE" in submit
    assert "'mail_failure'" in submit and "$config['failure_message']" in submit
    assert all(value in renderer for value in (
        "data-validation-rule", "data-validation-minimum-length",
        "data-validation-maximum-length", "data-atlas-v5-field-error",
    ))
    assert 'setAttribute("aria-invalid", "true")' in script
    assert 'removeAttribute("aria-invalid")' in script
    assert 'result.state === "validation_error" ? markValidationErrors() : null' in script
    assert "return firstInvalid;" in script
    assert "focusFirstInvalid(firstInvalid);" in script
    assert "window.requestAnimationFrame(applyFocus);" in script
    assert 'control.scrollIntoView({ behavior: "auto", block: "center", inline: "nearest" });' in script
