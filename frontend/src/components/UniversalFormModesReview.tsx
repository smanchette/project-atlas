import {
  AlertTriangle,
  Ban,
  Boxes,
  CheckCircle2,
  CircleDashed,
  Clock3,
  ExternalLink,
  Inbox,
  LockKeyhole,
  Mail,
  Network,
  RotateCcw,
  ShieldCheck,
} from "lucide-react";

export const UNIVERSAL_FORM_DELIVERY_MODES = [
  "disabled",
  "atlas_email",
  "provider_owned",
  "atlasops360_native",
  "external_adapter",
] as const;

export type UniversalFormDeliveryMode = (typeof UNIVERSAL_FORM_DELIVERY_MODES)[number];

type ModeReview = {
  mode: UniversalFormDeliveryMode;
  label: string;
  providerOwner: string;
  collector: string;
  notificationDestination: string;
  retentionOwner: string;
  readiness: string;
  missingConfig: readonly string[];
  productionEnabled: false;
  atlasStoresCustomerData: false;
  externalRequestNow: false;
};

export const UNIVERSAL_FORM_MODE_REVIEWS: readonly ModeReview[] = [
  {
    mode: "disabled", label: "Disabled", providerOwner: "None", collector: "None",
    notificationDestination: "None", retentionOwner: "None", readiness: "Valid disabled state",
    missingConfig: [], productionEnabled: false, atlasStoresCustomerData: false, externalRequestNow: false,
  },
  {
    mode: "atlas_email", label: "Atlas Email", providerOwner: "Atlas transport adapter",
    collector: "Atlas normalized envelope", notificationDestination: "Verified recipient set",
    retentionOwner: "Website retention policy", readiness: "Blocked",
    missingConfig: ["Verified recipient approval", "Opaque transport reference", "Secure payload store and key manager", "Privacy, consent, retention, abuse, and idempotency policies"],
    productionEnabled: false, atlasStoresCustomerData: false, externalRequestNow: false,
  },
  {
    mode: "provider_owned", label: "Provider Owned", providerOwner: "Approved external provider",
    collector: "Provider-owned destination", notificationDestination: "Provider-owned workflow",
    retentionOwner: "External provider", readiness: "Presentation only",
    missingConfig: ["Verified exact HTTPS origin", "Provider approval evidence"],
    productionEnabled: false, atlasStoresCustomerData: false, externalRequestNow: false,
  },
  {
    mode: "atlasops360_native", label: "AtlasOps360 Native", providerOwner: "Optional AtlasOps360 adapter",
    collector: "AtlasOps360 module boundary", notificationDestination: "Opaque workspace binding",
    retentionOwner: "AtlasOps360 policy", readiness: "Unavailable",
    missingConfig: ["Installed compatible adapter", "Approved workspace binding"],
    productionEnabled: false, atlasStoresCustomerData: false, externalRequestNow: false,
  },
  {
    mode: "external_adapter", label: "External Adapter", providerOwner: "Registered adapter owner",
    collector: "Adapter-defined destination", notificationDestination: "Opaque adapter binding",
    retentionOwner: "Adapter policy owner", readiness: "Blocked",
    missingConfig: ["Registered compatible adapter", "Approved opaque configuration references"],
    productionEnabled: false, atlasStoresCustomerData: false, externalRequestNow: false,
  },
] as const;

const modeIcons = { disabled: Ban, atlas_email: Mail, provider_owned: ExternalLink, atlasops360_native: Network, external_adapter: Boxes } as const;

function Fact({ label, value }: { label: string; value: string }) {
  return <div className="universalFormModesReviewFact"><dt>{label}</dt><dd>{value}</dd></div>;
}

function SafetyFlags({ review }: { review: ModeReview }) {
  return (
    <ul className="universalFormModesReviewSafetyFlags" aria-label={`${review.label} safety facts`}>
      <li><ShieldCheck aria-hidden="true" /> Production enabled: no</li>
      <li><LockKeyhole aria-hidden="true" /> Atlas stores customer data: no</li>
      <li><CircleDashed aria-hidden="true" /> External request now: no</li>
    </ul>
  );
}

function ModeSummary({ review, compact = false }: { review: ModeReview; compact?: boolean }) {
  const Icon = modeIcons[review.mode];
  return (
    <article className={`universalFormModesReviewMode universalFormModesReviewMode--${review.mode}`} data-mode={review.mode}>
      <header>
        <span className="universalFormModesReviewModeIcon"><Icon aria-hidden="true" /></span>
        <div><p className="universalFormModesReviewEyebrow">{review.mode}</p><h3>{review.label}</h3></div>
        <span className="universalFormModesReviewReadiness">{review.readiness}</span>
      </header>
      {!compact && (
        <dl className="universalFormModesReviewFacts">
          <Fact label="Provider owner" value={review.providerOwner} />
          <Fact label="Collector" value={review.collector} />
          <Fact label="Notification destination" value={review.notificationDestination} />
          <Fact label="Retention owner" value={review.retentionOwner} />
          <Fact label="Readiness" value={review.readiness} />
          <Fact label="Missing configuration" value={review.missingConfig.length ? review.missingConfig.join("; ") : "None"} />
        </dl>
      )}
      <SafetyFlags review={review} />
    </article>
  );
}

function ReviewPanel({ id, eyebrow, title, children, wide = false }: { id: string; eyebrow: string; title: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <section id={id} className={`universalFormModesReviewPanel${wide ? " universalFormModesReviewPanel--wide" : ""}`} data-review-panel={id} aria-labelledby={`${id}-title`}>
      <p className="universalFormModesReviewEyebrow">{eyebrow}</p><h2 id={`${id}-title`}>{title}</h2>{children}
    </section>
  );
}

const reviewByMode = Object.fromEntries(UNIVERSAL_FORM_MODE_REVIEWS.map((review) => [review.mode, review])) as Record<UniversalFormDeliveryMode, ModeReview>;

const atlasEmailTestReview: ModeReview = {
  ...reviewByMode.atlas_email,
  collector: "Synthetic in-memory envelope",
  notificationDestination: "Synthetic in-memory sink",
  readiness: "Test-ready only",
  missingConfig: ["Production transport registration", "Secure production payload store and key manager"],
};
const providerMissingOriginReview: ModeReview = {
  ...reviewByMode.provider_owned,
  collector: "None until destination verification",
  notificationDestination: "None",
  readiness: "Blocked",
};
const atlasOps360TestReview: ModeReview = {
  ...reviewByMode.atlasops360_native,
  collector: "Synthetic AtlasOps360 adapter",
  notificationDestination: "Synthetic workspace binding",
  readiness: "Test-ready only",
  missingConfig: ["Production module installation", "Approved production workspace binding"],
};

export default function UniversalFormModesReview() {
  return (
    <main className="universalFormModesReview" data-universal-form-modes-review="local-only">
      <header className="universalFormModesReviewHero">
        <div><p className="universalFormModesReviewEyebrow">Operator-only evidence surface</p><h1>Universal form delivery modes</h1><p>A static review of the Website-scoped delivery boundary. Every state below is synthetic, inactive, and disconnected from customer data and external services.</p></div>
        <div className="universalFormModesReviewDemoFlag"><ShieldCheck aria-hidden="true" /><span><strong>DEMO CONFIGURATION</strong>NOT ACTIVE</span></div>
      </header>
      <nav className="universalFormModesReviewJump" aria-label="Universal form modes review sections">
        <a href="#universal-form-mode-contact-sheet">Review the five modes</a><a href="#universal-form-master-contact-sheet">Review the safety matrix</a>
      </nav>
      <div className="universalFormModesReviewGrid">
        <ReviewPanel id="architecture-summary" eyebrow="01 / Boundary" title="One core, three product surfaces" wide>
          <div className="universalFormModesReviewArchitecture">
            <div><strong>Website Builder Core</strong><span>Owns portable form contracts, readiness, and adapter boundaries.</span></div>
            <div><strong>Standalone Atlas</strong><span>Uses the core without an operations product or shared database.</span></div>
            <div><strong>Atlas + AtlasOps360</strong><span>Optional module depends inward through the same stable contract.</span></div>
            <div><strong>External adapters</strong><span>Remain replaceable and fail closed when unregistered or incomplete.</span></div>
          </div><p className="universalFormModesReviewCallout">No fork. No fallback. No cross-product tables. No activation in this review.</p>
        </ReviewPanel>
        <ReviewPanel id="disabled-mode" eyebrow="02 / Mode" title="Disabled means absent">
          <ModeSummary review={reviewByMode.disabled} /><div className="universalFormModesReviewEmptyState"><Ban aria-hidden="true" /><strong>No public form surface</strong><span>No wrapper, destination, envelope, outbox, or delivery attempt exists.</span></div>
        </ReviewPanel>
        <ReviewPanel id="atlas-email-blocked" eyebrow="03 / Mode" title="Atlas Email - blocked">
          <ModeSummary review={reviewByMode.atlas_email} /><ul className="universalFormModesReviewChecklist">{reviewByMode.atlas_email.missingConfig.map((item) => <li key={item}><AlertTriangle aria-hidden="true" />{item}</li>)}</ul>
        </ReviewPanel>
        <ReviewPanel id="atlas-email-test-ready" eyebrow="04 / Disposable proof" title="Atlas Email - test-ready">
          <ModeSummary review={atlasEmailTestReview} /><div className="universalFormModesReviewState universalFormModesReviewState--ready"><CheckCircle2 aria-hidden="true" /><div><strong>Synthetic in-memory sink available</strong><span>Automated-test runtime only. Payload is process-local and wiped after the assertion.</span></div></div><p>No transport credential, real recipient, external request, or production readiness is implied.</p>
        </ReviewPanel>
        <ReviewPanel id="provider-owned-hosted" eyebrow="05 / Presentation" title="Provider-owned hosted surface">
          <ModeSummary review={reviewByMode.provider_owned} /><div className="universalFormModesReviewHosted" role="region" aria-label="Inert provider-owned presentation preview"><span className="universalFormModesReviewHostedTag">Provider-owned</span><strong>Continue in the provider's approved surface</strong><p>Atlas may present a verified destination with an accessible title and ownership disclosure.</p><dl><Fact label="Origin policy" value="Exact approved HTTPS origin" /><Fact label="Sandbox policy" value="allow-forms only" /><Fact label="Referrer policy" value="no-referrer" /></dl></div>
        </ReviewPanel>
        <ReviewPanel id="provider-owned-missing-origin" eyebrow="06 / Fail closed" title="Provider destination missing">
          <ModeSummary review={providerMissingOriginReview} /><div className="universalFormModesReviewState universalFormModesReviewState--blocked"><AlertTriangle aria-hidden="true" /><div><strong>No hosted surface rendered</strong><span>An exact verified origin is required. Atlas does not guess, redirect, or fall back to email.</span></div></div>
        </ReviewPanel>
        <ReviewPanel id="atlasops360-unavailable" eyebrow="07 / Optional module" title="AtlasOps360 adapter unavailable">
          <ModeSummary review={reviewByMode.atlasops360_native} /><p>The Website Builder remains complete without AtlasOps360. Missing module registration blocks only this mode.</p>
        </ReviewPanel>
        <ReviewPanel id="atlasops360-test-adapter" eyebrow="08 / Boundary proof" title="AtlasOps360 synthetic adapter">
          <ModeSummary review={atlasOps360TestReview} /><div className="universalFormModesReviewState universalFormModesReviewState--ready"><Network aria-hidden="true" /><div><strong>Contract-compatible test adapter</strong><span>Exercises the portable envelope without accounts, authentication, deployment, or database sharing.</span></div></div>
        </ReviewPanel>
        <ReviewPanel id="external-adapter-missing" eyebrow="09 / Adapter" title="External adapter missing">
          <ModeSummary review={reviewByMode.external_adapter} /><p>Opaque configuration references are never resolved by this static review. Unregistered adapters remain blocked.</p>
        </ReviewPanel>
        <ReviewPanel id="recipient-verification" eyebrow="10 / Governance" title="Recipient verification">
          <ModeSummary review={reviewByMode.atlas_email} /><div className="universalFormModesReviewRecipientFlow"><span>Candidate</span><span>Independent approval</span><span>Verified revision</span><span>Enabled recipient set</span></div><p className="universalFormModesReviewCallout">A mutable business contact is not recipient approval. No candidate is auto-seeded.</p>
        </ReviewPanel>
        <ReviewPanel id="policy-blockers" eyebrow="11 / Readiness" title="Policy blockers">
          <ModeSummary review={reviewByMode.atlas_email} /><div className="universalFormModesReviewPolicyGrid">{["Privacy", "Consent", "Retention", "Abuse prevention", "Success behavior", "Failure behavior", "Idempotency"].map((item) => <div key={item}><AlertTriangle aria-hidden="true" /><strong>{item}</strong><span>Explicit approved reference required</span></div>)}</div>
        </ReviewPanel>
        <ReviewPanel id="outbox-status" eyebrow="12 / Safe evidence" title="Outbox status">
          <ModeSummary review={atlasEmailTestReview} /><div className="universalFormModesReviewTimeline"><div className="is-current"><Inbox aria-hidden="true" /><strong>Queued</strong><span>Safe envelope identity only</span></div><div><Clock3 aria-hidden="true" /><strong>Processing</strong><span>Optimistic state version</span></div><div><CheckCircle2 aria-hidden="true" /><strong>Delivered</strong><span>Provider-safe reference only</span></div></div>
        </ReviewPanel>
        <ReviewPanel id="retry-state" eyebrow="13 / Attempt" title="Transient retry">
          <ModeSummary review={atlasEmailTestReview} /><div className="universalFormModesReviewState universalFormModesReviewState--waiting"><RotateCcw aria-hidden="true" /><div><strong>Safe code: transport_temporarily_unavailable</strong><span>Retry timing requires an explicit approved policy; no arbitrary retry count is invented.</span></div></div>
        </ReviewPanel>
        <ReviewPanel id="permanent-failure" eyebrow="14 / Attempt" title="Terminal failure">
          <ModeSummary review={reviewByMode.external_adapter} /><div className="universalFormModesReviewState universalFormModesReviewState--blocked"><Ban aria-hidden="true" /><div><strong>Safe code: destination_rejected</strong><span>Delivery stops. The ledger retains no plaintext fields, body, recipient list, or credential.</span></div></div>
        </ReviewPanel>
        <ReviewPanel id="universal-form-mode-contact-sheet" eyebrow="17 / Contact sheet" title="Five-mode contact sheet" wide>
          <div className="universalFormModesReviewContactSheet">{UNIVERSAL_FORM_MODE_REVIEWS.map((review) => <ModeSummary key={review.mode} review={review} />)}</div>
        </ReviewPanel>
        <ReviewPanel id="universal-form-master-contact-sheet" eyebrow="18 / Master evidence" title="Ownership and safety matrix" wide>
          <div className="universalFormModesReviewMasterGrid" role="list" aria-label="Universal form mode ownership and safety evidence">
            {UNIVERSAL_FORM_MODE_REVIEWS.map((review) => (
              <article key={review.mode} className={`universalFormModesReviewMasterCard universalFormModesReviewMode--${review.mode}`} role="listitem">
                <h3>{review.mode}</h3>
                <dl>
                  <Fact label="Provider owner" value={review.providerOwner} />
                  <Fact label="Collector" value={review.collector} />
                  <Fact label="Notification destination" value={review.notificationDestination} />
                  <Fact label="Retention owner" value={review.retentionOwner} />
                  <Fact label="Readiness" value={review.readiness} />
                  <Fact label="Missing configuration" value={review.missingConfig.length ? review.missingConfig.join("; ") : "None"} />
                  <Fact label="Production" value="No" />
                  <Fact label="Atlas customer data" value="No" />
                  <Fact label="Request now" value="No" />
                </dl>
              </article>
            ))}
          </div>
        </ReviewPanel>
      </div>
      <footer className="universalFormModesReviewFooter"><strong>Review boundary:</strong> static source-defined fixtures only. No submission, persistence, adapter invocation, or activation occurs here.</footer>
    </main>
  );
}
