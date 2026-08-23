import {
  ArrowUp,
  ChevronDown,
  Mail,
  Menu,
  Phone,
  ShieldCheck,
  X,
} from "lucide-react";
import {
  type FormEvent,
  type ReactNode,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import { Link } from "react-router-dom";

import {
  performanceLocalActionCopyEquivalent,
  performanceLocalFormDomId,
  type PerformanceLocalCampaign,
  type PerformanceLocalEstimateFormConfiguration,
  type PerformanceLocalGovernedContact,
} from "./PerformanceLocalRenderer";
import {
  PERFORMANCE_LOCAL_V5_DEMO_MEDIA_LABEL,
} from "./performanceLocalThemeV5";
import type {
  PerformanceLocalV5CountyCityPresentation,
  PerformanceLocalV5DestinationConsumptionRecord,
  PerformanceLocalV5HomeServicePresentation,
} from "./performanceLocalV5LayoutContract";
import {
  buildNavigationTree,
  resolvePageMediaDisplayPreset,
  type ResolvedNavigationItem,
} from "../pages/GeneratedPagePreview";
import type {
  PageComponentInstance,
  PageMediaDisplayPreset,
} from "../types";

export type PerformanceLocalV5ReviewMode = "truthful" | "structural_demo";

export type PerformanceLocalV5TopAction =
  | Readonly<{
      destination: string;
      label: string;
      mode: "special" | "request_estimate" | "service_promotion";
    }>
  | Readonly<{
      mode: "disabled";
    }>;

export type PerformanceLocalV5RegionPlan = Readonly<{
  regionKey: string;
  requirement: "required" | "optional";
  sourceInstanceKeys: readonly string[];
  presentationGroups: readonly Readonly<{
    groupKey: string;
    sourceInstanceKeys: readonly string[];
  }>[];
  missing: boolean;
}>;

type NonCityPageType = "home" | "service" | "county" | "about" | "contact" | "faq";

export type PerformanceLocalV5LayoutBodyProps = Readonly<{
  callLabel: string;
  componentByInstanceKey: ReadonlyMap<string, PageComponentInstance>;
  countyCityPresentation: PerformanceLocalV5CountyCityPresentation;
  destinationForGeneratedPageId: (generatedPageId: number) => string;
  estimateDestination: string | null;
  estimateForm: PerformanceLocalEstimateFormConfiguration | null;
  governedContact: PerformanceLocalGovernedContact | null;
  homeServicePresentation: PerformanceLocalV5HomeServicePresentation;
  layoutKey: string;
  onFormFocusRiskChange: (focused: boolean) => void;
  pageType: NonCityPageType;
  regions: readonly PerformanceLocalV5RegionPlan[];
  reviewMode: PerformanceLocalV5ReviewMode;
}>;

export function PerformanceLocalV5LayoutBody(props: PerformanceLocalV5LayoutBodyProps) {
  switch (props.pageType) {
    case "home":
      return <HomeLayout {...props} />;
    case "service":
      return <ServiceLayout {...props} />;
    case "county":
      return <ServiceCountyLayout {...props} />;
    case "about":
      return <AboutLayout {...props} />;
    case "contact":
      return <ContactLayout {...props} />;
    case "faq":
      return <FaqLayout {...props} />;
  }
}

function HomeLayout(props: PerformanceLocalV5LayoutBodyProps) {
  const hero = region(props, "hero");
  const trust = region(props, "trust");
  const services = region(props, "service_discovery");
  const companyValue = region(props, "company_value");
  const serviceArea = region(props, "service_area_discovery");
  const related = region(props, "supporting_discovery");
  const final = region(props, "final_conversion");
  return (
    <LayoutRoot props={props} layoutClass="performanceLocalV5LayoutHome">
      <HeroRegion props={props} regionPlan={hero} />
      <TrustRegion props={props} regionPlan={trust} />
      <HomeServiceDiscovery props={props} regionPlan={services} />
      <ComposedAuthorityRegion
        className="performanceLocalV5AuthorityPair"
        props={props}
        regions={[companyValue, serviceArea]}
      />
      <ProjectedDestinationRegion
        destinations={props.homeServicePresentation.remainingDestinations}
        includeMedia={false}
        props={props}
        regionPlan={related}
        sourceInstanceKey={props.homeServicePresentation.relatedLinksSourceInstanceKey}
      />
      <SharedFinalConversion props={props} regionPlan={final} />
    </LayoutRoot>
  );
}

function ServiceLayout(props: PerformanceLocalV5LayoutBodyProps) {
  return (
    <LayoutRoot props={props} layoutClass="performanceLocalV5LayoutService">
      <HeroRegion props={props} regionPlan={region(props, "hero")} />
      <TrustRegion props={props} regionPlan={region(props, "trust")} />
      <AuthorityRegion props={props} regionPlan={region(props, "service_overview")} emphasis="overview" />
      <DisclosureBodyRegion props={props} regionPlan={region(props, "approved_guidance")} kind="guidance" />
      <ComposedAuthorityRegion
        className="performanceLocalV5DiscoveryComposition"
        props={props}
        regions={[region(props, "service_area_discovery"), region(props, "related_discovery")]}
      />
      <FaqRegion props={props} regionPlan={region(props, "faq")} />
      <SharedFinalConversion props={props} regionPlan={region(props, "final_conversion")} />
    </LayoutRoot>
  );
}

function ServiceCountyLayout(props: PerformanceLocalV5LayoutBodyProps) {
  return (
    <LayoutRoot props={props} layoutClass="performanceLocalV5LayoutCounty">
      <HeroRegion props={props} regionPlan={region(props, "hero")} />
      <TrustRegion props={props} regionPlan={region(props, "trust")} />
      <AuthorityRegion props={props} regionPlan={region(props, "county_overview")} emphasis="overview" />
      <CountyCityDiscovery
        props={props}
        cityRegion={region(props, "city_discovery")}
        relatedRegion={region(props, "related_city_discovery")}
      />
      <AuthorityRegion props={props} regionPlan={region(props, "service_process")} emphasis="process" />
      <DisclosureBodyRegion props={props} regionPlan={region(props, "customer_expectations")} kind="guidance" />
      <ComposedAuthorityRegion
        className="performanceLocalV5AuthorityPair"
        props={props}
        regions={[region(props, "preparation_guidance"), region(props, "county_credentials")]}
      />
      <ProjectedDestinationRegion
        destinations={props.countyCityPresentation.remainingDestinations}
        props={props}
        regionPlan={region(props, "related_city_discovery")}
        sourceInstanceKey={props.countyCityPresentation.destinationCardsSourceInstanceKey}
      />
      <FaqRegion props={props} regionPlan={region(props, "faq")} />
      <SharedFinalConversion props={props} regionPlan={region(props, "final_conversion")} />
    </LayoutRoot>
  );
}

function AboutLayout(props: PerformanceLocalV5LayoutBodyProps) {
  return (
    <LayoutRoot props={props} layoutClass="performanceLocalV5LayoutAbout">
      <HeroRegion props={props} regionPlan={region(props, "hero")} />
      <section className="performanceLocalV5Section performanceLocalV5AboutAuthority" data-v5-composition="story-and-credentials">
        <div className="performanceLocalV5Container performanceLocalV5AboutAuthorityGrid">
          <RegionContents props={props} regionPlan={region(props, "company_story")} />
          <div className="performanceLocalV5AboutCredentials">
            <RegionContents props={props} regionPlan={region(props, "trust")} />
          </div>
        </div>
      </section>
      <AuthorityRegion props={props} regionPlan={region(props, "experience")} emphasis="overview" />
      <section className="performanceLocalV5Section performanceLocalV5PurposeJourney" data-v5-composition="purpose-and-navigation">
        <div className="performanceLocalV5Container performanceLocalV5PurposeJourneyGrid">
          <RegionContents props={props} regionPlan={region(props, "service_philosophy")} />
          <RegionContents props={props} regionPlan={region(props, "service_discovery")} />
        </div>
      </section>
      <SharedFinalConversion props={props} regionPlan={region(props, "final_conversion")} />
    </LayoutRoot>
  );
}

function ContactLayout(props: PerformanceLocalV5LayoutBodyProps) {
  return (
    <LayoutRoot props={props} layoutClass="performanceLocalV5LayoutContact">
      <HeroRegion props={props} regionPlan={region(props, "hero")} compact />
      <AuthorityRegion props={props} regionPlan={region(props, "immediate_contact")} emphasis="related" />
      <ContactInformationRegion props={props} regionPlan={region(props, "contact_information")} />
      <SharedFinalConversion props={props} regionPlan={region(props, "final_conversion")} compactForm />
      <AuthorityRegion props={props} regionPlan={region(props, "related_discovery")} emphasis="related" />
    </LayoutRoot>
  );
}

function FaqLayout(props: PerformanceLocalV5LayoutBodyProps) {
  const support = [region(props, "contact_support"), region(props, "trust")];
  return (
    <LayoutRoot props={props} layoutClass="performanceLocalV5LayoutFaq">
      <HeroRegion props={props} regionPlan={region(props, "hero")} compact />
      <FaqRegion props={props} regionPlan={region(props, "faq")} />
      <AuthorityRegion props={props} regionPlan={region(props, "related_discovery")} emphasis="related" />
      <SharedFinalConversion
        props={props}
        regionPlan={region(props, "final_conversion")}
        supportRegions={support}
      />
    </LayoutRoot>
  );
}

function LayoutRoot({
  children,
  layoutClass,
  props,
}: {
  children: ReactNode;
  layoutClass: string;
  props: PerformanceLocalV5LayoutBodyProps;
}) {
  return (
    <div
      className={`performanceLocalV5Layout ${layoutClass}`}
      data-v5-layout-key={props.layoutKey}
      data-v5-page-type={props.pageType}
    >
      {children}
    </div>
  );
}

function HeroRegion({
  compact = false,
  props,
  regionPlan,
}: {
  compact?: boolean;
  props: PerformanceLocalV5LayoutBodyProps;
  regionPlan: PerformanceLocalV5RegionPlan | null;
}) {
  const component = exactComponent(regionPlan, props.componentByInstanceKey, "hero");
  if (!component) return null;
  const media = exactTargetMedia(component, props.componentByInstanceKey);
  const hasRenderableHeroMedia = Boolean(media && renderableMedia(media));
  const hasDemoSlot = Boolean(media && !hasRenderableHeroMedia && props.reviewMode === "structural_demo");
  const heroMediaState = hasRenderableHeroMedia ? "renderable" : hasDemoSlot ? "demo" : "omitted";
  const data = component.resolved_data;
  return (
    <section
      className={`performanceLocalV5Hero${compact ? " performanceLocalV5HeroCompact" : ""}`}
      data-v5-region="hero"
      aria-label="hero"
    >
      <div
        className={`performanceLocalV5Container performanceLocalV5HeroGrid${heroMediaState === "omitted" ? " performanceLocalV5HeroGridSingle" : ""}`}
        data-source-instance-key={component.instance_key}
        data-v5-hero-media-state={heroMediaState}
      >
        <div className="performanceLocalV5HeroCopy">
          <h1>{text(data.title)}</h1>
          {text(data.intro) ? <p className="performanceLocalV5HeroSummary">{text(data.intro)}</p> : null}
          <div className="performanceLocalV5ActionRow" data-v5-hero-actions>
            {props.governedContact ? <PhoneAction contact={props.governedContact} label={props.callLabel} /> : null}
            {props.estimateDestination && props.estimateForm?.ctaLabel ? (
              <a className="performanceLocalV5Button performanceLocalV5ButtonSecondary" href={props.estimateDestination}>
                {props.estimateForm.ctaLabel}
              </a>
            ) : null}
          </div>
        </div>
        {heroMediaState !== "omitted" ? (
          <MediaOrDemoSlot
            component={media}
            priority
            reviewMode={props.reviewMode}
            slot="hero"
            targetInstanceKey={component.instance_key}
          />
        ) : null}
      </div>
    </section>
  );
}

function TrustRegion({
  props,
  regionPlan,
}: {
  props: PerformanceLocalV5LayoutBodyProps;
  regionPlan: PerformanceLocalV5RegionPlan | null;
}) {
  const trust = exactComponent(regionPlan, props.componentByInstanceKey, "trust_license");
  if (!trust) return null;
  const media = exactTargetMedia(trust, props.componentByInstanceKey);
  return (
    <section className="performanceLocalV5CredentialBand" data-v5-region="trust" aria-label="Credentials">
      <div className="performanceLocalV5Container">
        <PresenterWithAttachedMedia media={media} props={props} targetInstanceKey={trust.instance_key} compact>
          <TrustFacts component={trust} />
        </PresenterWithAttachedMedia>
      </div>
    </section>
  );
}

function HomeServiceDiscovery({
  props,
  regionPlan,
}: {
  props: PerformanceLocalV5LayoutBodyProps;
  regionPlan: PerformanceLocalV5RegionPlan | null;
}) {
  const presentation = props.homeServicePresentation;
  if (presentation.status !== "ready" || !presentation.services.length) return null;
  const source = presentation.primaryServicesSourceInstanceKey
    ? props.componentByInstanceKey.get(presentation.primaryServicesSourceInstanceKey) ?? null
    : null;
  if (!source) return null;
  const relatedSource = presentation.relatedLinksSourceInstanceKey
    ? props.componentByInstanceKey.get(presentation.relatedLinksSourceInstanceKey) ?? null
    : null;
  const media = relatedSource
    ? exactTargetMedia(relatedSource, props.componentByInstanceKey)
    : exactTargetMedia(source, props.componentByInstanceKey);
  const mode = presentation.mode === "featured" ? "featured" : "grid";
  return (
    <section
      className="performanceLocalV5Section performanceLocalV5Services"
      data-v5-region={regionPlan?.regionKey ?? "service_discovery"}
      data-v5-service-presentation={mode}
    >
      <div className="performanceLocalV5Container">
        <PresenterWithAttachedMedia
          media={media}
          props={props}
          targetInstanceKey={relatedSource?.instance_key ?? source.instance_key}
        >
          <div data-source-instance-key={source.instance_key}>
            {text(source.resolved_data.heading) ? <h2>{text(source.resolved_data.heading)}</h2> : null}
            <div
              className={`performanceLocalV5ServiceEntries performanceLocalV5ServiceEntries-${mode}`}
              data-v5-service-count={presentation.services.length}
            >
              {presentation.services.map((service) => (
                <article
                  key={`${service.sourceItemIndex}-${service.destination.originalLinkIndex}`}
                  className="performanceLocalV5ServiceEntry"
                  data-v5-source-item-index={service.sourceItemIndex}
                  data-v5-destination-link-index={service.destination.originalLinkIndex}
                  data-v5-destination-source-instance-key={service.destination.sourceInstanceKey}
                >
                  <h3>
                    <Link
                      to={props.destinationForGeneratedPageId(service.destination.targetGeneratedPageId)}
                      data-canonical-slug={service.destination.slug}
                    >
                      {service.title}
                    </Link>
                  </h3>
                  <p
                    data-v5-destination-purpose-consumption={
                      service.destination.purpose === service.description
                        ? "deduplicated_exact_description_match"
                        : undefined
                    }
                  >
                    {service.description}
                  </p>
                  {service.destination.purpose && service.destination.purpose !== service.description ? (
                    <p className="performanceLocalV5DestinationPurpose">{service.destination.purpose}</p>
                  ) : null}
                </article>
              ))}
            </div>
          </div>
        </PresenterWithAttachedMedia>
      </div>
    </section>
  );
}

function CountyCityDiscovery({
  cityRegion,
  props,
  relatedRegion,
}: {
  cityRegion: PerformanceLocalV5RegionPlan | null;
  props: PerformanceLocalV5LayoutBodyProps;
  relatedRegion: PerformanceLocalV5RegionPlan | null;
}) {
  const presentation = props.countyCityPresentation;
  if (presentation.status !== "ready" || !presentation.cityEntries.length) return null;
  const cities = presentation.citiesServedSourceInstanceKey
    ? props.componentByInstanceKey.get(presentation.citiesServedSourceInstanceKey) ?? null
    : null;
  const related = presentation.relatedCityServicesSourceInstanceKey
    ? props.componentByInstanceKey.get(presentation.relatedCityServicesSourceInstanceKey) ?? null
    : null;
  if (!cities || !related) return null;
  const media = exactTargetMedia(cities, props.componentByInstanceKey);
  return (
    <section
      className="performanceLocalV5Section performanceLocalV5CountyCities"
      data-v5-region={`${cityRegion?.regionKey ?? "city_discovery"}|${relatedRegion?.regionKey ?? "related_city_discovery"}`}
      data-v5-composition="governed-city-discovery"
    >
      <div className="performanceLocalV5Container">
        <PresenterWithAttachedMedia media={media} props={props} targetInstanceKey={cities.instance_key}>
          <div
            className="performanceLocalV5CountyCityCopy"
            data-v5-source-instance-keys={`${cities.instance_key}|${related.instance_key}|${presentation.destinationCardsSourceInstanceKey ?? ""}`}
          >
            {text(cities.resolved_data.heading) ? <h2>{text(cities.resolved_data.heading)}</h2> : null}
            {text(related.resolved_data.heading) ? <p className="performanceLocalV5SourceSubheading">{text(related.resolved_data.heading)}</p> : null}
            <div className="performanceLocalV5CityGrid" data-v5-destination-count={presentation.cityEntries.length}>
              {presentation.cityEntries.map((entry) => (
                <article
                  key={`${entry.cityIndex}-${entry.originalLinkIndex}`}
                  data-v5-city-index={entry.cityIndex}
                  data-v5-destination-link-index={entry.originalLinkIndex}
                  data-v5-destination-source-instance-key={entry.destination.sourceInstanceKey}
                >
                  <Link
                    to={props.destinationForGeneratedPageId(entry.destination.targetGeneratedPageId)}
                    data-canonical-slug={entry.destination.slug}
                    data-v5-governed-city-name={entry.cityName}
                  >
                    {entry.destination.label}
                  </Link>
                  {entry.destination.purpose ? <p>{entry.destination.purpose}</p> : null}
                </article>
              ))}
            </div>
          </div>
        </PresenterWithAttachedMedia>
      </div>
    </section>
  );
}

function ProjectedDestinationRegion({
  destinations,
  includeMedia = true,
  props,
  regionPlan,
  sourceInstanceKey,
}: {
  destinations: readonly PerformanceLocalV5DestinationConsumptionRecord[];
  includeMedia?: boolean;
  props: PerformanceLocalV5LayoutBodyProps;
  regionPlan: PerformanceLocalV5RegionPlan | null;
  sourceInstanceKey: string | null;
}) {
  if (!destinations.length || !sourceInstanceKey) return null;
  const source = props.componentByInstanceKey.get(sourceInstanceKey) ?? null;
  const media = includeMedia && source ? exactTargetMedia(source, props.componentByInstanceKey) : null;
  return (
    <section className="performanceLocalV5Section performanceLocalV5Related" data-v5-region={regionPlan?.regionKey ?? "related_discovery"}>
      <div className="performanceLocalV5Container">
        <PresenterWithAttachedMedia media={media} props={props} targetInstanceKey={sourceInstanceKey}>
          <DestinationGrid destinations={destinations} destinationForGeneratedPageId={props.destinationForGeneratedPageId} />
        </PresenterWithAttachedMedia>
      </div>
    </section>
  );
}

function AuthorityRegion({
  emphasis,
  props,
  regionPlan,
}: {
  emphasis: "overview" | "process" | "related";
  props: PerformanceLocalV5LayoutBodyProps;
  regionPlan: PerformanceLocalV5RegionPlan | null;
}) {
  if (!renderableRegion(regionPlan, props.componentByInstanceKey)) return null;
  return (
    <section className={`performanceLocalV5Section performanceLocalV5AuthorityRegion performanceLocalV5AuthorityRegion-${emphasis}`} data-v5-region={regionPlan!.regionKey}>
      <div className="performanceLocalV5Container">
        <RegionContents props={props} regionPlan={regionPlan} />
      </div>
    </section>
  );
}

function ContactInformationRegion({
  props,
  regionPlan,
}: {
  props: PerformanceLocalV5LayoutBodyProps;
  regionPlan: PerformanceLocalV5RegionPlan | null;
}) {
  if (!regionPlan || regionPlan.missing) return null;
  const components = regionPlan.sourceInstanceKeys
    .map((key) => props.componentByInstanceKey.get(key))
    .filter((component): component is PageComponentInstance => Boolean(component))
    .filter((component) => component.component_key !== "media_placement" && !isNestedComponent(component.component_key));
  if (!components.length) return null;
  return (
    <section
      className="performanceLocalV5Section performanceLocalV5ContactInformation"
      data-v5-region={regionPlan.regionKey}
      data-v5-composition="contact-information"
    >
      <div className="performanceLocalV5Container performanceLocalV5ContactInformationGrid">
        {components.map((component) => (
          <SourceComponent key={component.instance_key} compact component={component} props={props} />
        ))}
      </div>
    </section>
  );
}

function ComposedAuthorityRegion({
  className,
  props,
  regions,
}: {
  className: string;
  props: PerformanceLocalV5LayoutBodyProps;
  regions: readonly (PerformanceLocalV5RegionPlan | null)[];
}) {
  const available = regions.filter((item): item is PerformanceLocalV5RegionPlan =>
    renderableRegion(item, props.componentByInstanceKey));
  if (!available.length) return null;
  return (
    <section className={`performanceLocalV5Section ${className}`} data-v5-region={available.map((item) => item.regionKey).join("|")}>
      <div className="performanceLocalV5Container performanceLocalV5ComposedGrid">
        {available.map((item) => <RegionContents key={item.regionKey} props={props} regionPlan={item} compact />)}
      </div>
    </section>
  );
}

function DisclosureBodyRegion({
  kind,
  props,
  regionPlan,
}: {
  kind: "guidance";
  props: PerformanceLocalV5LayoutBodyProps;
  regionPlan: PerformanceLocalV5RegionPlan | null;
}) {
  const component = firstContentComponent(regionPlan, props.componentByInstanceKey);
  if (!component) return null;
  const heading = text(component.resolved_data.heading);
  const groups = sourceBodyGroups(sourceBodyBlocks(text(component.resolved_data.body)));
  const media = exactTargetMedia(component, props.componentByInstanceKey);
  return (
    <section className="performanceLocalV5Section performanceLocalV5DisclosureRegion" data-v5-region={regionPlan?.regionKey ?? kind}>
      <div className="performanceLocalV5Container">
        <PresenterWithAttachedMedia media={media} props={props} targetInstanceKey={component.instance_key}>
          <div data-source-instance-key={component.instance_key}>
            {heading ? <h2>{heading}</h2> : null}
            <SourceDisclosureGroups groups={groups} />
          </div>
        </PresenterWithAttachedMedia>
      </div>
    </section>
  );
}

function FaqRegion({
  props,
  regionPlan,
}: {
  props: PerformanceLocalV5LayoutBodyProps;
  regionPlan: PerformanceLocalV5RegionPlan | null;
}) {
  const component = exactComponent(regionPlan, props.componentByInstanceKey, "faq");
  if (!component) return null;
  const items = array(component.resolved_data.items)
    .map(record)
    .filter((item) => text(item.question) && text(item.answer));
  if (!items.length) return null;
  const media = exactTargetMedia(component, props.componentByInstanceKey);
  return (
    <section className="performanceLocalV5Section performanceLocalV5FaqRegion" data-v5-region={regionPlan?.regionKey ?? "faq"}>
      <div className="performanceLocalV5Container">
        <PresenterWithAttachedMedia media={media} props={props} targetInstanceKey={component.instance_key}>
          <div className="performanceLocalV5DisclosureGrid" data-source-instance-key={component.instance_key} data-v5-disclosure-kind="faq">
            {items.map((item, index) => (
              <details key={`${text(item.question)}-${index}`}>
                <summary>{text(item.question)}</summary>
                <div className="performanceLocalV5DisclosureAnswer"><p>{text(item.answer)}</p></div>
              </details>
            ))}
          </div>
        </PresenterWithAttachedMedia>
      </div>
    </section>
  );
}

function SharedFinalConversion({
  compactForm = false,
  props,
  regionPlan,
  supportRegions = [],
}: {
  compactForm?: boolean;
  props: PerformanceLocalV5LayoutBodyProps;
  regionPlan: PerformanceLocalV5RegionPlan | null;
  supportRegions?: readonly (PerformanceLocalV5RegionPlan | null)[];
}) {
  const component = exactComponent(regionPlan, props.componentByInstanceKey, "final_cta");
  if (!component) return null;
  const heading = text(component.resolved_data.heading);
  const body = text(component.resolved_data.body);
  return (
    <section className="performanceLocalV5Final" data-v5-region="final_conversion" data-v5-shared-final-conversion="true">
      <div className="performanceLocalV5Container performanceLocalV5FinalGrid" data-source-instance-key={component.instance_key}>
        <div className="performanceLocalV5FinalCopy">
          {supportRegions.map((support) => (
            <RegionContents key={support?.regionKey ?? "missing"} props={props} regionPlan={support} compact />
          ))}
          {heading ? <h2>{heading}</h2> : null}
          {body ? <p>{body}</p> : null}
          <div className="performanceLocalV5ActionRow">
            {props.governedContact ? <PhoneAction contact={props.governedContact} label={props.callLabel} /> : null}
            {props.estimateDestination && props.estimateForm?.ctaLabel ? (
              <a className="performanceLocalV5Button performanceLocalV5ButtonSecondary" href={props.estimateDestination}>
                {props.estimateForm.ctaLabel}
              </a>
            ) : null}
          </div>
        </div>
        {props.estimateForm ? (
          <ProviderDisabledForm
            compact={compactForm}
            configuration={props.estimateForm}
            onFormFocusRiskChange={props.onFormFocusRiskChange}
          />
        ) : null}
      </div>
    </section>
  );
}

function RegionContents({
  compact = false,
  props,
  regionPlan,
}: {
  compact?: boolean;
  props: PerformanceLocalV5LayoutBodyProps;
  regionPlan: PerformanceLocalV5RegionPlan | null;
}) {
  if (!regionPlan || regionPlan.missing) return null;
  const components = regionPlan.sourceInstanceKeys
    .map((key) => props.componentByInstanceKey.get(key))
    .filter((component): component is PageComponentInstance => Boolean(component))
    .filter((component) => !isNestedComponent(component.component_key) && component.component_key !== "media_placement");
  return <>{components.map((component) => (
    <SourceComponent key={component.instance_key} compact={compact} component={component} props={props} />
  ))}</>;
}

function SourceComponent({
  compact,
  component,
  props,
}: {
  compact: boolean;
  component: PageComponentInstance;
  props: PerformanceLocalV5LayoutBodyProps;
}) {
  const media = exactTargetMedia(component, props.componentByInstanceKey);
  switch (component.component_key) {
    case "trust_license":
      return (
        <PresenterWithAttachedMedia media={media} props={props} targetInstanceKey={component.instance_key} compact={compact}>
          <TrustFacts component={component} />
        </PresenterWithAttachedMedia>
      );
    case "content_section":
    case "service_summary":
      return (
        <PresenterWithAttachedMedia media={media} props={props} targetInstanceKey={component.instance_key} compact={compact}>
          <SourceAuthority component={component} compact={compact} />
        </PresenterWithAttachedMedia>
      );
    case "destination_cards":
    case "related_page_links":
      return (
        <PresenterWithAttachedMedia media={media} props={props} targetInstanceKey={component.instance_key} compact={compact}>
          <RawDestinationGrid component={component} destinationForGeneratedPageId={props.destinationForGeneratedPageId} />
        </PresenterWithAttachedMedia>
      );
    case "faq":
      return null;
    case "contact_pathways":
      return (
        <PresenterWithAttachedMedia media={media} props={props} targetInstanceKey={component.instance_key} compact={compact}>
          <ContactPathways component={component} governedContact={props.governedContact} />
        </PresenterWithAttachedMedia>
      );
    case "final_cta":
      return null;
    default:
      return (
        <aside className="performanceLocalV5SourceBlocker" role="alert" data-v5-unhandled-component={component.component_key} data-source-instance-key={component.instance_key}>
          Source component {component.instance_key} has no V5 presenter.
        </aside>
      );
  }
}

function SourceAuthority({
  compact,
  component,
}: {
  compact: boolean;
  component: PageComponentInstance;
}) {
  const heading = text(component.resolved_data.heading);
  const body = text(component.resolved_data.body);
  const steps = array(component.resolved_data.steps).map(record).map((step) => ({
    heading: text(step.heading) || text(step.title) || text(step.label),
    body: text(step.body) || text(step.description),
  })).filter((step) => step.heading || step.body);
  if (!heading && !body && !steps.length) return null;
  return (
    <article className={`performanceLocalV5Authority${compact ? " performanceLocalV5AuthorityCompact" : ""}`} data-source-instance-key={component.instance_key}>
      {heading ? <h2>{heading}</h2> : null}
      {body ? <SourceStructuredBody body={body} /> : null}
      {steps.length ? (
        <ol className="performanceLocalV5Process">
          {steps.map((step, index) => (
            <li key={`${step.heading}-${index}`}>
              <span aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
              <div>{step.heading ? <strong>{step.heading}</strong> : null}{step.body ? <p>{step.body}</p> : null}</div>
            </li>
          ))}
        </ol>
      ) : null}
    </article>
  );
}

function SourceStructuredBody({ body }: { body: string }) {
  const groups = sourceBodyGroups(sourceBodyBlocks(body));
  return (
    <div className="performanceLocalV5StructuredBody" data-v5-structured-group-count={groups.length}>
      {groups.map((group, groupIndex) => {
        const content = <SourceBlocks blocks={group.blocks} />;
        return group.heading ? (
          <section key={`section-${groupIndex}`} className="performanceLocalV5SourceSection">
            <h3>{group.heading}</h3>
            {content}
          </section>
        ) : <div key={`flow-${groupIndex}`} className="performanceLocalV5SourceFlow">{content}</div>;
      })}
    </div>
  );
}

function SourceDisclosureGroups({ groups }: { groups: readonly SourceBodyGroup[] }) {
  return (
    <div className="performanceLocalV5DisclosureGrid" data-v5-disclosure-kind="guidance">
      {groups.map((group, index) => group.heading ? (
        <details key={`${group.heading}-${index}`}>
          <summary>{group.heading}</summary>
          <div className="performanceLocalV5DisclosureAnswer"><SourceBlocks blocks={group.blocks} /></div>
        </details>
      ) : (
        <div className="performanceLocalV5DisclosurePrelude" key={`prelude-${index}`}>
          <SourceBlocks blocks={group.blocks} />
        </div>
      ))}
    </div>
  );
}

function SourceBlocks({ blocks }: { blocks: SourceBodyGroup["blocks"] }) {
  return <>{blocks.map((block, blockIndex) => block.kind === "list" ? (
    <ul key={`list-${blockIndex}`}>{block.items.map((item, itemIndex) => <li key={`${blockIndex}-${itemIndex}`}>{item}</li>)}</ul>
  ) : <p key={`paragraph-${blockIndex}`}>{block.value}</p>)}</>;
}

function DestinationGrid({
  destinationForGeneratedPageId,
  destinations,
}: {
  destinationForGeneratedPageId: (generatedPageId: number) => string;
  destinations: readonly PerformanceLocalV5DestinationConsumptionRecord[];
}) {
  if (!destinations.length) return null;
  return (
    <div className="performanceLocalV5DestinationGrid" data-v5-destination-count={destinations.length}>
      {destinations.map((destination) => (
        <article
          key={`${destination.sourceInstanceKey}-${destination.originalLinkIndex}`}
          data-v5-destination-source-instance-key={destination.sourceInstanceKey}
          data-v5-destination-link-index={destination.originalLinkIndex}
          data-v5-presentation-slot={destination.presentationSlot}
        >
          <h2>
            <Link to={destinationForGeneratedPageId(destination.targetGeneratedPageId)} data-canonical-slug={destination.slug}>
              {destination.label}
            </Link>
          </h2>
          {destination.purpose ? <p>{destination.purpose}</p> : null}
        </article>
      ))}
    </div>
  );
}

function RawDestinationGrid({
  component,
  destinationForGeneratedPageId,
}: {
  component: PageComponentInstance;
  destinationForGeneratedPageId: (generatedPageId: number) => string;
}) {
  const links = array(component.resolved_data.links).map(record).filter((link) => text(link.label));
  if (!links.length) return null;
  return (
    <div
      className="performanceLocalV5DestinationGrid"
      data-source-instance-key={component.instance_key}
      data-v5-destination-count={links.length}
    >
      {links.map((link, index) => {
        const generatedPageId = positiveInteger(link.target_generated_page_id);
        const stableKey = positiveInteger(link.target_planned_page_id) ?? text(link.slug) ?? index;
        return (
          <article key={stableKey} data-v5-destination-link-index={index}>
            <h2>{generatedPageId ? (
              <Link to={destinationForGeneratedPageId(generatedPageId)} data-canonical-slug={text(link.slug)}>{text(link.label)}</Link>
            ) : <span>{text(link.label)}</span>}</h2>
            {text(link.purpose) ? <p>{text(link.purpose)}</p> : null}
          </article>
        );
      })}
    </div>
  );
}

function PresenterWithAttachedMedia({
  children,
  compact = false,
  media,
  props,
  targetInstanceKey,
}: {
  children: ReactNode;
  compact?: boolean;
  media: PageComponentInstance | null;
  props: PerformanceLocalV5LayoutBodyProps;
  targetInstanceKey: string;
}) {
  if (!media || (props.reviewMode === "truthful" && !renderableMedia(media))) return children;
  return (
    <div className={`performanceLocalV5AttachedGrid${compact ? " performanceLocalV5AttachedGridCompact" : ""}`} data-v5-attached-media-target={targetInstanceKey}>
      <div>{children}</div>
      <MediaOrDemoSlot component={media} reviewMode={props.reviewMode} slot="supporting" targetInstanceKey={targetInstanceKey} />
    </div>
  );
}

function MediaOrDemoSlot({
  component,
  priority = false,
  reviewMode,
  slot,
  targetInstanceKey,
}: {
  component: PageComponentInstance | null;
  priority?: boolean;
  reviewMode: PerformanceLocalV5ReviewMode;
  slot: "hero" | "supporting";
  targetInstanceKey: string;
}) {
  const media = component ? renderableMedia(component) : null;
  if (media) {
    return (
      <figure
        className={`performanceLocalV5Media performanceLocalV5Media-${media.preset.replace(/_/g, "-")}`}
        data-source-instance-key={component!.instance_key}
        data-semantic-media-role={media.role}
        data-effective-display-preset={media.preset}
      >
        <div className="performanceLocalV5MediaFrame">
          <img
            src={media.source}
            alt={media.alt}
            title={media.title || undefined}
            decoding="async"
            loading={priority ? "eager" : "lazy"}
            style={{ objectPosition: `${media.focalX * 100}% ${media.focalY * 100}%` }}
          />
        </div>
        {media.caption ? <figcaption>{media.caption}</figcaption> : null}
      </figure>
    );
  }
  if (reviewMode !== "structural_demo" || !component) return null;
  return (
    <div
      className={`performanceLocalV5DemoMedia performanceLocalV5DemoMedia-${slot}`}
      role="img"
      aria-label={PERFORMANCE_LOCAL_V5_DEMO_MEDIA_LABEL}
      data-source-instance-key={component.instance_key}
      data-v5-demo-media-slot={slot}
      data-v5-demo-target-instance-key={targetInstanceKey}
    >
      <span>{PERFORMANCE_LOCAL_V5_DEMO_MEDIA_LABEL}</span>
    </div>
  );
}

function TrustFacts({ component }: { component: PageComponentInstance }) {
  const facts = [
    text(component.resolved_data.license_number) ? { label: "License", value: text(component.resolved_data.license_number) } : null,
    text(component.resolved_data.certified_operator) ? { label: "Certified operator", value: text(component.resolved_data.certified_operator) } : null,
  ].filter((item): item is { label: string; value: string } => Boolean(item));
  if (!facts.length) return null;
  return (
    <div className="performanceLocalV5TrustGrid" data-source-instance-key={component.instance_key}>
      {facts.map((fact) => (
        <article key={fact.label}><ShieldCheck aria-hidden="true" /><span>{fact.label}</span><strong>{fact.value}</strong></article>
      ))}
    </div>
  );
}

function ContactPathways({
  component,
  governedContact,
}: {
  component: PageComponentInstance;
  governedContact: PerformanceLocalGovernedContact | null;
}) {
  const email = safeEmail(component.resolved_data.email);
  if (!governedContact && !email) return null;
  return (
    <div className="performanceLocalV5ContactActions" data-source-instance-key={component.instance_key}>
      {governedContact ? <PhoneAction contact={governedContact} /> : null}
      {email ? <a className="performanceLocalV5Email" href={`mailto:${email}`}><Mail aria-hidden="true" /><span>{email}</span></a> : null}
    </div>
  );
}

function PhoneAction({
  contact,
  label,
}: {
  contact: PerformanceLocalGovernedContact;
  label?: string;
}) {
  return (
    <a className="performanceLocalV5Button" href={contact.callDestination}>
      <Phone aria-hidden="true" /><span>{label || contact.phoneDisplay}</span>
    </a>
  );
}

function ProviderDisabledForm({
  compact,
  configuration,
  onFormFocusRiskChange,
}: {
  compact: boolean;
  configuration: PerformanceLocalEstimateFormConfiguration;
  onFormFocusRiskChange: (focused: boolean) => void;
}) {
  function preventSubmission(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
  }
  return (
    <form
      id={performanceLocalFormDomId(configuration.componentConfigurationId)}
      className={`performanceLocalV5Form${compact ? " performanceLocalV5FormCompact" : ""}`}
      aria-label="Estimate request preview"
      autoComplete="off"
      data-preview-only="true"
      data-provider-state={configuration.providerState.submissionState}
      data-provider-configured="false"
      data-collects-data="false"
      data-controls-read-only="true"
      data-v5-default-field-count={configuration.fields.length}
      data-v5-maximum-field-count="6"
      onSubmit={preventSubmission}
      onFocusCapture={() => onFormFocusRiskChange(true)}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) onFormFocusRiskChange(false);
      }}
    >
      <p className="performanceLocalV5FormNotice">{configuration.previewNotice}</p>
      <div className="performanceLocalV5FormGrid">
        {[...configuration.fields].sort((left, right) => left.order - right.order).map((field) => (
          <label key={field.key} className={field.responsive.desktop === "full" ? "performanceLocalV5FormFieldFull" : undefined}>
            <span>{field.label}</span>
            {field.control === "textarea" ? (
              <textarea
                aria-label={field.accessibilityLabel}
                autoComplete="off"
                data-field-key={field.key}
                data-field-order={field.order}
                data-field-responsive={`${field.responsive.desktop}:${field.responsive.tablet}:${field.responsive.mobile}`}
                data-provider-mapping={field.providerMapping}
                maxLength={field.maxLength}
                readOnly
                required={field.required}
                rows={field.rows}
              />
            ) : (
              <input
                aria-label={field.accessibilityLabel}
                autoComplete="off"
                data-field-key={field.key}
                data-field-order={field.order}
                data-field-responsive={`${field.responsive.desktop}:${field.responsive.tablet}:${field.responsive.mobile}`}
                data-provider-mapping={field.providerMapping}
                inputMode={field.inputMode}
                maxLength={field.maxLength}
                readOnly
                required={field.required}
                type={field.type}
              />
            )}
          </label>
        ))}
      </div>
      <button type="submit" disabled>{configuration.submitLabel}</button>
    </form>
  );
}

export function PerformanceLocalV5CampaignBanner({ campaign }: { campaign: PerformanceLocalCampaign }) {
  const singleAction = campaign.intent === "evergreen_conversion" &&
    performanceLocalActionCopyEquivalent(campaign.campaignLabel, campaign.ctaLabel);
  return (
    <aside
      className={`performanceLocalV5Campaign${singleAction ? " performanceLocalV5CampaignSingle" : ""}`}
      aria-label={campaign.campaignLabel}
      data-conversion-intent={campaign.intent}
      data-public-action-copy={singleAction ? "semantic_duplicate_suppressed" : "distinct_copy_and_action"}
    >
      {singleAction ? (
        <a href={campaign.ctaDestination}><strong>{campaign.campaignLabel}</strong></a>
      ) : (
        <div className="performanceLocalV5Container performanceLocalV5CampaignInner">
          <p>
            <strong>{campaign.campaignLabel}</strong>
            {campaign.price ? <span>{campaign.price}</span> : null}
            {campaign.qualifier ? <span>{campaign.qualifier}</span> : null}
          </p>
          <a href={campaign.ctaDestination}>{campaign.ctaLabel}</a>
        </div>
      )}
    </aside>
  );
}

export function PerformanceLocalV5TopConversionStack({
  action,
  callLabel,
  contact,
}: {
  action: PerformanceLocalV5TopAction;
  callLabel: string;
  contact: PerformanceLocalGovernedContact | null;
}) {
  const resolvedAction = action.mode !== "disabled" && action.destination.trim() && action.label.trim()
    ? action
    : null;
  if (!contact && !resolvedAction) return null;
  return (
    <div
      className="performanceLocalV5TopConversionStack"
      data-v5-top-conversion-stack="true"
      data-v5-top-action-mode={action.mode}
      data-v5-top-action-enabled={resolvedAction ? "true" : "false"}
    >
      {contact ? (
        <div className="performanceLocalV5StickyPhoneBar">
          <a href={contact.callDestination} aria-label={`${callLabel} ${contact.phoneDisplay}`}>
            <Phone aria-hidden="true" />
            <span>{callLabel} <strong>{contact.phoneDisplay}</strong></span>
          </a>
        </div>
      ) : null}
      {resolvedAction ? (
        <aside className="performanceLocalV5StickyActionBanner" aria-label={resolvedAction.label}>
          <a href={resolvedAction.destination}>{resolvedAction.label}</a>
        </aside>
      ) : null}
    </div>
  );
}

export function PerformanceLocalV5SiteHeader({
  component,
  contact,
  destinationForGeneratedPageId,
  estimateDestination,
  estimateLabel,
  menuOpen,
  onMenuOpenChange,
  primaryNavigation,
  utilityNavigation,
}: {
  component: PageComponentInstance;
  contact: PerformanceLocalGovernedContact | null;
  destinationForGeneratedPageId: (generatedPageId: number) => string;
  estimateDestination: string | null;
  estimateLabel: string;
  menuOpen: boolean;
  onMenuOpenChange: (open: boolean) => void;
  primaryNavigation: PageComponentInstance | null;
  utilityNavigation: PageComponentInstance | null;
}) {
  const triggerRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLDivElement>(null);
  const data = component.resolved_data;
  const displayName = text(data.display_name) || text(data.company_name);
  const navigation = navigationNodes(primaryNavigation, utilityNavigation);

  function closeMenu({ restoreFocus }: { restoreFocus: boolean }) {
    onMenuOpenChange(false);
    if (restoreFocus) window.setTimeout(() => triggerRef.current?.focus(), 0);
  }

  useEffect(() => {
    if (!menuOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    focusableElements(drawerRef.current)[0]?.focus();
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        closeMenu({ restoreFocus: true });
        return;
      }
      if (event.key !== "Tab") return;
      const values = focusableElements(drawerRef.current);
      if (!values.length) return;
      const first = values[0];
      const last = values[values.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [menuOpen, onMenuOpenChange]);

  return (
    <header
      className="performanceLocalV5Header"
      data-source-instance-key={component.instance_key}
      data-v5-menu-open={menuOpen ? "true" : "false"}
    >
      <div className="performanceLocalV5Container performanceLocalV5HeaderInner">
        <div className="performanceLocalV5Brand" aria-label={displayName}>
          <BrandIdentity data={data} displayName={displayName} slot="header_logo" />
          <span>
            <strong>{displayName}</strong>
            {text(data.tagline) ? <small>{text(data.tagline)}</small> : null}
          </span>
        </div>
        {navigation.length ? (
          <nav
            className="performanceLocalV5DesktopNav"
            aria-label="Website navigation"
            data-v5-navigation-source-instance-keys={navigationSourceKeys(primaryNavigation, utilityNavigation)}
          >
            <NavigationList nodes={navigation} destinationForGeneratedPageId={destinationForGeneratedPageId} />
          </nav>
        ) : null}
        <div className="performanceLocalV5HeaderActions">
          {contact ? <PhoneAction contact={contact} /> : null}
          {estimateDestination && estimateLabel ? (
            <a className="performanceLocalV5Button performanceLocalV5ButtonSecondary" href={estimateDestination}>{estimateLabel}</a>
          ) : null}
        </div>
        <button
          ref={triggerRef}
          className="performanceLocalV5MenuTrigger"
          type="button"
          aria-controls="performance-local-v5-mobile-menu"
          aria-expanded={menuOpen}
          aria-label={menuOpen ? "Close website navigation" : "Open website navigation"}
          onClick={() => menuOpen ? closeMenu({ restoreFocus: true }) : onMenuOpenChange(true)}
        >
          {menuOpen ? <X aria-hidden="true" /> : <Menu aria-hidden="true" />}
        </button>
      </div>
      {menuOpen ? (
        <div className="performanceLocalV5DrawerBackdrop" onMouseDown={(event) => {
          if (event.target === event.currentTarget) closeMenu({ restoreFocus: true });
        }}>
          <div
            id="performance-local-v5-mobile-menu"
            ref={drawerRef}
            className="performanceLocalV5Drawer"
            role="dialog"
            aria-modal="true"
            aria-label="Website navigation"
          >
            <button type="button" onClick={() => closeMenu({ restoreFocus: true })} aria-label="Close website navigation"><X aria-hidden="true" /></button>
            <nav aria-label="Mobile website navigation">
              <NavigationList
                nodes={navigation}
                destinationForGeneratedPageId={destinationForGeneratedPageId}
                onNavigate={() => closeMenu({ restoreFocus: false })}
              />
            </nav>
          </div>
        </div>
      ) : null}
    </header>
  );
}

export function PerformanceLocalV5SiteFooter({
  component,
  contact,
  destinationForGeneratedPageId,
  navigation,
}: {
  component: PageComponentInstance;
  contact: PerformanceLocalGovernedContact | null;
  destinationForGeneratedPageId: (generatedPageId: number) => string;
  navigation: PageComponentInstance | null;
}) {
  const data = component.resolved_data;
  const displayName = text(data.company_name) || text(data.display_name);
  const nodes = navigationNodes(navigation, null);
  const email = safeEmail(data.email);
  return (
    <footer className="performanceLocalV5Footer" data-source-instance-key={component.instance_key}>
      <div className="performanceLocalV5Container performanceLocalV5FooterGrid">
        <div className="performanceLocalV5FooterBrand">
          <BrandIdentity data={data} displayName={displayName} slot="footer_logo" />
          <strong>{displayName}</strong>
          {text(data.business_type) ? <span>{text(data.business_type)}</span> : null}
        </div>
        {nodes.length ? (
          <nav
            aria-label={text(navigation?.resolved_data.label) || "Footer navigation"}
            data-source-instance-key={navigation?.instance_key}
            data-v5-consumption-mode="nested_navigation"
          >
            <NavigationList nodes={nodes} destinationForGeneratedPageId={destinationForGeneratedPageId} />
          </nav>
        ) : null}
        <div className="performanceLocalV5FooterContact">
          {contact ? <PhoneAction contact={contact} /> : null}
          {email ? <a className="performanceLocalV5Email" href={`mailto:${email}`}><Mail aria-hidden="true" /><span>{email}</span></a> : null}
          {text(data.license_number) ? <span>License {text(data.license_number)}</span> : null}
        </div>
      </div>
    </footer>
  );
}

export function PerformanceLocalV5StickyActions({
  callLabel,
  contact,
  estimateDestination,
  estimateLabel,
}: {
  callLabel: string;
  contact: PerformanceLocalGovernedContact | null;
  estimateDestination: string | null;
  estimateLabel: string;
}) {
  if (!contact && !estimateDestination) return null;
  return (
    <aside className="performanceLocalV5StickyActions" aria-label="Contact actions">
      {contact ? <PhoneAction contact={contact} label={callLabel} /> : null}
      {estimateDestination ? <a className="performanceLocalV5Button performanceLocalV5ButtonSecondary" href={estimateDestination}>{estimateLabel}</a> : null}
    </aside>
  );
}

export function PerformanceLocalV5BackToTop({ suppressed }: { suppressed: boolean }) {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    function update() {
      setVisible(window.scrollY >= Math.max(480, window.innerHeight * 0.75));
    }
    update();
    window.addEventListener("scroll", update, { passive: true });
    return () => window.removeEventListener("scroll", update);
  }, []);
  if (!visible || suppressed) return null;
  return (
    <button
      className="performanceLocalV5BackToTop"
      type="button"
      aria-label="Back to top"
      onClick={() => window.scrollTo({
        top: 0,
        behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
      })}
    >
      <ArrowUp aria-hidden="true" />
    </button>
  );
}

function BrandIdentity({
  data,
  displayName,
  slot,
}: {
  data: Record<string, unknown>;
  displayName: string;
  slot: "header_logo" | "footer_logo";
}) {
  const asset = record(record(data.identity_assets)[slot]);
  const source = text(asset.asset_url);
  const alt = text(asset.accessibility_description);
  if (source && alt && safeLocalAssetUrl(source)) return <img className="performanceLocalV5Logo" src={source} alt={alt} />;
  if (slot === "footer_logo") return null;
  return <span className="performanceLocalV5BrandMark" aria-hidden="true">{initials(displayName)}</span>;
}

function navigationNodes(
  primary: PageComponentInstance | null,
  utility: PageComponentInstance | null,
): ResolvedNavigationItem[] {
  const primaryTree = primary ? buildNavigationTree(array(primary.resolved_data.items)) : { nodes: [], error: null };
  if (primaryTree.error) return [];
  const utilityTree = utility ? buildNavigationTree(array(utility.resolved_data.items)) : { nodes: [], error: null };
  if (utilityTree.error) return [];
  const seenTargets = new Set<number>();
  return [
    ...deduplicateNavigation(primaryTree.nodes, seenTargets),
    ...deduplicateNavigation(utilityTree.nodes, seenTargets),
  ];
}

function deduplicateNavigation(
  nodes: readonly ResolvedNavigationItem[],
  seenTargets: Set<number>,
): ResolvedNavigationItem[] {
  const result: ResolvedNavigationItem[] = [];
  for (const node of nodes) {
    if (seenTargets.has(node.targetPlannedPageId)) continue;
    seenTargets.add(node.targetPlannedPageId);
    result.push({ ...node, children: deduplicateNavigation(node.children, seenTargets) });
  }
  return result;
}

function navigationSourceKeys(
  primary: PageComponentInstance | null,
  utility: PageComponentInstance | null,
): string | undefined {
  const keys = [primary?.instance_key, utility?.instance_key].filter((value): value is string => Boolean(value));
  return keys.length ? keys.join("|") : undefined;
}

function NavigationList({
  destinationForGeneratedPageId,
  nodes,
  onNavigate,
}: {
  destinationForGeneratedPageId: (generatedPageId: number) => string;
  nodes: readonly ResolvedNavigationItem[];
  onNavigate?: () => void;
}) {
  const navigationId = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  return (
    <ul>
      {nodes.map((node) => (
        <NavigationBranch
          key={node.navigationItemId}
          node={node}
          submenuId={`performance-local-v5-submenu-${navigationId}-${node.navigationItemId}`}
          destinationForGeneratedPageId={destinationForGeneratedPageId}
          onNavigate={onNavigate}
        />
      ))}
    </ul>
  );
}

function NavigationBranch({
  destinationForGeneratedPageId,
  node,
  onNavigate,
  submenuId,
}: {
  destinationForGeneratedPageId: (generatedPageId: number) => string;
  node: ResolvedNavigationItem;
  onNavigate?: () => void;
  submenuId: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const destination = node.targetGeneratedPageId ? (
    <Link to={destinationForGeneratedPageId(node.targetGeneratedPageId)} data-canonical-slug={node.canonicalSlug} onClick={onNavigate}>{node.label}</Link>
  ) : <span aria-disabled="true">{node.label}</span>;
  if (!node.children.length) return <li>{destination}</li>;
  return (
    <li className="performanceLocalV5NavigationBranch">
      <div className="performanceLocalV5NavigationParent">
        {destination}
        <button
          ref={triggerRef}
          className="performanceLocalV5NavigationToggle"
          type="button"
          aria-label={`Toggle ${node.label} submenu`}
          aria-expanded={expanded}
          aria-controls={submenuId}
          onClick={() => setExpanded((current) => !current)}
          onKeyDown={(event) => {
            if (event.key !== "Escape" || !expanded) return;
            event.preventDefault();
            event.stopPropagation();
            setExpanded(false);
            triggerRef.current?.focus();
          }}
        >
          <ChevronDown aria-hidden="true" />
        </button>
      </div>
      <ul
        id={submenuId}
        hidden={!expanded}
        onKeyDown={(event) => {
          if (event.key !== "Escape" || !expanded) return;
          event.preventDefault();
          event.stopPropagation();
          setExpanded(false);
          triggerRef.current?.focus();
        }}
      >
        {node.children.map((child) => (
          <NavigationBranch
            key={child.navigationItemId}
            node={child}
            submenuId={`${submenuId}-${child.navigationItemId}`}
            destinationForGeneratedPageId={destinationForGeneratedPageId}
            onNavigate={onNavigate}
          />
        ))}
      </ul>
    </li>
  );
}

function focusableElements(root: HTMLElement | null): HTMLElement[] {
  if (!root) return [];
  return Array.from(root.querySelectorAll<HTMLElement>(
    'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), details > summary, [tabindex]:not([tabindex="-1"])',
  )).filter((element) => !element.closest('[hidden], [aria-hidden="true"], [inert]'));
}

function initials(value: string): string {
  const words = value.split(/\s+/).filter(Boolean).slice(0, 2);
  return words.map((word) => word[0]?.toUpperCase()).join("") || "A";
}

function region(props: PerformanceLocalV5LayoutBodyProps, key: string): PerformanceLocalV5RegionPlan | null {
  return props.regions.find((item) => item.regionKey === key) ?? null;
}

function renderableRegion(
  regionPlan: PerformanceLocalV5RegionPlan | null,
  components: ReadonlyMap<string, PageComponentInstance>,
): boolean {
  return Boolean(regionPlan && !regionPlan.missing && regionPlan.sourceInstanceKeys.some((key) => {
    const component = components.get(key);
    return component && component.component_key !== "media_placement" && !isNestedComponent(component.component_key);
  }));
}

function exactComponent(
  regionPlan: PerformanceLocalV5RegionPlan | null,
  components: ReadonlyMap<string, PageComponentInstance>,
  componentKey: string,
): PageComponentInstance | null {
  if (!regionPlan || regionPlan.missing) return null;
  const matches = regionPlan.sourceInstanceKeys
    .map((key) => components.get(key))
    .filter((component): component is PageComponentInstance => component?.component_key === componentKey);
  return matches.length === 1 ? matches[0] : null;
}

function firstContentComponent(
  regionPlan: PerformanceLocalV5RegionPlan | null,
  components: ReadonlyMap<string, PageComponentInstance>,
): PageComponentInstance | null {
  if (!regionPlan || regionPlan.missing) return null;
  return regionPlan.sourceInstanceKeys
    .map((key) => components.get(key))
    .find((component) => component?.component_key === "content_section" || component?.component_key === "service_summary") ?? null;
}

function exactTargetMedia(
  target: PageComponentInstance,
  components: ReadonlyMap<string, PageComponentInstance>,
): PageComponentInstance | null {
  const matches = [...components.values()].filter((component) =>
    component.component_key === "media_placement" &&
    text(component.input_bindings.target_component_instance_key) === target.instance_key,
  );
  return matches.length === 1 ? matches[0] : null;
}

type RenderableMedia = Readonly<{
  alt: string;
  caption: string;
  focalX: number;
  focalY: number;
  preset: PageMediaDisplayPreset;
  role: string;
  source: string;
  title: string;
}>;

function renderableMedia(component: PageComponentInstance): RenderableMedia | null {
  const data = component.resolved_data;
  const source = text(data.asset_url);
  const alt = text(data.alt_text);
  if (!source || !alt || !safeLocalAssetUrl(source)) return null;
  const preset = resolvePageMediaDisplayPreset(data, component.input_bindings);
  if (preset.error || !preset.preset) return null;
  return {
    alt,
    caption: text(data.caption),
    focalX: boundedNumber(data.focal_x, 0.5),
    focalY: boundedNumber(data.focal_y, 0.5),
    preset: preset.preset,
    role: text(data.image_role),
    source,
    title: text(data.image_title),
  };
}

function isNestedComponent(componentKey: string): boolean {
  return ["website_header", "primary_navigation", "utility_navigation", "footer_navigation", "website_footer"].includes(componentKey);
}

function safeLocalAssetUrl(value: string): boolean {
  if (!value || /[\u0000-\u001f\u007f\\]/.test(value)) return false;
  if (value.startsWith("/")) return !value.startsWith("//");
  try {
    const parsed = new URL(value);
    return (parsed.protocol === "http:" || parsed.protocol === "https:") &&
      !parsed.username && !parsed.password && ["localhost", "127.0.0.1", "[::1]"].includes(parsed.hostname);
  } catch {
    return false;
  }
}

function safeEmail(value: unknown): string | null {
  const email = text(value);
  return email && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) ? email : null;
}

type SourceBodyBlock =
  | Readonly<{ kind: "heading"; value: string }>
  | Readonly<{ kind: "paragraph"; value: string }>
  | Readonly<{ kind: "list"; items: readonly string[] }>;

type SourceBodyGroup = Readonly<{
  heading: string | null;
  blocks: readonly Exclude<SourceBodyBlock, { kind: "heading" }>[];
}>;

function sourceBodyGroups(blocks: readonly SourceBodyBlock[]): SourceBodyGroup[] {
  const groups: Array<{ heading: string | null; blocks: Array<Exclude<SourceBodyBlock, { kind: "heading" }>> }> = [];
  for (const block of blocks) {
    if (block.kind === "heading") {
      groups.push({ heading: block.value, blocks: [] });
      continue;
    }
    const current = groups.length ? groups[groups.length - 1] : undefined;
    if (!current || (current.heading === null && current.blocks.length > 0)) groups.push({ heading: null, blocks: [block] });
    else current.blocks.push(block);
  }
  return groups;
}

function sourceBodyBlocks(value: string): SourceBodyBlock[] {
  if (!value) return [];
  const result: SourceBodyBlock[] = [];
  let paragraph: string[] = [];
  let list: string[] = [];
  const flushParagraph = () => {
    if (!paragraph.length) return;
    result.push({ kind: "paragraph", value: paragraph.join(" ") });
    paragraph = [];
  };
  const flushList = () => {
    if (!list.length) return;
    result.push({ kind: "list", items: list });
    list = [];
  };
  for (const rawLine of value.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) {
      flushParagraph();
      flushList();
      continue;
    }
    const heading = /^###\s+(.+)$/.exec(line);
    if (heading) {
      flushParagraph();
      flushList();
      result.push({ kind: "heading", value: heading[1].trim() });
      continue;
    }
    const listItem = /^-\s+(.+)$/.exec(line);
    if (listItem) {
      flushParagraph();
      list.push(listItem[1].trim());
      continue;
    }
    flushList();
    paragraph.push(line);
  }
  flushParagraph();
  flushList();
  return result;
}

function boundedNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : fallback;
}

function positiveInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0 ? value : null;
}

function array(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function text(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value).trim() : "";
}
