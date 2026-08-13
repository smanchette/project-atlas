import {
  PERFORMANCE_LOCAL_THEME,
  PERFORMANCE_LOCAL_THEME_VERSION,
} from "./performanceLocalTheme";

export type PerformanceLocalActivationInputKey =
  | "human_visual_approval"
  | "durable_theme_family_representation"
  | "website_scoped_production_tokens"
  | "active_theme_selection"
  | "production_renderer_integration"
  | "export_integration"
  | "wordpress_adapter"
  | "form_provider"
  | "privacy_and_consent"
  | "campaign_configuration"
  | "review_configuration"
  | "statistics_configuration"
  | "video_configuration"
  | "map_configuration"
  | "language_routing"
  | "publication_authorization"
  | "deployment_authorization";

export type PerformanceLocalActivationReadinessInput = Readonly<{
  previewImplementationPresent?: boolean;
  observedThemeFamilyVersion?: number | null;
}>;

export type PerformanceLocalActivationReadinessItem = Readonly<{
  key: PerformanceLocalActivationInputKey;
  label: string;
  status: "incomplete";
  reason: string;
}>;

export type PerformanceLocalActivationReadinessResult = Readonly<{
  themeKey: typeof PERFORMANCE_LOCAL_THEME.key;
  themeFamilyVersion: typeof PERFORMANCE_LOCAL_THEME_VERSION;
  lifecycle: "preview_candidate";
  productionReady: false;
  previewImplementationPresent: boolean;
  observedThemeFamilyVersion: number | null;
  status: "blocked";
  canActivate: false;
  canPublish: false;
  canDeploy: false;
  mutatesAtlas: false;
  incompleteCount: number;
  items: readonly PerformanceLocalActivationReadinessItem[];
}>;

const ACTIVATION_INPUT_DEFINITIONS = Object.freeze([
  ["human_visual_approval", "Human visual approval", "A local preview does not constitute operator visual approval."],
  ["durable_theme_family_representation", "Durable Theme-family representation", "The source-defined preview candidate is not a durable approved Theme-family record."],
  ["website_scoped_production_tokens", "Website-scoped production tokens", "Preview token resolution does not establish approved production tokens."],
  ["active_theme_selection", "Active Theme selection", "Performance Local is not selected as an active Website Theme."],
  ["production_renderer_integration", "Production renderer integration", "The isolated preview renderer is not a production renderer integration."],
  ["export_integration", "Export integration", "No approved export adapter exists for this Theme family."],
  ["wordpress_adapter", "WordPress adapter", "No WordPress rendering or publication adapter is authorized."],
  ["form_provider", "Form provider", "No production form provider or submission destination is configured."],
  ["privacy_and_consent", "Privacy and consent", "Production privacy, retention, and consent controls are not approved."],
  ["campaign_configuration", "Campaign configuration", "No durable, approved, time-bounded campaign configuration is present."],
  ["review_configuration", "Review configuration", "No verified review provider evidence and approval are present."],
  ["statistics_configuration", "Statistics configuration", "No sourced, effective-dated statistics approval is present."],
  ["video_configuration", "Video configuration", "No governed video identity, provider, privacy mode, and approval are present."],
  ["map_configuration", "Map configuration", "No approved location or service-area provider configuration is present."],
  ["language_routing", "Language routing", "No translated content, routes, canonical, or hreflang approval is present."],
  ["publication_authorization", "Publication authorization", "No publication authorization is present."],
  ["deployment_authorization", "Deployment authorization", "No deployment authorization is present."],
] satisfies readonly (readonly [PerformanceLocalActivationInputKey, string, string])[]);

export const PERFORMANCE_LOCAL_ACTIVATION_INPUTS = Object.freeze(
  ACTIVATION_INPUT_DEFINITIONS.map(([key, label, reason]) => Object.freeze({
    key,
    label,
    status: "incomplete" as const,
    reason,
  })),
);

/**
 * Returns diagnostic evidence only. Inputs may describe the local preview, but
 * cannot complete, activate, publish, deploy, or persist any production gate.
 */
export function performanceLocalActivationReadiness(
  input: PerformanceLocalActivationReadinessInput = {},
): PerformanceLocalActivationReadinessResult {
  return Object.freeze({
    themeKey: PERFORMANCE_LOCAL_THEME.key,
    themeFamilyVersion: PERFORMANCE_LOCAL_THEME_VERSION,
    lifecycle: "preview_candidate" as const,
    productionReady: false as const,
    previewImplementationPresent: input.previewImplementationPresent === true,
    observedThemeFamilyVersion: Number.isSafeInteger(input.observedThemeFamilyVersion)
      ? input.observedThemeFamilyVersion ?? null
      : null,
    status: "blocked" as const,
    canActivate: false as const,
    canPublish: false as const,
    canDeploy: false as const,
    mutatesAtlas: false as const,
    incompleteCount: PERFORMANCE_LOCAL_ACTIVATION_INPUTS.length,
    items: PERFORMANCE_LOCAL_ACTIVATION_INPUTS,
  });
}
