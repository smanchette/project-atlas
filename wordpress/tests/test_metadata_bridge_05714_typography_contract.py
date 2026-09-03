from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
SYNC_SCRIPT = ROOT / "wordpress/sync_performance_local_v5_css_05714.py"
HISTORICAL_SYNC_SCRIPT = ROOT / "wordpress/sync_performance_local_v5_css_05713.py"
SOURCE = ROOT / "wordpress/project-atlas-metadata-bridge-0.57.14"
STYLESHEET = SOURCE / "assets/performance-local-v5.css"
PREDECESSOR = (
    ROOT
    / "wordpress/project-atlas-metadata-bridge-0.57.13/assets/performance-local-v5.css"
)
FRONTEND = ROOT / "frontend/src/styles.css"
BROWSER_HELPER = ROOT / "wordpress/tests/performance-local-v5-typography-regression.js"
STICKY_HELPER = ROOT / "wordpress/tests/performance-local-v5-sticky-scroll-regression.js"
README = SOURCE / "README.md"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_sync():
    return _load(SYNC_SCRIPT, "atlas_v5_css_05714_sync")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_05714_css_is_exactly_the_sealed_05713_phone_weight_patch() -> None:
    sync = _load_sync()
    predecessor = PREDECESSOR.read_text(encoding="utf-8")
    successor = STYLESHEET.read_text(encoding="utf-8")
    assert successor == sync.build_css()
    assert _sha256(PREDECESSOR) == sync.PREDECESSOR_SHA256
    assert _sha256(FRONTEND) == sync.AUTHORITATIVE_SOURCE_SHA256
    assert successor.count(sync.TYPOGRAPHY_BLOCK_05714) == 1
    assert FRONTEND.read_text(encoding="utf-8").count(sync.TYPOGRAPHY_BLOCK_05714) == 1

    restored = successor.replace(
        sync.TYPOGRAPHY_BLOCK_05714,
        sync.TYPOGRAPHY_BLOCK_05713,
        1,
    ).replace(sync.HEADER_05714, sync.HEADER_05713, 1)
    assert restored == predecessor


def test_05714_phone_weight_override_is_exact_scoped_and_geometry_neutral() -> None:
    sync = _load_sync()
    old_lines = sync.TYPOGRAPHY_BLOCK_05713.splitlines()
    new_lines = sync.TYPOGRAPHY_BLOCK_05714.splitlines()
    assert new_lines == old_lines[:1] + [
        ".performanceLocalV5StickyPhoneBar strong,"
    ] + old_lines[1:]
    assert sync.TYPOGRAPHY_BLOCK_05714.count(
        ".performanceLocalV5StickyPhoneBar strong,"
    ) == 1
    for declaration in (
        "font-family: var(--atlas-font-body, system-ui, sans-serif);",
        "font-style: normal;",
        "font-synthesis: none;",
        "font-weight: 700;",
        "text-shadow: none;",
        "-webkit-text-stroke: 0;",
        "filter: none;",
        "opacity: 1;",
    ):
        assert declaration in sync.TYPOGRAPHY_BLOCK_05714
    for forbidden in (
        "font-smoothing", "@font-face", "url(", "font-size:", "line-height:",
        "letter-spacing:", "transform:", "position:", "padding:", "margin:",
        "color:", "background:",
    ):
        assert forbidden not in sync.TYPOGRAPHY_BLOCK_05714
    assert "\nstrong," not in sync.TYPOGRAPHY_BLOCK_05714
    assert "\nstrong {" not in sync.TYPOGRAPHY_BLOCK_05714


def test_05714_historical_sync_is_fail_closed_after_authoritative_advance() -> None:
    historical = _load(HISTORICAL_SYNC_SCRIPT, "atlas_v5_css_05713_historical_sync")
    assert historical.AUTHORITATIVE_SOURCE_SHA256 == (
        "4bcbeada3e61553c97d7d2ca71ef518291971a5ef3288c895122fb325a266c20"
    )
    with pytest.raises(historical.CssSynchronizationError, match="authoritative frontend"):
        historical.build_css()


def test_05714_sync_fails_closed_on_predecessor_or_authoritative_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sync = _load_sync()
    predecessor = tmp_path / "predecessor.css"
    predecessor.write_bytes(PREDECESSOR.read_bytes() + b"\n")
    monkeypatch.setattr(sync, "PREDECESSOR_PATH", predecessor)
    with pytest.raises(sync.CssSynchronizationError, match="0.57.13 stylesheet"):
        sync.build_css()

    monkeypatch.setattr(sync, "PREDECESSOR_PATH", PREDECESSOR)
    authoritative = tmp_path / "styles.css"
    authoritative.write_bytes(FRONTEND.read_bytes() + b"\n")
    monkeypatch.setattr(sync, "AUTHORITATIVE_SOURCE_PATH", authoritative)
    with pytest.raises(sync.CssSynchronizationError, match="authoritative frontend"):
        sync.build_css()


def test_05714_browser_helpers_bind_nested_weight_and_sticky_contracts() -> None:
    typography = BROWSER_HELPER.read_text(encoding="utf-8")
    for expected in (
        '"0.57.13"',
        '"0.57.14"',
        "sticky_phone_number",
        "baseline_05713.phone_parent_700_nested_900",
        "successor_05714.phone_parent_nested_match",
        "font_synthesis",
        "no_horizontal_overflow",
        "hero_typography_preserved",
        "hero_cta_preserved",
        "body_typography_preserved",
    ):
        assert expected in typography
    sticky = STICKY_HELPER.read_text(encoding="utf-8")
    assert '"0.57.14"' in sticky
    assert "0.57.11 through 0.57.14" in sticky
    for helper in (typography, sticky):
        assert "fetch(" not in helper
        assert "XMLHttpRequest" not in helper
        assert "WebSocket" not in helper

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable; JavaScript syntax is verified by the focused shell matrix.")
    for helper_path in (BROWSER_HELPER, STICKY_HELPER):
        result = subprocess.run(
            [node, "--check", str(helper_path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr


def test_05714_readme_records_only_the_nested_phone_weight_successor() -> None:
    readme = README.read_text(encoding="utf-8")
    for expected in (
        "Metadata Bridge 0.57.14",
        "narrow successor to 0.57.13",
        "browser-default `bolder` emphasis",
        "weight 900 while its row resolved to weight 700",
        "font synthesis",
        "does not globally redefine `strong`",
        "no external font request",
        "does not authorize production installation",
    ):
        assert expected in readme
