from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE_05710 = ROOT / "wordpress/project-atlas-metadata-bridge-0.57.10"
SOURCE = ROOT / "wordpress/project-atlas-metadata-bridge-0.57.11"
RENDERER_05710 = SOURCE_05710 / "includes/performance-local-v5-renderer.php"
RENDERER = SOURCE / "includes/performance-local-v5-renderer.php"


def _function(source: str, name: str) -> str:
    match = re.search(
        rf"function {re.escape(name)}\([^)]*\)(?:\s*:\s*[^{{]+)?\s*{{",
        source,
    )
    assert match, name
    depth = 1
    index = match.end()
    while depth and index < len(source):
        depth += (source[index] == "{") - (source[index] == "}")
        index += 1
    assert depth == 0, name
    return source[match.start():index]


def _asset_pattern() -> re.Pattern[str]:
    body = _function(
        RENDERER.read_text(encoding="utf-8"),
        "atlas_performance_local_v5_asset_path",
    )
    match = re.search(r"preg_match\(\s*'(?P<pattern>#[^']+#i)'", body, re.S)
    assert match
    php_pattern = match.group("pattern")
    assert php_pattern.startswith("#") and php_pattern.endswith("#i")
    return re.compile(php_pattern[1:-2], re.I)


def _accepted_like_exact_php_contract(value: str) -> bool:
    if (
        not value
        or value != value.strip()
        or len(value.encode("utf-8")) > 512
        or re.search(r"[\x00-\x1f\x7f<>]", value)
        or "\\" in value
        or "%" in value
        or not value.startswith("/")
        or value.startswith("//")
        or "?" in value
        or "#" in value
        or re.fullmatch(r"/[A-Za-z0-9._~/-]*", value) is None
        or any(segment in {".", ".."} for segment in value.split("/"))
    ):
        return False
    return _asset_pattern().fullmatch(value) is not None


def test_05711_preserves_internal_href_gate_and_changes_only_asset_path_function() -> None:
    old = RENDERER_05710.read_text(encoding="utf-8")
    new = RENDERER.read_text(encoding="utf-8")
    assert _function(new, "atlas_performance_local_v5_internal_href") == _function(
        old,
        "atlas_performance_local_v5_internal_href",
    )
    old_asset = _function(old, "atlas_performance_local_v5_asset_path")
    new_asset = _function(new, "atlas_performance_local_v5_asset_path")
    assert old_asset != new_asset
    assert old.replace(old_asset, new_asset, 1) == new
    assert "/wp-content/uploads/" in new_asset
    assert "atlas-v5/" in new_asset
    assert "[1-9][0-9]{3}" in new_asset
    assert "(?:0[1-9]|1[0-2])" in new_asset


def test_05711_accepts_exact_legacy_and_core_wordpress_original_paths() -> None:
    accepted = (
        "/wp-content/uploads/atlas-v5/flo-zone-page41-hero.webp",
        "/wp-content/uploads/atlas-v5/nested/flo-zone.header-logo.V1.PNG",
        "/wp-content/uploads/2026/01/flo-zone-page41-hero.webp",
        "/wp-content/uploads/2026/08/flo-zone-page41-process-planning.webp",
        "/wp-content/uploads/9999/12/flo-zone.footer_logo-v1.PNG",
    )
    assert all(_accepted_like_exact_php_contract(path) for path in accepted)


def test_05711_rejects_unsafe_or_out_of_contract_upload_paths() -> None:
    rejected = (
        "https://www.staging3.drywoodtenting.com/wp-content/uploads/2026/08/file.webp",
        "//www.staging3.drywoodtenting.com/wp-content/uploads/2026/08/file.webp",
        "/wp-content/uploads/file.webp",
        "/wp-content/uploads/arbitrary/file.webp",
        "/wp-content/uploads/0000/08/file.webp",
        "/wp-content/uploads/026/08/file.webp",
        "/wp-content/uploads/2026/00/file.webp",
        "/wp-content/uploads/2026/13/file.webp",
        "/wp-content/uploads/2026/8/file.webp",
        "/wp-content/uploads/2026/08/nested/file.webp",
        "/wp-content/uploads/2026/08/-file.webp",
        "/wp-content/uploads/2026/08/.hidden.webp",
        "/wp-content/uploads/2026/08/file name.webp",
        "/wp-content/uploads/2026/08/file.gif",
        "/wp-content/uploads/2026/08/file.webp?size=full",
        "/wp-content/uploads/2026/08/file.webp#asset",
        "/wp-content/uploads/2026/08/file%2ewebp",
        "/wp-content/uploads/2026/08/../file.webp",
        "/wp-content/uploads/2026\\08\\file.webp",
        "/wp-content/uploads/2026//08/file.webp",
        "/wp-content/uploads/2026/08/file.webp\n",
    )
    assert all(not _accepted_like_exact_php_contract(path) for path in rejected)


def test_05711_readme_records_the_narrow_upload_path_boundary() -> None:
    readme = (SOURCE / "README.md").read_text(encoding="utf-8")
    for expected in (
        "Metadata Bridge 0.57.11",
        "narrow successor to 0.57.10",
        "/wp-content/uploads/atlas-v5/",
        "/wp-content/uploads/YYYY/MM/filename.ext",
        "Arbitrary uploads subdirectories",
        "query strings",
        "fragments",
        "external URLs",
        "does not authorize production installation",
    ):
        assert expected in readme
