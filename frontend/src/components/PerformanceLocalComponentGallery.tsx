import {
  PERFORMANCE_LOCAL_THEME_COMPATIBILITY,
  performanceLocalOptionalComponentAttributes,
  performanceLocalOptionalConfiguration,
  resolveOptionalComponent,
  type OptionalComponentResolution,
  type PerformanceLocalComponentKey,
  type PerformanceLocalViewport,
} from "./performanceLocalTheme";

const DEMO_LABEL = "DEMO COMPONENT — NOT SITE CONTENT";
const DEMO_WEBSITE_ID = 9_000_001;

export type PerformanceLocalGalleryComponentKey = Extract<
  PerformanceLocalComponentKey,
  | "campaign_banner"
  | "review_badge_group"
  | "statistics_counter_band"
  | "video_embed_section"
  | "map_or_service_area_section"
  | "community_program_section"
  | "language_selector"
>;

export type PerformanceLocalComponentGalleryProps = Readonly<{
  evaluatedAt?: Date;
  viewport?: PerformanceLocalViewport;
}>;

type DemoCard = Readonly<{
  key: PerformanceLocalGalleryComponentKey;
  title: string;
  purpose: string;
  structure: readonly string[];
  enabledConfiguration: Readonly<Record<string, unknown>>;
}>;

const DEMO_CARDS: readonly DemoCard[] = Object.freeze([
  Object.freeze({
    key: "campaign_banner",
    title: "Campaign banner",
    purpose: "Shows the hierarchy of a time-bounded, approved campaign without a public offer.",
    structure: Object.freeze(["Message region", "Local action", "Terms reference"]),
    enabledConfiguration: Object.freeze({
      campaignLabel: "Illustrative campaign message — no offer",
      ctaLabel: "Preview action",
      ctaDestination: "#demo-terms",
      startDate: "2000-01-01T00:00:00Z",
      endDate: "2099-12-31T23:59:59Z",
      termsReference: "Demo terms placeholder",
      approvalIdentity: "DEMO-NOT-AN-APPROVAL",
    }),
  }),
  Object.freeze({
    key: "review_badge_group",
    title: "Review badge group",
    purpose: "Shows the intended hierarchy for governed provider evidence without presenting a real rating or count.",
    structure: Object.freeze(["Provider identity", "Verified evidence", "Approved destination"]),
    enabledConfiguration: Object.freeze({
      provider: "DEMO REVIEW PROVIDER",
      rating: 0,
      reviewCount: 0,
      ratingApprovalStatus: "approved",
      reviewCountApprovalStatus: "approved",
      verificationDate: "2000-01-01",
      destination: "#demo-review-destination",
      trademarkUseAuthorization: "DEMO ONLY — NO TRADEMARK",
      approvalIdentity: "DEMO-NOT-AN-APPROVAL",
    }),
  }),
  Object.freeze({
    key: "statistics_counter_band",
    title: "Statistics band",
    purpose: "Shows the intended sourced-metric hierarchy using nonnumeric demonstration labels only.",
    structure: Object.freeze(["Metric label", "Approved value", "Source and effective date"]),
    enabledConfiguration: Object.freeze({
      metricLabel: "DEMO METRIC A",
      value: "DEMO VALUE",
      source: "DEMO SOURCE — NOT EVIDENCE",
      effectiveDate: "2000-01-01",
      approvalIdentity: "DEMO-NOT-AN-APPROVAL",
    }),
  }),
  Object.freeze({
    key: "video_embed_section",
    title: "Video section",
    purpose: "Shows a provider-free, privacy-gated video treatment without loading or embedding media.",
    structure: Object.freeze(["Consent surface", "Accessible title", "Governed media identity"]),
    enabledConfiguration: Object.freeze({
      approvedProvider: "DEMO PROVIDER — NONE LOADED",
      approvedUrlOrMediaIdentity: "media:DEMO-NO-MEDIA-LOADED",
      title: "DEMO VIDEO TITLE",
      accessibilityText: "DEMO ACCESSIBILITY TEXT",
      privacyMode: "local_media",
      approvalIdentity: "DEMO-NOT-AN-APPROVAL",
    }),
  }),
  Object.freeze({
    key: "map_or_service_area_section",
    title: "Map or service area",
    purpose: "Shows provider and storefront status without a map, address, coordinates, or geographic claim.",
    structure: Object.freeze(["Approved area", "Storefront status", "Privacy control"]),
    enabledConfiguration: Object.freeze({
      approvedLocationOrServiceArea: "DEMO SERVICE AREA — NO ADDRESS OR MAP PROVIDER",
      approvedProvider: "DEMO PROVIDER STATUS — NONE LOADED",
      externalRequestConsent: true,
      locationStatus: "approved",
      storefrontStatus: "service_area_only",
      approvalIdentity: "DEMO-NOT-AN-APPROVAL",
    }),
  }),
  Object.freeze({
    key: "community_program_section",
    title: "Community program",
    purpose: "Shows the intended effective-dated program hierarchy without implying that a real program exists.",
    structure: Object.freeze(["Program identity", "Approved description", "Local destination"]),
    enabledConfiguration: Object.freeze({
      approvedProgramIdentity: "DEMO COMMUNITY PROGRAM",
      approvedCopy: "DEMO DESCRIPTION",
      destination: "#demo-community-destination",
      effectiveStartDate: "2000-01-01",
      effectiveEndDate: "2099-12-31",
      approvalIdentity: "DEMO-NOT-AN-APPROVAL",
    }),
  }),
  Object.freeze({
    key: "language_selector",
    title: "Language selector",
    purpose: "Shows an inert language-control treatment without adding translations, routes, or persisted selection.",
    structure: Object.freeze(["Language labels", "Translated routes", "Canonical and hreflang configuration"]),
    enabledConfiguration: Object.freeze({
      actualTranslatedContent: true,
      translatedRoutes: Object.freeze([
        Object.freeze({ language: "language-a", destination: "/demo-language-a" }),
        Object.freeze({ language: "language-b", destination: "/demo-language-b" }),
      ]),
      canonicalHreflangConfiguration: "approved",
      languageLabels: Object.freeze({ "language-a": "LANGUAGE A", "language-b": "LANGUAGE B" }),
      routingBehavior: "approved_local_routes",
      approvalIdentity: "DEMO-NOT-AN-APPROVAL",
    }),
  }),
]);

const DUAL_STATE_COMPONENTS = new Set<PerformanceLocalGalleryComponentKey>([
  "review_badge_group",
  "statistics_counter_band",
  "video_embed_section",
  "map_or_service_area_section",
  "community_program_section",
  "language_selector",
]);

export function PerformanceLocalComponentGallery({
  evaluatedAt = new Date(),
  viewport = "desktop",
}: PerformanceLocalComponentGalleryProps) {
  return (
    <section
      aria-labelledby="performance-local-gallery-title"
      className="performanceLocalComponentGallery"
      data-demo-only="true"
      data-external-requests="0"
      data-theme-compatibility={PERFORMANCE_LOCAL_THEME_COMPATIBILITY}
    >
      <header>
        <p className="eyebrow">{DEMO_LABEL}</p>
        <h2 id="performance-local-gallery-title">Optional conversion-component gallery</h2>
        <p>
          Runtime-only presentation previews. These examples are not business facts, public content,
          provider integrations, active configurations, or activation evidence.
        </p>
      </header>
      <div className="performanceLocalGalleryGrid">
        {DEMO_CARDS.map((card) => {
          const enabledConfiguration = performanceLocalOptionalConfiguration(
            card.key,
            DEMO_WEBSITE_ID,
            `${card.title} synthetic demonstration`,
            card.enabledConfiguration,
          );
          const enabledResolution = resolveOptionalComponent(
            card.key,
            enabledConfiguration,
            DEMO_WEBSITE_ID,
            viewport,
            evaluatedAt,
          );
          const missingResolution = DUAL_STATE_COMPONENTS.has(card.key)
            ? resolveOptionalComponent(
                card.key,
                performanceLocalOptionalConfiguration(
                  card.key,
                  DEMO_WEBSITE_ID,
                  `${card.title} missing-configuration demonstration`,
                ),
                DEMO_WEBSITE_ID,
                viewport,
                evaluatedAt,
              )
            : null;
          return (
            <article
              className="performanceLocalGalleryCard"
              data-component-key={card.key}
              data-demo-only="true"
              data-resolution={enabledResolution.visible ? "demo_enabled" : "fail_closed"}
              key={card.key}
            >
              <p className="eyebrow">{DEMO_LABEL}</p>
              <h3>{card.title}</h3>
              <p>{card.purpose}</p>
              {enabledResolution.visible ? (
                <EnabledDemoPresentation card={card} resolution={enabledResolution} />
              ) : (
                <ResolutionFailure title={`${card.title} enabled demonstration`} resolution={enabledResolution} />
              )}
              <ul aria-label={`${card.title} structural regions`} className="performanceLocalGalleryRegionList">
                {card.structure.map((item) => <li key={item}>{item}</li>)}
              </ul>
              <p className="performanceLocalGalleryOperatorDiagnostic" role="status">
                <strong>{enabledResolution.visible ? "Demo enabled" : "Fail closed"}</strong>
                {enabledResolution.visible
                  ? " — runtime-only illustrative configuration; no state is persisted."
                  : " — the synthetic configuration did not pass its centralized contract."}
              </p>
              {missingResolution ? (
                <FailClosedDemo card={card} resolution={missingResolution} />
              ) : null}
            </article>
          );
        })}
      </div>
      <p id="demo-terms">Demo-only terms placeholder. No campaign or offer exists.</p>
    </section>
  );
}

function EnabledDemoPresentation({
  card,
  resolution,
}: {
  card: DemoCard;
  resolution: OptionalComponentResolution;
}) {
  const attributes = performanceLocalOptionalComponentAttributes(card.key, resolution);
  if (card.key === "campaign_banner") {
    return <GalleryStructure card={card} attributes={attributes} />;
  }

  return (
    <section
      {...attributes}
      aria-label={`${card.title} enabled synthetic demonstration`}
      className={`performanceLocalGalleryEnabledDemo performanceLocalGalleryEnabledDemo-${card.key.replace(/_/g, "-")}`}
      data-demo-only="true"
      data-demo-state="enabled"
      data-enabled-demo-component={card.key}
    >
      <p className="performanceLocalGalleryDemoNotice">{DEMO_LABEL}</p>
      {card.key === "review_badge_group" ? <ReviewDemo /> : null}
      {card.key === "statistics_counter_band" ? <StatisticsDemo /> : null}
      {card.key === "video_embed_section" ? <VideoDemo /> : null}
      {card.key === "map_or_service_area_section" ? <ServiceAreaDemo /> : null}
      {card.key === "community_program_section" ? <CommunityDemo /> : null}
      {card.key === "language_selector" ? <LanguageDemo /> : null}
    </section>
  );
}

function ReviewDemo() {
  return (
    <div className="performanceLocalGalleryReviewDemo">
      <div className="performanceLocalGalleryReviewProvider">
        <span aria-hidden="true" className="performanceLocalGalleryIconToken">R</span>
        <div><span>Provider / evidence</span><strong>DEMO REVIEW PROVIDER</strong><small>DEMO EVIDENCE — NOT VERIFIED</small></div>
      </div>
      <div><span>Rating presentation</span><strong>DEMO RATING</strong></div>
      <div><span>Count presentation</span><strong>DEMO REVIEW COUNT</strong></div>
      <button disabled type="button">DEMO DESTINATION</button>
    </div>
  );
}

function StatisticsDemo() {
  return (
    <div className="performanceLocalGalleryStatisticsDemo">
      {["A", "B", "C"].map((metric) => (
        <div key={metric}>
          <span aria-hidden="true" className="performanceLocalGalleryMetricToken" />
          <strong>DEMO VALUE</strong>
          <span>{`DEMO METRIC ${metric}`}</span>
        </div>
      ))}
    </div>
  );
}

function VideoDemo() {
  return (
    <div className="performanceLocalGalleryVideoDemo">
      <div aria-label="Inert demo video poster; no media is loaded" className="performanceLocalGalleryVideoPoster" role="img">
        <button aria-label="Demo play control; no media is loaded" disabled type="button">
          <span aria-hidden="true">▶</span>
        </button>
        <strong>DEMO VIDEO — NO MEDIA LOADED</strong>
      </div>
      <div className="performanceLocalGalleryVideoDetails">
        <strong>DEMO VIDEO TITLE</strong>
        <span>Accessibility text: DEMO ACCESSIBILITY TEXT</span>
        <span>Privacy mode: PROVIDER-FREE / REQUEST-FREE</span>
      </div>
    </div>
  );
}

function ServiceAreaDemo() {
  return (
    <div className="performanceLocalGalleryServiceAreaDemo">
      <div aria-hidden="true" className="performanceLocalGalleryAbstractSurface">
        <span /><span /><span />
      </div>
      <div>
        <strong>DEMO SERVICE AREA — NO ADDRESS OR MAP PROVIDER</strong>
        <dl>
          <div><dt>Storefront status</dt><dd>DEMO SERVICE-AREA STATUS</dd></div>
          <div><dt>Provider / privacy</dt><dd>NO PROVIDER LOADED / NO REQUEST</dd></div>
        </dl>
        <button disabled type="button">DEMO ACTION — NO DESTINATION</button>
      </div>
    </div>
  );
}

function CommunityDemo() {
  return (
    <div className="performanceLocalGalleryCommunityDemo">
      <span aria-hidden="true" className="performanceLocalGalleryIconToken">+</span>
      <div>
        <strong>DEMO COMMUNITY PROGRAM</strong>
        <p>DEMO DESCRIPTION</p>
        <span>DEMO EFFECTIVE STATUS</span>
      </div>
      <button disabled type="button">DEMO DESTINATION</button>
    </div>
  );
}

function LanguageDemo() {
  return (
    <div aria-label="Inert language selector demonstration" className="performanceLocalGalleryLanguageDemo" role="group">
      <span>Demo language presentation</span>
      <div>
        <button aria-pressed="false" disabled type="button">LANGUAGE A</button>
        <button aria-pressed="false" disabled type="button">LANGUAGE B</button>
      </div>
      <small>No translated content, routes, provider, or persisted selection is created.</small>
    </div>
  );
}

function FailClosedDemo({ card, resolution }: { card: DemoCard; resolution: OptionalComponentResolution }) {
  return (
    <section
      aria-label={`${card.title} missing-configuration demonstration`}
      className="performanceLocalGalleryFailClosedDemo"
      data-demo-only="true"
      data-demo-state="fail-closed"
      data-fail-closed-component={card.key}
      data-resolution="fail_closed"
    >
      <div>
        <strong>Fail-closed / missing governed configuration</strong>
        <span>Required scope: exact current Website identity; no cross-Website configuration.</span>
      </div>
      <ul aria-label={`${card.title} missing governed requirements`}>
        {resolution.errors.map((error) => <li key={error}>{error}</li>)}
      </ul>
      <p>{resolution.diagnostics}</p>
      <button disabled type="button">Disabled until governed inputs are complete</button>
    </section>
  );
}

function ResolutionFailure({ title, resolution }: { title: string; resolution: OptionalComponentResolution }) {
  return (
    <section aria-label={title} className="performanceLocalGalleryFailClosedDemo" data-resolution="fail_closed">
      <strong>Fail closed</strong>
      <ul>{resolution.errors.map((error) => <li key={error}>{error}</li>)}</ul>
    </section>
  );
}

function GalleryStructure({
  card,
  attributes,
}: {
  card: DemoCard;
  attributes: ReturnType<typeof performanceLocalOptionalComponentAttributes>;
}) {
  return (
    <div
      {...attributes}
      className={`performanceLocalGalleryDemoSurface performanceLocalGalleryDemo-${card.key.replace(/_/g, "-")}`}
      aria-label={`${card.title} non-factual structural preview`}
      data-demo-only="true"
      data-enabled-demo-component={card.key}
    >
      <span className="performanceLocalGalleryDemoLabel">Structural preview</span>
      {card.structure.map((item, index) => (
        <span className="performanceLocalGalleryDemoRegion" data-demo-region={index + 1} key={item}>
          {item}
        </span>
      ))}
    </div>
  );
}

export default PerformanceLocalComponentGallery;
