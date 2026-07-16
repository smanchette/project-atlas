from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
from io import BytesIO
import json
from pathlib import Path
import shutil
from zipfile import ZipFile

import pytest
from PIL import Image
from conftest import TEST_MEDIA_PATH as test_media_path

from app.db.city_data import TARGET_COUNTIES
from app.db import backup as backup_module
from app.db.backup import BACKUP_MODELS, BackupValidationError, export_backup, restore_backup
from app.db.knowledge_block_data import KNOWLEDGE_BLOCKS
from app.db.seed import seed_database
from app.db.session import engine
from app.main import app
from app.models import (
    ApprovalAudit,
    Business,
    City,
    County,
    GeneratedPage,
    GeneratedPageRevision,
    ImageMetadata,
    KnowledgeBlock,
    PageImageAssignment,
    Service,
    Setting,
    WordPressDraftAudit,
    WordPressPublishAudit,
    WordPressQualityReview,
)
from app.services.draft_generation import (
    DeterministicMockProvider,
    DraftGenerationError,
    UnsafeContentError,
    assemble_generation_prompt,
    generate_batch,
    generate_page_draft,
    get_draft_provider,
    load_generation_context,
    preview_batch,
    validate_safe_content,
)
from app.services.approval_audit import draft_content_hash
from app.services.approval_queue import build_approval_queue
from app.services.page_queue import create_city_service_page_queue
from app.services.page_export import build_page_export_package, generate_suggested_slug, slugify
from app.services import media_backup
from app.services import program_backup
from app.services import wordpress_sandbox
from app.services import wordpress_drafts
from app.services import wordpress_draft_review
from app.services import wordpress_draft_queue
from app.services import wordpress_draft_update
from app.services import wordpress_publish
from app.schemas.qa import QABatchRequest
from app.services.page_qa import evaluate_page_qa, preview_qa_batch, run_qa_batch, save_page_qa
from fastapi.testclient import TestClient
from sqlmodel import Session, select


FLO_ZONE_COMPANY_NAME = "Flo-Zone Pest And Termite Solutions Inc"


def test_health_check() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_seeded_business_is_available() -> None:
    with TestClient(app) as client:
        response = client.get("/api/businesses")
    assert response.status_code == 200
    businesses = response.json()
    assert any(item["company_name"] == FLO_ZONE_COMPANY_NAME for item in businesses)


def test_target_counties_exist() -> None:
    with TestClient(app):
        with Session(engine) as session:
            county_names = {county.county_name for county in session.exec(select(County)).all()}

    assert set(TARGET_COUNTIES).issubset(county_names)


def test_cities_are_seeded_and_orlando_is_primary() -> None:
    with TestClient(app):
        with Session(engine) as session:
            cities = session.exec(select(City)).all()
            orlando = session.exec(select(City).where(City.city_slug == "orlando")).one()

    assert len(cities) == 55
    assert orlando.priority == "Primary"
    assert orlando.is_primary_market is True


def test_city_slugs_are_unique() -> None:
    with TestClient(app):
        with Session(engine) as session:
            slugs = [city.city_slug for city in session.exec(select(City)).all()]

    duplicates = [slug for slug, count in Counter(slugs).items() if count > 1]
    assert duplicates == []


def test_page_queue_creates_one_draft_page_per_city_without_duplicates() -> None:
    with TestClient(app):
        with Session(engine) as session:
            first_created = create_city_service_page_queue(
                session,
                business_company_name=FLO_ZONE_COMPANY_NAME,
                service_slug="drywood-termite-tenting",
            )
            second_created = create_city_service_page_queue(
                session,
                business_company_name=FLO_ZONE_COMPANY_NAME,
                service_slug="drywood-termite-tenting",
            )

            business = session.exec(select(Business).where(Business.company_name == FLO_ZONE_COMPANY_NAME)).one()
            service = session.exec(
                select(Service).where(Service.business_id == business.id, Service.service_slug == "drywood-termite-tenting")
            ).one()
            city_count = len(session.exec(select(City)).all())
            pages = session.exec(
                select(GeneratedPage).where(
                    GeneratedPage.business_id == business.id,
                    GeneratedPage.service_id == service.id,
                    GeneratedPage.page_type == "city_service",
                )
            ).all()

    assert first_created == 0
    assert second_created == 0
    assert len(pages) == city_count
    assert all(page.status == "draft" for page in pages)
    assert len({page.city_id for page in pages}) == city_count
    assert any(page.page_slug == "drywood-termite-tenting-orlando-fl" for page in pages)


def test_knowledge_blocks_seed_with_unique_slugs_and_required_questions() -> None:
    required_questions = {block["question"] for block in KNOWLEDGE_BLOCKS}

    with TestClient(app):
        with Session(engine) as session:
            blocks = session.exec(select(KnowledgeBlock)).all()

    assert len(blocks) == 18
    assert {block.question for block in blocks} == required_questions
    assert len({block.slug for block in blocks}) == len(blocks)


def test_knowledge_blocks_belong_to_flo_zone_drywood_service() -> None:
    with TestClient(app):
        with Session(engine) as session:
            business = session.exec(select(Business).where(Business.company_name == FLO_ZONE_COMPANY_NAME)).one()
            service = session.exec(
                select(Service).where(Service.business_id == business.id, Service.service_slug == "drywood-termite-tenting")
            ).one()
            blocks = session.exec(select(KnowledgeBlock)).all()

    assert all(block.business_id == business.id for block in blocks)
    assert all(block.service_id == service.id for block in blocks)


def test_required_document_backed_knowledge_blocks_exist() -> None:
    required_slugs = {
        "why-boom-lift-is-needed-for-tall-structures",
        "about-vikane-fumigant-gas",
        "flo-zone-fumigation-preparation-checklist",
        "reentry-and-clearance-explanation",
    }

    with TestClient(app):
        with Session(engine) as session:
            slugs = {block.slug for block in session.exec(select(KnowledgeBlock)).all()}

    assert required_slugs.issubset(slugs)


def test_public_knowledge_blocks_do_not_contain_unsafe_absolute_wording() -> None:
    unsafe_phrases = ("100% guaranteed solution", "guaranteed 100%")

    with TestClient(app):
        with Session(engine) as session:
            blocks = session.exec(select(KnowledgeBlock)).all()

    for block in blocks:
        public_copy = " ".join(
            [block.title, block.question, block.short_answer, block.long_answer, block.source_notes or ""]
        ).lower()
        assert all(phrase not in public_copy for phrase in unsafe_phrases)


def test_repeated_seed_does_not_duplicate_knowledge_blocks() -> None:
    with TestClient(app):
        with Session(engine) as session:
            seed_database(session)
            first_count = len(session.exec(select(KnowledgeBlock)).all())
            seed_database(session)
            second_count = len(session.exec(select(KnowledgeBlock)).all())

    assert first_count == 18
    assert second_count == 18


def test_backup_export_contains_metadata_counts_and_all_data_groups(tmp_path: Path) -> None:
    with TestClient(app):
        with Session(engine) as session:
            before_counts = _database_counts(session)
            result = export_backup(session, backup_dir=tmp_path)
            after_counts = _database_counts(session)

    backup_path = Path(result["path"])
    payload = json.loads(backup_path.read_text(encoding="utf-8"))

    assert backup_path.is_file()
    assert payload["metadata"]["app"] == "Project Atlas"
    assert payload["metadata"]["version"] == "0.34"
    assert isinstance(payload["metadata"]["created_at"], str)
    assert payload["metadata"]["table_counts"] == before_counts
    assert set(payload["data"]) == set(BACKUP_MODELS)
    assert len(payload["data"]["knowledge_blocks"]) == 18
    assert len(payload["data"]["cities"]) == 55
    assert len(payload["data"]["generated_pages"]) == 55
    assert payload["data"]["image_metadata"]
    assert payload["data"]["page_image_assignments"]
    assert after_counts == before_counts


def test_backup_restore_is_idempotent_and_does_not_duplicate_records(tmp_path: Path) -> None:
    with TestClient(app):
        with Session(engine) as session:
            export_result = export_backup(session, backup_dir=tmp_path)
            before_counts = _database_counts(session)
            first_restore = restore_backup(session, export_result["path"])
            first_counts = _database_counts(session)
            second_restore = restore_backup(session, export_result["path"])
            second_counts = _database_counts(session)

    assert first_restore["status"] == "restored"
    assert second_restore["status"] == "restored"
    assert first_counts == before_counts
    assert second_counts == before_counts


def test_data_backup_download_is_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_name = "atlas-backup-2026-07-03-120000.json"
    backup_path = tmp_path / file_name
    content = b'{"metadata":{"app":"Project Atlas"},"data":{}}\n'
    backup_path.write_bytes(content)
    before = _file_tree_snapshot(tmp_path)
    monkeypatch.setattr(backup_module, "BACKUP_DIR", tmp_path)

    with TestClient(app) as client:
        response = client.get(f"/api/backups/data/{file_name}")

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"].startswith("application/json")
    assert file_name in response.headers["content-disposition"]
    assert _file_tree_snapshot(tmp_path) == before


def test_invalid_backup_fails_without_modifying_database(tmp_path: Path) -> None:
    invalid_backup = tmp_path / "atlas-backup-invalid.json"
    invalid_backup.write_text('{"metadata": {}, "data": {}}', encoding="utf-8")

    with TestClient(app):
        with Session(engine) as session:
            before_counts = _database_counts(session)
            with pytest.raises(BackupValidationError):
                restore_backup(session, invalid_backup)
            after_counts = _database_counts(session)

    assert after_counts == before_counts


def test_media_backup_endpoint_contains_only_fixed_media_folders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_media = tmp_path / "backend" / "media"
    frontend_media = tmp_path / "frontend" / "public" / "media"
    backups = tmp_path / "backend" / "backups"
    unrelated = tmp_path / "frontend" / "node_modules"
    (backend_media / "originals").mkdir(parents=True)
    (backend_media / "thumbnails").mkdir()
    frontend_media.mkdir(parents=True)
    backups.mkdir()
    unrelated.mkdir(parents=True)
    (backend_media / "originals" / "photo.jpg").write_bytes(b"original media")
    (backend_media / "thumbnails" / ".gitkeep").write_bytes(b"\n")
    (frontend_media / "preview.png").write_bytes(b"preview media")
    (backups / "atlas-backup-protected.json").write_text("protected", encoding="utf-8")
    (unrelated / "ignored.js").write_text("ignored", encoding="utf-8")

    monkeypatch.setattr(media_backup, "BACKEND_MEDIA_DIR", backend_media)
    monkeypatch.setattr(media_backup, "FRONTEND_MEDIA_DIR", frontend_media)
    before_media = _file_tree_snapshot(backend_media) | _file_tree_snapshot(frontend_media)
    before_backups = _file_tree_snapshot(backups)

    with TestClient(app) as client:
        response = client.post("/api/backups/media")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "atlas-media-backup-" in response.headers["content-disposition"]
    with ZipFile(BytesIO(response.content)) as archive:
        names = set(archive.namelist())

    assert "backend/media/" in names
    assert "backend/media/originals/photo.jpg" in names
    assert "backend/media/thumbnails/.gitkeep" in names
    assert "frontend/public/media/" in names
    assert "frontend/public/media/preview.png" in names
    assert not any("backups" in name for name in names)
    assert not any("node_modules" in name for name in names)
    assert not any("__pycache__" in name or name.endswith(".db") for name in names)
    assert _file_tree_snapshot(backend_media) | _file_tree_snapshot(frontend_media) == before_media
    assert _file_tree_snapshot(backups) == before_backups


def test_media_backup_endpoint_fails_when_a_required_folder_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_media = tmp_path / "backend" / "media"
    backend_media.mkdir(parents=True)
    missing_frontend_media = tmp_path / "frontend" / "public" / "media"
    monkeypatch.setattr(media_backup, "BACKEND_MEDIA_DIR", backend_media)
    monkeypatch.setattr(media_backup, "FRONTEND_MEDIA_DIR", missing_frontend_media)

    with TestClient(app) as client:
        response = client.post("/api/backups/media")

    assert response.status_code == 500
    assert "requires both media folders" in response.json()["detail"]
    assert str(missing_frontend_media) in response.json()["detail"]


def test_program_backup_endpoint_contains_rebuild_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _program_backup_project(tmp_path)
    monkeypatch.setattr(program_backup, "resolve_program_root", lambda: project_root)

    with TestClient(app) as client:
        response = client.post("/api/backups/program")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "atlas-program-backup-" in response.headers["content-disposition"]
    assert response.headers["content-disposition"].endswith('.zip"')
    with ZipFile(BytesIO(response.content)) as archive:
        names = set(archive.namelist())

    assert {
        "backend/app/main.py",
        "backend/alembic/env.py",
        "backend/tests/test_app.py",
        "backend/requirements.txt",
        "backend/Dockerfile",
        "frontend/src/main.tsx",
        "frontend/public/robots.txt",
        "frontend/package.json",
        "frontend/index.html",
        "frontend/vite.config.ts",
        "frontend/tsconfig.json",
        "frontend/Dockerfile",
        "docker-compose.yml",
        "README.md",
    }.issubset(names)


def test_program_backup_excludes_generated_private_and_protected_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _program_backup_project(tmp_path)
    before = _file_tree_snapshot(project_root)
    monkeypatch.setattr(program_backup, "resolve_program_root", lambda: project_root)

    with TestClient(app) as client:
        response = client.post("/api/backups/program")

    after = _file_tree_snapshot(project_root)
    with ZipFile(BytesIO(response.content)) as archive:
        names = archive.namelist()

    excluded_fragments = (
        ".git/",
        ".pytest_cache/",
        "__pycache__/",
        "backend/backups/",
        "backend/media/",
        "frontend/public/media/",
        "frontend/node_modules/",
        "frontend/dist/",
    )
    assert response.status_code == 200
    assert after == before
    assert not any(fragment in name for name in names for fragment in excluded_fragments)
    assert not any(
        Path(name).name.lower() == ".env"
        or Path(name).name.lower().startswith(".env.")
        or "secret" in Path(name).name.lower()
        or Path(name).suffix.lower() in {".db", ".key", ".pem", ".pyc"}
        for name in names
    )


def test_page_export_package_builds_from_existing_atlas_data() -> None:
    with TestClient(app):
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page = _ensure_complete_page(session, page)
            package = build_page_export_package(session, page.id)

    assert package.page_title == "Drywood Termite Tenting in Orlando, FL"
    assert package.url_slug == "drywood-termite-tenting-orlando-fl"
    assert package.city == "Orlando"
    assert package.county == "Orange County"
    assert package.service == "Drywood Termite Tenting"
    assert package.business_name == FLO_ZONE_COMPANY_NAME
    assert package.phone and "(844) 600-8368" in package.phone
    assert package.content_sections["intro"]
    assert package.faq_items
    assert package.cta_block
    assert package.assigned_media[0].image_role == "hero"
    assert package.assigned_media[0].alt_text
    assert package.canonical_url_preview.endswith("/drywood-termite-tenting-orlando-fl/")
    assert any(warning.code == "page_not_approved" for warning in package.warnings)
    assert package.export_ready is False


def test_page_export_slug_generation_is_deterministic_and_safe() -> None:
    with TestClient(app):
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            service = session.get(Service, page.service_id)
            city = session.get(City, page.city_id)
            assert service is not None
            assert city is not None
            first = generate_suggested_slug(service, city)
            second = generate_suggested_slug(service, city)

    assert first == second == "drywood-termite-tenting-orlando-fl"
    assert slugify("Drywood Termite Tenting / St. Cloud, FL!") == "drywood-termite-tenting-st-cloud-fl"


def test_page_export_detects_duplicate_suggested_slug_conflict() -> None:
    with TestClient(app):
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            original_slug = page.page_slug
            page.page_slug = "custom-orlando-export"
            session.add(page)
            session.flush()
            conflict = GeneratedPage(
                business_id=page.business_id,
                service_id=page.service_id,
                city_id=page.city_id,
                county_id=page.county_id,
                page_type="city_service",
                page_title="Slug Conflict Test",
                page_slug=original_slug,
                status="draft",
            )
            session.add(conflict)
            session.flush()

            package = build_page_export_package(session, page.id)
            conflict_id = conflict.id
            session.rollback()

    assert package.seo.suggested_url_slug == original_slug
    assert package.slug_conflicts == [conflict_id]
    assert any(warning.code == "slug_conflict" for warning in package.warnings)
    assert package.export_ready is False


def test_page_export_warns_for_unsafe_absolute_claims() -> None:
    with TestClient(app):
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            original = deepcopy(page.draft_content)
            draft = deepcopy(page.draft_content or {})
            draft["intro"] = f"{draft.get('intro', '')} Results are guaranteed."
            page.draft_content = draft
            session.add(page)
            session.flush()

            package = build_page_export_package(session, page.id)
            page.draft_content = original
            session.rollback()

    unsafe = next(warning for warning in package.warnings if warning.code == "unsafe_phrase")
    assert unsafe.severity == "blocker"
    assert "guaranteed" in unsafe.message


def test_page_export_json_ld_contains_only_supported_facts() -> None:
    with TestClient(app):
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            package = build_page_export_package(session, page.id)

    graph = package.json_ld["@graph"]
    assert [item["@type"] for item in graph] == [
        "LocalBusiness",
        "Service",
        "FAQPage",
        "BreadcrumbList",
    ]
    serialized = json.dumps(package.json_ld)
    assert FLO_ZONE_COMPANY_NAME in serialized
    assert "(844) 600-8368" in serialized
    assert "JB360566" in serialized
    assert "Jordan Ward" in serialized
    assert "Orlando" in serialized
    assert "aggregateRating" not in serialized
    assert '"review"' not in serialized
    assert '"offers"' not in serialized
    assert '"price"' not in serialized


def test_page_export_endpoint_is_read_only() -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page_id = page.id
            before = _approval_queue_database_snapshot(session)

        response = client.get(f"/api/generated-pages/{page_id}/export-package")

        with Session(engine) as session:
            after = _approval_queue_database_snapshot(session)

    assert response.status_code == 200
    assert response.json()["page_id"] == page_id
    assert after == before


def test_single_page_export_download_returns_json_without_mutation() -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page_id = page.id
            before = _approval_queue_database_snapshot(session)

        response = client.get(f"/api/generated-pages/{page_id}/export-package/download")

        with Session(engine) as session:
            after = _approval_queue_database_snapshot(session)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert "atlas-page-export-drywood-termite-tenting-orlando-fl.json" in response.headers[
        "content-disposition"
    ]
    assert response.json()["page_id"] == page_id
    assert after == before


def test_bulk_page_export_contains_only_selected_json_packages() -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            orlando = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            deltona = _page_by_slug(session, "drywood-termite-tenting-deltona-fl")
            selected_ids = {orlando.id, deltona.id}
            before = _approval_queue_database_snapshot(session)

        preview = client.post(
            "/api/generated-pages/export/bulk-preview",
            json={"page_ids": list(selected_ids)},
        )
        response = client.post(
            "/api/generated-pages/export/bulk",
            json={"page_ids": list(selected_ids)},
        )

        with Session(engine) as session:
            after = _approval_queue_database_snapshot(session)

    assert preview.status_code == 200
    assert preview.json()["selected_count"] == 2
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with ZipFile(BytesIO(response.content)) as archive:
        names = archive.namelist()
        packages = [json.loads(archive.read(name)) for name in names]
    assert len(names) == 2
    assert all(name.endswith(".json") for name in names)
    assert {package["page_id"] for package in packages} == selected_ids
    assert not any(name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")) for name in names)
    assert after == before


def test_generation_prompt_includes_location_business_service_and_knowledge() -> None:
    with TestClient(app):
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            context = load_generation_context(session, page.id)
            prompt = assemble_generation_prompt(context)

    assert "Flo-Zone Pest And Termite Solutions Inc" in prompt
    assert "Drywood Termite Tenting" in prompt
    assert "City: Orlando" in prompt
    assert "County: Orange County" in prompt
    assert "What is drywood termite tenting?" in prompt
    assert "Knowledge blocks:" in prompt


def test_unsafe_generated_phrases_are_blocked() -> None:
    with pytest.raises(UnsafeContentError):
        validate_safe_content({"intro": "This is a 100% guaranteed treatment."})


def test_mock_generator_creates_structured_draft_output() -> None:
    with TestClient(app):
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-apopka-fl")
            page.status = "draft"
            page.draft_content = None
            page.content_body = None
            page.generation_status = "not_generated"
            session.add(page)
            session.commit()

            generated = generate_page_draft(session, page.id)

    assert generated.generation_status == "generated"
    assert generated.status == "draft"
    assert generated.draft_content is not None
    assert generated.draft_content["h1"] == "Drywood Termite Tenting in Apopka, Florida"
    assert generated.draft_content["faq_items"]
    assert "County County" not in generated.draft_content["intro"]
    validate_safe_content(generated.draft_content)


def test_generator_does_not_overwrite_approved_page_without_confirmation() -> None:
    with TestClient(app):
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-bay-lake-fl")
            sentinel = {"title": "Approved content"}
            page.status = "approved"
            page.draft_content = sentinel
            page.content_body = "Approved body"
            session.add(page)
            session.commit()

            with pytest.raises(DraftGenerationError):
                generate_page_draft(session, page.id)

            session.refresh(page)
            assert page.status == "approved"
            assert page.draft_content == sentinel
            assert page.content_body == "Approved body"

            page.status = "draft"
            page.draft_content = None
            page.content_body = None
            page.generation_status = "not_generated"
            session.add(page)
            session.commit()


def test_batch_preview_does_not_modify_database() -> None:
    with TestClient(app):
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-belle-isle-fl")
            before = (page.status, page.generation_status, page.draft_content, page.content_body, page.updated_at)

            preview = preview_batch(session, city_ids=[page.city_id])
            session.refresh(page)
            after = (page.status, page.generation_status, page.draft_content, page.content_body, page.updated_at)

    assert preview.matched_count == 1
    assert preview.eligible_count == 1
    assert after == before


def test_batch_generation_updates_only_allowed_draft_pages() -> None:
    with TestClient(app):
        with Session(engine) as session:
            draft_page = _page_by_slug(session, "drywood-termite-tenting-edgewood-fl")
            approved_page = _page_by_slug(session, "drywood-termite-tenting-eatonville-fl")
            draft_page.status = "draft"
            draft_page.draft_content = None
            draft_page.content_body = None
            draft_page.generation_status = "not_generated"
            approved_page.status = "approved"
            approved_page.draft_content = {"title": "Keep me"}
            approved_page.content_body = "Keep this approved body"
            session.add(draft_page)
            session.add(approved_page)
            session.commit()

            generated_ids = generate_batch(
                session,
                city_ids=[draft_page.city_id, approved_page.city_id],
            )
            session.refresh(draft_page)
            session.refresh(approved_page)

            assert generated_ids == [draft_page.id]
            assert draft_page.generation_status == "generated"
            assert draft_page.draft_content is not None
            assert approved_page.status == "approved"
            assert approved_page.draft_content == {"title": "Keep me"}
            assert approved_page.content_body == "Keep this approved body"

            approved_page.status = "draft"
            approved_page.draft_content = None
            approved_page.content_body = None
            approved_page.generation_status = "not_generated"
            session.add(approved_page)
            session.commit()


def test_mock_provider_is_used_without_external_api_key() -> None:
    assert isinstance(get_draft_provider(), DeterministicMockProvider)


def test_orlando_reviewed_hero_media_is_seeded_and_assigned() -> None:
    with TestClient(app):
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            assignment = session.exec(
                select(PageImageAssignment).where(
                    PageImageAssignment.generated_page_id == page.id,
                    PageImageAssignment.image_role == "hero",
                )
            ).one()
            image = session.get(ImageMetadata, assignment.image_metadata_id)

    assert image is not None
    assert image.image_role == "hero"
    assert image.review_status == "reviewed"
    assert image.reviewed_alt_text
    assert image.asset_url == "/media/orlando-drywood-termite-tenting-hero.png"
    assert image.focal_x == 0.5
    assert image.focal_y == 0.5
    assert image.city_id == page.city_id
    assert image.county_id == page.county_id
    assert image.service_id == page.service_id


def test_page_media_assignment_can_be_removed_and_restored_without_changing_page() -> None:
    with TestClient(app) as client:
        pages = client.get("/api/generated-pages").json()
        page = next(item for item in pages if item["page_slug"] == "drywood-termite-tenting-orlando-fl")
        images = client.get("/api/image-metadata").json()
        image = next(item for item in images if item["asset_url"] == "/media/orlando-drywood-termite-tenting-hero.png")
        page_before = client.get(f"/api/generated-pages/{page['id']}").json()

        delete_response = client.delete(f"/api/generated-pages/{page['id']}/media/hero")
        empty_media = client.get(f"/api/generated-pages/{page['id']}/media").json()
        assign_response = client.put(
            f"/api/generated-pages/{page['id']}/media/hero",
            json={"image_metadata_id": image["id"]},
        )
        page_after = client.get(f"/api/generated-pages/{page['id']}").json()

    assert delete_response.status_code == 200
    assert empty_media == []
    assert assign_response.status_code == 200
    assert assign_response.json()["image"]["reviewed_alt_text"] == image["reviewed_alt_text"]
    assert page_after["draft_content"] == page_before["draft_content"]
    assert page_after["status"] == page_before["status"]
    assert page_after["updated_at"] == page_before["updated_at"]


def test_unreviewed_image_cannot_be_assigned() -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            image = ImageMetadata(
                business_id=page.business_id,
                service_id=page.service_id,
                city_id=page.city_id,
                county_id=page.county_id,
                file_name="unreviewed-orlando-image.jpg",
                image_title="Unreviewed Orlando Image",
                image_role="support",
                review_status="pending",
            )
            session.add(image)
            session.commit()
            session.refresh(image)
            image_id = image.id
            page_id = page.id

        response = client.put(
            f"/api/generated-pages/{page_id}/media/support",
            json={"image_metadata_id": image_id},
        )

        with Session(engine) as session:
            stored_image = session.get(ImageMetadata, image_id)
            if stored_image:
                session.delete(stored_image)
                session.commit()

    assert response.status_code == 409
    assert "reviewed" in response.json()["detail"].lower()


def test_media_upload_accepts_valid_image_and_creates_metadata_and_variants() -> None:
    with TestClient(app) as client:
        context = _orlando_context(client)
        response = client.post(
            "/api/media/upload",
            files={"file": ("Orlando Inspection.png", _png_bytes(), "image/png")},
            data={
                "business_id": context["page"]["business_id"],
                "service_id": context["page"]["service_id"],
                "county_id": context["page"]["county_id"],
                "city_id": context["page"]["city_id"],
                "image_title": "Orlando Drywood Termite Inspection",
                "image_role": "support",
                "notes": "Uploaded during media workflow testing.",
            },
        )

    assert response.status_code == 201
    uploaded = response.json()
    assert uploaded["review_status"] == "pending_review"
    assert uploaded["original_filename"] == "Orlando Inspection.png"
    assert uploaded["stored_filename"].endswith(".png")
    assert uploaded["thumbnail_url"]
    assert uploaded["optimized_url"]
    assert uploaded["focal_x"] == 0.5
    assert uploaded["focal_y"] == 0.5
    assert _managed_path(uploaded["stored_filename"], "originals").is_file()
    assert _managed_path_from_url(uploaded["thumbnail_url"]).is_file()
    assert _managed_path_from_url(uploaded["optimized_url"]).is_file()

    with Session(engine) as session:
        stored = session.get(ImageMetadata, uploaded["id"])
        assert stored is not None
        assert stored.image_title == "Orlando Drywood Termite Inspection"


def test_media_upload_rejects_invalid_file_type() -> None:
    with TestClient(app) as client:
        context = _orlando_context(client)
        response = client.post(
            "/api/media/upload",
            files={"file": ("payload.txt", b"not an image", "text/plain")},
            data={"business_id": context["page"]["business_id"]},
        )

    assert response.status_code == 415
    assert "jpeg" in response.json()["detail"].lower()


def test_media_upload_rejects_oversized_file(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "media_max_upload_bytes", 32)
    with TestClient(app) as client:
        context = _orlando_context(client)
        response = client.post(
            "/api/media/upload",
            files={"file": ("large.png", b"x" * 33, "image/png")},
            data={"business_id": context["page"]["business_id"]},
        )

    assert response.status_code == 413
    assert "limit" in response.json()["detail"].lower()


def test_uploaded_media_requires_review_before_assignment_and_preserves_draft() -> None:
    with TestClient(app) as client:
        context = _orlando_context(client)
        page_before = client.get(f"/api/generated-pages/{context['page']['id']}").json()
        upload = client.post(
            "/api/media/upload",
            files={"file": ("pending-support.png", _png_bytes(color=(62, 118, 91)), "image/png")},
            data={
                "business_id": context["page"]["business_id"],
                "service_id": context["page"]["service_id"],
                "county_id": context["page"]["county_id"],
                "city_id": context["page"]["city_id"],
                "image_role": "support",
            },
        ).json()

        pending_assignment = client.put(
            f"/api/generated-pages/{context['page']['id']}/media/support",
            json={"image_metadata_id": upload["id"]},
        )
        reviewed = client.patch(
            f"/api/image-metadata/{upload['id']}",
            json={
                "reviewed_alt_text": "Pest professional inspecting an Orlando home for drywood termites",
                "review_status": "reviewed",
            },
        )
        reviewed_assignment = client.put(
            f"/api/generated-pages/{context['page']['id']}/media/support",
            json={"image_metadata_id": upload["id"]},
        )
        page_after = client.get(f"/api/generated-pages/{context['page']['id']}").json()
        hero_after = client.get(f"/api/generated-pages/{context['page']['id']}/media").json()
        client.delete(f"/api/generated-pages/{context['page']['id']}/media/support")

    assert pending_assignment.status_code == 409
    assert reviewed.status_code == 200
    assert reviewed_assignment.status_code == 200
    assert page_after["draft_content"] == page_before["draft_content"]
    assert page_after["status"] == page_before["status"]
    assert page_after["updated_at"] == page_before["updated_at"]
    hero = next(item for item in hero_after if item["image_role"] == "hero")
    assert hero["image"]["asset_url"] == "/media/orlando-drywood-termite-tenting-hero.png"


def test_backup_export_preserves_uploaded_media_metadata_and_assignments(tmp_path: Path) -> None:
    with TestClient(app):
        with Session(engine) as session:
            result = export_backup(session, backup_dir=tmp_path)

    payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    images = payload["data"]["image_metadata"]
    assignments = payload["data"]["page_image_assignments"]
    assert any(image.get("thumbnail_url") and image.get("optimized_url") for image in images)
    assert all(0 <= image["focal_x"] <= 1 and 0 <= image["focal_y"] <= 1 for image in images)
    assert all("sort_order" in assignment for assignment in assignments)
    assert all("override_focal_x" in assignment for assignment in assignments)
    assert all("override_focal_y" in assignment for assignment in assignments)
    assert all("override_alt_text" in assignment for assignment in assignments)
    assert all("display_preset" in assignment for assignment in assignments)
    assert any(assignment["image_role"] == "hero" for assignment in assignments)


def test_focal_point_can_be_updated_and_media_api_returns_it_without_changing_page() -> None:
    with TestClient(app) as client:
        context = _orlando_context(client)
        page_id = context["page"]["id"]
        page_before = client.get(f"/api/generated-pages/{page_id}").json()
        media_before = client.get(f"/api/generated-pages/{page_id}/media").json()
        hero_before = next(item for item in media_before if item["image_role"] == "hero")
        image_id = hero_before["image"]["id"]

        update = client.patch(
            f"/api/image-metadata/{image_id}",
            json={"focal_x": 0.27, "focal_y": 0.68},
        )
        media_after = client.get(f"/api/generated-pages/{page_id}/media").json()
        page_after = client.get(f"/api/generated-pages/{page_id}").json()
        client.patch(
            f"/api/image-metadata/{image_id}",
            json={
                "focal_x": hero_before["image"]["focal_x"],
                "focal_y": hero_before["image"]["focal_y"],
            },
        )

    hero_after = next(item for item in media_after if item["image_role"] == "hero")
    assert update.status_code == 200
    assert update.json()["focal_x"] == 0.27
    assert update.json()["focal_y"] == 0.68
    assert hero_after["image"]["focal_x"] == 0.27
    assert hero_after["image"]["focal_y"] == 0.68
    assert page_after["draft_content"] == page_before["draft_content"]
    assert page_after["status"] == page_before["status"]
    assert page_after["updated_at"] == page_before["updated_at"]


@pytest.mark.parametrize(
    ("field", "value"),
    [("focal_x", -0.01), ("focal_x", 1.01), ("focal_y", -0.01), ("focal_y", 1.01)],
)
def test_invalid_focal_point_values_are_rejected(field: str, value: float) -> None:
    with TestClient(app) as client:
        context = _orlando_context(client)
        media = client.get(f"/api/generated-pages/{context['page']['id']}/media").json()
        image_id = next(item for item in media if item["image_role"] == "hero")["image"]["id"]
        response = client.patch(f"/api/image-metadata/{image_id}", json={field: value})

    assert response.status_code == 422


def test_backup_restore_preserves_focal_points(tmp_path: Path) -> None:
    with TestClient(app):
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            assignment = session.exec(
                select(PageImageAssignment).where(
                    PageImageAssignment.generated_page_id == page.id,
                    PageImageAssignment.image_role == "hero",
                )
            ).one()
            image = session.get(ImageMetadata, assignment.image_metadata_id)
            assert image is not None
            original = (image.focal_x, image.focal_y)
            image.focal_x = 0.34
            image.focal_y = 0.72
            session.add(image)
            session.commit()

            result = export_backup(session, backup_dir=tmp_path)
            payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
            exported = next(item for item in payload["data"]["image_metadata"] if item["id"] == image.id)

            image.focal_x = 0.5
            image.focal_y = 0.5
            session.add(image)
            session.commit()
            restore_backup(session, result["path"])
            session.refresh(image)
            restored = (image.focal_x, image.focal_y)

            image.focal_x, image.focal_y = original
            session.add(image)
            session.commit()

    assert exported["focal_x"] == 0.34
    assert exported["focal_y"] == 0.72
    assert restored == (0.34, 0.72)


def test_page_media_override_defaults_use_global_image_values() -> None:
    with TestClient(app) as client:
        context = _orlando_context(client)
        media = client.get(f"/api/generated-pages/{context['page']['id']}/media").json()

    hero = next(item for item in media if item["image_role"] == "hero")
    assert hero["override_focal_x"] is None
    assert hero["override_focal_y"] is None
    assert hero["override_alt_text"] is None
    assert hero["display_preset"] == "hero_desktop"
    assert hero["effective_focal_x"] == hero["image"]["focal_x"]
    assert hero["effective_focal_y"] == hero["image"]["focal_y"]
    assert hero["effective_alt_text"] == hero["image"]["reviewed_alt_text"]


def test_page_media_override_wins_and_does_not_change_generated_page() -> None:
    with TestClient(app) as client:
        context = _orlando_context(client)
        page_id = context["page"]["id"]
        page_before = client.get(f"/api/generated-pages/{page_id}").json()
        media = client.get(f"/api/generated-pages/{page_id}/media").json()
        hero = next(item for item in media if item["image_role"] == "hero")

        update = client.patch(
            f"/api/generated-pages/{page_id}/media/assignments/{hero['assignment_id']}",
            json={
                "override_focal_x": 0.22,
                "override_focal_y": 0.74,
                "override_alt_text": "Page-specific Orlando tenting hero",
                "display_preset": "hero_desktop",
            },
        )
        page_after = client.get(f"/api/generated-pages/{page_id}").json()
        client.patch(
            f"/api/generated-pages/{page_id}/media/assignments/{hero['assignment_id']}",
            json={
                "override_focal_x": None,
                "override_focal_y": None,
                "override_alt_text": None,
            },
        )

    assert update.status_code == 200
    updated = update.json()
    assert updated["effective_focal_x"] == 0.22
    assert updated["effective_focal_y"] == 0.74
    assert updated["effective_alt_text"] == "Page-specific Orlando tenting hero"
    assert page_after["draft_content"] == page_before["draft_content"]
    assert page_after["status"] == page_before["status"]
    assert page_after["updated_at"] == page_before["updated_at"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("override_focal_x", -0.01),
        ("override_focal_x", 1.01),
        ("override_focal_y", -0.01),
        ("override_focal_y", 1.01),
    ],
)
def test_invalid_page_media_override_focal_values_are_rejected(
    field: str,
    value: float,
) -> None:
    with TestClient(app) as client:
        context = _orlando_context(client)
        media = client.get(f"/api/generated-pages/{context['page']['id']}/media").json()
        hero = next(item for item in media if item["image_role"] == "hero")
        response = client.patch(
            f"/api/generated-pages/{context['page']['id']}/media/assignments/{hero['assignment_id']}",
            json={field: value},
        )

    assert response.status_code == 422


def test_hero_assignment_remains_singular() -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            image = _create_reviewed_image(session, page, "second-hero")
            page_id = page.id
            image_id = image.id

        response = client.post(
            f"/api/generated-pages/{page_id}/media",
            json={"image_metadata_id": image_id, "image_role": "hero"},
        )

        with Session(engine) as session:
            stored = session.get(ImageMetadata, image_id)
            if stored:
                session.delete(stored)
                session.commit()

    assert response.status_code == 409
    assert "hero" in response.json()["detail"].lower()


@pytest.mark.parametrize("image_role", ["service", "support"])
def test_service_and_support_allow_multiple_ordered_images(image_role: str) -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            first = _create_reviewed_image(session, page, f"{image_role}-first")
            second = _create_reviewed_image(session, page, f"{image_role}-second")
            page_id = page.id
            image_ids = [first.id, second.id]
        page_before = client.get(f"/api/generated-pages/{page_id}").json()

        first_response = client.post(
            f"/api/generated-pages/{page_id}/media",
            json={
                "image_metadata_id": image_ids[0],
                "image_role": image_role,
                "sort_order": 20,
            },
        )
        second_response = client.post(
            f"/api/generated-pages/{page_id}/media",
            json={
                "image_metadata_id": image_ids[1],
                "image_role": image_role,
                "sort_order": 10,
            },
        )
        duplicate = client.post(
            f"/api/generated-pages/{page_id}/media",
            json={
                "image_metadata_id": image_ids[0],
                "image_role": image_role,
            },
        )
        ordered_before = [
            item
            for item in client.get(f"/api/generated-pages/{page_id}/media").json()
            if item["image_role"] == image_role
        ]
        reorder = client.put(
            f"/api/generated-pages/{page_id}/media/order/{image_role}",
            json={
                "assignment_ids": [
                    first_response.json()["assignment_id"],
                    second_response.json()["assignment_id"],
                ]
            },
        )
        page_after = client.get(f"/api/generated-pages/{page_id}").json()

        for assignment in (first_response.json(), second_response.json()):
            client.delete(
                f"/api/generated-pages/{page_id}/media/assignments/{assignment['assignment_id']}"
            )
        with Session(engine) as session:
            for image_id in image_ids:
                stored = session.get(ImageMetadata, image_id)
                if stored:
                    session.delete(stored)
            session.commit()

    assert first_response.status_code == 201
    assert second_response.status_code == 201
    assert [item["image"]["id"] for item in ordered_before] == [image_ids[1], image_ids[0]]
    assert duplicate.status_code == 409
    assert [item["sort_order"] for item in reorder.json()] == [0, 10]
    assert page_after["draft_content"] == page_before["draft_content"]
    assert page_after["status"] == page_before["status"]
    assert page_after["updated_at"] == page_before["updated_at"]


def test_removing_assignment_preserves_image_metadata_and_managed_files() -> None:
    with TestClient(app) as client:
        context = _orlando_context(client)
        upload = client.post(
            "/api/media/upload",
            files={"file": ("removal-safety.png", _png_bytes(), "image/png")},
            data={
                "business_id": context["page"]["business_id"],
                "service_id": context["page"]["service_id"],
                "county_id": context["page"]["county_id"],
                "city_id": context["page"]["city_id"],
                "image_role": "support",
            },
        ).json()
        client.patch(
            f"/api/image-metadata/{upload['id']}",
            json={
                "reviewed_alt_text": "Reviewed support image for removal safety",
                "review_status": "reviewed",
            },
        )
        assignment = client.post(
            f"/api/generated-pages/{context['page']['id']}/media",
            json={"image_metadata_id": upload["id"], "image_role": "support"},
        ).json()
        removal = client.delete(
            f"/api/generated-pages/{context['page']['id']}/media/assignments/{assignment['assignment_id']}"
        )
        metadata_after = client.get(f"/api/image-metadata/{upload['id']}")

    assert removal.status_code == 200
    assert metadata_after.status_code == 200
    assert _managed_path(upload["stored_filename"], "originals").is_file()
    assert _managed_path_from_url(upload["thumbnail_url"]).is_file()
    assert _managed_path_from_url(upload["optimized_url"]).is_file()


def test_backup_restore_preserves_assignment_overrides_and_sort_order(
    tmp_path: Path,
) -> None:
    with TestClient(app):
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            image = _create_reviewed_image(session, page, "backup-assignment")
            assignment = PageImageAssignment(
                generated_page_id=page.id,
                image_metadata_id=image.id,
                image_role="support",
                sort_order=37,
                override_focal_x=0.19,
                override_focal_y=0.81,
                override_alt_text="Backup-specific support alt",
                display_preset="square",
            )
            session.add(assignment)
            session.commit()
            session.refresh(assignment)
            assignment_id = assignment.id
            image_id = image.id

            result = export_backup(session, backup_dir=tmp_path)
            payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
            exported = next(
                item
                for item in payload["data"]["page_image_assignments"]
                if item["id"] == assignment_id
            )

            assignment.sort_order = 0
            assignment.override_focal_x = None
            assignment.override_focal_y = None
            assignment.override_alt_text = None
            assignment.display_preset = "original"
            session.add(assignment)
            session.commit()
            restore_backup(session, result["path"])
            session.refresh(assignment)
            restored = (
                assignment.sort_order,
                assignment.override_focal_x,
                assignment.override_focal_y,
                assignment.override_alt_text,
                assignment.display_preset,
            )

            session.delete(assignment)
            stored_image = session.get(ImageMetadata, image_id)
            if stored_image:
                session.delete(stored_image)
            session.commit()

    assert exported["sort_order"] == 37
    assert exported["override_focal_x"] == 0.19
    assert exported["override_focal_y"] == 0.81
    assert exported["override_alt_text"] == "Backup-specific support alt"
    assert exported["display_preset"] == "square"
    assert restored == (37, 0.19, 0.81, "Backup-specific support alt", "square")


def test_qa_passes_complete_orlando_page() -> None:
    with TestClient(app):
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page = _ensure_complete_page(session, page)
            result = evaluate_page_qa(session, page.id)

    assert result.readiness_status == "ready", [
        (check.key, check.status, check.message)
        for check in result.checks
        if check.status != "pass"
    ]
    assert result.failed_count == 0
    assert result.warning_count == 0
    assert all(check.status == "pass" for check in result.checks)


def test_qa_flags_missing_core_content_fields() -> None:
    missing_keys = {
        "title",
        "meta_title",
        "meta_description",
        "h1",
        "call_to_action",
        "faqs",
    }
    with TestClient(app):
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page = _ensure_complete_page(session, page)
            original = {
                "page_title": page.page_title,
                "meta_title": page.meta_title,
                "meta_description": page.meta_description,
                "h1": page.h1,
                "draft_content": deepcopy(page.draft_content),
            }
            draft = deepcopy(page.draft_content or {})
            for key in ("title", "meta_title", "meta_description", "h1", "call_to_action"):
                draft[key] = ""
            draft["faq_items"] = []
            page.page_title = ""
            page.meta_title = ""
            page.meta_description = ""
            page.h1 = ""
            page.draft_content = draft
            session.add(page)
            session.flush()

            result = evaluate_page_qa(session, page.id)
            failed = {check.key for check in result.checks if check.status == "fail"}

            for key, value in original.items():
                setattr(page, key, value)
            session.add(page)
            session.commit()

    assert result.readiness_status == "blocked"
    assert missing_keys.issubset(failed)


def test_qa_flags_unsafe_phrases_and_county_duplication() -> None:
    with TestClient(app):
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page = _ensure_complete_page(session, page)
            original = deepcopy(page.draft_content)
            draft = deepcopy(page.draft_content or {})
            draft["intro"] = f"{draft.get('intro', '')} County County. This is 100% guaranteed."
            page.draft_content = draft
            session.add(page)
            session.flush()

            result = evaluate_page_qa(session, page.id)
            status_by_key = {check.key: check.status for check in result.checks}

            page.draft_content = original
            session.add(page)
            session.commit()

    assert status_by_key["unsafe_phrases"] == "fail"
    assert status_by_key["county_county"] == "fail"


def test_qa_flags_missing_hero_image() -> None:
    with TestClient(app):
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page = _ensure_complete_page(session, page)
            hero = session.exec(
                select(PageImageAssignment).where(
                    PageImageAssignment.generated_page_id == page.id,
                    PageImageAssignment.image_role == "hero",
                )
            ).one()
            session.delete(hero)
            session.flush()
            result = evaluate_page_qa(session, page.id)
            status_by_key = {check.key: check.status for check in result.checks}
            session.rollback()

    assert status_by_key["hero_assigned"] == "fail"
    assert status_by_key["hero_reviewed"] == "fail"
    assert status_by_key["hero_alt_text"] == "fail"


def test_qa_flags_unreviewed_image_and_missing_alt_text() -> None:
    with TestClient(app):
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page = _ensure_complete_page(session, page)
            hero = session.exec(
                select(PageImageAssignment).where(
                    PageImageAssignment.generated_page_id == page.id,
                    PageImageAssignment.image_role == "hero",
                )
            ).one()
            image = session.get(ImageMetadata, hero.image_metadata_id)
            assert image is not None
            original = (image.review_status, image.reviewed_alt_text, image.alt_text)
            image.review_status = "pending_review"
            image.reviewed_alt_text = None
            image.alt_text = None
            session.add(image)
            session.flush()

            result = evaluate_page_qa(session, page.id)
            status_by_key = {check.key: check.status for check in result.checks}

            image.review_status, image.reviewed_alt_text, image.alt_text = original
            session.add(image)
            session.commit()

    assert status_by_key["hero_reviewed"] == "fail"
    assert status_by_key["hero_alt_text"] == "fail"
    assert status_by_key["assigned_images_reviewed"] == "fail"


def test_qa_batch_preview_does_not_modify_database() -> None:
    with TestClient(app):
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page = _ensure_complete_page(session, page)
            before = (
                page.qa_status,
                deepcopy(page.qa_result),
                page.qa_checked_at,
                deepcopy(page.draft_content),
                page.status,
                page.updated_at,
            )
            result = preview_qa_batch(
                session,
                QABatchRequest(city_ids=[page.city_id]),
            )
            session.refresh(page)
            after = (
                page.qa_status,
                page.qa_result,
                page.qa_checked_at,
                page.draft_content,
                page.status,
                page.updated_at,
            )

    assert result.matched_count == 1
    assert result.saved_count == 0
    assert after == before


def test_qa_batch_run_saves_only_qa_result() -> None:
    with TestClient(app):
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page = _ensure_complete_page(session, page)
            before = (deepcopy(page.draft_content), page.status, page.updated_at)
            result = run_qa_batch(
                session,
                QABatchRequest(city_ids=[page.city_id], confirm=True),
            )
            session.refresh(page)
            after = (page.draft_content, page.status, page.updated_at)

    assert result.saved_count == 1
    assert page.qa_status == "ready"
    assert page.qa_result is not None
    assert page.qa_checked_at is not None
    assert after == before


def test_qa_backup_export_and_restore_preserve_result(tmp_path: Path) -> None:
    with TestClient(app):
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page = _ensure_complete_page(session, page)
            saved = save_page_qa(session, page.id)
            export = export_backup(session, backup_dir=tmp_path)
            payload = json.loads(Path(export["path"]).read_text(encoding="utf-8"))
            exported = next(
                record
                for record in payload["data"]["generated_pages"]
                if record["id"] == page.id
            )

            page.qa_status = "not_run"
            page.qa_result = None
            page.qa_checked_at = None
            session.add(page)
            session.commit()
            restore_backup(session, export["path"])
            session.refresh(page)

    assert exported["qa_status"] == saved.readiness_status
    assert exported["qa_result"]["checks"]
    assert page.qa_status == saved.readiness_status
    assert page.qa_result == exported["qa_result"]
    assert page.qa_checked_at is not None


def test_qa_warning_and_blocker_items_include_remediation_guidance() -> None:
    with TestClient(app):
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page = _ensure_complete_page(session, page)
            original = deepcopy(page.draft_content)
            draft = deepcopy(page.draft_content or {})
            draft["call_to_action"] = ""
            draft["intro"] = f"{draft['intro']} {page.page_title}"
            page.draft_content = draft
            session.add(page)
            session.commit()
            result = evaluate_page_qa(session, page.id)
            issues = [item for item in result.checks if item.status != "pass"]
            page.draft_content = original
            session.add(page)
            session.commit()

    assert issues
    assert all(item.suggested_fix for item in issues)
    assert all(
        item.issue_location
        in {"content", "business_info", "city_county_info", "media", "preview", "safety_wording"}
        for item in issues
    )


def test_manual_review_notes_do_not_change_draft_or_page_status() -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            before = (deepcopy(page.draft_content), page.status, page.updated_at)
            revisions_before = len(
                session.exec(
                    select(GeneratedPageRevision).where(
                        GeneratedPageRevision.generated_page_id == page.id
                    )
                ).all()
            )
            page_id = page.id

        response = client.patch(
            f"/api/generated-pages/{page_id}/review",
            json={
                "internal_notes": "Need better local landmark section",
                "last_reviewed_by": "Atlas Reviewer",
            },
        )

        with Session(engine) as session:
            page = session.get(GeneratedPage, page_id)
            assert page is not None
            after = (page.draft_content, page.status, page.updated_at)
            reviewed_at = page.last_reviewed_at
            revisions_after = len(
                session.exec(
                    select(GeneratedPageRevision).where(
                        GeneratedPageRevision.generated_page_id == page_id
                    )
                ).all()
            )
            page.internal_notes = None
            page.last_reviewed_at = None
            page.last_reviewed_by = None
            session.add(page)
            session.commit()

    assert response.status_code == 200
    assert response.json()["internal_notes"] == "Need better local landmark section"
    assert response.json()["last_reviewed_by"] == "Atlas Reviewer"
    assert reviewed_at is not None
    assert after == before
    assert revisions_after == revisions_before


def test_approval_reruns_qa_and_blocks_stale_ready_page() -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page = _ensure_complete_page(session, page)
            original = deepcopy(page.draft_content)
            draft = deepcopy(page.draft_content or {})
            draft["call_to_action"] = ""
            page.draft_content = draft
            page.qa_status = "ready"
            page.qa_result = {"readiness_status": "ready"}
            session.add(page)
            session.commit()
            page_id = page.id

        response = client.post(f"/api/generated-pages/{page_id}/approve")

        with Session(engine) as session:
            page = session.get(GeneratedPage, page_id)
            assert page is not None
            audits = session.exec(
                select(ApprovalAudit).where(ApprovalAudit.generated_page_id == page_id)
            ).all()
            status_after = page.status
            qa_after = page.qa_status
            page.draft_content = original
            page.qa_status = "not_run"
            page.qa_result = None
            page.qa_checked_at = None
            session.add(page)
            session.commit()

    assert response.status_code == 409
    assert status_after == "draft"
    assert qa_after == "blocked"
    assert audits == []


def test_successful_approval_creates_audit_and_preserves_draft_content() -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page = _ensure_complete_page(session, page)
            page.status = "draft"
            session.add(page)
            session.commit()
            before_draft = deepcopy(page.draft_content)
            before_status = page.status
            before_audits = session.exec(
                select(ApprovalAudit).where(ApprovalAudit.generated_page_id == page.id)
            ).all()
            page_id = page.id

        response = client.post(
            f"/api/generated-pages/{page_id}/approve",
            json={"approved_by": "Atlas Reviewer"},
        )

        with Session(engine) as session:
            page = session.get(GeneratedPage, page_id)
            assert page is not None
            audits = session.exec(
                select(ApprovalAudit).where(ApprovalAudit.generated_page_id == page_id)
            ).all()
            after_draft = deepcopy(page.draft_content)
            after_status = page.status
            audit = audits[0]
            page.status = "draft"
            page.qa_status = "not_run"
            page.qa_result = None
            page.qa_checked_at = None
            session.add(page)
            for record in audits:
                session.delete(record)
            session.commit()

    assert before_status == "draft"
    assert before_audits == []
    assert response.status_code == 200
    assert after_status == "approved"
    assert after_draft == before_draft
    assert len(audits) == 1
    assert audit.approved_by == "Atlas Reviewer"
    assert audit.qa_status_at_approval == "ready"
    assert audit.qa_result_snapshot["readiness_status"] == "ready"
    assert audit.qa_result_snapshot["checks"]
    assert audit.draft_hash_at_approval == draft_content_hash(before_draft)
    assert audit.page_status_before == "draft"
    assert audit.page_status_after == "approved"


def test_backup_restore_preserves_review_notes_and_approval_audits_idempotently(
    tmp_path: Path,
) -> None:
    approved_at = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    with TestClient(app):
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page = _ensure_complete_page(session, page)
            original_review = (
                page.internal_notes,
                page.last_reviewed_at,
                page.last_reviewed_by,
            )
            qa = evaluate_page_qa(session, page.id)
            page.internal_notes = "Need hero crop reviewed on mobile"
            page.last_reviewed_at = approved_at
            page.last_reviewed_by = "Backup Reviewer"
            audit = ApprovalAudit(
                generated_page_id=page.id,
                approved_at=approved_at,
                approved_by="Backup Reviewer",
                qa_status_at_approval=qa.readiness_status,
                qa_checked_at=qa.checked_at,
                qa_result_snapshot=qa.model_dump(mode="json", exclude={"persisted"}),
                draft_hash_at_approval=draft_content_hash(page.draft_content),
                page_status_before="draft",
                page_status_after="approved",
            )
            session.add(page)
            session.add(audit)
            session.commit()
            export = export_backup(session, backup_dir=tmp_path)
            payload = json.loads(Path(export["path"]).read_text(encoding="utf-8"))
            page.internal_notes = None
            page.last_reviewed_at = None
            page.last_reviewed_by = None
            session.add(page)
            session.delete(audit)
            session.commit()

            restore_backup(session, export["path"])
            restore_backup(session, export["path"])
            session.refresh(page)
            restored_audits = session.exec(
                select(ApprovalAudit).where(ApprovalAudit.generated_page_id == page.id)
            ).all()
            restored_review = (
                page.internal_notes,
                page.last_reviewed_at,
                page.last_reviewed_by,
            )
            page.internal_notes, page.last_reviewed_at, page.last_reviewed_by = original_review
            session.add(page)
            for record in restored_audits:
                session.delete(record)
            session.commit()

        assert payload["metadata"]["version"] == "0.34"
    assert payload["data"]["approval_audits"]
    exported_page = next(
        record
        for record in payload["data"]["generated_pages"]
        if record["page_slug"] == "drywood-termite-tenting-orlando-fl"
    )
    assert exported_page["internal_notes"] == "Need hero crop reviewed on mobile"
    assert exported_page["last_reviewed_by"] == "Backup Reviewer"
    assert restored_review[0] == "Need hero crop reviewed on mobile"
    assert restored_review[2] == "Backup Reviewer"
    assert len(restored_audits) == 1


def test_manual_draft_save_updates_content_and_creates_revision() -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page = _ensure_complete_page(session, page)
            original = _editor_page_state(page)
            payload = _manual_editor_payload(page)
            payload["draft"]["intro"] += " Manual Orlando review update."
            page_id = page.id

        response = client.put(f"/api/generated-pages/{page_id}/draft", json=payload)

        with Session(engine) as session:
            page = session.get(GeneratedPage, page_id)
            assert page is not None
            revisions = session.exec(
                select(GeneratedPageRevision).where(
                    GeneratedPageRevision.generated_page_id == page_id
                )
            ).all()
            saved_draft = deepcopy(page.draft_content)
            revision = revisions[0]
            _restore_editor_page(session, page, original, revisions=revisions)

    assert response.status_code == 200
    assert saved_draft["intro"].endswith("Manual Orlando review update.")
    assert saved_draft["hero_subheadline"]
    assert saved_draft["service_explanation"]
    assert saved_draft["local_city_section"]
    assert saved_draft["why_choose_section"]
    assert len(revisions) == 1
    assert revision.draft_hash_before == draft_content_hash(original["draft_content"])
    assert revision.draft_hash_after == draft_content_hash(saved_draft)
    assert "intro" in revision.changed_fields
    assert response.json()["page"]["status"] == "draft"


def test_invalid_manual_draft_save_is_rejected_without_revision() -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page = _ensure_complete_page(session, page)
            before_draft = deepcopy(page.draft_content)
            payload = _manual_editor_payload(page)
            payload["draft"]["hero_headline"] = ""
            page_id = page.id
            revisions_before = _revision_count(session, page_id)

        response = client.put(f"/api/generated-pages/{page_id}/draft", json=payload)

        with Session(engine) as session:
            page = session.get(GeneratedPage, page_id)
            assert page is not None
            revisions_after = _revision_count(session, page_id)
            after_draft = deepcopy(page.draft_content)

    assert response.status_code == 422
    assert after_draft == before_draft
    assert revisions_after == revisions_before


def test_unsafe_manual_draft_save_is_rejected_without_revision() -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page = _ensure_complete_page(session, page)
            before_draft = deepcopy(page.draft_content)
            payload = _manual_editor_payload(page)
            payload["draft"]["call_to_action"] = "This treatment is 100% guaranteed."
            page_id = page.id
            revisions_before = _revision_count(session, page_id)

        response = client.put(f"/api/generated-pages/{page_id}/draft", json=payload)

        with Session(engine) as session:
            page = session.get(GeneratedPage, page_id)
            assert page is not None
            revisions_after = _revision_count(session, page_id)
            after_draft = deepcopy(page.draft_content)

    assert response.status_code == 422
    assert "unsafe wording" in str(response.json()["detail"]).lower()
    assert after_draft == before_draft
    assert revisions_after == revisions_before


def test_approved_wp_ref_page_can_be_repaired_with_revision_and_qa() -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page = _ensure_complete_page(session, page)
            original = _approved_repair_page_state(page)
            page.status = "approved"
            page.wordpress_post_id = 8001
            page.wordpress_status = "draft"
            page.wordpress_url = "https://example.test/?page_id=8001"
            session.add(page)
            session.commit()
            page_id = page.id
            before_refs = (page.wordpress_post_id, page.wordpress_status, page.wordpress_url)
            before_audit_count = _wordpress_draft_audit_count(session, page_id)
            revisions_before = _revision_count(session, page_id)
            payload = {
                "draft": {
                    "intro": f"{page.draft_content['intro']} Atlas-only approved repair context.",
                    "internal_notes": "v0.31 approved repair verification.",
                },
                "repaired_by": "Atlas Repair Test",
                "reason": "Approved page Atlas-only repair test",
            }

        response = client.put(f"/api/generated-pages/{page_id}/approved-repair", json=payload)

        with Session(engine) as session:
            page = session.get(GeneratedPage, page_id)
            assert page is not None
            revisions = session.exec(
                select(GeneratedPageRevision)
                .where(GeneratedPageRevision.generated_page_id == page_id)
                .order_by(GeneratedPageRevision.id)
            ).all()
            after_refs = (page.wordpress_post_id, page.wordpress_status, page.wordpress_url)
            after_audit_count = _wordpress_draft_audit_count(session, page_id)
            repaired_draft = deepcopy(page.draft_content)
            repaired_status = page.status
            repaired_qa_status = page.qa_status
            manual_review = session.exec(
                select(WordPressQualityReview).where(
                    WordPressQualityReview.generated_page_id == page_id
                )
            ).first()
            new_revisions = revisions[revisions_before:]
            _restore_approved_repair_page(session, page, original, revisions=new_revisions)
            if manual_review:
                session.delete(manual_review)
                session.commit()

    assert response.status_code == 200
    body = response.json()
    assert repaired_status == "approved"
    assert repaired_qa_status == "ready"
    assert after_refs == before_refs
    assert after_audit_count == before_audit_count
    assert repaired_draft["intro"].endswith("Atlas-only approved repair context.")
    assert repaired_draft["internal_notes"] == "v0.31 approved repair verification."
    assert len(new_revisions) == 1
    assert set(new_revisions[0].changed_fields) == {"intro", "internal_notes"}
    assert body["page"]["status"] == "approved"
    assert body["qa_result"]["readiness_status"] == "ready"
    assert body["export_blocker_count"] == 0
    assert body["draft_hash_before"] != body["draft_hash_after"]
    assert body["payload_hash_before"] != body["payload_hash_after"]
    assert body["wordpress_post_id"] == 8001
    assert manual_review is not None
    assert manual_review.review_status == "needs_changes"
    assert "Atlas content repair completed" in (manual_review.reviewer_notes or "")
    assert manual_review.reviewed_by == "Atlas Repair Test"


def test_approved_repair_rejects_draft_page_without_revision() -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page = _ensure_complete_page(session, page)
            original = _approved_repair_page_state(page)
            page.status = "draft"
            page.wordpress_post_id = 8002
            page.wordpress_status = "draft"
            page.wordpress_url = "https://example.test/?page_id=8002"
            session.add(page)
            session.commit()
            page_id = page.id
            before_draft = deepcopy(page.draft_content)
            revisions_before = _revision_count(session, page_id)

        response = client.put(
            f"/api/generated-pages/{page_id}/approved-repair",
            json={
                "draft": {"intro": f"{before_draft['intro']} Should not save."},
                "repaired_by": "Atlas Repair Test",
            },
        )

        with Session(engine) as session:
            page = session.get(GeneratedPage, page_id)
            assert page is not None
            after_draft = deepcopy(page.draft_content)
            revisions_after = _revision_count(session, page_id)
            _restore_approved_repair_page(session, page, original)

    assert response.status_code == 409
    assert after_draft == before_draft
    assert revisions_after == revisions_before


def test_approved_repair_rejects_unsafe_wording_without_revision() -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page = _ensure_complete_page(session, page)
            original = _approved_repair_page_state(page)
            page.status = "approved"
            page.wordpress_post_id = 8003
            page.wordpress_status = "draft"
            page.wordpress_url = "https://example.test/?page_id=8003"
            session.add(page)
            session.commit()
            page_id = page.id
            before_draft = deepcopy(page.draft_content)
            revisions_before = _revision_count(session, page_id)

        response = client.put(
            f"/api/generated-pages/{page_id}/approved-repair",
            json={
                "draft": {"intro": f"{before_draft['intro']} This is 100% guaranteed."},
                "repaired_by": "Atlas Repair Test",
            },
        )

        with Session(engine) as session:
            page = session.get(GeneratedPage, page_id)
            assert page is not None
            after_draft = deepcopy(page.draft_content)
            revisions_after = _revision_count(session, page_id)
            _restore_approved_repair_page(session, page, original)

    assert response.status_code == 422
    assert "unsafe wording" in str(response.json()["detail"]).lower()
    assert after_draft == before_draft
    assert revisions_after == revisions_before


def test_qa_run_does_not_create_page_revision() -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page = _ensure_complete_page(session, page)
            page_id = page.id
            revisions_before = _revision_count(session, page_id)

        response = client.post(f"/api/generated-pages/{page_id}/qa/run")

        with Session(engine) as session:
            revisions_after = _revision_count(session, page_id)

    assert response.status_code == 200
    assert revisions_after == revisions_before


def test_save_draft_and_run_qa_creates_one_revision_and_saves_qa() -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page = _ensure_complete_page(session, page)
            original = _editor_page_state(page)
            payload = _manual_editor_payload(page)
            payload["draft"]["why_choose_section"] += " Updated after manual review."
            page_id = page.id

        response = client.put(
            f"/api/generated-pages/{page_id}/draft-and-qa",
            json=payload,
        )

        with Session(engine) as session:
            page = session.get(GeneratedPage, page_id)
            assert page is not None
            revisions = session.exec(
                select(GeneratedPageRevision).where(
                    GeneratedPageRevision.generated_page_id == page_id
                )
            ).all()
            qa_status = page.qa_status
            qa_result = deepcopy(page.qa_result)
            _restore_editor_page(session, page, original, revisions=revisions)

    assert response.status_code == 200
    assert len(revisions) == 1
    assert response.json()["qa_result"]["persisted"] is True
    assert qa_status == response.json()["qa_result"]["readiness_status"]
    assert qa_result["checks"]


def test_approval_audit_uses_latest_manually_edited_draft_hash() -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page = _ensure_complete_page(session, page)
            original = _editor_page_state(page)
            payload = _manual_editor_payload(page)
            payload["draft"]["call_to_action"] += " Ask about scheduling options."
            page_id = page.id

        save_response = client.put(
            f"/api/generated-pages/{page_id}/draft-and-qa",
            json=payload,
        )
        approve_response = client.post(
            f"/api/generated-pages/{page_id}/approve",
            json={"approved_by": "Editor Reviewer"},
        )

        with Session(engine) as session:
            page = session.get(GeneratedPage, page_id)
            assert page is not None
            revisions = session.exec(
                select(GeneratedPageRevision).where(
                    GeneratedPageRevision.generated_page_id == page_id
                )
            ).all()
            audits = session.exec(
                select(ApprovalAudit).where(ApprovalAudit.generated_page_id == page_id)
            ).all()
            latest_hash = draft_content_hash(page.draft_content)
            audit_hash = audits[0].draft_hash_at_approval
            _restore_editor_page(
                session,
                page,
                original,
                revisions=revisions,
                audits=audits,
            )

    assert save_response.status_code == 200
    assert approve_response.status_code == 200
    assert audit_hash == latest_hash


def test_backup_restore_preserves_page_revisions_idempotently(tmp_path: Path) -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page = _ensure_complete_page(session, page)
            original = _editor_page_state(page)
            payload = _manual_editor_payload(page)
            payload["draft"]["hero_subheadline"] += " Reviewed for backup."
            page_id = page.id

        save_response = client.put(f"/api/generated-pages/{page_id}/draft", json=payload)
        assert save_response.status_code == 200

        with Session(engine) as session:
            export = export_backup(session, backup_dir=tmp_path)
            payload_json = json.loads(Path(export["path"]).read_text(encoding="utf-8"))
            revisions = session.exec(
                select(GeneratedPageRevision).where(
                    GeneratedPageRevision.generated_page_id == page_id
                )
            ).all()
            for revision in revisions:
                session.delete(revision)
            session.commit()

            restore_backup(session, export["path"])
            restore_backup(session, export["path"])
            page = session.get(GeneratedPage, page_id)
            assert page is not None
            restored_revisions = session.exec(
                select(GeneratedPageRevision).where(
                    GeneratedPageRevision.generated_page_id == page_id
                )
            ).all()
            restored_after = deepcopy(restored_revisions[0].draft_content_after)
            _restore_editor_page(
                session,
                page,
                original,
                revisions=restored_revisions,
            )

    assert payload_json["metadata"]["version"] == "0.34"
    assert payload_json["data"]["page_revisions"]
    assert len(restored_revisions) == 1
    assert restored_after["hero_subheadline"].endswith("Reviewed for backup.")


def test_generated_page_read_does_not_embed_revision_history() -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page_id = page.id

        response = client.get(f"/api/generated-pages/{page_id}")

    assert response.status_code == 200
    assert "revisions" not in response.json()
    assert "revision_history" not in response.json()


def test_approval_gate_rejects_page_with_qa_blockers() -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page = _ensure_complete_page(session, page)
            original = deepcopy(page.draft_content)
            draft = deepcopy(page.draft_content or {})
            draft["call_to_action"] = ""
            page.draft_content = draft
            page.qa_status = "not_run"
            page.qa_result = None
            page.qa_checked_at = None
            session.add(page)
            session.commit()
            page_id = page.id
            status_before = page.status

        response = client.post(f"/api/generated-pages/{page_id}/approve")

        with Session(engine) as session:
            page = session.get(GeneratedPage, page_id)
            assert page is not None
            status_after = page.status
            page.draft_content = original
            page.qa_status = "not_run"
            page.qa_result = None
            page.qa_checked_at = None
            session.add(page)
            session.commit()

    assert response.status_code == 409
    assert status_after == status_before


def test_approval_queue_detects_ready_page() -> None:
    with TestClient(app):
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page = _ensure_complete_page(session, page)
            qa = evaluate_page_qa(session, page.id)
            assert qa.readiness_status == "ready"
            page.qa_status = qa.readiness_status
            page.qa_result = qa.model_dump(mode="json", exclude={"persisted"})
            page.qa_checked_at = qa.checked_at
            page.status = "draft"
            session.add(page)
            session.flush()

            item = _approval_queue_item(session, page.id)
            session.rollback()

    assert item.is_ready_for_approval is True
    assert item.has_blockers is False
    assert item.has_warnings is False
    assert item.next_recommended_action.startswith("Review the preview")


def test_approval_queue_detects_blocked_page() -> None:
    with TestClient(app):
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-deltona-fl")
            qa = evaluate_page_qa(session, page.id)
            page.qa_status = qa.readiness_status
            page.qa_result = qa.model_dump(mode="json", exclude={"persisted"})
            page.qa_checked_at = qa.checked_at
            session.add(page)
            session.flush()

            item = _approval_queue_item(session, page.id)
            session.rollback()

    assert item.has_blockers is True
    assert item.is_ready_for_approval is False
    assert item.needs_manual_review is True


def test_approval_queue_detects_warnings() -> None:
    with TestClient(app):
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page.qa_status = "needs_review"
            page.qa_result = {
                "warning_count": 1,
                "failed_count": 0,
                "checks": [{"status": "warning"}],
            }
            page.qa_checked_at = datetime.now(UTC)
            page.status = "draft"
            session.add(page)
            session.flush()

            item = _approval_queue_item(session, page.id)
            session.rollback()

    assert item.has_warnings is True
    assert item.has_blockers is False
    assert item.is_ready_for_approval is False


def test_approval_queue_detects_edit_after_last_qa() -> None:
    with TestClient(app):
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page.qa_status = "ready"
            page.qa_result = {"warning_count": 0, "failed_count": 0, "checks": []}
            page.qa_checked_at = datetime(2026, 1, 1, tzinfo=UTC)
            revision = GeneratedPageRevision(
                generated_page_id=page.id,
                created_at=datetime(2026, 1, 2, tzinfo=UTC),
                created_by="Queue test",
                draft_hash_before="before",
                draft_hash_after="after",
                draft_content_before=deepcopy(page.draft_content or {}),
                draft_content_after=deepcopy(page.draft_content or {}),
                changed_fields=["intro"],
            )
            session.add(page)
            session.add(revision)
            session.flush()

            item = _approval_queue_item(session, page.id)
            session.rollback()

    assert item.edited_since_last_qa is True
    assert item.is_ready_for_approval is False
    assert item.next_recommended_action == "Run QA again after the latest manual edit."


def test_approval_queue_detects_approved_but_unpublished() -> None:
    with TestClient(app):
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page.status = "approved"
            page.wordpress_url = None
            session.add(page)
            session.flush()

            item = _approval_queue_item(session, page.id)
            session.rollback()

    assert item.approved_but_unpublished is True
    assert item.is_ready_for_approval is False
    assert item.next_recommended_action.startswith("Hold for a future")


def test_approval_queue_detects_missing_media() -> None:
    with TestClient(app):
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-deltona-fl")
            item = _approval_queue_item(session, page.id)

    assert item.missing_media is True
    assert item.hero_image_status == "missing"
    assert item.is_ready_for_approval is False


def test_approval_queue_endpoint_is_read_only() -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            before = _approval_queue_database_snapshot(session)

        response = client.get("/api/generated-pages/approval-queue")

        with Session(engine) as session:
            after = _approval_queue_database_snapshot(session)

    assert response.status_code == 200
    assert response.json()["total_count"] == 55
    assert len(response.json()["items"]) == 55
    assert after == before


def test_wordpress_settings_default_to_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WORDPRESS_APPLICATION_PASSWORD", raising=False)
    wordpress_sandbox.clear_wordpress_application_password()
    with TestClient(app) as client:
        with Session(engine) as session:
            _clear_wordpress_settings(session)
        response = client.get("/api/wordpress/settings")

    assert response.status_code == 200
    assert response.json() == {
        "site_url": "",
        "username": "",
        "publishing_mode": "disabled",
        "has_application_password": False,
        "password_storage": "Process memory only. It is cleared when the backend restarts.",
    }


def test_wordpress_settings_save_without_exposing_or_persisting_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "atlas-local-application-password"
    monkeypatch.delenv("WORDPRESS_APPLICATION_PASSWORD", raising=False)
    wordpress_sandbox.clear_wordpress_application_password()
    with TestClient(app) as client:
        with Session(engine) as session:
            _clear_wordpress_settings(session)
        response = client.put(
            "/api/wordpress/settings",
            json={
                "site_url": "https://example.test/",
                "username": "atlas-editor",
                "application_password": secret,
                "publishing_mode": "sandbox",
            },
        )
        read_response = client.get("/api/wordpress/settings")
        with Session(engine) as session:
            stored = {
                setting.setting_key: setting.setting_value
                for setting in session.exec(
                    select(Setting).where(Setting.setting_key.startswith("wordpress_"))
                ).all()
            }
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 200
    assert read_response.status_code == 200
    assert response.json()["has_application_password"] is True
    assert read_response.json()["has_application_password"] is True
    assert secret not in response.text
    assert secret not in read_response.text
    assert stored == {
        "wordpress_site_url": "https://example.test",
        "wordpress_username": "atlas-editor",
        "wordpress_publishing_mode": "sandbox",
    }


def test_wordpress_connection_requires_process_memory_password_when_username_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WORDPRESS_APPLICATION_PASSWORD", raising=False)
    wordpress_sandbox.clear_wordpress_application_password()
    with TestClient(app) as client:
        with Session(engine) as session:
            _clear_wordpress_settings(session)
        save = client.put(
            "/api/wordpress/settings",
            json={
                "site_url": "https://wordpress.example",
                "username": "atlas",
                "publishing_mode": "sandbox",
            },
        )
        response = client.post("/api/wordpress/test-connection")
        with Session(engine) as session:
            _clear_wordpress_settings(session)

    assert save.status_code == 200
    assert save.json()["has_application_password"] is False
    assert response.status_code == 200
    assert response.json()["connection_status"] == "failed"
    assert response.json()["rest_api_reachable"] is False
    assert response.json()["authenticated"] is False
    assert response.json()["credentials_present"] is False
    assert "application password is not stored" in response.json()["error_message"]
    assert "Re-enter it after backend restart" in response.json()["error_message"]


def test_data_backup_and_restore_exclude_wordpress_secrets(tmp_path: Path) -> None:
    secret_key = "wordpress_application_password"
    secret_value = "must-never-enter-a-backup"
    with TestClient(app):
        with Session(engine) as session:
            _clear_wordpress_settings(session)
            session.add(Setting(setting_key=secret_key, setting_value=secret_value))
            session.commit()
            export = export_backup(session, backup_dir=tmp_path)
            payload = json.loads(Path(export["path"]).read_text(encoding="utf-8"))
            assert not any(
                record["setting_key"] == secret_key
                for record in payload["data"]["settings"]
            )

            secret = session.exec(
                select(Setting).where(Setting.setting_key == secret_key)
            ).one()
            session.delete(secret)
            session.commit()
            payload["data"]["settings"].append(
                {
                    "id": 999999,
                    "setting_key": secret_key,
                    "setting_value": secret_value,
                    "description": "Legacy secret that must be ignored.",
                    "created_at": datetime.now(UTC).isoformat(),
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            )
            payload["metadata"]["table_counts"]["settings"] += 1
            legacy_path = tmp_path / "atlas-backup-legacy-secret.json"
            legacy_path.write_text(json.dumps(payload), encoding="utf-8")
            restore_backup(session, legacy_path)
            restored = session.exec(
                select(Setting).where(Setting.setting_key == secret_key)
            ).first()
            _clear_wordpress_settings(session)

    assert secret_value not in json.dumps(payload["data"]["settings"][:-1])
    assert restored is None


def test_wordpress_connection_test_uses_get_requests_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[tuple[str, str, bool]] = []

    class FakeResponse:
        status_code = 200

        def json(self) -> dict[str, str]:
            return {"name": "Atlas WordPress Sandbox"}

    class FakeClient:
        def __init__(self, **_: object) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def get(self, url: str, *, auth: object | None = None) -> FakeResponse:
            requests.append(("GET", url, auth is not None))
            return FakeResponse()

    monkeypatch.setattr(wordpress_sandbox.httpx, "Client", FakeClient)
    wordpress_sandbox.clear_wordpress_application_password()
    with TestClient(app) as client:
        with Session(engine) as session:
            _clear_wordpress_settings(session)
        save = client.put(
            "/api/wordpress/settings",
            json={
                "site_url": "https://wordpress.example",
                "username": "atlas",
                "application_password": "local-only",
                "publishing_mode": "sandbox",
            },
        )
        response = client.post("/api/wordpress/test-connection")
        with Session(engine) as session:
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert save.status_code == 200
    assert response.status_code == 200
    assert response.json()["connection_status"] == "connected"
    assert response.json()["rest_api_reachable"] is True
    assert response.json()["authenticated"] is True
    assert response.json()["credentials_present"] is True
    assert response.json()["site_name"] == "Atlas WordPress Sandbox"
    assert [request[0] for request in requests] == ["GET", "GET"]
    assert requests[0][1].endswith("/wp-json/")
    assert requests[1][1].endswith("/wp-json/wp/v2/users/me?context=edit")
    assert requests[0][2] is False
    assert requests[1][2] is True


def test_wordpress_connection_reachable_without_auth_is_not_authenticated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[tuple[str, bool]] = []

    class FakeResponse:
        status_code = 200

        def json(self) -> dict[str, str]:
            return {"name": "Public REST"}

    class FakeClient:
        def __init__(self, **_: object) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def get(self, url: str, *, auth: object | None = None) -> FakeResponse:
            requests.append((url, auth is not None))
            return FakeResponse()

    monkeypatch.setattr(wordpress_sandbox.httpx, "Client", FakeClient)
    wordpress_sandbox.clear_wordpress_application_password()
    with TestClient(app) as client:
        with Session(engine) as session:
            _clear_wordpress_settings(session)
        save = client.put(
            "/api/wordpress/settings",
            json={
                "site_url": "https://wordpress.example",
                "username": "",
                "publishing_mode": "sandbox",
            },
        )
        response = client.post("/api/wordpress/test-connection")
        with Session(engine) as session:
            _clear_wordpress_settings(session)

    assert save.status_code == 200
    assert response.status_code == 200
    assert response.json()["connection_status"] == "connected"
    assert response.json()["rest_api_reachable"] is True
    assert response.json()["authenticated"] is False
    assert response.json()["credentials_present"] is False
    assert len(requests) == 1
    assert requests[0][0].endswith("/wp-json/")
    assert requests[0][1] is False


def test_wordpress_payload_preview_is_draft_and_read_only() -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page_id = page.id
            before = _approval_queue_database_snapshot(session)

        response = client.get(f"/api/wordpress/pages/{page_id}/payload-preview")

        with Session(engine) as session:
            after = _approval_queue_database_snapshot(session)

    assert response.status_code == 200
    payload = response.json()
    assert payload["sandbox_only"] is True
    assert payload["payload"]["status"] == "draft"
    assert payload["payload"]["title"] == payload["export_package"]["page_title"]
    assert payload["payload"]["slug"] == payload["export_package"]["url_slug"]
    assert payload["heading_contract"] == {
        "policy_id": "template_post_title_owns_primary_h1",
        "template_renders_primary_h1": True,
        "body_heading_level": 2,
    }
    assert payload["payload"]["content"].startswith(
        "<h2>Drywood Termite Tenting in Orlando, Florida</h2>"
    )
    assert payload["payload"]["schema_block_preview"]["@context"] == "https://schema.org"
    assert after == before


def test_wordpress_draft_review_list_includes_orlando_with_reference() -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            audit = _add_wordpress_draft_audit(session, page, status="created")
            audit_id = audit.id
            page_id = page.id
        response = client.get("/api/wordpress/draft-review")
        with Session(engine) as session:
            _restore_wordpress_page(
                session,
                session.get(GeneratedPage, page_id),
                original,
                audits=[session.get(WordPressDraftAudit, audit_id)],
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_count"] >= 1
    item = next(item for item in payload["items"] if item["page_id"] == page_id)
    assert item["city"] == "Orlando"
    assert item["wordpress_post_id"] == 712
    assert item["wordpress_status"] == "draft"
    assert item["successful_draft_audit_count"] == 1
    assert item["admin_edit_url"] == "https://wordpress.example/wp-admin/post.php?post=712&action=edit"
    assert "Draft Confirmed" in item["badges"]


def test_wordpress_draft_live_status_check_uses_get_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[tuple[str, str]] = []

    class FakeResponse:
        status_code = 200

        def json(self) -> dict:
            return {
                "id": 712,
                "status": "draft",
                "link": "https://wordpress.example/?page_id=712",
                "modified_gmt": "2026-07-07T04:48:40",
                "title": {"rendered": "Drywood Termite Tenting in Orlando, FL"},
                "slug": "drywood-termite-tenting-orlando-fl",
            }

    class FakeClient:
        def __init__(self, **_: object) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def get(self, url: str, *, auth: object | None = None) -> FakeResponse:
            requests.append(("GET", url))
            assert auth is not None
            return FakeResponse()

        def post(self, *_: object, **__: object) -> None:
            raise AssertionError("WordPress draft review must not POST")

        def put(self, *_: object, **__: object) -> None:
            raise AssertionError("WordPress draft review must not PUT")

        def patch(self, *_: object, **__: object) -> None:
            raise AssertionError("WordPress draft review must not PATCH")

        def delete(self, *_: object, **__: object) -> None:
            raise AssertionError("WordPress draft review must not DELETE")

    monkeypatch.setattr(wordpress_draft_review.httpx, "Client", FakeClient)
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            audit = _add_wordpress_draft_audit(session, page, status="created")
            audit_id = audit.id
            page_id = page.id
        response = client.get(f"/api/wordpress/draft-review/{page_id}/live-status")
        with Session(engine) as session:
            _restore_wordpress_page(
                session,
                session.get(GeneratedPage, page_id),
                original,
                audits=[session.get(WordPressDraftAudit, audit_id)],
            )
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 200
    payload = response.json()
    assert payload["wordpress_post_id"] == 712
    assert payload["wordpress_status"] == "draft"
    assert payload["is_still_draft"] is True
    assert payload["appears_published"] is False
    assert [item[0] for item in requests] == ["GET"]
    assert requests[0][1] == "https://wordpress.example/wp-json/wp/v2/pages/712?context=edit"


def test_wordpress_draft_review_comparison_detects_matching_payload_hash() -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            audit = _add_wordpress_draft_audit(session, page, status="created")
            audit_id = audit.id
            page_id = page.id
        response = client.get(f"/api/wordpress/draft-review/{page_id}")
        with Session(engine) as session:
            _restore_wordpress_page(
                session,
                session.get(GeneratedPage, page_id),
                original,
                audits=[session.get(WordPressDraftAudit, audit_id)],
            )

    assert response.status_code == 200
    comparison = response.json()["comparison"]
    assert comparison["audit_payload_hash"] == comparison["current_export_payload_hash"]
    assert comparison["atlas_export_differs_from_original"] is False


def test_wordpress_draft_review_comparison_detects_changed_atlas_export_hash() -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            audit = _add_wordpress_draft_audit(session, page, status="created")
            audit_id = audit.id
            draft = deepcopy(page.draft_content or {})
            draft["intro"] = f"{draft.get('intro', '')} Internal review changed this Atlas draft."
            page.draft_content = draft
            session.add(page)
            session.commit()
            page_id = page.id
        response = client.get(f"/api/wordpress/draft-review/{page_id}")
        with Session(engine) as session:
            _restore_wordpress_page(
                session,
                session.get(GeneratedPage, page_id),
                original,
                audits=[session.get(WordPressDraftAudit, audit_id)],
            )

    assert response.status_code == 200
    comparison = response.json()["comparison"]
    assert comparison["audit_payload_hash"] != comparison["current_export_payload_hash"]
    assert comparison["atlas_export_differs_from_original"] is True
    assert "Atlas content has changed" in comparison["message"]


def test_wordpress_draft_review_admin_edit_link_is_generated_safely() -> None:
    with TestClient(app):
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            audit = _add_wordpress_draft_audit(session, page, status="created")
            item = next(
                item
                for item in wordpress_draft_review.list_wordpress_draft_reviews(session).items
                if item.page_id == page.id
            )
            _restore_wordpress_page(
                session,
                page,
                original,
                audits=[audit],
            )

    assert item.admin_edit_url == "https://wordpress.example/wp-admin/post.php?post=712&action=edit"
    assert item.admin_edit_url.startswith("https://")
    assert "password" not in item.admin_edit_url.lower()


def test_wordpress_draft_quality_review_returns_manual_checklist() -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            audit = _add_wordpress_draft_audit(session, page, status="created")
            audit_id = audit.id
            page_id = page.id
        response = client.get(f"/api/wordpress/draft-quality-review/{page_id}")
        with Session(engine) as session:
            _restore_wordpress_page(
                session,
                session.get(GeneratedPage, page_id),
                original,
                audits=[session.get(WordPressDraftAudit, audit_id)],
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["city"] == "Orlando"
    assert payload["wordpress_post_id"] == 712
    assert payload["wordpress_status"] == "draft"
    assert payload["payload_hash_matches_audit"] is True
    assert payload["overall_publish_readiness"] == "needs_review"
    checks = {item["key"]: item for item in payload["checklist"]}
    assert checks["wordpress_draft_exists"]["status"] == "pass"
    assert checks["wordpress_status_draft"]["status"] == "pass"
    assert checks["manual_wordpress_visual_review_needed"]["status"] == "warning"
    assert checks["reviewer_notes"]["status"] == "warning"
    assert payload["safe_for_future_manual_review"] is True


def test_wordpress_draft_quality_review_endpoint_is_read_only() -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            audit = _add_wordpress_draft_audit(session, page, status="created")
            audit_id = audit.id
            page_id = page.id
            before_page = _wordpress_page_state(page)
            before_audit_count = len(session.exec(select(WordPressDraftAudit)).all())
            before_media_count = len(session.exec(select(ImageMetadata)).all())
        response = client.get("/api/wordpress/draft-quality-review")
        with Session(engine) as session:
            page = session.get(GeneratedPage, page_id)
            after_page = _wordpress_page_state(page)
            after_audit_count = len(session.exec(select(WordPressDraftAudit)).all())
            after_media_count = len(session.exec(select(ImageMetadata)).all())
            _restore_wordpress_page(
                session,
                page,
                original,
                audits=[session.get(WordPressDraftAudit, audit_id)],
            )

    assert response.status_code == 200
    assert after_page == before_page
    assert after_audit_count == before_audit_count
    assert after_media_count == before_media_count


def test_wordpress_quality_manual_review_can_be_saved_and_reloaded() -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            audit = _add_wordpress_draft_audit(session, page, status="created")
            audit_id = audit.id
            page_id = page.id
        response = client.patch(
            f"/api/wordpress/draft-quality-review/{page_id}/manual-review",
            json={
                "review_status": "needs_changes",
                "reviewer_notes": "  Needs visual spacing review.  ",
                "reviewed_by": "  Jordan  ",
            },
        )
        reload_response = client.get(f"/api/wordpress/draft-quality-review/{page_id}")
        with Session(engine) as session:
            saved = session.exec(
                select(WordPressQualityReview).where(
                    WordPressQualityReview.generated_page_id == page_id
                )
            ).first()
            if saved:
                session.delete(saved)
                session.commit()
            _restore_wordpress_page(
                session,
                session.get(GeneratedPage, page_id),
                original,
                audits=[session.get(WordPressDraftAudit, audit_id)],
            )

    assert response.status_code == 200
    manual = response.json()["manual_review"]
    assert manual["review_status"] == "needs_changes"
    assert manual["reviewer_notes"] == "Needs visual spacing review."
    assert manual["reviewed_by"] == "Jordan"
    assert manual["reviewed_at"]
    assert reload_response.json()["manual_review"] == manual


def test_wordpress_quality_manual_review_rejects_invalid_status() -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            audit = _add_wordpress_draft_audit(session, page, status="created")
            audit_id = audit.id
            page_id = page.id
        response = client.patch(
            f"/api/wordpress/draft-quality-review/{page_id}/manual-review",
            json={
                "review_status": "published",
                "reviewer_notes": "Not a valid manual review status.",
            },
        )
        with Session(engine) as session:
            saved = session.exec(
                select(WordPressQualityReview).where(
                    WordPressQualityReview.generated_page_id == page_id
                )
            ).first()
            _restore_wordpress_page(
                session,
                session.get(GeneratedPage, page_id),
                original,
                audits=[session.get(WordPressDraftAudit, audit_id)],
            )

    assert response.status_code == 422
    assert saved is None


def test_wordpress_quality_manual_review_save_only_changes_review_record() -> None:
    with TestClient(app) as client:
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            audit = _add_wordpress_draft_audit(session, page, status="created")
            audit_id = audit.id
            page_id = page.id
            before_page = _wordpress_page_state(page)
            before_audit_count = len(session.exec(select(WordPressDraftAudit)).all())
            before_media_count = len(session.exec(select(ImageMetadata)).all())
            before_approval_count = len(session.exec(select(ApprovalAudit)).all())
        response = client.patch(
            f"/api/wordpress/draft-quality-review/{page_id}/manual-review",
            json={
                "review_status": "in_review",
                "reviewer_notes": "Manual review started.",
            },
        )
        with Session(engine) as session:
            page = session.get(GeneratedPage, page_id)
            after_page = _wordpress_page_state(page)
            after_audit_count = len(session.exec(select(WordPressDraftAudit)).all())
            after_media_count = len(session.exec(select(ImageMetadata)).all())
            after_approval_count = len(session.exec(select(ApprovalAudit)).all())
            saved = session.exec(
                select(WordPressQualityReview).where(
                    WordPressQualityReview.generated_page_id == page_id
                )
            ).first()
            if saved:
                session.delete(saved)
                session.commit()
            _restore_wordpress_page(
                session,
                page,
                original,
                audits=[session.get(WordPressDraftAudit, audit_id)],
            )

    assert response.status_code == 200
    assert after_page == before_page
    assert after_audit_count == before_audit_count
    assert after_media_count == before_media_count
    assert after_approval_count == before_approval_count


def test_backup_restore_preserves_wordpress_quality_review_idempotently(tmp_path: Path) -> None:
    with Session(engine) as session:
        page, original = _prepare_wordpress_draft_page(session)
        audit = _add_wordpress_draft_audit(session, page, status="created")
        audit_id = audit.id
        page_id = page.id
        review = WordPressQualityReview(
            generated_page_id=page_id,
            review_status="ready_for_manual_publish_review",
            reviewer_notes="Ready after manual review.",
            reviewed_by="Jordan",
            reviewed_at=datetime.now(UTC),
        )
        session.add(review)
        session.commit()
        result = export_backup(session, backup_dir=tmp_path)
        backup_payload = json.loads((tmp_path / result["file_name"]).read_text(encoding="utf-8"))
        review_count = len(backup_payload["data"]["wordpress_quality_reviews"])
        session.delete(review)
        session.commit()
        restore_backup(session, tmp_path / result["file_name"])
        restore_backup(session, tmp_path / result["file_name"])
        restored = session.exec(
            select(WordPressQualityReview).where(
                WordPressQualityReview.generated_page_id == page_id
            )
        ).all()
        restored_review = restored[0]
        session.delete(restored_review)
        session.commit()
        _restore_wordpress_page(
            session,
            session.get(GeneratedPage, page_id),
            original,
            audits=[session.get(WordPressDraftAudit, audit_id)],
        )

    assert review_count >= 1
    assert len(restored) == 1
    assert restored_review.review_status == "ready_for_manual_publish_review"
    assert restored_review.reviewer_notes == "Ready after manual review."


def test_old_backup_without_wordpress_quality_reviews_still_restores(tmp_path: Path) -> None:
    with Session(engine) as session:
        result = export_backup(session, backup_dir=tmp_path)
    backup_path = tmp_path / result["file_name"]
    payload = json.loads(backup_path.read_text(encoding="utf-8"))
    payload["metadata"]["version"] = "0.17"
    payload["metadata"]["table_counts"].pop("wordpress_quality_reviews", None)
    payload["data"].pop("wordpress_quality_reviews", None)
    backup_path.write_text(json.dumps(payload), encoding="utf-8")

    with Session(engine) as session:
        result = restore_backup(session, backup_path)

    assert result["status"] == "restored"
    assert result["table_counts"]["wordpress_quality_reviews"] == 0


def test_wordpress_draft_queue_lists_orlando_as_already_has_draft() -> None:
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            audit = _add_wordpress_draft_audit(session, page, status="created")
            page_id = page.id

        response = client.get("/api/wordpress/draft-queue")

        with Session(engine) as session:
            _restore_wordpress_page(
                session,
                session.get(GeneratedPage, page_id),
                original,
                audits=[session.get(WordPressDraftAudit, audit.id)],
            )
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 200
    item = next(item for item in response.json()["items"] if item["page_id"] == page_id)
    assert item["queue_group"] == "already_has_draft"
    assert item["eligible"] is False
    assert item["wordpress_post_id"] == 712


def test_wordpress_draft_queue_identifies_eligible_approved_ready_page() -> None:
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            page_id = page.id

        response = client.get("/api/wordpress/draft-queue")

        with Session(engine) as session:
            _restore_wordpress_page(session, session.get(GeneratedPage, page_id), original)
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 200
    item = next(item for item in response.json()["items"] if item["page_id"] == page_id)
    assert item["queue_group"] == "eligible"
    assert item["eligible"] is True
    assert item["payload_status"] == "draft"


def test_wordpress_draft_queue_blocks_unapproved_pages() -> None:
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            page.status = "draft"
            session.add(page)
            session.commit()
            page_id = page.id

        response = client.get("/api/wordpress/draft-queue")

        with Session(engine) as session:
            _restore_wordpress_page(session, session.get(GeneratedPage, page_id), original)
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 200
    item = next(item for item in response.json()["items"] if item["page_id"] == page_id)
    assert item["queue_group"] == "blocked_approval"
    assert item["eligible"] is False


def test_wordpress_draft_queue_blocks_stale_qa_after_edits() -> None:
    qa_time = datetime(2026, 7, 12, 12, 0, 0, tzinfo=UTC)
    revision_time = qa_time + timedelta(seconds=1)
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            page.qa_checked_at = qa_time
            session.add(page)
            revision = GeneratedPageRevision(
                generated_page_id=page.id,
                created_at=revision_time,
                draft_hash_before="before",
                draft_hash_after="after",
                draft_content_before=page.draft_content,
                draft_content_after=page.draft_content,
                changed_fields=["intro"],
            )
            session.add(revision)
            session.commit()
            page_id = page.id
            revision_id = revision.id

        response = client.get("/api/wordpress/draft-queue")

        with Session(engine) as session:
            revision = session.get(GeneratedPageRevision, revision_id)
            if revision:
                session.delete(revision)
                session.commit()
            _restore_wordpress_page(session, session.get(GeneratedPage, page_id), original)
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 200
    item = next(item for item in response.json()["items"] if item["page_id"] == page_id)
    assert item["queue_group"] == "blocked_stale_qa"
    assert datetime.fromisoformat(item["latest_revision_at"]).replace(tzinfo=UTC) > datetime.fromisoformat(item["qa_checked_at"]).replace(tzinfo=UTC)
    assert item["eligible"] is False


@pytest.mark.parametrize(
    ("revision_offset", "expected_group"),
    [(-1, "eligible"), (0, "eligible"), (1, "blocked_stale_qa")],
    ids=["revision-before-qa", "revision-equal-qa", "revision-after-qa"],
)
def test_wordpress_draft_queue_qa_revision_timestamp_boundaries(revision_offset: int, expected_group: str) -> None:
    qa_time = datetime(2026, 7, 12, 13, 0, 0, 123456, tzinfo=UTC)
    revision_time = qa_time + timedelta(seconds=revision_offset)
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            page.qa_checked_at = qa_time
            session.add(page)
            revision = GeneratedPageRevision(generated_page_id=page.id, created_at=revision_time,
                draft_hash_before="before", draft_hash_after=f"after-{revision_offset}",
                draft_content_before=page.draft_content, draft_content_after=page.draft_content, changed_fields=["intro"])
            session.add(revision); session.commit(); page_id, revision_id = page.id, revision.id
        response = client.get("/api/wordpress/draft-queue")
        with Session(engine) as session:
            persisted_page = session.get(GeneratedPage, page_id); persisted_revision = session.get(GeneratedPageRevision, revision_id)
            assert persisted_page.qa_checked_at.tzinfo is None and persisted_revision.created_at.tzinfo is None
            session.delete(persisted_revision); _restore_wordpress_page(session, persisted_page, original); _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()
    item = next(item for item in response.json()["items"] if item["page_id"] == page_id)
    assert item["queue_group"] == expected_group
    assert item["eligible"] is (expected_group == "eligible")


def test_wordpress_draft_queue_blocks_missing_credentials() -> None:
    wordpress_sandbox.clear_wordpress_application_password()
    with TestClient(app) as client:
        with Session(engine) as session:
            _clear_wordpress_settings(session)
        client.put(
            "/api/wordpress/settings",
            json={
                "site_url": "https://wordpress.example",
                "username": "atlas",
                "publishing_mode": "sandbox",
            },
        )
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            page_id = page.id

        response = client.get("/api/wordpress/draft-queue")

        with Session(engine) as session:
            _restore_wordpress_page(session, session.get(GeneratedPage, page_id), original)
            _clear_wordpress_settings(session)

    assert response.status_code == 200
    item = next(item for item in response.json()["items"] if item["page_id"] == page_id)
    assert response.json()["has_application_password"] is False
    assert item["queue_group"] == "blocked_credentials"
    assert item["eligible"] is False


def test_wordpress_draft_queue_endpoint_is_read_only() -> None:
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            page_id = page.id
            before = _approval_queue_database_snapshot(session)
            before_page = _wordpress_page_state(page)

        response = client.get("/api/wordpress/draft-queue")

        with Session(engine) as session:
            page = session.get(GeneratedPage, page_id)
            after = _approval_queue_database_snapshot(session)
            after_page = _wordpress_page_state(page)
            _restore_wordpress_page(session, page, original)
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 200
    assert after == before
    assert after_page == before_page


def test_wordpress_api_exposes_only_controlled_publish_and_existing_write_routes() -> None:
    wordpress_routes = [
        (route.path, method)
        for route in app.routes
        if route.path.startswith("/api/wordpress")
        for method in (route.methods or set())
    ]
    write_routes = {
        item
        for item in wordpress_routes
        if item[1] in {"POST", "PUT", "PATCH", "DELETE"}
    }

    assert write_routes == {
        ("/api/wordpress/settings", "PUT"),
        ("/api/wordpress/test-connection", "POST"),
        ("/api/wordpress/draft-quality-review/{page_id}/manual-review", "PATCH"),
        ("/api/wordpress/draft/dry-run/{page_id}", "POST"),
        ("/api/wordpress/draft/create/{page_id}", "POST"),
        ("/api/wordpress/draft-update/dry-run/{page_id}", "POST"),
        ("/api/wordpress/draft-update/apply/{page_id}", "POST"),
        ("/api/wordpress/publish/dry-run/{page_id}", "POST"),
        ("/api/wordpress/publish/apply/{page_id}", "POST"),
        ("/api/wordpress/media/dry-run/{page_id}", "POST"),
        ("/api/wordpress/media/upload/{page_id}", "POST"),
        ("/api/wordpress/media/reconciliation/dry-run/{page_id}", "POST"),
        ("/api/wordpress/media/reconciliation/apply/{page_id}", "POST"),
        ("/api/wordpress/media/featured-image/dry-run/{page_id}", "POST"),
        ("/api/wordpress/media/featured-image/apply/{page_id}", "POST"),
        ("/api/wordpress/media/featured-image/verify/{page_id}", "POST"),
        ("/api/wordpress/metadata/dry-run/{page_id}", "POST"),
        ("/api/wordpress/metadata/apply/{page_id}", "POST"),
        ("/api/wordpress/metadata/verify/{page_id}", "POST"),
        ("/api/wordpress/metadata/reconciliation/dry-run/{page_id}", "POST"),
        ("/api/wordpress/metadata/reconciliation/apply/{page_id}", "POST"),
            ("/api/wordpress/metadata/rollback/dry-run/{page_id}", "POST"),
            ("/api/wordpress/metadata/rollback/apply/{page_id}", "POST"),
            ("/api/wordpress/metadata/staging/preflight/{page_id}", "POST"),
            ("/api/wordpress/metadata/staging/apply/{page_id}", "POST"),
            ("/api/wordpress/metadata/rendering/preflight/{page_id}", "POST"),
            ("/api/wordpress/metadata/rendering/apply/{page_id}", "POST"),
            ("/api/wordpress/metadata/rendering/disable/preflight/{page_id}", "POST"),
            ("/api/wordpress/metadata/rendering/disable/apply/{page_id}", "POST"),
            ("/api/wordpress/metadata/staging/rollback/preflight/{page_id}", "POST"),
            ("/api/wordpress/metadata/staging/rollback/apply/{page_id}", "POST"),
            ("/api/wordpress/deployment/metadata-bridge/install/preflight/{page_id}", "POST"),
            ("/api/wordpress/deployment/metadata-bridge/install/dry-run/{page_id}", "POST"),
        ("/api/wordpress/deployment/metadata-bridge/install/authorize/{page_id}", "POST"),
        ("/api/wordpress/deployment/metadata-bridge/install/report-manual-complete/{page_id}", "POST"),
            ("/api/wordpress/deployment/metadata-bridge/install/verify/{page_id}", "POST"),
            ("/api/wordpress/deployment/metadata-bridge/install/reconciliation/verify/{page_id}", "POST"),
                ("/api/wordpress/deployment/metadata-bridge/install/reconciliation/apply/{page_id}", "POST"),
                ("/api/wordpress/deployment/metadata-bridge/activation/preflight/{page_id}", "POST"),
                ("/api/wordpress/deployment/metadata-bridge/activation/apply/{page_id}", "POST"),
            ("/api/wordpress/heading-correction/dry-run/{page_id}", "POST"),
            ("/api/wordpress/heading-correction/apply/{page_id}", "POST"),
            ("/api/wordpress/heading-correction/verify/{page_id}", "POST"),
            ("/api/wordpress/heading-correction/reconcile/{page_id}", "POST"),
        }
    assert not any(
        forbidden in path.lower()
        for path, _ in wordpress_routes
        for forbidden in ("delete", "bulk")
    )
    assert not any(
        path.lower().startswith("/api/wordpress/draft-update/")
        and not (
            path.lower().endswith("/dry-run/{page_id}")
            or path.lower().endswith("/apply/{page_id}")
        )
        for path, _ in wordpress_routes
    )
    assert not any(
        path.lower().startswith("/api/wordpress/publish/")
        and not (
            path.lower().endswith("/dry-run/{page_id}")
            or path.lower().endswith("/apply/{page_id}")
        )
        for path, _ in wordpress_routes
    )


def test_wordpress_dry_run_blocked_when_mode_disabled() -> None:
    wordpress_sandbox.clear_wordpress_application_password()
    with TestClient(app) as client:
        with Session(engine) as session:
            _clear_wordpress_settings(session)
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            page_id = page.id
        response = client.post(f"/api/wordpress/draft/dry-run/{page_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "blocked"
    assert _gate_response(response.json(), "sandbox_mode")["passed"] is False
    assert response.json()["confirmation_token"] is None


def test_wordpress_dry_run_blocked_when_page_not_approved() -> None:
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            original = _wordpress_page_state(page)
            page.status = "draft"
            page.qa_status = "ready"
            page.qa_checked_at = datetime.now(UTC)
            session.add(page)
            session.commit()
            page_id = page.id
        response = client.post(f"/api/wordpress/draft/dry-run/{page_id}")
        with Session(engine) as session:
            _restore_wordpress_page(session, session.get(GeneratedPage, page_id), original)
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 200
    assert _gate_response(response.json(), "page_approved")["passed"] is False


def test_wordpress_dry_run_blocked_when_qa_not_ready() -> None:
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            original = _wordpress_page_state(page)
            page.status = "approved"
            page.qa_status = "blocked"
            page.qa_checked_at = datetime.now(UTC)
            session.add(page)
            session.commit()
            page_id = page.id
        response = client.post(f"/api/wordpress/draft/dry-run/{page_id}")
        with Session(engine) as session:
            _restore_wordpress_page(session, session.get(GeneratedPage, page_id), original)
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 200
    assert _gate_response(response.json(), "qa_ready")["passed"] is False


def test_wordpress_dry_run_blocked_when_qa_is_stale_after_revision() -> None:
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            page.qa_checked_at = datetime(2026, 1, 1, tzinfo=UTC)
            revision = GeneratedPageRevision(
                generated_page_id=page.id,
                created_at=datetime(2026, 1, 2, tzinfo=UTC),
                draft_hash_before="before-stale",
                draft_hash_after="after-stale",
                draft_content_before=deepcopy(page.draft_content or {}),
                draft_content_after=deepcopy(page.draft_content or {}),
                changed_fields=["intro"],
            )
            session.add(page)
            session.add(revision)
            session.commit()
            page_id = page.id
        response = client.post(f"/api/wordpress/draft/dry-run/{page_id}")
        with Session(engine) as session:
            revisions = session.exec(
                select(GeneratedPageRevision).where(
                    GeneratedPageRevision.generated_page_id == page_id,
                    GeneratedPageRevision.draft_hash_after == "after-stale",
                )
            ).all()
            _restore_wordpress_page(
                session,
                session.get(GeneratedPage, page_id),
                original,
                revisions=revisions,
            )
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 200
    assert _gate_response(response.json(), "qa_current")["passed"] is False


def test_wordpress_dry_run_detects_slug_conflict() -> None:
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            other = _page_by_slug(session, "drywood-termite-tenting-deltona-fl")
            other_slug = other.page_slug
            page.page_slug = "orlando-temporary-for-conflict-test"
            session.add(page)
            session.commit()
            other.page_slug = "drywood-termite-tenting-orlando-fl"
            session.add(other)
            session.commit()
            page_id = page.id
        response = client.post(f"/api/wordpress/draft/dry-run/{page_id}")
        with Session(engine) as session:
            page = session.get(GeneratedPage, page_id)
            other = session.exec(
                select(GeneratedPage).where(
                    GeneratedPage.page_slug == "drywood-termite-tenting-orlando-fl"
                )
            ).one()
            other.page_slug = other_slug
            session.add(other)
            session.commit()
            _restore_wordpress_page(session, page, original)
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 200
    assert _gate_response(response.json(), "slug_unique")["passed"] is False


def test_wordpress_dry_run_is_read_only() -> None:
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            page_id = page.id
            before = _approval_queue_database_snapshot(session)
        response = client.post(f"/api/wordpress/draft/dry-run/{page_id}")
        with Session(engine) as session:
            after = _approval_queue_database_snapshot(session)
            _restore_wordpress_page(session, session.get(GeneratedPage, page_id), original)
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 200
    assert response.json()["status"] == "dry_run_ready"
    assert response.json()["payload"]["status"] == "draft"
    assert response.json()["confirmation_token"]
    assert response.json()["confirmation_phrase"]
    assert after == before


def test_wordpress_dry_run_uses_saved_process_memory_password() -> None:
    wordpress_sandbox.clear_wordpress_application_password()
    with TestClient(app) as client:
        save = _configure_wordpress_sandbox(client)
        settings = client.get("/api/wordpress/settings")
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            page_id = page.id
        response = client.post(f"/api/wordpress/draft/dry-run/{page_id}")
        with Session(engine) as session:
            _restore_wordpress_page(session, session.get(GeneratedPage, page_id), original)
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert save.status_code == 200
    assert save.json()["has_application_password"] is True
    assert settings.json()["has_application_password"] is True
    assert response.status_code == 200
    assert response.json()["status"] == "dry_run_ready"
    assert _gate_response(response.json(), "credentials_ready")["passed"] is True
    assert response.json()["confirmation_token"]
    assert response.json()["confirmation_phrase"] == "CREATE WORDPRESS DRAFT drywood-termite-tenting-orlando-fl"


def test_wordpress_update_dry_run_blocks_missing_credentials() -> None:
    wordpress_sandbox.clear_wordpress_application_password()
    with TestClient(app) as client:
        with Session(engine) as session:
            _clear_wordpress_settings(session)
            page, original = _prepare_wordpress_draft_page(session)
            audit = _add_wordpress_draft_audit(session, page, status="created")
            page_id = page.id
        response = client.post(f"/api/wordpress/draft-update/dry-run/{page_id}")
        with Session(engine) as session:
            _restore_wordpress_page(
                session,
                session.get(GeneratedPage, page_id),
                original,
                audits=[audit],
            )
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 200
    assert response.json()["status"] == "blocked"
    assert _gate_response(response.json(), "credentials_ready")["passed"] is False
    assert response.json()["confirmation_token"] is None


def test_wordpress_update_dry_run_blocks_non_approved_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wordpress_draft_review.httpx, "Client", _fake_wordpress_get_client(status="draft"))
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            audit = _add_wordpress_draft_audit(session, page, status="created")
            page.status = "draft"
            session.add(page)
            session.commit()
            page_id = page.id
        response = client.post(f"/api/wordpress/draft-update/dry-run/{page_id}")
        with Session(engine) as session:
            _restore_wordpress_page(
                session,
                session.get(GeneratedPage, page_id),
                original,
                audits=[audit],
            )
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 200
    assert _gate_response(response.json(), "page_approved")["passed"] is False
    assert response.json()["status"] == "blocked"


def test_wordpress_update_dry_run_blocks_stale_qa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wordpress_draft_review.httpx, "Client", _fake_wordpress_get_client(status="draft"))
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            audit = _add_wordpress_draft_audit(session, page, status="created")
            page.qa_checked_at = datetime(2026, 1, 1, tzinfo=UTC)
            revision = GeneratedPageRevision(
                generated_page_id=page.id,
                created_at=datetime(2026, 1, 2, tzinfo=UTC),
                draft_hash_before="update-before-stale",
                draft_hash_after="update-after-stale",
                draft_content_before=deepcopy(page.draft_content or {}),
                draft_content_after=deepcopy(page.draft_content or {}),
                changed_fields=["intro"],
            )
            session.add(page)
            session.add(revision)
            session.commit()
            page_id = page.id
        response = client.post(f"/api/wordpress/draft-update/dry-run/{page_id}")
        with Session(engine) as session:
            revisions = session.exec(
                select(GeneratedPageRevision).where(
                    GeneratedPageRevision.generated_page_id == page_id,
                    GeneratedPageRevision.draft_hash_after == "update-after-stale",
                )
            ).all()
            _restore_wordpress_page(
                session,
                session.get(GeneratedPage, page_id),
                original,
                revisions=revisions,
                audits=[audit],
            )
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 200
    assert _gate_response(response.json(), "qa_current")["passed"] is False
    assert response.json()["status"] == "blocked"


def test_wordpress_update_dry_run_blocks_missing_wp_ref() -> None:
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            page_id = page.id
        response = client.post(f"/api/wordpress/draft-update/dry-run/{page_id}")
        with Session(engine) as session:
            _restore_wordpress_page(session, session.get(GeneratedPage, page_id), original)
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 200
    assert _gate_response(response.json(), "has_wordpress_ref")["passed"] is False
    assert response.json()["status"] == "blocked"


def test_wordpress_update_dry_run_blocks_live_status_not_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wordpress_draft_review.httpx, "Client", _fake_wordpress_get_client(status="publish"))
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            audit = _add_wordpress_draft_audit(session, page, status="created")
            page_id = page.id
        response = client.post(f"/api/wordpress/draft-update/dry-run/{page_id}")
        with Session(engine) as session:
            _restore_wordpress_page(
                session,
                session.get(GeneratedPage, page_id),
                original,
                audits=[audit],
            )
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 200
    assert _gate_response(response.json(), "live_wordpress_status_draft")["passed"] is False
    assert response.json()["live_status"]["appears_published"] is True
    assert response.json()["confirmation_token"] is None


def test_wordpress_update_dry_run_is_read_only_and_returns_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wordpress_draft_review.httpx, "Client", _fake_wordpress_get_client(status="draft"))
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            audit = _add_wordpress_draft_audit(session, page, status="created")
            page_id = page.id
            before = _approval_queue_database_snapshot(session)
        response = client.post(f"/api/wordpress/draft-update/dry-run/{page_id}")
        with Session(engine) as session:
            after = _approval_queue_database_snapshot(session)
            _restore_wordpress_page(
                session,
                session.get(GeneratedPage, page_id),
                original,
                audits=[audit],
            )
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "dry_run_ready"
    assert body["payload"]["status"] == "draft"
    assert body["comparison"]["original_payload_hash"]
    assert body["comparison"]["current_payload_hash"]
    assert body["comparison"]["media_reference_warning"]
    assert body["confirmation_phrase"].startswith("UPDATE WORDPRESS DRAFT ")
    assert body["confirmation_token"]
    assert after == before


def test_wordpress_update_apply_requires_valid_confirmation_without_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wordpress_draft_review.httpx, "Client", _fake_wordpress_get_client(status="draft"))
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            audit = _add_wordpress_draft_audit(session, page, status="created")
            page_id = page.id
            audit_count_before = len(session.exec(select(WordPressDraftAudit)).all())
        response = client.post(
            f"/api/wordpress/draft-update/apply/{page_id}",
            json={"confirmation_token": "invalid", "confirmation_phrase": "invalid"},
        )
        with Session(engine) as session:
            audit_count_after = len(session.exec(select(WordPressDraftAudit)).all())
            _restore_wordpress_page(
                session,
                session.get(GeneratedPage, page_id),
                original,
                audits=[audit],
            )
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 422
    assert audit_count_after == audit_count_before


def test_wordpress_update_apply_blocks_expired_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wordpress_draft_review.httpx, "Client", _fake_wordpress_get_client(status="draft"))
    monkeypatch.setattr(wordpress_draft_update, "TOKEN_TTL_MINUTES", -1)
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            audit = _add_wordpress_draft_audit(session, page, status="created")
            page_id = page.id
        dry_run = client.post(f"/api/wordpress/draft-update/dry-run/{page_id}").json()
        response = client.post(
            f"/api/wordpress/draft-update/apply/{page_id}",
            json={
                "confirmation_token": dry_run["confirmation_token"],
                "confirmation_phrase": dry_run["confirmation_phrase"],
            },
        )
        with Session(engine) as session:
            update_audits = session.exec(
                select(WordPressDraftAudit).where(
                    WordPressDraftAudit.generated_page_id == page_id,
                    WordPressDraftAudit.action_type == "update_draft",
                )
            ).all()
            _restore_wordpress_page(
                session,
                session.get(GeneratedPage, page_id),
                original,
                audits=[audit, *update_audits],
            )
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 409
    assert response.json()["detail"] == "The dry-run confirmation token expired."
    assert update_audits == []


def test_wordpress_update_apply_blocks_wrong_confirmation_phrase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wordpress_draft_review.httpx, "Client", _fake_wordpress_get_client(status="draft"))
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            audit = _add_wordpress_draft_audit(session, page, status="created")
            page_id = page.id
        dry_run = client.post(f"/api/wordpress/draft-update/dry-run/{page_id}").json()
        response = client.post(
            f"/api/wordpress/draft-update/apply/{page_id}",
            json={
                "confirmation_token": dry_run["confirmation_token"],
                "confirmation_phrase": "UPDATE WORDPRESS DRAFT wrong-slug",
            },
        )
        with Session(engine) as session:
            update_audits = session.exec(
                select(WordPressDraftAudit).where(
                    WordPressDraftAudit.generated_page_id == page_id,
                    WordPressDraftAudit.action_type == "update_draft",
                )
            ).all()
            _restore_wordpress_page(
                session,
                session.get(GeneratedPage, page_id),
                original,
                audits=[audit, *update_audits],
            )
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 422
    assert update_audits == []


def test_wordpress_update_apply_reruns_gates_and_records_blocked_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wordpress_draft_review.httpx, "Client", _fake_wordpress_get_client(status="draft"))
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            audit = _add_wordpress_draft_audit(session, page, status="created")
            page_id = page.id
        dry_run = client.post(f"/api/wordpress/draft-update/dry-run/{page_id}").json()
        with Session(engine) as session:
            page = session.get(GeneratedPage, page_id)
            page.qa_status = "blocked"
            session.add(page)
            session.commit()
        response = client.post(
            f"/api/wordpress/draft-update/apply/{page_id}",
            json={
                "confirmation_token": dry_run["confirmation_token"],
                "confirmation_phrase": dry_run["confirmation_phrase"],
            },
        )
        with Session(engine) as session:
            update_audits = session.exec(
                select(WordPressDraftAudit).where(
                    WordPressDraftAudit.generated_page_id == page_id,
                    WordPressDraftAudit.action_type == "update_draft",
                )
            ).all()
            _restore_wordpress_page(
                session,
                session.get(GeneratedPage, page_id),
                original,
                audits=[audit, *update_audits],
            )
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 409
    assert len(update_audits) == 1
    assert update_audits[0].status == "blocked"
    assert any(
        item["code"] == "qa_ready" and item["passed"] is False
        for item in update_audits[0].gate_results
    )


def test_wordpress_update_apply_blocks_live_status_not_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wordpress_draft_review.httpx, "Client", _fake_wordpress_get_client(status="draft"))
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            audit = _add_wordpress_draft_audit(session, page, status="created")
            page_id = page.id
        dry_run = client.post(f"/api/wordpress/draft-update/dry-run/{page_id}").json()
        monkeypatch.setattr(wordpress_draft_review.httpx, "Client", _fake_wordpress_get_client(status="publish"))
        response = client.post(
            f"/api/wordpress/draft-update/apply/{page_id}",
            json={
                "confirmation_token": dry_run["confirmation_token"],
                "confirmation_phrase": dry_run["confirmation_phrase"],
            },
        )
        with Session(engine) as session:
            update_audits = session.exec(
                select(WordPressDraftAudit).where(
                    WordPressDraftAudit.generated_page_id == page_id,
                    WordPressDraftAudit.action_type == "update_draft",
                )
            ).all()
            _restore_wordpress_page(
                session,
                session.get(GeneratedPage, page_id),
                original,
                audits=[audit, *update_audits],
            )
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 409
    assert len(update_audits) == 1
    assert any(
        item["code"] == "live_wordpress_status_draft" and item["passed"] is False
        for item in update_audits[0].gate_results
    )


def test_wordpress_update_apply_sends_draft_only_and_records_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[dict] = []
    monkeypatch.setattr(wordpress_draft_review.httpx, "Client", _fake_wordpress_get_client(status="draft"))
    monkeypatch.setattr(
        wordpress_draft_update.httpx,
        "Client",
        _fake_wordpress_update_client(sent=sent, status="draft"),
    )
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            original_draft = deepcopy(page.draft_content)
            create_audit = _add_wordpress_draft_audit(session, page, status="created")
            original_created_at = page.wordpress_created_at
            revisions_before = _revision_count(session, page.id)
            create_count_before = len(
                session.exec(
                    select(WordPressDraftAudit).where(
                        WordPressDraftAudit.generated_page_id == page.id,
                        WordPressDraftAudit.action_type == "create_draft",
                    )
                ).all()
            )
            page_id = page.id
        dry_run = client.post(f"/api/wordpress/draft-update/dry-run/{page_id}").json()
        response = client.post(
            f"/api/wordpress/draft-update/apply/{page_id}",
            json={
                "confirmation_token": dry_run["confirmation_token"],
                "confirmation_phrase": dry_run["confirmation_phrase"],
            },
        )
        with Session(engine) as session:
            page = session.get(GeneratedPage, page_id)
            update_audits = session.exec(
                select(WordPressDraftAudit).where(
                    WordPressDraftAudit.generated_page_id == page_id,
                    WordPressDraftAudit.action_type == "update_draft",
                )
            ).all()
            create_count_after = len(
                session.exec(
                    select(WordPressDraftAudit).where(
                        WordPressDraftAudit.generated_page_id == page_id,
                        WordPressDraftAudit.action_type == "create_draft",
                    )
                ).all()
            )
            saved = {
                "status": page.status,
                "wordpress_post_id": page.wordpress_post_id,
                "wordpress_status": page.wordpress_status,
                "wordpress_url": page.wordpress_url,
                "wordpress_created_at": page.wordpress_created_at,
                "last_wordpress_sync_at": page.last_wordpress_sync_at,
                "draft_content": deepcopy(page.draft_content),
                "revision_count": _revision_count(session, page_id),
            }
            _restore_wordpress_page(
                session,
                page,
                original,
                audits=[create_audit, *update_audits],
            )
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 200
    assert sent[0]["url"] == "https://wordpress.example/wp-json/wp/v2/pages/712"
    assert sent[0]["json"]["status"] == "draft"
    assert set(sent[0]["json"]) == {"title", "slug", "status", "content", "excerpt"}
    assert sent[0]["auth"] is True
    assert saved["status"] == "approved"
    assert saved["wordpress_post_id"] == 712
    assert saved["wordpress_status"] == "draft"
    assert saved["wordpress_url"] == "https://wordpress.example/?page_id=712"
    assert saved["wordpress_created_at"] == original_created_at
    assert saved["last_wordpress_sync_at"] is not None
    assert saved["draft_content"] == original_draft
    assert saved["revision_count"] == revisions_before
    assert len(update_audits) == 1
    assert update_audits[0].status == "updated"
    assert update_audits[0].payload_hash == dry_run["comparison"]["current_payload_hash"]
    assert create_count_after == create_count_before
    assert "password" not in json.dumps(update_audits[0].model_dump(mode="json")).lower()


def test_wordpress_update_apply_records_failed_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wordpress_draft_review.httpx, "Client", _fake_wordpress_get_client(status="draft"))
    monkeypatch.setattr(
        wordpress_draft_update.httpx,
        "Client",
        _fake_wordpress_update_client(sent=[], status="draft", response_status_code=500),
    )
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            create_audit = _add_wordpress_draft_audit(session, page, status="created")
            page_id = page.id
        dry_run = client.post(f"/api/wordpress/draft-update/dry-run/{page_id}").json()
        response = client.post(
            f"/api/wordpress/draft-update/apply/{page_id}",
            json={
                "confirmation_token": dry_run["confirmation_token"],
                "confirmation_phrase": dry_run["confirmation_phrase"],
            },
        )
        with Session(engine) as session:
            update_audits = session.exec(
                select(WordPressDraftAudit).where(
                    WordPressDraftAudit.generated_page_id == page_id,
                    WordPressDraftAudit.action_type == "update_draft",
                )
            ).all()
            page = session.get(GeneratedPage, page_id)
            wordpress_status = page.wordpress_status
            _restore_wordpress_page(
                session,
                page,
                original,
                audits=[create_audit, *update_audits],
            )
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 502
    assert len(update_audits) == 1
    assert update_audits[0].status == "failed"
    assert update_audits[0].error_message == "WordPress returned HTTP 500."
    assert wordpress_status == "draft"


def test_wordpress_update_apply_does_not_add_broader_wordpress_routes() -> None:
    with TestClient(app) as client:
        responses = [
            client.post("/api/wordpress/draft-update/bulk"),
            client.post("/api/wordpress/draft-update/create/1"),
            client.post("/api/wordpress/draft-update/publish/1"),
            client.post("/api/wordpress/draft-update/delete/1"),
            client.post("/api/wordpress/draft-update/media/1"),
        ]

    assert [response.status_code for response in responses] == [404, 404, 404, 404, 404]


def test_wordpress_publish_dry_run_blocks_missing_credentials() -> None:
    wordpress_sandbox.clear_wordpress_application_password()
    with TestClient(app) as client:
        with Session(engine) as session:
            _clear_wordpress_settings(session)
            page, original = _prepare_wordpress_draft_page(session)
            create_audit = _add_wordpress_draft_audit(session, page, status="created")
            update_audit = _add_wordpress_update_audit(session, page)
            review = _set_manual_publish_ready(session, page.id)
            review_id = review.id
            page_id = page.id
        response = client.post(f"/api/wordpress/publish/dry-run/{page_id}")
        with Session(engine) as session:
            _restore_wordpress_page(
                session,
                session.get(GeneratedPage, page_id),
                original,
                audits=[create_audit, update_audit],
            )
            session.delete(session.get(WordPressQualityReview, review_id))
            session.commit()
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 200
    assert response.json()["status"] == "blocked"
    assert _gate_response(response.json(), "credentials_ready")["passed"] is False
    assert response.json()["confirmation_token"] is None


def test_wordpress_audit_helpers_are_monotonic_and_restore_removes_history() -> None:
    with TestClient(app):
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            create_audit = _add_wordpress_draft_audit(session, page, status="created")
            first = _add_wordpress_update_audit(session, page)
            second = _add_wordpress_update_audit(session, page)
            assert first.payload_hash == second.payload_hash
            assert first.attempted_at != second.attempted_at
            page_id = page.id
            _restore_wordpress_page(session, page, original, audits=[create_audit, first, second])
            assert session.exec(select(WordPressDraftAudit).where(WordPressDraftAudit.generated_page_id == page_id)).all() == []


def test_wordpress_publish_dry_run_blocks_manual_review_not_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wordpress_draft_review.httpx, "Client", _fake_wordpress_get_client(status="draft"))
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            create_audit = _add_wordpress_draft_audit(session, page, status="created")
            update_audit = _add_wordpress_update_audit(session, page)
            review = _set_manual_publish_ready(session, page.id)
            review.review_status = "needs_changes"
            session.add(review)
            session.commit()
            review_id = review.id
            page_id = page.id
        response = client.post(f"/api/wordpress/publish/dry-run/{page_id}")
        with Session(engine) as session:
            _restore_wordpress_page(
                session,
                session.get(GeneratedPage, page_id),
                original,
                audits=[create_audit, update_audit],
            )
            session.delete(session.get(WordPressQualityReview, review_id))
            session.commit()
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 200
    assert _gate_response(response.json(), "manual_review_ready")["passed"] is False
    assert response.json()["status"] == "blocked"


def test_wordpress_publish_dry_run_blocks_live_status_not_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wordpress_draft_review.httpx, "Client", _fake_wordpress_get_client(status="publish"))
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            create_audit = _add_wordpress_draft_audit(session, page, status="created")
            update_audit = _add_wordpress_update_audit(session, page)
            review = _set_manual_publish_ready(session, page.id)
            review_id = review.id
            page_id = page.id
        response = client.post(f"/api/wordpress/publish/dry-run/{page_id}")
        with Session(engine) as session:
            _restore_wordpress_page(
                session,
                session.get(GeneratedPage, page_id),
                original,
                audits=[create_audit, update_audit],
            )
            session.delete(session.get(WordPressQualityReview, review_id))
            session.commit()
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 200
    assert _gate_response(response.json(), "live_wordpress_status_draft")["passed"] is False
    assert response.json()["live_status"]["appears_published"] is True
    assert response.json()["confirmation_token"] is None


def test_wordpress_publish_dry_run_blocks_hash_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wordpress_draft_review.httpx, "Client", _fake_wordpress_get_client(status="draft"))
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            create_audit = _add_wordpress_draft_audit(session, page, status="created")
            update_audit = _add_wordpress_update_audit(session, page)
            update_audit.payload_hash = "stale-update-hash"
            session.add(update_audit)
            review = _set_manual_publish_ready(session, page.id)
            session.commit()
            review_id = review.id
            page_id = page.id
        response = client.post(f"/api/wordpress/publish/dry-run/{page_id}")
        with Session(engine) as session:
            _restore_wordpress_page(
                session,
                session.get(GeneratedPage, page_id),
                original,
                audits=[create_audit, update_audit],
            )
            session.delete(session.get(WordPressQualityReview, review_id))
            session.commit()
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 200
    assert _gate_response(response.json(), "latest_update_hash_matches")["passed"] is False
    assert response.json()["status"] == "blocked"


def test_wordpress_publish_dry_run_is_read_only_and_returns_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wordpress_draft_review.httpx, "Client", _fake_wordpress_get_client(status="draft"))
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            create_audit = _add_wordpress_draft_audit(session, page, status="created")
            update_audit = _add_wordpress_update_audit(session, page)
            review = _set_manual_publish_ready(session, page.id)
            review_id = review.id
            page_id = page.id
            before = _approval_queue_database_snapshot(session)
        response = client.post(f"/api/wordpress/publish/dry-run/{page_id}")
        with Session(engine) as session:
            after = _approval_queue_database_snapshot(session)
            _restore_wordpress_page(
                session,
                session.get(GeneratedPage, page_id),
                original,
                audits=[create_audit, update_audit],
            )
            session.delete(session.get(WordPressQualityReview, review_id))
            session.commit()
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "dry_run_ready"
    assert body["payload"]["status"] == "publish"
    assert body["current_payload_hash"] == body["latest_update_audit_hash"]
    assert body["publish_payload_hash"] != body["current_payload_hash"]
    assert body["confirmation_phrase"] == "PUBLISH WORDPRESS PAGE drywood-termite-tenting-orlando-fl"
    assert body["confirmation_token"]
    assert "public" in body["public_publish_warning"].lower()
    assert after == before


def test_wordpress_publish_exposes_no_bulk_or_unrelated_routes() -> None:
    with TestClient(app) as client:
        responses = [
            client.post("/api/wordpress/publish/bulk"),
            client.post("/api/wordpress/publish/create/1"),
            client.post("/api/wordpress/publish/delete/1"),
            client.post("/api/wordpress/publish/media/1"),
        ]

    assert [response.status_code for response in responses] == [404, 404, 404, 404]


def test_wordpress_publish_apply_rejects_invalid_token_without_audit() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/wordpress/publish/apply/1",
            json={"confirmation_token": "invalid", "confirmation_phrase": "invalid", "confirmed_backup_file": "atlas-backup-test.json"},
        )
        with Session(engine) as session:
            assert session.exec(select(WordPressPublishAudit)).all() == []
    assert response.status_code == 422


def test_wordpress_publish_apply_reruns_gates_and_sends_no_request_when_credentials_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[dict] = []
    monkeypatch.setattr(wordpress_publish.httpx, "Client", _fake_wordpress_publish_client(sent, []))
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            _add_wordpress_draft_audit(session, page, status="created")
            _add_wordpress_update_audit(session, page)
            review = _set_manual_publish_ready(session, page.id)
            page_id, review_id = page.id, review.id
        dry_run = client.post(f"/api/wordpress/publish/dry-run/{page_id}").json()
        wordpress_sandbox.clear_wordpress_application_password()
        response = client.post(
            f"/api/wordpress/publish/apply/{page_id}",
            json={"confirmation_token": dry_run["confirmation_token"], "confirmation_phrase": dry_run["confirmation_phrase"], "confirmed_backup_file": "atlas-backup-test.json"},
        )
        with Session(engine) as session:
            assert session.exec(select(WordPressPublishAudit)).all() == []
            session.delete(session.get(WordPressQualityReview, review_id))
            draft_audits = session.exec(select(WordPressDraftAudit).where(WordPressDraftAudit.generated_page_id == page_id)).all()
            _restore_wordpress_page(session, session.get(GeneratedPage, page_id), original, audits=draft_audits)
            _clear_wordpress_settings(session)
    assert response.status_code == 409
    assert sent == []


def test_wordpress_publish_apply_blocks_invalid_backup_without_wordpress_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[dict] = []
    monkeypatch.setattr(wordpress_publish.httpx, "Client", _fake_wordpress_publish_client(sent, []))
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            _add_wordpress_draft_audit(session, page, status="created")
            _add_wordpress_update_audit(session, page)
            review = _set_manual_publish_ready(session, page.id)
            page_id, review_id = page.id, review.id
        dry_run = client.post(f"/api/wordpress/publish/dry-run/{page_id}").json()
        response = client.post(
            f"/api/wordpress/publish/apply/{page_id}",
            json={"confirmation_token": dry_run["confirmation_token"], "confirmation_phrase": dry_run["confirmation_phrase"], "confirmed_backup_file": "missing.json"},
        )
        with Session(engine) as session:
            assert session.exec(select(WordPressPublishAudit)).all() == []
            session.delete(session.get(WordPressQualityReview, review_id))
            draft_audits = session.exec(select(WordPressDraftAudit).where(WordPressDraftAudit.generated_page_id == page_id)).all()
            _restore_wordpress_page(session, session.get(GeneratedPage, page_id), original, audits=draft_audits)
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()
    assert response.status_code == 409
    assert sent == []


def test_wordpress_publish_apply_publishes_one_confirmed_page_and_preserves_draft_audits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[dict] = []
    pending_seen: list[bool] = []
    monkeypatch.setattr(wordpress_publish.httpx, "Client", _fake_wordpress_publish_client(sent, pending_seen))
    monkeypatch.setattr(wordpress_publish, "resolve_backup_download", lambda _: Path("atlas-backup-test.json"))
    monkeypatch.setattr(wordpress_publish, "load_backup", lambda _: {"metadata": {"created_at": datetime.now(UTC).isoformat()}})
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            create_audit = _add_wordpress_draft_audit(session, page, status="created")
            update_audit = _add_wordpress_update_audit(session, page)
            review = _set_manual_publish_ready(session, page.id)
            page_id, review_id = page.id, review.id
            draft_count = _wordpress_draft_audit_count(session, page_id)
        dry_run = client.post(f"/api/wordpress/publish/dry-run/{page_id}").json()
        response = client.post(
            f"/api/wordpress/publish/apply/{page_id}",
            json={
                "confirmation_token": dry_run["confirmation_token"],
                "confirmation_phrase": dry_run["confirmation_phrase"],
                "confirmed_backup_file": "atlas-backup-test.json",
            },
        )
        with Session(engine) as session:
            published = session.get(GeneratedPage, page_id)
            audits = session.exec(select(WordPressPublishAudit).where(WordPressPublishAudit.generated_page_id == page_id)).all()
            assert published.status == "published"
            assert published.wordpress_status == "publish"
            assert _wordpress_draft_audit_count(session, page_id) == draft_count
            assert len(audits) == 1 and audits[0].status == "published"
            session.delete(audits[0])
            session.delete(session.get(WordPressQualityReview, review_id))
            draft_audits = session.exec(select(WordPressDraftAudit).where(WordPressDraftAudit.generated_page_id == page_id)).all()
            _restore_wordpress_page(session, published, original, audits=draft_audits)
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()
    assert response.status_code == 200
    assert response.json()["wordpress_post_id"] == 712
    assert response.json()["wordpress_status"] == "publish"
    assert pending_seen == [True]
    assert len(sent) == 1 and sent[0]["json"]["status"] == "publish"


def test_backup_restore_preserves_publish_audits_idempotently(tmp_path: Path) -> None:
    with TestClient(app):
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            now = datetime.now(UTC)
            audit = WordPressPublishAudit(
                generated_page_id=page.id,
                wordpress_post_id=8,
                wordpress_site_url="https://wordpress.example",
                attempted_at=now,
                completed_at=now,
                status="published",
                pre_publish_wordpress_status="draft",
                returned_wordpress_status="publish",
                returned_wordpress_url="https://wordpress.example/orlando/",
                current_draft_payload_hash="current-draft-hash",
                latest_update_audit_hash="current-draft-hash",
                publish_payload_hash="publish-hash",
                gate_results=[{"code": "one_page_only", "passed": True}],
                backup_file_name="atlas-backup-before-publish.json",
            )
            session.add(audit)
            session.commit()
            export = export_backup(session, backup_dir=tmp_path)
            session.delete(audit)
            session.commit()
            restore_backup(session, export["path"])
            restore_backup(session, export["path"])
            restored = session.exec(select(WordPressPublishAudit).where(WordPressPublishAudit.publish_payload_hash == "publish-hash")).all()
            assert len(restored) == 1
            assert restored[0].status == "published"
            session.delete(restored[0])
            session.commit()


def test_wordpress_create_requires_valid_confirmation_without_audit() -> None:
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            page_id = page.id
            audit_count_before = len(session.exec(select(WordPressDraftAudit)).all())
        response = client.post(
            f"/api/wordpress/draft/create/{page_id}",
            json={"confirmation_token": "invalid", "confirmation_phrase": "invalid"},
        )
        with Session(engine) as session:
            audit_count_after = len(session.exec(select(WordPressDraftAudit)).all())
            _restore_wordpress_page(session, session.get(GeneratedPage, page_id), original)
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 422
    assert audit_count_after == audit_count_before


def test_wordpress_create_reruns_gates_and_records_blocked_attempt() -> None:
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            page_id = page.id
        dry_run = client.post(f"/api/wordpress/draft/dry-run/{page_id}").json()
        with Session(engine) as session:
            page = session.get(GeneratedPage, page_id)
            page.qa_status = "blocked"
            session.add(page)
            session.commit()
        response = client.post(
            f"/api/wordpress/draft/create/{page_id}",
            json={
                "confirmation_token": dry_run["confirmation_token"],
                "confirmation_phrase": dry_run["confirmation_phrase"],
            },
        )
        with Session(engine) as session:
            audits = session.exec(
                select(WordPressDraftAudit).where(
                    WordPressDraftAudit.generated_page_id == page_id
                )
            ).all()
            blocked = [audit for audit in audits if audit.status == "blocked"]
            _restore_wordpress_page(
                session,
                session.get(GeneratedPage, page_id),
                original,
                audits=blocked,
            )
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 409
    assert blocked
    assert any(
        item["code"] == "qa_ready" and item["passed"] is False
        for item in blocked[0].gate_results
    )


def test_wordpress_create_sends_draft_only_and_records_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[dict] = []

    class FakeResponse:
        status_code = 201

        def json(self) -> dict:
            return {
                "id": 712,
                "status": "draft",
                "link": "https://wordpress.example/?page_id=712",
            }

    class FakeClient:
        def __init__(self, **_: object) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def post(self, url: str, *, json: dict, auth: object) -> FakeResponse:
            sent.append({"url": url, "json": deepcopy(json), "auth": auth is not None})
            return FakeResponse()

    monkeypatch.setattr(wordpress_drafts.httpx, "Client", FakeClient)
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            original_draft = deepcopy(page.draft_content)
            page_id = page.id
        dry_run = client.post(f"/api/wordpress/draft/dry-run/{page_id}").json()
        response = client.post(
            f"/api/wordpress/draft/create/{page_id}",
            json={
                "confirmation_token": dry_run["confirmation_token"],
                "confirmation_phrase": dry_run["confirmation_phrase"],
            },
        )
        with Session(engine) as session:
            page = session.get(GeneratedPage, page_id)
            audits = session.exec(
                select(WordPressDraftAudit).where(
                    WordPressDraftAudit.generated_page_id == page_id
                )
            ).all()
            created = [audit for audit in audits if audit.status == "created"]
            saved = {
                "status": page.status,
                "wordpress_post_id": page.wordpress_post_id,
                "wordpress_status": page.wordpress_status,
                "wordpress_url": page.wordpress_url,
                "draft_content": deepcopy(page.draft_content),
            }
            _restore_wordpress_page(session, page, original, audits=created)
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 200
    assert sent[0]["url"] == "https://wordpress.example/wp-json/wp/v2/pages"
    assert sent[0]["json"]["status"] == "draft"
    assert set(sent[0]["json"]) == {"title", "slug", "status", "content", "excerpt"}
    assert sent[0]["auth"] is True
    assert saved["status"] == "approved"
    assert saved["wordpress_post_id"] == 712
    assert saved["wordpress_status"] == "draft"
    assert saved["draft_content"] == original_draft
    assert len(created) == 1
    assert created[0].wordpress_post_id == 712
    assert created[0].payload_hash == dry_run["payload_hash"]
    assert "password" not in json.dumps(created[0].model_dump(mode="json")).lower()


def test_wordpress_create_records_failed_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        status_code = 500

        def json(self) -> dict:
            return {}

    class FakeClient:
        def __init__(self, **_: object) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def post(self, *_: object, **__: object) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(wordpress_drafts.httpx, "Client", FakeClient)
    with TestClient(app) as client:
        _configure_wordpress_sandbox(client)
        with Session(engine) as session:
            page, original = _prepare_wordpress_draft_page(session)
            page_id = page.id
        dry_run = client.post(f"/api/wordpress/draft/dry-run/{page_id}").json()
        response = client.post(
            f"/api/wordpress/draft/create/{page_id}",
            json={
                "confirmation_token": dry_run["confirmation_token"],
                "confirmation_phrase": dry_run["confirmation_phrase"],
            },
        )
        with Session(engine) as session:
            failed = session.exec(
                select(WordPressDraftAudit).where(
                    WordPressDraftAudit.generated_page_id == page_id,
                    WordPressDraftAudit.status == "failed",
                )
            ).all()
            page = session.get(GeneratedPage, page_id)
            wordpress_post_id = page.wordpress_post_id
            _restore_wordpress_page(session, page, original, audits=failed)
            _clear_wordpress_settings(session)
    wordpress_sandbox.clear_wordpress_application_password()

    assert response.status_code == 502
    assert len(failed) == 1
    assert failed[0].error_message == "WordPress returned HTTP 500."
    assert wordpress_post_id is None


def test_backup_restore_preserves_wordpress_audits_and_safe_references_idempotently(
    tmp_path: Path,
) -> None:
    with TestClient(app):
        with Session(engine) as session:
            page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
            original = _wordpress_page_state(page)
            now = datetime.now(UTC)
            page.wordpress_post_id = 911
            page.wordpress_url = "https://wordpress.example/?page_id=911"
            page.wordpress_status = "draft"
            page.wordpress_created_at = now
            page.last_wordpress_sync_at = now
            audit = WordPressDraftAudit(
                generated_page_id=page.id,
                attempted_at=now,
                action_type="create_draft",
                status="created",
                wordpress_site_url="https://wordpress.example",
                wordpress_post_id=911,
                wordpress_status="draft",
                slug=page.page_slug,
                payload_hash="payload-backup-hash",
                qa_status_at_attempt="ready",
                qa_checked_at=now,
                draft_hash_at_attempt="draft-backup-hash",
                gate_results=[{"code": "draft_status", "passed": True}],
            )
            session.add(page)
            session.add(audit)
            session.commit()
            export = export_backup(session, backup_dir=tmp_path)
            payload = json.loads(Path(export["path"]).read_text(encoding="utf-8"))
            session.delete(audit)
            page.wordpress_post_id = None
            page.wordpress_url = None
            page.wordpress_status = None
            page.wordpress_created_at = None
            page.last_wordpress_sync_at = None
            session.add(page)
            session.commit()

            restore_backup(session, export["path"])
            restore_backup(session, export["path"])
            restored_page = session.get(GeneratedPage, page.id)
            restored_audits = session.exec(
                select(WordPressDraftAudit).where(
                    WordPressDraftAudit.generated_page_id == page.id,
                    WordPressDraftAudit.payload_hash == "payload-backup-hash",
                )
            ).all()
            restored_post_id = restored_page.wordpress_post_id
            _restore_wordpress_page(
                session,
                restored_page,
                original,
                audits=restored_audits,
            )

    assert payload["metadata"]["version"] == "0.34"
    assert payload["data"]["wordpress_draft_audits"]
    assert payload["data"]["generated_pages"][0].get("wordpress_post_id") is not None or any(
        item.get("wordpress_post_id") == 911
        for item in payload["data"]["generated_pages"]
    )
    assert len(restored_audits) == 1
    assert restored_post_id == 911


def _database_counts(session: Session) -> dict[str, int]:
    return {
        group: len(session.exec(select(model)).all())
        for group, model in BACKUP_MODELS.items()
    }


def _clear_wordpress_settings(session: Session) -> None:
    settings = session.exec(
        select(Setting).where(Setting.setting_key.startswith("wordpress_"))
    ).all()
    for setting in settings:
        session.delete(setting)
    session.commit()


def _configure_wordpress_sandbox(client: TestClient):
    response = client.put(
        "/api/wordpress/settings",
        json={
            "site_url": "https://wordpress.example",
            "username": "atlas",
            "application_password": "local-test-only",
            "publishing_mode": "sandbox",
        },
    )
    assert response.status_code == 200
    return response


def _prepare_wordpress_draft_page(
    session: Session,
) -> tuple[GeneratedPage, dict]:
    page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
    page = _ensure_complete_page(session, page)
    original = _wordpress_page_state(page)
    qa = evaluate_page_qa(session, page.id)
    assert qa.readiness_status == "ready"
    page.status = "approved"
    page.qa_status = "ready"
    page.qa_result = qa.model_dump(mode="json", exclude={"persisted"})
    page.qa_checked_at = datetime.now(UTC)
    page.wordpress_post_id = None
    page.wordpress_url = None
    page.wordpress_status = None
    page.wordpress_created_at = None
    page.last_wordpress_sync_at = None
    session.add(page)
    session.commit()
    session.refresh(page)
    return page, original


def _add_wordpress_draft_audit(
    session: Session,
    page: GeneratedPage,
    *,
    status: str,
) -> WordPressDraftAudit:
    now = datetime.now(UTC)
    page.wordpress_post_id = 712
    page.wordpress_url = "https://wordpress.example/?page_id=712"
    page.wordpress_status = "draft"
    page.wordpress_created_at = now
    page.last_wordpress_sync_at = now
    session.add(page)
    session.flush()
    current_hash = wordpress_draft_review.compare_wordpress_draft(
        session,
        page.id,
    ).current_export_payload_hash
    audit = WordPressDraftAudit(
        generated_page_id=page.id,
        attempted_at=now,
        action_type="create_draft",
        status=status,
        wordpress_site_url="https://wordpress.example",
        wordpress_post_id=712,
        wordpress_status="draft",
        slug=page.page_slug,
        payload_hash=current_hash,
        qa_status_at_attempt=page.qa_status,
        qa_checked_at=page.qa_checked_at,
        draft_hash_at_attempt=draft_content_hash(page.draft_content),
        gate_results=[{"code": "draft_status", "passed": True}],
    )
    session.add(audit)
    session.commit()
    session.refresh(page)
    session.refresh(audit)
    return audit


def _add_wordpress_update_audit(
    session: Session,
    page: GeneratedPage,
) -> WordPressDraftAudit:
    current_hash = wordpress_draft_review.compare_wordpress_draft(
        session,
        page.id,
    ).current_export_payload_hash
    now = _next_wordpress_audit_time(session, page.id, current_hash)
    audit = WordPressDraftAudit(
        generated_page_id=page.id,
        attempted_at=now,
        action_type="update_draft",
        status="updated",
        wordpress_site_url="https://wordpress.example",
        wordpress_post_id=page.wordpress_post_id,
        wordpress_status="draft",
        slug=page.page_slug,
        payload_hash=current_hash,
        qa_status_at_attempt=page.qa_status,
        qa_checked_at=page.qa_checked_at,
        draft_hash_at_attempt=draft_content_hash(page.draft_content),
        gate_results=[{"code": "draft_status", "passed": True}],
    )
    session.add(audit)
    session.commit()
    session.refresh(audit)
    return audit


def _next_wordpress_audit_time(session: Session, page_id: int, payload_hash: str) -> datetime:
    latest = session.exec(
        select(WordPressDraftAudit).where(
            WordPressDraftAudit.generated_page_id == page_id,
            WordPressDraftAudit.payload_hash == payload_hash,
        ).order_by(WordPressDraftAudit.attempted_at.desc())
    ).first()
    now = datetime.now(UTC)
    if latest is not None:
        latest_time = latest.attempted_at
        if latest_time.tzinfo is None:
            latest_time = latest_time.replace(tzinfo=UTC)
        if now <= latest_time:
            now = latest_time + timedelta(microseconds=1)
    return now


def _set_manual_publish_ready(
    session: Session,
    page_id: int,
) -> WordPressQualityReview:
    now = datetime.now(UTC)
    record = session.exec(
        select(WordPressQualityReview).where(
            WordPressQualityReview.generated_page_id == page_id
        )
    ).first()
    if record is None:
        record = WordPressQualityReview(generated_page_id=page_id)
    record.review_status = "ready_for_manual_publish_review"
    record.reviewer_notes = "Manual visual review complete for publish dry-run tests."
    record.reviewed_by = "pytest"
    record.reviewed_at = now
    record.updated_at = now
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def _wordpress_page_state(page: GeneratedPage) -> dict:
    return {
        "page_slug": page.page_slug,
        "status": page.status,
        "qa_status": page.qa_status,
        "qa_result": deepcopy(page.qa_result),
        "qa_checked_at": page.qa_checked_at,
        "wordpress_post_id": page.wordpress_post_id,
        "wordpress_url": page.wordpress_url,
        "wordpress_status": page.wordpress_status,
        "wordpress_created_at": page.wordpress_created_at,
        "last_wordpress_sync_at": page.last_wordpress_sync_at,
        "updated_at": page.updated_at,
    }


def _restore_wordpress_page(
    session: Session,
    page: GeneratedPage | None,
    state: dict,
    *,
    revisions: list[GeneratedPageRevision] | None = None,
    audits: list[WordPressDraftAudit] | None = None,
) -> None:
    assert page is not None
    for key, value in state.items():
        setattr(page, key, value)
    session.add(page)
    for revision in revisions or []:
        session.delete(revision)
    for audit in audits or []:
        session.delete(audit)
    session.commit()


def _gate_response(payload: dict, code: str) -> dict:
    return next(item for item in payload["gate_results"] if item["code"] == code)


def _approval_queue_item(session: Session, page_id: int):
    return next(
        item
        for item in build_approval_queue(session).items
        if item.page_id == page_id
    )


def _approval_queue_database_snapshot(session: Session) -> dict:
    pages = session.exec(select(GeneratedPage).order_by(GeneratedPage.id)).all()
    revisions = session.exec(
        select(GeneratedPageRevision).order_by(GeneratedPageRevision.id)
    ).all()
    audits = session.exec(select(ApprovalAudit).order_by(ApprovalAudit.id)).all()
    assignments = session.exec(
        select(PageImageAssignment).order_by(PageImageAssignment.id)
    ).all()
    images = session.exec(select(ImageMetadata).order_by(ImageMetadata.id)).all()
    wordpress_audits = session.exec(
        select(WordPressDraftAudit).order_by(WordPressDraftAudit.id)
    ).all()
    quality_reviews = session.exec(
        select(WordPressQualityReview).order_by(WordPressQualityReview.id)
    ).all()
    backup_root = Path("backups")
    return {
        "pages": [
            (
                page.id,
                page.status,
                deepcopy(page.draft_content),
                page.qa_status,
                deepcopy(page.qa_result),
                page.qa_checked_at,
                page.updated_at,
            )
            for page in pages
        ],
        "revisions": [revision.model_dump() for revision in revisions],
        "approval_audits": [audit.model_dump() for audit in audits],
        "media_assignments": [assignment.model_dump() for assignment in assignments],
        "image_metadata": [image.model_dump() for image in images],
        "wordpress_draft_audits": [audit.model_dump() for audit in wordpress_audits],
        "wordpress_quality_reviews": [review.model_dump() for review in quality_reviews],
        "backup_files": _file_tree_snapshot(backup_root) if backup_root.exists() else {},
    }


def _program_backup_project(root: Path) -> Path:
    included_files = {
        "backend/app/main.py": "print('atlas')\n",
        "backend/alembic/env.py": "# migrations\n",
        "backend/tests/test_app.py": "def test_placeholder(): pass\n",
        "backend/requirements.txt": "fastapi\n",
        "backend/Dockerfile": "FROM python:3.12\n",
        "backend/alembic.ini": "[alembic]\n",
        "frontend/src/main.tsx": "export {};\n",
        "frontend/public/robots.txt": "User-agent: *\n",
        "frontend/package.json": '{"name":"atlas"}\n',
        "frontend/index.html": "<div id=\"root\"></div>\n",
        "frontend/vite.config.ts": "export default {};\n",
        "frontend/tsconfig.json": "{}\n",
        "frontend/Dockerfile": "FROM node:20\n",
        "docker-compose.yml": "services: {}\n",
        "README.md": "# Atlas\n",
    }
    excluded_files = {
        ".git/config": "private git metadata\n",
        ".runtime/atlas-release.json": "runtime identity\n",
        ".local-wp-integration/compose.yaml": "temporary wordpress\n",
        "backend/.env": "DATABASE_URL=secret\n",
        "backend/app/.env.local": "SECRET=hidden\n",
        "backend/app/private_key.pem": "private\n",
        "backend/app/secrets.json": "{}\n",
        "backend/app/cache.db": "database\n",
        "backend/app/cache.db-wal": "database sidecar\n",
        "backend/app/cache.sqlite-shm": "database sidecar\n",
        "backend/app/cache.sqlite3-journal": "database sidecar\n",
        "backend/app/__pycache__/main.pyc": "cache\n",
        "backend/alembic/.pytest_cache/state": "cache\n",
        "backend/backups/atlas-backup-old.json": "backup\n",
        "backend/media/originals/image.jpg": "media\n",
        "frontend/.env": "VITE_SECRET=hidden\n",
        "frontend/src/.env.production": "VITE_SECRET=hidden\n",
        "frontend/public/media/hero.png": "media\n",
        "frontend/node_modules/pkg/index.js": "dependency\n",
        "frontend/dist/index.html": "build output\n",
    }
    for relative_path, content in {**included_files, **excluded_files}.items():
        destination = root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
    return root


def _file_tree_snapshot(root: Path) -> dict[str, tuple[int, int, str]]:
    return {
        file.relative_to(root).as_posix(): (
            file.stat().st_size,
            file.stat().st_mtime_ns,
            hashlib.sha256(file.read_bytes()).hexdigest(),
        )
        for file in root.rglob("*")
        if file.is_file()
    }


def _manual_editor_payload(page: GeneratedPage) -> dict:
    draft = page.draft_content or {}
    return {
        "draft": {
            "hero_headline": draft["h1"],
            "hero_subheadline": draft.get("hero_subheadline") or draft["meta_description"],
            "intro": draft["intro"],
            "service_explanation": draft.get("service_explanation") or draft["why_it_matters"],
            "local_city_section": draft.get("local_city_section")
            or draft["realtor_property_manager_section"],
            "process_section": draft["process_section"],
            "prep_reentry_section": draft["prep_section"],
            "why_choose_section": draft.get("why_choose_section")
            or "Choose Flo-Zone for careful planning, clear preparation guidance, and licensed service.",
            "faq_items": deepcopy(draft["faq_items"]),
            "call_to_action": draft["call_to_action"],
        },
        "created_by": "Atlas Editor",
        "reason": "Manual QA remediation",
    }


def _editor_page_state(page: GeneratedPage) -> dict:
    return {
        "draft_content": deepcopy(page.draft_content),
        "h1": page.h1,
        "content_body": page.content_body,
        "qa_status": page.qa_status,
        "qa_result": deepcopy(page.qa_result),
        "qa_checked_at": page.qa_checked_at,
        "updated_at": page.updated_at,
        "status": page.status,
    }


def _approved_repair_page_state(page: GeneratedPage) -> dict:
    state = _editor_page_state(page)
    state.update(
        {
            "wordpress_post_id": page.wordpress_post_id,
            "wordpress_url": page.wordpress_url,
            "wordpress_status": page.wordpress_status,
            "wordpress_created_at": page.wordpress_created_at,
            "last_wordpress_sync_at": page.last_wordpress_sync_at,
        }
    )
    return state


def _restore_editor_page(
    session: Session,
    page: GeneratedPage,
    state: dict,
    *,
    revisions: list[GeneratedPageRevision] | None = None,
    audits: list[ApprovalAudit] | None = None,
) -> None:
    page.draft_content = state["draft_content"]
    page.h1 = state["h1"]
    page.content_body = state["content_body"]
    page.qa_status = state["qa_status"]
    page.qa_result = state["qa_result"]
    page.qa_checked_at = state["qa_checked_at"]
    page.updated_at = state["updated_at"]
    page.status = state["status"]
    session.add(page)
    for revision in revisions or []:
        session.delete(revision)
    for audit in audits or []:
        session.delete(audit)
    session.commit()


def _restore_approved_repair_page(
    session: Session,
    page: GeneratedPage,
    state: dict,
    *,
    revisions: list[GeneratedPageRevision] | None = None,
) -> None:
    page.draft_content = state["draft_content"]
    page.h1 = state["h1"]
    page.content_body = state["content_body"]
    page.qa_status = state["qa_status"]
    page.qa_result = state["qa_result"]
    page.qa_checked_at = state["qa_checked_at"]
    page.updated_at = state["updated_at"]
    page.status = state["status"]
    page.wordpress_post_id = state["wordpress_post_id"]
    page.wordpress_url = state["wordpress_url"]
    page.wordpress_status = state["wordpress_status"]
    page.wordpress_created_at = state["wordpress_created_at"]
    page.last_wordpress_sync_at = state["last_wordpress_sync_at"]
    session.add(page)
    for revision in revisions or []:
        session.delete(revision)
    session.commit()


def _revision_count(session: Session, page_id: int) -> int:
    return len(
        session.exec(
            select(GeneratedPageRevision).where(
                GeneratedPageRevision.generated_page_id == page_id
            )
        ).all()
    )


def _wordpress_draft_audit_count(session: Session, page_id: int) -> int:
    return len(
        session.exec(
            select(WordPressDraftAudit).where(
                WordPressDraftAudit.generated_page_id == page_id
            )
        ).all()
    )


def _fake_wordpress_get_client(*, status: str = "draft"):
    class FakeResponse:
        status_code = 200

        def json(self) -> dict:
            return {
                "id": 712,
                "status": status,
                "link": "https://wordpress.example/?page_id=712",
                "modified_gmt": "2026-07-10T00:00:00",
                "title": {"rendered": "Drywood Termite Tenting in Orlando, FL"},
                "slug": "drywood-termite-tenting-orlando-fl",
            }

    class FakeClient:
        def __init__(self, **_: object) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def get(self, *_: object, **__: object) -> FakeResponse:
            return FakeResponse()

    return FakeClient


def _fake_wordpress_update_client(
    *,
    sent: list[dict],
    status: str = "draft",
    response_status_code: int = 200,
):
    class FakeGetResponse:
        status_code = 200

        def json(self) -> dict:
            return {
                "id": 712,
                "status": status,
                "link": "https://wordpress.example/?page_id=712",
                "modified_gmt": "2026-07-10T00:00:00",
                "title": {"rendered": "Drywood Termite Tenting in Orlando, FL"},
                "slug": "drywood-termite-tenting-orlando-fl",
            }

    class FakePostResponse:
        status_code = response_status_code

        def json(self) -> dict:
            return {
                "id": 712,
                "status": status,
                "link": "https://wordpress.example/?page_id=712",
            }

    class FakeClient:
        def __init__(self, **_: object) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def get(self, *_: object, **__: object) -> FakeGetResponse:
            return FakeGetResponse()

        def post(self, url: str, *, json: dict, auth: object) -> FakePostResponse:
            sent.append({"url": url, "json": deepcopy(json), "auth": auth is not None})
            return FakePostResponse()

    return FakeClient


def _fake_wordpress_publish_client(sent: list[dict], pending_seen: list[bool]):
    class FakeGetResponse:
        status_code = 200

        def json(self) -> dict:
            return {
                "id": 712, "status": "draft", "link": "https://wordpress.example/?page_id=712",
                "modified_gmt": "2026-07-10T00:00:00",
                "title": {"rendered": "Drywood Termite Tenting in Orlando, FL"},
                "slug": "drywood-termite-tenting-orlando-fl",
            }

    class FakeResponse:
        status_code = 200

        def json(self) -> dict:
            return {"id": 712, "status": "publish", "link": "https://wordpress.example/orlando/"}

    class FakeClient:
        def __init__(self, **_: object) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def get(self, *_: object, **__: object) -> FakeGetResponse:
            return FakeGetResponse()

        def post(self, url: str, *, json: dict, auth: object) -> FakeResponse:
            with Session(engine) as verification_session:
                pending_seen.append(bool(verification_session.exec(select(WordPressPublishAudit).where(WordPressPublishAudit.status == "pending")).first()))
            sent.append({"url": url, "json": deepcopy(json), "auth": auth is not None})
            return FakeResponse()

    return FakeClient


def _page_by_slug(session: Session, slug: str) -> GeneratedPage:
    return session.exec(select(GeneratedPage).where(GeneratedPage.page_slug == slug)).one()


def _png_bytes(color: tuple[int, int, int] = (33, 92, 70)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (1200, 800), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _orlando_context(client: TestClient) -> dict[str, object]:
    pages = client.get("/api/generated-pages").json()
    page = next(item for item in pages if item["page_slug"] == "drywood-termite-tenting-orlando-fl")
    return {"page": page}


def _managed_path(filename: str, directory: str) -> Path:
    return test_media_path / directory / filename


def _managed_path_from_url(url: str) -> Path:
    return test_media_path / url.split("/media/", 1)[1]


def _create_reviewed_image(
    session: Session,
    page: GeneratedPage,
    suffix: str,
) -> ImageMetadata:
    image = ImageMetadata(
        business_id=page.business_id,
        service_id=page.service_id,
        city_id=page.city_id,
        county_id=page.county_id,
        file_name=f"{suffix}.jpg",
        image_title=suffix.replace("-", " ").title(),
        reviewed_alt_text=f"Reviewed {suffix.replace('-', ' ')} image",
        asset_url=f"/media/{suffix}.jpg",
        image_role="support",
        review_status="reviewed",
    )
    session.add(image)
    session.commit()
    session.refresh(image)
    return image


def _ensure_complete_page(
    session: Session,
    page: GeneratedPage,
) -> GeneratedPage:
    if not page.draft_content:
        generate_page_draft(session, page.id)
        session.refresh(page)
    return page
