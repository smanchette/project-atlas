"""Build the 0.57.14 stylesheet as a sealed 0.57.13 phone-weight patch."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
AUTHORITATIVE_SOURCE_PATH = REPOSITORY_ROOT / "frontend" / "src" / "styles.css"
AUTHORITATIVE_SOURCE_SHA256 = (
    "11348084010b7a8bfcf50196b81e9538006028ab19ff01e666e1543b4181f5d6"
)
PREDECESSOR_PATH = (
    REPOSITORY_ROOT
    / "wordpress"
    / "project-atlas-metadata-bridge-0.57.13"
    / "assets"
    / "performance-local-v5.css"
)
PREDECESSOR_SHA256 = (
    "b4158eb11a2d53b8c06c1bfcec8ccda4ce8329e65514b8c3a0aa9f58ad30f82f"
)
OUTPUT_PATH = (
    REPOSITORY_ROOT
    / "wordpress"
    / "project-atlas-metadata-bridge-0.57.14"
    / "assets"
    / "performance-local-v5.css"
)


class CssSynchronizationError(RuntimeError):
    """Raised when either sealed input no longer matches the narrow patch contract."""


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


HEADER_05713 = "* wordpress/sync_performance_local_v5_css_05713.py."
HEADER_05714 = "* wordpress/sync_performance_local_v5_css_05714.py."

TYPOGRAPHY_BLOCK_05713 = """.performanceLocalV5StickyPhoneBar a,
.performanceLocalV5StickyActionBanner a,
.performanceLocalV5CityServicePreview .performanceLocalDesktopNavigation :where(a, span, button),
.performanceLocalV5CityServicePreview .performanceLocalDrawerList :where(a, span, button) {
  font-family: var(--atlas-font-body, system-ui, sans-serif);
  font-style: normal;
  font-synthesis: none;
  font-weight: 700;
  text-shadow: none;
  -webkit-text-stroke: 0;
  filter: none;
  opacity: 1;
}"""

TYPOGRAPHY_BLOCK_05714 = """.performanceLocalV5StickyPhoneBar a,
.performanceLocalV5StickyPhoneBar strong,
.performanceLocalV5StickyActionBanner a,
.performanceLocalV5CityServicePreview .performanceLocalDesktopNavigation :where(a, span, button),
.performanceLocalV5CityServicePreview .performanceLocalDrawerList :where(a, span, button) {
  font-family: var(--atlas-font-body, system-ui, sans-serif);
  font-style: normal;
  font-synthesis: none;
  font-weight: 700;
  text-shadow: none;
  -webkit-text-stroke: 0;
  filter: none;
  opacity: 1;
}"""


def build_css() -> str:
    predecessor_bytes = PREDECESSOR_PATH.read_bytes()
    if _sha256(predecessor_bytes) != PREDECESSOR_SHA256:
        raise CssSynchronizationError("The immutable 0.57.13 stylesheet differs")
    authoritative_bytes = AUTHORITATIVE_SOURCE_PATH.read_bytes()
    if _sha256(authoritative_bytes) != AUTHORITATIVE_SOURCE_SHA256:
        raise CssSynchronizationError("The authoritative frontend stylesheet differs")

    predecessor = predecessor_bytes.decode("utf-8")
    authoritative = authoritative_bytes.decode("utf-8")
    if predecessor.count(HEADER_05713) != 1 or HEADER_05714 in predecessor:
        raise CssSynchronizationError("The predecessor generator identity differs")
    if predecessor.count(TYPOGRAPHY_BLOCK_05713) != 1:
        raise CssSynchronizationError("The predecessor typography block differs")
    if TYPOGRAPHY_BLOCK_05714 in predecessor:
        raise CssSynchronizationError("The predecessor already contains the correction")
    if authoritative.count(TYPOGRAPHY_BLOCK_05714) != 1:
        raise CssSynchronizationError(
            "The authoritative source lacks the exact phone-weight correction"
        )
    if TYPOGRAPHY_BLOCK_05713 in authoritative:
        raise CssSynchronizationError(
            "The authoritative source still contains the predecessor typography block"
        )

    stylesheet = predecessor.replace(HEADER_05713, HEADER_05714, 1)
    stylesheet = stylesheet.replace(
        TYPOGRAPHY_BLOCK_05713,
        TYPOGRAPHY_BLOCK_05714,
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
        help="verify the 0.57.14 stylesheet against both sealed inputs",
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
