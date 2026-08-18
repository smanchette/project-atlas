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
  type RefObject,
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
  PERFORMANCE_LOCAL_V4_DEMO_MEDIA_LABEL,
} from "./performanceLocalThemeV4";
import {
  PERFORMANCE_LOCAL_V4_COUNTY_RELATED_CITY_GROUP_KEY,
} from "./performanceLocalV4LayoutContract";
import {
  buildNavigationTree,
  resolvePageMediaDisplayPreset,
  type ResolvedNavigationItem,
} from "../pages/GeneratedPagePreview";
import type {
  PageComponentInstance,
  PageMediaDisplayPreset,
} from "../types";

export type PerformanceLocalV4ReviewMode = "truthful" | "structural_demo";

export type PerformanceLocalV4RegionPlan = Readonly<{
  regionKey: string;
  requirement: "required" | "optional";
  sourceInstanceKeys: readonly string[];
  presentationGroups: readonly Readonly<{
    groupKey: string;
    sourceInstanceKeys: readonly string[];
  }>[];
  missing: boolean;
}>;

export type PerformanceLocalV4LayoutBodyProps = Readonly<{
  componentByInstanceKey: ReadonlyMap<string, PageComponentInstance>;
  destinationForGeneratedPageId: (generatedPageId: number) => string;
  estimateDestination: string | null;
  estimateForm: PerformanceLocalEstimateFormConfiguration | null;
  governedContact: PerformanceLocalGovernedContact | null;
  layoutKey: string;
  onFormFocusRiskChange: (focused: boolean) => void;
  pageType: "home" | "service" | "county" | "about" | "contact" | "faq";
  regions: readonly PerformanceLocalV4RegionPlan[];
  reviewMode: PerformanceLocalV4ReviewMode;
}>;

export function PerformanceLocalV4LayoutBody(props: PerformanceLocalV4LayoutBodyProps) {
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

function HomeLayout(props: PerformanceLocalV4LayoutBodyProps) {
  return <LayoutRegions {...props} layoutClass="performanceLocalV4LayoutHome" />;
}

function ServiceLayout(props: PerformanceLocalV4LayoutBodyProps) {
  return <LayoutRegions {...props} layoutClass="performanceLocalV4LayoutService" />;
}

function ServiceCountyLayout(props: PerformanceLocalV4LayoutBodyProps) {
  return <LayoutRegions {...props} layoutClass="performanceLocalV4LayoutCounty" />;
}

function AboutLayout(props: PerformanceLocalV4LayoutBodyProps) {
  return <LayoutRegions {...props} layoutClass="performanceLocalV4LayoutAbout" />;
}

function ContactLayout(props: PerformanceLocalV4LayoutBodyProps) {
  return <LayoutRegions {...props} layoutClass="performanceLocalV4LayoutContact" />;
}

function FaqLayout(props: PerformanceLocalV4LayoutBodyProps) {
  return <LayoutRegions {...props} layoutClass="performanceLocalV4LayoutFaq" />;
}

function LayoutRegions({
  componentByInstanceKey,
  destinationForGeneratedPageId,
  estimateDestination,
  estimateForm,
  governedContact,
  layoutClass,
  layoutKey,
  onFormFocusRiskChange,
  pageType,
  regions,
  reviewMode,
}: PerformanceLocalV4LayoutBodyProps & { layoutClass: string }) {
  return (
    <div
      className={`performanceLocalV4Layout ${layoutClass}`}
      data-v4-layout-key={layoutKey}
      data-v4-page-type={pageType}
    >
      {regions.map((region) => (
        <LayoutRegion
          key={region.regionKey}
          region={region}
          componentByInstanceKey={componentByInstanceKey}
          destinationForGeneratedPageId={destinationForGeneratedPageId}
          estimateDestination={estimateDestination}
          estimateForm={estimateForm}
          governedContact={governedContact}
          onFormFocusRiskChange={onFormFocusRiskChange}
          reviewMode={reviewMode}
        />
      ))}
    </div>
  );
}

function LayoutRegion({
  componentByInstanceKey,
  destinationForGeneratedPageId,
  estimateDestination,
  estimateForm,
  governedContact,
  onFormFocusRiskChange,
  region,
  reviewMode,
}: Omit<PerformanceLocalV4LayoutBodyProps, "layoutKey" | "pageType" | "regions"> & {
  region: PerformanceLocalV4RegionPlan;
}) {
  if (region.missing) return null;
  const groupsByFirst = new Map<string, PerformanceLocalV4RegionPlan["presentationGroups"][number]>();
  const groupedKeys = new Set<string>();
  for (const group of region.presentationGroups) {
    if (!group.sourceInstanceKeys.length) continue;
    groupsByFirst.set(group.sourceInstanceKeys[0], group);
    group.sourceInstanceKeys.forEach((key) => groupedKeys.add(key));
  }
  const rendered = region.sourceInstanceKeys.flatMap((instanceKey) => {
    const group = groupsByFirst.get(instanceKey);
    if (group) {
      const components = group.sourceInstanceKeys
        .map((key) => componentByInstanceKey.get(key))
        .filter((value): value is PageComponentInstance => Boolean(value));
      return components.length
        ? [
            <PresentationGroup
              key={group.groupKey}
              groupKey={group.groupKey}
              components={components}
              destinationForGeneratedPageId={destinationForGeneratedPageId}
            />,
          ]
        : [];
    }
    if (groupedKeys.has(instanceKey)) return [];
    const component = componentByInstanceKey.get(instanceKey);
    if (!component || isNestedComponent(component.component_key)) return [];
    return [
      <SourceComponent
        key={component.instance_key}
        component={component}
        region={region}
        componentByInstanceKey={componentByInstanceKey}
        destinationForGeneratedPageId={destinationForGeneratedPageId}
        estimateDestination={estimateDestination}
        estimateForm={estimateForm}
        governedContact={governedContact}
        onFormFocusRiskChange={onFormFocusRiskChange}
        reviewMode={reviewMode}
      />,
    ];
  });
  if (!rendered.length) return null;
  return (
    <section
      className={`performanceLocalV4Region performanceLocalV4Region-${cssIdentity(region.regionKey)}`}
      data-v4-region={region.regionKey}
      data-v4-region-requirement={region.requirement}
      aria-label={region.regionKey.replace(/_/g, " ")}
    >
      <div className="performanceLocalV4Container performanceLocalV4RegionInner">
        {rendered}
      </div>
    </section>
  );
}

function SourceComponent({
  component,
  componentByInstanceKey,
  destinationForGeneratedPageId,
  estimateDestination,
  estimateForm,
  governedContact,
  onFormFocusRiskChange,
  region,
  reviewMode,
}: {
  component: PageComponentInstance;
  componentByInstanceKey: ReadonlyMap<string, PageComponentInstance>;
  destinationForGeneratedPageId: (generatedPageId: number) => string;
  estimateDestination: string | null;
  estimateForm: PerformanceLocalEstimateFormConfiguration | null;
  governedContact: PerformanceLocalGovernedContact | null;
  onFormFocusRiskChange: (focused: boolean) => void;
  region: PerformanceLocalV4RegionPlan;
  reviewMode: PerformanceLocalV4ReviewMode;
}) {
  const media = exactTargetMedia(component, region, componentByInstanceKey);
  switch (component.component_key) {
    case "hero":
      return (
        <HeroContent
          component={component}
          media={media}
          reviewMode={reviewMode}
          governedContact={governedContact}
          estimateDestination={estimateDestination}
          estimateLabel={estimateForm?.ctaLabel ?? ""}
        />
      );
    case "trust_license":
      return (
        <PresenterWithAttachedMedia
          media={media}
          reviewMode={reviewMode}
          targetInstanceKey={component.instance_key}
        >
          <TrustFacts component={component} />
        </PresenterWithAttachedMedia>
      );
    case "content_section":
    case "service_summary":
      return (
        <AuthorityContent
          component={component}
          media={media}
          regionKey={region.regionKey}
          reviewMode={reviewMode}
        />
      );
    case "destination_cards":
    case "related_page_links":
      return (
        <PresenterWithAttachedMedia
          media={media}
          reviewMode={reviewMode}
          targetInstanceKey={component.instance_key}
        >
          <DestinationCards
            component={component}
            destinationForGeneratedPageId={destinationForGeneratedPageId}
          />
        </PresenterWithAttachedMedia>
      );
    case "faq":
      return (
        <PresenterWithAttachedMedia
          media={media}
          reviewMode={reviewMode}
          targetInstanceKey={component.instance_key}
        >
          <FaqDisclosures component={component} />
        </PresenterWithAttachedMedia>
      );
    case "contact_pathways":
      return (
        <PresenterWithAttachedMedia
          media={media}
          reviewMode={reviewMode}
          targetInstanceKey={component.instance_key}
        >
          <ContactPathways component={component} governedContact={governedContact} />
        </PresenterWithAttachedMedia>
      );
    case "final_cta":
      return (
        <PresenterWithAttachedMedia
          media={media}
          reviewMode={reviewMode}
          targetInstanceKey={component.instance_key}
        >
          <FinalConversion
            component={component}
            estimateForm={estimateForm}
            governedContact={governedContact}
            onFormFocusRiskChange={onFormFocusRiskChange}
          />
        </PresenterWithAttachedMedia>
      );
    default:
      return (
        <aside
          className="performanceLocalV4SourceBlocker"
          role="alert"
          data-v4-unhandled-component={component.component_key}
          data-source-instance-key={component.instance_key}
        >
          Source component {component.instance_key} has no V4 presenter.
        </aside>
      );
  }
}

function PresenterWithAttachedMedia({
  children,
  media,
  reviewMode,
  targetInstanceKey,
}: {
  children: ReactNode;
  media: PageComponentInstance | null;
  reviewMode: PerformanceLocalV4ReviewMode;
  targetInstanceKey: string;
}) {
  if (!media || (reviewMode === "truthful" && !renderableMedia(media))) return children;
  return (
    <div className="performanceLocalV4AttachedGrid" data-v4-attached-media-target={targetInstanceKey}>
      <div className="performanceLocalV4AttachedContent">{children}</div>
      <MediaOrDemoSlot
        component={media}
        reviewMode={reviewMode}
        slot="supporting"
        targetInstanceKey={targetInstanceKey}
      />
    </div>
  );
}

function HeroContent({
  component,
  estimateDestination,
  estimateLabel,
  governedContact,
  media,
  reviewMode,
}: {
  component: PageComponentInstance;
  estimateDestination: string | null;
  estimateLabel: string;
  governedContact: PerformanceLocalGovernedContact | null;
  media: PageComponentInstance | null;
  reviewMode: PerformanceLocalV4ReviewMode;
}) {
  const data = component.resolved_data;
  return (
    <div className="performanceLocalV4HeroGrid" data-source-instance-key={component.instance_key}>
      <div className="performanceLocalV4HeroCopy">
        {text(data.page_type) ? <p className="performanceLocalV4Eyebrow">{text(data.page_type).replace(/_/g, " ")}</p> : null}
        <h1>{text(data.title)}</h1>
        {text(data.intro) ? <p className="performanceLocalV4HeroSummary">{text(data.intro)}</p> : null}
        <div className="performanceLocalV4ActionRow" data-v4-hero-actions>
          {governedContact ? <PhoneAction contact={governedContact} /> : null}
          {estimateDestination && estimateLabel ? (
            <a className="performanceLocalV4Button performanceLocalV4ButtonSecondary" href={estimateDestination}>
              {estimateLabel}
            </a>
          ) : null}
        </div>
      </div>
      <MediaOrDemoSlot
        component={media}
        reviewMode={reviewMode}
        slot="hero"
        targetInstanceKey={component.instance_key}
        priority
      />
    </div>
  );
}

function AuthorityContent({
  component,
  media,
  regionKey,
  reviewMode,
}: {
  component: PageComponentInstance;
  media: PageComponentInstance | null;
  regionKey: string;
  reviewMode: PerformanceLocalV4ReviewMode;
}) {
  const heading = text(component.resolved_data.heading);
  const body = text(component.resolved_data.body);
  const steps = array(component.resolved_data.steps)
    .map(record)
    .map((step) => ({
      heading: text(step.heading) || text(step.title) || text(step.label),
      body: text(step.body) || text(step.description),
    }))
    .filter((step) => step.heading || step.body);
  if (!heading && !body && !steps.length && !media && reviewMode === "truthful") return null;
  return (
    <article className="performanceLocalV4Authority" data-source-instance-key={component.instance_key}>
      <div className="performanceLocalV4AuthorityCopy">
        {heading ? <h2>{heading}</h2> : null}
        {body ? <SourceStructuredBody body={body} regionKey={regionKey} /> : null}
        {steps.length ? (
          <ol className="performanceLocalV4InlineSteps">
            {steps.map((step, index) => (
              <li key={`${step.heading}-${index}`}>
                {step.heading ? <strong>{step.heading}</strong> : null}
                {step.body ? <span>{step.body}</span> : null}
              </li>
            ))}
          </ol>
        ) : null}
      </div>
      <MediaOrDemoSlot
        component={media}
        reviewMode={reviewMode}
        slot="supporting"
        targetInstanceKey={component.instance_key}
      />
    </article>
  );
}

function SourceStructuredBody({ body, regionKey }: { body: string; regionKey: string }) {
  const groups = sourceBodyGroups(sourceBodyBlocks(body));
  if (!groups.length) return null;
  return (
    <div className="performanceLocalV4StructuredBody" data-v4-source-body-region={regionKey}>
      {groups.map((group, groupIndex) => {
        const content = group.blocks.map((block, blockIndex) => block.kind === "list" ? (
          <ul
            key={`list-${blockIndex}`}
            className="performanceLocalV4SourceCards"
            data-v4-source-list-region={regionKey}
          >
            {block.items.map((item, itemIndex) => (
              <li key={`${blockIndex}-${itemIndex}`}>{item}</li>
            ))}
          </ul>
        ) : (
          <p key={`paragraph-${blockIndex}`}>{block.value}</p>
        ));
        return group.heading ? (
          <section className="performanceLocalV4SourceSection" key={`section-${groupIndex}`}>
            <h3>{group.heading}</h3>
            {content}
          </section>
        ) : (
          <div className="performanceLocalV4SourceFlow" key={`flow-${groupIndex}`}>{content}</div>
        );
      })}
    </div>
  );
}

function SourceSequence({
  components,
  groupKey,
}: {
  components: readonly PageComponentInstance[];
  groupKey: string;
}) {
  return (
    <ol className="performanceLocalV4Process" data-v4-presentation-group={groupKey}>
      {components.map((component, index) => {
        const heading = text(component.resolved_data.heading);
        const body = text(component.resolved_data.body);
        return (
          <li key={component.instance_key} data-source-instance-key={component.instance_key}>
            <span className="performanceLocalV4StepMarker" aria-hidden="true">
              {String(index + 1).padStart(2, "0")}
            </span>
            <div>
              {heading ? <h2>{heading}</h2> : null}
              {body ? <p>{body}</p> : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function PresentationGroup({
  components,
  destinationForGeneratedPageId,
  groupKey,
}: {
  components: readonly PageComponentInstance[];
  destinationForGeneratedPageId: (generatedPageId: number) => string;
  groupKey: string;
}) {
  if (groupKey === PERFORMANCE_LOCAL_V4_COUNTY_RELATED_CITY_GROUP_KEY) {
    return (
      <CountyRelatedCityDiscovery
        components={components}
        destinationForGeneratedPageId={destinationForGeneratedPageId}
        groupKey={groupKey}
      />
    );
  }
  return <SourceSequence components={components} groupKey={groupKey} />;
}

function CountyRelatedCityDiscovery({
  components,
  destinationForGeneratedPageId,
  groupKey,
}: {
  components: readonly PageComponentInstance[];
  destinationForGeneratedPageId: (generatedPageId: number) => string;
  groupKey: string;
}) {
  const source = components[0];
  const destinations = components[1];
  if (
    components.length !== 2 ||
    source?.component_key !== "content_section" ||
    source.input_bindings.section_key !== "related_city_services" ||
    destinations?.component_key !== "destination_cards"
  ) {
    return (
      <aside
        className="performanceLocalV4SourceBlocker"
        role="alert"
        data-v4-presentation-group={groupKey}
        data-v4-group-source-instance-keys={components.map((component) => component.instance_key).join("|")}
      >
        The audited County related-city presentation group is unavailable.
      </aside>
    );
  }
  const heading = text(source.resolved_data.heading);
  return (
    <div
      className="performanceLocalV4CountyRelatedCityDiscovery"
      data-v4-presentation-group={groupKey}
      data-v4-group-source-instance-keys={`${source.instance_key}|${destinations.instance_key}`}
    >
      <article
        className="performanceLocalV4Authority"
        data-source-instance-key={source.instance_key}
        data-v4-source-body-consumption="deduplicated_exact_destination_label_prefix"
      >
        <div className="performanceLocalV4AuthorityCopy">
          <h2>{heading}</h2>
        </div>
      </article>
      <DestinationCards
        component={destinations}
        destinationForGeneratedPageId={destinationForGeneratedPageId}
      />
    </div>
  );
}

function TrustFacts({ component }: { component: PageComponentInstance }) {
  const facts = [
    text(component.resolved_data.license_number)
      ? { label: "License", value: text(component.resolved_data.license_number) }
      : null,
    text(component.resolved_data.certified_operator)
      ? { label: "Certified operator", value: text(component.resolved_data.certified_operator) }
      : null,
  ].filter((value): value is { label: string; value: string } => Boolean(value));
  if (!facts.length) return null;
  return (
    <div className="performanceLocalV4TrustGrid" data-source-instance-key={component.instance_key}>
      {facts.map((fact) => (
        <article key={fact.label}>
          <ShieldCheck aria-hidden="true" />
          <span>{fact.label}</span>
          <strong>{fact.value}</strong>
        </article>
      ))}
    </div>
  );
}

function DestinationCards({
  component,
  destinationForGeneratedPageId,
}: {
  component: PageComponentInstance;
  destinationForGeneratedPageId: (generatedPageId: number) => string;
}) {
  const links = array(component.resolved_data.links)
    .map(record)
    .filter((link) => text(link.label));
  if (!links.length) return null;
  return (
    <div className="performanceLocalV4CardGrid" data-source-instance-key={component.instance_key}>
      {links.map((link, index) => {
        const generatedPageId = positiveInteger(link.target_generated_page_id);
        const stableKey = positiveInteger(link.target_planned_page_id) ?? text(link.slug) ?? index;
        return (
          <article key={stableKey}>
            <h2>
              {generatedPageId ? (
                <Link
                  to={destinationForGeneratedPageId(generatedPageId)}
                  data-canonical-slug={text(link.slug)}
                >
                  {text(link.label)}
                </Link>
              ) : (
                <span>{text(link.label)}</span>
              )}
            </h2>
            {text(link.purpose) ? <p>{text(link.purpose)}</p> : null}
          </article>
        );
      })}
    </div>
  );
}

function FaqDisclosures({ component }: { component: PageComponentInstance }) {
  const items = array(component.resolved_data.items)
    .map(record)
    .filter((item) => text(item.question) && text(item.answer));
  if (!items.length) return null;
  return (
    <div className="performanceLocalV4FaqList" data-source-instance-key={component.instance_key}>
      {items.map((item, index) => (
        <details key={`${text(item.question)}-${index}`}>
          <summary>{text(item.question)}</summary>
          <p>{text(item.answer)}</p>
        </details>
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
    <div className="performanceLocalV4ContactPathways" data-source-instance-key={component.instance_key}>
      {governedContact ? <PhoneAction contact={governedContact} /> : null}
      {email ? <EmailAction email={email} /> : null}
    </div>
  );
}

function FinalConversion({
  component,
  estimateForm,
  governedContact,
  onFormFocusRiskChange,
}: {
  component: PageComponentInstance;
  estimateForm: PerformanceLocalEstimateFormConfiguration | null;
  governedContact: PerformanceLocalGovernedContact | null;
  onFormFocusRiskChange: (focused: boolean) => void;
}) {
  const heading = text(component.resolved_data.heading);
  const body = text(component.resolved_data.body);
  return (
    <div className="performanceLocalV4FinalGrid" data-source-instance-key={component.instance_key}>
      <div className="performanceLocalV4FinalCopy">
        {heading ? <h2>{heading}</h2> : null}
        {body ? <p>{body}</p> : null}
        {governedContact ? <PhoneAction contact={governedContact} /> : null}
      </div>
      {estimateForm ? (
        <ProviderDisabledForm
          configuration={estimateForm}
          onFormFocusRiskChange={onFormFocusRiskChange}
        />
      ) : null}
    </div>
  );
}

function ProviderDisabledForm({
  configuration,
  onFormFocusRiskChange,
}: {
  configuration: PerformanceLocalEstimateFormConfiguration;
  onFormFocusRiskChange: (focused: boolean) => void;
}) {
  function preventSubmission(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
  }
  return (
    <form
      id={performanceLocalFormDomId(configuration.componentConfigurationId)}
      className="performanceLocalV4Form"
      aria-label="Estimate request preview"
      autoComplete="off"
      data-preview-only="true"
      data-provider-state={configuration.providerState.submissionState}
      data-provider-configured="false"
      data-collects-data="false"
      data-controls-read-only="true"
      onSubmit={preventSubmission}
      onFocusCapture={() => onFormFocusRiskChange(true)}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          onFormFocusRiskChange(false);
        }
      }}
    >
      <p className="performanceLocalV4FormNotice">{configuration.previewNotice}</p>
      <div className="performanceLocalV4FormGrid">
        {[...configuration.fields].sort((left, right) => left.order - right.order).map((field) => (
          <label
            key={field.key}
            className={field.responsive.desktop === "full" ? "performanceLocalV4FormFieldFull" : undefined}
          >
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

export function PerformanceLocalV4CampaignBanner({ campaign }: { campaign: PerformanceLocalCampaign }) {
  const singleAction = campaign.intent === "evergreen_conversion" &&
    performanceLocalActionCopyEquivalent(campaign.campaignLabel, campaign.ctaLabel);
  return (
    <aside
      className={`performanceLocalV4Campaign${singleAction ? " performanceLocalV4CampaignSingle" : ""}`}
      aria-label={campaign.campaignLabel}
      data-conversion-intent={campaign.intent}
      data-public-action-copy={singleAction ? "semantic_duplicate_suppressed" : "distinct_copy_and_action"}
    >
      {singleAction ? (
        <a href={campaign.ctaDestination}><strong>{campaign.campaignLabel}</strong></a>
      ) : (
        <div className="performanceLocalV4Container performanceLocalV4CampaignInner">
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

export function PerformanceLocalV4SiteHeader({
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

  useEffect(() => {
    if (!menuOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusable = focusableElements(drawerRef.current);
    focusable[0]?.focus();
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onMenuOpenChange(false);
        triggerRef.current?.focus();
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
    <header className="performanceLocalV4Header" data-source-instance-key={component.instance_key}>
      <div className="performanceLocalV4Container performanceLocalV4HeaderInner">
        <div className="performanceLocalV4Brand" aria-label={displayName}>
          <BrandIdentity data={data} displayName={displayName} slot="header_logo" />
          <span>
            <strong>{displayName}</strong>
            {text(data.tagline) ? <small>{text(data.tagline)}</small> : null}
          </span>
        </div>
        {navigation.length ? (
          <nav
            className="performanceLocalV4DesktopNav"
            aria-label="Website navigation"
            data-v4-navigation-source-instance-keys={navigationSourceKeys(primaryNavigation, utilityNavigation)}
          >
            <NavigationList nodes={navigation} destinationForGeneratedPageId={destinationForGeneratedPageId} />
          </nav>
        ) : null}
        <div className="performanceLocalV4HeaderActions">
          {contact ? <PhoneAction contact={contact} compact /> : null}
          {estimateDestination && estimateLabel ? <a href={estimateDestination}>{estimateLabel}</a> : null}
        </div>
        <button
          ref={triggerRef}
          className="performanceLocalV4MenuTrigger"
          type="button"
          aria-controls="performance-local-v4-mobile-menu"
          aria-expanded={menuOpen}
          aria-label={menuOpen ? "Close website navigation" : "Open website navigation"}
          onClick={() => onMenuOpenChange(!menuOpen)}
        >
          {menuOpen ? <X aria-hidden="true" /> : <Menu aria-hidden="true" />}
        </button>
      </div>
      {menuOpen ? (
        <div className="performanceLocalV4DrawerBackdrop" onMouseDown={() => onMenuOpenChange(false)}>
          <div
            id="performance-local-v4-mobile-menu"
            ref={drawerRef}
            className="performanceLocalV4Drawer"
            role="dialog"
            aria-modal="true"
            aria-label="Website navigation"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <button type="button" onClick={() => onMenuOpenChange(false)} aria-label="Close website navigation">
              <X aria-hidden="true" />
            </button>
            <nav aria-label="Mobile website navigation">
              <NavigationList
                nodes={navigation}
                destinationForGeneratedPageId={destinationForGeneratedPageId}
                onNavigate={() => onMenuOpenChange(false)}
              />
            </nav>
          </div>
        </div>
      ) : null}
    </header>
  );
}

export function PerformanceLocalV4SiteFooter({
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
    <footer className="performanceLocalV4Footer" data-source-instance-key={component.instance_key}>
      <div className="performanceLocalV4Container performanceLocalV4FooterGrid">
        <div className="performanceLocalV4FooterBrand">
          <BrandIdentity data={data} displayName={displayName} slot="footer_logo" />
          <strong>{displayName}</strong>
          {text(data.business_type) ? <span>{text(data.business_type)}</span> : null}
        </div>
        {nodes.length ? (
          <nav
            aria-label={text(navigation?.resolved_data.label) || "Footer navigation"}
            data-source-instance-key={navigation?.instance_key}
            data-v4-consumption-mode="nested_navigation"
          >
            <NavigationList nodes={nodes} destinationForGeneratedPageId={destinationForGeneratedPageId} />
          </nav>
        ) : null}
        <div className="performanceLocalV4FooterContact">
          {contact ? <PhoneAction contact={contact} /> : null}
          {email ? <EmailAction email={email} /> : null}
          {text(data.license_number) ? <span>License {text(data.license_number)}</span> : null}
        </div>
      </div>
    </footer>
  );
}

export function PerformanceLocalV4StickyActions({
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
    <aside className="performanceLocalV4StickyActions" aria-label="Contact actions">
      {contact ? <PhoneAction contact={contact} label={callLabel} compact /> : null}
      {estimateDestination ? <a href={estimateDestination}>{estimateLabel}</a> : null}
    </aside>
  );
}

export function PerformanceLocalV4BackToTop({ suppressed }: { suppressed: boolean }) {
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
      className="performanceLocalV4BackToTop"
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

function MediaOrDemoSlot({
  component,
  priority = false,
  reviewMode,
  slot,
  targetInstanceKey,
}: {
  component: PageComponentInstance | null;
  priority?: boolean;
  reviewMode: PerformanceLocalV4ReviewMode;
  slot: "hero" | "supporting";
  targetInstanceKey: string;
}) {
  const media = component ? renderableMedia(component) : null;
  if (media) {
    return (
      <figure
        className={`performanceLocalV4Media performanceLocalV4Media-${media.preset.replace(/_/g, "-")}`}
        data-source-instance-key={component!.instance_key}
        data-semantic-media-role={media.role}
        data-effective-display-preset={media.preset}
      >
        <div className="performanceLocalV4MediaFrame">
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
  if (reviewMode !== "structural_demo") return null;
  return (
    <div
      className={`performanceLocalV4DemoMedia performanceLocalV4DemoMedia-${slot}`}
      role="img"
      aria-label={PERFORMANCE_LOCAL_V4_DEMO_MEDIA_LABEL}
      data-source-instance-key={component?.instance_key}
      data-v4-demo-media-slot={slot}
      data-v4-demo-target-instance-key={targetInstanceKey}
    >
      <span>{PERFORMANCE_LOCAL_V4_DEMO_MEDIA_LABEL}</span>
    </div>
  );
}

function exactTargetMedia(
  target: PageComponentInstance,
  region: PerformanceLocalV4RegionPlan,
  componentByInstanceKey: ReadonlyMap<string, PageComponentInstance>,
): PageComponentInstance | null {
  const matches = region.sourceInstanceKeys
    .map((key) => componentByInstanceKey.get(key))
    .filter((component): component is PageComponentInstance => Boolean(component))
    .filter((component) =>
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
  if (source && alt && safeLocalAssetUrl(source)) {
    return <img className="performanceLocalV4Logo" src={source} alt={alt} />;
  }
  if (slot === "footer_logo") return null;
  return <span className="performanceLocalV4BrandMark" aria-hidden="true">{initials(displayName)}</span>;
}

function navigationNodes(
  primary: PageComponentInstance | null,
  utility: PageComponentInstance | null,
): ResolvedNavigationItem[] {
  const primaryTree = primary
    ? buildNavigationTree(array(primary.resolved_data.items))
    : { nodes: [], error: null };
  if (primaryTree.error) return [];
  const utilityTree = utility
    ? buildNavigationTree(array(utility.resolved_data.items))
    : { nodes: [], error: null };
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
    result.push({
      ...node,
      children: deduplicateNavigation(node.children, seenTargets),
    });
  }
  return result;
}

function navigationSourceKeys(
  primary: PageComponentInstance | null,
  utility: PageComponentInstance | null,
): string | undefined {
  const keys = [primary?.instance_key, utility?.instance_key].filter(
    (value): value is string => Boolean(value),
  );
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
          submenuId={`performance-local-v4-submenu-${navigationId}-${node.navigationItemId}`}
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
    <Link
      to={destinationForGeneratedPageId(node.targetGeneratedPageId)}
      data-canonical-slug={node.canonicalSlug}
      onClick={onNavigate}
    >
      {node.label}
    </Link>
  ) : (
    <span aria-disabled="true">{node.label}</span>
  );

  if (!node.children.length) return <li>{destination}</li>;
  return (
    <li className="performanceLocalV4NavigationBranch">
      <div className="performanceLocalV4NavigationParent">
        {destination}
        <button
          ref={triggerRef}
          className="performanceLocalV4NavigationToggle"
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

function PhoneAction({
  compact = false,
  contact,
  label,
}: {
  compact?: boolean;
  contact: PerformanceLocalGovernedContact;
  label?: string;
}) {
  return (
    <a
      className={compact ? "performanceLocalV4PhoneCompact" : "performanceLocalV4Button"}
      href={contact.callDestination}
    >
      <Phone aria-hidden="true" />
      <span>{label || contact.phoneDisplay}</span>
    </a>
  );
}

function EmailAction({ email }: { email: string }) {
  return (
    <a className="performanceLocalV4Email" href={`mailto:${email}`}>
      <Mail aria-hidden="true" />
      <span>{email}</span>
    </a>
  );
}

function isNestedComponent(componentKey: string): boolean {
  return [
    "website_header",
    "primary_navigation",
    "utility_navigation",
    "footer_navigation",
    "website_footer",
    "media_placement",
  ].includes(componentKey);
}

function focusableElements(root: HTMLElement | null): HTMLElement[] {
  if (!root) return [];
  return Array.from(root.querySelectorAll<HTMLElement>(
    'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), details > summary, [tabindex]:not([tabindex="-1"])',
  )).filter((element) => !element.closest('[hidden], [aria-hidden="true"], [inert]'));
}

function safeLocalAssetUrl(value: string): boolean {
  if (!value || /[\u0000-\u001f\u007f\\]/.test(value)) return false;
  if (value.startsWith("/")) return !value.startsWith("//");
  try {
    const parsed = new URL(value);
    return (
      (parsed.protocol === "http:" || parsed.protocol === "https:") &&
      !parsed.username &&
      !parsed.password &&
      ["localhost", "127.0.0.1", "[::1]"].includes(parsed.hostname)
    );
  } catch {
    return false;
  }
}

function safeEmail(value: unknown): string | null {
  const email = text(value);
  return email && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) ? email : null;
}

function initials(value: string): string {
  const words = value.split(/\s+/).filter(Boolean).slice(0, 2);
  return words.map((word) => word[0]?.toUpperCase()).join("") || "A";
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
  const groups: Array<{
    heading: string | null;
    blocks: Array<Exclude<SourceBodyBlock, { kind: "heading" }>>;
  }> = [];
  for (const block of blocks) {
    if (block.kind === "heading") {
      groups.push({ heading: block.value, blocks: [] });
      continue;
    }
    const current = groups.length ? groups[groups.length - 1] : undefined;
    if (!current || (current.heading === null && current.blocks.length > 0)) {
      groups.push({ heading: null, blocks: [block] });
    } else {
      current.blocks.push(block);
    }
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

function cssIdentity(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9_-]+/g, "-");
}

function boundedNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.min(1, Math.max(0, value))
    : fallback;
}

function positiveInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0 ? value : null;
}

function array(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function text(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value).trim() : "";
}
