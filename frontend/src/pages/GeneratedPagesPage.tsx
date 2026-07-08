import { CSSProperties, useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowDown, ArrowUp, CheckCircle2, CircleCheck, ClipboardList, Eye, FileClock, FileJson, Image as ImageIcon, ListChecks, Monitor, Pencil, Plus, RotateCcw, Save, ShieldCheck, Sparkles, Trash2, X, XCircle } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";

import { ApiError, apiRequest, listItems } from "../api";
import type { ApprovalAudit, ApprovalHistorySummary, AssignedMedia, City, County, GeneratedPage, GeneratedPageRevision, ImageMetadata, ManualDraftFields, ManualDraftSaveResponse, PageQAResult, QABatchResponse } from "../types";

type BatchCandidate = {
  page_id: number;
  page_title: string;
  city_name: string;
  county_name: string;
  page_status: string;
  generation_status: string;
  eligible: boolean;
  reason?: string;
};

type BatchPreview = {
  matched_count: number;
  eligible_count: number;
  skipped_count: number;
  candidates: BatchCandidate[];
};

type BatchResult = {
  generated_count: number;
  skipped_count: number;
  page_ids: number[];
};

type EditorValidationError = {
  field: string;
  message: string;
};

function GeneratedPagesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [pages, setPages] = useState<GeneratedPage[]>([]);
  const [cities, setCities] = useState<City[]>([]);
  const [counties, setCounties] = useState<County[]>([]);
  const [images, setImages] = useState<ImageMetadata[]>([]);
  const [selectedPageId, setSelectedPageId] = useState<number | null>(null);
  const [mediaAssignments, setMediaAssignments] = useState<AssignedMedia[]>([]);
  const [qaResult, setQaResult] = useState<PageQAResult | null>(null);
  const [qaBatchPreview, setQaBatchPreview] = useState<QABatchResponse | null>(null);
  const [qaRunningPageId, setQaRunningPageId] = useState<number | null>(null);
  const [approvalHistory, setApprovalHistory] = useState<ApprovalAudit[]>([]);
  const [pageRevisions, setPageRevisions] = useState<GeneratedPageRevision[]>([]);
  const [approvalCounts, setApprovalCounts] = useState<Map<number, number>>(new Map());
  const [reviewNotes, setReviewNotes] = useState("");
  const [reviewedBy, setReviewedBy] = useState("");
  const [mediaRole, setMediaRole] = useState("hero");
  const [selectedImageId, setSelectedImageId] = useState("");
  const [countyFilter, setCountyFilter] = useState("all");
  const [cityFilter, setCityFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [qaFilter, setQaFilter] = useState("all");
  const [batchPreview, setBatchPreview] = useState<BatchPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [generatingPageId, setGeneratingPageId] = useState<number | null>(null);
  const [editorPageId, setEditorPageId] = useState<number | null>(null);
  const [editorDraft, setEditorDraft] = useState<ManualDraftFields | null>(null);
  const [editorBaseline, setEditorBaseline] = useState<ManualDraftFields | null>(null);
  const [editorCreatedBy, setEditorCreatedBy] = useState("");
  const [editorReason, setEditorReason] = useState("");
  const [editorErrors, setEditorErrors] = useState<EditorValidationError[]>([]);
  const [editorSaving, setEditorSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const selectedPage = pages.find((page) => page.id === selectedPageId) ?? null;
  const editorPage = pages.find((page) => page.id === editorPageId) ?? null;
  const editorDirty = Boolean(
    editorDraft &&
    editorBaseline &&
    JSON.stringify(editorDraft) !== JSON.stringify(editorBaseline)
  );

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const [pageData, cityData, countyData, imageData, approvalSummary] = await Promise.all([
        listItems<GeneratedPage>("/api/generated-pages"),
        listItems<City>("/api/cities"),
        listItems<County>("/api/counties"),
        listItems<ImageMetadata>("/api/image-metadata"),
        listItems<ApprovalHistorySummary>("/api/generated-pages/approval-history-summary")
      ]);
      setPages(pageData);
      setCities(cityData);
      setCounties(countyData);
      setImages(imageData);
      setApprovalCounts(new Map(approvalSummary.map((item) => [item.generated_page_id, item.approval_count])));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load generated pages.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  useEffect(() => {
    if (loading || pages.length === 0) return;
    const pageId = Number(searchParams.get("page"));
    const action = searchParams.get("action");
    if (!pageId || !action) return;
    const page = pages.find((item) => item.id === pageId);
    if (!page) return;
    setSelectedPageId(page.id);
    if (action === "edit" && page.status === "draft" && page.draft_content) {
      openEditor(page);
    }
    const targetId = action === "history" ? "approval-history-panel" : action === "issues" ? "qa-panel" : null;
    if (targetId) {
      window.setTimeout(() => document.getElementById(targetId)?.scrollIntoView({ behavior: "smooth" }), 250);
    }
    setSearchParams({}, { replace: true });
  }, [loading, pages, searchParams, setSearchParams]);

  useEffect(() => {
    if (!selectedPageId) {
      setMediaAssignments([]);
      setQaResult(null);
      setApprovalHistory([]);
      setPageRevisions([]);
      return;
    }
    loadPageMedia(selectedPageId);
    loadPageQa(selectedPageId);
    loadApprovalHistory(selectedPageId);
    loadPageRevisions(selectedPageId);
  }, [selectedPageId]);

  useEffect(() => {
    function warnBeforeUnload(event: BeforeUnloadEvent) {
      if (!editorDirty) return;
      event.preventDefault();
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => window.removeEventListener("beforeunload", warnBeforeUnload);
  }, [editorDirty]);

  useEffect(() => {
    setReviewNotes(selectedPage?.internal_notes ?? "");
    setReviewedBy(selectedPage?.last_reviewed_by ?? "");
  }, [selectedPage?.id, selectedPage?.internal_notes, selectedPage?.last_reviewed_by]);

  useEffect(() => {
    setSelectedImageId("");
  }, [mediaRole, selectedPageId]);

  const cityById = useMemo(() => new Map(cities.map((city) => [city.id, city])), [cities]);
  const countyNameById = useMemo(
    () => new Map(counties.map((county) => [county.id, county.county_name])),
    [counties]
  );
  const eligibleImages = selectedPage
    ? images.filter((image) => {
        return (
          image.review_status === "reviewed" &&
          Boolean(image.asset_url) &&
          Boolean(image.reviewed_alt_text) &&
          image.business_id === selectedPage.business_id &&
          (image.service_id === undefined || image.service_id === null || image.service_id === selectedPage.service_id) &&
          (image.city_id === undefined || image.city_id === null || image.city_id === selectedPage.city_id) &&
          (image.county_id === undefined || image.county_id === null || image.county_id === selectedPage.county_id)
        );
      })
    : [];

  const filteredPages = pages.filter((page) => {
    const countyMatches = countyFilter === "all" || String(page.county_id) === countyFilter;
    const cityMatches = cityFilter === "all" || String(page.city_id) === cityFilter;
    const statusMatches = statusFilter === "all" || page.status === statusFilter;
    const warningCount = page.qa_result?.warning_count ?? 0;
    const blockerCount = page.qa_result?.failed_count ?? 0;
    const qaMatches =
      qaFilter === "all" ||
      page.qa_status === qaFilter ||
      (qaFilter === "has_warnings" && warningCount > 0) ||
      (qaFilter === "has_blockers" && blockerCount > 0) ||
      (qaFilter === "not_run" && page.qa_status === "not_run");
    return countyMatches && cityMatches && statusMatches && qaMatches;
  });

  const cityServiceCount = pages.filter((page) => page.page_type === "city_service").length;
  const cityOptions = countyFilter === "all" ? cities : cities.filter((city) => String(city.county_id) === countyFilter);
  const statusOptions = Array.from(new Set(pages.map((page) => page.status))).sort();

  function batchPayload(confirm = false) {
    return {
      county_ids: countyFilter === "all" ? [] : [Number(countyFilter)],
      city_ids: cityFilter === "all" ? [] : [Number(cityFilter)],
      status: statusFilter === "all" ? null : statusFilter,
      confirm
    };
  }

  function clearBatchPreview() {
    setBatchPreview(null);
    setQaBatchPreview(null);
    setMessage(null);
  }

  async function loadPageMedia(pageId: number) {
    try {
      setMediaAssignments(await apiRequest<AssignedMedia[]>(`/api/generated-pages/${pageId}/media`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load page media.");
    }
  }

  async function loadPageQa(pageId: number) {
    try {
      setQaResult(await apiRequest<PageQAResult>(`/api/generated-pages/${pageId}/qa`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load page QA.");
    }
  }

  async function loadApprovalHistory(pageId: number) {
    try {
      setApprovalHistory(
        await apiRequest<ApprovalAudit[]>(`/api/generated-pages/${pageId}/approval-history`)
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load approval history.");
    }
  }

  async function loadPageRevisions(pageId: number) {
    try {
      setPageRevisions(
        await apiRequest<GeneratedPageRevision[]>(`/api/generated-pages/${pageId}/revisions`)
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load revision history.");
    }
  }

  function openEditor(page: GeneratedPage) {
    if (editorDirty && editorPageId !== page.id) {
      const discard = window.confirm("Discard unsaved draft changes and open another page?");
      if (!discard) return;
    }
    const editable = manualDraftFromPage(page);
    setSelectedPageId(page.id);
    setEditorPageId(page.id);
    setEditorDraft(editable);
    setEditorBaseline(structuredClone(editable));
    setEditorCreatedBy(page.last_reviewed_by ?? "");
    setEditorReason("");
    setEditorErrors([]);
  }

  function closeEditor() {
    if (editorDirty && !window.confirm("Discard unsaved draft changes?")) {
      return;
    }
    setEditorPageId(null);
    setEditorDraft(null);
    setEditorBaseline(null);
    setEditorErrors([]);
  }

  async function saveEditor(runQa: boolean) {
    if (!editorPage || !editorDraft) return;
    setEditorSaving(true);
    setMessage(null);
    setError(null);
    setEditorErrors([]);
    try {
      const result = await apiRequest<ManualDraftSaveResponse>(
        `/api/generated-pages/${editorPage.id}/${runQa ? "draft-and-qa" : "draft"}`,
        {
          method: "PUT",
          body: JSON.stringify({
            draft: editorDraft,
            created_by: editorCreatedBy || null,
            reason: editorReason || null
          })
        }
      );
      const savedDraft = manualDraftFromPage(result.page);
      setEditorDraft(savedDraft);
      setEditorBaseline(structuredClone(savedDraft));
      setEditorReason("");
      if (result.qa_result) {
        setQaResult(result.qa_result);
      }
      await loadData();
      await loadPageRevisions(editorPage.id);
      if (runQa) {
        await loadPageQa(editorPage.id);
      }
      setMessage(
        runQa
          ? `${editorPage.page_title} saved, revision recorded, and QA rerun.`
          : `${editorPage.page_title} saved and revision recorded.`
      );
    } catch (err) {
      if (err instanceof ApiError) {
        setEditorErrors(editorErrorsFromDetail(err.detail));
      }
      setError(err instanceof Error ? err.message : "Unable to save draft.");
    } finally {
      setEditorSaving(false);
    }
  }

  async function saveReviewNotes() {
    if (!selectedPage) return;
    setWorking(true);
    setMessage(null);
    setError(null);
    try {
      await apiRequest<GeneratedPage>(`/api/generated-pages/${selectedPage.id}/review`, {
        method: "PATCH",
        body: JSON.stringify({
          internal_notes: reviewNotes || null,
          last_reviewed_by: reviewedBy || null
        })
      });
      await loadData();
      setMessage(`Review notes saved for ${selectedPage.page_title}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save review notes.");
    } finally {
      setWorking(false);
    }
  }

  async function assignMedia() {
    if (!selectedPage || !selectedImageId) {
      return;
    }
    setWorking(true);
    setError(null);
    setMessage(null);
    try {
      const hasHero = mediaAssignments.some((item) => item.image_role === "hero");
      if (mediaRole === "hero" && hasHero) {
        await apiRequest(`/api/generated-pages/${selectedPage.id}/media/hero`, {
          method: "PUT",
          body: JSON.stringify({ image_metadata_id: Number(selectedImageId) })
        });
      } else {
        await apiRequest(`/api/generated-pages/${selectedPage.id}/media`, {
          method: "POST",
          body: JSON.stringify({
            image_metadata_id: Number(selectedImageId),
            image_role: mediaRole
          })
        });
      }
      await loadPageMedia(selectedPage.id);
      setQaResult(null);
      await loadData();
      setSelectedImageId("");
      setMessage(`${humanize(mediaRole)} image assigned to ${selectedPage.page_title}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to assign page image.");
    } finally {
      setWorking(false);
    }
  }

  async function removeMedia(assignmentId: number) {
    if (!selectedPage) {
      return;
    }
    setWorking(true);
    setError(null);
    setMessage(null);
    try {
      await apiRequest(`/api/generated-pages/${selectedPage.id}/media/assignments/${assignmentId}`, {
        method: "DELETE"
      });
      await loadPageMedia(selectedPage.id);
      setQaResult(null);
      await loadData();
      setMessage(`Image assignment removed from ${selectedPage.page_title}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to remove page image.");
    } finally {
      setWorking(false);
    }
  }

  async function updateMediaAssignment(
    assignmentId: number,
    payload: Partial<AssignedMedia>
  ) {
    if (!selectedPage) return;
    setWorking(true);
    setError(null);
    setMessage(null);
    try {
      await apiRequest(
        `/api/generated-pages/${selectedPage.id}/media/assignments/${assignmentId}`,
        {
          method: "PATCH",
          body: JSON.stringify(payload)
        }
      );
      await loadPageMedia(selectedPage.id);
      setQaResult(null);
      await loadData();
      setMessage("Page-specific media settings saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save media settings.");
    } finally {
      setWorking(false);
    }
  }

  async function reorderMedia(imageRole: string, assignmentIds: number[]) {
    if (!selectedPage) return;
    setWorking(true);
    setError(null);
    try {
      await apiRequest(`/api/generated-pages/${selectedPage.id}/media/order/${imageRole}`, {
        method: "PUT",
        body: JSON.stringify({ assignment_ids: assignmentIds })
      });
      await loadPageMedia(selectedPage.id);
      setQaResult(null);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to reorder page media.");
    } finally {
      setWorking(false);
    }
  }

  async function previewBatch() {
    setWorking(true);
    setMessage(null);
    setError(null);
    try {
      const preview = await apiRequest<BatchPreview>("/api/generated-pages/generate-batch-preview", {
        method: "POST",
        body: JSON.stringify(batchPayload())
      });
      setBatchPreview(preview);
      setMessage(`Preview found ${preview.eligible_count} eligible draft pages and ${preview.skipped_count} skipped pages.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to preview batch.");
    } finally {
      setWorking(false);
    }
  }

  async function runBatch() {
    if (!batchPreview || batchPreview.eligible_count === 0) {
      return;
    }
    setWorking(true);
    setMessage(null);
    setError(null);
    try {
      const result = await apiRequest<BatchResult>("/api/generated-pages/generate-batch", {
        method: "POST",
        body: JSON.stringify(batchPayload(true))
      });
      setMessage(`${result.generated_count} draft pages generated; ${result.skipped_count} pages skipped.`);
      setBatchPreview(null);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to generate batch.");
    } finally {
      setWorking(false);
    }
  }

  async function generateSingle(page: GeneratedPage) {
    setGeneratingPageId(page.id);
    setMessage(null);
    setError(null);
    try {
      await apiRequest(`/api/generated-pages/${page.id}/generate-draft`, {
        method: "POST",
        body: JSON.stringify({ allow_overwrite: false })
      });
      setSelectedPageId(page.id);
      setMessage(`${page.page_title} draft generated.`);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to generate page draft.");
    } finally {
      setGeneratingPageId(null);
    }
  }

  async function approveDraft(page: GeneratedPage) {
    setWorking(true);
    setMessage(null);
    setError(null);
    try {
      await apiRequest<GeneratedPage>(`/api/generated-pages/${page.id}/approve`, {
        method: "POST",
        body: JSON.stringify({ approved_by: page.last_reviewed_by ?? null })
      });
      setMessage(`${page.page_title} marked approved.`);
      await loadData();
      await loadPageQa(page.id);
      await loadApprovalHistory(page.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to approve draft.");
    } finally {
      setWorking(false);
    }
  }

  async function runPageQa(page: GeneratedPage) {
    setQaRunningPageId(page.id);
    setMessage(null);
    setError(null);
    try {
      const result = await apiRequest<PageQAResult>(`/api/generated-pages/${page.id}/qa/run`, {
        method: "POST"
      });
      if (selectedPageId === page.id) {
        setQaResult(result);
      }
      setMessage(`${page.page_title} QA status: ${humanize(result.readiness_status)}.`);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to run page QA.");
    } finally {
      setQaRunningPageId(null);
    }
  }

  function qaBatchPayload(confirm = false) {
    return {
      county_ids: countyFilter === "all" ? [] : [Number(countyFilter)],
      city_ids: cityFilter === "all" ? [] : [Number(cityFilter)],
      page_status: statusFilter === "all" ? null : statusFilter,
      confirm
    };
  }

  async function previewQaBatch() {
    setWorking(true);
    setMessage(null);
    setError(null);
    try {
      const result = await apiRequest<QABatchResponse>("/api/generated-pages/qa/batch-preview", {
        method: "POST",
        body: JSON.stringify(qaBatchPayload())
      });
      setQaBatchPreview(result);
      setMessage(`QA preview checked ${result.matched_count} pages without saving results.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to preview batch QA.");
    } finally {
      setWorking(false);
    }
  }

  async function runQaBatch() {
    if (!qaBatchPreview) return;
    setWorking(true);
    setMessage(null);
    setError(null);
    try {
      const result = await apiRequest<QABatchResponse>("/api/generated-pages/qa/batch-run", {
        method: "POST",
        body: JSON.stringify(qaBatchPayload(true))
      });
      setQaBatchPreview(result);
      setMessage(`Saved QA results for ${result.saved_count} pages.`);
      await loadData();
      if (selectedPageId) await loadPageQa(selectedPageId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to run batch QA.");
    } finally {
      setWorking(false);
    }
  }

  return (
    <section className="page">
      <header className="pageHeader">
        <div>
          <p className="eyebrow">Draft Queue</p>
          <h1>Generated Pages</h1>
        </div>
        <span className="countBadge">{cityServiceCount} city-service pages</span>
      </header>

      {message && <div className="successAlert">{message}</div>}
      {error && <div className="alert">{error}</div>}

      <section className="panel batchPanel">
        <div className="panelHeader">
          <div>
            <h2>Batch Draft Generation</h2>
            <p>Preview the current filters before generating draft content.</p>
          </div>
          <div className="formActions">
            <button className="secondaryButton buttonWithIcon" type="button" onClick={previewBatch} disabled={working}>
              <ListChecks size={17} aria-hidden="true" />
              {working && !batchPreview ? "Checking..." : "Preview Batch"}
            </button>
            <button
              className="primaryButton buttonWithIcon"
              type="button"
              onClick={runBatch}
              disabled={working || !batchPreview || batchPreview.eligible_count === 0}
            >
              <Sparkles size={17} aria-hidden="true" />
              Generate {batchPreview?.eligible_count ?? 0} Drafts
            </button>
          </div>
        </div>

        <div className="filterBar generatedPageFilters">
          <label>
            <span>County</span>
            <select
              value={countyFilter}
              onChange={(event) => {
                setCountyFilter(event.target.value);
                setCityFilter("all");
                clearBatchPreview();
              }}
            >
              <option value="all">All counties</option>
              {counties.map((county) => (
                <option key={county.id} value={county.id}>
                  {county.county_name}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>City</span>
            <select
              value={cityFilter}
              onChange={(event) => {
                setCityFilter(event.target.value);
                clearBatchPreview();
              }}
            >
              <option value="all">All cities</option>
              {cityOptions.map((city) => (
                <option key={city.id} value={city.id}>
                  {city.city_name}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Status</span>
            <select
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(event.target.value);
                clearBatchPreview();
              }}
            >
              <option value="all">All statuses</option>
              {statusOptions.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>QA Readiness</span>
            <select value={qaFilter} onChange={(event) => setQaFilter(event.target.value)}>
              <option value="all">All</option>
              <option value="ready">Ready</option>
              <option value="needs_review">Needs Review</option>
              <option value="blocked">Blocked</option>
              <option value="has_warnings">Has Warnings</option>
              <option value="has_blockers">Has Blockers</option>
              <option value="not_run">QA Not Run</option>
            </select>
          </label>
        </div>

        {batchPreview && (
          <div className="batchSummary" aria-live="polite">
            <span>Matched: {batchPreview.matched_count}</span>
            <span>Eligible drafts: {batchPreview.eligible_count}</span>
            <span>Skipped: {batchPreview.skipped_count}</span>
          </div>
        )}
      </section>

      <section className="panel qaBatchPanel">
        <div className="panelHeader">
          <div>
            <h2>Batch QA Readiness</h2>
            <p>Preview current filters without saving, then run QA when the scope looks right.</p>
          </div>
          <div className="formActions">
            <button className="secondaryButton buttonWithIcon" type="button" onClick={previewQaBatch} disabled={working}>
              <ShieldCheck size={17} aria-hidden="true" />
              Preview QA
            </button>
            <button
              className="primaryButton buttonWithIcon"
              type="button"
              onClick={runQaBatch}
              disabled={working || !qaBatchPreview}
            >
              <ListChecks size={17} aria-hidden="true" />
              Run QA for {qaBatchPreview?.matched_count ?? 0}
            </button>
          </div>
        </div>
        {qaBatchPreview ? (
          <>
            <div className="qaBatchSummary" aria-live="polite">
              <span>Matched: {qaBatchPreview.matched_count}</span>
              <span className="ready">Ready: {qaBatchPreview.ready_count}</span>
              <span className="needs_review">Needs review: {qaBatchPreview.needs_review_count}</span>
              <span className="blocked">Blocked: {qaBatchPreview.blocked_count}</span>
            </div>
            <div className="qaCandidatePreview">
              {qaBatchPreview.candidates.slice(0, 8).map((candidate) => (
                <div key={candidate.page_id}>
                  <span>{candidate.city_name || candidate.page_title}</span>
                  <QAStatusBadge status={candidate.readiness_status} />
                  <small>{candidate.failed_count} blockers | {candidate.warning_count} warnings</small>
                </div>
              ))}
              {qaBatchPreview.candidates.length > 8 && (
                <p>Plus {qaBatchPreview.candidates.length - 8} additional pages in this batch.</p>
              )}
            </div>
          </>
        ) : (
          <p className="mutedText">Uses the county, city, and page-status filters above.</p>
        )}
      </section>

      <section className="panel tablePanel generatedPagesTable">
        <div className="panelHeader">
          <h2>Page Queue</h2>
          <span className="countBadge">{filteredPages.length} shown</span>
        </div>
        {loading ? (
          <p>Loading generated pages...</p>
        ) : (
          <div className="tableWrap">
            <table>
              <thead>
                <tr>
                  <th>Page Title</th>
                  <th>City</th>
                  <th>County</th>
                  <th>Page Status</th>
                  <th>Generation</th>
                  <th>QA Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredPages.map((page) => {
                  const city = page.city_id ? cityById.get(page.city_id) : undefined;
                  const canGenerate = page.status === "draft";
                  return (
                    <tr key={page.id}>
                      <td>
                        {page.page_title}
                        {(approvalCounts.get(page.id) ?? 0) > 0 && (
                          <span className="approvalHistoryIndicator">
                            <FileClock size={13} aria-hidden="true" />
                            Approved before
                          </span>
                        )}
                      </td>
                      <td>{city?.city_name ?? "-"}</td>
                      <td>{page.county_id ? countyNameById.get(page.county_id) ?? page.county_id : "-"}</td>
                      <td>{page.status}</td>
                      <td>{humanize(page.generation_status)}</td>
                      <td><QAStatusBadge status={page.qa_status} /></td>
                      <td className="actionsCell">
                        <button
                          className="linkButton buttonWithIcon"
                          type="button"
                          onClick={() => setSelectedPageId(page.id)}
                        >
                          <Eye size={15} aria-hidden="true" />
                          Review
                        </button>
                        {page.status === "draft" && page.draft_content && (
                          <button
                            className="secondaryButton buttonWithIcon"
                            type="button"
                            onClick={() => openEditor(page)}
                          >
                            <Pencil size={15} aria-hidden="true" />
                            Edit Draft
                          </button>
                        )}
                        {((page.qa_result?.warning_count ?? 0) > 0 ||
                          (page.qa_result?.failed_count ?? 0) > 0) && (
                          <button
                            className="warningButton buttonWithIcon"
                            type="button"
                            onClick={() => setSelectedPageId(page.id)}
                          >
                            <ClipboardList size={15} aria-hidden="true" />
                            Fix Issues
                          </button>
                        )}
                        {page.draft_content && (
                          <Link
                            className="linkButton buttonWithIcon previewPageLink"
                            to={`/generated-pages/${page.id}/preview`}
                          >
                            <Monitor size={15} aria-hidden="true" />
                            Preview Page
                          </Link>
                        )}
                        <Link
                          className="linkButton buttonWithIcon"
                          to={`/generated-pages/${page.id}/export`}
                        >
                          <FileJson size={15} aria-hidden="true" />
                          View Export Package
                        </Link>
                        <button
                          className="secondaryButton buttonWithIcon"
                          type="button"
                          disabled={qaRunningPageId === page.id}
                          onClick={() => runPageQa(page)}
                        >
                          <ShieldCheck size={15} aria-hidden="true" />
                          {qaRunningPageId === page.id ? "Checking..." : "Run QA"}
                        </button>
                        <button
                          className="primaryButton buttonWithIcon"
                          type="button"
                          disabled={!canGenerate || generatingPageId === page.id}
                          onClick={() => generateSingle(page)}
                          title={canGenerate ? "Generate or refresh this draft" : "Only draft pages can be generated"}
                        >
                          <Sparkles size={15} aria-hidden="true" />
                          {generatingPageId === page.id ? "Generating..." : "Generate Draft"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <MediaAssignmentPanel
        page={selectedPage}
        assignments={mediaAssignments}
        eligibleImages={eligibleImages}
        mediaRole={mediaRole}
        selectedImageId={selectedImageId}
        working={working}
        onRoleChange={setMediaRole}
        onImageChange={setSelectedImageId}
        onAssign={assignMedia}
        onRemove={removeMedia}
        onUpdate={updateMediaAssignment}
        onReorder={reorderMedia}
      />

      <QAPanel
        page={selectedPage}
        result={qaResult}
        working={working || qaRunningPageId === selectedPage?.id}
        onRun={runPageQa}
      />

      <PageEditorPanel
        page={editorPage}
        draft={editorDraft}
        qaResult={editorPageId === selectedPageId ? qaResult : null}
        createdBy={editorCreatedBy}
        reason={editorReason}
        errors={editorErrors}
        saving={editorSaving}
        dirty={editorDirty}
        onDraftChange={setEditorDraft}
        onCreatedByChange={setEditorCreatedBy}
        onReasonChange={setEditorReason}
        onSave={() => saveEditor(false)}
        onSaveAndQa={() => saveEditor(true)}
        onClose={closeEditor}
      />

      <RevisionHistoryPanel page={selectedPage} revisions={pageRevisions} />

      <ReviewNotesPanel
        page={selectedPage}
        notes={reviewNotes}
        reviewedBy={reviewedBy}
        working={working}
        onNotesChange={setReviewNotes}
        onReviewedByChange={setReviewedBy}
        onSave={saveReviewNotes}
      />

      <ApprovalHistoryPanel page={selectedPage} history={approvalHistory} />

      <DraftReview
        page={selectedPage}
        qaResult={qaResult}
        onApprove={approveDraft}
        working={working}
      />
    </section>
  );
}

function MediaAssignmentPanel({
  page,
  assignments,
  eligibleImages,
  mediaRole,
  selectedImageId,
  working,
  onRoleChange,
  onImageChange,
  onAssign,
  onRemove,
  onUpdate,
  onReorder
}: {
  page: GeneratedPage | null;
  assignments: AssignedMedia[];
  eligibleImages: ImageMetadata[];
  mediaRole: string;
  selectedImageId: string;
  working: boolean;
  onRoleChange: (role: string) => void;
  onImageChange: (imageId: string) => void;
  onAssign: () => Promise<void>;
  onRemove: (assignmentId: number) => Promise<void>;
  onUpdate: (assignmentId: number, payload: Partial<AssignedMedia>) => Promise<void>;
  onReorder: (imageRole: string, assignmentIds: number[]) => Promise<void>;
}) {
  const [editing, setEditing] = useState<AssignedMedia | null>(null);
  const groupedAssignments = {
    hero: assignments.filter((item) => item.image_role === "hero"),
    service: assignments.filter((item) => item.image_role === "service").sort(compareMedia),
    support: assignments.filter((item) => item.image_role === "support").sort(compareMedia)
  };
  const hasHero = groupedAssignments.hero.length > 0;

  useEffect(() => {
    if (!editing) return;
    const refreshed = assignments.find((item) => item.assignment_id === editing.assignment_id);
    if (!refreshed) {
      setEditing(null);
    }
  }, [assignments, editing]);

  function moveAssignment(assignment: AssignedMedia, direction: -1 | 1) {
    const group = groupedAssignments[assignment.image_role as "hero" | "service" | "support"];
    const index = group.findIndex((item) => item.assignment_id === assignment.assignment_id);
    const targetIndex = index + direction;
    if (index < 0 || targetIndex < 0 || targetIndex >= group.length) return;
    const orderedIds = group.map((item) => item.assignment_id);
    [orderedIds[index], orderedIds[targetIndex]] = [orderedIds[targetIndex], orderedIds[index]];
    onReorder(assignment.image_role, orderedIds);
  }

  return (
    <section className="panel mediaAssignmentPanel">
      <div className="panelHeader">
        <div>
          <h2>Preview Media</h2>
          <p>Assign reviewed images by page role without changing draft content.</p>
        </div>
        {page?.draft_content && (
          <Link className="linkButton buttonWithIcon previewPageLink" to={`/generated-pages/${page.id}/preview`}>
            <Monitor size={16} aria-hidden="true" />
            Open Preview
          </Link>
        )}
      </div>

      {!page ? (
        <p>Select a generated page to manage its preview media.</p>
      ) : (
        <div className="pageMediaManager">
          <div className="mediaAddBar">
            <label>
              <span>Image Role</span>
              <select value={mediaRole} onChange={(event) => onRoleChange(event.target.value)}>
                <option value="hero">Hero</option>
                <option value="service">Service</option>
                <option value="support">Support</option>
              </select>
            </label>
            <label>
              <span>Reviewed Image</span>
              <select value={selectedImageId} onChange={(event) => onImageChange(event.target.value)}>
                <option value="">No image selected</option>
                {eligibleImages.map((image) => (
                  <option key={image.id} value={image.id}>
                    {image.image_title ?? image.file_name}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="primaryButton buttonWithIcon"
              type="button"
              disabled={working || !selectedImageId}
              onClick={onAssign}
            >
              <ImageIcon size={16} aria-hidden="true" />
              {mediaRole === "hero" && hasHero ? "Replace Hero" : "Add Image"}
            </button>
          </div>

          <div className="assignmentGroups">
            {(["hero", "service", "support"] as const).map((role) => {
              const group = groupedAssignments[role];
              return (
                <section key={role} className="assignmentGroup">
                  <div className="assignmentGroupHeader">
                    <h3>{humanize(role)}</h3>
                    <span>{group.length} assigned</span>
                  </div>
                  {group.length ? (
                    <div className="assignmentList">
                      {group.map((assignment, index) => (
                        <article key={assignment.assignment_id} className="assignmentItem">
                          <img
                            src={assignment.image.thumbnail_url || assignment.image.optimized_url || assignment.image.asset_url}
                            alt={assignment.effective_alt_text}
                            style={mediaFocalStyle(assignment.effective_focal_x, assignment.effective_focal_y)}
                          />
                          <div className="assignmentSummary">
                            <strong>{assignment.image.image_title ?? assignment.image.file_name}</strong>
                            <span>{assignment.effective_alt_text}</span>
                            <small>
                              {humanize(assignment.display_preset)} | Order {assignment.sort_order}
                              {assignment.override_focal_x !== null && assignment.override_focal_x !== undefined
                                ? " | Page focal"
                                : " | Global focal"}
                            </small>
                          </div>
                          <div className="assignmentActions">
                            {role !== "hero" && (
                              <>
                                <button
                                  className="iconButton"
                                  type="button"
                                  title="Move image up"
                                  aria-label={`Move ${assignment.image.image_title ?? "image"} up`}
                                  disabled={working || index === 0}
                                  onClick={() => moveAssignment(assignment, -1)}
                                >
                                  <ArrowUp size={16} aria-hidden="true" />
                                </button>
                                <button
                                  className="iconButton"
                                  type="button"
                                  title="Move image down"
                                  aria-label={`Move ${assignment.image.image_title ?? "image"} down`}
                                  disabled={working || index === group.length - 1}
                                  onClick={() => moveAssignment(assignment, 1)}
                                >
                                  <ArrowDown size={16} aria-hidden="true" />
                                </button>
                              </>
                            )}
                            <button
                              className="iconButton"
                              type="button"
                              title="Edit page media settings"
                              aria-label={`Edit ${assignment.image.image_title ?? "image"} settings`}
                              onClick={() => setEditing({ ...assignment })}
                            >
                              <Pencil size={16} aria-hidden="true" />
                            </button>
                            <button
                              className="iconButton dangerIconButton"
                              type="button"
                              title="Remove assignment"
                              aria-label={`Remove ${assignment.image.image_title ?? "image"} assignment`}
                              disabled={working}
                              onClick={() => onRemove(assignment.assignment_id)}
                            >
                              <Trash2 size={16} aria-hidden="true" />
                            </button>
                          </div>
                          {editing?.assignment_id === assignment.assignment_id && (
                            <AssignmentOverrideEditor
                              assignment={editing}
                              working={working}
                              onChange={setEditing}
                              onCancel={() => setEditing(null)}
                              onSave={async () => {
                                await onUpdate(editing.assignment_id, {
                                  override_focal_x: editing.override_focal_x,
                                  override_focal_y: editing.override_focal_y,
                                  override_alt_text: editing.override_alt_text,
                                  display_preset: editing.display_preset
                                });
                                setEditing(null);
                              }}
                            />
                          )}
                        </article>
                      ))}
                    </div>
                  ) : (
                    <div className="mediaEmptyState compact">
                      <ImageIcon size={20} aria-hidden="true" />
                      <span>No {role} images assigned.</span>
                    </div>
                  )}
                </section>
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
}

function AssignmentOverrideEditor({
  assignment,
  working,
  onChange,
  onCancel,
  onSave
}: {
  assignment: AssignedMedia;
  working: boolean;
  onChange: (assignment: AssignedMedia) => void;
  onCancel: () => void;
  onSave: () => Promise<void>;
}) {
  const hasFocalOverride =
    assignment.override_focal_x !== null &&
    assignment.override_focal_x !== undefined &&
    assignment.override_focal_y !== null &&
    assignment.override_focal_y !== undefined;
  const focalX = hasFocalOverride ? assignment.override_focal_x! : assignment.image.focal_x;
  const focalY = hasFocalOverride ? assignment.override_focal_y! : assignment.image.focal_y;

  function setFocal(focal_x: number, focal_y: number) {
    onChange({ ...assignment, override_focal_x: focal_x, override_focal_y: focal_y });
  }

  return (
    <div className="assignmentOverrideEditor">
      <div className="overridePreview" style={mediaFocalStyle(focalX, focalY)}>
        <img
          src={assignment.image.optimized_url || assignment.image.asset_url}
          alt=""
        />
        <i aria-hidden="true" />
      </div>
      <div className="overrideFields">
        <label>
          <span>Display Preset</span>
          <select
            value={assignment.display_preset}
            onChange={(event) => onChange({ ...assignment, display_preset: event.target.value as AssignedMedia["display_preset"] })}
          >
            <option value="hero_desktop">Hero Desktop / Mobile</option>
            <option value="hero_mobile">Hero Mobile</option>
            <option value="card_thumbnail">Card Thumbnail</option>
            <option value="square">Square</option>
            <option value="original">Original</option>
          </select>
        </label>
        <label>
          <span>Page Alt Override</span>
          <input
            value={assignment.override_alt_text ?? ""}
            placeholder={assignment.image.reviewed_alt_text}
            onChange={(event) => onChange({ ...assignment, override_alt_text: event.target.value || null })}
          />
        </label>
        <label>
          <span>Horizontal Override <output>{focalX.toFixed(2)}</output></span>
          <input
            type="range"
            min="0"
            max="1"
            step="0.01"
            value={focalX}
            onChange={(event) => setFocal(Number(event.target.value), focalY)}
          />
        </label>
        <label>
          <span>Vertical Override <output>{focalY.toFixed(2)}</output></span>
          <input
            type="range"
            min="0"
            max="1"
            step="0.01"
            value={focalY}
            onChange={(event) => setFocal(focalX, Number(event.target.value))}
          />
        </label>
        <div className="formActions">
          <button
            className="secondaryButton buttonWithIcon"
            type="button"
            disabled={!hasFocalOverride}
            onClick={() => onChange({ ...assignment, override_focal_x: null, override_focal_y: null })}
          >
            <RotateCcw size={15} aria-hidden="true" />
            Use Global Focal
          </button>
          <button className="primaryButton" type="button" disabled={working} onClick={onSave}>
            Save Overrides
          </button>
          <button className="secondaryButton" type="button" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

function compareMedia(left: AssignedMedia, right: AssignedMedia) {
  return left.sort_order - right.sort_order || left.assignment_id - right.assignment_id;
}

function mediaFocalStyle(focalX: number, focalY: number) {
  return {
    "--focal-x": `${Math.min(1, Math.max(0, focalX)) * 100}%`,
    "--focal-y": `${Math.min(1, Math.max(0, focalY)) * 100}%`
  } as CSSProperties;
}

function QAPanel({
  page,
  result,
  working,
  onRun
}: {
  page: GeneratedPage | null;
  result: PageQAResult | null;
  working: boolean;
  onRun: (page: GeneratedPage) => Promise<void>;
}) {
  const issues = result?.checks.filter((check) => check.status !== "pass") ?? [];
  return (
    <section className="panel qaPanel" id="qa-panel">
      <div className="panelHeader">
        <div>
          <h2>Publication Readiness</h2>
          <p>Internal QA only. Running checks never approves or publishes a page.</p>
        </div>
        {page && (
          <div className="formActions">
            {page.draft_content && (
              <Link className="linkButton buttonWithIcon" to={`/generated-pages/${page.id}/preview?qa=1`}>
                <Monitor size={15} aria-hidden="true" />
                Preview with QA
              </Link>
            )}
            <button
              className="primaryButton buttonWithIcon"
              type="button"
              disabled={working}
              onClick={() => onRun(page)}
            >
              <ShieldCheck size={16} aria-hidden="true" />
              {working ? "Running QA..." : "Run QA"}
            </button>
          </div>
        )}
      </div>

      {!page ? (
        <p>Select a page to inspect its QA checklist.</p>
      ) : !result ? (
        <p>Loading QA checklist...</p>
      ) : (
        <>
          <div className="qaResultHeader">
            <QAStatusBadge status={result.readiness_status} />
            <span>{result.passed_count} passed</span>
            <span>{result.warning_count} warnings</span>
            <span>{result.failed_count} blockers</span>
            <small>{result.persisted ? "Saved result" : "Current preview; not saved"}</small>
          </div>
          <section className="qaRemediation">
            <div className="qaRemediationHeader">
              <div>
                <h3>QA Remediation</h3>
                <p>Guidance only. Atlas will not rewrite the draft automatically.</p>
              </div>
              <span className="countBadge">{issues.length} issues</span>
            </div>
            {issues.length === 0 ? (
              <p className="qaClearMessage">No warnings or blockers are present in the current QA result.</p>
            ) : (
              <div className="qaIssueList">
                {issues.map((check) => (
                  <article key={check.key} className={`qaIssue ${check.status}`}>
                    <div className="qaIssueTitle">
                      {check.status === "warning" ? (
                        <AlertTriangle size={18} aria-hidden="true" />
                      ) : (
                        <XCircle size={18} aria-hidden="true" />
                      )}
                      <strong>{check.label}</strong>
                      <span className={`qaIssueStatus ${check.status}`}>{check.status}</span>
                    </div>
                    <p>{check.message}</p>
                    <dl>
                      <div>
                        <dt>Suggested fix</dt>
                        <dd>{check.suggested_fix}</dd>
                      </div>
                      <div>
                        <dt>Likely location</dt>
                        <dd>{humanize(check.issue_location)}</dd>
                      </div>
                    </dl>
                  </article>
                ))}
              </div>
            )}
          </section>
          <div className="qaChecklist">
            {result.checks.map((check) => (
              <article key={check.key} className={`qaCheck ${check.status}`}>
                {check.status === "pass" ? (
                  <CircleCheck size={18} aria-hidden="true" />
                ) : check.status === "warning" ? (
                  <AlertTriangle size={18} aria-hidden="true" />
                ) : (
                  <XCircle size={18} aria-hidden="true" />
                )}
                <div>
                  <strong>{check.label}</strong>
                  <span>{check.message}</span>
                </div>
              </article>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function PageEditorPanel({
  page,
  draft,
  qaResult,
  createdBy,
  reason,
  errors,
  saving,
  dirty,
  onDraftChange,
  onCreatedByChange,
  onReasonChange,
  onSave,
  onSaveAndQa,
  onClose
}: {
  page: GeneratedPage | null;
  draft: ManualDraftFields | null;
  qaResult: PageQAResult | null;
  createdBy: string;
  reason: string;
  errors: EditorValidationError[];
  saving: boolean;
  dirty: boolean;
  onDraftChange: (draft: ManualDraftFields) => void;
  onCreatedByChange: (value: string) => void;
  onReasonChange: (value: string) => void;
  onSave: () => Promise<void>;
  onSaveAndQa: () => Promise<void>;
  onClose: () => void;
}) {
  if (!page || !draft) {
    return (
      <section className="panel pageEditorPanel">
        <h2>Safe Page Editor</h2>
        <p>Choose Edit Draft on a draft page to make manual structured changes.</p>
      </section>
    );
  }

  function updateField(field: keyof ManualDraftFields, value: string) {
    onDraftChange({ ...draft!, [field]: value });
  }

  function updateFaq(index: number, field: "question" | "answer", value: string) {
    const faqItems = draft!.faq_items.map((item, itemIndex) =>
      itemIndex === index ? { ...item, [field]: value } : item
    );
    onDraftChange({ ...draft!, faq_items: faqItems });
  }

  function addFaq() {
    onDraftChange({
      ...draft!,
      faq_items: [...draft!.faq_items, { question: "", answer: "" }]
    });
  }

  function removeFaq(index: number) {
    onDraftChange({
      ...draft!,
      faq_items: draft!.faq_items.filter((_, itemIndex) => itemIndex !== index)
    });
  }

  return (
    <section className="panel pageEditorPanel">
      <div className="panelHeader editorHeader">
        <div>
          <p className="eyebrow">Manual Editing</p>
          <h2>Safe Page Editor</h2>
          <p>{page.page_title}</p>
        </div>
        <div className="editorHeaderActions">
          {dirty && <span className="unsavedBadge">Unsaved changes</span>}
          <button
            className="iconButton"
            type="button"
            onClick={onClose}
            aria-label="Close draft editor"
            title="Close editor"
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>
      </div>

      <div className="editorSafetyNotice">
        Manual edits only. Atlas validates the complete draft and will not rewrite or approve it automatically.
      </div>

      {errors.length > 0 && (
        <div className="editorValidationAlert" role="alert">
          <strong>Draft was not saved.</strong>
          <ul>
            {errors.map((validationError, index) => (
              <li key={`${validationError.field}-${index}`}>{validationError.message}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="editorFields">
        <EditorTextField
          label="Hero Headline"
          value={draft.hero_headline}
          field="hero_headline"
          errors={errors}
          hints={editorHints(qaResult, "hero_headline")}
          onChange={(value) => updateField("hero_headline", value)}
          compact
        />
        <EditorTextField
          label="Hero Subheadline"
          value={draft.hero_subheadline}
          field="hero_subheadline"
          errors={errors}
          hints={editorHints(qaResult, "hero_subheadline")}
          onChange={(value) => updateField("hero_subheadline", value)}
        />
        <EditorTextField
          label="Introduction"
          value={draft.intro}
          field="intro"
          errors={errors}
          hints={editorHints(qaResult, "intro")}
          onChange={(value) => updateField("intro", value)}
        />
        <EditorTextField
          label="Service Explanation"
          value={draft.service_explanation}
          field="service_explanation"
          errors={errors}
          hints={editorHints(qaResult, "service_explanation")}
          onChange={(value) => updateField("service_explanation", value)}
        />
        <EditorTextField
          label="Local City Section"
          value={draft.local_city_section}
          field="local_city_section"
          errors={errors}
          hints={editorHints(qaResult, "local_city_section")}
          onChange={(value) => updateField("local_city_section", value)}
        />
        <EditorTextField
          label="Process Section"
          value={draft.process_section}
          field="process_section"
          errors={errors}
          hints={editorHints(qaResult, "process_section")}
          onChange={(value) => updateField("process_section", value)}
        />
        <EditorTextField
          label="Preparation and Re-entry"
          value={draft.prep_reentry_section}
          field="prep_reentry_section"
          errors={errors}
          hints={editorHints(qaResult, "prep_reentry_section")}
          onChange={(value) => updateField("prep_reentry_section", value)}
        />
        <EditorTextField
          label="Why Choose Flo-Zone"
          value={draft.why_choose_section}
          field="why_choose_section"
          errors={errors}
          hints={editorHints(qaResult, "why_choose_section")}
          onChange={(value) => updateField("why_choose_section", value)}
        />

        <section className="editorFaqSection">
          <div className="editorFieldHeader">
            <div>
              <h3>Frequently Asked Questions</h3>
              <EditorHints
                hints={editorHints(qaResult, "faq_items")}
                errors={fieldErrors(errors, "faq_items")}
              />
            </div>
            <button className="secondaryButton buttonWithIcon" type="button" onClick={addFaq}>
              <Plus size={16} aria-hidden="true" />
              Add FAQ
            </button>
          </div>
          <div className="editorFaqList">
            {draft.faq_items.map((item, index) => (
              <article key={index}>
                <div className="editorFaqTitle">
                  <strong>FAQ {index + 1}</strong>
                  <button
                    className="iconButton dangerIconButton"
                    type="button"
                    onClick={() => removeFaq(index)}
                    aria-label={`Remove FAQ ${index + 1}`}
                    title="Remove FAQ"
                  >
                    <Trash2 size={16} aria-hidden="true" />
                  </button>
                </div>
                <label>
                  <span>Question</span>
                  <input
                    value={item.question}
                    onChange={(event) => updateFaq(index, "question", event.target.value)}
                  />
                </label>
                <label>
                  <span>Answer</span>
                  <textarea
                    value={item.answer}
                    onChange={(event) => updateFaq(index, "answer", event.target.value)}
                  />
                </label>
              </article>
            ))}
          </div>
        </section>

        <EditorTextField
          label="Call to Action"
          value={draft.call_to_action}
          field="call_to_action"
          errors={errors}
          hints={editorHints(qaResult, "call_to_action")}
          onChange={(value) => updateField("call_to_action", value)}
        />
      </div>

      <div className="editorMetadata">
        <label>
          <span>Edited By</span>
          <input
            value={createdBy}
            onChange={(event) => onCreatedByChange(event.target.value)}
            placeholder="Optional editor name"
          />
        </label>
        <label>
          <span>Revision Reason</span>
          <input
            value={reason}
            onChange={(event) => onReasonChange(event.target.value)}
            placeholder="Optional reason for this change"
          />
        </label>
      </div>

      <div className="editorActions">
        <button
          className="secondaryButton buttonWithIcon"
          type="button"
          disabled={saving || !dirty}
          onClick={onSave}
        >
          <Save size={16} aria-hidden="true" />
          {saving ? "Saving..." : "Save Draft"}
        </button>
        <button
          className="primaryButton buttonWithIcon"
          type="button"
          disabled={saving || !dirty}
          onClick={onSaveAndQa}
        >
          <ShieldCheck size={16} aria-hidden="true" />
          {saving ? "Saving..." : "Save Draft + Run QA"}
        </button>
      </div>
    </section>
  );
}

function EditorTextField({
  label,
  value,
  field,
  errors,
  hints,
  onChange,
  compact = false
}: {
  label: string;
  value: string;
  field: string;
  errors: EditorValidationError[];
  hints: string[];
  onChange: (value: string) => void;
  compact?: boolean;
}) {
  const relatedErrors = fieldErrors(errors, field);
  return (
    <label className="editorField">
      <span>{label}</span>
      {compact ? (
        <input value={value} onChange={(event) => onChange(event.target.value)} />
      ) : (
        <textarea value={value} onChange={(event) => onChange(event.target.value)} />
      )}
      <EditorHints hints={hints} errors={relatedErrors} />
    </label>
  );
}

function EditorHints({ hints, errors }: { hints: string[]; errors: string[] }) {
  return (
    <>
      {hints.map((hint) => (
        <small key={hint} className="editorQaHint">
          <AlertTriangle size={13} aria-hidden="true" />
          {hint}
        </small>
      ))}
      {errors.map((validationError) => (
        <small key={validationError} className="editorFieldError">{validationError}</small>
      ))}
    </>
  );
}

function RevisionHistoryPanel({
  page,
  revisions
}: {
  page: GeneratedPage | null;
  revisions: GeneratedPageRevision[];
}) {
  return (
    <section className="panel revisionHistoryPanel">
      <div className="panelHeader">
        <div>
          <h2>Revision History</h2>
          <p>Manual draft saves only. QA runs and review notes do not create revisions.</p>
        </div>
        <span className="countBadge">{revisions.length} revisions</span>
      </div>
      {!page ? (
        <p>Select a page to inspect its revision history.</p>
      ) : revisions.length === 0 ? (
        <p>No manual draft revisions have been recorded for this page.</p>
      ) : (
        <div className="revisionHistoryList">
          {revisions.map((revision) => (
            <article key={revision.id}>
              <div className="revisionHistoryTitle">
                <FileClock size={18} aria-hidden="true" />
                <strong>{formatDateTime(revision.created_at)}</strong>
                <span>{revision.created_by ?? "Editor not specified"}</span>
              </div>
              <p>{revision.reason || "No revision reason supplied."}</p>
              <div className="revisionChangedFields">
                {revision.changed_fields.map((field) => (
                  <span key={field}>{humanize(field)}</span>
                ))}
              </div>
              <dl>
                <div><dt>Before</dt><dd><code>{revision.draft_hash_before}</code></dd></div>
                <div><dt>After</dt><dd><code>{revision.draft_hash_after}</code></dd></div>
              </dl>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function ReviewNotesPanel({
  page,
  notes,
  reviewedBy,
  working,
  onNotesChange,
  onReviewedByChange,
  onSave
}: {
  page: GeneratedPage | null;
  notes: string;
  reviewedBy: string;
  working: boolean;
  onNotesChange: (value: string) => void;
  onReviewedByChange: (value: string) => void;
  onSave: () => Promise<void>;
}) {
  return (
    <section className="panel reviewNotesPanel">
      <div className="panelHeader">
        <div>
          <h2>Manual Fix Notes</h2>
          <p>Internal review notes only. Saving does not change draft content or page status.</p>
        </div>
        {page?.last_reviewed_at && (
          <small>Last reviewed {formatDateTime(page.last_reviewed_at)}</small>
        )}
      </div>
      {!page ? (
        <p>Select a page to record remediation notes.</p>
      ) : (
        <div className="reviewNotesForm">
          <label>
            <span>Internal Notes</span>
            <textarea
              value={notes}
              onChange={(event) => onNotesChange(event.target.value)}
              placeholder="Record the manual changes or follow-up this page needs."
            />
          </label>
          <label>
            <span>Reviewed By</span>
            <input
              value={reviewedBy}
              onChange={(event) => onReviewedByChange(event.target.value)}
              placeholder="Optional reviewer name"
            />
          </label>
          <button className="primaryButton buttonWithIcon" type="button" disabled={working} onClick={onSave}>
            <Save size={16} aria-hidden="true" />
            {working ? "Saving..." : "Save Review Notes"}
          </button>
        </div>
      )}
    </section>
  );
}

function ApprovalHistoryPanel({
  page,
  history
}: {
  page: GeneratedPage | null;
  history: ApprovalAudit[];
}) {
  return (
    <section className="panel approvalHistoryPanel" id="approval-history-panel">
      <div className="panelHeader">
        <div>
          <h2>Approval History</h2>
          <p>Immutable snapshots created only after an explicit, QA-ready approval.</p>
        </div>
        <span className="countBadge">{history.length} approvals</span>
      </div>
      {!page ? (
        <p>Select a page to inspect its approval history.</p>
      ) : history.length === 0 ? (
        <p>No successful approvals have been recorded for this page.</p>
      ) : (
        <div className="approvalHistoryList">
          {history.map((audit) => (
            <article key={audit.id}>
              <div className="approvalHistoryTitle">
                <FileClock size={18} aria-hidden="true" />
                <strong>{formatDateTime(audit.approved_at)}</strong>
                <QAStatusBadge status={audit.qa_status_at_approval} />
              </div>
              <dl>
                <div><dt>Approved by</dt><dd>{audit.approved_by ?? "Not specified"}</dd></div>
                <div><dt>Status</dt><dd>{audit.page_status_before} to {audit.page_status_after}</dd></div>
                <div><dt>Draft hash</dt><dd><code>{audit.draft_hash_at_approval}</code></dd></div>
                <div>
                  <dt>QA snapshot</dt>
                  <dd>
                    {audit.qa_result_snapshot.passed_count} passed,{" "}
                    {audit.qa_result_snapshot.warning_count} warnings,{" "}
                    {audit.qa_result_snapshot.failed_count} failed
                  </dd>
                </div>
              </dl>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function QAStatusBadge({ status }: { status: string }) {
  const normalized = status || "not_run";
  return <span className={`qaStatusBadge ${normalized}`}>{humanize(normalized)}</span>;
}

function DraftReview({
  page,
  qaResult,
  onApprove,
  working
}: {
  page: GeneratedPage | null;
  qaResult: PageQAResult | null;
  onApprove: (page: GeneratedPage) => Promise<void>;
  working: boolean;
}) {
  if (!page) {
    return (
      <section className="panel draftReview">
        <h2>Draft Review</h2>
        <p>Select a page to review its generated fields.</p>
      </section>
    );
  }

  const draft = page.draft_content;
  const canApprove =
    page.qa_status === "ready" &&
    qaResult?.persisted === true &&
    qaResult.readiness_status === "ready";
  return (
    <section className="panel draftReview">
      <div className="panelHeader">
        <div>
          <h2>{page.page_title}</h2>
          <p>
            {humanize(page.generation_status)} | {page.status}
          </p>
        </div>
        {draft && page.status === "draft" && (
          <button
            className="primaryButton buttonWithIcon"
            type="button"
            disabled={working || !canApprove}
            onClick={() => onApprove(page)}
            title={canApprove ? "Approve this QA-ready draft" : "Run QA and resolve blockers before approval"}
          >
            <CheckCircle2 size={17} aria-hidden="true" />
            Approve Draft
          </button>
        )}
      </div>

      {!draft ? (
        <p>No structured draft has been generated for this page.</p>
      ) : (
        <div className="draftSections">
          <DraftField label="Meta Title" value={draft.meta_title} />
          <DraftField label="Meta Description" value={draft.meta_description} />
          <DraftField label="H1" value={draft.h1} />
          <DraftField label="Introduction" value={draft.intro} />
          <DraftField label="Why It Matters" value={draft.why_it_matters} />
          <DraftField label="Signs" value={draft.signs_section} />
          <DraftField label="Process" value={draft.process_section} />
          <DraftField label="Preparation" value={draft.prep_section} />
          <DraftField label="Realtors and Property Managers" value={draft.realtor_property_manager_section} />
          <section className="draftField">
            <h3>Frequently Asked Questions</h3>
            <div className="faqReview">
              {draft.faq_items.map((item) => (
                <div key={item.question}>
                  <strong>{item.question}</strong>
                  <p>{item.answer}</p>
                </div>
              ))}
            </div>
          </section>
          <DraftField label="Call to Action" value={draft.call_to_action} />
          <DraftField label="Internal Notes" value={draft.internal_notes} muted />
        </div>
      )}
    </section>
  );
}

function DraftField({ label, value, muted = false }: { label: string; value: string; muted?: boolean }) {
  return (
    <section className={muted ? "draftField internalNotes" : "draftField"}>
      <h3>{label}</h3>
      <p>{value}</p>
    </section>
  );
}

function manualDraftFromPage(page: GeneratedPage): ManualDraftFields {
  const draft = page.draft_content;
  if (!draft) {
    return {
      hero_headline: "",
      hero_subheadline: "",
      intro: "",
      service_explanation: "",
      local_city_section: "",
      process_section: "",
      prep_reentry_section: "",
      why_choose_section: "",
      faq_items: [],
      call_to_action: ""
    };
  }
  return {
    hero_headline: draft.h1,
    hero_subheadline: draft.hero_subheadline || draft.meta_description,
    intro: draft.intro,
    service_explanation: draft.service_explanation || draft.why_it_matters,
    local_city_section: draft.local_city_section || draft.realtor_property_manager_section,
    process_section: draft.process_section,
    prep_reentry_section: draft.prep_section,
    why_choose_section:
      draft.why_choose_section ||
      "Choose Flo-Zone for licensed service, clear preparation guidance, and careful project coordination.",
    faq_items: draft.faq_items.map((item) => ({ ...item })),
    call_to_action: draft.call_to_action
  };
}

function editorErrorsFromDetail(detail: unknown): EditorValidationError[] {
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      const record = item as { loc?: Array<string | number>; msg?: string };
      const field = (record.loc ?? []).filter((part) => part !== "body" && part !== "draft").join(".");
      return { field: field || "draft", message: record.msg ?? "Draft validation failed." };
    });
  }
  if (detail && typeof detail === "object" && "errors" in detail) {
    const errors = (detail as { errors?: unknown }).errors;
    if (Array.isArray(errors)) {
      return errors.map((item) => {
        const record = item as { field?: string; message?: string };
        return {
          field: record.field ?? "draft",
          message: record.message ?? "Draft validation failed."
        };
      });
    }
  }
  return [];
}

function fieldErrors(errors: EditorValidationError[], field: string): string[] {
  return errors
    .filter((error) => error.field === field || error.field.startsWith(`${field}.`))
    .map((error) => error.message);
}

function editorHints(result: PageQAResult | null, field: keyof ManualDraftFields): string[] {
  if (!result) return [];
  const keysByField: Record<keyof ManualDraftFields, string[]> = {
    hero_headline: ["h1"],
    hero_subheadline: ["meta_description"],
    intro: ["intro"],
    service_explanation: ["why_it_matters", "service_name"],
    local_city_section: ["city_name", "county_county"],
    process_section: ["process_section"],
    prep_reentry_section: ["prep_section"],
    why_choose_section: ["license_operator"],
    faq_items: ["faqs"],
    call_to_action: ["call_to_action", "phone", "unsafe_phrases"]
  };
  const acceptedKeys = keysByField[field];
  return result.checks
    .filter((check) => check.status !== "pass" && acceptedKeys.includes(check.key))
    .map((check) => check.suggested_fix || check.message);
}

function humanize(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(new Date(value));
}

export default GeneratedPagesPage;
