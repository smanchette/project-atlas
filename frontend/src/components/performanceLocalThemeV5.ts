import {
  PERFORMANCE_LOCAL_THEME,
  type PerformanceLocalComponentKey,
  type PerformanceLocalVisibility,
  type SerializedThemeFamilyComponentContract,
} from "./performanceLocalTheme";
import {
  PERFORMANCE_LOCAL_V3_RENDERER_CONTRACT,
  PERFORMANCE_LOCAL_V3_THEME_COMPATIBILITY,
} from "./performanceLocalThemeV3";
import {
  PERFORMANCE_LOCAL_V4_RENDERER_CONTRACT,
  PERFORMANCE_LOCAL_V4_SERIALIZED_COMPONENT_CONTRACTS,
  PERFORMANCE_LOCAL_V4_THEME_COMPATIBILITY,
  type SerializedPerformanceLocalV4ComponentContract,
} from "./performanceLocalThemeV4";

export const PERFORMANCE_LOCAL_V5_THEME_VERSION = 5 as const;
export const PERFORMANCE_LOCAL_V5_THEME_COMPATIBILITY = "performance-local@5" as const;
export const PERFORMANCE_LOCAL_V5_RENDERER_CONTRACT =
  "performance-local-page-layouts@2" as const;
export const PERFORMANCE_LOCAL_V5_DIAGNOSTIC_IDENTITY =
  "performance-local-v5-layout-diagnostics@1" as const;
export const PERFORMANCE_LOCAL_V5_COMPATIBILITY_IDENTITY =
  `atlas-semantic-composition@1|${PERFORMANCE_LOCAL_V5_THEME_COMPATIBILITY}` as const;
export const PERFORMANCE_LOCAL_V5_PREVIEW_LABEL =
  "PERFORMANCE LOCAL V5 — DRAFT PREVIEW — NOT ACTIVE" as const;
export const PERFORMANCE_LOCAL_V5_DEMO_MEDIA_LABEL =
  "DEMO MEDIA SLOT — NOT SITE CONTENT" as const;

export const PERFORMANCE_LOCAL_V5_FORM_FIELD_CONTRACT = Object.freeze({
  defaultCustomerEntryFieldCount: 5 as const,
  maximumCustomerEntryFieldCount: 6 as const,
  activeOptionalFieldCount: 0 as const,
  seventhFieldBehavior: "reject" as const,
});

export type SerializedPerformanceLocalV5ComponentContract = Readonly<{
  component_key: PerformanceLocalComponentKey;
  contract_version: typeof PERFORMANCE_LOCAL_V5_THEME_VERSION;
  optional: boolean;
  default_enabled: boolean;
  scope: "website_with_optional_page_override";
  supports_page_override: true;
  placement: string;
  variant: string;
  responsive_visibility: PerformanceLocalVisibility;
  theme_compatibility: readonly [typeof PERFORMANCE_LOCAL_V5_THEME_COMPATIBILITY];
  content_source: SerializedThemeFamilyComponentContract["content_source"];
  required_configuration: readonly string[];
  supports_cta_label: true;
  supports_cta_destination: true;
  accessibility_label_required: boolean;
  diagnostic_label: string;
}>;

function v5Contract(
  contract: SerializedPerformanceLocalV4ComponentContract,
): SerializedPerformanceLocalV5ComponentContract {
  return Object.freeze({
    ...contract,
    contract_version: PERFORMANCE_LOCAL_V5_THEME_VERSION,
    responsive_visibility: Object.freeze({ ...contract.responsive_visibility }),
    theme_compatibility: Object.freeze([
      PERFORMANCE_LOCAL_V5_THEME_COMPATIBILITY,
    ]) as readonly [typeof PERFORMANCE_LOCAL_V5_THEME_COMPATIBILITY],
    required_configuration: Object.freeze([...contract.required_configuration]),
  });
}

/**
 * V5 advances only the source-defined visual-layout contract. The immutable V4
 * capability set is copied into a new frozen identity; no V4 object is mutated
 * or presented as a durable V5 registration.
 */
export const PERFORMANCE_LOCAL_V5_SERIALIZED_COMPONENT_CONTRACTS = Object.freeze(
  PERFORMANCE_LOCAL_V4_SERIALIZED_COMPONENT_CONTRACTS.map(v5Contract),
);

export const PERFORMANCE_LOCAL_V5_THEME = Object.freeze({
  key: "performance-local" as const,
  displayName: "Performance Local" as const,
  version: PERFORMANCE_LOCAL_V5_THEME_VERSION,
  status: "preview_candidate" as const,
  productionReady: false as const,
  websiteIndependent: true as const,
  sourceOnly: true as const,
  durableRegistration: "absent_by_design" as const,
  activeSelection: "absent_by_design" as const,
  activationReady: false as const,
  publicExportEligible: false as const,
  compatibilityIdentity: PERFORMANCE_LOCAL_V5_COMPATIBILITY_IDENTITY,
  diagnosticIdentity: PERFORMANCE_LOCAL_V5_DIAGNOSTIC_IDENTITY,
  rendererContract: PERFORMANCE_LOCAL_V5_RENDERER_CONTRACT,
  designContract: PERFORMANCE_LOCAL_THEME.designContract,
  supportedComponents: PERFORMANCE_LOCAL_V5_SERIALIZED_COMPONENT_CONTRACTS,
  immutablePredecessor: Object.freeze({
    themeCompatibility: PERFORMANCE_LOCAL_V4_THEME_COMPATIBILITY,
    rendererContract: PERFORMANCE_LOCAL_V4_RENDERER_CONTRACT,
    identityTreatment: "preserve_as_immutable_v4_source" as const,
    mutation: "forbidden" as const,
  }),
  governedConversionInput: Object.freeze({
    themeCompatibility: PERFORMANCE_LOCAL_V3_THEME_COMPATIBILITY,
    rendererContract: PERFORMANCE_LOCAL_V3_RENDERER_CONTRACT,
    identityTreatment: "preserve_as_v3_input" as const,
    mutation: "forbidden" as const,
  }),
  formFieldContract: PERFORMANCE_LOCAL_V5_FORM_FIELD_CONTRACT,
  previewMetadata: Object.freeze({
    localOnly: true as const,
    operatorOnly: true as const,
    persistsSelection: false as const,
    persistsControls: false as const,
    mutatesSource: false as const,
    externalRequests: false as const,
    previewLabel: PERFORMANCE_LOCAL_V5_PREVIEW_LABEL,
    structuralDemoMediaLabel: PERFORMANCE_LOCAL_V5_DEMO_MEDIA_LABEL,
  }),
});

export function performanceLocalV5ComponentContract(
  key: PerformanceLocalComponentKey | string,
): SerializedPerformanceLocalV5ComponentContract | undefined {
  return PERFORMANCE_LOCAL_V5_SERIALIZED_COMPONENT_CONTRACTS.find(
    (contract) => contract.component_key === key,
  );
}
