"""Deterministically build the public Performance Local V5 WordPress stylesheet.

The React Theme Lab stylesheet is the governed presentation source, but it also
contains review, diagnostic, and demo-only rules.  This synchronizer extracts
only the shared logo rules and the public Performance Local rule namespaces
needed by the 0.57.8 WordPress bridge.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from pathlib import Path
import sys
import textwrap


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = REPOSITORY_ROOT / "frontend" / "src" / "styles.css"
OUTPUT_PATH = (
    REPOSITORY_ROOT
    / "wordpress"
    / "project-atlas-metadata-bridge-0.57.8"
    / "assets"
    / "performance-local-v5.css"
)

V5_MARKER = (
    "/* Performance Local V5: additive source-only layout and local review namespace. */"
)
BASE_SELECTORS = (
    ".previewBrandMark",
    ".previewBrandLogo",
    ".previewFooterLogo",
)

# These namespaces and state hooks exist only for Theme Lab, operator review,
# diagnostics, failure inspection, or synthetic demo material.  Public trust
# output deliberately uses ``performanceLocalV5ReviewTrust*`` and therefore is
# excluded by exact demo/operator prefixes rather than by the word "Review".
FORBIDDEN_SELECTOR_FRAGMENTS = (
    ".themeLab",
    ".performanceLocalDiagnostics",
    ".performanceLocalFormReadiness",
    ".performanceLocalDelivery",
    ".performanceLocalV5ReviewHeader",
    ".performanceLocalV5ReviewControls",
    ".performanceLocalV5ReviewState",
    ".performanceLocalV5Diagnostic",
    ".performanceLocalV5Manifest",
    ".performanceLocalV5SourceBlocker",
    ".performanceLocalV5Unavailable",
    ".performanceLocalV5Demo",
    ".performanceLocalV5ReviewTrustBadgeDemo",
    ".performanceLocalV5ReviewTrustDemoStructure",
    ".performanceLocalV5MapFrameDemo",
    "[data-v5-demo",
    "[data-v5-review",
    "[data-v5-diagnostic",
)

GENERATED_HEADER = """/*
 * Generated from frontend/src/styles.css by
 * wordpress/sync_performance_local_v5_css_0578.py.
 * Do not edit this asset directly.
 */

body.project-atlas-v5-template {
  min-width: 0;
  margin: 0;
  padding: 0;
  overflow-x: clip;
}

body.project-atlas-v5-template .projectAtlasV5Root {
  min-width: 0;
}

body.project-atlas-v5-template .projectAtlasV5Root,
body.project-atlas-v5-template .projectAtlasV5Root *,
body.project-atlas-v5-template .projectAtlasV5Root *::before,
body.project-atlas-v5-template .projectAtlasV5Root *::after {
  box-sizing: border-box;
}

body.project-atlas-v5-template .projectAtlasV5Root [hidden] {
  display: none !important;
}
"""

WORDPRESS_V5_OVERRIDES = """/* WordPress-only V5 integration corrections. */
body.project-atlas-v5-template .projectAtlasV5Root a.performanceLocalV5Brand,
body.project-atlas-v5-template .projectAtlasV5Root a.performanceLocalV5Brand:hover,
body.project-atlas-v5-template .projectAtlasV5Root a.performanceLocalV5Brand:visited {
  text-decoration: none;
}

body.project-atlas-v5-template .projectAtlasV5Root a.performanceLocalV5Brand:focus-visible {
  text-decoration: none;
  outline: 3px solid var(--atlas-color-focus, var(--plv5-lime));
  outline-offset: 3px;
}

body.project-atlas-v5-template .projectAtlasV5Root .performanceLocalV5EstimatePage .performanceLocalV5Form {
  display: grid;
  width: 100%;
  grid-template-columns: minmax(0, 1fr);
}

body.project-atlas-v5-template .projectAtlasV5Root .performanceLocalV5EstimatePage .performanceLocalV5Form > .performanceLocalV5FormNotice,
body.project-atlas-v5-template .projectAtlasV5Root .performanceLocalV5EstimatePage .performanceLocalV5Form > .performanceLocalV5FormGrid,
body.project-atlas-v5-template .projectAtlasV5Root .performanceLocalV5EstimatePage .performanceLocalV5Form > button {
  grid-column: 1 / -1;
}

body.project-atlas-v5-template .projectAtlasV5Root .performanceLocalV5EstimatePage .performanceLocalV5FormGrid {
  width: 100%;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

body.project-atlas-v5-template .projectAtlasV5Root .performanceLocalV5EstimatePage .performanceLocalV5FormFieldFull {
  grid-column: 1 / -1;
}

@media (max-width: 900px) {
  body.project-atlas-v5-template .projectAtlasV5Root .performanceLocalV5EstimatePage .performanceLocalV5FormGrid {
    grid-template-columns: minmax(0, 1fr);
  }

  body.project-atlas-v5-template .projectAtlasV5Root .performanceLocalV5EstimatePage .performanceLocalV5FormFieldFull {
    grid-column: 1;
  }
}
"""


class CssExtractionError(RuntimeError):
    """Raised when the governed source no longer matches the extraction contract."""


def _matching_brace(css: str, opening_brace: int) -> int:
    depth = 0
    quote: str | None = None
    escaped = False
    index = opening_brace

    while index < len(css):
        character = css[index]
        following = css[index + 1] if index + 1 < len(css) else ""

        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            index += 1
            continue

        if character in {'"', "'"}:
            quote = character
            index += 1
            continue

        if character == "/" and following == "*":
            comment_end = css.find("*/", index + 2)
            if comment_end < 0:
                raise CssExtractionError("Unterminated CSS comment")
            index = comment_end + 2
            continue

        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return index
            if depth < 0:
                break
        index += 1

    raise CssExtractionError("Unbalanced CSS rule")


def _prelude_delimiter(css: str, start: int) -> tuple[int, str]:
    quote: str | None = None
    escaped = False
    parentheses = 0
    brackets = 0
    index = start

    while index < len(css):
        character = css[index]
        following = css[index + 1] if index + 1 < len(css) else ""

        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            index += 1
            continue

        if character in {'"', "'"}:
            quote = character
        elif character == "/" and following == "*":
            comment_end = css.find("*/", index + 2)
            if comment_end < 0:
                raise CssExtractionError("Unterminated CSS comment")
            index = comment_end + 2
            continue
        elif character == "(":
            parentheses += 1
        elif character == ")":
            parentheses -= 1
        elif character == "[":
            brackets += 1
        elif character == "]":
            brackets -= 1
        elif parentheses == 0 and brackets == 0 and character in "{;":
            return index, character
        index += 1

    raise CssExtractionError("CSS prelude has no rule delimiter")


def _rule_blocks(css: str) -> Iterator[tuple[str, str]]:
    index = 0
    while index < len(css):
        while index < len(css):
            if css[index].isspace():
                index += 1
                continue
            if css.startswith("/*", index):
                comment_end = css.find("*/", index + 2)
                if comment_end < 0:
                    raise CssExtractionError("Unterminated CSS comment")
                index = comment_end + 2
                continue
            break

        if index >= len(css):
            return

        delimiter_index, delimiter = _prelude_delimiter(css, index)
        if delimiter == ";":
            index = delimiter_index + 1
            continue

        prelude = css[index:delimiter_index].strip()
        closing_brace = _matching_brace(css, delimiter_index)
        yield prelude, css[delimiter_index + 1 : closing_brace]
        index = closing_brace + 1


def _split_selector_list(selector_list: str) -> list[str]:
    selectors: list[str] = []
    start = 0
    quote: str | None = None
    escaped = False
    parentheses = 0
    brackets = 0

    for index, character in enumerate(selector_list):
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue

        if character in {'"', "'"}:
            quote = character
        elif character == "(":
            parentheses += 1
        elif character == ")":
            parentheses -= 1
        elif character == "[":
            brackets += 1
        elif character == "]":
            brackets -= 1
        elif character == "," and parentheses == 0 and brackets == 0:
            selectors.append(selector_list[start:index].strip())
            start = index + 1

    selectors.append(selector_list[start:].strip())
    return [selector for selector in selectors if selector]


def _indent(content: str) -> str:
    return textwrap.indent(content, "  ")


def _render_declaration_rule(selectors: list[str], body: str) -> str:
    declarations = textwrap.dedent(body.strip("\r\n")).rstrip()
    if not declarations:
        raise CssExtractionError(f"Empty CSS rule for {selectors[0]}")
    selector_text = ",\n".join(selectors)
    return f"{selector_text} {{\n{_indent(declarations)}\n}}"


def _selector_is_public(selector: str) -> bool:
    return ".performanceLocal" in selector and not any(
        fragment in selector for fragment in FORBIDDEN_SELECTOR_FRAGMENTS
    )


def _render_public_rule_list(css: str) -> str:
    rendered: list[str] = []
    for prelude, body in _rule_blocks(css):
        if prelude.startswith("@media "):
            public_children = _render_public_rule_list(body)
            if public_children:
                rendered.append(f"{prelude} {{\n{_indent(public_children)}\n}}")
            continue

        if prelude.startswith("@"):
            raise CssExtractionError(f"Unsupported block at-rule in public source: {prelude}")

        public_selectors = [
            selector
            for selector in _split_selector_list(prelude)
            if _selector_is_public(selector)
        ]
        if public_selectors:
            rendered.append(_render_declaration_rule(public_selectors, body))

    return "\n\n".join(rendered)


def _extract_exact_rule(source: str, selector: str) -> str:
    matches = [
        _render_declaration_rule([prelude], body)
        for prelude, body in _rule_blocks(source)
        if prelude == selector
    ]
    if len(matches) != 1:
        raise CssExtractionError(
            f"Expected exactly one top-level {selector} rule; found {len(matches)}"
        )
    return matches[0]


def _line_start(source: str, selector: str, *, after: int = 0) -> int:
    token = f"\n{selector} {{"
    location = source.find(token, after)
    if location < 0:
        raise CssExtractionError(f"Missing governed source boundary: {selector}")
    return location + 1


def build_css(source: str) -> str:
    """Return the exact generated public asset for ``source``."""

    if source.count(V5_MARKER) != 1:
        raise CssExtractionError("Expected exactly one Performance Local V5 marker")

    marker_index = source.index(V5_MARKER)
    legacy_start = _line_start(source, ".performanceLocalSite")
    v5_start = _line_start(source, ".performanceLocalV5Site", after=marker_index)
    if not legacy_start < marker_index < v5_start:
        raise CssExtractionError("Performance Local stylesheet boundaries are out of order")

    base_rules = [_extract_exact_rule(source, selector) for selector in BASE_SELECTORS]
    legacy_rules = _render_public_rule_list(source[legacy_start:marker_index])
    v5_rules = _render_public_rule_list(source[v5_start:])
    if not legacy_rules or not v5_rules:
        raise CssExtractionError("A required public stylesheet range produced no rules")

    generated = (
        GENERATED_HEADER.rstrip()
        + "\n\n"
        + "\n\n".join(base_rules)
        + "\n\n"
        + legacy_rules
        + "\n\n"
        + v5_rules
        + "\n\n"
        + WORDPRESS_V5_OVERRIDES.rstrip()
        + "\n"
    )

    required_fragments = (
        ".previewBrandMark {",
        ".previewBrandLogo {",
        ".previewFooterLogo {",
        ".performanceLocalSite {",
        ".performanceLocalEstimateForm {",
        ".performanceLocalV5Site {",
        ".performanceLocalV5ReviewTrustGrid {",
        ".performanceLocalV5LocationMap {",
    )
    missing = [fragment for fragment in required_fragments if fragment not in generated]
    if missing:
        raise CssExtractionError(f"Required public rules were not extracted: {missing}")

    leaked = [
        fragment for fragment in FORBIDDEN_SELECTOR_FRAGMENTS if fragment in generated
    ]
    if leaked:
        raise CssExtractionError(f"Non-public selectors leaked into generated CSS: {leaked}")

    return generated


def synchronize(*, check: bool = False) -> bool:
    expected = build_css(SOURCE_PATH.read_text(encoding="utf-8"))
    if check:
        actual = OUTPUT_PATH.read_bytes() if OUTPUT_PATH.exists() else None
        return actual == expected.encode("utf-8")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(expected, encoding="utf-8", newline="\n")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify that the generated asset exactly matches the governed source",
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
