import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { CheckCircle2, ImagePlus, ShieldCheck } from "lucide-react";

import { apiRequest } from "../api";
import type { Brand, BrandAsset, WebsiteIdentity, WebsiteIdentityAssets } from "../types";

const assetTypes = [
  "primary_logo", "alternate_logo", "brand_mark", "favicon",
  "browser_icon", "apple_touch_icon", "open_graph_image"
];
const usages = ["website_header", "website_footer", "browser_tab", "social_preview", "reports", "login_screen"];
const slots = ["header_logo", "footer_logo", "favicon", "browser_icon", "apple_touch_icon", "open_graph_image"] as const;
type IdentitySlot = (typeof slots)[number];
const slotContracts: Record<IdentitySlot, { assetTypes: readonly string[]; requiredUsage: string }> = {
  header_logo: { assetTypes: ["primary_logo", "alternate_logo", "brand_mark"], requiredUsage: "website_header" },
  footer_logo: { assetTypes: ["primary_logo", "alternate_logo", "brand_mark"], requiredUsage: "website_footer" },
  favicon: { assetTypes: ["favicon"], requiredUsage: "browser_tab" },
  browser_icon: { assetTypes: ["browser_icon"], requiredUsage: "browser_tab" },
  apple_touch_icon: { assetTypes: ["apple_touch_icon"], requiredUsage: "browser_tab" },
  open_graph_image: { assetTypes: ["open_graph_image"], requiredUsage: "social_preview" }
};

export default function BrandAssetsPage() {
  const [brands, setBrands] = useState<Brand[]>([]);
  const [identities, setIdentities] = useState<WebsiteIdentity[]>([]);
  const [assets, setAssets] = useState<BrandAsset[]>([]);
  const [selections, setSelections] = useState<WebsiteIdentityAssets | null>(null);
  const [brandId, setBrandId] = useState(0);
  const [identityId, setIdentityId] = useState(0);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);

  async function load(selectedBrand = brandId, selectedIdentity = identityId) {
    const [brandRows, identityRows] = await Promise.all([
      apiRequest<Brand[]>("/api/brands"),
      apiRequest<WebsiteIdentity[]>("/api/website-identities")
    ]);
    const nextBrand = selectedBrand || brandRows[0]?.id || 0;
    const nextIdentity = selectedIdentity || identityRows[0]?.id || 0;
    setBrands(brandRows); setIdentities(identityRows); setBrandId(nextBrand); setIdentityId(nextIdentity);
    setAssets(nextBrand ? await apiRequest<BrandAsset[]>(`/api/brand-assets?brand_id=${nextBrand}`) : []);
    setSelections(nextIdentity ? await apiRequest<WebsiteIdentityAssets>(`/api/website-identities/${nextIdentity}/assets`) : null);
  }

  useEffect(() => { void load().catch(value => setError(value instanceof Error ? value.message : "Unable to load Brand Assets.")); }, []);

  async function submitUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setWorking(true); setError(""); setMessage("");
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    form.set("business_id", String(brands.find(item => item.id === brandId)?.business_id ?? ""));
    form.set("brand_id", String(brandId));
    form.set("approved_usage", JSON.stringify(form.getAll("usage")));
    form.set("restrictions", JSON.stringify(form.getAll("restriction")));
    if (!form.get("replaces_brand_asset_id")) form.delete("replaces_brand_asset_id");
    form.delete("usage"); form.delete("restriction");
    try {
      const created = await apiRequest<BrandAsset>("/api/brand-assets/upload", { method: "POST", body: form });
      setMessage(`${created.asset_key} version ${created.version} is pending review.`);
      formElement.reset(); await load(brandId, identityId);
    } catch (value) { setError(value instanceof Error ? value.message : "Upload failed."); }
    finally { setWorking(false); }
  }

  async function approve(asset: BrandAsset) {
    const approvedBy = window.prompt("Operator name for approval provenance:");
    if (!approvedBy) return;
    setWorking(true); setError("");
    try {
      await apiRequest(`/api/brand-assets/${asset.id}/approve`, { method: "POST", body: JSON.stringify({ approved_by: approvedBy }) });
      setMessage(`${asset.asset_key} version ${asset.version} approved.`); await load(brandId, identityId);
    } catch (value) { setError(value instanceof Error ? value.message : "Approval failed."); }
    finally { setWorking(false); }
  }

  async function assign(slot: string, assetId: number) {
    if (!identityId || !assetId) return;
    const assignedBy = window.prompt("Operator name for selection provenance:");
    if (!assignedBy) return;
    setWorking(true); setError("");
    try {
      await apiRequest(`/api/website-identities/${identityId}/assets/assign`, {
        method: "POST", body: JSON.stringify({ brand_asset_id: assetId, slot, assigned_by: assignedBy, rationale: "Approved Website Identity selection" })
      });
      setMessage(`${humanize(slot)} selection updated with version history preserved.`); await load(brandId, identityId);
    } catch (value) { setError(value instanceof Error ? value.message : "Selection failed."); }
    finally { setWorking(false); }
  }

  async function retire(asset: BrandAsset) {
    const retiredBy = window.prompt("Operator name for retirement provenance:");
    if (!retiredBy) return;
    const rationale = window.prompt("Why is this asset being retired?");
    if (!rationale) return;
    setWorking(true); setError("");
    try {
      await apiRequest(`/api/brand-assets/${asset.id}/retire`, {
        method: "POST", body: JSON.stringify({ retired_by: retiredBy, rationale })
      });
      setMessage(`${asset.asset_key} version ${asset.version} retired with history preserved.`); await load(brandId, identityId);
    } catch (value) { setError(value instanceof Error ? value.message : "Retirement failed."); }
    finally { setWorking(false); }
  }

  const approved = useMemo(() => assets.filter(item =>
    item.status === "approved" &&
    !assets.some(candidate => candidate.status === "approved" && candidate.replaces_brand_asset_id === item.id)
  ), [assets]);
  return <section className="page brandAssetsPage">
    <header className="pageHeader"><div><span className="eyebrow">Visual identity governance</span><h1>Brand Assets</h1><p>Approve owned visual identity, then select it explicitly for one Website Identity. Assets contain no business facts or layout rules.</p></div></header>
    {error && <div className="errorBanner">{error}</div>}{message && <div className="successBanner">{message}</div>}
    <section className="panel"><h2>Asset library</h2><div className="fieldGrid"><label>Brand<select value={brandId} onChange={event => { const value=Number(event.target.value); setBrandId(value); void load(value, identityId); }}>{brands.map(item => <option key={item.id} value={item.id}>{item.brand_name}</option>)}</select></label><label>Website Identity<select value={identityId} onChange={event => { const value=Number(event.target.value); setIdentityId(value); void load(brandId, value); }}>{identities.map(item => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select></label></div>
      <div className="brandAssetGrid">{assets.map(asset => <article className="brandAssetCard" key={asset.id}><img src={asset.thumbnail_url || asset.asset_url} alt={asset.accessibility_description}/><div><span className={`statusBadge ${asset.status}`}>{humanize(asset.status)}</span><h3>{humanize(asset.asset_key)} <small>v{asset.version}</small></h3><p><strong>Purpose:</strong> {asset.purpose}</p><p><strong>Approved:</strong> {asset.approved_usage.map(humanize).join(", ")}</p><p><strong>Never:</strong> {asset.restrictions.length ? asset.restrictions.map(humanize).join(", ") : "No additional restrictions"}</p><p><strong>Accessibility:</strong> {asset.accessibility_description}</p><p className="helperText">{asset.width}×{asset.height} · {asset.provenance_type} · rights {asset.rights_status} · SHA-256 {asset.checksum_sha256.slice(0, 12)}…</p>{asset.status === "pending_review" && <button disabled={working} onClick={() => void approve(asset)}><ShieldCheck size={16}/>Approve asset</button>}{asset.status !== "retired" && <button disabled={working} onClick={() => void retire(asset)}>Retire asset</button>}</div></article>)}</div>
    </section>
    <section className="panel"><h2><ImagePlus size={20}/> Add governed asset</h2><form onSubmit={submitUpload}><div className="fieldGrid"><label>Image<input name="file" type="file" accept="image/png,image/jpeg,image/webp" required/></label><label>Asset key<input name="asset_key" pattern="[a-z0-9_-]+" required placeholder="primary-logo"/></label><label>Explicit replacement<select name="replaces_brand_asset_id"><option value="">New asset key</option>{assets.map(asset => <option value={asset.id} key={asset.id}>{humanize(asset.asset_key)} v{asset.version}</option>)}</select></label><label>Type<select name="asset_type">{assetTypes.map(value => <option key={value} value={value}>{humanize(value)}</option>)}</select></label><label>Variant<input name="variant_key" defaultValue="default" required/></label><label>Purpose<textarea name="purpose" required/></label><label>Accessible description / alt-text intent<textarea name="accessibility_description" required/></label><label>Provenance<select name="provenance_type"><option value="company_original">Company original</option><option value="commissioned">Commissioned</option><option value="licensed">Licensed</option><option value="public_domain">Public domain</option></select></label><label>Provenance notes<textarea name="provenance_notes"/></label><label>Rights status<select name="rights_status"><option value="owned">Owned</option><option value="commissioned">Commissioned</option><option value="licensed">Licensed</option><option value="public_domain">Public domain</option></select></label><label>Rights holder<input name="rights_holder"/></label><label>Rights notes<textarea name="rights_notes"/></label><label>Created by<input name="created_by" required/></label></div><fieldset><legend>Approved usage</legend>{usages.map(value => <label className="inlineCheck" key={value}><input type="checkbox" name="usage" value={value}/>{humanize(value)}</label>)}</fieldset><fieldset><legend>Restrictions</legend>{usages.map(value => <label className="inlineCheck" key={value}><input type="checkbox" name="restriction" value={value}/>{humanize(value)}</label>)}</fieldset><button className="primaryButton" disabled={working}>Upload for review</button></form></section>
    <section className="panel"><h2>Website Identity selections</h2><p>Only approved assets compatible with each semantic slot can be selected. Replacements create durable assignment history.</p><div className="identitySlotGrid">{slots.map(slot => { const current=selections?.active[slot]; const compatible = approved.filter(asset => isCompatibleWithSlot(asset, slot)); return <article key={slot}><h3>{humanize(slot)}</h3>{current?.asset ? <p><CheckCircle2 size={15}/> {humanize(current.asset.asset_key)} v{current.asset.version}</p> : <p className="helperText">Selection required</p>}<select value="" disabled={working} onChange={event => void assign(slot, Number(event.target.value))}><option value="">Select approved asset…</option>{compatible.map(asset => <option key={asset.id} value={asset.id}>{humanize(asset.asset_key)} v{asset.version} ({humanize(asset.asset_type)})</option>)}</select></article>; })}</div><p className="helperText">Selection history: {selections?.history.length ?? 0} durable record(s).</p></section>
  </section>;
}

function humanize(value: string) { return value.replace(/_/g, " ").replace(/\b\w/g, character => character.toUpperCase()); }
function isCompatibleWithSlot(asset: BrandAsset, slot: IdentitySlot) {
  const contract = slotContracts[slot];
  return contract.assetTypes.includes(asset.asset_type) &&
    asset.approved_usage.includes(contract.requiredUsage) &&
    !asset.restrictions.includes(contract.requiredUsage);
}
