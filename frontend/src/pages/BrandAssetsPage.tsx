import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { CheckCircle2, ImagePlus, ShieldCheck } from "lucide-react";

import { apiRequest } from "../api";
import {
  IDENTITY_SLOTS,
  bindWebsiteContext,
  currentApprovedAssets,
  isAssetCompatibleWithSlot,
  validateContextOwnedAssets,
  validateIdentitySelections,
} from "../components/brandAssetContext";
import type { BrandAssetContextBinding } from "../components/brandAssetContext";
import type {
  BrandAsset,
  Website,
  WebsiteContext,
  WebsiteIdentityAssets,
} from "../types";

const assetTypes = [
  "primary_logo",
  "alternate_logo",
  "brand_mark",
  "favicon",
  "browser_icon",
  "apple_touch_icon",
  "open_graph_image",
];
const usages = [
  "website_header",
  "website_footer",
  "browser_tab",
  "social_preview",
  "reports",
  "login_screen",
];

export default function BrandAssetsPage() {
  const [websites, setWebsites] = useState<Website[]>([]);
  const [websiteId, setWebsiteId] = useState(0);
  const [context, setContext] = useState<WebsiteContext | null>(null);
  const [binding, setBinding] = useState<BrandAssetContextBinding | null>(null);
  const [assets, setAssets] = useState<BrandAsset[]>([]);
  const [selections, setSelections] = useState<WebsiteIdentityAssets | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);
  const [contextLoading, setContextLoading] = useState(false);
  const loadGeneration = useRef(0);

  useEffect(() => {
    async function loadWebsites() {
      try {
        const rows = await apiRequest<Website[]>("/api/websites");
        setWebsites(rows);
        setWebsiteId(rows[0]?.id ?? 0);
      } catch (value) {
        setError(value instanceof Error ? value.message : "Unable to load Websites.");
      }
    }
    void loadWebsites();
  }, []);

  useEffect(() => {
    if (websiteId) void loadWebsiteContext(websiteId);
    else clearContext();
  }, [websiteId, websites]);

  function clearContext() {
    loadGeneration.current += 1;
    setContext(null);
    setBinding(null);
    setAssets([]);
    setSelections(null);
  }

  async function loadWebsiteContext(selectedWebsiteId: number) {
    const generation = ++loadGeneration.current;
    const website = websites.find((item) => item.id === selectedWebsiteId);
    if (!website) {
      clearContext();
      return;
    }
    setContextLoading(true);
    setError("");
    setContext(null);
    setBinding(null);
    setAssets([]);
    setSelections(null);
    try {
      const nextContext = await apiRequest<WebsiteContext>(
        `/api/websites/${selectedWebsiteId}/context`,
      );
      const nextBinding = bindWebsiteContext(website, nextContext);
      const [assetRows, selectionRows] = await Promise.all([
        apiRequest<BrandAsset[]>(
          `/api/brand-assets?brand_id=${nextBinding.brandId}`,
        ),
        apiRequest<WebsiteIdentityAssets>(
          `/api/website-identities/${nextBinding.identityId}/assets`,
        ),
      ]);
      const ownedAssets = validateContextOwnedAssets(assetRows, nextBinding);
      const ownedSelections = validateIdentitySelections(
        selectionRows,
        nextBinding,
      );
      if (generation !== loadGeneration.current) return;
      setContext(nextContext);
      setBinding(nextBinding);
      setAssets(ownedAssets);
      setSelections(ownedSelections);
    } catch (value) {
      if (generation !== loadGeneration.current) return;
      setError(
        value instanceof Error
          ? value.message
          : "Unable to load the authoritative Website Context.",
      );
    } finally {
      if (generation === loadGeneration.current) setContextLoading(false);
    }
  }

  async function reloadContext() {
    if (websiteId) await loadWebsiteContext(websiteId);
  }

  function requireOwnedAsset(asset: BrandAsset): boolean {
    if (
      !binding ||
      asset.business_id !== binding.businessId ||
      asset.brand_id !== binding.brandId
    ) {
      setError(
        "The selected asset does not belong to the authoritative Website Context.",
      );
      return false;
    }
    return true;
  }

  async function submitUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!binding) {
      setError("Select a valid Website Context before adding a Brand Asset.");
      return;
    }
    setWorking(true);
    setError("");
    setMessage("");
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const restrictionValues = form.getAll("restriction");
    if (!hasProhibitedUsageDecision(restrictionValues)) {
      setError("Select at least one prohibited usage before submitting the asset.");
      setWorking(false);
      return;
    }
    form.set("business_id", String(binding.businessId));
    form.set("brand_id", String(binding.brandId));
    form.set("approved_usage", JSON.stringify(form.getAll("usage")));
    form.set("restrictions", JSON.stringify(restrictionValues));
    if (!form.get("replaces_brand_asset_id")) {
      form.delete("replaces_brand_asset_id");
    }
    form.delete("usage");
    form.delete("restriction");
    try {
      const created = await apiRequest<BrandAsset>("/api/brand-assets/upload", {
        method: "POST",
        body: form,
      });
      if (!requireOwnedAsset(created)) return;
      setMessage(`${created.asset_key} version ${created.version} is pending review.`);
      formElement.reset();
      await reloadContext();
    } catch (value) {
      setError(value instanceof Error ? value.message : "Upload failed.");
    } finally {
      setWorking(false);
    }
  }

  async function approve(asset: BrandAsset) {
    if (!requireOwnedAsset(asset)) return;
    const approvedBy = window.prompt("Operator name for approval provenance:");
    if (!approvedBy) return;
    setWorking(true);
    setError("");
    try {
      await apiRequest(`/api/brand-assets/${asset.id}/approve`, {
        method: "POST",
        body: JSON.stringify({ approved_by: approvedBy }),
      });
      setMessage(`${asset.asset_key} version ${asset.version} approved.`);
      await reloadContext();
    } catch (value) {
      setError(value instanceof Error ? value.message : "Approval failed.");
    } finally {
      setWorking(false);
    }
  }

  async function assign(slot: (typeof IDENTITY_SLOTS)[number], assetId: number) {
    const asset = assets.find((item) => item.id === assetId);
    if (!binding || !assetId || !asset || !requireOwnedAsset(asset)) return;
    if (!isAssetCompatibleWithSlot(asset, slot, binding)) {
      setError("The selected asset is not compatible with this Website Identity slot.");
      return;
    }
    const assignedBy = window.prompt("Operator name for selection provenance:");
    if (!assignedBy) return;
    const rationale = window.prompt(
      "Rationale for this Website Identity asset selection:",
    );
    if (!rationale?.trim()) return;
    setWorking(true);
    setError("");
    try {
      await apiRequest(
        `/api/website-identities/${binding.identityId}/assets/assign`,
        {
          method: "POST",
          body: JSON.stringify({
            brand_asset_id: assetId,
            slot,
            assigned_by: assignedBy,
            rationale: rationale.trim(),
          }),
        },
      );
      setMessage(
        `${humanize(slot)} selection updated with version history preserved.`,
      );
      await reloadContext();
    } catch (value) {
      setError(value instanceof Error ? value.message : "Selection failed.");
    } finally {
      setWorking(false);
    }
  }

  async function retire(asset: BrandAsset) {
    if (!requireOwnedAsset(asset)) return;
    const retiredBy = window.prompt("Operator name for retirement provenance:");
    if (!retiredBy) return;
    const rationale = window.prompt("Why is this asset being retired?");
    if (!rationale) return;
    setWorking(true);
    setError("");
    try {
      await apiRequest(`/api/brand-assets/${asset.id}/retire`, {
        method: "POST",
        body: JSON.stringify({ retired_by: retiredBy, rationale }),
      });
      setMessage(
        `${asset.asset_key} version ${asset.version} retired with history preserved.`,
      );
      await reloadContext();
    } catch (value) {
      setError(value instanceof Error ? value.message : "Retirement failed.");
    } finally {
      setWorking(false);
    }
  }

  const approved = useMemo(() => currentApprovedAssets(assets), [assets]);

  return (
    <section className="page brandAssetsPage">
      <header className="pageHeader">
        <div>
          <span className="eyebrow">Visual identity governance</span>
          <h1>Brand Assets</h1>
          <p>
            Approve owned visual identity, then select it explicitly for one
            Website Identity. Assets contain no business facts or layout rules.
          </p>
        </div>
      </header>

      {error && <div className="errorBanner">{error}</div>}
      {message && <div className="successBanner">{message}</div>}

      <section className="panel">
        <h2>Authoritative Website Context</h2>
        <p>
          Brand Asset ownership and Website Identity selections are derived from
          one Website. Brand and Identity cannot be selected independently.
        </p>
        <label>
          Website
          <select
            value={websiteId}
            disabled={working || contextLoading}
            onChange={(event) => {
              setMessage("");
              setWebsiteId(Number(event.target.value));
            }}
          >
            {!websites.length && <option value={0}>No Websites available</option>}
            {websites.map((website) => (
              <option key={website.id} value={website.id}>
                {website.website_name} ({website.domain})
              </option>
            ))}
          </select>
        </label>
        {contextLoading && <p className="helperText">Loading Website Context…</p>}
        {context && binding && (
          <dl className="detailGrid brandAssetContextSummary">
            <div>
              <dt>Business</dt>
              <dd>{context.business.company_name}</dd>
            </div>
            <div>
              <dt>Brand</dt>
              <dd>{context.brand.public_name}</dd>
            </div>
            <div>
              <dt>Website Identity</dt>
              <dd>{context.identity.display_name}</dd>
            </div>
            <div>
              <dt>Ownership binding</dt>
              <dd>
                Website {binding.websiteId} · Business {binding.businessId} · Brand{" "}
                {binding.brandId} · Identity {binding.identityId}
              </dd>
            </div>
          </dl>
        )}
      </section>

      <section className="panel">
        <h2>Asset library</h2>
        {!binding && (
          <p className="helperText">
            A valid persisted Website Context is required before assets can be
            displayed.
          </p>
        )}
        {binding && assets.length === 0 && (
          <p className="helperText">
            No governed assets exist for this Website&apos;s Brand.
          </p>
        )}
        <div className="brandAssetGrid">
          {assets.map((asset) => (
            <article className="brandAssetCard" key={asset.id}>
              <img
                src={asset.thumbnail_url || asset.asset_url}
                alt={asset.accessibility_description}
              />
              <div>
                <span className={`statusBadge ${asset.status}`}>
                  {humanize(asset.status)}
                </span>
                <h3>
                  {humanize(asset.asset_key)} <small>v{asset.version}</small>
                </h3>
                <BrandAssetEvidence asset={asset} />
                {asset.status === "pending_review" && (
                  <button disabled={working} onClick={() => void approve(asset)}>
                    <ShieldCheck size={16} /> Approve asset
                  </button>
                )}
                {asset.status !== "retired" && (
                  <button disabled={working} onClick={() => void retire(asset)}>
                    Retire asset
                  </button>
                )}
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="panel">
        <h2>
          <ImagePlus size={20} /> Add governed asset
        </h2>
        {!binding ? (
          <p className="helperText">
            Resolve the authoritative Website Context before uploading an asset.
          </p>
        ) : (
          <form onSubmit={submitUpload}>
            <div className="fieldGrid">
              <label>
                Image
                <input
                  name="file"
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  required
                />
              </label>
              <label>
                Asset key
                <input
                  name="asset_key"
                  pattern="[a-z0-9_-]+"
                  required
                  placeholder="primary-logo"
                />
              </label>
              <label>
                Explicit replacement
                <select name="replaces_brand_asset_id">
                  <option value="">New asset key</option>
                  {assets.map((asset) => (
                    <option value={asset.id} key={asset.id}>
                      {humanize(asset.asset_key)} v{asset.version}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Type
                <select name="asset_type">
                  {assetTypes.map((value) => (
                    <option key={value} value={value}>
                      {humanize(value)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Variant
                <input name="variant_key" defaultValue="default" required />
              </label>
              <label>
                Purpose
                <textarea name="purpose" required />
              </label>
              <label>
                Accessible description / alt-text intent
                <textarea name="accessibility_description" required />
              </label>
              <label>
                Provenance
                <select name="provenance_type">
                  <option value="company_original">Company original</option>
                  <option value="commissioned">Commissioned</option>
                  <option value="licensed">Licensed</option>
                  <option value="public_domain">Public domain</option>
                </select>
              </label>
              <label>
                Provenance notes
                <textarea name="provenance_notes" required />
              </label>
              <label>
                Rights status
                <select name="rights_status">
                  <option value="owned">Owned</option>
                  <option value="commissioned">Commissioned</option>
                  <option value="licensed">Licensed</option>
                  <option value="public_domain">Public domain</option>
                </select>
              </label>
              <label>
                Rights holder
                <input name="rights_holder" required />
              </label>
              <label>
                Rights notes
                <textarea name="rights_notes" required />
              </label>
              <label>
                Creator / source identity
                <input name="created_by" required />
              </label>
            </div>
            <fieldset>
              <legend>Approved usage</legend>
              {usages.map((value) => (
                <label className="inlineCheck" key={value}>
                  <input type="checkbox" name="usage" value={value} />
                  {humanize(value)}
                </label>
              ))}
            </fieldset>
            <fieldset>
              <legend>Restrictions</legend>
              <p className="helperText">
                Select at least one prohibited usage. An explicit restriction
                decision is required for every governed asset.
              </p>
              {usages.map((value) => (
                <label className="inlineCheck" key={value}>
                  <input type="checkbox" name="restriction" value={value} />
                  {humanize(value)}
                </label>
              ))}
            </fieldset>
            <button className="primaryButton" disabled={working}>
              Upload for review
            </button>
          </form>
        )}
      </section>

      <section className="panel">
        <h2>Website Identity selections</h2>
        <p>
          Only current approved assets owned by this Website Context and compatible
          with each semantic slot can be selected. Replacements preserve durable
          assignment history.
        </p>
        <div className="identitySlotGrid">
          {IDENTITY_SLOTS.map((slot) => {
            const current = selections?.active[slot];
            const compatible = binding
              ? approved.filter((asset) =>
                  isAssetCompatibleWithSlot(asset, slot, binding),
                )
              : [];
            return (
              <article key={slot}>
                <h3>{humanize(slot)}</h3>
                {current?.asset ? (
                  <p>
                    <CheckCircle2 size={15} /> {humanize(current.asset.asset_key)} v
                    {current.asset.version}
                  </p>
                ) : (
                  <p className="helperText">Selection required</p>
                )}
                <select
                  value=""
                  disabled={working || contextLoading || !binding}
                  onChange={(event) => void assign(slot, Number(event.target.value))}
                >
                  <option value="">Select approved asset…</option>
                  {compatible.map((asset) => (
                    <option key={asset.id} value={asset.id}>
                      {humanize(asset.asset_key)} v{asset.version} (
                      {humanize(asset.asset_type)})
                    </option>
                  ))}
                </select>
              </article>
            );
          })}
        </div>
        <p className="helperText">
          Selection history: {selections?.history.length ?? 0} durable record(s).
        </p>
      </section>
    </section>
  );
}

function humanize(value: string) {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

export function BrandAssetEvidence({ asset }: { asset: BrandAsset }) {
  return (
    <dl className="brandAssetEvidence">
      <div>
        <dt>Version context</dt>
        <dd>
          Version {asset.version} ·{" "}
          {asset.replaces_brand_asset_id
            ? `Replaces Brand Asset ${asset.replaces_brand_asset_id}`
            : "Original version"}
        </dd>
      </div>
      <div>
        <dt>Asset contract</dt>
        <dd>
          {humanize(asset.asset_type)} · {humanize(asset.variant_key)} variant
        </dd>
      </div>
      <div>
        <dt>Purpose</dt>
        <dd>{asset.purpose}</dd>
      </div>
      <div>
        <dt>Approved usage</dt>
        <dd>{asset.approved_usage.map(humanize).join(", ")}</dd>
      </div>
      <div>
        <dt>Prohibited usage</dt>
        <dd>
          {asset.restrictions.length
            ? asset.restrictions.map(humanize).join(", ")
            : "No prohibited usage recorded"}
        </dd>
      </div>
      <div>
        <dt>Accessibility</dt>
        <dd>{asset.accessibility_description}</dd>
      </div>
      <div>
        <dt>Original filename</dt>
        <dd>{asset.original_filename}</dd>
      </div>
      <div>
        <dt>MIME type</dt>
        <dd>{asset.mime_type}</dd>
      </div>
      <div>
        <dt>Exact file evidence</dt>
        <dd>
          {asset.file_size} bytes · {asset.width}×{asset.height} pixels
        </dd>
      </div>
      <div>
        <dt>SHA-256</dt>
        <dd>
          <code>{asset.checksum_sha256}</code>
        </dd>
      </div>
      <div>
        <dt>Provenance classification</dt>
        <dd>{humanize(asset.provenance_type)}</dd>
      </div>
      <div>
        <dt>Provenance notes</dt>
        <dd>{asset.provenance_notes || "Not recorded"}</dd>
      </div>
      <div>
        <dt>Rights status</dt>
        <dd>{humanize(asset.rights_status)}</dd>
      </div>
      <div>
        <dt>Rights holder</dt>
        <dd>{asset.rights_holder || "Not recorded"}</dd>
      </div>
      <div>
        <dt>Rights notes</dt>
        <dd>{asset.rights_notes || "Not recorded"}</dd>
      </div>
      <div>
        <dt>Creator / source identity</dt>
        <dd>{asset.created_by}</dd>
      </div>
    </dl>
  );
}

export function hasProhibitedUsageDecision(values: unknown[]): boolean {
  return values.some(
    (value) => typeof value === "string" && value.trim().length > 0,
  );
}
