from copy import deepcopy
from datetime import UTC, datetime
import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.services import automatic_cta_refresh as refresh_service
from app.models import Business, City, County, GeneratedPage, Service
from app.schemas.generation import DraftContent
from app.schemas.website_context import (
    WebsiteContextBrand,
    WebsiteContextBusiness,
    WebsiteContextGeography,
    WebsiteContextIdentity,
    WebsiteContextRead,
    WebsiteContextService,
    WebsiteContextSite,
)
from app.services.automatic_cta_refresh import (
    AUTOMATIC_CLASSIFICATION,
    EXCLUDED_CLASSIFICATION,
    LEGACY_SOURCE_COMMIT,
    MANIFEST_SCHEMA,
    SOURCE_OWNER,
    AutomaticCTARefreshError,
    _AUTHORITATIVE_SOURCE_TABLES,
    _assert_global_generated_page_inventory,
    _assert_exact_before_identity,
    _contains_governed_credential_copy_outside_cta,
    _timestamp,
    _canonical_hash,
    _lock_authoritative_source_tables,
    _require_effective_qa,
    automatic_cta_refresh_manifest_sha256,
    legacy_automatic_public_call_to_action,
    validate_automatic_cta_refresh_manifest,
)
from app.services.draft_generation import (
    GenerationContext,
    build_automatic_public_call_to_action,
)
from app.services.page_editor import append_generated_page_revision
from scripts.rehearse_automatic_cta_refresh import (
    EXPECTED_ALEMBIC_REVISION,
    RehearsalGuardError,
    require_disposable_database,
)


HASH = "a" * 64


def _context() -> GenerationContext:
    business = Business(
        id=11,
        company_name="Synthetic Home Services",
        business_type="Synthetic local service",
        phone="(555) 010-2200",
        email="hello@synthetic.example",
        state="FL",
        license_number="SYN-LICENSE-42",
        certified_operator="Synthetic Operator",
    )
    service = Service(
        id=12,
        business_id=11,
        service_name="Synthetic Property Care",
        service_slug="synthetic-property-care",
    )
    county = County(id=13, county_name="Synthetic County", state="FL")
    city = City(
        id=14,
        county_id=13,
        city_name="Example City",
        city_slug="example-city",
        state="FL",
    )
    page = GeneratedPage(
        id=15,
        business_id=11,
        website_id=16,
        service_id=12,
        city_id=14,
        county_id=13,
        page_type="city_service",
        page_title="Synthetic Property Care in Example City",
        page_slug="synthetic-property-care-example-city",
    )
    website_context = WebsiteContextRead(
        business=WebsiteContextBusiness(
            id=11,
            company_name=business.company_name,
            business_type=business.business_type,
            phone=business.phone,
            email=business.email,
            state="FL",
            license_number=business.license_number,
            certified_operator=business.certified_operator,
        ),
        brand=WebsiteContextBrand(public_name="Synthetic Home Services"),
        website=WebsiteContextSite(
            id=16,
            website_name="Synthetic Website",
            domain="synthetic.example",
            public_url="https://synthetic.example",
            locale="en-US",
            primary_language="en",
            configuration={"license_label": "Synthetic License"},
            status="active",
        ),
        identity=WebsiteContextIdentity(
            display_name="Synthetic Home Services",
            status="active",
        ),
        services=[
            WebsiteContextService(
                id=12,
                service_name=service.service_name,
                service_slug=service.service_slug,
                status="active",
            )
        ],
        geography=WebsiteContextGeography(
            city_id=14,
            city_name=city.city_name,
            county_id=13,
            county_name=county.county_name,
            state_code="FL",
            state_name="Florida",
        ),
    )
    return GenerationContext(
        page=page,
        business=business,
        service=service,
        city=city,
        county=county,
        knowledge_blocks=[],
        settings={},
        customer_types=["synthetic customers"],
        website_context=website_context,
    )


def _manifest() -> dict[str, Any]:
    entry = {
        "website_id": 16,
        "site_plan_id": 17,
        "planned_page_id": 18,
        "generated_page_id": 15,
        "page_type": "city_service",
        "classification": AUTOMATIC_CLASSIFICATION,
        "page_status": "approved",
        "page_updated_at": "2026-08-25T00:00:00+00:00",
        "page_protected_sha256": HASH,
        "planned_page_sha256": HASH,
        "draft_without_cta_sha256": HASH,
        "current_draft_sha256": HASH,
        "current_content_body_sha256": HASH,
        "current_cta_sha256": HASH,
        "expected_corrected_cta_sha256": HASH,
        "expected_after_draft_sha256": HASH,
        "expected_after_content_body_sha256": HASH,
        "credential_source_fingerprint": HASH,
        "generated_page_revision_id": 19,
        "generated_page_revision_sha256": HASH,
        "composition_id": 20,
        "composition_version": 3,
        "composition_source_sha256": HASH,
        "composition_revision_id": 21,
        "composition_revision_sha256": HASH,
        "qa_result_id": 22,
        "qa_result_sha256": HASH,
    }
    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "task_identity": "synthetic-refresh-test",
        "created_at": "2026-08-25T00:00:00+00:00",
        "source_owner": SOURCE_OWNER,
        "legacy_source_commit": LEGACY_SOURCE_COMMIT,
        "website_id": 16,
        "site_plan_id": 17,
        "site_plan_version": 1,
        "current_generated_page_count": 1,
        "eligible_count": 1,
        "custom_copy_exclusion_count": 0,
        "already_corrected_count": 0,
        "classification_counts": {AUTOMATIC_CLASSIFICATION: 1},
        "inventory_sha256": _canonical_hash([entry]),
        "entries": [entry],
    }
    manifest["manifest_sha256"] = automatic_cta_refresh_manifest_sha256(manifest)
    return manifest


def _draft(cta: str) -> dict[str, Any]:
    return DraftContent(
        title="Synthetic Title",
        meta_title="Synthetic Meta Title",
        meta_description="Synthetic meta description.",
        h1="Synthetic H1",
        intro="Synthetic intro.",
        why_it_matters="Synthetic reason.",
        signs_section="Synthetic signs.",
        process_section="Synthetic process.",
        prep_section="Synthetic preparation.",
        realtor_property_manager_section="Synthetic coordination.",
        faq_items=[{"question": "Synthetic question?", "answer": "Synthetic answer."}],
        call_to_action=cta,
        internal_notes="Synthetic internal note.",
    ).model_dump(mode="json")


def test_legacy_identity_is_exact_and_corrected_generation_retains_internal_facts() -> None:
    context = _context()

    legacy = legacy_automatic_public_call_to_action(context)
    corrected = build_automatic_public_call_to_action(context)

    assert legacy == (
        "To discuss synthetic property care in Example City, contact Synthetic Home Services "
        "at (555) 010-2200 or hello@synthetic.example. Florida license "
        "SYN-LICENSE-42; certified operator Synthetic Operator."
    )
    assert corrected == (
        "To discuss synthetic property care in Example City, contact Synthetic Home Services "
        "at (555) 010-2200 or hello@synthetic.example."
    )
    assert context.business.license_number == "SYN-LICENSE-42"
    assert context.business.certified_operator == "Synthetic Operator"
    assert "SYN-LICENSE-42" not in corrected
    assert "Synthetic Operator" not in corrected
    assert "certified operator" not in corrected.lower()


def test_structured_classifier_rejects_governed_credentials_outside_the_cta() -> None:
    context = _context()
    draft = _draft(legacy_automatic_public_call_to_action(context))
    assert not _contains_governed_credential_copy_outside_cta(draft, context)

    draft["intro"] = "Synthetic governed fact SYN-LICENSE-42 appears here."
    assert _contains_governed_credential_copy_outside_cta(draft, context)

    draft["intro"] = "Synthetic public introduction without credentials."
    draft["faq_items"][0]["answer"] = "Synthetic Operator is named publicly."
    assert _contains_governed_credential_copy_outside_cta(draft, context)

    draft["faq_items"][0]["answer"] = "Synthetic\u00a0Operator is named publicly."
    assert _contains_governed_credential_copy_outside_cta(draft, context)

    draft["faq_items"][0]["answer"] = "Synthetic   Operator is named publicly."
    assert not _contains_governed_credential_copy_outside_cta(draft, context)

    draft["faq_items"][0]["answer"] = "Synthetic answer."
    draft["faq_items"][0]["internal_notes"] = "SYN-LICENSE-42 is nested public data."
    assert _contains_governed_credential_copy_outside_cta(draft, context)

    del draft["faq_items"][0]["internal_notes"]
    draft["faq_items"][0]["call_to_action"] = "Synthetic Operator is nested public data."
    assert _contains_governed_credential_copy_outside_cta(draft, context)

    del draft["faq_items"][0]["call_to_action"]
    draft["faq_items"][0]["answer"] = "Synthetic answer."
    draft["internal_notes"] = "SYN-LICENSE-42 and Synthetic Operator remain internal."
    assert not _contains_governed_credential_copy_outside_cta(draft, context)

    draft["status"] = "SYN-LICENSE-42"
    assert not _contains_governed_credential_copy_outside_cta(draft, context)


def test_refresh_accepts_only_explicitly_allowed_exact_legacy_qa_predecessor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _context().page
    record = SimpleNamespace(id=22, result_hash=HASH)
    stale = SimpleNamespace(current=False, record=record, result=None)
    monkeypatch.setattr(refresh_service, "effective_page_qa_state", lambda *_: stale)
    monkeypatch.setattr(
        refresh_service,
        "is_exact_legacy_city_service_qa_predecessor",
        lambda *_: True,
    )

    _require_effective_qa(
        SimpleNamespace(),  # type: ignore[arg-type]
        page,
        record,  # type: ignore[arg-type]
        allow_exact_legacy_city_service_predecessor=True,
    )

    with pytest.raises(AutomaticCTARefreshError, match="not current"):
        _require_effective_qa(
            SimpleNamespace(),  # type: ignore[arg-type]
            page,
            record,  # type: ignore[arg-type]
        )

    monkeypatch.setattr(
        refresh_service,
        "is_exact_legacy_city_service_qa_predecessor",
        lambda *_: False,
    )
    with pytest.raises(AutomaticCTARefreshError, match="not current"):
        _require_effective_qa(
            SimpleNamespace(),  # type: ignore[arg-type]
            page,
            record,  # type: ignore[arg-type]
            allow_exact_legacy_city_service_predecessor=True,
        )


def test_exact_before_identity_rechecks_the_frozen_legacy_qa_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    updated_at = datetime(2026, 8, 25, 15, 20, tzinfo=UTC)
    draft = {"call_to_action": "Synthetic legacy CTA."}
    page = SimpleNamespace(
        id=15,
        draft_content=draft,
        updated_at=updated_at,
        content_body="Synthetic rendered body.",
    )
    planned = SimpleNamespace(id=18)
    composition = SimpleNamespace(
        id=20,
        composition_version=3,
        source_hash=HASH,
    )
    revision = SimpleNamespace(id=19)
    composition_revision = SimpleNamespace(id=21, revision_hash=HASH)
    qa = SimpleNamespace(id=22, result_hash=HASH)
    entry = {
        "current_draft_sha256": refresh_service.draft_content_hash(draft),
        "page_updated_at": _timestamp(updated_at),
        "current_content_body_sha256": refresh_service._text_hash(page.content_body),
        "current_cta_sha256": refresh_service._text_hash(draft["call_to_action"]),
        "generated_page_revision_id": revision.id,
        "generated_page_revision_sha256": HASH,
        "composition_version": composition.composition_version,
        "composition_source_sha256": composition.source_hash,
        "composition_revision_id": composition_revision.id,
        "composition_revision_sha256": composition_revision.revision_hash,
        "qa_result_id": qa.id,
        "qa_result_sha256": qa.result_hash,
    }
    observed: dict[str, bool] = {}
    monkeypatch.setattr(refresh_service, "_assert_common_identity", lambda *_: None)
    monkeypatch.setattr(
        refresh_service,
        "read_composition_for_generated_page",
        lambda *_: SimpleNamespace(),
    )
    monkeypatch.setattr(
        refresh_service,
        "_generated_page_revision_history_identity",
        lambda *_args, **_kwargs: (revision, HASH),
    )
    monkeypatch.setattr(
        refresh_service,
        "current_composition_revision",
        lambda *_: composition_revision,
    )
    monkeypatch.setattr(refresh_service, "_current_qa", lambda *_: qa)

    def require_qa(*_args, **kwargs) -> None:
        observed["allow_legacy"] = kwargs.get(
            "allow_exact_legacy_city_service_predecessor",
            False,
        )

    monkeypatch.setattr(refresh_service, "_require_effective_qa", require_qa)

    _assert_exact_before_identity(
        SimpleNamespace(),  # type: ignore[arg-type]
        entry,
        page,  # type: ignore[arg-type]
        planned,  # type: ignore[arg-type]
        composition,  # type: ignore[arg-type]
    )

    assert observed == {"allow_legacy": True}

    monkeypatch.setattr(
        refresh_service,
        "_generated_page_revision_history_identity",
        lambda *_args, **_kwargs: (revision, "e" * 64),
    )
    with pytest.raises(AutomaticCTARefreshError, match="before-state identity"):
        _assert_exact_before_identity(
            SimpleNamespace(),  # type: ignore[arg-type]
            entry,
            page,  # type: ignore[arg-type]
            planned,  # type: ignore[arg-type]
            composition,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("id", 20),
        ("generated_page_id", 16),
        ("created_at", datetime(2026, 8, 25, 15, 21, tzinfo=UTC)),
        ("created_by", "different-actor"),
        ("reason", "different reason"),
        ("draft_hash_before", "b" * 64),
        ("draft_hash_after", "c" * 64),
        ("draft_content_before", {"call_to_action": "different before"}),
        ("draft_content_after", {"call_to_action": "different after"}),
        ("changed_fields", ["intro"]),
    ],
)
def test_generated_page_revision_fingerprint_binds_every_persisted_field(
    field: str,
    replacement: object,
) -> None:
    revision = SimpleNamespace(
        id=19,
        generated_page_id=15,
        created_at=datetime(2026, 8, 25, 15, 20, tzinfo=UTC),
        created_by="synthetic-actor",
        reason="synthetic reason",
        draft_hash_before="d" * 64,
        draft_hash_after="e" * 64,
        draft_content_before={"call_to_action": "before"},
        draft_content_after={"call_to_action": "after"},
        changed_fields=["call_to_action"],
    )
    baseline = _canonical_hash(
        [refresh_service._generated_page_revision_payload(revision)]
    )
    setattr(revision, field, replacement)

    assert _canonical_hash(
        [refresh_service._generated_page_revision_payload(revision)]
    ) != baseline


def test_generated_page_revision_fingerprint_binds_full_ordered_history() -> None:
    first = SimpleNamespace(
        id=19,
        generated_page_id=15,
        created_at=datetime(2026, 8, 25, 15, 20, tzinfo=UTC),
        created_by="synthetic-actor",
        reason="synthetic first reason",
        draft_hash_before="d" * 64,
        draft_hash_after="e" * 64,
        draft_content_before={"call_to_action": "before first"},
        draft_content_after={"call_to_action": "after first"},
        changed_fields=["call_to_action"],
    )
    second = SimpleNamespace(
        id=20,
        generated_page_id=15,
        created_at=datetime(2026, 8, 25, 15, 21, tzinfo=UTC),
        created_by="synthetic-actor",
        reason="synthetic second reason",
        draft_hash_before="e" * 64,
        draft_hash_after="f" * 64,
        draft_content_before={"call_to_action": "after first"},
        draft_content_after={"call_to_action": "after second"},
        changed_fields=["call_to_action"],
    )
    ordered_payload = [
        refresh_service._generated_page_revision_payload(first),
        refresh_service._generated_page_revision_payload(second),
    ]
    baseline = _canonical_hash(ordered_payload)

    assert _canonical_hash(ordered_payload[:1]) != baseline
    assert _canonical_hash(list(reversed(ordered_payload))) != baseline


def test_refresh_timestamp_identity_normalizes_postgresql_naive_utc_values() -> None:
    aware = datetime(2026, 8, 25, 15, 20, 0, 123456, tzinfo=UTC)
    naive = aware.replace(tzinfo=None)

    assert _timestamp(aware) == _timestamp(naive)


def test_manifest_allowlist_and_hash_validation_fail_closed() -> None:
    manifest = _manifest()
    validate_automatic_cta_refresh_manifest(manifest)

    extra = deepcopy(manifest)
    extra["unexpected"] = True
    extra["manifest_sha256"] = automatic_cta_refresh_manifest_sha256(extra)
    with pytest.raises(AutomaticCTARefreshError, match="allowlist"):
        validate_automatic_cta_refresh_manifest(extra)

    tampered = deepcopy(manifest)
    tampered["entries"][0]["page_status"] = "published"
    with pytest.raises(AutomaticCTARefreshError, match="inventory hash|hash verification"):
        validate_automatic_cta_refresh_manifest(tampered)

    wrong_counts = deepcopy(manifest)
    wrong_counts["classification_counts"] = {}
    wrong_counts["manifest_sha256"] = automatic_cta_refresh_manifest_sha256(wrong_counts)
    with pytest.raises(AutomaticCTARefreshError, match="classification counts"):
        validate_automatic_cta_refresh_manifest(wrong_counts)


def test_manifest_rejects_inconsistent_revision_identity_even_when_rehashed() -> None:
    manifest = _manifest()
    manifest["entries"][0]["generated_page_revision_sha256"] = None
    manifest["inventory_sha256"] = _canonical_hash(manifest["entries"])
    manifest["manifest_sha256"] = automatic_cta_refresh_manifest_sha256(manifest)

    with pytest.raises(AutomaticCTARefreshError, match="revision identity"):
        validate_automatic_cta_refresh_manifest(manifest)


def test_manifest_rejects_rehashed_city_service_automatic_to_excluded_tamper() -> None:
    manifest = _manifest()
    manifest["entries"][0]["classification"] = EXCLUDED_CLASSIFICATION
    manifest["eligible_count"] = 0
    manifest["classification_counts"] = {EXCLUDED_CLASSIFICATION: 1}
    manifest["inventory_sha256"] = _canonical_hash(manifest["entries"])
    manifest["manifest_sha256"] = automatic_cta_refresh_manifest_sha256(manifest)

    with pytest.raises(AutomaticCTARefreshError, match="does not match its page type"):
        validate_automatic_cta_refresh_manifest(manifest)


@pytest.mark.parametrize("current_kind", ["corrected", "custom"])
def test_runtime_reclassification_rejects_rehashed_automatic_entry(
    monkeypatch: pytest.MonkeyPatch,
    current_kind: str,
) -> None:
    context = _context()
    page = context.page
    corrected = build_automatic_public_call_to_action(context)
    current_cta = corrected if current_kind == "corrected" else "Synthetic custom CTA."
    page.draft_content = _draft(current_cta)
    page.page_title = page.draft_content["title"]
    page.meta_title = page.draft_content["meta_title"]
    page.meta_description = page.draft_content["meta_description"]
    page.h1 = page.draft_content["h1"]
    page.content_body = "canonical-rendered-content"
    monkeypatch.setattr(
        refresh_service,
        "load_generation_context",
        lambda *_: context,
    )
    monkeypatch.setattr(
        refresh_service,
        "render_content_body",
        lambda *_: page.content_body,
    )

    with pytest.raises(AutomaticCTARefreshError, match="classification changed"):
        refresh_service._assert_current_source_classification(
            SimpleNamespace(),  # type: ignore[arg-type]
            {"classification": AUTOMATIC_CLASSIFICATION},
            page,
        )


def test_runtime_reclassification_rejects_nfkc_equivalent_public_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context()
    page = context.page
    draft = _draft(legacy_automatic_public_call_to_action(context))
    draft["intro"] = "Synthetic\u00a0Operator is named publicly."
    page.draft_content = draft
    page.page_title = draft["title"]
    page.meta_title = draft["meta_title"]
    page.meta_description = draft["meta_description"]
    page.h1 = draft["h1"]
    page.content_body = "canonical-rendered-content"
    monkeypatch.setattr(
        refresh_service,
        "load_generation_context",
        lambda *_: context,
    )
    monkeypatch.setattr(
        refresh_service,
        "render_content_body",
        lambda *_: page.content_body,
    )

    with pytest.raises(AutomaticCTARefreshError, match="classification changed"):
        refresh_service._assert_current_source_classification(
            SimpleNamespace(),  # type: ignore[arg-type]
            {"classification": AUTOMATIC_CLASSIFICATION},
            page,
        )


class _WriteCaptureSession:
    def __init__(self) -> None:
        self.added: list[Any] = []
        self.flush_count = 0

    def add(self, value: Any) -> None:
        self.added.append(value)

    def flush(self) -> None:
        self.flush_count += 1


def test_revision_append_seam_uses_canonical_shape_without_committing() -> None:
    before = _draft("Contact the synthetic company.")
    after = _draft("Call the synthetic company.")
    page = _context().page
    page.draft_content = deepcopy(before)
    session = _WriteCaptureSession()

    revision = append_generated_page_revision(
        session,  # type: ignore[arg-type]
        page,
        before=before,
        after=after,
        changed_fields=["call_to_action"],
        rendered_content="Synthetic rendered content.",
        created_by="synthetic-refresh-actor",
        reason="Synthetic refresh reason",
    )

    assert session.flush_count == 1
    assert session.added == [page, revision]
    assert page.draft_content == after
    assert page.content_body == "Synthetic rendered content."
    assert page.qa_status == "not_run"
    assert page.qa_result is None
    assert revision.generated_page_id == page.id
    assert revision.changed_fields == ["call_to_action"]
    assert revision.draft_content_before == before
    assert revision.draft_content_after == after
    after["call_to_action"] = "Mutated outside the writer."
    assert revision.draft_content_after["call_to_action"] == "Call the synthetic company."


def test_revision_append_seam_rejects_invalid_before_and_revision_shapes_without_writes() -> None:
    before = _draft("Contact the synthetic company.")
    changed = _draft("Call the synthetic company.")

    cases = [
        (
            "persisted page",
            SimpleNamespace(id=None, draft_content=deepcopy(before)),
            before,
            changed,
            ["call_to_action"],
        ),
        (
            "at least one changed field",
            _context().page,
            before,
            changed,
            [],
        ),
        (
            "before-state differs",
            _context().page,
            _draft("Stale predecessor CTA."),
            changed,
            ["call_to_action"],
        ),
        (
            "changed draft hash",
            _context().page,
            before,
            deepcopy(before),
            ["call_to_action"],
        ),
    ]

    for expected_message, page, claimed_before, after, changed_fields in cases:
        if page.id is not None:
            page.draft_content = deepcopy(before)
        session = _WriteCaptureSession()
        with pytest.raises(RuntimeError, match=expected_message):
            append_generated_page_revision(
                session,  # type: ignore[arg-type]
                page,  # type: ignore[arg-type]
                before=claimed_before,
                after=after,
                changed_fields=changed_fields,
                rendered_content="Synthetic rendered content.",
                created_by="synthetic-refresh-actor",
                reason="Synthetic invalid revision",
            )
        assert session.added == []
        assert session.flush_count == 0


class _GuardSession:
    def __init__(self, first_row: tuple[str, str, str]) -> None:
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
        self.rows = [first_row, (EXPECTED_ALEMBIC_REVISION,)]

    def get_bind(self) -> Any:
        return self.bind

    def exec(self, _statement: Any) -> Any:
        return SimpleNamespace(one=lambda: self.rows.pop(0))


def test_runner_requires_exact_disposable_database_marker_and_refuses_active_atlas() -> None:
    nonce = "b" * 64
    database = "atlas_cta_refresh_01234567_scratch"
    run_id = "synthetic-run-1"
    result = require_disposable_database(
        _GuardSession((database, run_id, nonce)),  # type: ignore[arg-type]
        expected_database=database,
        run_id=run_id,
        nonce_sha256=nonce,
    )
    assert result["database"] == database
    assert result["alembic_revision"] == EXPECTED_ALEMBIC_REVISION

    with pytest.raises(RehearsalGuardError, match="not an allowed"):
        require_disposable_database(
            _GuardSession(("atlas", run_id, nonce)),  # type: ignore[arg-type]
            expected_database="atlas",
            run_id=run_id,
            nonce_sha256=nonce,
        )

    with pytest.raises(RehearsalGuardError, match="marker"):
        require_disposable_database(
            _GuardSession((database, "different-run", nonce)),  # type: ignore[arg-type]
            expected_database=database,
            run_id=run_id,
            nonce_sha256=nonce,
        )


class _FenceSession:
    def __init__(self, dialect_name: str) -> None:
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect_name))
        self.statements: list[Any] = []

    def get_bind(self) -> Any:
        return self.bind

    def exec(self, statement: Any) -> None:
        self.statements.append(statement)


def test_refresh_fences_every_authoritative_composition_source_table() -> None:
    session = _FenceSession("postgresql")
    _lock_authoritative_source_tables(session)  # type: ignore[arg-type]

    assert len(session.statements) == 1
    sql = " ".join(str(session.statements[0]).split())
    assert sql == (
        "LOCK TABLE " + ", ".join(_AUTHORITATIVE_SOURCE_TABLES) + " IN SHARE MODE"
    )
    assert {
        "business",
        "generatedpage",
        "generatedpagerevision",
        "generatedpageqaresult",
        "internallinkintent",
        "navigationitem",
        "navigationset",
        "pageimageassignment",
        "pagecompositionrevision",
        "plannedpage",
        "plannedpagemediarequirement",
        "scopedmediaauthorization",
        "semanticcomponentdefinition",
        "siteplan",
        "theme",
        "websiteidentity",
        "websitemediaplanningrecord",
        "websitethemeselection",
    } <= set(_AUTHORITATIVE_SOURCE_TABLES)

    with pytest.raises(AutomaticCTARefreshError, match="PostgreSQL source fencing"):
        _lock_authoritative_source_tables(  # type: ignore[arg-type]
            _FenceSession("sqlite")
        )


class _GeneratedPageInventorySession:
    def __init__(self, identities: list[int]) -> None:
        self.identities = identities

    def exec(self, _statement: Any) -> Any:
        return SimpleNamespace(all=lambda: self.identities)


def test_refresh_rejects_an_extra_or_missing_global_generated_page() -> None:
    manifest = _manifest()
    _assert_global_generated_page_inventory(  # type: ignore[arg-type]
        _GeneratedPageInventorySession([15]),
        manifest,
    )

    with pytest.raises(AutomaticCTARefreshError, match="global Generated Page"):
        _assert_global_generated_page_inventory(  # type: ignore[arg-type]
            _GeneratedPageInventorySession([15, 99]),
            manifest,
        )

    with pytest.raises(AutomaticCTARefreshError, match="global Generated Page"):
        _assert_global_generated_page_inventory(  # type: ignore[arg-type]
            _GeneratedPageInventorySession([]),
            manifest,
        )


def test_refresh_test_source_contains_no_production_company_or_operator_literals() -> None:
    source = json.dumps(
        {
            "legacy": legacy_automatic_public_call_to_action(_context()),
            "corrected": build_automatic_public_call_to_action(_context()),
        }
    ).lower()
    assert "flo-zone" not in source
    assert "orlando" not in source
