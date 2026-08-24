export type PerformanceLocalV5FormIdentity = Readonly<{
  componentConfigurationId: number;
  componentInstanceKey: string;
  destination: string;
}>;

export type PerformanceLocalV5EstimatePageConfiguration =
  | Readonly<{
      enabled: false;
    }>
  | Readonly<{
      enabled: true;
      formIdentity: PerformanceLocalV5FormIdentity;
      heading: "Request an Estimate";
      introduction: string;
      phoneAlternativeEnabled: boolean;
      route: string;
    }>;

export type PerformanceLocalV5SpecialPageConfiguration =
  | Readonly<{
      enabled: false;
    }>
  | Readonly<{
      callActionEnabled: true;
      description: string;
      eligibleServiceReferences?: readonly string[];
      enabled: true;
      estimateActionEnabled: boolean;
      expiresAt?: string | null;
      headline: string;
      route: string;
      terms?: string | null;
    }>;

export type PerformanceLocalV5StickyActionConfiguration =
  | Readonly<{
      mode: "disabled";
    }>
  | Readonly<{
      accessibilityLabel?: string;
      destination: string;
      mode: "estimate" | "service_promotion" | "special";
      publicLabel: string;
    }>;

export type PerformanceLocalV5ActionConfiguration = Readonly<{
  authorizedServicePromotionDestinations: readonly string[];
  estimate: PerformanceLocalV5EstimatePageConfiguration;
  special: PerformanceLocalV5SpecialPageConfiguration;
  sticky: PerformanceLocalV5StickyActionConfiguration;
}>;

export type PerformanceLocalV5TopAction =
  | Readonly<{
      accessibilityLabel?: string;
      destination: string;
      label: string;
      mode: "estimate" | "service_promotion" | "special";
    }>
  | Readonly<{
      mode: "disabled";
    }>;

export type PerformanceLocalV5ActionResolutionReason =
  | "configured_action"
  | "disabled"
  | "estimate_fallback"
  | "expired_without_fallback"
  | "invalid_configuration"
  | "self_link_hidden"
  | "self_link_switched_to_estimate"
  | "self_link_switched_to_special";

export type PerformanceLocalV5ActionResolution = Readonly<{
  action: PerformanceLocalV5TopAction;
  reason: PerformanceLocalV5ActionResolutionReason;
}>;

export type PerformanceLocalV5ActionSurface = "estimate" | "site" | "special";

type SpecialState = "active" | "disabled" | "expired" | "invalid";

const DISABLED_ACTION = Object.freeze({ mode: "disabled" as const });
const CONTROL_CHARACTER = /[\u0000-\u001f\u007f]/;
const STRICT_ISO_INSTANT = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,9})?(Z|[+-]\d{2}:\d{2})$/;

export function resolvePerformanceLocalV5TopAction(input: Readonly<{
  configuration: PerformanceLocalV5ActionConfiguration;
  currentRoute: string;
  currentSurface: PerformanceLocalV5ActionSurface;
  evaluatedAt: Date;
  exactFormIdentity: PerformanceLocalV5FormIdentity;
}>): PerformanceLocalV5ActionResolution {
  const { configuration } = input;
  if (!validDate(input.evaluatedAt) || !safeInternalPageRoute(input.currentRoute)) {
    return disabled("invalid_configuration");
  }

  const estimateValid = performanceLocalV5EstimatePageIsRenderable(configuration.estimate, input.exactFormIdentity);
  const specialState = performanceLocalV5SpecialPageState(configuration.special, input.evaluatedAt);
  if (
    configuration.estimate.enabled &&
    configuration.special.enabled &&
    configuration.estimate.route === configuration.special.route
  ) return disabled("invalid_configuration");
  let resolution: PerformanceLocalV5ActionResolution;

  switch (configuration.sticky.mode) {
    case "disabled":
      resolution = disabled("disabled");
      break;
    case "estimate":
      resolution = resolveEstimate(configuration, input.exactFormIdentity, estimateValid);
      break;
    case "special":
      resolution = resolveSpecial(configuration, input.exactFormIdentity, estimateValid, specialState);
      break;
    case "service_promotion":
      resolution = resolveServicePromotion(configuration);
      break;
  }

  if (resolution.action.mode === "disabled" || resolution.action.destination !== input.currentRoute) {
    return resolution;
  }

  if (input.currentSurface === "special") {
    if (estimateValid && configuration.estimate.enabled) {
      return {
        action: estimatePageAction(configuration.estimate),
        reason: "self_link_switched_to_estimate",
      };
    }
    return disabled("self_link_hidden");
  }

  if (input.currentSurface === "estimate") {
    if (specialState === "active" && configuration.special.enabled) {
      return {
        action: {
          destination: configuration.special.route,
          label: configuration.special.headline,
          mode: "special",
        },
        reason: "self_link_switched_to_special",
      };
    }
    return disabled("self_link_hidden");
  }

  return disabled("self_link_hidden");
}

export function performanceLocalV5EstimatePageIsRenderable(
  configuration: PerformanceLocalV5EstimatePageConfiguration,
  exactFormIdentity: PerformanceLocalV5FormIdentity,
): configuration is Extract<PerformanceLocalV5EstimatePageConfiguration, { enabled: true }> {
  if (!configuration.enabled) return false;
  return configuration.heading === "Request an Estimate" &&
    exactPublicText(configuration.introduction) &&
    safeInternalPageRoute(configuration.route) &&
    exactFormIdentity.componentConfigurationId > 0 &&
    exactPublicText(exactFormIdentity.componentInstanceKey) &&
    safeExactFormAnchor(exactFormIdentity.destination) &&
    configuration.formIdentity.componentConfigurationId === exactFormIdentity.componentConfigurationId &&
    configuration.formIdentity.componentInstanceKey === exactFormIdentity.componentInstanceKey &&
    configuration.formIdentity.destination === exactFormIdentity.destination;
}

export function performanceLocalV5SpecialPageState(
  configuration: PerformanceLocalV5SpecialPageConfiguration,
  evaluatedAt: Date,
): SpecialState {
  if (!configuration.enabled) return "disabled";
  if (
    !validDate(evaluatedAt) ||
    !safeInternalPageRoute(configuration.route) ||
    !exactPublicText(configuration.headline) ||
    !exactPublicText(configuration.description) ||
    !configuration.callActionEnabled ||
    !optionalPublicText(configuration.terms) ||
    !optionalServiceReferences(configuration.eligibleServiceReferences)
  ) return "invalid";
  if (configuration.expiresAt === undefined || configuration.expiresAt === null) return "active";
  const expiresAt = strictInstant(configuration.expiresAt);
  if (expiresAt === null) return "invalid";
  return evaluatedAt.getTime() >= expiresAt ? "expired" : "active";
}

export function safePerformanceLocalV5InternalPageRoute(value: string): boolean {
  return safeInternalPageRoute(value);
}

function resolveEstimate(
  configuration: PerformanceLocalV5ActionConfiguration,
  exactFormIdentity: PerformanceLocalV5FormIdentity,
  estimateValid: boolean,
): PerformanceLocalV5ActionResolution {
  const sticky = configuration.sticky;
  if (sticky.mode !== "estimate" || !estimateValid || !configuration.estimate.enabled) {
    return disabled("invalid_configuration");
  }
  if (
    sticky.publicLabel !== configuration.estimate.heading ||
    !optionalAccessibilityLabel(sticky.accessibilityLabel) ||
    (sticky.destination !== configuration.estimate.route && sticky.destination !== exactFormIdentity.destination)
  ) return disabled("invalid_configuration");
  return {
    action: {
      accessibilityLabel: sticky.accessibilityLabel,
      destination: sticky.destination,
      label: sticky.publicLabel,
      mode: "estimate",
    },
    reason: "configured_action",
  };
}

function resolveSpecial(
  configuration: PerformanceLocalV5ActionConfiguration,
  exactFormIdentity: PerformanceLocalV5FormIdentity,
  estimateValid: boolean,
  specialState: SpecialState,
): PerformanceLocalV5ActionResolution {
  const sticky = configuration.sticky;
  if (sticky.mode !== "special") return disabled("invalid_configuration");
  if (
    !configuration.special.enabled ||
    !exactPublicText(sticky.publicLabel) ||
    !optionalAccessibilityLabel(sticky.accessibilityLabel) ||
    sticky.destination !== configuration.special.route
  ) return disabled("invalid_configuration");
  if (specialState === "invalid" || specialState === "disabled") return disabled("invalid_configuration");
  if (specialState === "expired") {
    if (estimateValid && configuration.estimate.enabled) {
      return { action: estimatePageAction(configuration.estimate), reason: "estimate_fallback" };
    }
    return disabled("expired_without_fallback");
  }
  return {
    action: {
      accessibilityLabel: sticky.accessibilityLabel,
      destination: sticky.destination,
      label: sticky.publicLabel,
      mode: "special",
    },
    reason: "configured_action",
  };
}

function resolveServicePromotion(
  configuration: PerformanceLocalV5ActionConfiguration,
): PerformanceLocalV5ActionResolution {
  const sticky = configuration.sticky;
  if (
    sticky.mode !== "service_promotion" ||
    !exactPublicText(sticky.publicLabel) ||
    !optionalAccessibilityLabel(sticky.accessibilityLabel) ||
    !safeInternalPageRoute(sticky.destination) ||
    !configuration.authorizedServicePromotionDestinations.every(safeInternalPageRoute) ||
    !configuration.authorizedServicePromotionDestinations.includes(sticky.destination)
  ) return disabled("invalid_configuration");
  return {
    action: {
      accessibilityLabel: sticky.accessibilityLabel,
      destination: sticky.destination,
      label: sticky.publicLabel,
      mode: "service_promotion",
    },
    reason: "configured_action",
  };
}

function estimatePageAction(
  configuration: Extract<PerformanceLocalV5EstimatePageConfiguration, { enabled: true }>,
): PerformanceLocalV5TopAction {
  return {
    destination: configuration.route,
    label: configuration.heading,
    mode: "estimate",
  };
}

function disabled(reason: PerformanceLocalV5ActionResolutionReason): PerformanceLocalV5ActionResolution {
  return { action: DISABLED_ACTION, reason };
}

function exactPublicText(value: string): boolean {
  return value.length > 0 && value === value.trim() && !CONTROL_CHARACTER.test(value);
}

function optionalAccessibilityLabel(value: string | undefined): boolean {
  return value === undefined || exactPublicText(value);
}

function optionalPublicText(value: string | null | undefined): boolean {
  return value === undefined || value === null || exactPublicText(value);
}

function optionalServiceReferences(value: readonly string[] | undefined): boolean {
  return value === undefined || value.every(exactPublicText);
}

function safeInternalPageRoute(value: string): boolean {
  if (!exactPublicText(value) || !value.startsWith("/") || value.startsWith("//")) return false;
  if (value.includes("\\") || value.includes("?") || value.includes("#") || value.includes("%")) return false;
  if (value.split("/").some((segment) => segment === "." || segment === "..")) return false;
  try {
    const parsed = new URL(value, "https://atlas.invalid");
    return parsed.origin === "https://atlas.invalid" && parsed.pathname === value && !parsed.search && !parsed.hash;
  } catch {
    return false;
  }
}

function safeExactFormAnchor(value: string): boolean {
  return /^#[A-Za-z][A-Za-z0-9_-]*$/.test(value);
}

function validDate(value: Date): boolean {
  return value instanceof Date && Number.isFinite(value.getTime());
}

function strictInstant(value: string): number | null {
  if (!exactPublicText(value)) return null;
  const match = STRICT_ISO_INSTANT.exec(value);
  if (!match) return null;
  const [, yearText, monthText, dayText, hourText, minuteText, secondText, zone] = match;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const hour = Number(hourText);
  const minute = Number(minuteText);
  const second = Number(secondText);
  if (month < 1 || month > 12 || day < 1 || day > new Date(Date.UTC(year, month, 0)).getUTCDate()) return null;
  if (hour > 23 || minute > 59 || second > 59) return null;
  if (zone !== "Z") {
    const [zoneHour, zoneMinute] = zone.slice(1).split(":").map(Number);
    if (zoneHour > 23 || zoneMinute > 59) return null;
  }
  const instant = Date.parse(value);
  return Number.isFinite(instant) ? instant : null;
}
