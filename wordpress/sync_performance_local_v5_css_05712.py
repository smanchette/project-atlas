"""Build the 0.57.12 stylesheet as a sealed 0.57.11 sticky-geometry patch."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
AUTHORITATIVE_SOURCE_PATH = REPOSITORY_ROOT / "frontend" / "src" / "styles.css"
AUTHORITATIVE_SOURCE_SHA256 = (
    "e8dc265dc5ee5ce22cd99f7d3ee4366c2985ad1e6314de06f6b28cb6a69b7742"
)
PREDECESSOR_PATH = (
    REPOSITORY_ROOT
    / "wordpress"
    / "project-atlas-metadata-bridge-0.57.11"
    / "assets"
    / "performance-local-v5.css"
)
PREDECESSOR_SHA256 = (
    "3a227011edb8dcd56e6a30ba701dddc488c7bb1b3c5556530c49cb4b39a4445e"
)
OUTPUT_PATH = (
    REPOSITORY_ROOT
    / "wordpress"
    / "project-atlas-metadata-bridge-0.57.12"
    / "assets"
    / "performance-local-v5.css"
)


class CssSynchronizationError(RuntimeError):
    """Raised when either sealed input no longer matches the narrow patch contract."""


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _replace_exact_once(
    stylesheet: str,
    predecessor: str,
    successor: str,
    authoritative_source: str,
    *,
    label: str,
) -> str:
    if stylesheet.count(predecessor) != 1:
        raise CssSynchronizationError(
            f"Expected exactly one predecessor CSS block for {label}"
        )
    if authoritative_source.count(successor) != 1:
        raise CssSynchronizationError(
            f"Authoritative frontend source does not contain exactly one {label} block"
        )
    return stylesheet.replace(predecessor, successor, 1)


CITY_ROOT_05711 = """.performanceLocalV5CityServicePreview {
  --plv5-city-phone-height: 44px;
  --plv5-city-action-height: 52px;
  --plv5-city-safe-top: env(safe-area-inset-top, 0px);
  --plv5-city-stack-height: calc(
    var(--plv5-city-phone-height) +
    var(--plv5-city-action-height) +
    var(--plv5-city-safe-top)
  );
  min-width: 0;
  background: var(--atlas-color-background, #fff);
  font-family: var(--atlas-font-body, Inter, ui-sans-serif, system-ui, sans-serif);
  scroll-padding-block-start: var(--plv5-city-stack-height);
}"""
CITY_ROOT_05712 = """.performanceLocalV5CityServicePreview {
  --plv5-city-phone-height: 44px;
  --plv5-city-action-height: 52px;
  --plv5-city-safe-top: env(safe-area-inset-top, 0px);
  --plv5-viewport-top-offset: 0px;
  --plv5-city-stack-height: calc(
    var(--plv5-city-phone-height) +
    var(--plv5-city-action-height) +
    var(--plv5-city-safe-top)
  );
  min-width: 0;
  padding-block-start: var(--plv5-city-stack-height);
  background: var(--atlas-color-background, #fff);
  font-family: var(--atlas-font-body, Inter, ui-sans-serif, system-ui, sans-serif);
  scroll-padding-block-start: var(--plv5-city-stack-height);
}"""

TOP_STACK_05711 = """.performanceLocalV5TopConversionStack {
  position: sticky;
  z-index: 130;
  top: 0;
  display: grid;
  width: 100%;
  height: var(--plv5-city-stack-height);"""
TOP_STACK_05712 = """.performanceLocalV5TopConversionStack {
  position: fixed;
  z-index: 130;
  top: var(--plv5-viewport-top-offset);
  right: 0;
  left: 0;
  display: grid;
  width: 100%;
  height: var(--plv5-city-stack-height);"""

CITY_SKIP_LINK_05711 = """.performanceLocalV5CityServicePreview .performanceLocalSkipLink {
  z-index: 180;
}"""
CITY_SKIP_LINK_05712 = """.performanceLocalV5CityServicePreview .performanceLocalSkipLink {
  z-index: 180;
  top: calc(var(--plv5-viewport-top-offset) + 8px);
}"""

CITY_SCROLL_MARGIN_05711 = """.performanceLocalV5CityServicePreview #main-content,
.performanceLocalV5CityServicePreview .performanceLocalEstimateForm,
.performanceLocalV5CityServicePreview .performanceLocalEstimateForm :where(input, textarea, button) {
  scroll-margin-block-start: calc(var(--plv5-city-stack-height) + 16px);
}"""
CITY_SCROLL_MARGIN_05712 = """.performanceLocalV5CityServicePreview #main-content,
.performanceLocalV5CityServicePreview .performanceLocalEstimateForm,
.performanceLocalV5CityServicePreview .performanceLocalEstimateForm :where(input, textarea, button) {
  scroll-margin-block-start: calc(
    var(--plv5-viewport-top-offset) +
    var(--plv5-city-stack-height) +
    16px
  );
}"""

CONDITIONAL_ROOT_05711 = """.performanceLocalV5ConditionalPage {
  --plv5-city-phone-height: 44px;
  --plv5-city-action-height: 52px;
  --plv5-city-safe-top: env(safe-area-inset-top, 0px);
  --plv5-city-stack-height: calc(
    var(--plv5-city-phone-height) +
    var(--plv5-city-action-height) +
    var(--plv5-city-safe-top)
  );
  min-width: 0;
  background: var(--plv5-cream);
  scroll-padding-block-start: calc(var(--plv5-city-stack-height) + 94px);
}"""
CONDITIONAL_ROOT_05712 = """.performanceLocalV5ConditionalPage {
  --plv5-city-phone-height: 44px;
  --plv5-city-action-height: 52px;
  --plv5-city-safe-top: env(safe-area-inset-top, 0px);
  --plv5-viewport-top-offset: 0px;
  --plv5-city-stack-height: calc(
    var(--plv5-city-phone-height) +
    var(--plv5-city-action-height) +
    var(--plv5-city-safe-top)
  );
  min-width: 0;
  padding-block-start: var(--plv5-city-stack-height);
  background: var(--plv5-cream);
  scroll-padding-block-start: calc(var(--plv5-city-stack-height) + 94px);
}"""

CONDITIONAL_SKIP_LINK_05711 = """.performanceLocalV5ConditionalPage .performanceLocalV5SkipLink {
  z-index: 180;
}"""
CONDITIONAL_SKIP_LINK_05712 = """.performanceLocalV5ConditionalPage .performanceLocalV5SkipLink {
  z-index: 180;
  top: calc(var(--plv5-viewport-top-offset) + 12px);
}"""

CONDITIONAL_HEADER_05711 = """.performanceLocalV5ConditionalPage .performanceLocalV5Header {
  z-index: 120;
  top: var(--plv5-city-stack-height);
}"""
CONDITIONAL_HEADER_05712 = """.performanceLocalV5ConditionalPage .performanceLocalV5Header {
  z-index: 120;
  top: calc(var(--plv5-viewport-top-offset) + var(--plv5-city-stack-height));
}"""

CONDITIONAL_FOCUS_HEADER_05711 = """.performanceLocalV5ConditionalPage[data-v5-menu-open="true"] .performanceLocalV5Header,
.performanceLocalV5ConditionalPage[data-v5-form-focus-risk="true"] .performanceLocalV5Header {
  top: 0;
}"""
CONDITIONAL_FOCUS_HEADER_05712 = """.performanceLocalV5ConditionalPage[data-v5-menu-open="true"] .performanceLocalV5Header,
.performanceLocalV5ConditionalPage[data-v5-form-focus-risk="true"] .performanceLocalV5Header {
  top: var(--plv5-viewport-top-offset);
}"""

CONDITIONAL_SCROLL_MARGIN_05711 = """.performanceLocalV5ConditionalPage #performance-local-v5-conditional-main,
.performanceLocalV5ConditionalPage .performanceLocalV5Form,
.performanceLocalV5ConditionalPage .performanceLocalV5Form :where(input, textarea, button) {
  scroll-margin-block-start: calc(var(--plv5-city-stack-height) + 94px);
}"""
CONDITIONAL_SCROLL_MARGIN_05712 = """.performanceLocalV5ConditionalPage #performance-local-v5-conditional-main,
.performanceLocalV5ConditionalPage .performanceLocalV5Form,
.performanceLocalV5ConditionalPage .performanceLocalV5Form :where(input, textarea, button) {
  scroll-margin-block-start: calc(
    var(--plv5-viewport-top-offset) +
    var(--plv5-city-stack-height) +
    94px
  );
}"""

ADMIN_TOOLBAR_BLOCK_05712 = """body.admin-bar .performanceLocalV5CityServicePreview,
body.admin-bar .performanceLocalV5ConditionalPage {
  --plv5-viewport-top-offset: 32px;
}

@media screen and (max-width: 782px) {
  body.admin-bar .performanceLocalV5CityServicePreview,
  body.admin-bar .performanceLocalV5ConditionalPage {
    --plv5-viewport-top-offset: 46px;
  }
}

@media screen and (max-width: 600px) {
  body.admin-bar .performanceLocalV5CityServicePreview,
  body.admin-bar .performanceLocalV5ConditionalPage {
    --plv5-viewport-top-offset: 0px;
    padding-block-start: 0;
  }

  body.admin-bar .performanceLocalV5CityServicePreview .performanceLocalV5TopConversionStack,
  body.admin-bar .performanceLocalV5ConditionalPage .performanceLocalV5TopConversionStack {
    position: sticky;
  }
}"""

HEADER_05711 = "* wordpress/sync_performance_local_v5_css_0578.py."
HEADER_05712 = "* wordpress/sync_performance_local_v5_css_05712.py."
ADMIN_INSERTION_ANCHOR = """.performanceLocalV5ConditionalMain {
  min-width: 0;
  padding-block: clamp(64px, 8vw, 112px);
}"""


PATCHES = (
    (CITY_ROOT_05711, CITY_ROOT_05712, "city-service stack reservation"),
    (TOP_STACK_05711, TOP_STACK_05712, "fixed top conversion stack"),
    (CITY_SKIP_LINK_05711, CITY_SKIP_LINK_05712, "city-service skip-link offset"),
    (CITY_SCROLL_MARGIN_05711, CITY_SCROLL_MARGIN_05712, "city-service focus offset"),
    (CONDITIONAL_ROOT_05711, CONDITIONAL_ROOT_05712, "conditional-page stack reservation"),
    (
        CONDITIONAL_SKIP_LINK_05711,
        CONDITIONAL_SKIP_LINK_05712,
        "conditional-page skip-link offset",
    ),
    (CONDITIONAL_HEADER_05711, CONDITIONAL_HEADER_05712, "conditional-page header offset"),
    (
        CONDITIONAL_FOCUS_HEADER_05711,
        CONDITIONAL_FOCUS_HEADER_05712,
        "conditional-page focus-safe header offset",
    ),
    (
        CONDITIONAL_SCROLL_MARGIN_05711,
        CONDITIONAL_SCROLL_MARGIN_05712,
        "conditional-page focus offset",
    ),
)


def build_css() -> str:
    predecessor_bytes = PREDECESSOR_PATH.read_bytes()
    if _sha256(predecessor_bytes) != PREDECESSOR_SHA256:
        raise CssSynchronizationError("The immutable 0.57.11 stylesheet differs")
    authoritative_bytes = AUTHORITATIVE_SOURCE_PATH.read_bytes()
    if _sha256(authoritative_bytes) != AUTHORITATIVE_SOURCE_SHA256:
        raise CssSynchronizationError("The authoritative frontend stylesheet differs")

    predecessor = predecessor_bytes.decode("utf-8")
    authoritative = authoritative_bytes.decode("utf-8")
    if predecessor.count(HEADER_05711) != 1:
        raise CssSynchronizationError("The predecessor generator identity differs")
    stylesheet = predecessor.replace(HEADER_05711, HEADER_05712, 1)

    for old, new, label in PATCHES:
        stylesheet = _replace_exact_once(
            stylesheet,
            old,
            new,
            authoritative,
            label=label,
        )

    if authoritative.count(ADMIN_TOOLBAR_BLOCK_05712) != 1:
        raise CssSynchronizationError(
            "Authoritative frontend source lacks the exact admin-toolbar offset block"
        )
    if ADMIN_TOOLBAR_BLOCK_05712 in predecessor:
        raise CssSynchronizationError("The predecessor unexpectedly contains the new toolbar block")
    if stylesheet.count(ADMIN_INSERTION_ANCHOR) != 1:
        raise CssSynchronizationError("The toolbar insertion anchor is not unique")
    stylesheet = stylesheet.replace(
        ADMIN_INSERTION_ANCHOR,
        ADMIN_TOOLBAR_BLOCK_05712 + "\n\n" + ADMIN_INSERTION_ANCHOR,
        1,
    )
    return stylesheet


def synchronize(*, check: bool = False) -> bool:
    expected = build_css().encode("utf-8")
    if check:
        return OUTPUT_PATH.is_file() and OUTPUT_PATH.read_bytes() == expected
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_bytes(expected)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the 0.57.12 stylesheet against both sealed inputs",
    )
    arguments = parser.parse_args(argv)
    if not synchronize(check=arguments.check):
        print(
            f"stale generated asset: {OUTPUT_PATH.relative_to(REPOSITORY_ROOT)}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
