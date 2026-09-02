from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
SYNC_SCRIPT = ROOT / "wordpress/sync_performance_local_v5_css_05713.py"
SOURCE = ROOT / "wordpress/project-atlas-metadata-bridge-0.57.13"
STYLESHEET = SOURCE / "assets/performance-local-v5.css"
PREDECESSOR = (
    ROOT
    / "wordpress/project-atlas-metadata-bridge-0.57.12/assets/performance-local-v5.css"
)
FRONTEND = ROOT / "frontend/src/styles.css"
BROWSER_HELPER = ROOT / "wordpress/tests/performance-local-v5-typography-regression.js"
README = SOURCE / "README.md"


def _load_sync():
    spec = importlib.util.spec_from_file_location("atlas_v5_css_05713_sync", SYNC_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_05713_css_is_exactly_the_sealed_05712_typography_patch() -> None:
    sync = _load_sync()
    predecessor = PREDECESSOR.read_text(encoding="utf-8")
    successor = STYLESHEET.read_text(encoding="utf-8")
    assert successor == sync.build_css()
    assert _sha256(PREDECESSOR) == sync.PREDECESSOR_SHA256
    assert _sha256(FRONTEND) == sync.AUTHORITATIVE_SOURCE_SHA256
    assert successor.count(sync.TYPOGRAPHY_BLOCK_05713) == 1
    assert FRONTEND.read_text(encoding="utf-8").count(sync.TYPOGRAPHY_BLOCK_05713) == 1

    restored = successor.replace(
        "\n\n" + sync.TYPOGRAPHY_BLOCK_05713,
        "",
        1,
    ).replace(sync.HEADER_05713, sync.HEADER_05712, 1)
    assert restored == predecessor


def test_05713_interface_typography_is_real_weight_local_and_geometry_neutral() -> None:
    sync = _load_sync()
    block = sync.TYPOGRAPHY_BLOCK_05713
    for selector in (
        ".performanceLocalV5StickyPhoneBar a",
        ".performanceLocalV5StickyActionBanner a",
        ".performanceLocalDesktopNavigation :where(a, span, button)",
        ".performanceLocalDrawerList :where(a, span, button)",
    ):
        assert selector in block
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
        assert declaration in block
    for forbidden in (
        "font-smoothing",
        "@font-face",
        "url(",
        "font-size:",
        "line-height:",
        "letter-spacing:",
        "transform:",
        "position:",
        "padding:",
        "margin:",
    ):
        assert forbidden not in block


def test_05713_browser_helper_binds_before_after_and_preservation_contracts() -> None:
    helper = BROWSER_HELPER.read_text(encoding="utf-8")
    for expected in (
        "project-atlas-performance-local-v5-typography-regression@1",
        '"0.57.12"',
        '"0.57.13"',
        "system-ui platform-local face",
        "font_synthesis",
        "no_horizontal_overflow",
        "hero_typography_preserved",
        "hero_cta_preserved",
        "body_typography_preserved",
    ):
        assert expected in helper
    assert "fetch(" not in helper
    assert "XMLHttpRequest" not in helper
    assert "WebSocket" not in helper

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable; JavaScript syntax is verified by the focused shell matrix.")
    result = subprocess.run(
        [node, "--check", str(BROWSER_HELPER)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_05713_readme_records_only_the_interface_typography_successor() -> None:
    readme = README.read_text(encoding="utf-8")
    for expected in (
        "Metadata Bridge 0.57.13",
        "narrow successor to 0.57.12",
        "supported weight 700",
        "disabled font synthesis",
        "no-shadow",
        "no-stroke",
        "no external font request",
        "does not authorize production installation",
    ):
        assert expected in readme
