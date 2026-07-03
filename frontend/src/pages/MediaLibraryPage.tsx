import { CSSProperties, FormEvent, MouseEvent as ReactMouseEvent, ReactNode, useEffect, useMemo, useState } from "react";
import { CheckCircle2, Crosshair, ImagePlus, LocateFixed, Pencil, Upload } from "lucide-react";

import { listItems, updateItem, uploadMedia } from "../api";
import type { Business, City, County, ImageMetadata, Service } from "../types";

type UploadForm = {
  business_id: string;
  service_id: string;
  county_id: string;
  city_id: string;
  image_title: string;
  image_role: string;
  notes: string;
};

const emptyUpload: UploadForm = {
  business_id: "",
  service_id: "",
  county_id: "",
  city_id: "",
  image_title: "",
  image_role: "support",
  notes: ""
};

function MediaLibraryPage() {
  const [images, setImages] = useState<ImageMetadata[]>([]);
  const [businesses, setBusinesses] = useState<Business[]>([]);
  const [services, setServices] = useState<Service[]>([]);
  const [counties, setCounties] = useState<County[]>([]);
  const [cities, setCities] = useState<City[]>([]);
  const [uploadForm, setUploadForm] = useState<UploadForm>(emptyUpload);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [selected, setSelected] = useState<ImageMetadata | null>(null);
  const [filter, setFilter] = useState("all");
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function loadData() {
    try {
      const [imageData, businessData, serviceData, countyData, cityData] = await Promise.all([
        listItems<ImageMetadata>("/api/image-metadata"),
        listItems<Business>("/api/businesses"),
        listItems<Service>("/api/services"),
        listItems<County>("/api/counties"),
        listItems<City>("/api/cities")
      ]);
      setImages(imageData);
      setBusinesses(businessData);
      setServices(serviceData);
      setCounties(countyData);
      setCities(cityData);
      setUploadForm((current) => ({
        ...current,
        business_id: current.business_id || String(businessData[0]?.id ?? ""),
        service_id: current.service_id || String(serviceData[0]?.id ?? "")
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load the media library.");
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  const visibleImages = useMemo(
    () => images.filter((image) => filter === "all" || (filter === "pending_review" ? isPending(image) : image.review_status === filter)),
    [filter, images]
  );

  const uploadCities = useMemo(
    () => cities.filter((city) => !uploadForm.county_id || city.county_id === Number(uploadForm.county_id)),
    [cities, uploadForm.county_id]
  );

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!uploadFile) {
      setError("Choose an image before uploading.");
      return;
    }
    setUploading(true);
    setError(null);
    setNotice(null);
    const payload = new FormData();
    payload.append("file", uploadFile);
    Object.entries(uploadForm).forEach(([key, value]) => {
      if (value) payload.append(key, value);
    });
    try {
      const created = await uploadMedia<ImageMetadata>(payload);
      setUploadFile(null);
      setUploadForm((current) => ({ ...emptyUpload, business_id: current.business_id, service_id: current.service_id }));
      setSelected(created);
      setNotice("Upload optimized and added for review.");
      await loadData();
    } catch (err) {
      setError(readApiError(err));
    } finally {
      setUploading(false);
    }
  }

  async function saveReview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    if (selected.review_status === "reviewed" && !selected.reviewed_alt_text?.trim()) {
      setError("Reviewed alt text is required before marking an image reviewed.");
      return;
    }
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await updateItem<ImageMetadata>("/api/image-metadata", selected.id, {
        image_title: selected.image_title,
        reviewed_alt_text: selected.reviewed_alt_text,
        service_id: selected.service_id ?? null,
        county_id: selected.county_id ?? null,
        city_id: selected.city_id ?? null,
        focal_x: selected.focal_x,
        focal_y: selected.focal_y,
        image_role: selected.image_role,
        review_status: selected.review_status,
        notes: selected.notes
      });
      setSelected(updated);
      setNotice(updated.review_status === "reviewed" ? "Image reviewed and available for assignment." : "Media details saved.");
      await loadData();
    } catch (err) {
      setError(readApiError(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="page">
      <header className="pageHeader">
        <div>
          <p className="eyebrow">Review workspace</p>
          <h1>Media Library</h1>
        </div>
        <div className="mediaStats">
          <span>{images.filter(isPending).length} pending</span>
          <span>{images.filter((image) => image.review_status === "reviewed").length} reviewed</span>
        </div>
      </header>

      {error && <div className="alert">{error}</div>}
      {notice && <div className="successAlert">{notice}</div>}

      <div className="mediaWorkspace">
        <section className="panel mediaUploadPanel">
          <div className="sectionTitle">
            <ImagePlus size={20} aria-hidden="true" />
            <div>
              <h2>Upload Image</h2>
              <p>JPEG, PNG, or WebP. Maximum 10 MB.</p>
            </div>
          </div>
          <form className="recordForm" onSubmit={handleUpload}>
            <label className="filePicker">
              <Upload size={22} aria-hidden="true" />
              <span>{uploadFile?.name ?? "Choose image"}</span>
              <input
                type="file"
                accept="image/jpeg,image/png,image/webp"
                onChange={(event) => setUploadFile(event.target.files?.[0] ?? null)}
              />
            </label>
            <label>
              <span>Image Title</span>
              <input value={uploadForm.image_title} onChange={(event) => setUpload("image_title", event.target.value)} />
            </label>
            <div className="formRow">
              <SelectField label="Business" value={uploadForm.business_id} onChange={(value) => setUpload("business_id", value)} required>
                {businesses.map((business) => <option key={business.id} value={business.id}>{business.brand_name || business.company_name}</option>)}
              </SelectField>
              <SelectField label="Service" value={uploadForm.service_id} onChange={(value) => setUpload("service_id", value)}>
                <option value="">Any service</option>
                {services.map((service) => <option key={service.id} value={service.id}>{service.service_name}</option>)}
              </SelectField>
            </div>
            <div className="formRow">
              <SelectField label="County" value={uploadForm.county_id} onChange={(value) => {
                setUploadForm((current) => ({ ...current, county_id: value, city_id: "" }));
              }}>
                <option value="">Any county</option>
                {counties.map((county) => <option key={county.id} value={county.id}>{county.county_name}</option>)}
              </SelectField>
              <SelectField label="City" value={uploadForm.city_id} onChange={(value) => setUpload("city_id", value)}>
                <option value="">Any city</option>
                {uploadCities.map((city) => <option key={city.id} value={city.id}>{city.city_name}</option>)}
              </SelectField>
            </div>
            <SelectField label="Suggested Role" value={uploadForm.image_role} onChange={(value) => setUpload("image_role", value)}>
              <option value="hero">Hero</option>
              <option value="service">Service</option>
              <option value="support">Support</option>
            </SelectField>
            <label>
              <span>Notes</span>
              <textarea value={uploadForm.notes} onChange={(event) => setUpload("notes", event.target.value)} />
            </label>
            <button className="primaryButton" type="submit" disabled={uploading || !uploadFile}>
              <Upload size={17} aria-hidden="true" />
              {uploading ? "Optimizing..." : "Upload and Optimize"}
            </button>
          </form>
        </section>

        <section className="panel mediaLibraryPanel">
          <div className="libraryHeader">
            <div>
              <h2>Saved Media</h2>
              <p>{visibleImages.length} images shown</p>
            </div>
            <div className="segmentedControl" aria-label="Review status filter">
              {["all", "pending_review", "reviewed"].map((status) => (
                <button key={status} className={filter === status ? "active" : ""} type="button" onClick={() => setFilter(status)}>
                  {status === "pending_review" ? "Pending" : titleCase(status)}
                </button>
              ))}
            </div>
          </div>
          <div className="mediaGrid">
            {visibleImages.map((image) => (
              <article key={image.id} className={selected?.id === image.id ? "mediaCard selected" : "mediaCard"}>
                <button type="button" className="mediaCardSelect" onClick={() => setSelected({ ...image })}>
                  <img src={image.thumbnail_url || image.asset_url} alt={image.reviewed_alt_text || image.image_title || "Pending media review"} />
                  <span className={`reviewBadge ${image.review_status}`}>
                    {image.review_status === "reviewed" ? <CheckCircle2 size={14} aria-hidden="true" /> : null}
                    {image.review_status === "reviewed" ? "Reviewed" : "Pending"}
                  </span>
                  <strong>{image.image_title || image.original_filename || image.file_name}</strong>
                  <span>{titleCase(image.image_role)} | {image.reviewed_alt_text || "Alt text pending"}</span>
                </button>
              </article>
            ))}
          </div>
        </section>
      </div>

      {selected && (
        <section className="panel mediaReviewPanel">
          <div className="sectionTitle">
            <Pencil size={19} aria-hidden="true" />
            <div>
              <h2>Review Media</h2>
              <p>{selected.original_filename || selected.file_name}</p>
            </div>
          </div>
          <div className="reviewMediaLayout">
            <img src={selected.optimized_url || selected.asset_url} alt={selected.reviewed_alt_text || selected.image_title || "Media under review"} />
            <form className="recordForm" onSubmit={saveReview}>
              <label>
                <span>Image Title</span>
                <input value={selected.image_title ?? ""} onChange={(event) => editSelected("image_title", event.target.value)} />
              </label>
              <label>
                <span>Reviewed Alt Text *</span>
                <textarea value={selected.reviewed_alt_text ?? ""} onChange={(event) => editSelected("reviewed_alt_text", event.target.value)} />
              </label>
              <div className="formRow">
                <SelectField label="County" value={String(selected.county_id ?? "")} onChange={(value) => {
                  setSelected((current) => current ? { ...current, county_id: numberOrNull(value), city_id: null } : current);
                }}>
                  <option value="">Any county</option>
                  {counties.map((county) => <option key={county.id} value={county.id}>{county.county_name}</option>)}
                </SelectField>
                <SelectField label="City" value={String(selected.city_id ?? "")} onChange={(value) => editSelected("city_id", numberOrNull(value))}>
                  <option value="">Any city</option>
                  {cities.filter((city) => !selected.county_id || city.county_id === selected.county_id).map((city) => (
                    <option key={city.id} value={city.id}>{city.city_name}</option>
                  ))}
                </SelectField>
              </div>
              <div className="formRow">
                <SelectField label="Service" value={String(selected.service_id ?? "")} onChange={(value) => editSelected("service_id", numberOrNull(value))}>
                  <option value="">Any service</option>
                  {services.map((service) => <option key={service.id} value={service.id}>{service.service_name}</option>)}
                </SelectField>
                <SelectField label="Role" value={selected.image_role} onChange={(value) => editSelected("image_role", value)}>
                  <option value="hero">Hero</option>
                  <option value="service">Service</option>
                  <option value="support">Support</option>
                </SelectField>
              </div>
              <label>
                <span>Notes</span>
                <textarea value={selected.notes ?? ""} onChange={(event) => editSelected("notes", event.target.value)} />
              </label>
              <SelectField label="Review Status" value={selected.review_status} onChange={(value) => editSelected("review_status", value)}>
                <option value="pending_review">Pending Review</option>
                <option value="reviewed">Reviewed</option>
              </SelectField>
              <FocalPointEditor
                image={selected}
                onChange={(focalX, focalY) => {
                  setSelected((current) => current ? { ...current, focal_x: focalX, focal_y: focalY } : current);
                }}
              />
              <button className="primaryButton" type="submit" disabled={saving}>
                {saving ? "Saving..." : "Save Review"}
              </button>
            </form>
          </div>
        </section>
      )}
    </section>
  );

  function setUpload(field: keyof UploadForm, value: string) {
    setUploadForm((current) => ({ ...current, [field]: value }));
  }

  function editSelected(field: keyof ImageMetadata, value: string | number | null | undefined) {
    setSelected((current) => current ? { ...current, [field]: value } : current);
  }
}

function SelectField({
  label,
  value,
  onChange,
  children,
  required = false
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: ReactNode;
  required?: boolean;
}) {
  return (
    <label>
      <span>{label}{required ? " *" : ""}</span>
      <select value={value} required={required} onChange={(event) => onChange(event.target.value)}>
        {children}
      </select>
    </label>
  );
}

const cropPresets = [
  { key: "hero_desktop", label: "Hero Desktop", className: "heroDesktop" },
  { key: "hero_mobile", label: "Hero Mobile", className: "heroMobile" },
  { key: "card_thumbnail", label: "Card Thumbnail", className: "cardThumbnail" },
  { key: "square", label: "Square", className: "square" },
  { key: "original", label: "Original", className: "original" }
] as const;

function FocalPointEditor({
  image,
  onChange
}: {
  image: ImageMetadata;
  onChange: (focalX: number, focalY: number) => void;
}) {
  const source = image.optimized_url || image.asset_url;
  const focalX = image.focal_x ?? 0.5;
  const focalY = image.focal_y ?? 0.5;
  const style = focalStyle(focalX, focalY);

  function setFromPreview(event: ReactMouseEvent<HTMLButtonElement>) {
    const bounds = event.currentTarget.getBoundingClientRect();
    const x = clamp((event.clientX - bounds.left) / bounds.width);
    const y = clamp((event.clientY - bounds.top) / bounds.height);
    onChange(roundFocal(x), roundFocal(y));
  }

  return (
    <fieldset className="focalEditor">
      <legend>
        <Crosshair size={18} aria-hidden="true" />
        Crop and Focal Point
      </legend>
      <div className="focalControls">
        <label>
          <span>Horizontal focal point <output>{focalX.toFixed(2)}</output></span>
          <input
            type="range"
            min="0"
            max="1"
            step="0.01"
            value={focalX}
            onChange={(event) => onChange(Number(event.target.value), focalY)}
          />
        </label>
        <label>
          <span>Vertical focal point <output>{focalY.toFixed(2)}</output></span>
          <input
            type="range"
            min="0"
            max="1"
            step="0.01"
            value={focalY}
            onChange={(event) => onChange(focalX, Number(event.target.value))}
          />
        </label>
        <button className="secondaryButton focalCenterButton" type="button" onClick={() => onChange(0.5, 0.5)}>
          <LocateFixed size={16} aria-hidden="true" />
          Center
        </button>
      </div>
      <div className="cropPresetGrid">
        {cropPresets.map((preset) => (
          <div key={preset.key} className={`cropPreset ${preset.className}`}>
            <span>{preset.label}</span>
            <button
              type="button"
              aria-label={`Set focal point from ${preset.label} preview`}
              onClick={setFromPreview}
              style={style}
            >
              {source ? <img src={source} alt="" /> : <span className="cropEmpty">No preview</span>}
              <i aria-hidden="true" />
            </button>
          </div>
        ))}
      </div>
    </fieldset>
  );
}

function focalStyle(focalX: number, focalY: number) {
  return {
    "--focal-x": `${clamp(focalX) * 100}%`,
    "--focal-y": `${clamp(focalY) * 100}%`
  } as CSSProperties;
}

function clamp(value: number) {
  return Math.min(1, Math.max(0, value));
}

function roundFocal(value: number) {
  return Math.round(value * 100) / 100;
}

function numberOrNull(value: string) {
  return value ? Number(value) : null;
}

function titleCase(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function readApiError(error: unknown) {
  if (!(error instanceof Error)) return "Unable to complete the media request.";
  try {
    const parsed = JSON.parse(error.message);
    return parsed.detail || error.message;
  } catch {
    return error.message;
  }
}

function isPending(image: ImageMetadata) {
  return image.review_status === "pending" || image.review_status === "pending_review";
}

export default MediaLibraryPage;
