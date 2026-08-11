import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";

import {
  bindPageMediaContext,
  effectivePlacementId,
  effectiveRequirementDecision,
  isCurrentPageMediaLoad,
  isPageMediaAssetEligible,
  isSafeLocalMediaUrl,
  placementReadinessStatus,
  validatePageMediaWorkspace,
} from "../src/components/pageMediaContext";
import {
  buildPageMediaAssignmentPayload,
  buildPageMediaDecisionPayload,
  pageMediaTargetLabel,
} from "../src/pages/PageMediaPlanningPage";
import {
  pageMediaDisplayPresetClassName,
  renderComponent,
  resolvePageMediaDisplayPreset,
} from "../src/pages/GeneratedPagePreview";
import type { DecisionFormState } from "../src/pages/PageMediaPlanningPage";
import type {
  PageMediaAssetCandidate,
  PageMediaPlacement,
  PageMediaPlanningWorkspace,
  PageComponentInstance,
  PageMediaRequirementDecision,
  SitePlan,
  Website,
  WebsiteContext,
} from "../src/types";

test("legacy page-media candidates come from the Website-scoped safe endpoint", () => {
  const source = readFileSync(
    resolve(process.cwd(), "src/pages/GeneratedPagesPage.tsx"),
    "utf8",
  );
  assert.match(source, /generated-pages\/\$\{pageId\}\/media\/candidates/);
  assert.doesNotMatch(
    source,
    /listItems<ImageMetadata>\("\/api\/image-metadata"\)/,
  );
});

test("unassigned governed media renders an honest local placeholder", () => {
  const component: PageComponentInstance = {
    instance_key: "media_placement:requirement-81",
    component_key: "media_placement",
    contract_version: 1,
    region: "main",
    position: 5,
    variant: "placeholder",
    input_bindings: {
      media_requirement_id: 81,
      target_component_key: "hero",
      target_component_instance_key: "hero",
      placement_contract_version: 2,
    },
    resolved_data: {
      purpose: "Establish the approved service visually.",
      intended_subject: "An authentic approved service photograph.",
      requirement_state: "required",
      placement_contract_version: 2,
    },
  };

  const markup = renderToStaticMarkup(renderComponent(component));

  assert.match(markup, /Establish the approved service visually\./);
  assert.match(markup, /Placement reserved for future approved media\./);
  assert.doesNotMatch(markup, /<img\b/i);
  assert.doesNotMatch(markup, /\bsrc=/i);
  assert.match(markup, /data-display-preset-status="unassigned"/);
  assert.match(markup, /data-display-preset-source="unassigned"/);
  assert.match(markup, /data-effective-display-preset="unassigned"/);
  assert.doesNotMatch(markup, /Governed media unavailable/);
});

function governedMediaComponent(
  resolvedOverrides: Record<string, unknown> = {},
  bindingOverrides: Record<string, unknown> = {},
): PageComponentInstance {
  return {
    instance_key: "media_placement:requirement-81",
    component_key: "media_placement",
    contract_version: 1,
    region: "main",
    position: 5,
    variant: "approved_media",
    input_bindings: {
      media_requirement_id: 81,
      target_component_key: "hero",
      target_component_instance_key: "hero",
      placement_contract_version: 2,
      ...bindingOverrides,
    },
    resolved_data: {
      purpose: "Establish the approved service visually.",
      placement_contract_version: 2,
      image_role: "hero",
      asset_url: "/api/media/files/service.webp",
      alt_text: "Approved service work.",
      image_title: "Approved service photograph",
      stored_display_preset: "hero_desktop",
      effective_display_preset: "hero_desktop",
      focal_x: 0.5,
      focal_y: 0.5,
      ...resolvedOverrides,
    },
  };
}

test("frontend receives and exposes the effective display preset", () => {
  const markup = renderToStaticMarkup(renderComponent(governedMediaComponent()));

  assert.match(markup, /data-effective-display-preset="hero_desktop"/);
  assert.match(markup, /data-display-preset-source="effective"/);
  assert.match(markup, /class="previewGalleryItem preset-hero-desktop"/);
});

test("landscape media uses an actual 16:9 frame without a 4:3 wrapper", () => {
  const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");

  assert.match(
    css,
    /\.previewGalleryItem\.preset-hero-desktop \.previewMediaFrame\s*\{[^}]*aspect-ratio:\s*16\s*\/\s*9;/s,
  );
  assert.doesNotMatch(
    css,
    /\.previewGalleryItem\.preset-hero-desktop \.previewMediaFrame\s*\{[^}]*aspect-ratio:\s*4\s*\/\s*3;/s,
  );
});

test("the 16:9 preset preserves the full image without crop or stretching", () => {
  const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");

  assert.match(
    css,
    /\.previewGalleryItem\.preset-hero-desktop \.previewMediaFrame img\s*\{[^}]*object-fit:\s*contain;/s,
  );
  assert.match(css, /\.previewMediaFrame img\s*\{[^}]*width:\s*100%;[^}]*max-width:\s*100%;[^}]*height:\s*100%;/s);
  assert.doesNotMatch(
    css,
    /\.previewGalleryItem\.preset-hero-desktop \.previewMediaFrame img\s*\{[^}]*object-fit:\s*(?:cover|fill);/s,
  );
});

test("desktop tablet and mobile share the bounded 16:9 contain contract", () => {
  const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");
  const className = pageMediaDisplayPresetClassName("hero_desktop");

  assert.equal(className, "previewGalleryItem preset-hero-desktop");
  assert.match(css, /\.previewGalleryItem\s*\{[^}]*min-width:\s*0;[^}]*max-width:\s*100%;/s);
  assert.match(css, /\.previewMediaFrame\s*\{[^}]*width:\s*100%;[^}]*max-width:\s*100%;[^}]*overflow:\s*hidden;/s);
  assert.doesNotMatch(css, /@media[^{}]*\{[^{}]*preset-hero-desktop[^{}]*(?:cover|fill)/s);
});

test("unknown or missing current V2 presets fail closed", () => {
  const unknown = governedMediaComponent({
    stored_display_preset: "panorama",
    effective_display_preset: "panorama",
  });
  const missing = governedMediaComponent({
    stored_display_preset: undefined,
    effective_display_preset: undefined,
  });
  const legacyAliasOnly = governedMediaComponent({
    stored_display_preset: undefined,
    display_preset: "hero_desktop",
  });

  for (const component of [unknown, missing, legacyAliasOnly]) {
    const resolution = resolvePageMediaDisplayPreset(
      component.resolved_data,
      component.input_bindings,
    );
    const markup = renderToStaticMarkup(renderComponent(component));
    assert.equal(resolution.preset, null);
    assert.equal(resolution.source, "blocked_current");
    assert.match(markup, /data-display-preset-status="blocked"/);
    assert.doesNotMatch(markup, /<img\b/i);
  }
});

test("historical missing presets use the explicit non-cropping legacy fallback", () => {
  const component = governedMediaComponent(
    {
      placement_contract_version: 1,
      stored_display_preset: undefined,
      effective_display_preset: undefined,
    },
    { placement_contract_version: 1 },
  );
  const resolution = resolvePageMediaDisplayPreset(
    component.resolved_data,
    component.input_bindings,
  );
  const markup = renderToStaticMarkup(renderComponent(component));

  assert.deepEqual(resolution, {
    preset: "original",
    source: "legacy_fallback",
    error: null,
  });
  assert.match(markup, /preset-original/);
  assert.match(markup, /data-display-preset-source="legacy_fallback"/);
});

test("filename rationale and alt text cannot control the display preset", () => {
  const component = governedMediaComponent({
    effective_display_preset: undefined,
    stored_display_preset: undefined,
    original_filename: "hero_desktop.webp",
    assignment_rationale: "Use hero_desktop.",
    alt_text: "hero_desktop",
  });
  const resolution = resolvePageMediaDisplayPreset(
    component.resolved_data,
    component.input_bindings,
  );

  assert.equal(resolution.preset, null);
  assert.equal(resolution.source, "blocked_current");
});

test("process and evidence placements share a landscape preset without becoming hero roles", () => {
  const processMarkup = renderToStaticMarkup(renderComponent(governedMediaComponent({
    image_role: "service",
  })));
  const evidenceMarkup = renderToStaticMarkup(renderComponent(governedMediaComponent({
    image_role: "support",
  })));

  assert.match(processMarkup, /preset-hero-desktop/);
  assert.match(processMarkup, /data-semantic-media-role="service"/);
  assert.match(evidenceMarkup, /preset-hero-desktop/);
  assert.match(evidenceMarkup, /data-semantic-media-role="support"/);
  assert.doesNotMatch(processMarkup, /data-semantic-media-role="hero"/);
  assert.doesNotMatch(evidenceMarkup, /data-semantic-media-role="hero"/);
});

test("canonical semantic role and display preset remain separate concerns", () => {
  const process = governedMediaComponent({ image_role: "service" });
  const evidence = governedMediaComponent({ image_role: "support" });

  assert.deepEqual(
    resolvePageMediaDisplayPreset(process.resolved_data, process.input_bindings),
    resolvePageMediaDisplayPreset(evidence.resolved_data, evidence.input_bindings),
  );
});

const website: Website = {
  id: 31,
  business_id: 11,
  brand_id: 21,
  website_name: "Example Website",
  domain: "example.test",
  public_url: "https://example.test",
  locale: "en-US",
  primary_language: "en",
  configuration: {},
  status: "active",
  created_at: "2026-08-07T00:00:00Z",
  updated_at: "2026-08-07T00:00:00Z",
};

const context: WebsiteContext = {
  business: {
    id: 11,
    company_name: "Example Company",
    business_type: "Service business",
    state: "FL",
  },
  brand: { id: 21, public_name: "Example", identity_settings: {} },
  website: {
    id: 31,
    website_name: "Example Website",
    domain: "example.test",
    public_url: "https://example.test",
    locale: "en-US",
    primary_language: "en",
    configuration: {},
    status: "active",
    legacy_fallback: false,
  },
  identity: { id: 41, display_name: "Example", status: "approved" },
};

const plan: SitePlan = {
  id: 51,
  website_id: 31,
  plan_key: "primary",
  plan_name: "Primary Site Plan",
  status: "active",
  version: 3,
  created_at: "2026-08-07T00:00:00Z",
  updated_at: "2026-08-07T00:00:00Z",
};

function candidate(overrides: Partial<PageMediaAssetCandidate> = {}): PageMediaAssetCandidate {
  return {
    id: 71,
    business_id: 11,
    website_id: 31,
    media_key: "service-photo",
    media_version: 1,
    image_title: "Approved service photograph",
    original_filename: "service.png",
    stored_filename: "service.png",
    managed_storage_path: ".runtime/media/service.png",
    asset_url: "/api/media/files/service.png",
    thumbnail_url: "/api/media/files/service-thumb.webp",
    optimized_url: "/api/media/files/service.webp",
    checksum_sha256: "a".repeat(64),
    mime_type: "image/webp",
    file_size: 4096,
    width: 1600,
    height: 900,
    acquisition_source: "company_photograph",
    creator_source_identity: "Example Company",
    provenance_type: "company_original",
    provenance_notes: "Operator supplied original.",
    rights_status: "owned",
    rights_holder: "Example Company",
    rights_notes: "Approved company media.",
    approved_usage: ["page_media", "hero"],
    prohibited_usage: [],
    permitted_placement_keys: ["hero"],
    accessibility_intent: "informative",
    reviewed_alt_text: "A technician inspecting a home.",
    governance_status: "approved",
    approval_version: 1,
    approval_fingerprint: "b".repeat(64),
    usage_authorization_mode: "contract_default",
    required_authorization_terms: [],
    approved_by: "Operator",
    approved_at: "2026-08-07T00:00:00Z",
    retired_by: null,
    retirement_rationale: null,
    retired_at: null,
    replaces_image_metadata_id: null,
    gps_metadata_status: "absent",
    gps_metadata: {},
    gps_authorized_by: null,
    gps_authorized_at: null,
    gps_authorization_notes: null,
    created_at: "2026-08-07T00:00:00Z",
    updated_at: "2026-08-07T00:00:00Z",
    ...overrides,
  };
}

function decision(overrides: Partial<PageMediaRequirementDecision> = {}): PageMediaRequirementDecision {
  return {
    id: 81,
    website_id: 31,
    business_id: 11,
    site_plan_id: 51,
    planned_page_id: 61,
    planning_record_id: 111,
    component_or_section: "hero",
    target_component_instance_key: "hero",
    placement_key: "hero",
    contract_version: 2,
    requirement_state: "required",
    purpose: "Help visitors understand the service.",
    customer_outcome: "Understand the service.",
    intended_subject: "Approved service work.",
    orientation: "landscape",
    aspect_ratio: "16:9",
    effective_display_preset: "hero_desktop",
    minimum_width: 1200,
    minimum_height: 675,
    crop_intent: "Preserve the subject.",
    focal_point_intent: "Use the reviewed focal point.",
    responsive_behavior: "Use responsive derivatives.",
    accessibility_intent: "informative",
    caption_intent: null,
    approved_source_constraints: ["approved_company_media"],
    permitted_reuse_policy: "Reuse only for the same purpose.",
    replacement_policy: "Replacement requires operator approval.",
    compatible_page_types: ["service"],
    version: 1,
    decided_by: "Operator",
    rationale: "The hero image helps explain the service.",
    source_suggestion_key: "61:hero:v2",
    decided_at: "2026-08-07T00:05:00Z",
    lifecycle_status: "active",
    replaces_requirement_id: null,
    created_at: "2026-08-07T00:05:00Z",
    updated_at: "2026-08-07T00:05:00Z",
    ...overrides,
  };
}

function placement(overrides: Partial<PageMediaPlacement> = {}): PageMediaPlacement {
  const requirement = decision();
  return {
    placement_id: 81,
    planned_page: {
      id: 61,
      website_id: 31,
      site_plan_id: 51,
      page_type: "service",
      working_name: "Service",
      intended_slug: "service",
      generated_page_id: 91,
    },
    suggestion: {
      suggestion_key: "61:hero:v2",
      website_id: 31,
      business_id: 11,
      site_plan_id: 51,
      planned_page_id: 61,
      page_type: "service",
      contract_page_type: "service",
      compatible_page_types: ["service"],
      placement_key: "hero",
      component_or_section: "hero",
      target_component_instance_key: "hero",
      requirement_state: "required",
      purpose: "Help visitors understand the service.",
      customer_outcome: "Understand the service.",
      intended_subject: "Show approved service work without invented claims.",
      orientation: "landscape",
      aspect_ratio: "16:9",
      minimum_width: 1200,
      minimum_height: 675,
      crop_intent: "Preserve the approved subject.",
      focal_point_intent: "Use the reviewed focal point.",
      responsive_behavior: "Use approved responsive derivatives.",
      accessibility_intent: "informative",
      caption_intent: null,
      approved_source_constraints: ["approved_company_media"],
      permitted_reuse_policy: "Reuse only for the same approved purpose.",
      replacement_policy: "Replacement requires operator approval.",
      contract_version: 2,
    },
    effective_requirement: requirement,
    requirement_history: [requirement],
    active_assignment: {
      id: 101,
      generated_page_id: 91,
      image_metadata_id: 71,
      website_id: 31,
      site_plan_id: 51,
      planned_page_id: 61,
      media_requirement_id: 81,
      assignment_version: 1,
      media_version: 1,
      placement_contract_version: 2,
      image_role: "hero",
      sort_order: 0,
      override_focal_x: null,
      override_focal_y: null,
      override_alt_text: null,
      display_preset: "hero_desktop",
      effective_display_preset: "hero_desktop",
      status: "active",
      assigned_by: "Operator",
      assignment_rationale: "Approved for the service hero.",
      assigned_at: "2026-08-07T00:10:00Z",
      replaced_at: null,
      replaced_by: null,
      replacement_rationale: null,
      retired_by: null,
      retirement_rationale: null,
      retired_at: null,
      replaces_page_image_assignment_id: null,
      created_at: "2026-08-07T00:10:00Z",
      updated_at: "2026-08-07T00:10:00Z",
    },
    legacy_assignments: [],
    compatible_asset_ids: [71],
    blocking_reasons: [],
    composition_status: "current",
    readiness: "ready",
    ...overrides,
  };
}

function decisionForm(
  overrides: Partial<DecisionFormState> = {},
): DecisionFormState {
  const source = decision();
  return {
    requirementState: source.requirement_state,
    operator: "Operator",
    rationale: "Approved purpose.",
    componentOrSection: source.component_or_section,
    targetComponentInstanceKey: source.target_component_instance_key ?? "",
    purpose: source.purpose,
    customerOutcome: source.customer_outcome,
    intendedSubject: source.intended_subject,
    orientation: source.orientation,
    aspectRatio: source.aspect_ratio,
    minimumWidth: String(source.minimum_width),
    minimumHeight: String(source.minimum_height),
    cropIntent: source.crop_intent,
    focalPointIntent: source.focal_point_intent,
    responsiveBehavior: source.responsive_behavior,
    accessibilityIntent: source.accessibility_intent,
    captionIntent: source.caption_intent ?? "",
    approvedSourceConstraints: source.approved_source_constraints.join("\n"),
    permittedReusePolicy: source.permitted_reuse_policy,
    replacementPolicy: source.replacement_policy,
    compatiblePageTypes: source.compatible_page_types.join("\n"),
    ...overrides,
  };
}

function workspace(overrides: Partial<PageMediaPlanningWorkspace> = {}): PageMediaPlanningWorkspace {
  const item = placement();
  return {
    website_id: 31,
    business_id: 11,
    site_plan_id: 51,
    site_plan_version: 3,
    planning_record: {
      id: 111,
      website_id: 31,
      business_id: 11,
      site_plan_id: 51,
      version: 1,
      algorithm_version: "page-media-planning-v2",
      generated_media_suggestions: item.suggestion ? [item.suggestion] : [],
      source_snapshot: {},
      source_hash: "b".repeat(64),
      generated_at: "2026-08-07T00:00:00Z",
      replaces_record_id: null,
      created_at: "2026-08-07T00:00:00Z",
      updated_at: "2026-08-07T00:00:00Z",
    },
    summary: {
      planned_pages: 1,
      pages_with_current_plan: 1,
      pages_without_plan: 0,
      suggested_placements: 1,
      required_placements: 1,
      advisory_placements: 0,
      excluded_placements: 0,
      deferred_placements: 0,
      approved_assignments: 1,
      missing_required_media: 0,
      incomplete_governance: 0,
      incompatible_assignments: 0,
      stale_compositions: 0,
      pages_media_ready: 1,
      page_type_coverage: { service: { pages: 1, with_plan: 1, ready: 1 } },
    },
    placements: [item],
    assets: [candidate()],
    diagnostics: [],
    ready: true,
    evaluated_at: "2026-08-07T00:15:00Z",
    ...overrides,
  };
}

test("Website Context and Site Plan form one authoritative Page Media binding", () => {
  assert.deepEqual(bindPageMediaContext(website, context, plan), {
    websiteId: 31,
    businessId: 11,
    brandId: 21,
    identityId: 41,
    sitePlanId: 51,
  });
  assert.throws(
    () => bindPageMediaContext(website, { ...context, website: { ...context.website, legacy_fallback: true } }, plan),
    /legacy fallback cannot be used/,
  );
  assert.throws(
    () => bindPageMediaContext(website, context, { ...plan, website_id: 99 }),
    /does not belong/,
  );
});

test("aggregate results fail closed across every ownership boundary", () => {
  const binding = bindPageMediaContext(website, context, plan);
  assert.equal(validatePageMediaWorkspace(workspace(), binding).ready, true);
  assert.throws(
    () => validatePageMediaWorkspace(workspace({ website_id: 99 }), binding),
    /crossed the authoritative Website or Site Plan boundary/,
  );
  assert.throws(
    () => validatePageMediaWorkspace(workspace({ assets: [candidate({ business_id: 99 })] }), binding),
    /Business boundary/,
  );
  assert.throws(
    () => validatePageMediaWorkspace(workspace({ placements: [placement({ planned_page: { ...placement().planned_page, website_id: 99 } })] }), binding),
    /placement crossed/,
  );
  const legacy = {
    ...placement().active_assignment!,
    media_requirement_id: null,
    website_id: null,
    site_plan_id: null,
    planned_page_id: null,
  };
  assert.doesNotThrow(() =>
    validatePageMediaWorkspace(
      workspace({ placements: [placement({ legacy_assignments: [legacy] })] }),
      binding,
    ),
  );
});

test("null planning state is readable but cannot fabricate an operator decision", () => {
  const binding = bindPageMediaContext(website, context, plan);
  assert.equal(validatePageMediaWorkspace(workspace({ planning_record: null }), binding).planning_record, null);
  assert.throws(
    () => buildPageMediaDecisionPayload(
      workspace({ planning_record: null }),
      placement(),
      decisionForm(),
    ),
    /planning record and suggestion are required/,
  );
});

test("operator decision history is deterministic and suggestions remain separate", () => {
  const first = decision({ id: 1, version: 1 });
  const second = decision({ id: 2, version: 2, rationale: "New operator rationale." });
  assert.equal(effectiveRequirementDecision([second, first])?.id, 2);
  assert.throws(() => effectiveRequirementDecision([first, { ...second, version: 1 }]), /duplicate version/);
  const payload = buildPageMediaDecisionPayload(workspace(), placement(), decisionForm({
    requirementState: "deferred",
    operator: "  Human Operator  ",
    rationale: "  Awaiting an authentic approved photograph.  ",
  }));
  assert.equal(payload.decided_by, "Human Operator");
  assert.equal(payload.rationale, "Awaiting an authentic approved photograph.");
  assert.equal(payload.source_suggestion_key, "61:hero:v2");
  assert.equal(payload.expected_planning_version, 1);
  assert.equal(payload.requirement_state, "deferred");
  assert.equal(payload.target_component_instance_key, "hero");
  assert.equal(payload.minimum_width, 1200);
  assert.deepEqual(payload.approved_source_constraints, ["approved_company_media"]);
  assert.deepEqual(Object.keys(payload).sort(), [
    "accessibility_intent",
    "approved_source_constraints",
    "aspect_ratio",
    "caption_intent",
    "compatible_page_types",
    "component_or_section",
    "crop_intent",
    "customer_outcome",
    "decided_by",
    "expected_planning_version",
    "focal_point_intent",
    "intended_subject",
    "minimum_height",
    "minimum_width",
    "orientation",
    "permitted_reuse_policy",
    "placement_key",
    "planned_page_id",
    "purpose",
    "rationale",
    "replacement_policy",
    "requirement_state",
    "responsive_behavior",
    "site_plan_id",
    "source_suggestion_key",
    "target_component_instance_key",
    "website_id",
  ]);
  assert.throws(
    () => buildPageMediaDecisionPayload(
      workspace(),
      placement(),
      decisionForm({ targetComponentInstanceKey: "  " }),
    ),
    /Exact component instance is required/,
  );
});

test("exact component-instance targets remain visible while V1 history is explicit", () => {
  assert.equal(pageMediaTargetLabel(decision()), "hero / hero");
  assert.equal(
    pageMediaTargetLabel(decision({
      contract_version: 1,
      target_component_instance_key: null,
    })),
    "hero / historical component-only target",
  );
});

test("only governed local compatible assets may be assigned", () => {
  assert.equal(isPageMediaAssetEligible(candidate()), true);
  assert.equal(isPageMediaAssetEligible(candidate({ optimized_url: "https://example.com/image.webp" })), false);
  assert.equal(isPageMediaAssetEligible(candidate({ rights_status: "unknown" })), false);
  assert.equal(isPageMediaAssetEligible(candidate({ reviewed_alt_text: null })), false);
  assert.equal(isPageMediaAssetEligible(candidate({ reviewed_alt_text: null }), "decorative"), true);
  assert.equal(isSafeLocalMediaUrl("/api/media/files/example.webp"), true);
  assert.equal(isSafeLocalMediaUrl("http://localhost:8000/media/optimized/example.webp"), true);
  assert.equal(isSafeLocalMediaUrl("//external.example/image.webp"), false);

  const payload = buildPageMediaAssignmentPayload(placement(), {
    imageMetadataId: "71",
    operator: "Operator",
    rationale: "Approved for this exact placement.",
  });
  assert.equal(payload.image_metadata_id, 71);
  assert.equal(payload.expected_requirement_version, 1);
  assert.deepEqual(Object.keys(payload).sort(), [
    "assigned_by",
    "expected_requirement_version",
    "image_metadata_id",
    "rationale",
  ]);
  assert.throws(
    () => buildPageMediaAssignmentPayload(placement(), { imageMetadataId: "999", operator: "Operator", rationale: "Wrong asset." }),
    /not compatible/,
  );
  assert.throws(
    () => buildPageMediaAssignmentPayload(placement({ effective_requirement: decision({ requirement_state: "excluded" }) }), { imageMetadataId: "71", operator: "Operator", rationale: "Not allowed." }),
    /Only a required or advisory/,
  );
});

test("readiness and request-generation helpers remain deterministic", () => {
  assert.equal(effectivePlacementId(placement()), 81);
  assert.equal(placementReadinessStatus(placement()), "ready");
  assert.equal(placementReadinessStatus(placement({ active_assignment: null, readiness: "awaiting_assignment" })), "awaiting_assignment");
  assert.equal(placementReadinessStatus(placement({ effective_requirement: decision({ requirement_state: "deferred" }), readiness: "deferred" })), "deferred");
  assert.equal(placementReadinessStatus(placement({ composition_status: "stale", readiness: "stale" })), "stale");
  assert.equal(isCurrentPageMediaLoad(4, 4), true);
  assert.equal(isCurrentPageMediaLoad(4, 5), false);
});

test("workspace uses only bounded local Page Media and composition endpoints", () => {
  const source = readFileSync(resolve(process.cwd(), "src/pages/PageMediaPlanningPage.tsx"), "utf8");
  assert.match(source, /\/api\/site-plans\/\$\{plan\.id\}\/page-media/);
  assert.match(source, /page-media\/suggestions\/refresh/);
  assert.match(source, /page-media\/placements\/decide/);
  assert.match(source, /page-media\/placements\/\$\{placementId\}\/assign/);
  assert.match(source, /\/compositions\/refresh/);
  assert.match(source, /Historical assignment observations/);
  assert.match(source, /Exact component instance \*/);
  assert.match(source, /target_component_instance_key/);
  assert.match(source, /never treated as Page Media approval/);
  assert.match(source, /never refresh automatically/);
  assert.doesNotMatch(source, /\/api\/wordpress|siteground|drywoodtenting\.com/i);
  assert.doesNotMatch(source, /\/api\/media\/upload|uploadMedia\(/);
  assert.doesNotMatch(source, /Shawn Manchette/);
});
