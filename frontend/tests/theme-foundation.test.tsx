import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import {
  designTokenCssVariables,
  themePresentation,
  themeValidationError,
} from "../src/components/themeAdapter";
import { compositionValidationError } from "../src/pages/GeneratedPagePreview";
import { canSelectTheme, parseDesignTokens } from "../src/pages/ThemesPage";
import type { PageComposition } from "../src/types";
import { fallbackTheme, selectedTheme, themeTokens } from "./theme-fixtures";

function composition(
  resolvedTheme = selectedTheme(),
  overrides: Partial<PageComposition> = {},
): PageComposition {
  return {
    id: 1,
    website_id: 31,
    site_plan_id: 41,
    planned_page_id: 51,
    generated_page_id: 61,
    composition_version: 2,
    generated_components: [],
    operator_decisions: [],
    effective_components: [],
    source_snapshot: { theme: resolvedTheme.source_identity },
    source_hash: "c".repeat(64),
    resolved_theme: resolvedTheme,
    status: "current",
    validation_errors: [],
    generated_at: "2026-08-04T20:00:00Z",
    ...overrides,
  };
}

test("an approved available Website Theme is the authoritative presentation source", () => {
  const resolved = selectedTheme();
  assert.equal(themeValidationError(resolved, 31), null);
  const presentation = themePresentation(resolved, 31, 1280);
  assert.equal(presentation.attributes["data-atlas-theme-mode"], "selected");
  assert.equal(presentation.attributes["data-atlas-theme-key"], "governed-theme");
  assert.equal(presentation.attributes["data-atlas-theme-version"], "2");
  assert.equal(presentation.style["--atlas-color-primary"], "#1F2937");
  assert.equal(presentation.style["--atlas-button-background"], "#1F2937");
  assert.equal(presentation.style["--atlas-nav-min-target"], "44px");
  assert.equal(presentation.style["--atlas-cta-min-target"], "44px");
  assert.equal(presentation.style["--atlas-motion-normal"], "200ms");
  assert.equal(compositionValidationError(composition(resolved)), null);
});

test("the explicit neutral fallback is safe only when no governed selection exists", () => {
  const fallback = fallbackTheme();
  assert.equal(themeValidationError(fallback, 31), null);
  assert.equal(
    themePresentation(fallback, 31, 1280).attributes["data-atlas-theme-mode"],
    "neutral_fallback",
  );
  assert.match(
    themeValidationError(
      { ...fallback, selection: selectedTheme().selection },
      31,
    ) ?? "",
    /fallback identity is ambiguous/,
  );
});

test("cross-Website, unapproved, retired, stale, and mismatched identities fail closed", () => {
  const selected = selectedTheme();
  assert.match(themeValidationError(selected, 99) ?? "", /Website ownership boundary/);
  assert.match(
    themeValidationError(
      { ...selected, theme: { ...selected.theme!, approval_status: "pending_review" } },
      31,
    ) ?? "",
    /not an active approved Website-owned version/,
  );
  assert.match(
    themeValidationError(
      { ...selected, theme: { ...selected.theme!, lifecycle_status: "retired" } },
      31,
    ) ?? "",
    /not an active approved Website-owned version/,
  );
  assert.match(
    themeValidationError(
      {
        ...selected,
        source_identity: { ...selected.source_identity, theme_version: 999 },
      },
      31,
    ) ?? "",
    /does not match the governed selection/,
  );
  assert.match(
    compositionValidationError(composition(selected, { status: "stale" })) ?? "",
    /composition is not current/,
  );
});

test("unsafe token values cannot silently enter CSS custom properties", () => {
  const unsafe = structuredClone(themeTokens);
  unsafe.shadows.high = "0 0 1px #000; background: red";
  assert.throws(() => designTokenCssVariables(unsafe), /shadows.high is unsafe/);
  const unsafeFont = structuredClone(themeTokens);
  unsafeFont.typography.heading_family = "system-ui; color: red";
  assert.throws(
    () => designTokenCssVariables(unsafeFont),
    /typography.heading_family is unsafe/,
  );
});

test("accessibility metadata cannot masquerade for failing effective tokens", () => {
  const selected = selectedTheme();
  selected.effective_tokens.colors.accent = "#F2B84B";
  selected.effective_tokens.colors.accent_foreground = "#FFFFFF";
  assert.match(
    themeValidationError(selected, 31) ?? "",
    /accessibility evidence conflicts with its effective tokens/,
  );

  const mismatchedEvidence = selectedTheme();
  mismatchedEvidence.accessibility.ratios.body_text_on_background = 1;
  assert.match(
    themeValidationError(mismatchedEvidence, 31) ?? "",
    /accessibility evidence does not match.*body_text_on_background/,
  );
});

test("approved non-default breakpoints and layout decisions change adapter output", () => {
  const selected = selectedTheme();
  const custom = structuredClone(selected.effective_tokens);
  custom.responsive = {
    mobile_max: 899,
    tablet_min: 900,
    tablet_max: 1199,
    desktop_min: 1200,
  };
  custom.layout = {
    max_content_columns: 2,
    content_alignment: "center",
    mobile_stack: false,
    gutter: "xl",
    overflow_behavior: "scroll_explicit",
  };
  selected.effective_tokens = custom;
  selected.theme!.design_tokens = structuredClone(custom);

  const mobile = themePresentation(selected, 31, 850);
  const tablet = themePresentation(selected, 31, 1000);
  const desktop = themePresentation(selected, 31, 1400);
  assert.equal(mobile.attributes["data-atlas-theme-viewport"], "mobile");
  assert.equal(tablet.attributes["data-atlas-theme-viewport"], "tablet");
  assert.equal(desktop.attributes["data-atlas-theme-viewport"], "desktop");
  assert.equal(mobile.attributes["data-atlas-content-alignment"], "center");
  assert.equal(mobile.attributes["data-atlas-mobile-stack"], "false");
  assert.equal(mobile.attributes["data-atlas-overflow-behavior"], "scroll_explicit");
  assert.equal(mobile.style["--atlas-layout-max-columns"], 2);
  assert.equal(mobile.style["--atlas-layout-gutter"], "2rem");
});

test("Theme selection UI uses the backend lifecycle contract", () => {
  const theme = selectedTheme().theme!;
  assert.equal(canSelectTheme(theme, false), true);
  assert.equal(canSelectTheme(theme, true), false);
  assert.equal(canSelectTheme({ ...theme, lifecycle_status: "retired" }, false), false);
  assert.equal(canSelectTheme({ ...theme, approval_status: "pending_review" }, false), false);
});

test("Theme creation accepts one JSON object and leaves typed validation to the server", () => {
  assert.deepEqual(parseDesignTokens(JSON.stringify(themeTokens)), themeTokens);
  assert.throws(() => parseDesignTokens("[]"), /one JSON object/);
  assert.throws(() => parseDesignTokens("not-json"), /valid JSON/);
});

test("one adapter feeds the existing semantic renderer and CSS consumes its variables", () => {
  const previewSource = readFileSync(
    resolve(process.cwd(), "src/pages/GeneratedPagePreview.tsx"),
    "utf8",
  );
  const adapterSource = readFileSync(
    resolve(process.cwd(), "src/components/themeAdapter.ts"),
    "utf8",
  );
  const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");
  assert.match(previewSource, /const presentation = themePresentation\(/);
  assert.match(previewSource, /components\.filter\(\(item\) => item\.region === "main"\)\.map\(renderComponent\)/);
  assert.doesNotMatch(adapterSource, /page_type|city_service|service_county|switch\s*\(/);
  for (const variable of [
    "--atlas-color-background",
    "--atlas-font-heading",
    "--atlas-section-space-desktop",
    "--atlas-button-background",
    "--atlas-card-background",
    "--atlas-nav-background",
    "--atlas-cta-background",
    "--atlas-motion-fast",
  ]) {
    assert.match(css, new RegExp(`var\\(${variable.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`));
  }
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css, /overflow-x:\s*clip/);
  assert.match(previewSource, /const viewportWidth = useViewportWidth\(\)/);
  assert.match(previewSource, /window\.addEventListener\("resize", update\)/);
  assert.match(css, /data-atlas-theme-viewport="mobile"/);
  assert.match(css, /data-atlas-theme-viewport="tablet"/);
  assert.match(css, /data-atlas-content-alignment="center"/);
  assert.match(css, /data-atlas-mobile-stack="true"/);
  assert.match(css, /data-atlas-overflow-behavior="scroll_explicit"/);
  assert.match(
    css,
    /\.previewBandMuted\s*\{[^}]*background:\s*var\(--atlas-color-surface[^}]*color:\s*var\(--atlas-color-text/s,
  );
  assert.match(
    css,
    /\.previewProfessionalBand\s*\{[^}]*background:\s*var\(--atlas-color-accent[^}]*color:\s*var\(--atlas-color-accent-foreground/s,
  );
  assert.match(
    css,
    /\.previewHero\s*\{[^}]*color:\s*var\(--atlas-color-primary-foreground[^}]*background:\s*var\(--atlas-color-primary/s,
  );
});

test("Theme management remains Website-scoped and contains no Flo-Zone presentation values", () => {
  const source = readFileSync(resolve(process.cwd(), "src/pages/ThemesPage.tsx"), "utf8");
  assert.match(source, /\/api\/websites\/\$\{selectedWebsiteId\}\/context/);
  assert.match(source, /\/api\/websites\/\$\{selectedWebsiteId\}\/themes/);
  assert.match(source, /\/api\/websites\/\$\{selectedWebsiteId\}\/theme-selection/);
  assert.match(source, /Theme results crossed the authoritative Website Context boundary/);
  assert.doesNotMatch(source, /Flo-Zone|drywoodtenting|#185B45|#F2B84B/);
});
