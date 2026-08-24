export type PerformanceLocalV5OptionalModulePresentation = "public" | "theme_lab_demo";

export type PerformanceLocalV5ReviewTrustSourceConfiguration = Readonly<{
  badgeImageReference: string;
  description: string;
  enabled: boolean;
  imageAltText: string;
  profileDestination?: string;
  publicName: string;
  sourceKey: string;
  verifiedRatingText?: string;
  verifiedReviewCountText?: string;
}>;

export type PerformanceLocalV5ReviewTrustConfiguration = Readonly<{
  enabled: boolean;
  heading?: string;
  sources?: readonly PerformanceLocalV5ReviewTrustSourceConfiguration[];
}>;

export type PerformanceLocalV5LocationMapMode = "business_location" | "city_service_area" | "disabled";

export type PerformanceLocalV5BusinessLocationMapConfiguration = Readonly<{
  approvedAddressLines: readonly string[];
  approvedLocationName: string;
  description?: string;
  directionsDestination?: string;
  googleMapsEmbedInput: string;
  governedPhoneDisplay?: string;
  mapTitle: string;
  mode: "business_location";
  sectionHeading?: string;
}>;

export type PerformanceLocalV5CityServiceAreaMapConfiguration = Readonly<{
  description?: string;
  googleMapsEmbedInput: string;
  mapTitle: string;
  mode: "city_service_area";
  sectionHeading?: string;
  targetCity: string;
  targetState: string;
}>;

export type PerformanceLocalV5LocationMapConfiguration =
  | PerformanceLocalV5BusinessLocationMapConfiguration
  | PerformanceLocalV5CityServiceAreaMapConfiguration
  | Readonly<{ mode: "disabled" }>;

export type PerformanceLocalV5OptionalModulePageConfiguration = Readonly<{
  locationMap?: PerformanceLocalV5LocationMapConfiguration;
  reviewTrust?: PerformanceLocalV5ReviewTrustConfiguration;
}>;

export type PerformanceLocalV5ResolvedReviewTrustSource = Readonly<{
  badgeImageUrl: string;
  description: string;
  imageAltText: string;
  profileDestination: string | null;
  publicName: string;
  sourceKey: string;
  verifiedRatingText: string | null;
  verifiedReviewCountText: string | null;
}>;

export type PerformanceLocalV5ResolvedReviewTrust = Readonly<{
  heading: string | null;
  presentation: PerformanceLocalV5OptionalModulePresentation;
  sources: readonly PerformanceLocalV5ResolvedReviewTrustSource[];
}>;

type PerformanceLocalV5ResolvedLocationMapBase = Readonly<{
  description: string | null;
  googleMapsEmbedUrl: string;
  mapTitle: string;
  presentation: PerformanceLocalV5OptionalModulePresentation;
  sectionHeading: string;
}>;

export type PerformanceLocalV5ResolvedLocationMap =
  | (PerformanceLocalV5ResolvedLocationMapBase & Readonly<{
      approvedAddressLines: readonly string[];
      approvedLocationName: string;
      directionsDestination: string | null;
      governedPhoneDisplay: string | null;
      mode: "business_location";
    }>)
  | (PerformanceLocalV5ResolvedLocationMapBase & Readonly<{
      mode: "city_service_area";
      targetCity: string;
      targetState: string;
    }>);

export type PerformanceLocalV5OptionalModulesResolution = Readonly<{
  locationMap: PerformanceLocalV5ResolvedLocationMap | null;
  reviewTrust: PerformanceLocalV5ResolvedReviewTrust | null;
}>;

export type PerformanceLocalV5OptionalModuleResolutionContext = Readonly<{
  approvedLocalImages: Readonly<Record<string, string>>;
  governedPhoneDisplay: string | null;
  governedTargetCity: string | null;
  governedTargetState: string | null;
  pageType: unknown;
  presentation: PerformanceLocalV5OptionalModulePresentation;
}>;

const EMPTY_RESOLUTION: PerformanceLocalV5OptionalModulesResolution = Object.freeze({
  locationMap: null,
  reviewTrust: null,
});

const PAGE_CONFIGURATION_KEYS = Object.freeze(["locationMap", "reviewTrust"] as const);
const REVIEW_CONFIGURATION_KEYS = Object.freeze(["enabled", "heading", "sources"] as const);
const REVIEW_SOURCE_KEYS = Object.freeze([
  "badgeImageReference",
  "description",
  "enabled",
  "imageAltText",
  "profileDestination",
  "publicName",
  "sourceKey",
  "verifiedRatingText",
  "verifiedReviewCountText",
] as const);
const BUSINESS_LOCATION_CONFIGURATION_KEYS = Object.freeze([
  "approvedAddressLines",
  "approvedLocationName",
  "description",
  "directionsDestination",
  "googleMapsEmbedInput",
  "governedPhoneDisplay",
  "mapTitle",
  "mode",
  "sectionHeading",
] as const);
const CITY_SERVICE_AREA_CONFIGURATION_KEYS = Object.freeze([
  "description",
  "googleMapsEmbedInput",
  "mapTitle",
  "mode",
  "sectionHeading",
  "targetCity",
  "targetState",
] as const);
const DISABLED_LOCATION_CONFIGURATION_KEYS = Object.freeze(["mode"] as const);

export function resolvePerformanceLocalV5OptionalModules(
  raw: unknown,
  context: PerformanceLocalV5OptionalModuleResolutionContext,
): PerformanceLocalV5OptionalModulesResolution {
  if (context.pageType !== "service" && context.pageType !== "city_service") return EMPTY_RESOLUTION;
  const configuration = exactRecord(raw, PAGE_CONFIGURATION_KEYS);
  if (!configuration) return EMPTY_RESOLUTION;
  const reviewTrust = resolveReviewTrust(configuration.reviewTrust, context);
  const locationMap = resolveLocationMap(configuration.locationMap, context);
  if (!reviewTrust && !locationMap) return EMPTY_RESOLUTION;
  return Object.freeze({ locationMap, reviewTrust });
}

export function isPerformanceLocalV5SafeHttpsDestination(value: unknown): value is string {
  const candidate = exactOptionalText(value);
  if (!candidate || candidate.startsWith("//") || candidate.includes("\\")) return false;
  try {
    const parsed = new URL(candidate);
    if (
      parsed.protocol !== "https:" ||
      !parsed.hostname ||
      parsed.username ||
      parsed.password ||
      (parsed.port && parsed.port !== "443") ||
      isPrivateHostname(parsed.hostname)
    ) return false;
    return true;
  } catch {
    return false;
  }
}

export function isPerformanceLocalV5SafeLocalImageUrl(value: unknown): value is string {
  const candidate = exactOptionalText(value);
  if (
    !candidate ||
    !candidate.startsWith("/") ||
    candidate.startsWith("//") ||
    candidate.includes("\\") ||
    candidate.includes("%") ||
    candidate.includes("?") ||
    candidate.includes("#")
  ) return false;
  try {
    const parsed = new URL(candidate, "https://performance-local.invalid");
    if (parsed.origin !== "https://performance-local.invalid" || parsed.pathname !== candidate) return false;
    if (parsed.pathname.split("/").some((segment) => segment === "." || segment === "..")) return false;
    if (!/^\/(?:api\/media\/files|assets|media)\//.test(parsed.pathname)) return false;
    return /\.(?:avif|jpe?g|png|svg|webp)$/i.test(parsed.pathname);
  } catch {
    return false;
  }
}

export function isPerformanceLocalV5SafeGoogleMapsEmbedUrl(value: unknown): value is string {
  const candidate = exactOptionalText(value);
  if (!candidate || candidate.startsWith("//") || candidate.includes("\\")) return false;
  try {
    const parsed = new URL(candidate);
    if (
      parsed.protocol !== "https:" ||
      parsed.origin !== "https://www.google.com" ||
      parsed.username ||
      parsed.password ||
      parsed.port ||
      parsed.hash
    ) return false;
    if (parsed.pathname === "/maps/embed") return Boolean(parsed.searchParams.get("pb")?.trim());
    const versioned = parsed.pathname.match(/^\/maps\/embed\/v1\/(place|view|directions|search|streetview)$/);
    if (!versioned || !parsed.searchParams.get("key")?.trim()) return false;
    const hasParameter = (name: string) => Boolean(parsed.searchParams.get(name)?.trim());
    if (versioned[1] === "directions") return hasParameter("origin") && hasParameter("destination");
    if (versioned[1] === "view") return hasParameter("center") && hasParameter("zoom");
    if (versioned[1] === "streetview") return hasParameter("location") || hasParameter("pano");
    return hasParameter("q");
  } catch {
    return false;
  }
}

export function resolvePerformanceLocalV5GoogleMapsEmbedInput(value: unknown): string | null {
  if (typeof value !== "string" || !value || value.length > 16_384 || value !== value.trim()) return null;
  if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(value)) return null;
  const directUrlIsSafe: boolean = isPerformanceLocalV5SafeGoogleMapsEmbedUrl(value);
  if (directUrlIsSafe) return value;

  const iframe = value.match(/^<iframe\b([^>]*)>\s*<\/iframe>$/i);
  if (!iframe) return null;
  const source = iframeSourceAttribute(iframe[1] ?? "");
  if (!source) return null;
  const decodedSource = source
    .replace(/&amp;/gi, "&")
    .replace(/&#0*38;/gi, "&")
    .replace(/&#x0*26;/gi, "&");
  if (/&(?:[a-z][a-z0-9]+|#\d+|#x[\da-f]+);/i.test(decodedSource)) return null;
  return isPerformanceLocalV5SafeGoogleMapsEmbedUrl(decodedSource) ? decodedSource : null;
}

function resolveReviewTrust(
  raw: unknown,
  context: PerformanceLocalV5OptionalModuleResolutionContext,
): PerformanceLocalV5ResolvedReviewTrust | null {
  if (raw === undefined) return null;
  const configuration = exactRecord(raw, REVIEW_CONFIGURATION_KEYS);
  if (!configuration || typeof configuration.enabled !== "boolean" || !configuration.enabled) return null;
  if (!Array.isArray(configuration.sources) || configuration.sources.length < 1 || configuration.sources.length > 3) return null;
  const heading = optionalExactTextProperty(configuration, "heading");
  if (heading === false) return null;

  const records = configuration.sources
    .map((source) => exactRecord(source, REVIEW_SOURCE_KEYS))
    .filter((source): source is Record<string, unknown> => Boolean(source));
  const sourceKeys = records
    .map((source) => exactText(source.sourceKey))
    .filter((key): key is string => typeof key === "string" && /^[a-z][a-z0-9_-]{0,63}$/.test(key));
  if (new Set(sourceKeys).size !== sourceKeys.length) return null;

  const sources = records
    .map((source) => resolveReviewTrustSource(source, context))
    .filter((source): source is PerformanceLocalV5ResolvedReviewTrustSource => Boolean(source));
  if (!sources.length) return null;
  return Object.freeze({
    heading: heading || null,
    presentation: context.presentation,
    sources: Object.freeze(sources),
  });
}

function resolveReviewTrustSource(
  source: Record<string, unknown>,
  context: PerformanceLocalV5OptionalModuleResolutionContext,
): PerformanceLocalV5ResolvedReviewTrustSource | null {
  if (typeof source.enabled !== "boolean" || !source.enabled) return null;
  const sourceKey = exactText(source.sourceKey);
  const publicName = exactText(source.publicName);
  const description = exactText(source.description);
  const imageAltText = exactText(source.imageAltText);
  const badgeImageReference = exactText(source.badgeImageReference);
  if (
    !sourceKey ||
    !/^[a-z][a-z0-9_-]{0,63}$/.test(sourceKey) ||
    !publicName ||
    !description ||
    !imageAltText ||
    !badgeImageReference
  ) return null;
  const badgeImageUrl = context.approvedLocalImages[badgeImageReference];
  if (!isPerformanceLocalV5SafeLocalImageUrl(badgeImageUrl)) return null;

  const profileDestination = optionalSafeHttpsProperty(source, "profileDestination");
  const verifiedRatingText = optionalExactTextProperty(source, "verifiedRatingText");
  const verifiedReviewCountText = optionalExactTextProperty(source, "verifiedReviewCountText");
  if (profileDestination === false || verifiedRatingText === false || verifiedReviewCountText === false) return null;
  return Object.freeze({
    badgeImageUrl,
    description,
    imageAltText,
    profileDestination: profileDestination || null,
    publicName,
    sourceKey,
    verifiedRatingText: verifiedRatingText || null,
    verifiedReviewCountText: verifiedReviewCountText || null,
  });
}

function resolveLocationMap(
  raw: unknown,
  context: PerformanceLocalV5OptionalModuleResolutionContext,
): PerformanceLocalV5ResolvedLocationMap | null {
  if (raw === undefined) return null;
  const candidate = objectRecord(raw);
  if (!candidate) return null;
  if (candidate.mode === "disabled") {
    if (!exactRecord(raw, DISABLED_LOCATION_CONFIGURATION_KEYS)) return null;
    return null;
  }
  if (candidate.mode === "business_location") return resolveBusinessLocationMap(raw, context);
  if (candidate.mode === "city_service_area") return resolveCityServiceAreaMap(raw, context);
  return null;
}

function resolveBusinessLocationMap(
  raw: unknown,
  context: PerformanceLocalV5OptionalModuleResolutionContext,
): PerformanceLocalV5ResolvedLocationMap | null {
  const configuration = exactRecord(raw, BUSINESS_LOCATION_CONFIGURATION_KEYS);
  if (!configuration || configuration.mode !== "business_location") return null;
  const approvedLocationName = exactText(configuration.approvedLocationName);
  const mapTitle = exactText(configuration.mapTitle);
  if (!approvedLocationName || !mapTitle) return null;
  if (!Array.isArray(configuration.approvedAddressLines)) return null;
  const approvedAddressLines = configuration.approvedAddressLines.map(exactText);
  if (
    approvedAddressLines.length < 1 ||
    approvedAddressLines.length > 3 ||
    approvedAddressLines.some((line) => !line)
  ) return null;
  const exactAddressLines = approvedAddressLines as string[];
  if (!completePublicAddress(exactAddressLines)) return null;
  const googleMapsEmbedUrl = resolvePerformanceLocalV5GoogleMapsEmbedInput(configuration.googleMapsEmbedInput);
  if (!googleMapsEmbedUrl) return null;

  const description = optionalExactTextProperty(configuration, "description");
  const directionsDestination = optionalSafeHttpsProperty(configuration, "directionsDestination");
  const governedPhoneDisplay = optionalExactTextProperty(configuration, "governedPhoneDisplay");
  const sectionHeading = optionalExactTextProperty(configuration, "sectionHeading");
  if (
    description === false ||
    directionsDestination === false ||
    governedPhoneDisplay === false ||
    sectionHeading === false
  ) return null;
  if (governedPhoneDisplay && governedPhoneDisplay !== context.governedPhoneDisplay) return null;
  return Object.freeze({
    approvedAddressLines: Object.freeze(exactAddressLines),
    approvedLocationName,
    description: description || null,
    directionsDestination: directionsDestination || null,
    googleMapsEmbedUrl,
    governedPhoneDisplay: governedPhoneDisplay || null,
    mapTitle,
    mode: "business_location",
    presentation: context.presentation,
    sectionHeading: sectionHeading || "Our Location",
  });
}

function resolveCityServiceAreaMap(
  raw: unknown,
  context: PerformanceLocalV5OptionalModuleResolutionContext,
): PerformanceLocalV5ResolvedLocationMap | null {
  const configuration = exactRecord(raw, CITY_SERVICE_AREA_CONFIGURATION_KEYS);
  if (!configuration || configuration.mode !== "city_service_area") return null;
  const targetCity = exactPlaceName(configuration.targetCity);
  const targetState = exactPlaceName(configuration.targetState);
  const mapTitle = exactText(configuration.mapTitle);
  if (!targetCity || !targetState || !mapTitle) return null;
  if (targetCity !== context.governedTargetCity || targetState !== context.governedTargetState) return null;
  const googleMapsEmbedUrl = resolvePerformanceLocalV5GoogleMapsEmbedInput(configuration.googleMapsEmbedInput);
  if (!googleMapsEmbedUrl) return null;

  const description = optionalExactTextProperty(configuration, "description");
  const sectionHeading = optionalExactTextProperty(configuration, "sectionHeading");
  if (description === false || sectionHeading === false) return null;
  const exactSectionHeading = sectionHeading || `Serving ${targetCity}, ${targetState}`;
  if (!cityServiceAreaLanguageIsSafe([exactSectionHeading, description || "", mapTitle])) return null;
  return Object.freeze({
    description: description || null,
    googleMapsEmbedUrl,
    mapTitle,
    mode: "city_service_area",
    presentation: context.presentation,
    sectionHeading: exactSectionHeading,
    targetCity,
    targetState,
  });
}

function exactRecord<const Keys extends readonly string[]>(
  value: unknown,
  allowedKeys: Keys,
): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record);
  return keys.every((key) => allowedKeys.includes(key as Keys[number])) ? record : null;
}

function objectRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function exactText(value: unknown): string | null {
  if (typeof value !== "string" || !value || value !== value.trim() || /[\u0000-\u001f\u007f]/.test(value)) return null;
  return value;
}

function exactOptionalText(value: unknown): string | null {
  return exactText(value);
}

function optionalExactTextProperty(
  record: Record<string, unknown>,
  key: string,
): string | null | false {
  if (!Object.prototype.hasOwnProperty.call(record, key)) return null;
  return exactText(record[key]) ?? false;
}

function optionalSafeHttpsProperty(
  record: Record<string, unknown>,
  key: string,
): string | null | false {
  if (!Object.prototype.hasOwnProperty.call(record, key)) return null;
  return isPerformanceLocalV5SafeHttpsDestination(record[key]) ? record[key] : false;
}

function completePublicAddress(lines: readonly string[]): boolean {
  const combined = lines.join(" ");
  if (/\b(?:confidential|home address|personal address|private residence|residential address)\b/i.test(combined)) return false;
  return combined.length >= 12 && /[A-Za-z]/.test(combined) && /\d/.test(combined);
}

function exactPlaceName(value: unknown): string | null {
  const exact = exactText(value);
  if (!exact || exact.length > 80 || !/^[A-Za-z][A-Za-z .'-]*$/.test(exact)) return null;
  return exact;
}

function cityServiceAreaLanguageIsSafe(values: readonly string[]): boolean {
  const combined = values.join(" ");
  if (/\b(?:office|storefront|store|shop|address|location|headquarters|showroom|visit\s+us|find\s+us|located\s+at|come\s+see\s+us|google\s+business\s+profile)\b/i.test(combined)) return false;
  return !/\b\d{1,6}\s+[A-Za-z0-9 .'-]+\s(?:street|st|avenue|ave|road|rd|boulevard|blvd|drive|dr|lane|ln|way|court|ct|parkway|pkwy|highway|hwy)\b/i.test(combined);
}

function iframeSourceAttribute(attributes: string): string | null {
  let offset = 0;
  let source: string | null = null;
  while (offset < attributes.length) {
    while (/\s/.test(attributes[offset] ?? "")) offset += 1;
    if (offset >= attributes.length) break;
    const nameMatch = attributes.slice(offset).match(/^[A-Za-z][A-Za-z0-9:._-]*/);
    if (!nameMatch) return null;
    const name = nameMatch[0].toLowerCase();
    offset += nameMatch[0].length;
    while (/\s/.test(attributes[offset] ?? "")) offset += 1;

    let attributeValue: string | null = null;
    if (attributes[offset] === "=") {
      offset += 1;
      while (/\s/.test(attributes[offset] ?? "")) offset += 1;
      const quote = attributes[offset];
      if (quote !== '"' && quote !== "'") return null;
      offset += 1;
      const valueEnd = attributes.indexOf(quote, offset);
      if (valueEnd < 0) return null;
      attributeValue = attributes.slice(offset, valueEnd);
      offset = valueEnd + 1;
    }

    if (name === "src") {
      if (source !== null || !attributeValue) return null;
      source = attributeValue;
    }
  }
  return source;
}

function isPrivateHostname(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/\.$/, "");
  if (
    !host ||
    host === "localhost" ||
    host.endsWith(".localhost") ||
    host === "home.arpa" ||
    host.endsWith(".home.arpa") ||
    host.endsWith(".local") ||
    host.endsWith(".internal") ||
    host.endsWith(".home") ||
    host.endsWith(".lan")
  ) return true;

  const ipv4 = host.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
  if (ipv4) {
    const [, firstText, secondText] = ipv4;
    const first = Number(firstText);
    const second = Number(secondText);
    return (
      first === 0 ||
      first === 10 ||
      first === 127 ||
      (first === 100 && second >= 64 && second <= 127) ||
      (first === 169 && second === 254) ||
      (first === 172 && second >= 16 && second <= 31) ||
      (first === 192 && second === 168) ||
      (first === 198 && (second === 18 || second === 19)) ||
      first >= 224
    );
  }

  if (host.startsWith("[") && host.endsWith("]")) {
    const ipv6 = host.slice(1, -1);
    return (
      ipv6 === "::" ||
      ipv6 === "::1" ||
      ipv6.startsWith("::") ||
      ipv6.startsWith("64:ff9b:") ||
      ipv6.startsWith("100:") ||
      /^f[cd]/.test(ipv6) ||
      /^fe[89ab]/.test(ipv6) ||
      /^ff/.test(ipv6) ||
      /^2001:(?:2:|10:|20:|db8:)/.test(ipv6)
    );
  }

  return !host.includes(".");
}
