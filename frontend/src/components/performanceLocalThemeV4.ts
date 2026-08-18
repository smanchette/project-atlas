import {
  PERFORMANCE_LOCAL_THEME,
  type PerformanceLocalComponentKey,
  type PerformanceLocalVisibility,
  type SerializedThemeFamilyComponentContract,
} from "./performanceLocalTheme";
import {
  PERFORMANCE_LOCAL_V3_RENDERER_CONTRACT,
  PERFORMANCE_LOCAL_V3_SERIALIZED_COMPONENT_CONTRACTS,
  PERFORMANCE_LOCAL_V3_THEME_COMPATIBILITY,
} from "./performanceLocalThemeV3";

export const PERFORMANCE_LOCAL_V4_THEME_VERSION = 4 as const;
export const PERFORMANCE_LOCAL_V4_THEME_COMPATIBILITY = "performance-local@4" as const;
export const PERFORMANCE_LOCAL_V4_RENDERER_CONTRACT =
  "performance-local-page-layouts@1" as const;
export const PERFORMANCE_LOCAL_V4_DIAGNOSTIC_IDENTITY =
  "performance-local-v4-layout-diagnostics@1" as const;
export const PERFORMANCE_LOCAL_V4_COMPATIBILITY_IDENTITY =
  `atlas-semantic-composition@1|${PERFORMANCE_LOCAL_V4_THEME_COMPATIBILITY}` as const;
export const PERFORMANCE_LOCAL_V4_PREVIEW_LABEL =
  "PERFORMANCE LOCAL V4 — DRAFT PREVIEW — NOT ACTIVE" as const;
export const PERFORMANCE_LOCAL_V4_DEMO_MEDIA_LABEL =
  "DEMO MEDIA SLOT — NOT SITE CONTENT" as const;

export const PERFORMANCE_LOCAL_V4_FORM_FIELD_CONTRACT = Object.freeze({
  defaultCustomerEntryFieldCount: 5 as const,
  maximumCustomerEntryFieldCount: 6 as const,
  activeOptionalFieldCount: 0 as const,
  seventhFieldBehavior: "reject" as const,
});

export type SerializedPerformanceLocalV4ComponentContract = Readonly<{
  component_key: PerformanceLocalComponentKey;
  contract_version: typeof PERFORMANCE_LOCAL_V4_THEME_VERSION;
  optional: boolean;
  default_enabled: boolean;
  scope: "website_with_optional_page_override";
  supports_page_override: true;
  placement: string;
  variant: string;
  responsive_visibility: PerformanceLocalVisibility;
  theme_compatibility: readonly [typeof PERFORMANCE_LOCAL_V4_THEME_COMPATIBILITY];
  content_source: SerializedThemeFamilyComponentContract["content_source"];
  required_configuration: readonly string[];
  supports_cta_label: true;
  supports_cta_destination: true;
  accessibility_label_required: boolean;
  diagnostic_label: string;
}>;

function v4Contract(
  contract: (typeof PERFORMANCE_LOCAL_V3_SERIALIZED_COMPONENT_CONTRACTS)[number],
): SerializedPerformanceLocalV4ComponentContract {
  return Object.freeze({
    ...contract,
    contract_version: PERFORMANCE_LOCAL_V4_THEME_VERSION,
    responsive_visibility: Object.freeze({ ...contract.responsive_visibility }),
    theme_compatibility: Object.freeze([
      PERFORMANCE_LOCAL_V4_THEME_COMPATIBILITY,
    ]) as readonly [typeof PERFORMANCE_LOCAL_V4_THEME_COMPATIBILITY],
    required_configuration: Object.freeze([...contract.required_configuration]),
  });
}

/**
 * V4 keeps the governed V3 conversion capabilities, but owns a distinct,
 * source-only contract identity. Durable V3 component rows remain V3 input;
 * this map neither mutates them nor represents a durable V4 registration.
 */
export const PERFORMANCE_LOCAL_V4_SERIALIZED_COMPONENT_CONTRACTS = Object.freeze(
  PERFORMANCE_LOCAL_V3_SERIALIZED_COMPONENT_CONTRACTS.map(v4Contract),
);

export const PERFORMANCE_LOCAL_V4_THEME = Object.freeze({
  key: "performance-local" as const,
  displayName: "Performance Local" as const,
  version: PERFORMANCE_LOCAL_V4_THEME_VERSION,
  status: "preview_candidate" as const,
  productionReady: false as const,
  websiteIndependent: true as const,
  sourceOnly: true as const,
  durableRegistration: "absent_by_design" as const,
  activeSelection: "absent_by_design" as const,
  activationReady: false as const,
  publicExportEligible: false as const,
  compatibilityIdentity: PERFORMANCE_LOCAL_V4_COMPATIBILITY_IDENTITY,
  diagnosticIdentity: PERFORMANCE_LOCAL_V4_DIAGNOSTIC_IDENTITY,
  rendererContract: PERFORMANCE_LOCAL_V4_RENDERER_CONTRACT,
  designContract: PERFORMANCE_LOCAL_THEME.designContract,
  supportedComponents: PERFORMANCE_LOCAL_V4_SERIALIZED_COMPONENT_CONTRACTS,
  governedConversionInput: Object.freeze({
    themeCompatibility: PERFORMANCE_LOCAL_V3_THEME_COMPATIBILITY,
    rendererContract: PERFORMANCE_LOCAL_V3_RENDERER_CONTRACT,
    identityTreatment: "preserve_as_v3_input" as const,
    mutation: "forbidden" as const,
  }),
  formFieldContract: PERFORMANCE_LOCAL_V4_FORM_FIELD_CONTRACT,
  previewMetadata: Object.freeze({
    localOnly: true as const,
    operatorOnly: true as const,
    persistsSelection: false as const,
    persistsControls: false as const,
    mutatesSource: false as const,
    externalRequests: false as const,
    previewLabel: PERFORMANCE_LOCAL_V4_PREVIEW_LABEL,
    structuralDemoMediaLabel: PERFORMANCE_LOCAL_V4_DEMO_MEDIA_LABEL,
  }),
});

export function performanceLocalV4ComponentContract(
  key: PerformanceLocalComponentKey | string,
): SerializedPerformanceLocalV4ComponentContract | undefined {
  return PERFORMANCE_LOCAL_V4_SERIALIZED_COMPONENT_CONTRACTS.find(
    (contract) => contract.component_key === key,
  );
}
