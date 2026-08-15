import {
  PERFORMANCE_LOCAL_SERIALIZED_COMPONENT_CONTRACTS,
  type PerformanceLocalComponentKey,
  type PerformanceLocalVisibility,
  type SerializedThemeFamilyComponentContract,
} from "./performanceLocalTheme";

export const PERFORMANCE_LOCAL_V3_THEME_VERSION = 3 as const;
export const PERFORMANCE_LOCAL_V3_THEME_COMPATIBILITY = "performance-local@3" as const;
export const PERFORMANCE_LOCAL_V3_RENDERER_CONTRACT = "performance-local-delivery@1" as const;

export type SerializedPerformanceLocalV3ComponentContract = Readonly<{
  component_key: PerformanceLocalComponentKey;
  contract_version: typeof PERFORMANCE_LOCAL_V3_THEME_VERSION;
  optional: boolean;
  default_enabled: boolean;
  scope: "website_with_optional_page_override";
  supports_page_override: true;
  placement: string;
  variant: string;
  responsive_visibility: PerformanceLocalVisibility;
  theme_compatibility: readonly [typeof PERFORMANCE_LOCAL_V3_THEME_COMPATIBILITY];
  content_source: SerializedThemeFamilyComponentContract["content_source"];
  required_configuration: readonly string[];
  supports_cta_label: true;
  supports_cta_destination: true;
  accessibility_label_required: boolean;
  diagnostic_label: string;
}>;

const V3_COMPONENT_OVERRIDES = Object.freeze({
  campaign_banner: Object.freeze({
    variant: "single_action_safe_strip",
    required_configuration: Object.freeze([
      "enabled",
      "website_id",
      "theme_compatibility",
      "placement",
      "variant",
      "responsive_visibility",
      "content_source",
      "accessibility_label",
      "intent",
      "message",
      "cta_label",
      "cta_destination",
      "approval_identity",
    ]),
    diagnostic_label: "Approved evergreen or time-bounded single-action conversion banner",
  }),
  compact_estimate_form: Object.freeze({
    variant: "provider_independent_gateway",
    required_configuration: Object.freeze([
      "enabled",
      "website_id",
      "theme_compatibility",
      "placement",
      "variant",
      "responsive_visibility",
      "content_source",
      "accessibility_label",
      "submission_state",
      "fields",
      "provider",
      "privacy",
      "retention",
      "spam",
      "success_behavior",
      "failure_behavior",
      "security",
      "audit_identity",
    ]),
    diagnostic_label: "Provider-independent governed estimate form gateway",
  }),
});

function v3Contract(
  contract: SerializedThemeFamilyComponentContract,
): SerializedPerformanceLocalV3ComponentContract {
  const override = V3_COMPONENT_OVERRIDES[
    contract.component_key as keyof typeof V3_COMPONENT_OVERRIDES
  ];
  return Object.freeze({
    ...contract,
    contract_version: PERFORMANCE_LOCAL_V3_THEME_VERSION,
    variant: override?.variant ?? contract.variant,
    theme_compatibility: Object.freeze([
      PERFORMANCE_LOCAL_V3_THEME_COMPATIBILITY,
    ]) as readonly [typeof PERFORMANCE_LOCAL_V3_THEME_COMPATIBILITY],
    required_configuration: Object.freeze([
      ...(override?.required_configuration ?? contract.required_configuration),
    ]),
    diagnostic_label: override?.diagnostic_label ?? contract.diagnostic_label,
    responsive_visibility: Object.freeze({ ...contract.responsive_visibility }),
  });
}

/**
 * Source-defined V3 is deliberately separate from the pinned V2 contract.
 * Mapping the unchanged capabilities makes parity review explicit while the
 * two V3 delivery changes remain narrow and independently testable.
 */
export const PERFORMANCE_LOCAL_V3_SERIALIZED_COMPONENT_CONTRACTS = Object.freeze(
  PERFORMANCE_LOCAL_SERIALIZED_COMPONENT_CONTRACTS.map(v3Contract),
);

export const PERFORMANCE_LOCAL_V3_THEME = Object.freeze({
  key: "performance-local" as const,
  displayName: "Performance Local" as const,
  version: PERFORMANCE_LOCAL_V3_THEME_VERSION,
  status: "preview_candidate" as const,
  productionReady: false as const,
  websiteIndependent: true as const,
  compatibilityIdentity:
    `atlas-semantic-composition@1|${PERFORMANCE_LOCAL_V3_THEME_COMPATIBILITY}` as const,
  rendererContract: PERFORMANCE_LOCAL_V3_RENDERER_CONTRACT,
  supportedComponents: PERFORMANCE_LOCAL_V3_SERIALIZED_COMPONENT_CONTRACTS,
});

export function performanceLocalV3ComponentContract(
  key: PerformanceLocalComponentKey | string,
): SerializedPerformanceLocalV3ComponentContract | undefined {
  return PERFORMANCE_LOCAL_V3_SERIALIZED_COMPONENT_CONTRACTS.find(
    (contract) => contract.component_key === key,
  );
}
