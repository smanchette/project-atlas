import { AlertTriangle, ShieldCheck } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import { apiRequest } from "../api";
import PerformanceLocalRenderer, {
  type PerformanceLocalFormSubmissionPayload,
} from "../components/PerformanceLocalRenderer";
import {
  performanceLocalDeliveryApiPath,
  performanceLocalDeliveryConfiguration,
  performanceLocalDeliveryValidationError,
  type PerformanceLocalDeliveryConfiguration,
} from "../components/performanceLocalDelivery";
import {
  installIdentityHeadTags,
  removeIdentityHeadTags,
} from "../components/WebsiteIdentityPresentation";
import { themePresentation } from "../components/themeAdapter";
import type {
  PerformanceLocalDeliveryMode,
  PerformanceLocalDeliveryRead,
  PerformanceLocalSubmissionAcceptedRead,
} from "../types";

type PerformanceLocalDeliveryPageProps = Readonly<{
  requestedMode: PerformanceLocalDeliveryMode;
}>;

type DeliveryPageData = Readonly<{
  configuration: PerformanceLocalDeliveryConfiguration | null;
  delivery: PerformanceLocalDeliveryRead;
  requestKey: string;
}>;

const ACTIVE_DELIVERY_UNAVAILABLE = "Performance Local delivery is unavailable.";

export function performanceLocalDeliveryFailureMessage(
  requestedMode: PerformanceLocalDeliveryMode,
  value: unknown,
): string {
  if (requestedMode === "active") return ACTIVE_DELIVERY_UNAVAILABLE;
  return value instanceof Error ? value.message : ACTIVE_DELIVERY_UNAVAILABLE;
}

export function PerformanceLocalDeliveryPage({
  requestedMode,
}: PerformanceLocalDeliveryPageProps) {
  const { id, configurationId } = useParams();
  const requestKey = `${requestedMode}:${configurationId ?? "active"}:${id ?? "missing"}`;
  const [data, setData] = useState<DeliveryPageData | null>(null);
  const [requestStateKey, setRequestStateKey] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const loadGeneration = useRef(0);
  const viewportWidth = useViewportWidth();

  useLayoutEffect(() => {
    removeIdentityHeadTags(document);
    return () => removeIdentityHeadTags(document);
  }, [requestKey]);

  useEffect(() => {
    const generation = ++loadGeneration.current;
    let cancelled = false;
    const isCurrent = () => !cancelled && generation === loadGeneration.current;
    setRequestStateKey(requestKey);
    setLoading(true);
    setError(null);
    setData(null);
    document.title = "Performance Local delivery | Project Atlas";
    removeIdentityHeadTags(document);

    async function loadDelivery() {
      const pageId = positiveInteger(id);
      const requestedConfigurationId = requestedMode === "active"
        ? null
        : positiveInteger(configurationId);
      if (!pageId || (requestedMode !== "active" && !requestedConfigurationId)) {
        if (isCurrent()) {
          setError(performanceLocalDeliveryFailureMessage(
            requestedMode,
            new Error("Invalid Performance Local delivery identity."),
          ));
          setLoading(false);
        }
        return;
      }
      try {
        const delivery = await apiRequest<PerformanceLocalDeliveryRead>(
          performanceLocalDeliveryApiPath(requestedMode, pageId, requestedConfigurationId),
        );
        const validationError = performanceLocalDeliveryValidationError(
          delivery,
          requestedMode,
          pageId,
          requestedConfigurationId,
        );
        if (validationError) throw new Error(validationError);
        const configuration = delivery.renderer_result.status === "ready"
          ? performanceLocalDeliveryConfiguration(delivery)
          : null;
        if (delivery.renderer_result.status === "ready" && !configuration) {
          throw new Error("The server-resolved V3 conversion graph is incomplete or unsafe.");
        }
        if (!isCurrent()) return;
        setData({ configuration, delivery, requestKey });
        document.title = `${delivery.page.page_title} | Performance Local`;
      } catch (value) {
        if (!isCurrent()) return;
        setError(performanceLocalDeliveryFailureMessage(requestedMode, value));
      } finally {
        if (isCurrent()) setLoading(false);
      }
    }

    void loadDelivery();
    return () => {
      cancelled = true;
      if (generation === loadGeneration.current) loadGeneration.current += 1;
      removeIdentityHeadTags(document);
      document.title = "Project Atlas";
    };
  }, [configurationId, id, requestKey, requestedMode]);

  const currentData = requestStateKey === requestKey && data?.requestKey === requestKey
    ? data
    : null;

  useEffect(() => {
    if (!currentData) return;
    const header = currentData.delivery.composition.effective_components.find(
      (component) => component.component_key === "website_header",
    );
    return installIdentityHeadTags(document, record(header?.resolved_data.identity_assets));
  }, [currentData]);

  if (requestStateKey !== requestKey || loading) {
    return <DeliveryState message="Loading exact Performance Local delivery…" />;
  }
  if (error || !currentData) {
    return <DeliveryState message={error ?? "Performance Local delivery is unavailable."} error />;
  }

  const { configuration, delivery } = currentData;
  if (delivery.renderer_result.status === "blocked" || !configuration) {
    return (
      <div className="performanceLocalDelivery" data-delivery-mode={delivery.mode}>
        <DeliverySafetyLabel delivery={delivery} />
        <PerformanceLocalDeliveryBlocked delivery={delivery} />
      </div>
    );
  }

  let presentation;
  try {
    presentation = themePresentation(
      delivery.composition.resolved_theme,
      delivery.website_configuration.website_id,
      viewportWidth,
    );
  } catch (value) {
    return (
      <DeliveryState
        message={performanceLocalDeliveryFailureMessage(requestedMode, value)}
        error
      />
    );
  }

  const formSubmission = configuration.formSubmission.endpoint
    ? {
        ...configuration.formSubmission,
        submit: async (
          payload: PerformanceLocalFormSubmissionPayload,
          idempotencyKey: string,
        ) => submitPerformanceLocalForm(delivery, payload, idempotencyKey),
      }
    : configuration.formSubmission;

  return (
    <div
      className="performanceLocalDelivery"
      data-delivery-mode={delivery.mode}
      data-renderer-contract={delivery.renderer_contract}
      data-theme-family-id={delivery.theme_family.id}
      data-theme-version-id={delivery.theme_version.id}
      data-website-configuration-id={delivery.website_configuration.id}
    >
      <DeliverySafetyLabel delivery={delivery} />
      <section
        className="performanceLocalDeliveryCanvas"
        aria-label="Performance Local website"
        style={presentation.style}
        {...presentation.attributes}
      >
        <PerformanceLocalRenderer
          campaign={configuration.campaign}
          composition={delivery.composition}
          estimateForm={configuration.estimateForm}
          formSubmission={formSubmission}
          governedContact={configuration.governedContact}
          page={delivery.page}
          rendererIdentity={configuration.rendererIdentity}
          stickyActions={configuration.stickyActions}
          toggles={configuration.toggles}
        />
      </section>
    </div>
  );
}

async function submitPerformanceLocalForm(
  delivery: PerformanceLocalDeliveryRead,
  payload: PerformanceLocalFormSubmissionPayload,
  idempotencyKey: string,
): Promise<PerformanceLocalSubmissionAcceptedRead> {
  const readiness = delivery.form_readiness;
  const componentConfigurationId = readiness.component_configuration_id;
  const csrfToken = readiness.security.csrf_token;
  if (
    readiness.status !== "ready" ||
    readiness.can_submit !== true ||
    !positiveInteger(componentConfigurationId) ||
    !safeIdempotencyKey(idempotencyKey) ||
    !safeCsrfToken(csrfToken)
  ) {
    throw new Error("Form submission is not available.");
  }
  return apiRequest<PerformanceLocalSubmissionAcceptedRead>(
    `/api/websites/${delivery.website_configuration.website_id}/forms/${componentConfigurationId}/submissions`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
        "X-Atlas-CSRF-Token": csrfToken,
      },
      body: JSON.stringify(payload),
    },
  );
}

function DeliverySafetyLabel({ delivery }: { delivery: PerformanceLocalDeliveryRead }) {
  if (!delivery.non_active_label) return null;
  return (
    <div className="performanceLocalDeliverySafetyLabel" role="status">
      <ShieldCheck size={18} aria-hidden="true" />
      <strong>{delivery.non_active_label}</strong>
      <span>
        {delivery.mode === "activation_rehearsal"
          ? "Disposable internal rehearsal · never public"
          : "Explicit local operator preview · never active or public"}
      </span>
    </div>
  );
}

export function PerformanceLocalDeliveryBlocked({
  delivery,
}: {
  delivery: PerformanceLocalDeliveryRead;
}) {
  const exposeOperatorDetail = delivery.mode !== "active";
  return (
    <main className="performanceLocalDeliveryBlocked" role="alert">
      <AlertTriangle size={28} aria-hidden="true" />
      <p className="performanceLocalDeliveryEyebrow">Fail-closed delivery gate</p>
      <h1>Performance Local delivery unavailable</h1>
      <p>The exact server-resolved configuration is not eligible to render this page.</p>
      {exposeOperatorDetail ? <code>{delivery.renderer_result.result_code}</code> : null}
      {exposeOperatorDetail && delivery.blockers.length ? (
        <ul>
          {delivery.blockers.map((blocker) => (
            <li key={`${blocker.category}:${blocker.code}`}>
              <strong>{blocker.category}</strong> {blocker.reason}
            </li>
          ))}
        </ul>
      ) : null}
    </main>
  );
}

function DeliveryState({ message, error = false }: { message: string; error?: boolean }) {
  return (
    <main className="performanceLocalDeliveryState" role={error ? "alert" : "status"}>
      {error ? <AlertTriangle size={26} aria-hidden="true" /> : null}
      <h1>{error ? "Performance Local delivery unavailable" : "Performance Local delivery"}</h1>
      <p>{message}</p>
    </main>
  );
}

function useViewportWidth(): number {
  const [width, setWidth] = useState(() => window.innerWidth);
  useEffect(() => {
    const update = () => setWidth(window.innerWidth);
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);
  return width;
}

function positiveInteger(value: unknown): number | null {
  const numeric = typeof value === "string" && value.trim() ? Number(value) : value;
  return typeof numeric === "number" && Number.isSafeInteger(numeric) && numeric > 0
    ? numeric
    : null;
}

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function safeIdempotencyKey(value: unknown): value is string {
  return typeof value === "string" && value.length >= 32 && value.length <= 128 &&
    /^[A-Za-z0-9._~-]+$/.test(value);
}

function safeCsrfToken(value: unknown): value is string {
  return typeof value === "string" && value.length >= 16 && value.length <= 512 &&
    /^[A-Za-z0-9._~+\/-]+$/.test(value);
}

export default PerformanceLocalDeliveryPage;
