import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { transform } from "esbuild";

const sourceUrl = new URL("../src/components/performanceLocalInteractions.ts", import.meta.url);
const source = await readFile(sourceUrl, "utf8");
const compiled = await transform(source, {
  format: "esm",
  loader: "ts",
  target: "es2020",
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled.code).toString("base64")}`;
const { resolvePerformanceLocalStickyVisibility } = await import(moduleUrl);

const afterHero = Object.freeze({
  actionsAvailable: true,
  formFocusRisk: false,
  heroConversionVisible: false,
  mobileMenuOpen: false,
  mobileViewport: true,
});

test("shows the sticky actions only on mobile after the hero actions leave", () => {
  assert.deepEqual(resolvePerformanceLocalStickyVisibility(afterHero), {
    visible: true,
    reason: "shown_after_hero",
  });
});

test("fails closed when no safe actions are available", () => {
  assert.deepEqual(
    resolvePerformanceLocalStickyVisibility({ ...afterHero, actionsAvailable: false }),
    { visible: false, reason: "hidden_no_actions" },
  );
});

test("does not create sticky actions outside the mobile breakpoint", () => {
  assert.deepEqual(
    resolvePerformanceLocalStickyVisibility({ ...afterHero, mobileViewport: false }),
    { visible: false, reason: "hidden_non_mobile" },
  );
});

test("suppresses the sticky layer while the mobile menu is open", () => {
  assert.deepEqual(
    resolvePerformanceLocalStickyVisibility({ ...afterHero, mobileMenuOpen: true }),
    { visible: false, reason: "hidden_menu_open" },
  );
});

test("suppresses the sticky layer while form focus creates keyboard risk", () => {
  assert.deepEqual(
    resolvePerformanceLocalStickyVisibility({ ...afterHero, formFocusRisk: true }),
    { visible: false, reason: "hidden_form_focus" },
  );
});

test("suppresses the sticky layer while hero actions remain meaningfully visible", () => {
  assert.deepEqual(
    resolvePerformanceLocalStickyVisibility({ ...afterHero, heroConversionVisible: true }),
    { visible: false, reason: "hidden_hero_actions_visible" },
  );
});

test("applies safety precedence before intersection state", () => {
  assert.deepEqual(
    resolvePerformanceLocalStickyVisibility({
      ...afterHero,
      actionsAvailable: false,
      formFocusRisk: true,
      heroConversionVisible: true,
      mobileMenuOpen: true,
      mobileViewport: false,
    }),
    { visible: false, reason: "hidden_no_actions" },
  );
});
