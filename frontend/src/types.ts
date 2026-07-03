export type FieldType = "text" | "textarea" | "number" | "email" | "url";

export type FieldConfig<T> = {
  key: keyof T;
  label: string;
  type?: FieldType;
  required?: boolean;
};

export type Business = {
  id: number;
  company_name: string;
  brand_name?: string;
  business_type: string;
  phone?: string;
  email?: string;
  website?: string;
  main_city?: string;
  state: string;
  license_number?: string;
  certified_operator?: string;
  description?: string;
  created_at: string;
  updated_at: string;
};

export type Service = {
  id: number;
  business_id: number;
  service_name: string;
  service_slug: string;
  service_category?: string;
  short_description?: string;
  long_description?: string;
  status: string;
  created_at: string;
  updated_at: string;
};

export type County = {
  id: number;
  state: string;
  county_name: string;
  status: string;
};

export type City = {
  id: number;
  county_id: number;
  city_name: string;
  state: string;
  city_slug: string;
  priority: "Primary" | "High" | "Medium" | "Low";
  is_primary_market: boolean;
  notes?: string;
  status: string;
};

export type GeneratedPage = {
  id: number;
  business_id: number;
  service_id: number;
  city_id?: number;
  county_id?: number;
  page_type: string;
  page_title: string;
  page_slug: string;
  meta_title?: string;
  meta_description?: string;
  h1?: string;
  content_body?: string;
  draft_content?: DraftContent | null;
  generation_status: string;
  generated_at?: string | null;
  qa_status: "not_run" | "ready" | "needs_review" | "blocked";
  qa_result?: PageQAResult | null;
  qa_checked_at?: string | null;
  internal_notes?: string | null;
  last_reviewed_at?: string | null;
  last_reviewed_by?: string | null;
  status: string;
  wordpress_url?: string;
  created_at: string;
  updated_at: string;
};

export type QACheckItem = {
  key: string;
  label: string;
  status: "pass" | "fail" | "warning";
  severity: "blocker" | "warning";
  message: string;
  suggested_fix: string;
  issue_location: "content" | "business_info" | "city_county_info" | "media" | "preview" | "safety_wording";
};

export type PageQAResult = {
  page_id: number;
  readiness_status: "ready" | "needs_review" | "blocked";
  checked_at: string;
  passed_count: number;
  warning_count: number;
  failed_count: number;
  checks: QACheckItem[];
  persisted: boolean;
};

export type QABatchCandidate = {
  page_id: number;
  page_title: string;
  city_name: string;
  readiness_status: "ready" | "needs_review" | "blocked";
  passed_count: number;
  warning_count: number;
  failed_count: number;
};

export type QABatchResponse = {
  matched_count: number;
  ready_count: number;
  needs_review_count: number;
  blocked_count: number;
  saved_count: number;
  candidates: QABatchCandidate[];
};

export type ApprovalAudit = {
  id: number;
  generated_page_id: number;
  approved_at: string;
  approved_by?: string | null;
  qa_status_at_approval: string;
  qa_checked_at: string;
  qa_result_snapshot: PageQAResult;
  draft_hash_at_approval: string;
  page_status_before: string;
  page_status_after: string;
};

export type ApprovalHistorySummary = {
  generated_page_id: number;
  approval_count: number;
};

export type DraftContent = {
  title: string;
  meta_title: string;
  meta_description: string;
  h1: string;
  intro: string;
  why_it_matters: string;
  signs_section: string;
  process_section: string;
  prep_section: string;
  realtor_property_manager_section: string;
  faq_items: { question: string; answer: string }[];
  call_to_action: string;
  internal_notes: string;
  status: string;
  hero_subheadline?: string;
  service_explanation?: string;
  local_city_section?: string;
  why_choose_section?: string;
};

export type ManualDraftFields = {
  hero_headline: string;
  hero_subheadline: string;
  intro: string;
  service_explanation: string;
  local_city_section: string;
  process_section: string;
  prep_reentry_section: string;
  why_choose_section: string;
  faq_items: { question: string; answer: string }[];
  call_to_action: string;
};

export type GeneratedPageRevision = {
  id: number;
  generated_page_id: number;
  created_at: string;
  created_by?: string | null;
  reason?: string | null;
  draft_hash_before: string;
  draft_hash_after: string;
  draft_content_before: DraftContent;
  draft_content_after: DraftContent;
  changed_fields: string[];
};

export type ManualDraftSaveResponse = {
  page: GeneratedPage;
  revision: GeneratedPageRevision;
  qa_result?: PageQAResult | null;
};

export type ImageMetadata = {
  id: number;
  business_id: number;
  service_id?: number | null;
  city_id?: number | null;
  county_id?: number | null;
  file_name: string;
  image_title?: string;
  alt_text?: string;
  reviewed_alt_text?: string;
  caption?: string;
  asset_url?: string;
  thumbnail_url?: string;
  optimized_url?: string;
  original_filename?: string;
  stored_filename?: string;
  notes?: string;
  focal_x: number;
  focal_y: number;
  image_role: string;
  review_status: string;
  geo_city?: string;
  geo_state?: string;
  image_prompt?: string;
  exif_status: string;
  created_at: string;
  updated_at: string;
};

export type AssignedMedia = {
  assignment_id: number;
  generated_page_id: number;
  image_role: string;
  sort_order: number;
  override_focal_x?: number | null;
  override_focal_y?: number | null;
  override_alt_text?: string | null;
  display_preset: "hero_desktop" | "hero_mobile" | "card_thumbnail" | "square" | "original";
  effective_focal_x: number;
  effective_focal_y: number;
  effective_alt_text: string;
  status: string;
  created_at: string;
  updated_at: string;
  image: ImageMetadata;
};

export type KnowledgeBlock = {
  id: number;
  business_id: number;
  service_id: number;
  title: string;
  slug: string;
  question: string;
  short_answer: string;
  long_answer: string;
  category: string;
  customer_type: string;
  confidence_level: "High" | "Medium" | "Low";
  source_notes?: string;
  sort_order: number;
  status: string;
  created_at: string;
  updated_at: string;
};
