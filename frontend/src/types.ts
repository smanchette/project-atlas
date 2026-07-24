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
  wordpress_post_id?: number | null;
  wordpress_url?: string;
  wordpress_status?: string | null;
  wordpress_created_at?: string | null;
  last_wordpress_sync_at?: string | null;
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

export type ApprovalQueueItem = {
  page_id: number;
  page_title: string;
  city_id?: number | null;
  city_name: string;
  county_id?: number | null;
  county_name: string;
  service_id: number;
  service_name: string;
  page_status: string;
  qa_status: "not_run" | "ready" | "needs_review" | "blocked";
  qa_checked_at?: string | null;
  latest_revision_at?: string | null;
  revision_count: number;
  approval_history_count: number;
  hero_image_status: "missing" | "unreviewed" | "missing_alt_text" | "reviewed";
  last_reviewed_at?: string | null;
  internal_notes_snippet?: string | null;
  is_ready_for_approval: boolean;
  has_blockers: boolean;
  has_warnings: boolean;
  edited_since_last_qa: boolean;
  approved_but_unpublished: boolean;
  missing_media: boolean;
  needs_manual_review: boolean;
  next_recommended_action: string;
};

export type ApprovalQueueResponse = {
  total_count: number;
  items: ApprovalQueueItem[];
};

export type ExportWarning = {
  code: string;
  severity: "warning" | "blocker";
  message: string;
};

export type ExportSEO = {
  meta_title: string;
  meta_description: string;
  social_title: string;
  social_description: string;
  suggested_url_slug: string;
};

export type ExportMediaReference = {
  image_id: number;
  image_role: string;
  sort_order: number;
  image_title?: string | null;
  alt_text: string;
  asset_url?: string | null;
  optimized_url?: string | null;
  thumbnail_url?: string | null;
  display_preset: string;
  focal_x: number;
  focal_y: number;
  review_status: string;
};

export type PageExportPackage = {
  format_version: string;
  page_id: number;
  page_status: string;
  qa_status: string;
  page_title: string;
  url_slug: string;
  h1: string;
  seo: ExportSEO;
  content_sections: Record<string, string>;
  faq_items: { question: string; answer: string }[];
  cta_block: string;
  city: string;
  county: string;
  state: string;
  service: string;
  business_name: string;
  phone?: string | null;
  website?: string | null;
  email?: string | null;
  license_number?: string | null;
  certified_operator?: string | null;
  assigned_media: ExportMediaReference[];
  json_ld: Record<string, unknown>;
  canonical_url_preview: string;
  slug_conflicts: number[];
  export_ready: boolean;
  warnings: ExportWarning[];
};

export type BulkExportCandidate = {
  page_id: number;
  page_title: string;
  url_slug: string;
  export_ready: boolean;
  warning_count: number;
  blocker_count: number;
};

export type BulkExportPreview = {
  selected_count: number;
  export_ready_count: number;
  warning_count: number;
  blocker_count: number;
  candidates: BulkExportCandidate[];
};

export type WordPressPublishingMode = "disabled" | "sandbox" | "draft_only_future";

export type WordPressSettings = {
  site_url: string;
  username: string;
  publishing_mode: WordPressPublishingMode;
  has_application_password: boolean;
  password_storage: string;
};

export type WordPressConnectionResult = {
  connection_status: "disabled" | "connected" | "failed";
  rest_api_reachable: boolean;
  authenticated: boolean;
  credentials_present: boolean;
  site_name?: string | null;
  error_message?: string | null;
  endpoint?: string | null;
  response_source?: string | null;
  reason_code?: string | null;
  authenticated_user_id?: number | null;
  authenticated_username?: string | null;
  atlas_status_checked: boolean;
  atlas_status_reachable: boolean;
  atlas_status_code?: number | null;
};

export type WordPressPayload = {
  title: string;
  slug: string;
  status: "draft";
  content: string;
  excerpt: string;
  featured_media_reference?: Record<string, unknown> | null;
  meta: Record<string, string>;
  schema_block_preview: Record<string, unknown>;
};

export type WordPressHeadingContract = {
  policy_id: string;
  template_renders_primary_h1: boolean;
  body_heading_level: 1 | 2;
};

export type WordPressPayloadPreview = {
  page_id: number;
  export_package: PageExportPackage;
  payload: WordPressPayload;
  heading_contract: WordPressHeadingContract;
  warnings: ExportWarning[];
  sandbox_only: boolean;
};

export type WordPressDraftGateResult = {
  code: string;
  label: string;
  passed: boolean;
  message: string;
};

export type WordPressDraftRequestPayload = {
  title: string;
  slug: string;
  status: "draft";
  content: string;
  excerpt: string;
};

export type WordPressDraftDryRun = {
  page_id: number;
  status: "blocked" | "dry_run_ready";
  ready: boolean;
  payload: WordPressDraftRequestPayload;
  payload_hash: string;
  draft_hash: string;
  gate_results: WordPressDraftGateResult[];
  confirmation_token?: string | null;
  confirmation_phrase?: string | null;
  expires_at?: string | null;
};

export type WordPressDraftUpdateComparison = {
  original_create_audit_id?: number | null;
  original_payload_hash?: string | null;
  current_payload_hash: string;
  original_draft_hash?: string | null;
  current_draft_hash: string;
  payload_changed_since_create: boolean;
  media_reference_hash: string;
  media_reference_warning?: string | null;
  changed_summary: string[];
};

export type WordPressDraftUpdateDryRun = {
  page_id: number;
  status: "blocked" | "dry_run_ready";
  ready: boolean;
  wordpress_post_id?: number | null;
  live_status?: WordPressLiveDraftStatus | null;
  payload: WordPressDraftRequestPayload;
  comparison: WordPressDraftUpdateComparison;
  gate_results: WordPressDraftGateResult[];
  confirmation_token?: string | null;
  confirmation_phrase?: string | null;
  expires_at?: string | null;
  dry_run_only: boolean;
};

export type WordPressDraftUpdateApplyResult = {
  page_id: number;
  status: "updated";
  wordpress_post_id: number;
  wordpress_status: "draft";
  wordpress_url?: string | null;
  audit_id: number;
  payload_hash: string;
  gate_results: WordPressDraftGateResult[];
};

export type WordPressPublishRequestPayload = {
  title: string;
  slug: string;
  status: "publish";
  content: string;
  excerpt: string;
};

export type WordPressPublishDryRun = {
  page_id: number;
  status: "blocked" | "dry_run_ready";
  ready: boolean;
  wordpress_post_id?: number | null;
  live_status?: WordPressLiveDraftStatus | null;
  payload: WordPressPublishRequestPayload;
  current_payload_hash: string;
  latest_update_audit_hash?: string | null;
  publish_payload_hash: string;
  gate_results: WordPressDraftGateResult[];
  confirmation_token?: string | null;
  confirmation_phrase?: string | null;
  expires_at?: string | null;
  public_publish_warning: string;
  dry_run_only: boolean;
};

export type WordPressPublishApplyResult = {
  page_id: number;
  status: "published";
  wordpress_post_id: number;
  wordpress_status: "publish";
  wordpress_url: string;
  audit_id: number;
  publish_payload_hash: string;
  gate_results: WordPressDraftGateResult[];
};

export type WordPressDraftCreateResult = {
  page_id: number;
  status: "created";
  wordpress_post_id: number;
  wordpress_status: "draft";
  wordpress_url?: string | null;
  audit_id: number;
  payload_hash: string;
  gate_results: WordPressDraftGateResult[];
};

export type WordPressDraftReviewItem = {
  page_id: number;
  page_title: string;
  city?: string | null;
  county?: string | null;
  service?: string | null;
  atlas_status: string;
  qa_status: string;
  wordpress_post_id: number;
  wordpress_status?: string | null;
  wordpress_url?: string | null;
  last_wordpress_sync_at?: string | null;
  successful_draft_audit_count: number;
  latest_draft_audit_at?: string | null;
  audit_payload_hash?: string | null;
  audit_draft_hash?: string | null;
  admin_edit_url?: string | null;
  badges: string[];
};

export type WordPressDraftReviewList = {
  total_count: number;
  items: WordPressDraftReviewItem[];
};

export type WordPressLiveDraftStatus = {
  page_id: number;
  wordpress_post_id: number;
  rest_api_reachable?: boolean | null;
  authenticated?: boolean | null;
  credentials_present: boolean;
  wordpress_status?: string | null;
  wordpress_link?: string | null;
  wordpress_modified?: string | null;
  wordpress_title?: string | null;
  wordpress_slug?: string | null;
  is_still_draft: boolean;
  appears_published: boolean;
  error_message?: string | null;
};

export type WordPressDraftComparison = {
  page_id: number;
  atlas_saved_title: string;
  wordpress_title?: string | null;
  atlas_saved_slug: string;
  wordpress_slug?: string | null;
  atlas_expected_status: "draft";
  wordpress_actual_status?: string | null;
  atlas_wordpress_url?: string | null;
  wordpress_link?: string | null;
  audit_payload_hash?: string | null;
  current_export_payload_hash: string;
  audit_draft_hash?: string | null;
  atlas_export_differs_from_original: boolean;
  message?: string | null;
};

export type WordPressDraftReviewDetail = {
  item: WordPressDraftReviewItem;
  comparison: WordPressDraftComparison;
};

export type WordPressQualityCheckStatus = "pass" | "warning" | "fail";
export type WordPressQualityReadinessStatus = "ready" | "needs_review" | "blocked";
export type WordPressManualQualityReviewStatus =
  | "not_reviewed"
  | "in_review"
  | "needs_changes"
  | "ready_for_manual_publish_review";

export type WordPressQualityCheck = {
  key: string;
  label: string;
  status: WordPressQualityCheckStatus;
  message: string;
  review_field: string;
};

export type WordPressManualQualityReview = {
  id?: number | null;
  generated_page_id: number;
  review_status: WordPressManualQualityReviewStatus;
  reviewer_notes?: string | null;
  reviewed_at?: string | null;
  reviewed_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type WordPressDraftQualityReviewItem = {
  page_id: number;
  page_title: string;
  city?: string | null;
  county?: string | null;
  service?: string | null;
  atlas_status: string;
  qa_status: string;
  wordpress_post_id: number;
  wordpress_status?: string | null;
  wordpress_url?: string | null;
  admin_edit_url?: string | null;
  slug: string;
  payload_hash_matches_audit: boolean;
  pass_count: number;
  warning_count: number;
  fail_count: number;
  overall_publish_readiness: WordPressQualityReadinessStatus;
  blockers_or_issues: string[];
  safe_for_future_manual_review: boolean;
  manual_review: WordPressManualQualityReview;
  checklist: WordPressQualityCheck[];
};

export type WordPressDraftQualityReviewList = {
  total_count: number;
  ready_count: number;
  needs_review_count: number;
  blocked_count: number;
  items: WordPressDraftQualityReviewItem[];
};

export type WordPressDraftQueueGroup =
  | "eligible"
  | "blocked_approval"
  | "blocked_qa"
  | "blocked_stale_qa"
  | "blocked_missing_media"
  | "already_has_draft"
  | "blocked_credentials"
  | "blocked_export";

export type WordPressDraftQueueItem = {
  page_id: number;
  page_title: string;
  city?: string | null;
  county?: string | null;
  service?: string | null;
  atlas_status: string;
  qa_status: string;
  qa_checked_at?: string | null;
  revision_count: number;
  latest_revision_at?: string | null;
  approval_audit_count: number;
  export_ready: boolean;
  export_blocker_count: number;
  export_warning_count: number;
  slug: string;
  slug_conflicts: number[];
  wordpress_post_id?: number | null;
  wordpress_status?: string | null;
  wordpress_url?: string | null;
  payload_status: "draft";
  queue_group: WordPressDraftQueueGroup;
  eligible: boolean;
  gate_results: WordPressDraftGateResult[];
  next_required_action: string;
};

export type WordPressDraftQueueResponse = {
  total_count: number;
  eligible_count: number;
  blocked_count: number;
  already_has_draft_count: number;
  wordpress_mode: WordPressPublishingMode;
  has_application_password: boolean;
  site_url_configured: boolean;
  username_configured: boolean;
  items: WordPressDraftQueueItem[];
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

export type ApprovedPageRepairFields = {
  intro?: string | null;
  why_it_matters?: string | null;
  realtor_property_manager_section?: string | null;
  faq_items?: { question: string; answer: string }[] | null;
  internal_notes?: string | null;
};

export type ApprovedPageRepairResponse = {
  page: GeneratedPage;
  revision: GeneratedPageRevision;
  qa_result: PageQAResult;
  export_ready: boolean;
  export_blocker_count: number;
  export_warning_count: number;
  export_warnings: ExportWarning[];
  draft_hash_before: string;
  draft_hash_after: string;
  payload_hash_before: string;
  payload_hash_after: string;
  wordpress_post_id: number;
  wordpress_status?: string | null;
  wordpress_url?: string | null;
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
  wordpress_media_id?: number | null;
  wordpress_media_url?: string | null;
  wordpress_media_status?: string | null;
  wordpress_media_checksum?: string | null;
  wordpress_media_uploaded_at?: string | null;
  last_wordpress_media_sync_at?: string | null;
};

export type WordPressMediaDryRun = {
  page_id: number;
  wordpress_post_id: number;
  assignment_id: number;
  image_id: number;
  status: "blocked" | "dry_run_ready";
  ready: boolean;
  resolved_local_path: string;
  source_file_name: string;
  original_filename?: string | null;
  mime_type: string;
  file_size: number;
  width: number;
  height: number;
  checksum: string;
  alt_text: string;
  image_title: string;
  existing_wordpress_media_id?: number | null;
  existing_wordpress_media_url?: string | null;
  attachment_match: { status: string; wordpress_media_id?: number | null; wordpress_media_url?: string | null; message: string };
  gate_results: { code: string; label: string; passed: boolean; message: string }[];
  confirmation_token?: string | null;
  confirmation_phrase?: string | null;
  expires_at?: string | null;
  dry_run_only: boolean;
};

export type WordPressMediaUploadResult = {
  page_id: number;
  wordpress_post_id: number;
  image_id: number;
  assignment_id: number;
  status: "uploaded";
  wordpress_media_id: number;
  wordpress_media_url: string;
  checksum: string;
  alt_text: string;
  audit_id: number;
};

export type WordPressMediaReconciliationCandidate = {
  wordpress_media_id: number;
  date_gmt?: string | null;
  source_url?: string | null;
  title?: string | null;
  alt_text?: string | null;
  mime_type?: string | null;
  width?: number | null;
  height?: number | null;
  file_size?: number | null;
  parent_post_id?: number | null;
  remote_checksum?: string | null;
  featured_references: { object_type: "page" | "post"; object_id: number; title?: string | null; status?: string | null; slug?: string | null; link?: string | null }[];
  valid: boolean;
  gate_results: { code: string; label: string; passed: boolean; message: string }[];
};

export type WordPressMediaReconciliationDryRun = {
  page_id: number;
  wordpress_post_id: number;
  image_id: number;
  assignment_id: number;
  candidate_ids: number[];
  local_checksum: string;
  local_file_size: number;
  candidates: WordPressMediaReconciliationCandidate[];
  selected_media_id?: number | null;
  selected_media_url?: string | null;
  duplicate_candidate_ids: number[];
  post_status?: string | null;
  post_featured_media?: number | null;
  gate_results: { code: string; label: string; passed: boolean; message: string }[];
  status: "blocked" | "reconciliation_ready";
  ready: boolean;
  confirmation_token?: string | null;
  confirmation_phrase?: string | null;
  expires_at?: string | null;
};

export type WordPressMediaReconciliationApplyResult = {
  status: "reconciled";
  wordpress_media_id: number;
  wordpress_media_url: string;
  checksum: string;
  duplicate_candidate_ids: number[];
  audit_id: number;
};

export type WordPressFeaturedImageDryRun = {
  page_id: number;
  wordpress_post_id: number;
  image_id: number;
  assignment_id: number;
  wordpress_media_id: number;
  post_status?: string | null;
  post_slug?: string | null;
  post_url?: string | null;
  current_featured_media?: number | null;
  media?: WordPressMediaReconciliationCandidate | null;
  local_checksum: string;
  planned_payload: { featured_media: number };
  excluded_media_ids: number[];
  gate_results: { code: string; label: string; passed: boolean; message: string }[];
  status: "blocked" | "featured_image_ready";
  ready: boolean;
  confirmation_token?: string | null;
  confirmation_phrase?: string | null;
  expires_at?: string | null;
};

export type WordPressFeaturedImageApplyResult = {
  status: "featured_image_set";
  wordpress_post_id: number;
  wordpress_media_id: number;
  wordpress_status: "publish";
  wordpress_url: string;
  featured_media: number;
  audit_id: number;
};

export type WordPressFeaturedImageVerification = {
  page_id: number;
  wordpress_post_id: number;
  wordpress_media_id: number;
  post_status?: string | null;
  post_slug?: string | null;
  post_url?: string | null;
  featured_media?: number | null;
  media_31?: WordPressMediaReconciliationCandidate | null;
  media_32?: WordPressMediaReconciliationCandidate | null;
  gate_results: { code: string; label: string; passed: boolean; message: string }[];
  status: "verified" | "failed";
  ready: false;
  apply_needed: boolean;
  featured_image_correct: boolean;
  confirmation_token: null;
  confirmation_phrase: null;
  read_only: true;
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

export type WordPressMetadataGate = { code: string; label: string; passed: boolean; message: string };

export type WordPressMetadataDryRun = {
  page_id: number; wordpress_post_id: number; status: "blocked" | "metadata_ready"; ready: boolean;
  plugin_version: string; plugin_installed: boolean; plugin_active: boolean; plugin_rendering_enabled: boolean;
  payload: { meta_description: string; open_graph: Record<string, string>; twitter: Record<string, string>; json_ld: Record<string, unknown>; media_id: 31; excluded_media_ids: number[] };
  payload_hash: string; current_snapshot?: Record<string, unknown> | null; gate_results: WordPressMetadataGate[];
  confirmation_token?: string | null; confirmation_phrase?: string | null; expires_at?: string | null;
};

export type WordPressMetadataApplyResult = { page_id: number; wordpress_post_id: number; status: "metadata_applied"; payload_hash: string; wordpress_revision: string; audit_id: number; verification: Record<string, unknown> };

export type WordPressDeploymentGate = { code: string; label: string; passed: boolean; message: string };
export type WordPressManualBrowserEvidence = {
  evidence_schema: "project-atlas-manual-browser-evidence";
  evidence_schema_version: 1 | 2;
  capture_helper_version: "0.59.80";
  evidence_id: string; captured_at: string; expires_at: string; final_url: string;
  acquisition_source: "credential_free_public_browser";
  navigation_outcome: { status_code: 200; content_type: "text/html"; redirect_count: 0; outcome: "success" };
  page_identity: { document_title: string; h1: string; canonical_url: string; featured_image_url: string; featured_image_alt: string };
  metadata_inventory: {
    meta_descriptions: Record<string,string>[]; canonicals: string[]; open_graph: Record<string,string>[];
    twitter: Record<string,string>[]; json_ld: unknown[]; title_count: number; canonical_count: number;
    atlas_ownership_markers: string[]; featured_image_references: Record<string,string>[];
    media32_references: string[]; unexpected_metadata_owners: string[]; duplicates: string[];
  };
  metadata_inventory_hash: string; absence_findings: Record<string,boolean>;
  normalized_head: string; normalized_visible_content: string;
  rendered_head_hash: string; visible_content_hash: string;
  privacy_attestations: Record<string,boolean>;
  h1_inventory?: { text:string; ordinal:number; dom_path:string; classes:string[]; ancestor_classes:string[]; visible:boolean; source_classification:string }[] | null;
  h1_count?: number | null; primary_h1?: string | null; body_h1?: string | null;
  helper_signature: string;
};
export type WordPressHeadingCorrectionObservation = {
  attempted:boolean; acquisition_source:string; http_status?:number|null; final_url?:string|null;
  success:boolean; failure_code?:string|null; message:string;
};
export type WordPressHeadingCorrectionDryRun = {
  atlas_page_id:41; wordpress_post_id:8; status:"blocked"|"dry_run_ready"; ready:boolean;
  current_body_hash?:string|null; proposed_body_hash?:string|null; current_heading_fragment:string; proposed_heading_fragment:string;
  request_payload:Record<string,string>; gate_results:WordPressDeploymentGate[]; read_only:true; token_issued:boolean;
  nonce_consumed:false; audit_created:false; wordpress_write_count:0; atlas_write_count:0;
  page_8_observation?:WordPressHeadingCorrectionObservation|null; media_31_observation?:WordPressHeadingCorrectionObservation|null;
  media_32_observation?:WordPressHeadingCorrectionObservation|null; rendered_page_observation?:WordPressHeadingCorrectionObservation|null;
  token_handle?:string|null; confirmation_phrase?:string|null; expires_at?:string|null;
};
export type WordPressHeadingCorrectionApplyResult = {
  atlas_page_id:41; wordpress_post_id:8; status:"corrected"|"reconciliation_required"; audit_id:number;
  current_body_hash:string; proposed_body_hash:string; request_payload:{content:string}; gate_results:WordPressDeploymentGate[];
  wordpress_write_count:1; atlas_write_count:number; automatic_retry_count:0;
};
export type WordPressDeploymentReadiness = {
  release: { manifest_schema_version: number; source_compatibility_id: string; atlas_version: string; atlas_commit: string; atlas_tag: string; plugin_version: string; plugin_zip_filename: string; plugin_zip_sha256: string; manifest_sha256: string; verification_source: string; git_metadata_available: boolean; manifest_integrity_verified: boolean; expected_release_matched: boolean; runtime_identity_verified: boolean } | null;
  release_status: "verified" | "release_identity_unavailable"; release_error: string | null;
  source_expectations: { manifest_schema_version: number; source_compatibility_id: string; plugin_version: string; plugin_zip_filename: string; plugin_zip_sha256: string };
  program: { resolved_program_root: string; artifact_relative_path: string; artifact_exists: boolean; source_directory_exists: boolean };
  read_only: true;
};
export type WordPressDeploymentDryRun = {
  page_id: 41; wordpress_post_id: 8; status: "preflight_not_started" | "preflight_ready"; ready: boolean;
  artifact: Record<string, string>; inspected_state: Record<string, unknown>; backup_age_seconds?: number | null;
  gate_results: WordPressDeploymentGate[]; confirmation_token?: string | null; confirmation_phrase?: string | null; expires_at?: string | null; read_only: true;
};
export type WordPressDeploymentPreflight = {
  page_id: 41; wordpress_post_id: 8; status: "preflight_blocked" | "preflight_ready"; preflight_ready: boolean;
  backup_age_seconds?: number | null; backup_deadline?: string | null; artifact: Record<string, unknown>; inspected_state: Record<string, unknown>;
  gate_results: WordPressDeploymentGate[]; php_error_findings: Record<string, unknown>; inspection_only: true; token_issued: false;
  nonce_consumed: false; audit_created: false; wordpress_write_count: 0; atlas_write_count: 0; read_only: true;
};
export type WordPressDeploymentAuthorization = {
  audit_id: number; status: "awaiting_manual_installation"; installation_transport: "manual_wordpress_admin_upload";
  zip_file_name: string; zip_sha256: string; instructions: string[]; warning: "DO NOT CLICK ACTIVATE PLUGIN"; wordpress_request_performed: false; state_history: string[];
};
export type WordPressDeploymentVerification = {
  audit_id: number; status: "verified" | "verification_failed" | "reconciliation_required"; verified: boolean;
  gate_results: WordPressDeploymentGate[]; inspected_state: Record<string, unknown>; read_only_wordpress: true; state_history: string[]; inspection_limitations: string[];
};
export type WordPressDeploymentReconciliationVerification = {
  page_id: 41; wordpress_post_id: 8; audit_id: number; status: "reconciliation_blocked" | "reconciliation_ready";
  reconciliation_ready: boolean; reconciliation_handle?: string | null; confirmation_phrase?: string | null;
  binding_hash?: string | null; expires_at?: string | null; gate_results: WordPressDeploymentGate[];
  inspected_state: Record<string, unknown>; proposed_atlas_changes: string[]; inspection_only: true;
  installation_token_issued: false; installation_nonce_consumed: false; deployment_audit_created: false;
  wordpress_write_count: 0; atlas_write_count: 0;
};
export type WordPressDeploymentReconciliationResult = {
  page_id: 41; wordpress_post_id: 8; audit_id: number; status: "verified";
  completion_mode: "installed_inactive_reconciliation"; binding_hash: string; state_history: string[];
  wordpress_write_count: 0; atlas_write_count: 2; original_authorization_nonce_preserved: true;
  original_transition_history_preserved: true; further_reconciliation_required: false;
};
export type WordPressPluginUpgradePreflight = {
  page_id:41; wordpress_post_id:8;
  status:"plugin_upgrade_preflight_blocked"|"plugin_upgrade_preflight_ready";
  plugin_upgrade_preflight_ready:boolean; upgrade_handle?:string|null;
  upgrade_handle_fingerprint?:string|null; confirmation_phrase?:string|null;
  binding_hash?:string|null; expires_at?:string|null; backup_deadline?:string|null;
  current_version:"0.57.4"; target_version:"0.57.5";
  artifact:Record<string,unknown>; inspected_state:Record<string,unknown>;
  gate_results:WordPressDeploymentGate[]; proposed_wordpress_write_scope:string[];
  proposed_atlas_write_scope:string[]; expected_post_plugin_inventory_hash?:string|null;
  expected_post_active_plugin_inventory_hash?:string|null; inspection_only:true;
  token_issued:false; nonce_returned:false; audit_created:false;
  wordpress_write_count:0; atlas_write_count:0;
};
export type WordPressPluginUpgradeResult = {
  page_id:41; wordpress_post_id:8; upgrade_audit_id:number;
  status:"verified"|"verification_failed"|"failed"; binding_hash:string;
  state_history:string[]; previous_version:"0.57.4"; target_version:"0.57.5";
  gate_results:WordPressDeploymentGate[]; inspected_state:Record<string,unknown>;
  wordpress_write_count:1; wordpress_write_scope:string[];
  atlas_write_count:2; atlas_write_scope:string[];
  recovery_recommendation:"no_action"|"guarded_downgrade"|"siteground_restore";
  metadata_application_authorized:false; rendering_change_authorized:false;
  cache_purge_count:0; further_action_required:boolean;
};
export type WordPressPluginUpgradeRecoveryAssessment = {
  page_id:41; wordpress_post_id:8; upgrade_audit_id:number;
  status:"recovery_assessment_complete"|"recovery_assessment_blocked";
  recommendation:"no_action"|"guarded_downgrade"|"siteground_restore";
  gate_results:WordPressDeploymentGate[]; inspected_state:Record<string,unknown>;
  wordpress_write_count:0; atlas_write_count:0; automatic_recovery_performed:false;
};
export type WordPressBootstrapEstablishmentPreflight = {
  page_id:41; wordpress_post_id:8; stage:string; ready:boolean; status:string;
  establishment_audit_id?:number|null; handle?:string|null; handle_fingerprint?:string|null;
  binding_hash?:string|null; confirmation_phrase?:string|null; expires_at?:string|null;
  backup_deadline?:string|null; artifact:Record<string,unknown>; inspected_state:Record<string,unknown>;
  gate_results:WordPressDeploymentGate[]; instructions:string[];
  wordpress_write_count:0; cache_write_count:0; atlas_write_count:0;
};
export type WordPressBootstrapEstablishmentResult = {
  page_id:41; wordpress_post_id:8; establishment_audit_id:number; stage:string; status:string;
  state_history:string[]; binding_hash:string; gate_results:WordPressDeploymentGate[];
  inspected_state:Record<string,unknown>; wordpress_write_count:number; wordpress_write_scope:string[];
  cache_write_count:0; atlas_write_count:number; atlas_write_scope:string[];
  authorization_evidence:Record<string,unknown>; verification_evidence?:Record<string,unknown>|null;
  stable_evidence_match:boolean; fresh_evidence_required:boolean; backup_deadline_valid:boolean;
  original_backup:Record<string,unknown>; active_backup:Record<string,unknown>; backup_renewals:Record<string,unknown>[];
  recovery_recommendation:string; further_action_required:boolean;
};
export type WordPressBootstrapActivationReconciliationRequest = {
  establishment_audit_id:2; operator:string;
  manual_browser_evidence:WordPressManualBrowserEvidence;
  expected_runtime_identity:{
    atlas_version:string; atlas_commit:string; atlas_tag:string;
    manifest_sha256:string; source_compatibility_id:string;
  };
  repository_head:string; repository_origin_main:string; repository_tag:"v0.59.95";
  repository_branch:"main"; repository_working_tree_clean:boolean;
  protected_paths_unchanged:boolean; atlas_data_backup_file:string;
  atlas_data_backup_sha256:string; atlas_data_backup_size:number;
  atlas_data_backup_created_at:string; atlas_data_backup_onedrive_path:string;
  atlas_data_backup_onedrive_synced:boolean;
};
export type WordPressBootstrapActivationReconciliationApplyRequest = {
  reconciliation_handle:string; confirmation_phrase:string;
};
export type WordPressBootstrapActivationReconciliationPreflight = {
  page_id:41; wordpress_post_id:8; establishment_audit_id:2;
  status:"bootstrap_activation_reconciliation_blocked"|"bootstrap_activation_reconciliation_ready";
  reconciliation_ready:boolean; reconciliation_handle?:string|null;
  reconciliation_handle_fingerprint?:string|null; binding_hash?:string|null;
  confirmation_phrase?:string|null; expires_at?:string|null; expected_final_status:"verified";
  expected_history_append:"post_activation_verifier_contract_defect_reconciled";
  expected_wordpress_write_count:0; expected_plugin_write_count:0; expected_cache_write_count:0;
  expected_atlas_write_count:1; atlas_data_backup:Record<string,unknown>;
  inspected_state:Record<string,unknown>; gate_results:WordPressDeploymentGate[];
  inspection_only:true; audit_created:false;
};
export type WordPressBootstrapActivationReconciliationResult = {
  page_id:41; wordpress_post_id:8; establishment_audit_id:2; status:"verified";
  reconciliation_reason:"post_activation_verifier_contract_defect_reconciled";
  state_history:string[]; binding_hash:string; reconciliation_handle_fingerprint:string;
  wordpress_write_count:0; plugin_write_count:0; cache_write_count:0;
  request_atlas_write_count:0|1; cumulative_atlas_write_count:number;
  original_activation_write_count:1; original_activation_write_preserved:true;
  original_failure_history_preserved:true; new_audit_created:false;
  new_authorization_created:false; idempotent_replay:boolean;
  inspected_state:Record<string,unknown>; gate_results:WordPressDeploymentGate[];
  further_action_required:false;
};
export type WordPressBootstrapAuthorizationRetirementPreflight = {
  page_id:41; wordpress_post_id:8; establishment_audit_id:number; ready:boolean; status:string;
  current_status:string; retirement_reason:"manual_install_verification_genuine_transport_drift";
  transport_comparison:Record<string,unknown>; expected_transition:string[]; expected_history_append:"authorization_retired";
  expected_atlas_write_count:1; confirmation_phrase?:string|null; retirement_handle?:string|null;
  handle_fingerprint?:string|null; expires_at?:string|null; gate_results:WordPressDeploymentGate[];
  wordpress_write_count:0; plugin_write_count:0; cache_write_count:0; atlas_write_count:0;
};
export type WordPressBootstrapAuthorizationRetirementResult = {
  page_id:41; wordpress_post_id:8; establishment_audit_id:number; status:"authorization_retired";
  retirement_reason:"manual_install_verification_genuine_transport_drift"; state_history:string[];
  renewal_history:Record<string,unknown>[]; authorization_snapshot_preserved:boolean;
  verification_evidence_present:boolean; activation_handle_present:boolean; checksum_quarantine_active:boolean;
  pending_operation:boolean; idempotent_replay:boolean; wordpress_write_count:0; plugin_write_count:0;
  cache_write_count:0; request_atlas_write_count:number; atlas_write_count:number; fresh_authorization_permitted:boolean;
};
export type WordPressBootstrapBackupRenewalPreflight = {
  page_id:41; wordpress_post_id:8; establishment_audit_id:number; status:string; ready:boolean; reason_code:string;
  renewal_handle_fingerprint?:string|null; expires_at?:string|null; confirmation_phrase?:string|null;
  original_backup:WordPressBootstrapBackupEvidence; active_backup:WordPressBootstrapBackupEvidence; proposed_replacement:WordPressBootstrapBackupEvidence;
  renewal_sequence:number; gate_results:WordPressDeploymentGate[]; wordpress_write_count:0; cache_write_count:0; atlas_write_count:0;
};
export type WordPressBootstrapBackupEvidence = {
  atlas_data_backup_file?:string; atlas_media_backup_file?:string; atlas_program_backup_file?:string;
  wordpress_backup_method?:string; wordpress_backup_reference?:string; wordpress_backup_completed_at?:string;
  wordpress_database_included_attestation?:boolean; wordpress_plugins_included_attestation?:boolean;
  wordpress_restore_capability_attestation?:boolean; confirmer_identity?:string;
  no_relevant_wordpress_change_after_backup?:boolean; deadline?:string;
};
export type WordPressBootstrapBackupRenewalRecord = {
  sequence:number; replacement:WordPressBootstrapBackupEvidence; approved_at?:string; status:string;
  replacement_expired?:boolean|null; replacement_expiration_status?:"valid"|"expired"|"missing"|"invalid";
  replacement_remaining_seconds?:number|null; active?:boolean;
};
export type WordPressBootstrapBackupRenewalResult = {
  page_id:41; wordpress_post_id:8; establishment_audit_id:number; status:string; reason_code:string; renewal_sequence:number;
  original_backup:WordPressBootstrapBackupEvidence; active_backup:WordPressBootstrapBackupEvidence; renewal_history:WordPressBootstrapBackupRenewalRecord[];
  state_history:string[]; idempotent_replay:boolean; wordpress_write_count:0; cache_write_count:0;
  request_atlas_write_count:number; atlas_write_count:number; recovery_recommendation:string;
};
export type WordPressBootstrapBackupRenewalRecovery = {
  page_id:41; wordpress_post_id:8; establishment_audit_id:number;
  status:"recovery_assessment_complete"; audit_status:string; classification:string; reason_code:string;
  recommendation:string; next_required_action:string; renewal_eligible:boolean; renewal_blocked:boolean;
  original_backup:WordPressBootstrapBackupEvidence; active_backup:WordPressBootstrapBackupEvidence;
  original_backup_expired:boolean|null; original_backup_expiration_status:"valid"|"expired"|"missing"|"invalid";
  original_backup_remaining_seconds?:number|null;
  active_backup_source:"original"|"replacement"|"none"; active_backup_expired:boolean|null;
  active_backup_expiration_status:"valid"|"expired"|"missing"|"invalid"; active_backup_remaining_seconds?:number|null;
  active_renewal_sequence?:number|null;
  renewal_history:WordPressBootstrapBackupRenewalRecord[];
  renewal_count:number; maximum_renewals:number; renewals_remaining:number; renewal_limit_reached:boolean;
  bootstrap_manually_uploaded:boolean|null; verification_evidence_present:boolean; activation_started:boolean;
  checksum_quarantine_active:boolean; pending_operation:boolean;
  wordpress_write_count:0; cache_write_count:0; atlas_write_count:0;
};
export type WordPressMetadataVerification = { status: "verified" | "failed" | "not_applied"; metadata_correct: boolean; apply_needed: boolean; payload_hash: string; live_payload_hash?: string | null; gate_results: WordPressMetadataGate[]; read_only: true };
export type WordPressMetadataRollbackDryRun = { status: "blocked" | "rollback_ready"; ready: boolean; current_payload_hash?: string | null; gate_results: WordPressMetadataGate[]; confirmation_token?: string | null; confirmation_phrase?: string | null; expires_at?: string | null };

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
