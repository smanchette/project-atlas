from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
from zipfile import ZipFile

import pytest
from PIL import Image

os.environ["DATABASE_URL"] = "sqlite:///./test_atlas.db"
os.environ["MEDIA_ROOT"] = "test_media"
os.environ["MEDIA_PUBLIC_URL"] = "http://testserver/media"
test_db_path = Path("test_atlas.db")
if test_db_path.exists():
    test_db_path.unlink()
test_media_path = Path("test_media")
if test_media_path.exists():
    shutil.rmtree(test_media_path)

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
from app.services import media_backup
from app.services import program_backup
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
    assert payload["metadata"]["version"] == "0.13"
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
    monkeypatch.setattr(program_backup, "PROJECT_ROOT", project_root)

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
    monkeypatch.setattr(program_backup, "PROJECT_ROOT", project_root)

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

    assert payload["metadata"]["version"] == "0.13"
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

    assert payload_json["metadata"]["version"] == "0.13"
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


def _database_counts(session: Session) -> dict[str, int]:
    return {
        group: len(session.exec(select(model)).all())
        for group, model in BACKUP_MODELS.items()
    }


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
        "backend/.env": "DATABASE_URL=secret\n",
        "backend/app/.env.local": "SECRET=hidden\n",
        "backend/app/private_key.pem": "private\n",
        "backend/app/secrets.json": "{}\n",
        "backend/app/cache.db": "database\n",
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


def _revision_count(session: Session, page_id: int) -> int:
    return len(
        session.exec(
            select(GeneratedPageRevision).where(
                GeneratedPageRevision.generated_page_id == page_id
            )
        ).all()
    )


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
