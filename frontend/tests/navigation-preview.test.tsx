import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";

import {
  buildNavigationTree,
  localPreviewDestination,
  renderComponent,
} from "../src/pages/GeneratedPagePreview";
import { navigationSuggestionDefaults } from "../src/pages/SitePlansPage";
import type { PageComponentInstance } from "../src/types";

function item(
  navigationItemId: number,
  targetPlannedPageId: number,
  position: number,
  label: string,
  parentNavigationItemId: number | null = null,
  targetGeneratedPageId: number | null = targetPlannedPageId + 100,
) {
  return {
    navigation_item_id: navigationItemId,
    target_planned_page_id: targetPlannedPageId,
    target_generated_page_id: targetGeneratedPageId,
    parent_navigation_item_id: parentNavigationItemId,
    position,
    status: "active",
    label,
    slug: label.toLowerCase().replace(/\s+/g, "-"),
  };
}

function component(
  componentKey: "primary_navigation" | "related_page_links",
  resolvedData: Record<string, unknown>,
): PageComponentInstance {
  return {
    instance_key: componentKey,
    component_key: componentKey,
    contract_version: 1,
    region: componentKey === "primary_navigation" ? "header" : "main",
    position: 0,
    variant: "default",
    input_bindings: {},
    resolved_data: resolvedData,
  };
}

test("navigation hierarchy is deterministic regardless of source row order", () => {
  const result = buildNavigationTree([
    item(4, 14, 1, "Seminole County", 2),
    item(2, 12, 1, "Service Areas"),
    item(1, 11, 0, "Home"),
    item(3, 13, 0, "Orange County", 2),
  ]);
  assert.equal(result.error, null);
  assert.deepEqual(result.nodes.map((node) => node.navigationItemId), [1, 2]);
  assert.deepEqual(result.nodes[1].children.map((node) => node.navigationItemId), [3, 4]);
});

test("bad parents, cycles, duplicate targets, labels, and sibling positions fail closed", () => {
  assert.match(
    buildNavigationTree([item(1, 11, 0, "Home"), item(1, 12, 1, "Contact")]).error ?? "",
    /duplicate navigation item identity/,
  );
  assert.match(buildNavigationTree([item(1, 11, 0, "Home", 99)]).error ?? "", /missing parent/);
  assert.match(
    buildNavigationTree([item(1, 11, 0, "One", 2), item(2, 12, 1, "Two", 1)]).error ?? "",
    /cycle/,
  );
  assert.match(
    buildNavigationTree([item(1, 11, 0, "Home"), item(2, 11, 1, "Home Again")]).error ?? "",
    /duplicate navigation target/,
  );
  assert.match(
    buildNavigationTree([item(1, 11, 0, "Contact"), item(2, 12, 1, " contact ")]).error ?? "",
    /duplicate sibling label/,
  );
  assert.match(
    buildNavigationTree([item(1, 11, 0, "Home"), item(2, 12, 0, "Contact")]).error ?? "",
    /ordering conflict/,
  );
});

test("disabled navigation decisions are absent from the rendered tree", () => {
  const disabled = { ...item(2, 12, 1, "Disabled"), status: "disabled" };
  const result = buildNavigationTree([item(1, 11, 0, "Home"), disabled]);
  assert.equal(result.error, null);
  assert.deepEqual(result.nodes.map((node) => node.label), ["Home"]);
});

test("preview routing requires a real Generated Page identity", () => {
  assert.equal(localPreviewDestination(73), "/generated-pages/73/preview");
  for (const value of [null, undefined, 0, -1, 1.5, "73"]) {
    assert.equal(localPreviewDestination(value), null);
  }
});

test("navigation renders accessible nested local preview links and retains canonical slugs", () => {
  const markup = renderToStaticMarkup(
    <MemoryRouter>
      {renderComponent(component("primary_navigation", {
        label: "Primary navigation",
        items: [
          item(1, 11, 0, "Service", null, 73),
          item(2, 12, 0, "Orange County", 1, 74),
          item(3, 13, 1, "Contact", null, null),
        ],
      }))}
    </MemoryRouter>,
  );
  assert.match(markup, /<nav[^>]+aria-label="Primary navigation"/);
  assert.match(markup, /class="semanticNavigationChildren"/);
  assert.match(markup, /href="\/generated-pages\/73\/preview"/);
  assert.match(markup, /data-canonical-slug="service"/);
  assert.match(markup, /aria-disabled="true"/);
  assert.match(markup, /Contact <small>\(local preview unavailable\)<\/small>/);
  assert.doesNotMatch(markup, /href="\/service\/"/);
});

test("related destinations use local previews and expose unavailable targets explicitly", () => {
  const markup = renderToStaticMarkup(
    <MemoryRouter>
      {renderComponent(component("related_page_links", {
        links: [
          { label: "About", slug: "about", purpose: "Build trust", target_generated_page_id: 70 },
          { label: "Future", slug: "future", purpose: "Deferred", target_generated_page_id: null },
        ],
      }))}
    </MemoryRouter>,
  );
  assert.match(markup, /href="\/generated-pages\/70\/preview"/);
  assert.match(markup, /data-canonical-slug="about"/);
  assert.match(markup, /Future <small>\(local preview unavailable\)<\/small>/);
});

test("operator UI records provenance without converting Atlas suggestions into decisions", () => {
  const source = readFileSync(resolve(process.cwd(), "src/pages/SitePlansPage.tsx"), "utf8");
  assert.match(source, /Atlas suggestion source \(optional\)/);
  assert.match(source, /Independent operator decision/);
  assert.match(source, /decided_by:/);
  assert.match(source, /rationale:/);
  assert.match(source, /source_suggestion_key:/);
  assert.match(source, /\/api\/site-plans\/navigation-sets\/\$\{navSet\.id\}/);
  assert.doesNotMatch(source, /method:\s*"DELETE"/);
  assert.doesNotMatch(source, /Shawn Manchette/);
  const setDecisionSource = source.slice(
    source.indexOf("function NavigationSetDecision"),
    source.indexOf("function NavigationItemEditor"),
  );
  assert.doesNotMatch(setDecisionSource, /source_suggestion_key|Source suggestion/);
});

test("navigation suggestions use backend label and validated ordering fields", () => {
  assert.deepEqual(
    navigationSuggestionDefaults(
      { suggested_label: "  Service Areas  ", suggested_position: 4, label: "Wrong field" },
      "Fallback page name",
    ),
    { label: "Service Areas", position: 4 },
  );
  assert.deepEqual(
    navigationSuggestionDefaults(
      { suggested_label: "", suggested_position: -1 },
      "Fallback page name",
    ),
    { label: "Fallback page name", position: null },
  );
  assert.equal(
    navigationSuggestionDefaults({ suggested_position: "4" }, "Fallback").position,
    null,
  );
});
