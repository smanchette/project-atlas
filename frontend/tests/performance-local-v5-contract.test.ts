import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

import {
  auditPerformanceLocalV5ConversionEvidence,
  auditPerformanceLocalV5FullSite,
  auditPerformanceLocalV5Page41Preservation,
  PERFORMANCE_LOCAL_V5_CURRENT_SITE_EXPECTATION,
  PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION,
  type PerformanceLocalV5ConversionAuditEvidence,
} from "../src/components/performanceLocalV5Audit";
import {
  auditPerformanceLocalV5Composition,
  PERFORMANCE_LOCAL_V5_LAYOUT_MANIFESTS,
  resolvePerformanceLocalV5Layout,
  type PerformanceLocalV5PageType,
} from "../src/components/performanceLocalV5LayoutContract";
import {
  PERFORMANCE_LOCAL_V5_DEMO_MEDIA_LABEL,
  PERFORMANCE_LOCAL_V5_FORM_FIELD_CONTRACT,
  PERFORMANCE_LOCAL_V5_PREVIEW_LABEL,
  PERFORMANCE_LOCAL_V5_SERIALIZED_COMPONENT_CONTRACTS,
  PERFORMANCE_LOCAL_V5_THEME,
} from "../src/components/performanceLocalThemeV5";
import {
  PERFORMANCE_LOCAL_SERIALIZED_COMPONENT_CONTRACTS,
  PERFORMANCE_LOCAL_THEME,
} from "../src/components/performanceLocalTheme";
import {
  PERFORMANCE_LOCAL_V3_SERIALIZED_COMPONENT_CONTRACTS,
  PERFORMANCE_LOCAL_V3_THEME,
} from "../src/components/performanceLocalThemeV3";
import {
  PERFORMANCE_LOCAL_V4_SERIALIZED_COMPONENT_CONTRACTS,
  PERFORMANCE_LOCAL_V4_THEME,
} from "../src/components/performanceLocalThemeV4";
import {
  auditPerformanceLocalV4Page41Preservation,
  PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION,
} from "../src/components/performanceLocalV4Audit";
import type {
  GeneratedPage,
  PageComponentInstance,
  PageComposition,
  PageMediaPlanningWorkspace,
  PlannedPage,
} from "../src/types";

const hash = "a".repeat(64);
const pageTypes: readonly PerformanceLocalV5PageType[] = Object.freeze([
  "home",
  "service",
  "county",
  "city_service",
  "about",
  "contact",
  "faq",
]);

test("V5 is a distinct frozen source-only preview candidate without mutating V2, V3, or V4", () => {
  const v2Before = JSON.stringify(PERFORMANCE_LOCAL_SERIALIZED_COMPONENT_CONTRACTS);
  const v3Before = JSON.stringify(PERFORMANCE_LOCAL_V3_SERIALIZED_COMPONENT_CONTRACTS);
  const v4Before = JSON.stringify(PERFORMANCE_LOCAL_V4_SERIALIZED_COMPONENT_CONTRACTS);

  assert.equal(PERFORMANCE_LOCAL_THEME.version, 2);
  assert.equal(PERFORMANCE_LOCAL_V3_THEME.version, 3);
  assert.equal(PERFORMANCE_LOCAL_V4_THEME.version, 4);
  assert.equal(PERFORMANCE_LOCAL_V5_THEME.key, "performance-local");
  assert.equal(PERFORMANCE_LOCAL_V5_THEME.version, 5);
  assert.equal(PERFORMANCE_LOCAL_V5_THEME.status, "preview_candidate");
  assert.equal(PERFORMANCE_LOCAL_V5_THEME.productionReady, false);
  assert.equal(PERFORMANCE_LOCAL_V5_THEME.sourceOnly, true);
  assert.equal(PERFORMANCE_LOCAL_V5_THEME.durableRegistration, "absent_by_design");
  assert.equal(PERFORMANCE_LOCAL_V5_THEME.activeSelection, "absent_by_design");
  assert.equal(PERFORMANCE_LOCAL_V5_THEME.activationReady, false);
  assert.equal(PERFORMANCE_LOCAL_V5_THEME.publicExportEligible, false);
  assert.equal(PERFORMANCE_LOCAL_V5_THEME.compatibilityIdentity, "atlas-semantic-composition@1|performance-local@5");
  assert.equal(PERFORMANCE_LOCAL_V5_THEME.rendererContract, "performance-local-page-layouts@2");
  assert.equal(PERFORMANCE_LOCAL_V5_PREVIEW_LABEL, "PERFORMANCE LOCAL V5 \u2014 DRAFT PREVIEW \u2014 NOT ACTIVE");
  assert.equal(PERFORMANCE_LOCAL_V5_DEMO_MEDIA_LABEL, "DEMO MEDIA SLOT \u2014 NOT SITE CONTENT");
  assert.deepEqual(PERFORMANCE_LOCAL_V5_FORM_FIELD_CONTRACT, {
    defaultCustomerEntryFieldCount: 5,
    maximumCustomerEntryFieldCount: 6,
    activeOptionalFieldCount: 0,
    seventhFieldBehavior: "reject",
  });
  assert.equal(PERFORMANCE_LOCAL_V5_SERIALIZED_COMPONENT_CONTRACTS.length, 23);
  assert.ok(PERFORMANCE_LOCAL_V5_SERIALIZED_COMPONENT_CONTRACTS.every((item) =>
    item.contract_version === 5 && item.theme_compatibility[0] === "performance-local@5",
  ));
  assert.deepEqual(
    PERFORMANCE_LOCAL_V5_SERIALIZED_COMPONENT_CONTRACTS.map((item) => item.component_key),
    PERFORMANCE_LOCAL_V4_SERIALIZED_COMPONENT_CONTRACTS.map((item) => item.component_key),
  );
  assert.deepEqual(PERFORMANCE_LOCAL_V5_THEME.immutablePredecessor, {
    themeCompatibility: "performance-local@4",
    rendererContract: "performance-local-page-layouts@1",
    identityTreatment: "preserve_as_immutable_v4_source",
    mutation: "forbidden",
  });
  assert.deepEqual(PERFORMANCE_LOCAL_V5_THEME.governedConversionInput, {
    themeCompatibility: "performance-local@3",
    rendererContract: "performance-local-delivery@1",
    identityTreatment: "preserve_as_v3_input",
    mutation: "forbidden",
  });
  assert.equal(JSON.stringify(PERFORMANCE_LOCAL_SERIALIZED_COMPONENT_CONTRACTS), v2Before);
  assert.equal(JSON.stringify(PERFORMANCE_LOCAL_V3_SERIALIZED_COMPONENT_CONTRACTS), v3Before);
  assert.equal(JSON.stringify(PERFORMANCE_LOCAL_V4_SERIALIZED_COMPONENT_CONTRACTS), v4Before);
  assert.ok(Object.isFrozen(PERFORMANCE_LOCAL_V5_THEME));
  assert.ok(Object.isFrozen(PERFORMANCE_LOCAL_V5_SERIALIZED_COMPONENT_CONTRACTS));
});

test("the six immutable V4 source files retain their exact approved byte identities", () => {
  const expected = {
    "src/components/performanceLocalThemeV4.ts": "f70ff8b7971c279bab7e3a2a214d00ec08e0554bbec5bd91398f5f1de338623f",
    "src/components/performanceLocalV4LayoutContract.ts": "6fc6e374f0d738dd7556b9dd60f22d8ca58a501edf1f74b366c010caddb85dc3",
    "src/components/performanceLocalV4Audit.ts": "65e3a3c995fa2c50f3e9970e1695c722a17d0858291f6e6d0b7c21122b20aa95",
    "src/components/PerformanceLocalV4Layouts.tsx": "d1536b2cf5ee34036727e291b4c51ebf431d5339370f5c739194e9d0449e4559",
    "src/components/PerformanceLocalV4Renderer.tsx": "5233ab9802ac5eb7ce73b2cf94accc0a6d7b8843900d087451c5eb6d3f2a7ced",
    "src/pages/PerformanceLocalV4ReviewPage.tsx": "1316053d3616d4a14194609328b39bce0cb5e311896b0e315f2cd8a536483895",
  } as const;
  for (const [relativePath, expectedSha256] of Object.entries(expected)) {
    const bytes = readFileSync(resolve(process.cwd(), relativePath));
    assert.equal(createHash("sha256").update(bytes).digest("hex"), expectedSha256, relativePath);
  }
});

test("the exact seven-type resolver is deterministic and rejects aliases, unknowns, and prototype keys", () => {
  const expectedKeys = {
    home: "performance-local-v5-home",
    service: "performance-local-v5-service",
    county: "performance-local-v5-service-county",
    city_service: "performance-local-v5-city-service",
    about: "performance-local-v5-about",
    contact: "performance-local-v5-contact",
    faq: "performance-local-v5-faq",
  } as const;
  assert.deepEqual(Object.keys(PERFORMANCE_LOCAL_V5_LAYOUT_MANIFESTS), pageTypes);
  for (const pageType of pageTypes) {
    const first = resolvePerformanceLocalV5Layout(pageType);
    const second = resolvePerformanceLocalV5Layout(pageType);
    assert.equal(first.status, "resolved");
    assert.equal(second.status, "resolved");
    if (first.status !== "resolved" || second.status !== "resolved") continue;
    assert.strictEqual(first.manifest, second.manifest);
    assert.equal(first.manifest.supportedPageType, pageType);
    assert.equal(first.manifest.layoutKey, expectedKeys[pageType]);
    assert.equal(first.manifest.layoutVersion, 2);
    assert.equal(first.manifest.missingInputBehavior.genericFallback, "forbidden");
    assert.deepEqual(first.manifest.destinationEntryPolicy, {
      sourceComponentConsumption: "one_logical_claim",
      nestedEntryConsumption: "each_original_index_exactly_once",
      homeServiceMatching: "exact_title_to_exact_governed_label",
      countyCityMatching: "exact_ordered_city_suffix_to_governed_prefix",
      fallback: "forbidden",
    });
    assert.deepEqual(first.manifest.finalConversionPolicy, {
      sharedAcrossPurposeBuiltLayouts: true,
      page41DelegationUnchanged: true,
      exactCallAction: true,
      exactEstimateDestination: true,
      providerDisabled: true,
      defaultFieldCount: 5,
      maximumFieldCount: 6,
    });
    assert.deepEqual(first.manifest.visibleTextColumnPolicy, { desktop: 3, tablet: 2, mobile: 1 });
    assert.deepEqual(first.manifest.contentHeightPolicy, {
      ordinaryContentMinimumHeight: "forbidden",
      viewportHeightOutsideMobileDrawer: "forbidden",
      shortTextOnlyFullWidthBand: "forbidden_when_composable",
    });
    assert.deepEqual(first.manifest.navigationPresentationPolicy, {
      sourceClaimPolicy: "consume_each_navigation_component_exactly_once",
      headerSetPriority: ["primary_navigation", "utility_navigation"],
      duplicateHeaderTargetPolicy: "retain_source_claim_dedupe_presentation_by_target_planned_page_id",
      footerTargetScope: "independent_footer_navigation",
      invalidTargetPolicy: "block",
    });
    assert.ok(first.manifest.requiredSemanticRegions.length > 0);
    assert.ok(Object.isFrozen(first.manifest));
  }

  for (const raw of [
    "service_county",
    "city",
    "informational",
    "county ",
    "toString",
    "constructor",
    "__proto__",
    "hasOwnProperty",
    "",
    null,
    undefined,
  ]) {
    const resolution = resolvePerformanceLocalV5Layout(raw);
    assert.equal(resolution.status, "blocked", String(raw));
    if (resolution.status === "blocked") assert.ok(resolution.blockers.length > 0);
  }
  const forbiddenAlias = resolvePerformanceLocalV5Layout("service_county");
  assert.equal(forbiddenAlias.status, "blocked");
  if (forbiddenAlias.status === "blocked") {
    assert.deepEqual(forbiddenAlias.blockers.map((item) => item.code), ["service_county_alias_forbidden"]);
  }
  for (const prototypeKey of ["toString", "constructor", "__proto__", "hasOwnProperty"]) {
    const resolution = resolvePerformanceLocalV5Layout(prototypeKey);
    assert.equal(resolution.status, "blocked");
    if (resolution.status === "blocked") {
      assert.deepEqual(resolution.blockers.map((item) => item.code), ["unsupported_page_type"]);
    }
  }
  const county = resolvePerformanceLocalV5Layout("county");
  assert.equal(county.status, "resolved");
  if (county.status === "resolved") {
    assert.equal(county.manifest.displayName, "Service-County");
    assert.equal(county.manifest.supportedPageType, "county");
  }
});

test("V5 manifests encode the six corrected compositions and closed source-exact disclosure shapes", () => {
  assert.deepEqual(
    PERFORMANCE_LOCAL_V5_LAYOUT_MANIFESTS.home.visualCompositionRules.map((rule) => ({
      key: rule.compositionKey,
      regions: rule.regionKeys,
      variant: rule.presentationVariant,
    })),
    [
      { key: "home-service-discovery", regions: ["service_discovery"], variant: "featured_or_grid_service" },
      { key: "home-authority", regions: ["company_value", "service_area_discovery"], variant: "company_value_with_service_area" },
      { key: "home-related", regions: ["supporting_discovery"], variant: "related_destination_remainder" },
      { key: "home-final", regions: ["final_conversion"], variant: "shared_final_conversion" },
    ],
  );
  assert.deepEqual(
    PERFORMANCE_LOCAL_V5_LAYOUT_MANIFESTS.contact.semanticRegions
      .find((region) => region.regionKey === "contact_information")
      ?.selectors.map((selector) => selector.sectionKey ?? selector.componentKey),
    ["trust_license", "ways_to_contact", "hours", "service_area"],
  );
  assert.deepEqual(
    PERFORMANCE_LOCAL_V5_LAYOUT_MANIFESTS.about.visualCompositionRules
      .find((rule) => rule.compositionKey === "about-story-authority")?.regionKeys,
    ["company_story", "trust"],
  );

  const expectedDisclosureRegions = {
    home: [],
    service: ["approved_guidance", "faq"],
    county: ["customer_expectations", "faq"],
    city_service: [],
    about: [],
    contact: [],
    faq: ["faq"],
  } as const;
  for (const pageType of pageTypes) {
    const rules = PERFORMANCE_LOCAL_V5_LAYOUT_MANIFESTS[pageType].progressiveDisclosureRules;
    assert.deepEqual(rules.map((rule) => rule.regionKey), expectedDisclosureRegions[pageType]);
    assert.ok(rules.every((rule) =>
      rule.defaultState === "closed" &&
      rule.answerPolicy === "complete_source_exact" &&
      rule.openPresentation === "full_content_width" &&
      rule.maximumColumns.desktop === 2 &&
      rule.maximumColumns.tablet === 2 &&
      rule.maximumColumns.mobile === 1,
    ));
  }
  assert.equal(
    PERFORMANCE_LOCAL_V5_LAYOUT_MANIFESTS.county.semanticRegions
      .find((region) => region.regionKey === "faq")?.requirement,
    "required",
  );
  for (const pageType of pageTypes.filter((value) => value !== "city_service")) {
    assert.ok(PERFORMANCE_LOCAL_V5_LAYOUT_MANIFESTS[pageType].visualCompositionRules.some(
      (rule) => rule.presentationVariant === "shared_final_conversion" ||
        rule.presentationVariant === "support_and_credentials_with_shared_final",
    ));
  }
  assert.deepEqual(PERFORMANCE_LOCAL_V5_LAYOUT_MANIFESTS.city_service.visualCompositionRules, []);
});

test("long-form guidance keeps all 18 source groups and fails closed without exact disclosure headings", () => {
  for (const [pageType, sectionKey] of [
    ["service", "approved_guidance"],
    ["county", "customer_expectations"],
  ] as const) {
    const fixture = pageFixture(pageType, pageType === "service" ? 73 : 74);
    const source = fixture.composition.effective_components.find(
      (item) => item.input_bindings.section_key === sectionKey,
    )!;
    const bodyBefore = String(source.resolved_data.body);
    assert.equal((bodyBefore.match(/^### /gm) ?? []).length, 18);
    const ready = auditPerformanceLocalV5Composition(fixture);
    assert.equal(ready.layoutReady, true, JSON.stringify(ready.blockers));
    assert.equal(source.resolved_data.body, bodyBefore);

    const invalid = cloneFixture(fixture);
    const invalidSource = invalid.composition.effective_components.find(
      (item) => item.input_bindings.section_key === sectionKey,
    )!;
    invalidSource.resolved_data.body = "All answers exposed without source disclosure headings.";
    const blocked = auditPerformanceLocalV5Composition(invalid);
    assert.equal(blocked.layoutReady, false);
    assert.ok(blocked.blockers.some((item) => item.code === "progressive_disclosure_source_invalid"));
  }
});

test("all seven representative structures consume every source instance exactly once", () => {
  const expectedCounts = {
    home: 15,
    service: 15,
    county: 20,
    city_service: 18,
    about: 15,
    contact: 16,
    faq: 14,
  } as const;
  for (const [index, pageType] of pageTypes.entries()) {
    const fixture = pageFixture(pageType, index + 1);
    const sourceBefore = JSON.stringify(fixture);
    const audit = auditPerformanceLocalV5Composition(fixture);
    assert.equal(audit.resolutionStatus, "resolved", pageType);
    assert.equal(audit.status, "ready", pageType);
    assert.equal(audit.layoutReady, true, pageType);
    assert.equal(audit.pageType, pageType);
    assert.equal(audit.sourceComponentCount, expectedCounts[pageType]);
    assert.equal(audit.consumedComponentCount, expectedCounts[pageType]);
    assert.deepEqual(audit.unconsumedSourceInstanceKeys, []);
    assert.deepEqual(audit.duplicatedSourceInstanceKeys, []);
    assert.deepEqual(audit.missingRequiredRegionKeys, []);
    assert.equal(new Set(audit.consumption.map((item) => item.instanceKey)).size, expectedCounts[pageType]);
    assert.equal(JSON.stringify(fixture), sourceBefore, `${pageType} source mutated`);
  }

  const contact = auditPerformanceLocalV5Composition(pageFixture("contact", 71));
  assert.deepEqual(contact.regions.map((item) => item.regionKey), [
    "site_header",
    "hero",
    "immediate_contact",
    "contact_information",
    "final_conversion",
    "related_discovery",
    "site_footer",
  ]);
  const city = auditPerformanceLocalV5Composition(pageFixture(
    "city_service",
    PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.generatedPageId,
  ));
  assert.deepEqual(
    city.regions.flatMap((item) => item.sourceInstanceKeys),
    city.consumption.map((item) => item.instanceKey),
  );
  const groupedRegions = city.regions.filter((item) => item.presentationGroups.length > 0);
  assert.deepEqual(groupedRegions.map((item) => item.regionKey), ["process"]);
  assert.deepEqual(groupedRegions[0]?.presentationGroups, [{
    groupKey: "performance-local-v5-city-service:process",
    sourceInstanceKeys: [
      "content_section:process_section",
      "content_section:prep_section",
      "content_section:realtor_property_manager_section",
    ],
  }]);
  assert.ok(city.regions
    .filter((item) => item.regionKey !== "process")
    .every((item) => item.presentationGroups.length === 0));
  assert.deepEqual(
    city.consumption
      .filter((item) => item.regionKey === "process")
      .map((item) => ({ instanceKey: item.instanceKey, mode: item.mode, groupKey: item.groupKey })),
    [
      {
        instanceKey: "content_section:process_section",
        mode: "adjacent_group",
        groupKey: "performance-local-v5-city-service:process",
      },
      {
        instanceKey: "content_section:prep_section",
        mode: "adjacent_group",
        groupKey: "performance-local-v5-city-service:process",
      },
      {
        instanceKey: "content_section:realtor_property_manager_section",
        mode: "adjacent_group",
        groupKey: "performance-local-v5-city-service:process",
      },
    ],
  );
  const county = auditPerformanceLocalV5Composition(pageFixture("county", 74));
  const countyGroup = county.regions.find(
    (item) => item.regionKey === "related_city_discovery",
  )?.presentationGroups;
  assert.deepEqual(countyGroup, [{
    groupKey: "performance-local-v5-service-county:related_city_discovery",
    sourceInstanceKeys: ["content_section:related_city_services", "destination_cards"],
  }]);
  assert.deepEqual(
    county.consumption
      .filter((item) => item.regionKey === "related_city_discovery")
      .map((item) => ({ instanceKey: item.instanceKey, mode: item.mode, groupKey: item.groupKey })),
    [
      {
        instanceKey: "content_section:related_city_services",
        mode: "adjacent_group",
        groupKey: "performance-local-v5-service-county:related_city_discovery",
      },
      {
        instanceKey: "destination_cards",
        mode: "adjacent_group",
        groupKey: "performance-local-v5-service-county:related_city_discovery",
      },
    ],
  );
  for (const pageType of pageTypes.filter(
    (candidate) => candidate !== "city_service" && candidate !== "county",
  )) {
    const representative = auditPerformanceLocalV5Composition(pageFixture(pageType, 100 + pageTypes.indexOf(pageType)));
    assert.ok(representative.regions.every((item) => item.presentationGroups.length === 0), pageType);
    assert.ok(representative.consumption.every((item) => item.groupKey === null), pageType);
  }

  const overlappingHeaderNavigation = cloneFixture(pageFixture("home", 69));
  const governedContactTarget = {
    planned_page_id: 81,
    generated_page_id: 71,
    website_id: 1,
    site_plan_id: 1,
    intended_slug: "contact",
  };
  overlappingHeaderNavigation.composition.source_snapshot.navigation_items = [
    { id: 1, target: governedContactTarget },
    { id: 2, target: governedContactTarget },
  ];
  const primaryNavigation = overlappingHeaderNavigation.composition.effective_components.find(
    (item) => item.component_key === "primary_navigation",
  )!;
  const utilityNavigation = overlappingHeaderNavigation.composition.effective_components.find(
    (item) => item.component_key === "utility_navigation",
  )!;
  const resolvedContactTarget = {
    target_planned_page_id: 81,
    target_generated_page_id: 71,
    slug: "contact",
  };
  primaryNavigation.resolved_data.items = [{
    ...resolvedContactTarget,
    navigation_item_id: 1,
    parent_navigation_item_id: null,
    position: 0,
    label: "Contact",
  }];
  utilityNavigation.resolved_data.items = [{
    ...resolvedContactTarget,
    navigation_item_id: 2,
    parent_navigation_item_id: null,
    position: 0,
    label: "Contact us",
  }];
  const overlapAudit = auditPerformanceLocalV5Composition(overlappingHeaderNavigation);
  assert.equal(overlapAudit.layoutReady, true);
  assert.deepEqual(
    overlapAudit.consumption
      .filter((item) => item.mode === "nested_navigation")
      .map((item) => item.instanceKey),
    ["utility_navigation", "primary_navigation", "footer_navigation"],
  );

  primaryNavigation.resolved_data.items = [
    { ...resolvedContactTarget, navigation_item_id: 1, parent_navigation_item_id: null, position: 0, label: "Contact" },
    { ...resolvedContactTarget, navigation_item_id: 4, parent_navigation_item_id: null, position: 1, label: "Duplicate contact" },
  ];
  const duplicateWithinSetAudit = auditPerformanceLocalV5Composition(overlappingHeaderNavigation);
  assert.equal(duplicateWithinSetAudit.layoutReady, false);
  assert.ok(duplicateWithinSetAudit.blockers.some(
    (item) => item.code === "navigation_set_duplicate_target",
  ));

  const governedSelfNavigation = cloneFixture(pageFixture("home", 69));
  const governedSelfTarget = {
    planned_page_id: governedSelfNavigation.plannedPage.id,
    generated_page_id: governedSelfNavigation.page.id,
    website_id: governedSelfNavigation.composition.website_id,
    site_plan_id: governedSelfNavigation.composition.site_plan_id,
    intended_slug: governedSelfNavigation.plannedPage.intended_slug,
  };
  governedSelfNavigation.composition.source_snapshot.navigation_items = [
    { id: 3, target: governedSelfTarget },
  ];
  const selfNavigation = governedSelfNavigation.composition.effective_components.find(
    (item) => item.component_key === "primary_navigation",
  )!;
  selfNavigation.resolved_data.items = [{
    navigation_item_id: 3,
    target_planned_page_id: governedSelfTarget.planned_page_id,
    target_generated_page_id: governedSelfTarget.generated_page_id,
    parent_navigation_item_id: null,
    position: 0,
    slug: governedSelfTarget.intended_slug,
    label: "Home",
  }];
  const selfNavigationAudit = auditPerformanceLocalV5Composition(governedSelfNavigation);
  assert.equal(selfNavigationAudit.layoutReady, true);
  assert.ok(!selfNavigationAudit.blockers.some(
    (item) => item.code === "resolved_destination_scope_mismatch",
  ));

  const incompleteNavigation = cloneFixture(pageFixture("home", 69));
  const incompletePrimary = incompleteNavigation.composition.effective_components.find(
    (item) => item.component_key === "primary_navigation",
  )!;
  incompletePrimary.resolved_data.items = [{
    navigation_item_id: 5,
    target_planned_page_id: null,
    target_generated_page_id: 71,
    parent_navigation_item_id: null,
    position: 0,
    slug: "contact",
    label: "Contact",
  }];
  const incompleteNavigationAudit = auditPerformanceLocalV5Composition(incompleteNavigation);
  assert.equal(incompleteNavigationAudit.layoutReady, false);
  assert.ok(incompleteNavigationAudit.blockers.some(
    (item) => item.code === "navigation_resolved_tree_invalid",
  ));
  assert.ok(incompleteNavigationAudit.blockers.some(
    (item) => item.code === "resolved_destination_identity_incomplete",
  ));
});

test("Home service projection is exact, deterministic, featured for one service, and grid-based for many", () => {
  const featuredFixture = pageFixture("home", 69);
  const featured = auditPerformanceLocalV5Composition(featuredFixture);
  assert.equal(featured.layoutReady, true, JSON.stringify(featured.blockers));
  assert.equal(featured.homeServicePresentation.status, "ready");
  assert.equal(featured.homeServicePresentation.mode, "featured");
  assert.deepEqual(featured.homeServicePresentation.services.map((service) => ({
    sourceItemIndex: service.sourceItemIndex,
    title: service.title,
    description: service.description,
    matchedLinkIndex: service.matchedLinkIndex,
  })), [{
    sourceItemIndex: 0,
    title: "Exact governed service",
    description: "Exact source-backed service description.",
    matchedLinkIndex: 0,
  }]);
  assert.deepEqual(featured.homeServicePresentation.remainingLinkIndices, [1]);
  assert.deepEqual(featured.destinationConsumption.map((entry) => ({
    sourceInstanceKey: entry.sourceInstanceKey,
    originalLinkIndex: entry.originalLinkIndex,
    presentationSlot: entry.presentationSlot,
    label: entry.label,
  })), [
    {
      sourceInstanceKey: "related_page_links",
      originalLinkIndex: 0,
      presentationSlot: "featured_service",
      label: "Exact governed service",
    },
    {
      sourceInstanceKey: "related_page_links",
      originalLinkIndex: 1,
      presentationSlot: "related_destination",
      label: "Contact the business",
    },
  ]);
  assert.deepEqual(featured.unconsumedDestinationEntryKeys, []);
  assert.deepEqual(featured.duplicatedDestinationEntryKeys, []);

  const multipleFixture = pageFixture("home", 79);
  const source = multipleFixture.composition.effective_components.find(
    (item) => item.instance_key === "content_section:primary_services",
  )!;
  source.resolved_data.body = [
    "- Exact governed service: Exact source-backed service description.",
    "- Second governed service: Second exact source-backed description.",
  ].join("\n");
  const linksComponent = multipleFixture.composition.effective_components.find(
    (item) => item.instance_key === "related_page_links",
  )!;
  const existingLinks = linksComponent.resolved_data.links as Array<Record<string, unknown>>;
  const secondTarget = {
    planned_page_id: 399_991,
    generated_page_id: 499_991,
    website_id: 1,
    site_plan_id: 1,
    intended_slug: "second-governed-service",
  };
  linksComponent.resolved_data.links = [
    existingLinks[0],
    {
      label: "Second governed service",
      purpose: "Second exact governed route purpose.",
      slug: secondTarget.intended_slug,
      target_generated_page_id: secondTarget.generated_page_id,
      target_planned_page_id: secondTarget.planned_page_id,
    },
    existingLinks[1],
  ];
  const snapshotTargets = multipleFixture.composition.source_snapshot.draft_related_targets as Array<Record<string, unknown>>;
  snapshotTargets.splice(1, 0, secondTarget);
  linksComponent.input_bindings.draft_related_page_ids = snapshotTargets.map(
    (target) => target.planned_page_id,
  );
  const multiple = auditPerformanceLocalV5Composition(multipleFixture);
  assert.equal(multiple.layoutReady, true, JSON.stringify(multiple.blockers));
  assert.equal(multiple.homeServicePresentation.mode, "grid");
  assert.deepEqual(multiple.homeServicePresentation.services.map((service) => service.matchedLinkIndex), [0, 1]);
  assert.deepEqual(multiple.homeServicePresentation.remainingLinkIndices, [2]);
  assert.deepEqual(multiple.destinationConsumption.map((entry) => entry.originalLinkIndex), [0, 1, 2]);

  const mismatched = cloneFixture(featuredFixture);
  const mismatchedLinks = mismatched.composition.effective_components.find(
    (item) => item.instance_key === "related_page_links",
  )!;
  (mismatchedLinks.resolved_data.links as Array<Record<string, unknown>>)[0].label = "Different governed label";
  const mismatchAudit = auditPerformanceLocalV5Composition(mismatched);
  assert.equal(mismatchAudit.layoutReady, false);
  assert.equal(mismatchAudit.homeServicePresentation.status, "blocked");
  assert.ok(mismatchAudit.blockers.some((item) => item.code === "home_service_destination_match_invalid"));
  assert.ok(mismatchAudit.unconsumedDestinationEntryKeys.length > 0);
});

test("County related-city merge proves the exact governed prefix and fails closed on every drift shape", () => {
  const syntheticCountyShapes = new Map([
    [501, 1],
    [502, 2],
    [503, 3],
    [504, 4],
    [505, 5],
  ]);
  for (const [generatedPageId, expectedCityCount] of syntheticCountyShapes) {
    const fixture = pageFixture("county", generatedPageId);
    const audit = auditPerformanceLocalV5Composition(fixture);
    assert.equal(audit.layoutReady, true, JSON.stringify(audit.blockers));
    assert.equal(audit.countyCityPresentation.status, "ready");
    assert.equal(audit.countyCityPresentation.validatedCityPrefixCount, expectedCityCount);
    assert.equal(audit.countyCityPresentation.cityEntries.length, expectedCityCount);
    assert.deepEqual(
      audit.countyCityPresentation.cityEntries.map((entry) => entry.originalLinkIndex),
      Array.from({ length: expectedCityCount }, (_, index) => index),
    );
    assert.deepEqual(
      audit.countyCityPresentation.remainingLinkIndices,
      [expectedCityCount, expectedCityCount + 1],
    );
    assert.deepEqual(
      audit.destinationConsumption.map((entry) => entry.originalLinkIndex),
      Array.from({ length: expectedCityCount + 2 }, (_, index) => index),
    );
    assert.deepEqual(audit.unconsumedDestinationEntryKeys, []);
    assert.deepEqual(audit.duplicatedDestinationEntryKeys, []);
    const source = fixture.composition.effective_components.find(
      (item) => item.instance_key === "content_section:related_city_services",
    )!;
    const cards = fixture.composition.effective_components.find(
      (item) => item.component_key === "destination_cards",
    )!;
    const labels = (cards.resolved_data.links as Array<{ label: string }>).map((item) => item.label);
    assert.equal(labels.length, expectedCityCount + 2);
    assert.equal(source.resolved_data.body, labels.slice(0, expectedCityCount).join(", "));
    assert.match(String(source.resolved_data.body), /, Region Alpha/);
  }

  const alternateGovernedRegion = cloneFixture(pageFixture("county", 502));
  const alternateRegionLinks = destinationCards(alternateGovernedRegion).resolved_data.links as Array<Record<string, unknown>>;
  const alternateRegionCityCount = countyDestinationFixture(502).cityNames.length;
  for (let index = 0; index < alternateRegionCityCount; index += 1) {
    alternateRegionLinks[index].label = String(alternateRegionLinks[index].label)
      .replace(/, Region Alpha$/, ", Region Beta");
  }
  relatedCitySource(alternateGovernedRegion).resolved_data.body = alternateRegionLinks
    .slice(0, alternateRegionCityCount)
    .map((link) => link.label)
    .join(", ");
  let audit = auditPerformanceLocalV5Composition(alternateGovernedRegion);
  assert.equal(audit.layoutReady, true, JSON.stringify(audit.blockers));
  assert.equal(audit.countyCityPresentation.status, "ready");
  assert.ok(!audit.blockers.some((item) => item.code === "county_city_destination_region_mismatch"));

  const mixedRegions = cloneFixture(pageFixture("county", 502));
  const mixedRegionLinks = destinationCards(mixedRegions).resolved_data.links as Array<Record<string, unknown>>;
  const mixedRegionCityCount = countyDestinationFixture(502).cityNames.length;
  mixedRegionLinks[1].label = String(mixedRegionLinks[1].label)
    .replace(/, Region Alpha$/, ", Region Beta");
  relatedCitySource(mixedRegions).resolved_data.body = mixedRegionLinks
    .slice(0, mixedRegionCityCount)
    .map((link) => link.label)
    .join(", ");
  audit = auditPerformanceLocalV5Composition(mixedRegions);
  assert.equal(audit.layoutReady, false);
  assert.equal(audit.countyCityPresentation.status, "blocked");
  assert.ok(audit.blockers.some((item) => item.code === "county_city_destination_region_mismatch"));

  const bodyMismatch = cloneFixture(pageFixture("county", 74));
  relatedCitySource(bodyMismatch).resolved_data.body = "Unmatched governed city label";
  audit = auditPerformanceLocalV5Composition(bodyMismatch);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.blockers.some((item) => item.code === "county_related_city_merge_prefix_mismatch"));

  const reordered = cloneFixture(pageFixture("county", 75));
  const reorderedLinks = destinationCards(reordered).resolved_data.links as unknown[];
  [reorderedLinks[0], reorderedLinks[1]] = [reorderedLinks[1], reorderedLinks[0]];
  audit = auditPerformanceLocalV5Composition(reordered);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.blockers.some((item) => item.code === "county_related_city_merge_prefix_mismatch"));

  const oneRemaining = cloneFixture(pageFixture("county", 76));
  const sourceBody = String(relatedCitySource(oneRemaining).resolved_data.body);
  const cityCount = countyDestinationFixture(76).cityLabels.length;
  destinationCards(oneRemaining).resolved_data.links = (
    destinationCards(oneRemaining).resolved_data.links as unknown[]
  ).slice(0, cityCount + 1);
  assert.equal(relatedCitySource(oneRemaining).resolved_data.body, sourceBody);
  audit = auditPerformanceLocalV5Composition(oneRemaining);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.blockers.some(
    (item) => item.code === "county_related_city_merge_insufficient_remaining_destinations",
  ));

  const incompleteDestination = cloneFixture(pageFixture("county", 77));
  const incompleteLinks = destinationCards(incompleteDestination).resolved_data.links as Array<Record<string, unknown>>;
  incompleteLinks[0].target_generated_page_id = null;
  audit = auditPerformanceLocalV5Composition(incompleteDestination);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.blockers.some((item) => item.code === "county_related_city_merge_destinations_invalid"));

  const duplicatedDestination = cloneFixture(pageFixture("county", 77));
  const duplicatedLinks = destinationCards(duplicatedDestination).resolved_data.links as Array<Record<string, unknown>>;
  duplicatedLinks[1].target_generated_page_id = duplicatedLinks[0].target_generated_page_id;
  audit = auditPerformanceLocalV5Composition(duplicatedDestination);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.blockers.some((item) => item.code === "county_related_city_merge_destinations_invalid"));

  const crossWebsiteDestination = cloneFixture(pageFixture("county", 78));
  const crossWebsiteTargets = crossWebsiteDestination.composition.source_snapshot.draft_related_targets as Array<Record<string, unknown>>;
  crossWebsiteTargets[0].website_id = 2;
  audit = auditPerformanceLocalV5Composition(crossWebsiteDestination);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.ownershipMismatches.length > 0 || audit.blockers.some((item) => item.category === "scope"));

  const missingHeading = cloneFixture(pageFixture("county", 78));
  relatedCitySource(missingHeading).resolved_data.heading = "";
  audit = auditPerformanceLocalV5Composition(missingHeading);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.blockers.some((item) => item.code === "county_related_city_merge_source_invalid"));

  const oneSided = cloneFixture(pageFixture("county", 74));
  oneSided.composition.effective_components = oneSided.composition.effective_components.filter(
    (item) => item.component_key !== "destination_cards",
  );
  audit = auditPerformanceLocalV5Composition(oneSided);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.blockers.some((item) => item.code === "county_related_city_merge_component_mismatch"));

  const nonAdjacent = cloneFixture(pageFixture("county", 75));
  const cards = destinationCards(nonAdjacent);
  const faq = nonAdjacent.composition.effective_components.find((item) => item.component_key === "faq")!;
  [cards.position, faq.position] = [faq.position, cards.position];
  audit = auditPerformanceLocalV5Composition(nonAdjacent);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.blockers.some((item) => item.code === "non_adjacent_source_group"));

  const absentOptionalGroup = cloneFixture(pageFixture("county", 78));
  absentOptionalGroup.composition.effective_components = absentOptionalGroup.composition.effective_components.filter(
    (item) => !["content_section:related_city_services", "destination_cards"].includes(item.instance_key),
  );
  audit = auditPerformanceLocalV5Composition(absentOptionalGroup);
  assert.equal(audit.layoutReady, false, JSON.stringify(audit.blockers));
  assert.equal(
    audit.regions.find((item) => item.regionKey === "related_city_discovery")?.missing,
    true,
  );
  assert.ok(audit.missingRequiredRegionKeys.includes("related_city_discovery"));
});

test("composition audit fails closed for source drops, duplicates, scope leaks, and invalid media/grouping", () => {
  const unknown = cloneFixture(pageFixture("home", 69));
  unknown.composition.effective_components.push(component(
    "invented_component",
    "invented_component",
    unknown.composition.effective_components.length,
    {},
    { heading: "Invented heading" },
  ));
  let audit = auditPerformanceLocalV5Composition(unknown);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.unconsumedSourceInstanceKeys.includes("invented_component"));
  assert.ok(audit.blockers.some((item) => item.code === "unconsumed_source_components"));

  const missing = cloneFixture(pageFixture("service", 73));
  missing.composition.effective_components = missing.composition.effective_components.filter(
    (item) => item.component_key !== "service_summary",
  );
  audit = auditPerformanceLocalV5Composition(missing);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.missingRequiredRegionKeys.includes("service_overview"));

  const duplicated = cloneFixture(pageFixture("about", 70));
  duplicated.composition.effective_components.push({
    ...duplicated.composition.effective_components[3],
  });
  audit = auditPerformanceLocalV5Composition(duplicated);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.duplicatedSourceInstanceKeys.includes("hero"));

  const leaked = cloneFixture(pageFixture("contact", 71));
  const pathways = leaked.composition.effective_components.find(
    (item) => item.component_key === "contact_pathways",
  )!;
  pathways.input_bindings.website_id = 999;
  audit = auditPerformanceLocalV5Composition(leaked);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.blockers.some((item) => item.code === "component_website_mismatch"));

  const aliased = cloneFixture(pageFixture("county", 74));
  aliased.page.page_type = "service_county";
  audit = auditPerformanceLocalV5Composition(aliased);
  assert.equal(audit.resolutionStatus, "blocked");
  assert.equal(audit.layoutKey, null);

  const duplicateMedia = cloneFixture(pageFixture("home", 69));
  const media = duplicateMedia.composition.effective_components.find(
    (item) => item.component_key === "media_placement",
  )!;
  duplicateMedia.composition.effective_components.push({
    ...media,
    instance_key: `${media.instance_key}:duplicate`,
    position: 99,
  });
  audit = auditPerformanceLocalV5Composition(duplicateMedia);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.blockers.some((item) => item.code === "duplicate_media_target"));

  const staleMediaBinding = cloneFixture(pageFixture("home", 69));
  const requirements = (staleMediaBinding.composition.source_snapshot.page_media as {
    requirements: Array<Record<string, unknown>>;
  }).requirements;
  requirements[0].target_component_instance_key = "trust_license";
  audit = auditPerformanceLocalV5Composition(staleMediaBinding);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.blockers.some((item) => item.code === "media_requirement_binding_mismatch"));

  const reorderedProcess = cloneFixture(pageFixture(
    "city_service",
    PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.generatedPageId,
  ));
  const process = reorderedProcess.composition.effective_components.find(
    (item) => item.input_bindings.section_key === "process_section",
  )!;
  const prep = reorderedProcess.composition.effective_components.find(
    (item) => item.input_bindings.section_key === "prep_section",
  )!;
  [process.position, prep.position] = [prep.position, process.position];
  audit = auditPerformanceLocalV5Composition(reorderedProcess);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.blockers.some((item) => item.code === "non_adjacent_source_group"));
});

test("conversion evidence requires exact immutable V3 identity and safe five-of-six disabled form", () => {
  const safe = auditPerformanceLocalV5ConversionEvidence(conversionEvidence());
  assert.equal(safe.safePreviewContract, true);
  assert.equal(safe.rendererReady, true);
  assert.deepEqual(safe.blockers.map((item) => item.code), ["form_provider_disabled"]);

  const wrongIdentity = auditPerformanceLocalV5ConversionEvidence({
    ...conversionEvidence(),
    sourceThemeCompatibility: "performance-local@4",
  });
  assert.equal(wrongIdentity.rendererReady, false);
  assert.ok(wrongIdentity.blockers.some((item) => item.code === "governed_conversion_identity_mismatch"));

  const sixthFloZoneField = auditPerformanceLocalV5ConversionEvidence({
    ...conversionEvidence(),
    formFieldCount: 6,
    optionalFormFieldCount: 1,
  });
  assert.equal(sixthFloZoneField.rendererReady, false);
  assert.ok(sixthFloZoneField.blockers.some((item) => item.code === "form_preview_contract_mismatch"));

  const submitting = auditPerformanceLocalV5ConversionEvidence({
    ...conversionEvidence(),
    formState: "production_configured",
    formCanSubmit: true,
    formCollectsData: true,
  });
  assert.equal(submitting.rendererReady, false);
});

test("full-site audit evaluates an exact 65/65/65 bijection and all 1,165 instances", () => {
  const fixture = fullSiteFixture();
  const audit = auditPerformanceLocalV5FullSite(fixture);
  assert.strictEqual(PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION, PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION);
  assert.equal(audit.status, "blocked");
  assert.equal(audit.counts.evaluatedPages, 65);
  assert.equal(audit.counts.sourceComponents, 1_165);
  assert.equal(audit.counts.consumedComponents, 1_165);
  assert.equal(audit.counts.layoutReadyPages, 65);
  assert.equal(audit.counts.mediaReadyPages, 3);
  assert.equal(audit.counts.qaReadyPages, 65);
  assert.equal(audit.counts.formReadyPages, 0);
  assert.equal(audit.counts.activationReadyPages, 0);
  assert.equal(audit.counts.exportReadyPages, 0);
  assert.equal(audit.counts.publicationReadyPages, 0);
  assert.deepEqual(audit.sourceIdentity, {
    websiteId: 1,
    sitePlanId: 1,
    expectedPageCount: 65,
    expectedSourceComponentCount: 1_165,
    themeFamilyKey: "performance-local",
    themeVersion: 5,
    lifecycleStatus: "preview_candidate",
    productionReady: false,
    themeCompatibilityIdentity: "atlas-semantic-composition@1|performance-local@5",
    rendererContract: "performance-local-page-layouts@2",
    diagnosticIdentity: "performance-local-v5-layout-diagnostics@1",
    durableV5Registration: "absent_by_design",
    activeV5Selection: "absent_by_design",
  });
  assert.deepEqual(audit.counts.pageTypeDistribution, {
    home: 1,
    service: 1,
    county: 5,
    city_service: 55,
    about: 1,
    contact: 1,
    faq: 1,
  });
  assert.equal(audit.pages.every((row) => row.layoutReady), true);
  assert.equal(audit.pages.every((row) => row.formContractSafe && !row.formReady), true);
  assert.ok(audit.pages.some((row) => row.layoutReady && !row.mediaReady));
  assert.equal(audit.pages.every((row) => row.truthfulRendererResult === "ready"), true);
  assert.equal(audit.pages.every((row) => row.structuralDemoRendererResult === "ready"), true);
  assert.equal(audit.pages.every((row) => row.unconsumedDestinationEntries.length === 0), true);
  assert.equal(audit.pages.every((row) => row.duplicatedDestinationEntries.length === 0), true);
  const homeRow = audit.pages.find((row) => row.pageType === "home");
  assert.equal(homeRow?.homeServicePresentation?.status, "ready");
  assert.equal(homeRow?.homeServicePresentation?.mode, "featured");
  assert.equal(homeRow?.destinationConsumption.length, 2);
  const countyRows = audit.pages.filter((row) => row.pageType === "county");
  assert.equal(countyRows.length, 5);
  assert.equal(countyRows.every((row) => row.countyCityPresentation?.status === "ready"), true);
  assert.equal(audit.pages.every((row) => !row.publicExportEligibility), true);
  assert.equal(audit.pages.every((row) => !row.activationReady && !row.exportReady && !row.publicationReady), true);
  assert.deepEqual(audit.blockers, []);
  assert.equal(audit.page41Preservation?.preserved, true);
  assert.deepEqual(audit.page41Preservation?.compositionIdentity, {
    generatedPageId: PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.generatedPageId,
    plannedPageId: PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.plannedPageId,
    compositionId: PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.compositionId,
    compositionVersion: PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.compositionVersion,
    compositionSourceHash: PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.compositionSourceHash,
    qaResultId: PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.qaResultId,
    qaResultHash: PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.qaResultHash,
  });
  assert.deepEqual(
    audit.page41Preservation?.governedMediaIdentities,
    PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.governedMedia.map((item) => ({
      assignmentId: item.assignmentId,
      imageMetadataId: item.imageMetadataId,
      mediaRequirementId: item.mediaRequirementId,
      semanticRole: item.semanticRole,
      placementKey: item.placementKey,
      mediaComponentInstanceKey: item.mediaComponentInstanceKey,
      targetComponentKey: item.targetComponentKey,
      targetComponentInstanceKey: item.targetComponentInstanceKey,
      targetRegion: item.targetRegion,
      displayPreset: item.displayPreset,
      placementContractVersion: item.placementContractVersion,
      requirementVersion: item.requirementVersion,
    })),
  );

  const page41Index = fixture.generatedPages.findIndex(
    (page) => page.id === PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.generatedPageId,
  );
  const directPreservation = auditPerformanceLocalV5Page41Preservation({
    page: fixture.generatedPages[page41Index],
    plannedPage: fixture.plannedPages[page41Index],
    composition: fixture.compositions[page41Index],
    mediaWorkspace: fixture.mediaWorkspace,
  });
  assert.equal(directPreservation.preserved, true);
  assert.deepEqual(directPreservation, auditPerformanceLocalV4Page41Preservation({
    page: fixture.generatedPages[page41Index],
    plannedPage: fixture.plannedPages[page41Index],
    composition: fixture.compositions[page41Index],
    mediaWorkspace: fixture.mediaWorkspace,
  }));

  const driftedPage41 = fullSiteFixture();
  const heroMediaExpectation = PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.governedMedia.find(
    (item) => item.semanticRole === "hero",
  );
  assert.ok(heroMediaExpectation);
  const driftedAssignment = driftedPage41.mediaWorkspace.placements.find(
    (placement) => placement.active_assignment?.id === heroMediaExpectation?.assignmentId,
  )?.active_assignment;
  assert.ok(driftedAssignment);
  if (driftedAssignment) driftedAssignment.effective_display_preset = "square";
  const driftedAudit = auditPerformanceLocalV5FullSite(driftedPage41);
  assert.equal(driftedAudit.page41Preservation?.preserved, false);
  assert.equal(driftedAudit.pages.find(
    (item) => item.generatedPageId === PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.generatedPageId,
  )?.mediaReady, false);
  assert.equal(driftedAudit.counts.mediaReadyPages, 2);
  assert.ok(driftedAudit.page41Preservation?.blockers.some(
    (item) => item.code === "page_41_governed_media_identity_drift",
  ));

  const driftedSemanticRole = fullSiteFixture();
  const serviceMediaExpectation = PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.governedMedia.find(
    (item) => item.semanticRole === "service",
  );
  assert.ok(serviceMediaExpectation);
  const page41Composition = driftedSemanticRole.compositions.find(
    (item) => item.id === PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.compositionId,
  );
  const page41ProcessMedia = page41Composition?.effective_components.find(
    (item) => item.input_bindings.page_image_assignment_id === serviceMediaExpectation?.assignmentId,
  );
  assert.ok(page41ProcessMedia);
  if (page41ProcessMedia) page41ProcessMedia.resolved_data.image_role = "process";
  const semanticRoleAudit = auditPerformanceLocalV5FullSite(driftedSemanticRole);
  assert.equal(semanticRoleAudit.page41Preservation?.governedMediaIdentityPreserved, false);
  assert.ok(semanticRoleAudit.page41Preservation?.blockers.some(
    (item) => item.code === "page_41_governed_media_identity_drift",
  ));

  const driftedContentIdentity = fullSiteFixture();
  const driftedComposition = driftedContentIdentity.compositions.find(
    (item) => item.id === PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.compositionId,
  )!;
  const driftedPage = driftedContentIdentity.generatedPages.find(
    (item) => item.id === PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.generatedPageId,
  )!;
  driftedComposition.source_hash = "b".repeat(64);
  if (driftedPage.qa_result) driftedPage.qa_result.composition_source_hash = driftedComposition.source_hash;
  const contentIdentityAudit = auditPerformanceLocalV5FullSite(driftedContentIdentity);
  const driftedPageRow = contentIdentityAudit.pages.find(
    (item) => item.generatedPageId === PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.generatedPageId,
  );
  assert.equal(contentIdentityAudit.page41Preservation?.contentIdentityPreserved, false);
  assert.equal(driftedPageRow?.layoutReady, false);
  assert.equal(driftedPageRow?.qaReady, false);
  assert.deepEqual(PERFORMANCE_LOCAL_V5_CURRENT_SITE_EXPECTATION, {
    pageCount: 65,
    sourceComponentCount: 1_165,
    pageTypeDistribution: {
      home: 1,
      service: 1,
      county: 5,
      city_service: 55,
      about: 1,
      contact: 1,
      faq: 1,
    },
  });
});

test("full-site audit rejects extra, missing, stale, and unjoined Generated/Composition inputs", () => {
  const extraGenerated = fullSiteFixture();
  extraGenerated.generatedPages.push(generatedPage("home", 999));
  let audit = auditPerformanceLocalV5FullSite(extraGenerated);
  assert.ok(audit.blockers.some((item) => item.code === "full_site_generated_page_count_mismatch"));
  assert.ok(audit.blockers.some((item) => item.code === "full_site_inputs_not_bijective"));

  const extraComposition = fullSiteFixture();
  const extra = pageFixture("home", 999);
  extraComposition.compositions.push(extra.composition);
  audit = auditPerformanceLocalV5FullSite(extraComposition);
  assert.ok(audit.blockers.some((item) => item.code === "full_site_composition_count_mismatch"));
  assert.ok(audit.blockers.some((item) => item.code === "full_site_inputs_not_bijective"));

  const missingGenerated = fullSiteFixture();
  missingGenerated.generatedPages.pop();
  audit = auditPerformanceLocalV5FullSite(missingGenerated);
  assert.ok(audit.blockers.some((item) => item.code === "full_site_generated_page_count_mismatch"));
  assert.ok(audit.pages.some((row) => row.blockerList.some((item) => item.code === "full_site_page_join_missing")));

  const missingComposition = fullSiteFixture();
  missingComposition.compositions.pop();
  audit = auditPerformanceLocalV5FullSite(missingComposition);
  assert.ok(audit.blockers.some((item) => item.code === "full_site_composition_count_mismatch"));
  assert.ok(audit.pages.some((row) => row.blockerList.some((item) => item.code === "full_site_page_join_missing")));

  const duplicateGenerated = fullSiteFixture();
  duplicateGenerated.generatedPages[64].id = duplicateGenerated.generatedPages[63].id;
  audit = auditPerformanceLocalV5FullSite(duplicateGenerated);
  assert.ok(audit.blockers.some((item) => item.code === "duplicate_full_site_input_identity"));
  assert.ok(audit.blockers.some((item) => item.code === "full_site_inputs_not_bijective"));

  const duplicateComposition = fullSiteFixture();
  duplicateComposition.compositions[64].id = duplicateComposition.compositions[63].id;
  audit = auditPerformanceLocalV5FullSite(duplicateComposition);
  assert.ok(audit.blockers.some((item) => item.code === "duplicate_full_site_input_identity"));
  assert.ok(audit.blockers.some((item) => item.code === "full_site_composition_not_bijective"));

  const stale = fullSiteFixture();
  stale.compositions[0].status = "stale";
  audit = auditPerformanceLocalV5FullSite(stale);
  assert.ok(audit.blockers.some((item) => item.code === "full_site_composition_not_current"));
  assert.equal(audit.counts.layoutReadyPages, 64);

  const crossWebsite = fullSiteFixture();
  crossWebsite.plannedPages[0].website_id = 2;
  audit = auditPerformanceLocalV5FullSite(crossWebsite);
  assert.ok(audit.blockers.some((item) => item.code === "planned_page_scope_mismatch"));
  assert.equal(
    audit.pages.find((row) => row.plannedPageId === crossWebsite.plannedPages[0].id)?.layoutReady,
    false,
  );

  const crossJoined = fullSiteFixture();
  const firstGeneratedId = crossJoined.plannedPages[0].generated_page_id;
  crossJoined.plannedPages[0].generated_page_id = crossJoined.plannedPages[1].generated_page_id;
  crossJoined.plannedPages[1].generated_page_id = firstGeneratedId;
  audit = auditPerformanceLocalV5FullSite(crossJoined);
  assert.ok(audit.pages.filter((row) => !row.layoutReady).length >= 2);
  assert.ok(audit.pages.some((row) => row.layoutAudit?.ownershipMismatches.length));
});

type MutablePageFixture = {
  page: GeneratedPage;
  plannedPage: PlannedPage;
  composition: PageComposition;
};

function pageFixture(pageType: PerformanceLocalV5PageType, id: number): MutablePageFixture {
  const isPage41 = id === PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.generatedPageId;
  const plannedPageId = isPage41 ? PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.plannedPageId : 1_000 + id;
  const compositionId = isPage41 ? PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.compositionId : 2_000 + id;
  const effectiveComponents = componentsFor(pageType, id);
  const countyDestinations = pageType === "county" ? countyDestinationFixture(id) : null;
  const homeDestinations = pageType === "home" ? homeDestinationFixture(id) : null;
  if (homeDestinations) {
    const source = effectiveComponents.find(
      (item) => item.instance_key === "content_section:primary_services",
    )!;
    source.resolved_data = {
      heading: "Exact governed services",
      body: homeDestinations.sourceBody,
    };
    const links = effectiveComponents.find((item) => item.component_key === "related_page_links")!;
    links.resolved_data = { links: homeDestinations.links };
    links.input_bindings = {
      internal_link_intent_ids: [],
      draft_related_page_ids: homeDestinations.targets.map((target) => target.planned_page_id),
    };
  }
  if (countyDestinations) {
    const citiesServed = effectiveComponents.find(
      (item) => item.instance_key === "content_section:cities_served",
    )!;
    citiesServed.resolved_data = {
      heading: "Cities served",
      body: countyDestinations.cityNames.join(", "),
    };
    const source = effectiveComponents.find(
      (item) => item.instance_key === "content_section:related_city_services",
    )!;
    source.resolved_data = {
      heading: "Related city services",
      body: countyDestinations.cityLabels.join(", "),
    };
    const cards = effectiveComponents.find((item) => item.component_key === "destination_cards")!;
    cards.resolved_data = { links: countyDestinations.links };
    cards.input_bindings = {
      internal_link_intent_ids: [],
      draft_related_page_ids: countyDestinations.targets.map((target) => target.planned_page_id),
    };
  }
  const mediaRequirements = effectiveComponents
    .filter((item) => item.component_key === "media_placement")
    .map((item) => ({
      id: item.input_bindings.media_requirement_id,
      target_component_instance_key: item.input_bindings.target_component_instance_key,
      component_or_section: item.input_bindings.target_component_key,
      contract_version: item.input_bindings.placement_contract_version,
      lifecycle_status: "active",
    }));
  const composition: PageComposition = {
    id: compositionId,
    website_id: 1,
    site_plan_id: 1,
    planned_page_id: plannedPageId,
    generated_page_id: id,
    composition_version: pageType === "county"
      ? 8
      : isPage41
        ? PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.compositionVersion
        : 7,
    generated_components: [],
    operator_decisions: [],
    effective_components: effectiveComponents,
    source_snapshot: {
      website_id: 1,
      site_plan_id: 1,
      site_plan_version: 1,
      planned_page_id: plannedPageId,
      generated_page_id: id,
      navigation_sets: [{ id: 1 }, { id: 2 }, { id: 3 }],
      navigation_items: [],
      internal_links: [],
      draft_related_targets: countyDestinations?.targets ?? homeDestinations?.targets ?? [],
      page_media: {
        requirements: mediaRequirements,
      },
    },
    source_hash: isPage41
      ? PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.compositionSourceHash
      : hash,
    resolved_theme: selectedTheme() as PageComposition["resolved_theme"],
    status: "current",
    validation_errors: [],
    generated_at: "2026-08-17T00:00:00Z",
  };
  const plannedPage = plannedPageRecord(pageType, id, plannedPageId);
  const page = generatedPage(pageType, id);
  page.qa_result = qaResult(page, composition, plannedPage);
  return { page, plannedPage, composition };
}

function homeDestinationFixture(generatedPageId: number) {
  const services = [{
    title: "Exact governed service",
    description: "Exact source-backed service description.",
  }];
  const labels = [services[0].title, "Contact the business"];
  const targets = labels.map((_, index) => ({
    planned_page_id: 300_000 + generatedPageId * 10 + index,
    generated_page_id: 400_000 + generatedPageId * 10 + index,
    website_id: 1,
    site_plan_id: 1,
    intended_slug: `home-${generatedPageId}-destination-${index + 1}`,
  }));
  const links = labels.map((label, index) => ({
    label,
    purpose: `Exact governed home purpose ${index + 1}.`,
    slug: targets[index].intended_slug,
    target_generated_page_id: targets[index].generated_page_id,
    target_planned_page_id: targets[index].planned_page_id,
  }));
  return {
    services,
    sourceBody: services.map((service) => `- ${service.title}: ${service.description}`).join("\n"),
    links,
    targets,
  };
}

function countyDestinationFixture(generatedPageId: number) {
  const syntheticCountyCityCounts = new Map([
    [501, 1],
    [502, 2],
    [503, 3],
    [504, 4],
    [505, 5],
  ]);
  const cityCount = syntheticCountyCityCounts.get(generatedPageId) ?? 3;
  const cityNames = Array.from(
    { length: cityCount },
    (_, index) => `Fixture City ${index + 1}`,
  );
  const cityLabels = cityNames.map((cityName) => `Fixture Service in ${cityName}, Region Alpha`);
  const labels = [
    ...cityLabels,
    "Fixture Service Overview",
    "Fixture Contact Route",
  ];
  const targets = labels.map((_, index) => ({
    planned_page_id: 100_000 + generatedPageId * 100 + index,
    generated_page_id: 200_000 + generatedPageId * 100 + index,
    website_id: 1,
    site_plan_id: 1,
    intended_slug: `county-${generatedPageId}-destination-${index + 1}`,
  }));
  const links = labels.map((label, index) => ({
    label,
    purpose: `Exact governed purpose ${index + 1}.`,
    slug: targets[index].intended_slug,
    target_generated_page_id: targets[index].generated_page_id,
    target_planned_page_id: targets[index].planned_page_id,
  }));
  return { cityNames, cityLabels, labels, links, targets };
}

function componentsFor(pageType: PerformanceLocalV5PageType, generatedPageId: number) {
  const specs: Array<[string, string, Record<string, unknown>?]> = [
    ["website_header", "website_header", { website_id: 1 }],
    ["utility_navigation", "utility_navigation", { navigation_set_id: 2 }],
    ["primary_navigation", "primary_navigation", { navigation_set_id: 1 }],
    ["hero", "hero", { generated_page_id: generatedPageId }],
  ];
  const addMedia = (target: string, requirementOffset: number) => specs.push([
    `media_placement:requirement-${page41MediaIdentity(requirementOffset)?.mediaRequirementId ?? generatedPageId * 10 + requirementOffset}`,
    "media_placement",
    {
      media_requirement_id: page41MediaIdentity(requirementOffset)?.mediaRequirementId ?? generatedPageId * 10 + requirementOffset,
      ...(page41MediaIdentity(requirementOffset)
        ? { page_image_assignment_id: page41MediaIdentity(requirementOffset)?.assignmentId }
        : {}),
      target_component_key: target.split(":")[0],
      target_component_instance_key: target,
      placement_contract_version: 2,
      target_region: "main",
    },
  ]);
  const addTrust = () => specs.push(["trust_license", "trust_license", { website_id: 1 }]);
  const addSection = (key: string, componentKey = "content_section") => specs.push([
    `${componentKey}:${key}`,
    componentKey,
    { generated_page_id: generatedPageId, section_key: key },
  ]);

  if (pageType === "city_service") {
    addMedia("hero", 1);
    addTrust();
    addSection("why_it_matters", "service_summary");
    addMedia("service_summary:why_it_matters", 2);
    addSection("signs_section");
    addMedia("content_section:signs_section", 3);
    addSection("process_section");
    addSection("prep_section");
    addSection("realtor_property_manager_section");
    specs.push(["destination_cards", "destination_cards", { internal_link_intent_ids: [], draft_related_page_ids: [] }]);
    specs.push(["faq", "faq", { generated_page_id: generatedPageId }]);
  } else if (pageType === "home") {
    addMedia("hero", 1);
    addTrust();
    addMedia("trust_license", 3);
    addSection("primary_services");
    addSection("trust");
    addSection("service_area");
    specs.push(["related_page_links", "related_page_links", { internal_link_intent_ids: [], draft_related_page_ids: [] }]);
    addMedia("related_page_links", 2);
  } else if (pageType === "about") {
    addMedia("hero", 1);
    addTrust();
    addMedia("trust_license", 3);
    addSection("company_story");
    addSection("experience");
    addMedia("content_section:experience", 2);
    addSection("mission");
    specs.push(["related_page_links", "related_page_links", { internal_link_intent_ids: [], draft_related_page_ids: [] }]);
  } else if (pageType === "contact") {
    addTrust();
    addSection("ways_to_contact");
    addMedia("content_section:ways_to_contact", 2);
    addSection("hours");
    addSection("service_area");
    addMedia("content_section:service_area", 3);
    specs.push(["related_page_links", "related_page_links", { internal_link_intent_ids: [], draft_related_page_ids: [] }]);
    specs.push(["contact_pathways", "contact_pathways", { website_id: 1 }]);
    addMedia("contact_pathways", 1);
  } else if (pageType === "faq") {
    addMedia("hero", 3);
    addTrust();
    addSection("contact");
    addMedia("content_section:contact", 1);
    specs.push(["related_page_links", "related_page_links", { internal_link_intent_ids: [], draft_related_page_ids: [] }]);
    specs.push(["faq", "faq", { generated_page_id: generatedPageId }]);
    addMedia("faq", 2);
  } else if (pageType === "service") {
    addMedia("hero", 2);
    addTrust();
    addSection("service_overview", "service_summary");
    addMedia("service_summary:service_overview", 3);
    addSection("approved_guidance");
    addMedia("content_section:approved_guidance", 1);
    addSection("service_area");
    specs.push(["destination_cards", "destination_cards", { internal_link_intent_ids: [], draft_related_page_ids: [] }]);
  } else {
    addMedia("hero", 2);
    addTrust();
    addSection("service_county_intro", "service_summary");
    addMedia("service_summary:service_county_intro", 1);
    addSection("cities_served");
    addMedia("content_section:cities_served", 3);
    addSection("how_service_works");
    addSection("customer_expectations");
    addSection("preparation_guidance");
    addSection("trust_and_license");
    addSection("related_city_services");
    specs.push(["destination_cards", "destination_cards", { internal_link_intent_ids: [], draft_related_page_ids: [] }]);
    specs.push(["faq", "faq", { generated_page_id: generatedPageId }]);
  }

  specs.push(["final_cta", "final_cta", { generated_page_id: generatedPageId, website_id: 1 }]);
  specs.push(["footer_navigation", "footer_navigation", { navigation_set_id: 3 }]);
  specs.push(["website_footer", "website_footer", { website_id: 1 }]);
  return specs.map(([instanceKey, componentKey, bindings], position) => component(
    instanceKey,
    componentKey,
    position,
    bindings ?? {},
    componentKey === "media_placement"
      ? mediaResolvedData(generatedPageId, bindings ?? {})
      : sourceData(componentKey, bindings, pageType),
  ));

  function page41MediaIdentity(requirementOffset: number) {
    return generatedPageId === PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.generatedPageId
      ? PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.governedMedia[requirementOffset - 1]
      : undefined;
  }
}

function mediaResolvedData(generatedPageId: number, bindings: Record<string, unknown>) {
  const assignmentId = Number(bindings.page_image_assignment_id);
  const identity = PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.governedMedia.find(
    (candidate) => candidate.assignmentId === assignmentId,
  );
  if (generatedPageId !== PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.generatedPageId || !identity) {
    return { requirement_state: "required" };
  }
  return {
    requirement_state: "required",
    media_requirement_id: identity.mediaRequirementId,
    placement_contract_version: identity.placementContractVersion,
    image_role: identity.semanticRole,
    placement_key: identity.placementKey,
    component_or_section: identity.targetComponentKey,
    target_component_instance_key: identity.targetComponentInstanceKey,
    target_region: identity.targetRegion,
    stored_display_preset: identity.displayPreset,
    effective_display_preset: identity.displayPreset,
    display_preset: identity.displayPreset,
    asset_url: `/media/page-${PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.generatedPageId}-image-${identity.imageMetadataId}.webp`,
    alt_text: `Governed Page ${PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.generatedPageId} image ${identity.imageMetadataId}`,
    media_version: 1,
  };
}

function component(
  instanceKey: string,
  componentKey: string,
  position: number,
  inputBindings: Record<string, unknown>,
  resolvedData: Record<string, unknown>,
): PageComponentInstance {
  return {
    instance_key: instanceKey,
    component_key: componentKey,
    contract_version: 1,
    region: position < 3 ? "header" : componentKey.includes("footer") ? "footer" : "main",
    position,
    variant: componentKey === "media_placement" ? "placeholder" : "default",
    input_bindings: inputBindings,
    resolved_data: resolvedData,
  };
}

function sourceData(
  componentKey: string,
  bindings: Record<string, unknown> | undefined,
  pageType: PerformanceLocalV5PageType,
) {
  if (componentKey.endsWith("navigation")) return { label: componentKey, items: [] };
  if (componentKey === "hero") return { title: "Exact title", intro: "Exact intro", page_type: pageType };
  if (componentKey === "faq") return { items: [{ question: "Exact question?", answer: "Exact answer." }] };
  if (componentKey === "related_page_links" || componentKey === "destination_cards") return { links: [] };
  const sectionKey = typeof bindings?.section_key === "string" ? bindings.section_key : null;
  if (sectionKey === "approved_guidance" || sectionKey === "customer_expectations") {
    const label = sectionKey === "approved_guidance" ? "Guidance" : "Expectation";
    return {
      heading: sectionKey,
      body: Array.from(
        { length: 18 },
        (_, index) => `### ${label} ${index + 1}\nExact source body ${index + 1}.`,
      ).join("\n\n"),
    };
  }
  return {
    heading: sectionKey ?? "Exact source heading",
    body: "Exact source body.",
  };
}

function generatedPage(pageType: string, id: number): GeneratedPage {
  return {
    id,
    business_id: 1,
    website_id: 1,
    service_id: pageType === "home" || pageType === "about" || pageType === "contact" || pageType === "faq" ? null : 1,
    page_type: pageType,
    page_title: `${pageType} ${id}`,
    page_slug: `${pageType}-${id}`,
    generation_status: "generated",
    qa_status: "ready",
    status: "draft",
    created_at: "2026-08-17T00:00:00Z",
    updated_at: "2026-08-17T00:00:00Z",
  };
}

function plannedPageRecord(
  pageType: PerformanceLocalV5PageType,
  generatedPageId: number,
  plannedPageId: number,
): PlannedPage {
  return {
    id: plannedPageId,
    website_id: 1,
    site_plan_id: 1,
    page_type: pageType,
    working_name: `${pageType} ${generatedPageId}`,
    intended_slug: `${pageType}-${generatedPageId}`,
    planning_status: "planned",
    generated_page_id: generatedPageId,
    draft_readiness: {
      status: "ready",
      page_type_supported: true,
      required_information: [],
      blocking_reasons: [],
      recommendations: [],
    },
    planning_record: {
      id: 3_000 + generatedPageId,
      planned_page_id: plannedPageId,
      generated_answers: {},
      operator_overrides: {},
      effective_answers: {},
      source_snapshot: {},
      confidence_score: 1,
      confidence_level: "high",
      missing_information: [],
      improvement_recommendations: [],
      generated_at: "2026-08-17T00:00:00Z",
      updated_at: "2026-08-17T00:00:00Z",
    },
    created_at: "2026-08-17T00:00:00Z",
    updated_at: "2026-08-17T00:00:00Z",
  };
}

function qaResult(page: GeneratedPage, composition: PageComposition, plannedPage: PlannedPage) {
  const isPage41 = page.id === PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.generatedPageId;
  return {
    qa_result_id: isPage41 ? PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.qaResultId : 4_000 + page.id,
    page_id: page.id,
    website_id: 1,
    site_plan_id: 1,
    planned_page_id: plannedPage.id,
    latest_generated_page_revision_id: null,
    content_hash: hash,
    source_hash: hash,
    page_composition_id: composition.id,
    composition_version: composition.composition_version,
    composition_source_hash: composition.source_hash,
    qa_algorithm_key: "fixture",
    qa_algorithm_version: "1",
    qa_ruleset_key: "fixture",
    qa_ruleset_version: "1",
    qa_ruleset_hash: hash,
    readiness_status: "ready" as const,
    checked_at: "2026-08-17T00:00:00Z",
    passed_count: isPage41 ? PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.qaPassedCount : 1,
    warning_count: isPage41 ? PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.qaWarningCount : 0,
    failed_count: isPage41 ? PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.qaFailedCount : 0,
    checks: [],
    result_hash: isPage41 ? PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.qaResultHash : hash,
    lifecycle_status: "current" as const,
    currentness_status: "current_exact_identity_match",
    currentness_reasons: [],
    persisted: true,
  };
}

function selectedTheme() {
  return {
    mode: "selected",
    website_id: 1,
    theme_id: 1,
    theme_key: "fixture",
    theme_name: "Fixture",
    theme_version: 1,
    token_contract_version: 1,
    tokens: {},
    token_hash_sha256: hash,
    selection_id: 1,
    selection_version: 1,
    source_identity: {},
  };
}

function conversionEvidence(): PerformanceLocalV5ConversionAuditEvidence {
  return {
    sourceThemeCompatibility: "performance-local@3",
    sourceRendererContract: "performance-local-delivery@1",
    bannerState: "disabled",
    bannerPhraseCount: 0,
    formState: "provider_disabled",
    formFieldCount: 5,
    optionalFormFieldCount: 0,
    maximumFormFieldCount: 6,
    formCanSubmit: false,
    formCollectsData: false,
    stickyActionState: "configured",
  };
}

function fullSiteFixture() {
  const types: PerformanceLocalV5PageType[] = [
    ...Array.from({ length: 55 }, () => "city_service" as const),
    ...Array.from({ length: 5 }, () => "county" as const),
    "home",
    "service",
    "about",
    "contact",
    "faq",
  ];
  const fixtures = types.map((pageType, index) => pageFixture(pageType, index + 1));
  const mediaWorkspace = {
    website_id: 1,
    business_id: 1,
    site_plan_id: 1,
    site_plan_version: 1,
    planning_record: null,
    summary: {
      planned_pages: 65,
      pages_with_current_plan: 65,
      pages_without_plan: 0,
      suggested_placements: 195,
      required_placements: 189,
      advisory_placements: 6,
      excluded_placements: 0,
      deferred_placements: 0,
      approved_assignments: 3,
      missing_required_media: 62,
      incomplete_governance: 0,
      incompatible_assignments: 0,
      stale_compositions: 0,
      pages_media_ready: 3,
      page_type_coverage: {},
    },
    placements: fixtures.flatMap((fixture, index) => {
      const isPage41 = fixture.page.id === PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.generatedPageId;
      const ready = isPage41 || fixture.page.page_type === "contact" || fixture.page.page_type === "faq";
      const mediaComponents = fixture.composition.effective_components.filter(
        (component) => component.component_key === "media_placement",
      );
      return [0, 1, 2].map((placementIndex) => {
        const identity = isPage41
          ? PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.governedMedia[placementIndex]
          : null;
        const component = mediaComponents[placementIndex];
        const requirementId = identity?.mediaRequirementId ?? index * 3 + placementIndex + 1;
        return {
          placement_id: requirementId,
          planned_page: {
            id: fixture.plannedPage.id,
            website_id: 1,
            site_plan_id: 1,
            page_type: fixture.plannedPage.page_type,
            working_name: fixture.plannedPage.working_name,
            intended_slug: fixture.plannedPage.intended_slug,
            generated_page_id: fixture.page.id,
          },
          suggestion: {},
          effective_requirement: identity ? {
            id: identity.mediaRequirementId,
            website_id: 1,
            business_id: 1,
            site_plan_id: 1,
            planned_page_id: PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.plannedPageId,
            component_or_section: component.input_bindings.target_component_key,
            target_component_instance_key: component.input_bindings.target_component_instance_key,
            placement_key: identity.placementKey,
            contract_version: identity.placementContractVersion,
            version: identity.requirementVersion,
            effective_display_preset: identity.displayPreset,
            lifecycle_status: "active",
          } : { id: requirementId },
          requirement_history: [],
          active_assignment: identity ? {
            id: identity.assignmentId,
            generated_page_id: PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.generatedPageId,
            image_metadata_id: identity.imageMetadataId,
            website_id: 1,
            site_plan_id: 1,
            planned_page_id: PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.plannedPageId,
            media_requirement_id: identity.mediaRequirementId,
            assignment_version: 1,
            media_version: 1,
            placement_contract_version: identity.placementContractVersion,
            image_role: identity.semanticRole,
            sort_order: placementIndex,
            override_alt_text: null,
            display_preset: identity.displayPreset,
            effective_display_preset: identity.displayPreset,
            status: "active",
          } : ready ? {} : null,
          legacy_assignments: [],
          compatible_asset_ids: identity ? [identity.imageMetadataId] : [],
          blocking_reasons: ready ? [] : ["Required media placement has no approved assignment."],
          composition_status: "current",
          readiness: ready ? "ready" : "awaiting_assignment",
        };
      });
    }),
    assets: PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.governedMedia.map((identity) => ({
      id: identity.imageMetadataId,
      business_id: 1,
      website_id: 1,
      media_version: 1,
      reviewed_alt_text: `Governed Page ${PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.generatedPageId} image ${identity.imageMetadataId}`,
      optimized_url: `/media/page-${PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.generatedPageId}-image-${identity.imageMetadataId}.webp`,
      asset_url: `/media/page-${PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.generatedPageId}-image-${identity.imageMetadataId}.png`,
    })),
    diagnostics: [],
    ready: false,
    evaluated_at: "2026-08-17T00:00:00Z",
  } as unknown as PageMediaPlanningWorkspace;
  return {
    websiteId: 1,
    sitePlanId: 1,
    plannedPages: fixtures.map((item) => item.plannedPage),
    generatedPages: fixtures.map((item) => item.page),
    compositions: fixtures.map((item) => item.composition),
    mediaWorkspace,
    conversionEvidence: conversionEvidence(),
    expectedPageCount: 65 as const,
  };
}

function relatedCitySource(fixture: MutablePageFixture): PageComponentInstance {
  return fixture.composition.effective_components.find(
    (item) => item.instance_key === "content_section:related_city_services",
  )!;
}

function destinationCards(fixture: MutablePageFixture): PageComponentInstance {
  return fixture.composition.effective_components.find(
    (item) => item.component_key === "destination_cards",
  )!;
}

function cloneFixture<T>(value: T): T {
  return structuredClone(value);
}
