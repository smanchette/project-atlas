from copy import deepcopy
from datetime import UTC, datetime
import json
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import event, inspect
from sqlmodel import Session

from app.db.session import engine
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


def _synthetic_entry(classification: str, ordinal: int) -> dict[str, Any]:
    entry = deepcopy(_manifest()["entries"][0])
    entry.update(
        {
            "planned_page_id": 100 + ordinal,
            "generated_page_id": 200 + ordinal,
            "composition_id": 300 + ordinal,
            "composition_revision_id": 400 + ordinal,
            "qa_result_id": 500 + ordinal,
            "generated_page_revision_id": 600 + ordinal,
            "classification": classification,
        }
    )
    if classification == EXCLUDED_CLASSIFICATION:
        entry["page_type"] = "service"
        for key in (
            "expected_corrected_cta_sha256",
            "expected_after_draft_sha256",
            "expected_after_content_body_sha256",
            "credential_source_fingerprint",
        ):
            entry[key] = None
    return entry


def _manifest_for_entries(entries: list[dict[str, Any]]) -> dict[str, Any]:
    manifest = _manifest()
    ordered = sorted(deepcopy(entries), key=lambda entry: entry["planned_page_id"])
    counts: dict[str, int] = {}
    for entry in ordered:
        classification = str(entry["classification"])
        counts[classification] = counts.get(classification, 0) + 1
    manifest.update(
        {
            "current_generated_page_count": len(ordered),
            "eligible_count": counts.get(AUTOMATIC_CLASSIFICATION, 0),
            "custom_copy_exclusion_count": counts.get(
                refresh_service.CUSTOM_CLASSIFICATION,
                0,
            ),
            "already_corrected_count": counts.get(
                refresh_service.ALREADY_CORRECTED_CLASSIFICATION,
                0,
            ),
            "classification_counts": dict(sorted(counts.items())),
            "inventory_sha256": _canonical_hash(ordered),
            "entries": ordered,
        }
    )
    manifest["manifest_sha256"] = automatic_cta_refresh_manifest_sha256(manifest)
    return manifest


def _install_read_only_rehearsal_seams(
    monkeypatch: pytest.MonkeyPatch,
    manifest: dict[str, Any],
    *,
    legacy_state: str = "before",
) -> tuple[dict[str, list[str]], dict[str, dict[int, Any]]]:
    observed = {
        "classifications": [],
        "corrected_identities": [],
        "other_identities": [],
    }
    locked = {
        "generated_pages": {
            entry["generated_page_id"]: SimpleNamespace(
                id=entry["generated_page_id"],
                page_type=entry["page_type"],
            )
            for entry in manifest["entries"]
        },
        "planned_pages": {
            entry["planned_page_id"]: SimpleNamespace(id=entry["planned_page_id"])
            for entry in manifest["entries"]
        },
        "compositions": {
            entry["composition_id"]: SimpleNamespace(id=entry["composition_id"])
            for entry in manifest["entries"]
        },
    }
    monkeypatch.setattr(refresh_service, "_lock_authoritative_source_tables", lambda *_: None)
    monkeypatch.setattr(refresh_service, "_assert_global_generated_page_inventory", lambda *_: None)
    monkeypatch.setattr(refresh_service, "_lock_manifest_scope", lambda *_args, **_kwargs: locked)
    monkeypatch.setattr(
        refresh_service,
        "_assert_current_source_classification",
        lambda _session, entry, _page: observed["classifications"].append(
            entry["classification"]
        ),
    )
    monkeypatch.setattr(
        refresh_service,
        "_assert_exact_corrected_identity",
        lambda _session, entry, _page, _planned, _composition: observed[
            "corrected_identities"
        ].append(entry["classification"]),
    )
    monkeypatch.setattr(
        refresh_service,
        "_assert_exact_before_identity",
        lambda _session, entry, _page, _planned, _composition: observed[
            "other_identities"
        ].append(entry["classification"]),
    )
    monkeypatch.setattr(
        refresh_service,
        "_eligible_state",
        lambda _session, entry, page, _planned, _composition: (
            legacy_state,
            {
                "entry": entry,
                "page": page,
                "before": {"call_to_action": "Synthetic legacy CTA."},
                "after": {"call_to_action": "Synthetic corrected CTA."},
                "rendered_content": "Synthetic corrected render.",
            }
            if legacy_state == "before"
            else None,
        ),
    )
    return observed, locked


def _forbid_refresh_writers(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_writer(*_args: Any, **_kwargs: Any) -> None:
        pytest.fail("A refresh writer was called on a fail-closed or no-op path.")

    monkeypatch.setattr(refresh_service, "append_generated_page_revision", fail_writer)
    monkeypatch.setattr(refresh_service, "refresh_site_plan_compositions", fail_writer)
    monkeypatch.setattr(refresh_service, "save_page_qa", fail_writer)


def _application_database_state(session: Session) -> dict[str, Any]:
    connection = session.connection()
    table_names = sorted(inspect(connection).get_table_names())
    counts = {
        table_name: int(
            connection.exec_driver_sql(
                f'SELECT COUNT(*) FROM "{table_name.replace(chr(34), chr(34) * 2)}"'
            ).scalar_one()
        )
        for table_name in table_names
    }
    internal_tables = set(
        inspect(connection).get_table_names(sqlite_include_internal=True)
    )
    sequences = (
        [
            tuple(row)
            for row in connection.exec_driver_sql(
                "SELECT name, seq FROM sqlite_sequence ORDER BY name"
            ).all()
        ]
        if "sqlite_sequence" in internal_tables
        else None
    )
    return {"counts": counts, "sequences": sequences}


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


def _corrected_runtime() -> tuple[GenerationContext, GeneratedPage, dict[str, Any]]:
    context = _context()
    page = context.page
    corrected = build_automatic_public_call_to_action(context)
    draft = _draft(corrected)
    page.draft_content = draft
    page.page_title = draft["title"]
    page.meta_title = draft["meta_title"]
    page.meta_description = draft["meta_description"]
    page.h1 = draft["h1"]
    page.content_body = "Synthetic canonical rendered content."
    page.status = "approved"
    page.updated_at = datetime(2026, 8, 28, 7, 30, tzinfo=UTC)
    entry = _synthetic_entry(
        refresh_service.ALREADY_CORRECTED_CLASSIFICATION,
        1,
    )
    entry.update(
        {
            "current_cta_sha256": refresh_service._text_hash(corrected),
            "expected_corrected_cta_sha256": refresh_service._text_hash(corrected),
            "current_draft_sha256": refresh_service.draft_content_hash(draft),
            "expected_after_draft_sha256": refresh_service.draft_content_hash(draft),
            "current_content_body_sha256": refresh_service._text_hash(
                page.content_body
            ),
            "expected_after_content_body_sha256": refresh_service._text_hash(
                page.content_body
            ),
            "credential_source_fingerprint": (
                refresh_service._credential_source_fingerprint(context)
            ),
        }
    )
    return context, page, entry


def test_complete_all_legacy_manifest_remains_dry_run_eligible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest_for_entries(
        [
            _synthetic_entry(AUTOMATIC_CLASSIFICATION, 1),
            _synthetic_entry(AUTOMATIC_CLASSIFICATION, 2),
            _synthetic_entry(EXCLUDED_CLASSIFICATION, 3),
        ]
    )
    observed, _locked = _install_read_only_rehearsal_seams(monkeypatch, manifest)
    _forbid_refresh_writers(monkeypatch)

    result = refresh_service.rehearse_automatic_cta_refresh(
        SimpleNamespace(),  # type: ignore[arg-type]
        manifest,
        dry_run=True,
    )

    assert result == {
        "status": "DRY_RUN",
        "manifest_sha256": manifest["manifest_sha256"],
        "eligible_count": 2,
        "expected_generated_page_revisions": 2,
        "expected_composition_revisions": 2,
        "expected_qa_rows": 2,
        "writes": 0,
    }
    assert observed == {
        "classifications": [
            AUTOMATIC_CLASSIFICATION,
            AUTOMATIC_CLASSIFICATION,
            EXCLUDED_CLASSIFICATION,
        ],
        "corrected_identities": [],
        "other_identities": [EXCLUDED_CLASSIFICATION],
    }


def test_complete_all_legacy_manifest_preserves_successful_apply_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest_for_entries(
        [
            _synthetic_entry(AUTOMATIC_CLASSIFICATION, 1),
            _synthetic_entry(AUTOMATIC_CLASSIFICATION, 2),
            _synthetic_entry(EXCLUDED_CLASSIFICATION, 3),
        ]
    )
    _observed, _locked = _install_read_only_rehearsal_seams(monkeypatch, manifest)
    appended: list[int] = []
    after_checks: list[int] = []

    def append_revision(
        _session: Any,
        page: Any,
        **_kwargs: Any,
    ) -> Any:
        appended.append(page.id)
        return SimpleNamespace(id=700 + page.id)

    monkeypatch.setattr(
        refresh_service,
        "append_generated_page_revision",
        append_revision,
    )
    monkeypatch.setattr(
        refresh_service,
        "refresh_site_plan_compositions",
        lambda *_args, **_kwargs: SimpleNamespace(
            blocked=False,
            created=0,
            refreshed=2,
            unchanged=1,
        ),
    )
    monkeypatch.setattr(
        refresh_service,
        "save_page_qa",
        lambda _session, page_id, **_kwargs: SimpleNamespace(
            qa_result_id=800 + page_id
        ),
    )
    monkeypatch.setattr(
        refresh_service,
        "_assert_exact_after_identity",
        lambda _session, _entry, page, _revision, _qa_id: after_checks.append(
            page.id
        ),
    )

    class ApplySession:
        flush_count = 0

        def flush(self) -> None:
            self.flush_count += 1

    session = ApplySession()
    result = refresh_service.rehearse_automatic_cta_refresh(
        session,  # type: ignore[arg-type]
        manifest,
    )

    assert result == {
        "status": "APPLIED_PENDING_CALLER_COMMIT",
        "manifest_sha256": manifest["manifest_sha256"],
        "eligible_count": 2,
        "generated_page_revisions_created": 2,
        "composition_revisions_created": 2,
        "qa_rows_created": 2,
        "composition_created": 0,
        "composition_refreshed": 2,
        "composition_unchanged": 1,
        "writes": 6,
    }
    assert appended == [201, 202]
    assert after_checks == [201, 202]
    assert session.flush_count == 1


@pytest.mark.parametrize("governed_count", [1, 3])
def test_fresh_all_corrected_manifest_uses_generic_counts_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    governed_count: int,
) -> None:
    corrected = refresh_service.ALREADY_CORRECTED_CLASSIFICATION
    manifest = _manifest_for_entries(
        [
            *[
                _synthetic_entry(corrected, ordinal)
                for ordinal in range(1, governed_count + 1)
            ],
            _synthetic_entry(EXCLUDED_CLASSIFICATION, governed_count + 1),
        ]
    )
    observed, _locked = _install_read_only_rehearsal_seams(monkeypatch, manifest)
    _forbid_refresh_writers(monkeypatch)

    result = refresh_service.rehearse_automatic_cta_refresh(
        SimpleNamespace(),  # type: ignore[arg-type]
        manifest,
    )

    assert result == {
        "status": "UNCHANGED",
        "manifest_sha256": manifest["manifest_sha256"],
        "governed_target_count": governed_count,
        "corrected_count": governed_count,
        "legacy_count": 0,
        "custom_count": 0,
        "mixed_count": 0,
        "eligible_count": 0,
        "page_writes": 0,
        "revision_writes": 0,
        "composition_writes": 0,
        "qa_writes": 0,
        "generated_page_revisions_created": 0,
        "composition_revisions_created": 0,
        "qa_rows_created": 0,
        "writes": 0,
    }
    assert observed == {
        "classifications": [
            *[corrected for _ in range(governed_count)],
            EXCLUDED_CLASSIFICATION,
        ],
        "corrected_identities": [corrected for _ in range(governed_count)],
        "other_identities": [EXCLUDED_CLASSIFICATION],
    }


def test_all_corrected_noop_preserves_all_table_counts_and_supported_sequences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corrected = refresh_service.ALREADY_CORRECTED_CLASSIFICATION
    manifest = _manifest_for_entries(
        [
            _synthetic_entry(corrected, 1),
            _synthetic_entry(corrected, 2),
        ]
    )
    _observed, locked = _install_read_only_rehearsal_seams(monkeypatch, manifest)
    _forbid_refresh_writers(monkeypatch)
    locked_before = deepcopy(locked)
    observed_dml: list[str] = []

    def capture_dml(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        operation = statement.lstrip().partition(" ")[0].upper()
        if operation in {"INSERT", "UPDATE", "DELETE"}:
            observed_dml.append(statement)

    event.listen(engine, "before_cursor_execute", capture_dml)
    try:
        with Session(engine) as session:
            before = _application_database_state(session)
            result = refresh_service.rehearse_automatic_cta_refresh(
                session,
                manifest,
            )
            pending_orm_state = {
                "new": list(session.new),
                "dirty": list(session.dirty),
                "deleted": list(session.deleted),
            }
            after = _application_database_state(session)
            session.rollback()
    finally:
        event.remove(engine, "before_cursor_execute", capture_dml)

    assert result["status"] == "UNCHANGED"
    assert result["writes"] == 0
    assert before["counts"] == after["counts"]
    assert before["sequences"] == after["sequences"]
    assert pending_orm_state == {"new": [], "dirty": [], "deleted": []}
    assert locked == locked_before
    assert observed_dml == []


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        (
            [
                _synthetic_entry(AUTOMATIC_CLASSIFICATION, 1),
                _synthetic_entry(refresh_service.ALREADY_CORRECTED_CLASSIFICATION, 2),
            ],
            "Mixed legacy/corrected",
        ),
        (
            [
                _synthetic_entry(refresh_service.ALREADY_CORRECTED_CLASSIFICATION, 1),
                _synthetic_entry(refresh_service.CUSTOM_CLASSIFICATION, 2),
            ],
            "Custom or uncertain",
        ),
        (
            [_synthetic_entry(EXCLUDED_CLASSIFICATION, 1)],
            "no governed City-Service",
        ),
    ],
)
def test_mixed_custom_and_empty_governed_states_fail_before_writer_or_lock_seams(
    monkeypatch: pytest.MonkeyPatch,
    entries: list[dict[str, Any]],
    message: str,
) -> None:
    manifest = _manifest_for_entries(entries)
    _forbid_refresh_writers(monkeypatch)
    monkeypatch.setattr(
        refresh_service,
        "_lock_authoritative_source_tables",
        lambda *_: pytest.fail("A fail-closed state reached the database lock seam."),
    )

    with pytest.raises(AutomaticCTARefreshError, match=message):
        refresh_service.rehearse_automatic_cta_refresh(
            SimpleNamespace(),  # type: ignore[arg-type]
            manifest,
        )


def test_old_preapply_manifest_rejects_corrected_runtime_state_before_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest_for_entries(
        [_synthetic_entry(AUTOMATIC_CLASSIFICATION, 1)]
    )
    context, page, _corrected_entry = _corrected_runtime()
    entry = manifest["entries"][0]
    locked = {
        "generated_pages": {entry["generated_page_id"]: page},
        "planned_pages": {
            entry["planned_page_id"]: SimpleNamespace(id=entry["planned_page_id"])
        },
        "compositions": {
            entry["composition_id"]: SimpleNamespace(id=entry["composition_id"])
        },
    }
    monkeypatch.setattr(refresh_service, "_lock_authoritative_source_tables", lambda *_: None)
    monkeypatch.setattr(refresh_service, "_assert_global_generated_page_inventory", lambda *_: None)
    monkeypatch.setattr(refresh_service, "_lock_manifest_scope", lambda *_args, **_kwargs: locked)
    monkeypatch.setattr(refresh_service, "load_generation_context", lambda *_: context)
    monkeypatch.setattr(
        refresh_service,
        "render_content_body",
        lambda *_: page.content_body,
    )
    _forbid_refresh_writers(monkeypatch)

    with pytest.raises(AutomaticCTARefreshError, match="classification changed"):
        refresh_service.rehearse_automatic_cta_refresh(
            SimpleNamespace(),  # type: ignore[arg-type]
            manifest,
        )


def test_refingerprinted_legacy_credential_source_tamper_rejects_before_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context()
    page = context.page
    draft = _draft(legacy_automatic_public_call_to_action(context))
    page.draft_content = draft
    page.page_title = draft["title"]
    page.meta_title = draft["meta_title"]
    page.meta_description = draft["meta_description"]
    page.h1 = draft["h1"]
    page.content_body = "Synthetic canonical legacy render."
    entry = _synthetic_entry(AUTOMATIC_CLASSIFICATION, 1)
    entry["credential_source_fingerprint"] = "b" * 64
    manifest = _manifest_for_entries([entry])
    validate_automatic_cta_refresh_manifest(manifest)
    locked = {
        "generated_pages": {entry["generated_page_id"]: page},
        "planned_pages": {
            entry["planned_page_id"]: SimpleNamespace(id=entry["planned_page_id"])
        },
        "compositions": {
            entry["composition_id"]: SimpleNamespace(id=entry["composition_id"])
        },
    }
    monkeypatch.setattr(refresh_service, "_lock_authoritative_source_tables", lambda *_: None)
    monkeypatch.setattr(refresh_service, "_assert_global_generated_page_inventory", lambda *_: None)
    monkeypatch.setattr(refresh_service, "_lock_manifest_scope", lambda *_args, **_kwargs: locked)
    monkeypatch.setattr(refresh_service, "load_generation_context", lambda *_: context)
    monkeypatch.setattr(
        refresh_service,
        "render_content_body",
        lambda *_: page.content_body,
    )
    _forbid_refresh_writers(monkeypatch)

    with pytest.raises(AutomaticCTARefreshError, match="credential source identity"):
        refresh_service.rehearse_automatic_cta_refresh(
            SimpleNamespace(),  # type: ignore[arg-type]
            manifest,
        )


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


@pytest.mark.parametrize("governed_count", [1, 3])
def test_manifest_builder_binds_generic_fresh_corrected_current_identities(
    monkeypatch: pytest.MonkeyPatch,
    governed_count: int,
) -> None:
    plan = SimpleNamespace(id=17, website_id=16, version=4)
    contexts: dict[int, GenerationContext] = {}
    pages: dict[int, GeneratedPage] = {}
    planned_pages: list[Any] = []
    planned_by_page: dict[int, Any] = {}
    compositions_by_page: dict[int, Any] = {}
    composition_revisions: dict[int, Any] = {}
    revisions: dict[int, Any] = {}
    qa_results: dict[int, Any] = {}
    rendered_by_title: dict[str, str] = {}
    for ordinal in range(1, governed_count + 1):
        context = _context()
        page = context.page
        page.id = 200 + ordinal
        corrected = build_automatic_public_call_to_action(context)
        draft = _draft(corrected)
        draft["title"] = f"Synthetic Title {ordinal}"
        page.draft_content = draft
        page.page_title = draft["title"]
        page.meta_title = draft["meta_title"]
        page.meta_description = draft["meta_description"]
        page.h1 = draft["h1"]
        page.content_body = f"Synthetic canonical rendered content {ordinal}."
        page.status = "approved"
        page.updated_at = datetime(2026, 8, 28, 8, ordinal, tzinfo=UTC)
        planned = SimpleNamespace(
            id=100 + ordinal,
            website_id=plan.website_id,
            site_plan_id=plan.id,
            generated_page_id=page.id,
        )
        composition = SimpleNamespace(
            id=300 + ordinal,
            composition_version=ordinal + 2,
            source_hash=f"{ordinal:x}" * 64,
        )
        contexts[page.id] = context
        pages[page.id] = page
        planned_pages.append(planned)
        planned_by_page[page.id] = planned
        compositions_by_page[page.id] = composition
        composition_revisions[composition.id] = SimpleNamespace(
            id=400 + ordinal,
            revision_hash=f"{ordinal + 3:x}" * 64,
        )
        revisions[page.id] = SimpleNamespace(id=500 + ordinal)
        qa_results[page.id] = SimpleNamespace(
            id=600 + ordinal,
            result_hash=f"{ordinal + 6:x}" * 64,
        )
        rendered_by_title[draft["title"]] = page.content_body

    class ManifestBuilderSession:
        exec_count = 0

        def get(self, model: Any, identity: int) -> Any:
            if model is refresh_service.SitePlan:
                assert identity == plan.id
                return plan
            assert model is GeneratedPage and identity in pages
            return pages[identity]

        def exec(self, _statement: Any) -> Any:
            self.exec_count += 1
            if self.exec_count == 1:
                return SimpleNamespace(all=lambda: planned_pages)
            planned = planned_pages[self.exec_count - 2]
            composition = compositions_by_page[planned.generated_page_id]
            return SimpleNamespace(one_or_none=lambda: composition)

    monkeypatch.setattr(
        refresh_service,
        "current_composition_revision",
        lambda _session, composition: composition_revisions[composition.id],
    )
    monkeypatch.setattr(
        refresh_service,
        "_current_qa",
        lambda _session, page_id: qa_results[page_id],
    )
    monkeypatch.setattr(
        refresh_service,
        "_generated_page_revision_history_identity",
        lambda _session, page_id, **_kwargs: (revisions[page_id], "e" * 64),
    )
    monkeypatch.setattr(
        refresh_service,
        "read_composition_for_generated_page",
        lambda _session, page_id: SimpleNamespace(
            effective_components=[
                SimpleNamespace(
                    instance_key="final_cta",
                    resolved_data={
                        "body": pages[page_id].draft_content["call_to_action"]
                    },
                )
            ]
        ),
    )
    monkeypatch.setattr(
        refresh_service,
        "load_generation_context",
        lambda _session, page_id: contexts[page_id],
    )
    monkeypatch.setattr(
        refresh_service,
        "render_content_body",
        lambda draft, _website_context: rendered_by_title[draft.title],
    )
    qa_legacy_options: list[bool] = []

    def require_current_qa(*_args: Any, **kwargs: Any) -> None:
        qa_legacy_options.append(
            kwargs.get("allow_exact_legacy_city_service_predecessor", False)
        )

    monkeypatch.setattr(refresh_service, "_require_effective_qa", require_current_qa)
    monkeypatch.setattr(refresh_service, "_protected_planned_page_hash", lambda *_: HASH)

    manifest = refresh_service.build_automatic_cta_refresh_manifest(
        ManifestBuilderSession(),  # type: ignore[arg-type]
        plan.id,
        task_identity="synthetic-corrected-current-state",
        created_at=datetime(2026, 8, 28, 8, 0, tzinfo=UTC),
    )
    entry = manifest["entries"][0]

    assert manifest["website_id"] == plan.website_id
    assert manifest["site_plan_id"] == plan.id
    assert manifest["site_plan_version"] == plan.version
    assert manifest["source_owner"] == SOURCE_OWNER
    assert manifest["legacy_source_commit"] == LEGACY_SOURCE_COMMIT
    assert manifest["current_generated_page_count"] == governed_count
    assert manifest["eligible_count"] == 0
    assert manifest["already_corrected_count"] == governed_count
    assert manifest["classification_counts"] == {
        refresh_service.ALREADY_CORRECTED_CLASSIFICATION: governed_count
    }
    for entry in manifest["entries"]:
        page = pages[entry["generated_page_id"]]
        context = contexts[page.id]
        composition = compositions_by_page[page.id]
        composition_revision = composition_revisions[composition.id]
        revision = revisions[page.id]
        qa = qa_results[page.id]
        assert entry["classification"] == refresh_service.ALREADY_CORRECTED_CLASSIFICATION
        assert entry["website_id"] == plan.website_id
        assert entry["site_plan_id"] == plan.id
        assert entry["planned_page_id"] == planned_by_page[page.id].id
        assert entry["generated_page_id"] == page.id
        assert entry["page_protected_sha256"] == refresh_service._protected_page_hash(page)
        assert entry["planned_page_sha256"] == HASH
        assert entry["current_cta_sha256"] == entry["expected_corrected_cta_sha256"]
        assert entry["current_draft_sha256"] == entry["expected_after_draft_sha256"]
        assert (
            entry["current_content_body_sha256"]
            == entry["expected_after_content_body_sha256"]
        )
        assert entry["credential_source_fingerprint"] == (
            refresh_service._credential_source_fingerprint(context)
        )
        assert entry["generated_page_revision_id"] == revision.id
        assert entry["generated_page_revision_sha256"] == "e" * 64
        assert entry["composition_id"] == composition.id
        assert entry["composition_version"] == composition.composition_version
        assert entry["composition_source_sha256"] == composition.source_hash
        assert entry["composition_revision_id"] == composition_revision.id
        assert entry["composition_revision_sha256"] == composition_revision.revision_hash
        assert entry["qa_result_id"] == qa.id
        assert entry["qa_result_sha256"] == qa.result_hash
    assert qa_legacy_options == [False] * governed_count


@pytest.mark.parametrize(
    "field",
    [
        "expected_corrected_cta_sha256",
        "expected_after_draft_sha256",
        "expected_after_content_body_sha256",
        "credential_source_fingerprint",
    ],
)
def test_refingerprinted_corrected_source_tampering_rejects_at_runtime(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    context, page, entry = _corrected_runtime()
    entry[field] = "b" * 64
    manifest = _manifest_for_entries([entry])
    validate_automatic_cta_refresh_manifest(manifest)
    monkeypatch.setattr(refresh_service, "load_generation_context", lambda *_: context)
    monkeypatch.setattr(
        refresh_service,
        "render_content_body",
        lambda *_: page.content_body,
    )

    with pytest.raises(AutomaticCTARefreshError, match="source identity changed"):
        refresh_service._assert_current_source_classification(
            SimpleNamespace(),  # type: ignore[arg-type]
            manifest["entries"][0],
            page,
        )


def test_incorrect_corrected_cta_reclassifies_as_custom_and_rejects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, page, entry = _corrected_runtime()
    page.draft_content["call_to_action"] = "Synthetic divergent CTA."
    monkeypatch.setattr(refresh_service, "load_generation_context", lambda *_: context)
    monkeypatch.setattr(
        refresh_service,
        "render_content_body",
        lambda *_: page.content_body,
    )

    with pytest.raises(AutomaticCTARefreshError, match="classification changed"):
        refresh_service._assert_current_source_classification(
            SimpleNamespace(),  # type: ignore[arg-type]
            entry,
            page,
        )


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
        "classification": AUTOMATIC_CLASSIFICATION,
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

    entry["classification"] = refresh_service.ALREADY_CORRECTED_CLASSIFICATION
    _assert_exact_before_identity(
        SimpleNamespace(),  # type: ignore[arg-type]
        entry,
        page,  # type: ignore[arg-type]
        planned,  # type: ignore[arg-type]
        composition,  # type: ignore[arg-type]
    )
    assert observed == {"allow_legacy": False}
    entry["classification"] = AUTOMATIC_CLASSIFICATION

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


@pytest.mark.parametrize("stale_identity", ["revision", "composition", "qa", "draft"])
def test_corrected_noop_rejects_stale_bound_identity_or_unrelated_draft_drift(
    monkeypatch: pytest.MonkeyPatch,
    stale_identity: str,
) -> None:
    updated_at = datetime(2026, 8, 28, 7, 45, tzinfo=UTC)
    draft = {
        "intro": "Synthetic unchanged introduction.",
        "call_to_action": "Synthetic corrected CTA.",
    }
    current_draft_sha256 = refresh_service.draft_content_hash(draft)
    current_content_sha256 = refresh_service._text_hash("Synthetic rendered body.")
    current_cta_sha256 = refresh_service._text_hash(draft["call_to_action"])
    page = SimpleNamespace(
        id=15,
        draft_content=deepcopy(draft),
        updated_at=updated_at,
        content_body="Synthetic rendered body.",
    )
    planned = SimpleNamespace(id=18)
    composition = SimpleNamespace(
        id=20,
        composition_version=3,
        source_hash="b" * 64,
    )
    revision = SimpleNamespace(id=19)
    composition_revision = SimpleNamespace(id=21, revision_hash="c" * 64)
    qa = SimpleNamespace(id=22, result_hash="d" * 64)
    entry = {
        "classification": refresh_service.ALREADY_CORRECTED_CLASSIFICATION,
        "current_draft_sha256": current_draft_sha256,
        "expected_after_draft_sha256": current_draft_sha256,
        "page_updated_at": _timestamp(updated_at),
        "current_content_body_sha256": current_content_sha256,
        "expected_after_content_body_sha256": current_content_sha256,
        "current_cta_sha256": current_cta_sha256,
        "expected_corrected_cta_sha256": current_cta_sha256,
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

    def require_qa(*_args: Any, **kwargs: Any) -> None:
        observed["allow_legacy"] = kwargs.get(
            "allow_exact_legacy_city_service_predecessor",
            False,
        )

    monkeypatch.setattr(refresh_service, "_require_effective_qa", require_qa)

    if stale_identity == "revision":
        monkeypatch.setattr(
            refresh_service,
            "_generated_page_revision_history_identity",
            lambda *_args, **_kwargs: (revision, "e" * 64),
        )
    elif stale_identity == "composition":
        composition.composition_version += 1
    elif stale_identity == "qa":
        qa.id += 1
    else:
        page.draft_content["intro"] = "Synthetic unrelated drift."

    with pytest.raises(AutomaticCTARefreshError, match="before-state identity"):
        refresh_service._assert_exact_corrected_identity(
            SimpleNamespace(),  # type: ignore[arg-type]
            entry,
            page,  # type: ignore[arg-type]
            planned,  # type: ignore[arg-type]
            composition,  # type: ignore[arg-type]
        )

    assert observed == {"allow_legacy": False}


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


@pytest.mark.parametrize(
    ("field", "replacement"),
    [("website_id", 99), ("site_plan_id", 99)],
)
def test_manifest_rejects_refingerprinted_entry_hierarchy_tamper(
    field: str,
    replacement: int,
) -> None:
    manifest = _manifest()
    manifest["entries"][0][field] = replacement
    manifest["inventory_sha256"] = _canonical_hash(manifest["entries"])
    manifest["manifest_sha256"] = automatic_cta_refresh_manifest_sha256(manifest)

    with pytest.raises(AutomaticCTARefreshError, match="entry hierarchy"):
        validate_automatic_cta_refresh_manifest(manifest)


@pytest.mark.parametrize(
    "field",
    [
        "website_id",
        "site_plan_id",
        "site_plan_version",
        "current_generated_page_count",
        "eligible_count",
        "custom_copy_exclusion_count",
        "already_corrected_count",
        "classification_counts",
    ],
)
def test_manifest_rejects_refingerprinted_boolean_integer_tamper(field: str) -> None:
    manifest = _manifest()
    if field == "classification_counts":
        manifest[field][AUTOMATIC_CLASSIFICATION] = True
    elif field in {"custom_copy_exclusion_count", "already_corrected_count"}:
        manifest[field] = False
    else:
        manifest[field] = True
    manifest["manifest_sha256"] = automatic_cta_refresh_manifest_sha256(manifest)

    with pytest.raises(AutomaticCTARefreshError, match="integer|count values"):
        validate_automatic_cta_refresh_manifest(manifest)


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
