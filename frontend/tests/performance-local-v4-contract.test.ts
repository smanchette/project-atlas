import assert from "node:assert/strict";
import test from "node:test";

import {
  auditPerformanceLocalV4ConversionEvidence,
  auditPerformanceLocalV4FullSite,
  auditPerformanceLocalV4Page41Preservation,
  PERFORMANCE_LOCAL_V4_CURRENT_SITE_EXPECTATION,
  PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION,
  type PerformanceLocalV4ConversionAuditEvidence,
} from "../src/components/performanceLocalV4Audit";
import {
  auditPerformanceLocalV4Composition,
  PERFORMANCE_LOCAL_V4_LAYOUT_MANIFESTS,
  resolvePerformanceLocalV4Layout,
  type PerformanceLocalV4PageType,
} from "../src/components/performanceLocalV4LayoutContract";
import {
  PERFORMANCE_LOCAL_V4_DEMO_MEDIA_LABEL,
  PERFORMANCE_LOCAL_V4_FORM_FIELD_CONTRACT,
  PERFORMANCE_LOCAL_V4_PREVIEW_LABEL,
  PERFORMANCE_LOCAL_V4_SERIALIZED_COMPONENT_CONTRACTS,
  PERFORMANCE_LOCAL_V4_THEME,
} from "../src/components/performanceLocalThemeV4";
import {
  PERFORMANCE_LOCAL_SERIALIZED_COMPONENT_CONTRACTS,
  PERFORMANCE_LOCAL_THEME,
} from "../src/components/performanceLocalTheme";
import {
  PERFORMANCE_LOCAL_V3_SERIALIZED_COMPONENT_CONTRACTS,
  PERFORMANCE_LOCAL_V3_THEME,
} from "../src/components/performanceLocalThemeV3";
import type {
  GeneratedPage,
  PageComponentInstance,
  PageComposition,
  PageMediaPlanningWorkspace,
  PlannedPage,
} from "../src/types";

const hash = "a".repeat(64);
const pageTypes: readonly PerformanceLocalV4PageType[] = Object.freeze([
  "home",
  "service",
  "county",
  "city_service",
  "about",
  "contact",
  "faq",
]);

test("V4 is a distinct frozen source-only preview candidate without mutating V2 or V3", () => {
  const v2Before = JSON.stringify(PERFORMANCE_LOCAL_SERIALIZED_COMPONENT_CONTRACTS);
  const v3Before = JSON.stringify(PERFORMANCE_LOCAL_V3_SERIALIZED_COMPONENT_CONTRACTS);

  assert.equal(PERFORMANCE_LOCAL_THEME.version, 2);
  assert.equal(PERFORMANCE_LOCAL_V3_THEME.version, 3);
  assert.equal(PERFORMANCE_LOCAL_V4_THEME.key, "performance-local");
  assert.equal(PERFORMANCE_LOCAL_V4_THEME.version, 4);
  assert.equal(PERFORMANCE_LOCAL_V4_THEME.status, "preview_candidate");
  assert.equal(PERFORMANCE_LOCAL_V4_THEME.productionReady, false);
  assert.equal(PERFORMANCE_LOCAL_V4_THEME.sourceOnly, true);
  assert.equal(PERFORMANCE_LOCAL_V4_THEME.durableRegistration, "absent_by_design");
  assert.equal(PERFORMANCE_LOCAL_V4_THEME.activeSelection, "absent_by_design");
  assert.equal(PERFORMANCE_LOCAL_V4_THEME.activationReady, false);
  assert.equal(PERFORMANCE_LOCAL_V4_THEME.publicExportEligible, false);
  assert.equal(PERFORMANCE_LOCAL_V4_THEME.compatibilityIdentity, "atlas-semantic-composition@1|performance-local@4");
  assert.equal(PERFORMANCE_LOCAL_V4_THEME.rendererContract, "performance-local-page-layouts@1");
  assert.equal(PERFORMANCE_LOCAL_V4_PREVIEW_LABEL, "PERFORMANCE LOCAL V4 — DRAFT PREVIEW — NOT ACTIVE");
  assert.equal(PERFORMANCE_LOCAL_V4_DEMO_MEDIA_LABEL, "DEMO MEDIA SLOT — NOT SITE CONTENT");
  assert.deepEqual(PERFORMANCE_LOCAL_V4_FORM_FIELD_CONTRACT, {
    defaultCustomerEntryFieldCount: 5,
    maximumCustomerEntryFieldCount: 6,
    activeOptionalFieldCount: 0,
    seventhFieldBehavior: "reject",
  });
  assert.equal(PERFORMANCE_LOCAL_V4_SERIALIZED_COMPONENT_CONTRACTS.length, 23);
  assert.ok(PERFORMANCE_LOCAL_V4_SERIALIZED_COMPONENT_CONTRACTS.every((item) =>
    item.contract_version === 4 && item.theme_compatibility[0] === "performance-local@4",
  ));
  assert.deepEqual(
    PERFORMANCE_LOCAL_V4_SERIALIZED_COMPONENT_CONTRACTS.map((item) => item.component_key),
    PERFORMANCE_LOCAL_V3_SERIALIZED_COMPONENT_CONTRACTS.map((item) => item.component_key),
  );
  assert.equal(JSON.stringify(PERFORMANCE_LOCAL_SERIALIZED_COMPONENT_CONTRACTS), v2Before);
  assert.equal(JSON.stringify(PERFORMANCE_LOCAL_V3_SERIALIZED_COMPONENT_CONTRACTS), v3Before);
  assert.ok(Object.isFrozen(PERFORMANCE_LOCAL_V4_THEME));
  assert.ok(Object.isFrozen(PERFORMANCE_LOCAL_V4_SERIALIZED_COMPONENT_CONTRACTS));
});

test("the exact seven-type resolver is deterministic and rejects aliases, unknowns, and prototype keys", () => {
  const expectedKeys = {
    home: "performance-local-v4-home",
    service: "performance-local-v4-service",
    county: "performance-local-v4-service-county",
    city_service: "performance-local-v4-city-service",
    about: "performance-local-v4-about",
    contact: "performance-local-v4-contact",
    faq: "performance-local-v4-faq",
  } as const;
  assert.deepEqual(Object.keys(PERFORMANCE_LOCAL_V4_LAYOUT_MANIFESTS), pageTypes);
  for (const pageType of pageTypes) {
    const first = resolvePerformanceLocalV4Layout(pageType);
    const second = resolvePerformanceLocalV4Layout(pageType);
    assert.equal(first.status, "resolved");
    assert.equal(second.status, "resolved");
    if (first.status !== "resolved" || second.status !== "resolved") continue;
    assert.strictEqual(first.manifest, second.manifest);
    assert.equal(first.manifest.supportedPageType, pageType);
    assert.equal(first.manifest.layoutKey, expectedKeys[pageType]);
    assert.equal(first.manifest.layoutVersion, 1);
    assert.equal(first.manifest.missingInputBehavior.genericFallback, "forbidden");
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
    const resolution = resolvePerformanceLocalV4Layout(raw);
    assert.equal(resolution.status, "blocked", String(raw));
    if (resolution.status === "blocked") assert.ok(resolution.blockers.length > 0);
  }
  const county = resolvePerformanceLocalV4Layout("county");
  assert.equal(county.status, "resolved");
  if (county.status === "resolved") {
    assert.equal(county.manifest.displayName, "Service-County");
    assert.equal(county.manifest.supportedPageType, "county");
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
    const audit = auditPerformanceLocalV4Composition(fixture);
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

  const contact = auditPerformanceLocalV4Composition(pageFixture("contact", 71));
  assert.deepEqual(contact.regions.map((item) => item.regionKey), [
    "site_header",
    "hero",
    "immediate_contact",
    "final_conversion",
    "contact_expectations",
    "service_area_discovery",
    "related_discovery",
    "site_footer",
  ]);
  const city = auditPerformanceLocalV4Composition(pageFixture("city_service", 41));
  assert.deepEqual(
    city.regions.flatMap((item) => item.sourceInstanceKeys),
    city.consumption.map((item) => item.instanceKey),
  );
  const groupedRegions = city.regions.filter((item) => item.presentationGroups.length > 0);
  assert.deepEqual(groupedRegions.map((item) => item.regionKey), ["process"]);
  assert.deepEqual(groupedRegions[0]?.presentationGroups, [{
    groupKey: "performance-local-v4-city-service:process",
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
        groupKey: "performance-local-v4-city-service:process",
      },
      {
        instanceKey: "content_section:prep_section",
        mode: "adjacent_group",
        groupKey: "performance-local-v4-city-service:process",
      },
      {
        instanceKey: "content_section:realtor_property_manager_section",
        mode: "adjacent_group",
        groupKey: "performance-local-v4-city-service:process",
      },
    ],
  );
  const county = auditPerformanceLocalV4Composition(pageFixture("county", 74));
  const countyGroup = county.regions.find(
    (item) => item.regionKey === "related_city_discovery",
  )?.presentationGroups;
  assert.deepEqual(countyGroup, [{
    groupKey: "performance-local-v4-service-county:related_city_discovery",
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
        groupKey: "performance-local-v4-service-county:related_city_discovery",
      },
      {
        instanceKey: "destination_cards",
        mode: "adjacent_group",
        groupKey: "performance-local-v4-service-county:related_city_discovery",
      },
    ],
  );
  for (const pageType of pageTypes.filter(
    (candidate) => candidate !== "city_service" && candidate !== "county",
  )) {
    const representative = auditPerformanceLocalV4Composition(pageFixture(pageType, 100 + pageTypes.indexOf(pageType)));
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
  primaryNavigation.resolved_data.items = [{ ...resolvedContactTarget, label: "Contact" }];
  utilityNavigation.resolved_data.items = [{ ...resolvedContactTarget, label: "Contact us" }];
  const overlapAudit = auditPerformanceLocalV4Composition(overlappingHeaderNavigation);
  assert.equal(overlapAudit.layoutReady, true);
  assert.deepEqual(
    overlapAudit.consumption
      .filter((item) => item.mode === "nested_navigation")
      .map((item) => item.instanceKey),
    ["utility_navigation", "primary_navigation", "footer_navigation"],
  );

  primaryNavigation.resolved_data.items = [
    { ...resolvedContactTarget, label: "Contact" },
    { ...resolvedContactTarget, label: "Duplicate contact" },
  ];
  const duplicateWithinSetAudit = auditPerformanceLocalV4Composition(overlappingHeaderNavigation);
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
    target_planned_page_id: governedSelfTarget.planned_page_id,
    target_generated_page_id: governedSelfTarget.generated_page_id,
    slug: governedSelfTarget.intended_slug,
    label: "Home",
  }];
  const selfNavigationAudit = auditPerformanceLocalV4Composition(governedSelfNavigation);
  assert.equal(selfNavigationAudit.layoutReady, true);
  assert.ok(!selfNavigationAudit.blockers.some(
    (item) => item.code === "resolved_destination_scope_mismatch",
  ));
});

test("County related-city merge proves the exact governed prefix and fails closed on every drift shape", () => {
  const actualCityCounts = new Map([
    [74, 13],
    [75, 7],
    [76, 16],
    [77, 14],
    [78, 5],
  ]);
  for (const [generatedPageId, expectedCityCount] of actualCityCounts) {
    const fixture = pageFixture("county", generatedPageId);
    const audit = auditPerformanceLocalV4Composition(fixture);
    assert.equal(audit.layoutReady, true, JSON.stringify(audit.blockers));
    const source = fixture.composition.effective_components.find(
      (item) => item.instance_key === "content_section:related_city_services",
    )!;
    const cards = fixture.composition.effective_components.find(
      (item) => item.component_key === "destination_cards",
    )!;
    const labels = (cards.resolved_data.links as Array<{ label: string }>).map((item) => item.label);
    assert.equal(labels.length, expectedCityCount + 2);
    assert.equal(source.resolved_data.body, labels.slice(0, expectedCityCount).join(", "));
    assert.match(String(source.resolved_data.body), /, FL/);
  }

  const bodyMismatch = cloneFixture(pageFixture("county", 74));
  relatedCitySource(bodyMismatch).resolved_data.body = "Unmatched governed city label";
  let audit = auditPerformanceLocalV4Composition(bodyMismatch);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.blockers.some((item) => item.code === "county_related_city_merge_prefix_mismatch"));

  const reordered = cloneFixture(pageFixture("county", 75));
  const reorderedLinks = destinationCards(reordered).resolved_data.links as unknown[];
  [reorderedLinks[0], reorderedLinks[1]] = [reorderedLinks[1], reorderedLinks[0]];
  audit = auditPerformanceLocalV4Composition(reordered);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.blockers.some((item) => item.code === "county_related_city_merge_prefix_mismatch"));

  const oneRemaining = cloneFixture(pageFixture("county", 76));
  const sourceBody = String(relatedCitySource(oneRemaining).resolved_data.body);
  const cityCount = countyDestinationFixture(76).cityLabels.length;
  destinationCards(oneRemaining).resolved_data.links = (
    destinationCards(oneRemaining).resolved_data.links as unknown[]
  ).slice(0, cityCount + 1);
  assert.equal(relatedCitySource(oneRemaining).resolved_data.body, sourceBody);
  audit = auditPerformanceLocalV4Composition(oneRemaining);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.blockers.some(
    (item) => item.code === "county_related_city_merge_insufficient_remaining_destinations",
  ));

  const incompleteDestination = cloneFixture(pageFixture("county", 77));
  const incompleteLinks = destinationCards(incompleteDestination).resolved_data.links as Array<Record<string, unknown>>;
  incompleteLinks[0].target_generated_page_id = null;
  audit = auditPerformanceLocalV4Composition(incompleteDestination);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.blockers.some((item) => item.code === "county_related_city_merge_destinations_invalid"));

  const duplicatedDestination = cloneFixture(pageFixture("county", 77));
  const duplicatedLinks = destinationCards(duplicatedDestination).resolved_data.links as Array<Record<string, unknown>>;
  duplicatedLinks[1].target_generated_page_id = duplicatedLinks[0].target_generated_page_id;
  audit = auditPerformanceLocalV4Composition(duplicatedDestination);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.blockers.some((item) => item.code === "county_related_city_merge_destinations_invalid"));

  const missingHeading = cloneFixture(pageFixture("county", 78));
  relatedCitySource(missingHeading).resolved_data.heading = "";
  audit = auditPerformanceLocalV4Composition(missingHeading);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.blockers.some((item) => item.code === "county_related_city_merge_source_invalid"));

  const oneSided = cloneFixture(pageFixture("county", 74));
  oneSided.composition.effective_components = oneSided.composition.effective_components.filter(
    (item) => item.component_key !== "destination_cards",
  );
  audit = auditPerformanceLocalV4Composition(oneSided);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.blockers.some((item) => item.code === "county_related_city_merge_component_mismatch"));

  const nonAdjacent = cloneFixture(pageFixture("county", 75));
  const cards = destinationCards(nonAdjacent);
  const faq = nonAdjacent.composition.effective_components.find((item) => item.component_key === "faq")!;
  [cards.position, faq.position] = [faq.position, cards.position];
  audit = auditPerformanceLocalV4Composition(nonAdjacent);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.blockers.some((item) => item.code === "non_adjacent_source_group"));

  const absentOptionalGroup = cloneFixture(pageFixture("county", 78));
  absentOptionalGroup.composition.effective_components = absentOptionalGroup.composition.effective_components.filter(
    (item) => !["content_section:related_city_services", "destination_cards"].includes(item.instance_key),
  );
  audit = auditPerformanceLocalV4Composition(absentOptionalGroup);
  assert.equal(audit.layoutReady, true, JSON.stringify(audit.blockers));
  assert.equal(
    audit.regions.find((item) => item.regionKey === "related_city_discovery")?.missing,
    true,
  );
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
  let audit = auditPerformanceLocalV4Composition(unknown);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.unconsumedSourceInstanceKeys.includes("invented_component"));
  assert.ok(audit.blockers.some((item) => item.code === "unconsumed_source_components"));

  const missing = cloneFixture(pageFixture("service", 73));
  missing.composition.effective_components = missing.composition.effective_components.filter(
    (item) => item.component_key !== "service_summary",
  );
  audit = auditPerformanceLocalV4Composition(missing);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.missingRequiredRegionKeys.includes("service_overview"));

  const duplicated = cloneFixture(pageFixture("about", 70));
  duplicated.composition.effective_components.push({
    ...duplicated.composition.effective_components[3],
  });
  audit = auditPerformanceLocalV4Composition(duplicated);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.duplicatedSourceInstanceKeys.includes("hero"));

  const leaked = cloneFixture(pageFixture("contact", 71));
  const pathways = leaked.composition.effective_components.find(
    (item) => item.component_key === "contact_pathways",
  )!;
  pathways.input_bindings.website_id = 999;
  audit = auditPerformanceLocalV4Composition(leaked);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.blockers.some((item) => item.code === "component_website_mismatch"));

  const aliased = cloneFixture(pageFixture("county", 74));
  aliased.page.page_type = "service_county";
  audit = auditPerformanceLocalV4Composition(aliased);
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
  audit = auditPerformanceLocalV4Composition(duplicateMedia);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.blockers.some((item) => item.code === "duplicate_media_target"));

  const staleMediaBinding = cloneFixture(pageFixture("home", 69));
  const requirements = (staleMediaBinding.composition.source_snapshot.page_media as {
    requirements: Array<Record<string, unknown>>;
  }).requirements;
  requirements[0].target_component_instance_key = "trust_license";
  audit = auditPerformanceLocalV4Composition(staleMediaBinding);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.blockers.some((item) => item.code === "media_requirement_binding_mismatch"));

  const reorderedProcess = cloneFixture(pageFixture("city_service", 41));
  const process = reorderedProcess.composition.effective_components.find(
    (item) => item.input_bindings.section_key === "process_section",
  )!;
  const prep = reorderedProcess.composition.effective_components.find(
    (item) => item.input_bindings.section_key === "prep_section",
  )!;
  [process.position, prep.position] = [prep.position, process.position];
  audit = auditPerformanceLocalV4Composition(reorderedProcess);
  assert.equal(audit.layoutReady, false);
  assert.ok(audit.blockers.some((item) => item.code === "non_adjacent_source_group"));
});

test("conversion evidence requires exact immutable V3 identity and safe five-of-six disabled form", () => {
  const safe = auditPerformanceLocalV4ConversionEvidence(conversionEvidence());
  assert.equal(safe.safePreviewContract, true);
  assert.equal(safe.rendererReady, true);
  assert.deepEqual(safe.blockers.map((item) => item.code), ["form_provider_disabled"]);

  const wrongIdentity = auditPerformanceLocalV4ConversionEvidence({
    ...conversionEvidence(),
    sourceThemeCompatibility: "performance-local@4",
  });
  assert.equal(wrongIdentity.rendererReady, false);
  assert.ok(wrongIdentity.blockers.some((item) => item.code === "governed_conversion_identity_mismatch"));

  const sixthFloZoneField = auditPerformanceLocalV4ConversionEvidence({
    ...conversionEvidence(),
    formFieldCount: 6,
    optionalFormFieldCount: 1,
  });
  assert.equal(sixthFloZoneField.rendererReady, false);
  assert.ok(sixthFloZoneField.blockers.some((item) => item.code === "form_preview_contract_mismatch"));

  const submitting = auditPerformanceLocalV4ConversionEvidence({
    ...conversionEvidence(),
    formState: "production_configured",
    formCanSubmit: true,
    formCollectsData: true,
  });
  assert.equal(submitting.rendererReady, false);
});

test("full-site audit evaluates an exact 65/65/65 bijection and all 1,165 instances", () => {
  const fixture = fullSiteFixture();
  const audit = auditPerformanceLocalV4FullSite(fixture);
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
  assert.equal(audit.pages.every((row) => !row.publicExportEligibility), true);
  assert.equal(audit.pages.every((row) => !row.activationReady && !row.exportReady && !row.publicationReady), true);
  assert.deepEqual(audit.blockers, []);
  assert.equal(audit.page41Preservation?.preserved, true);
  assert.deepEqual(audit.page41Preservation?.compositionIdentity, {
    generatedPageId: 41,
    plannedPageId: 41,
    compositionId: 41,
    compositionVersion: 8,
    compositionSourceHash: PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION.compositionSourceHash,
    qaResultId: 80,
    qaResultHash: PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION.qaResultHash,
  });
  assert.deepEqual(
    audit.page41Preservation?.governedMediaIdentities,
    PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION.governedMedia.map((item) => ({
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

  const page41Index = fixture.generatedPages.findIndex((page) => page.id === 41);
  const directPreservation = auditPerformanceLocalV4Page41Preservation({
    page: fixture.generatedPages[page41Index],
    plannedPage: fixture.plannedPages[page41Index],
    composition: fixture.compositions[page41Index],
    mediaWorkspace: fixture.mediaWorkspace,
  });
  assert.equal(directPreservation.preserved, true);

  const driftedPage41 = fullSiteFixture();
  const driftedAssignment = driftedPage41.mediaWorkspace.placements.find(
    (placement) => placement.active_assignment?.id === 13,
  )?.active_assignment;
  assert.ok(driftedAssignment);
  if (driftedAssignment) driftedAssignment.effective_display_preset = "square";
  const driftedAudit = auditPerformanceLocalV4FullSite(driftedPage41);
  assert.equal(driftedAudit.page41Preservation?.preserved, false);
  assert.equal(driftedAudit.pages.find((item) => item.generatedPageId === 41)?.mediaReady, false);
  assert.equal(driftedAudit.counts.mediaReadyPages, 2);
  assert.ok(driftedAudit.page41Preservation?.blockers.some(
    (item) => item.code === "page_41_governed_media_identity_drift",
  ));

  const driftedSemanticRole = fullSiteFixture();
  const page41Composition = driftedSemanticRole.compositions.find((item) => item.id === 41);
  const page41ProcessMedia = page41Composition?.effective_components.find(
    (item) => item.input_bindings.page_image_assignment_id === 14,
  );
  assert.ok(page41ProcessMedia);
  if (page41ProcessMedia) page41ProcessMedia.resolved_data.image_role = "process";
  const semanticRoleAudit = auditPerformanceLocalV4FullSite(driftedSemanticRole);
  assert.equal(semanticRoleAudit.page41Preservation?.governedMediaIdentityPreserved, false);
  assert.ok(semanticRoleAudit.page41Preservation?.blockers.some(
    (item) => item.code === "page_41_governed_media_identity_drift",
  ));

  const driftedContentIdentity = fullSiteFixture();
  const driftedComposition = driftedContentIdentity.compositions.find((item) => item.id === 41)!;
  const driftedPage = driftedContentIdentity.generatedPages.find((item) => item.id === 41)!;
  driftedComposition.source_hash = "b".repeat(64);
  if (driftedPage.qa_result) driftedPage.qa_result.composition_source_hash = driftedComposition.source_hash;
  const contentIdentityAudit = auditPerformanceLocalV4FullSite(driftedContentIdentity);
  const driftedPageRow = contentIdentityAudit.pages.find((item) => item.generatedPageId === 41);
  assert.equal(contentIdentityAudit.page41Preservation?.contentIdentityPreserved, false);
  assert.equal(driftedPageRow?.layoutReady, false);
  assert.equal(driftedPageRow?.qaReady, false);
  assert.deepEqual(PERFORMANCE_LOCAL_V4_CURRENT_SITE_EXPECTATION, {
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
  let audit = auditPerformanceLocalV4FullSite(extraGenerated);
  assert.ok(audit.blockers.some((item) => item.code === "full_site_generated_page_count_mismatch"));
  assert.ok(audit.blockers.some((item) => item.code === "full_site_inputs_not_bijective"));

  const extraComposition = fullSiteFixture();
  const extra = pageFixture("home", 999);
  extraComposition.compositions.push(extra.composition);
  audit = auditPerformanceLocalV4FullSite(extraComposition);
  assert.ok(audit.blockers.some((item) => item.code === "full_site_composition_count_mismatch"));
  assert.ok(audit.blockers.some((item) => item.code === "full_site_inputs_not_bijective"));

  const missingGenerated = fullSiteFixture();
  missingGenerated.generatedPages.pop();
  audit = auditPerformanceLocalV4FullSite(missingGenerated);
  assert.ok(audit.blockers.some((item) => item.code === "full_site_generated_page_count_mismatch"));
  assert.ok(audit.pages.some((row) => row.blockerList.some((item) => item.code === "full_site_page_join_missing")));

  const missingComposition = fullSiteFixture();
  missingComposition.compositions.pop();
  audit = auditPerformanceLocalV4FullSite(missingComposition);
  assert.ok(audit.blockers.some((item) => item.code === "full_site_composition_count_mismatch"));
  assert.ok(audit.pages.some((row) => row.blockerList.some((item) => item.code === "full_site_page_join_missing")));

  const duplicateGenerated = fullSiteFixture();
  duplicateGenerated.generatedPages[64].id = duplicateGenerated.generatedPages[63].id;
  audit = auditPerformanceLocalV4FullSite(duplicateGenerated);
  assert.ok(audit.blockers.some((item) => item.code === "duplicate_full_site_input_identity"));
  assert.ok(audit.blockers.some((item) => item.code === "full_site_inputs_not_bijective"));

  const duplicateComposition = fullSiteFixture();
  duplicateComposition.compositions[64].id = duplicateComposition.compositions[63].id;
  audit = auditPerformanceLocalV4FullSite(duplicateComposition);
  assert.ok(audit.blockers.some((item) => item.code === "duplicate_full_site_input_identity"));
  assert.ok(audit.blockers.some((item) => item.code === "full_site_composition_not_bijective"));

  const stale = fullSiteFixture();
  stale.compositions[0].status = "stale";
  audit = auditPerformanceLocalV4FullSite(stale);
  assert.ok(audit.blockers.some((item) => item.code === "full_site_composition_not_current"));
  assert.equal(audit.counts.layoutReadyPages, 64);
});

type MutablePageFixture = {
  page: GeneratedPage;
  plannedPage: PlannedPage;
  composition: PageComposition;
};

function pageFixture(pageType: PerformanceLocalV4PageType, id: number): MutablePageFixture {
  const isPage41 = id === PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION.generatedPageId;
  const plannedPageId = isPage41 ? PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION.plannedPageId : 1_000 + id;
  const compositionId = isPage41 ? PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION.compositionId : 2_000 + id;
  const effectiveComponents = componentsFor(pageType, id);
  const countyDestinations = pageType === "county" ? countyDestinationFixture(id) : null;
  if (countyDestinations) {
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
    composition_version: pageType === "county" || (pageType === "city_service" && id === 41) ? 8 : 7,
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
      draft_related_targets: countyDestinations?.targets ?? [],
      page_media: {
        requirements: mediaRequirements,
      },
    },
    source_hash: isPage41
      ? PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION.compositionSourceHash
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

function countyDestinationFixture(generatedPageId: number) {
  const actualCountyCityCounts = new Map([
    [74, 13],
    [75, 7],
    [76, 16],
    [77, 14],
    [78, 5],
  ]);
  const cityCount = actualCountyCityCounts.get(generatedPageId) ?? 3;
  const cityLabels = Array.from(
    { length: cityCount },
    (_, index) => `Drywood Termite Tenting in Fixture City ${index + 1}, FL`,
  );
  const labels = [
    ...cityLabels,
    "Drywood Termite Tenting Service",
    "Contact the business",
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
  return { cityLabels, labels, links, targets };
}

function componentsFor(pageType: PerformanceLocalV4PageType, generatedPageId: number) {
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
    return generatedPageId === PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION.generatedPageId
      ? PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION.governedMedia[requirementOffset - 1]
      : undefined;
  }
}

function mediaResolvedData(generatedPageId: number, bindings: Record<string, unknown>) {
  const assignmentId = Number(bindings.page_image_assignment_id);
  const identity = PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION.governedMedia.find(
    (candidate) => candidate.assignmentId === assignmentId,
  );
  if (generatedPageId !== PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION.generatedPageId || !identity) {
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
    asset_url: `/media/page-41-image-${identity.imageMetadataId}.webp`,
    alt_text: `Governed Page 41 image ${identity.imageMetadataId}`,
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
  pageType: PerformanceLocalV4PageType,
) {
  if (componentKey.endsWith("navigation")) return { label: componentKey, items: [] };
  if (componentKey === "hero") return { title: "Exact title", intro: "Exact intro", page_type: pageType };
  if (componentKey === "faq") return { items: [{ question: "Exact question?", answer: "Exact answer." }] };
  if (componentKey === "related_page_links" || componentKey === "destination_cards") return { links: [] };
  return {
    heading: typeof bindings?.section_key === "string" ? bindings.section_key : "Exact source heading",
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
  pageType: PerformanceLocalV4PageType,
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
  const isPage41 = page.id === PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION.generatedPageId;
  return {
    qa_result_id: isPage41 ? PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION.qaResultId : 4_000 + page.id,
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
    passed_count: isPage41 ? PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION.qaPassedCount : 1,
    warning_count: isPage41 ? PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION.qaWarningCount : 0,
    failed_count: isPage41 ? PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION.qaFailedCount : 0,
    checks: [],
    result_hash: isPage41 ? PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION.qaResultHash : hash,
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

function conversionEvidence(): PerformanceLocalV4ConversionAuditEvidence {
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
  const types: PerformanceLocalV4PageType[] = [
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
      const isPage41 = fixture.page.id === PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION.generatedPageId;
      const ready = isPage41 || fixture.page.page_type === "contact" || fixture.page.page_type === "faq";
      const mediaComponents = fixture.composition.effective_components.filter(
        (component) => component.component_key === "media_placement",
      );
      return [0, 1, 2].map((placementIndex) => {
        const identity = isPage41
          ? PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION.governedMedia[placementIndex]
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
            planned_page_id: PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION.plannedPageId,
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
            generated_page_id: PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION.generatedPageId,
            image_metadata_id: identity.imageMetadataId,
            website_id: 1,
            site_plan_id: 1,
            planned_page_id: PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION.plannedPageId,
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
    assets: PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION.governedMedia.map((identity) => ({
      id: identity.imageMetadataId,
      business_id: 1,
      website_id: 1,
      media_version: 1,
      reviewed_alt_text: `Governed Page 41 image ${identity.imageMetadataId}`,
      optimized_url: `/media/page-41-image-${identity.imageMetadataId}.webp`,
      asset_url: `/media/page-41-image-${identity.imageMetadataId}.png`,
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
