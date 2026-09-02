from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SYNC_SCRIPT = ROOT / "wordpress/sync_performance_local_v5_css_05712.py"
SOURCE = ROOT / "wordpress/project-atlas-metadata-bridge-0.57.12"
STYLESHEET = SOURCE / "assets/performance-local-v5.css"
PREDECESSOR = (
    ROOT
    / "wordpress/project-atlas-metadata-bridge-0.57.11/assets/performance-local-v5.css"
)
README = SOURCE / "README.md"


def _load_sync():
    spec = importlib.util.spec_from_file_location("atlas_v5_css_05712_sync", SYNC_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_05712_css_is_exactly_the_sealed_predecessor_plus_declared_patch() -> None:
    sync = _load_sync()
    predecessor = PREDECESSOR.read_text(encoding="utf-8")
    successor = STYLESHEET.read_text(encoding="utf-8")
    assert successor == sync.build_css()

    restored = successor
    inserted = sync.ADMIN_TOOLBAR_BLOCK_05712 + "\n\n"
    assert restored.count(inserted) == 1
    restored = restored.replace(inserted, "", 1)
    for old, new, _label in reversed(sync.PATCHES):
        assert restored.count(new) == 1
        restored = restored.replace(new, old, 1)
    assert restored.count(sync.HEADER_05712) == 1
    restored = restored.replace(sync.HEADER_05712, sync.HEADER_05711, 1)
    assert restored == predecessor


def test_05712_sync_fails_closed_on_predecessor_or_authoritative_source_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sync = _load_sync()
    predecessor = tmp_path / "predecessor.css"
    predecessor.write_bytes(PREDECESSOR.read_bytes() + b"\n")
    monkeypatch.setattr(sync, "PREDECESSOR_PATH", predecessor)
    with pytest.raises(sync.CssSynchronizationError, match="0.57.11 stylesheet"):
        sync.build_css()

    monkeypatch.setattr(sync, "PREDECESSOR_PATH", PREDECESSOR)
    authoritative = tmp_path / "styles.css"
    authoritative.write_bytes(sync.AUTHORITATIVE_SOURCE_PATH.read_bytes() + b"\n")
    monkeypatch.setattr(sync, "AUTHORITATIVE_SOURCE_PATH", authoritative)
    with pytest.raises(sync.CssSynchronizationError, match="authoritative frontend"):
        sync.build_css()


def test_05712_top_stack_and_admin_toolbar_geometry_are_exact() -> None:
    sync = _load_sync()
    css = STYLESHEET.read_text(encoding="utf-8")
    authoritative = sync.AUTHORITATIVE_SOURCE_PATH.read_text(encoding="utf-8")

    for _old, successor, _label in sync.PATCHES:
        assert css.count(successor) == 1
        assert authoritative.count(successor) == 1
    assert css.count(sync.ADMIN_TOOLBAR_BLOCK_05712) == 1
    assert authoritative.count(sync.ADMIN_TOOLBAR_BLOCK_05712) == 1

    assert "--plv5-viewport-top-offset: 0px;" in sync.CITY_ROOT_05712
    assert "padding-block-start: var(--plv5-city-stack-height);" in sync.CITY_ROOT_05712
    assert "position: fixed;" in sync.TOP_STACK_05712
    assert "top: var(--plv5-viewport-top-offset);" in sync.TOP_STACK_05712
    assert "right: 0;" in sync.TOP_STACK_05712
    assert "left: 0;" in sync.TOP_STACK_05712

    toolbar = sync.ADMIN_TOOLBAR_BLOCK_05712
    desktop = "--plv5-viewport-top-offset: 32px;"
    tablet = "@media screen and (max-width: 782px)"
    mobile = "@media screen and (max-width: 600px)"
    assert toolbar.count(desktop) == 1
    assert toolbar.count("--plv5-viewport-top-offset: 46px;") == 1
    assert toolbar.count("--plv5-viewport-top-offset: 0px;") == 1
    assert toolbar.count("padding-block-start: 0;") == 1
    assert toolbar.count("position: sticky;") == 1
    assert toolbar.index(desktop) < toolbar.index(tablet) < toolbar.index(mobile)


def test_05712_focus_disabled_action_and_bottom_stack_contracts_are_preserved() -> None:
    sync = _load_sync()
    css = STYLESHEET.read_text(encoding="utf-8")
    assert "top: calc(var(--plv5-viewport-top-offset) + 8px);" in css
    assert "top: calc(var(--plv5-viewport-top-offset) + 12px);" in css
    assert (
        "top: calc(var(--plv5-viewport-top-offset) + var(--plv5-city-stack-height));"
        in css
    )
    assert sync.CITY_SCROLL_MARGIN_05712 in css
    assert sync.CONDITIONAL_SCROLL_MARGIN_05712 in css
    assert sync.CONDITIONAL_FOCUS_HEADER_05712 in css
    assert "--plv5-city-action-height: 0px;" in css
    assert """.performanceLocalV5CityServicePreview .performanceLocalStickyActions {
  display: none !important;
}""" in css


def test_05712_preserves_honeypot_and_wordpress_only_form_hardening_bytes() -> None:
    predecessor = PREDECESSOR.read_text(encoding="utf-8")
    successor = STYLESHEET.read_text(encoding="utf-8")
    for exact_fragment in (
        ".performanceLocalV5FormHoneypot {",
        "/* WordPress-only V5 integration corrections. */",
        "/* WordPress-only City-Service form presentation hardening for 0.57.9. */",
        ".performanceLocalV5Form[data-atlas-v5-active-form] button:not(:disabled)",
        "input:-webkit-autofill:focus",
        "> button[data-atlas-v5-form-submit]:disabled",
        "[data-field-key][aria-invalid=\"true\"]",
    ):
        assert successor.count(exact_fragment) == predecessor.count(exact_fragment) > 0


def test_05712_readme_records_only_the_narrow_sticky_geometry_successor() -> None:
    readme = README.read_text(encoding="utf-8")
    for expected in (
        "Metadata Bridge 0.57.12",
        "narrow successor to 0.57.11",
        "current authoritative `frontend/src/styles.css`",
        "32-pixel offset",
        "46-pixel offset",
        "600 pixels and below",
        "returns to sticky positioning",
        "does not authorize production installation",
    ):
        assert expected in readme
