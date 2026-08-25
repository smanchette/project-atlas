from __future__ import annotations

import importlib.util
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SYNC_PATH = REPOSITORY_ROOT / "wordpress" / "sync_performance_local_v5_css_0578.py"
SOURCE_PATH = REPOSITORY_ROOT / "frontend" / "src" / "styles.css"
ASSET_PATH = (
    REPOSITORY_ROOT
    / "wordpress"
    / "project-atlas-metadata-bridge-0.57.8"
    / "assets"
    / "performance-local-v5.css"
)


def _load_synchronizer():
    specification = importlib.util.spec_from_file_location(
        "sync_performance_local_v5_css_0578", SYNC_PATH
    )
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_wordpress_v5_css_asset_is_exact_public_source_extraction() -> None:
    synchronizer = _load_synchronizer()
    source = SOURCE_PATH.read_text(encoding="utf-8")
    expected = synchronizer.build_css(source)
    asset_bytes = ASSET_PATH.read_bytes()
    asset = asset_bytes.decode("utf-8")

    assert asset_bytes == expected.encode("utf-8")
    assert synchronizer.synchronize(check=True)

    for required in (
        "body.project-atlas-v5-template",
        "body.project-atlas-v5-template .projectAtlasV5Root",
        "body.project-atlas-v5-template .projectAtlasV5Root *::after",
        "box-sizing: border-box",
        "body.project-atlas-v5-template .projectAtlasV5Root [hidden]",
        "display: none !important",
        ".previewBrandMark {",
        ".previewBrandLogo {",
        ".previewFooterLogo {",
        ".performanceLocalSite {",
        ".performanceLocalEstimateForm {",
        ".performanceLocalV5Site {",
        ".performanceLocalV5ReviewTrustGrid {",
        ".performanceLocalV5LocationMap {",
    ):
        assert required in asset

    for forbidden in synchronizer.FORBIDDEN_SELECTOR_FRAGMENTS:
        assert forbidden not in asset

    assert """body.project-atlas-v5-template .projectAtlasV5Root a.performanceLocalV5Brand,
body.project-atlas-v5-template .projectAtlasV5Root a.performanceLocalV5Brand:hover,
body.project-atlas-v5-template .projectAtlasV5Root a.performanceLocalV5Brand:visited {
  text-decoration: none;
}""" in asset
    assert """body.project-atlas-v5-template .projectAtlasV5Root a.performanceLocalV5Brand:focus-visible {
  text-decoration: none;
  outline: 3px solid var(--atlas-color-focus, var(--plv5-lime));
  outline-offset: 3px;
}""" in asset
    assert """body.project-atlas-v5-template .projectAtlasV5Root .performanceLocalV5EstimatePage .performanceLocalV5Form {
  display: grid;
  width: 100%;
  grid-template-columns: minmax(0, 1fr);
}""" in asset
    assert """body.project-atlas-v5-template .projectAtlasV5Root .performanceLocalV5EstimatePage .performanceLocalV5Form > .performanceLocalV5FormNotice,
body.project-atlas-v5-template .projectAtlasV5Root .performanceLocalV5EstimatePage .performanceLocalV5Form > .performanceLocalV5FormGrid,
body.project-atlas-v5-template .projectAtlasV5Root .performanceLocalV5EstimatePage .performanceLocalV5Form > button {
  grid-column: 1 / -1;
}""" in asset
    assert """body.project-atlas-v5-template .projectAtlasV5Root .performanceLocalV5EstimatePage .performanceLocalV5FormGrid {
  width: 100%;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}""" in asset
    assert """body.project-atlas-v5-template .projectAtlasV5Root .performanceLocalV5EstimatePage .performanceLocalV5FormFieldFull {
  grid-column: 1 / -1;
}""" in asset
    assert """@media (max-width: 900px) {
  body.project-atlas-v5-template .projectAtlasV5Root .performanceLocalV5EstimatePage .performanceLocalV5FormGrid {
    grid-template-columns: minmax(0, 1fr);
  }

  body.project-atlas-v5-template .projectAtlasV5Root .performanceLocalV5EstimatePage .performanceLocalV5FormFieldFull {
    grid-column: 1;
  }
}""" in asset

    assert "Performance Local V5: additive source-only layout and local review namespace" not in asset
    assert "frontend/src/styles.css" in asset
