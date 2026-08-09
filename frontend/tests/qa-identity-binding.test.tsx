import test from "node:test";
import assert from "node:assert/strict";

import { effectiveQaDisplayStatus } from "../src/pages/GeneratedPagePreview";
import {
  effectiveStoredQaStatus,
  nextQaRequestSequenceForSelection,
  qaResultBelongsToSelection,
} from "../src/pages/GeneratedPagesPage";
import type { GeneratedPage, PageQAResult } from "../src/types";


function qa(overrides: Partial<PageQAResult> = {}): PageQAResult {
  return {
    qa_result_id: 91,
    page_id: 41,
    website_id: 1,
    site_plan_id: 1,
    planned_page_id: 41,
    latest_generated_page_revision_id: 7,
    content_hash: "a".repeat(64),
    source_hash: "b".repeat(64),
    page_composition_id: 41,
    composition_version: 7,
    composition_source_hash: "c".repeat(64),
    qa_algorithm_key: "atlas-page-qa",
    qa_algorithm_version: "2",
    qa_ruleset_key: "atlas-page-qa-rules",
    qa_ruleset_version: "2",
    qa_ruleset_hash: "d".repeat(64),
    readiness_status: "ready",
    checked_at: "2026-08-09T17:00:00Z",
    passed_count: 23,
    warning_count: 0,
    failed_count: 0,
    checks: [],
    result_hash: "e".repeat(64),
    lifecycle_status: "current",
    currentness_status: "current_exact_identity_match",
    currentness_reasons: [],
    persisted: true,
    ...overrides,
  };
}

function page(result: PageQAResult | null): GeneratedPage {
  return {
    id: 41,
    business_id: 1,
    website_id: 1,
    page_type: "city_service",
    page_title: "Orlando",
    page_slug: "orlando",
    status: "draft",
    generation_status: "generated",
    qa_status: "ready",
    qa_result: result,
  } as GeneratedPage;
}

test("a Page 1 QA projection never displays ready for Page 41", () => {
  assert.equal(effectiveStoredQaStatus(page(qa({ page_id: 1 }))), "not_run");
});

test("only an exact current stored projection displays its outcome", () => {
  assert.equal(effectiveStoredQaStatus(page(qa())), "ready");
  assert.equal(
    effectiveStoredQaStatus(
      page(qa({ readiness_status: "needs_review", warning_count: 1 })),
    ),
    "needs_review",
  );
  assert.equal(
    effectiveStoredQaStatus(page(qa({ currentness_status: "stale_composition" }))),
    "not_run",
  );
});

test("preview candidates and identity mismatches never display ready", () => {
  assert.equal(effectiveQaDisplayStatus(qa({ persisted: false })), "not_run");
  assert.equal(
    effectiveQaDisplayStatus(
      qa({ currentness_status: "wrong_page_identity", persisted: false }),
    ),
    "not_run",
  );
  assert.equal(effectiveQaDisplayStatus(qa()), "ready");
});

test("an out-of-order QA response cannot cross-bind the selected page", () => {
  assert.equal(qaResultBelongsToSelection(qa({ page_id: 1 }), 1, 41, 2, 2), false);
  assert.equal(qaResultBelongsToSelection(qa({ page_id: 1 }), 41, 41, 2, 2), false);
  assert.equal(qaResultBelongsToSelection(qa({ page_id: 41 }), 41, 41, 1, 2), false);
  assert.equal(qaResultBelongsToSelection(qa({ page_id: 41 }), 41, 41, 2, 2), true);
});

test("a pre-run GET cannot overwrite the same page's newer QA result", () => {
  assert.equal(qaResultBelongsToSelection(qa(), 41, 41, 7, 8), false);
  assert.equal(qaResultBelongsToSelection(qa(), 41, 41, 8, 8), true);
});

test("a former page reload cannot invalidate the current selection's QA request", () => {
  assert.equal(nextQaRequestSequenceForSelection(41, 42, 8), null);
  assert.equal(nextQaRequestSequenceForSelection(42, 42, 8), 9);
});
