import asyncio
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image
from pydantic import ValidationError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from starlette.datastructures import Headers

from app.core.config import Settings
from app.db import backup as backup_service
from app.db.backup import (
    BACKUP_VERSION,
    BackupValidationError,
    export_backup,
    load_backup,
    restore_backup,
)
from app.models import (
    Brand,
    BrandAsset,
    Business,
    Website,
    WebsiteIdentity,
    WebsiteIdentityAssetAssignment,
)
from app.schemas.brand_assets import IdentityAssetAssignmentCreate
from app.services import brand_assets as brand_asset_service
from app.services.brand_assets import (
    approve_brand_asset,
    assign_identity_asset,
    create_brand_asset,
    is_brand_asset_superseded,
    retire_brand_asset,
)
from app.services.media_uploads import store_uploaded_image


def _engine():
    return create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)


def _scope(session: Session, suffix: str):
    business = Business(company_name=f"Business {suffix}", business_type="Service", state="FL")
    session.add(business); session.flush()
    brand = Brand(business_id=business.id, brand_name=f"Brand {suffix}")
    session.add(brand); session.flush()
    website = Website(
        business_id=business.id, brand_id=brand.id, website_name=f"Website {suffix}",
        domain=f"{suffix}.example.test", public_url=f"https://{suffix}.example.test",
    )
    session.add(website); session.flush()
    identity = WebsiteIdentity(website_id=website.id, display_name=brand.brand_name, status="active")
    session.add(identity); session.flush(); session.commit()
    return business, brand, website, identity


def _asset(
    session: Session,
    business: Business,
    brand: Brand,
    *,
    key="primary-logo",
    kind="primary_logo",
    usage=None,
    version=1,
    status="approved",
    replaces_brand_asset_id=None,
):
    media_public_base = str(backup_service.get_settings().media_public_url).rstrip("/")
    value = BrandAsset(
        business_id=business.id, brand_id=brand.id, asset_key=key, version=version,
        asset_type=kind, variant_key="default", purpose="Identify the approved Brand.",
        approved_usage=usage or ["website_header"], restrictions=["social_preview"],
        accessibility_description="Flo-Zone Pest and Termite Solutions",
        original_filename="logo.png", stored_filename="logo.png",
        asset_url=f"{media_public_base}/originals/logo.png",
        optimized_url=f"{media_public_base}/optimized/logo-optimized.webp",
        thumbnail_url=f"{media_public_base}/thumbnails/logo-thumbnail.webp",
        mime_type="image/png", file_size=100, width=400, height=120,
        checksum_sha256="a" * 64,
        provenance_type="company_original",
        provenance_notes="Supplied directly by the company operator.",
        rights_status="owned",
        rights_holder=business.company_name,
        rights_notes="Company ownership confirmed by the operator.",
        status=status, created_by="operator", approved_by="operator" if status == "approved" else None,
        approved_at=datetime(2026, 8, 1, tzinfo=UTC) if status == "approved" else None,
        replaces_brand_asset_id=replaces_brand_asset_id,
    )
    session.add(value); session.flush(); return value


def test_identity_selection_requires_approved_compatible_same_brand_asset():
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, brand, website, identity = _scope(session, "one")
        asset = _asset(session, business, brand)
        session.commit()
        assignment = assign_identity_asset(
            session, identity.id, asset_id=asset.id, slot="header_logo",
            assigned_by="Shawn", rationale="Approved primary Website header identity.",
        )
        assert assignment.website_id == website.id
        assert assignment.brand_id == brand.id
        assert assignment.version == 1

        second_business, second_brand, _, _ = _scope(session, "two")
        foreign = _asset(session, second_business, second_brand, key="foreign-logo")
        session.commit()
        with pytest.raises(HTTPException, match="does not belong"):
            assign_identity_asset(
                session, identity.id, asset_id=foreign.id, slot="header_logo",
                assigned_by="Shawn", rationale=None,
            )


def test_assignment_replacement_preserves_versioned_operator_history():
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, brand, _, identity = _scope(session, "history")
        first = _asset(session, business, brand)
        second = _asset(session, business, brand, key="alternate-logo", kind="alternate_logo")
        session.commit()
        one = assign_identity_asset(session, identity.id, asset_id=first.id, slot="header_logo", assigned_by="One", rationale="Initial")
        two = assign_identity_asset(session, identity.id, asset_id=second.id, slot="header_logo", assigned_by="Two", rationale="Replacement")
        session.refresh(one)
        assert one.status == "replaced" and one.replaced_at is not None
        assert two.status == "active" and two.version == 2
        assert [row.assigned_by for row in session.exec(select(WebsiteIdentityAssetAssignment).order_by(WebsiteIdentityAssetAssignment.version)).all()] == ["One", "Two"]
        with pytest.raises(HTTPException, match="active Website Identity"):
            retire_brand_asset(session, second.id, retired_by="Two", rationale="No longer used")


def test_type_usage_and_approval_fail_closed():
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, brand, _, identity = _scope(session, "contracts")
        favicon = _asset(session, business, brand, key="favicon", kind="favicon", usage=["browser_tab"])
        pending = _asset(session, business, brand, key="pending")
        pending.status = "pending_review"
        session.commit()
        with pytest.raises(HTTPException, match="incompatible"):
            assign_identity_asset(session, identity.id, asset_id=favicon.id, slot="header_logo", assigned_by="Operator", rationale=None)
        with pytest.raises(HTTPException, match="only approved"):
            assign_identity_asset(session, identity.id, asset_id=pending.id, slot="header_logo", assigned_by="Operator", rationale=None)


def test_identity_selection_requires_operator_rationale():
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, brand, _, identity = _scope(session, "assignment-rationale")
        asset = _asset(session, business, brand)
        session.commit()
        with pytest.raises(HTTPException, match="Identity selection rationale is required"):
            assign_identity_asset(
                session,
                identity.id,
                asset_id=asset.id,
                slot="header_logo",
                assigned_by="Selection Operator",
                rationale=" ",
            )
        assert session.exec(select(WebsiteIdentityAssetAssignment)).all() == []


def test_identity_selection_schema_requires_nonblank_rationale():
    with pytest.raises(ValidationError):
        IdentityAssetAssignmentCreate(
            brand_asset_id=1,
            slot="header_logo",
            assigned_by="Selection Operator",
            rationale="   ",
        )
    with pytest.raises(ValidationError):
        IdentityAssetAssignmentCreate.model_validate({
            "brand_asset_id": 1,
            "slot": "header_logo",
            "assigned_by": "Selection Operator",
        })


def _image_bytes(format_name: str = "PNG", size: tuple[int, int] = (32, 16)) -> bytes:
    target = BytesIO()
    Image.new("RGB", size, "#245b46").save(target, format=format_name)
    return target.getvalue()


def _upload(filename: str, payload: bytes, content_type: str) -> UploadFile:
    return UploadFile(
        file=BytesIO(payload),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


def test_image_upload_records_detected_identity_and_rejects_unsafe_or_mismatched_files(tmp_path: Path):
    payload = _image_bytes()
    settings = Settings(
        _env_file=None,
        media_root=tmp_path,
        media_public_url="http://testserver/media",
        media_max_upload_bytes=1024 * 1024,
        media_max_pixels=1_000_000,
    )
    stored = asyncio.run(store_uploaded_image(_upload("temporary-logo.png", payload, "image/png"), settings))
    assert stored.original_filename == "temporary-logo.png"
    assert stored.mime_type == "image/png"
    assert stored.file_size == len(payload)
    assert (stored.width, stored.height) == (32, 16)
    assert stored.checksum_sha256 == sha256(payload).hexdigest()

    rejected = (
        ("../temporary-logo.png", payload, "image/png", 422),
        (" temporary-logo.png", payload, "image/png", 422),
        ("temporary-logo\n.png", payload, "image/png", 422),
        ("temporary-logo\x7f.png", payload, "image/png", 422),
        ("temporary-logo.png", payload, "image/jpeg", 415),
        ("temporary-logo.jpg", payload, "image/jpeg", 415),
        ("temporary-logo.png", b"not an image", "image/png", 415),
        ("temporary-logo.gif", _image_bytes("GIF"), "image/gif", 415),
    )
    for filename, body, content_type, status_code in rejected:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(store_uploaded_image(_upload(filename, body, content_type), settings))
        assert exc.value.status_code == status_code

    with pytest.raises(HTTPException) as too_large:
        asyncio.run(store_uploaded_image(
            _upload("large.png", payload, "image/png"),
            Settings(_env_file=None, media_root=tmp_path / "large", media_max_upload_bytes=8),
        ))
    assert too_large.value.status_code == 413
    with pytest.raises(HTTPException) as too_many_pixels:
        asyncio.run(store_uploaded_image(
            _upload("dimensions.png", payload, "image/png"),
            Settings(_env_file=None, media_root=tmp_path / "dimensions", media_max_pixels=100),
        ))
    assert too_many_pixels.value.status_code == 413


def test_create_requires_governed_rights_and_rejects_unknown_restrictions():
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, brand, _, _ = _scope(session, "rights")
        values = dict(
            file=_upload("owned-logo.png", _image_bytes(), "image/png"),
            business_id=business.id, brand_id=brand.id, asset_key="owned-logo",
            asset_type="primary_logo", variant_key="default",
            purpose="Identify the temporary test Brand.", approved_usage=["website_header"],
            restrictions=["social_preview"], accessibility_description="Temporary test Brand logo",
            provenance_type="company_original", provenance_notes="Supplied directly by the company operator.",
            rights_status="owned", rights_holder=None, rights_notes="Company ownership confirmed by the operator.",
            created_by="Smoke Operator", replaces_brand_asset_id=None,
        )
        with pytest.raises(HTTPException, match="rights holder"):
            asyncio.run(create_brand_asset(session, **values))
        values["rights_holder"] = "Temporary Test Business"
        values["restrictions"] = ["unsupported_surface"]
        with pytest.raises(HTTPException, match="Restrictions contain"):
            asyncio.run(create_brand_asset(session, **values))


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("provenance_notes", "provenance notes are required"),
        ("rights_holder", "rights holder is required"),
        ("rights_notes", "rights notes are required"),
    ],
)
def test_create_requires_complete_provenance_and_rights_for_every_classification(
    tmp_path: Path,
    field: str,
    message: str,
):
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, brand, _, _ = _scope(session, f"complete-{field}")
        values = dict(
            file=_upload("public-domain-mark.png", _image_bytes(), "image/png"),
            business_id=business.id,
            brand_id=brand.id,
            asset_key="public-domain-mark",
            asset_type="brand_mark",
            variant_key="default",
            purpose="Identify the governed Brand.",
            approved_usage=["website_header"],
            restrictions=["social_preview"],
            accessibility_description="Governed Brand mark",
            provenance_type="public_domain",
            provenance_notes="Operator identified the public-domain source.",
            rights_status="public_domain",
            rights_holder="Public-domain source identified by the operator",
            rights_notes="Operator confirmed the public-domain rights basis.",
            created_by="Source Operator",
            replaces_brand_asset_id=None,
        )
        values[field] = None
        with pytest.raises(HTTPException, match=message):
            asyncio.run(create_brand_asset(session, **values))


def test_create_requires_explicit_prohibited_usage():
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, brand, _, _ = _scope(session, "required-restrictions")
        with pytest.raises(HTTPException, match="restrictions are required"):
            asyncio.run(create_brand_asset(
                session,
                file=_upload("governed-logo.png", _image_bytes(), "image/png"),
                business_id=business.id,
                brand_id=brand.id,
                asset_key="governed-logo",
                asset_type="primary_logo",
                variant_key="default",
                purpose="Identify the governed Brand.",
                approved_usage=["website_header"],
                restrictions=[],
                accessibility_description="Governed Brand logo",
                provenance_type="company_original",
                provenance_notes="Supplied directly by the company operator.",
                rights_status="owned",
                rights_holder=business.company_name,
                rights_notes="Company ownership confirmed by the operator.",
                created_by="Source Operator",
                replaces_brand_asset_id=None,
            ))


def test_approved_replacement_supersedes_prior_version_for_new_assignments():
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, brand, website, identity = _scope(session, "superseded")
        first = _asset(session, business, brand)
        session.flush()
        replacement = _asset(
            session, business, brand, version=2, status="pending_review",
            replaces_brand_asset_id=first.id,
        )
        session.commit()
        assign_identity_asset(
            session, identity.id, asset_id=first.id, slot="header_logo",
            assigned_by="Original Operator", rationale="Valid before replacement approval",
        )

        second_website = Website(
            business_id=business.id, brand_id=brand.id, website_name="Second temporary site",
            domain="second-superseded.example.test", public_url="https://second-superseded.example.test",
        )
        session.add(second_website); session.flush()
        second_identity = WebsiteIdentity(website_id=second_website.id, display_name=brand.brand_name, status="active")
        session.add(second_identity); session.flush()
        replacement.status = "approved"; replacement.approved_by = "Replacement Operator"
        session.add(replacement); session.commit()
        with pytest.raises(HTTPException, match="superseded"):
            assign_identity_asset(
                session, second_identity.id, asset_id=first.id, slot="header_logo",
                assigned_by="Second Operator", rationale="Old version must not be reselected",
            )
        assert session.exec(select(WebsiteIdentityAssetAssignment).where(
            WebsiteIdentityAssetAssignment.website_id == website.id
        )).one().brand_asset_id == first.id


def test_three_version_chain_keeps_every_older_approved_version_superseded():
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, brand, _, identity = _scope(session, "three-version-chain")
        first = _asset(session, business, brand)
        second = _asset(
            session,
            business,
            brand,
            version=2,
            status="retired",
            replaces_brand_asset_id=first.id,
        )
        second.approved_by = "Second Version Operator"
        second.approved_at = datetime(2026, 8, 2, tzinfo=UTC)
        second.retired_by = "Second Version Operator"
        second.retirement_rationale = "Replaced by version 3."
        second.retired_at = datetime(2026, 8, 3, tzinfo=UTC)
        third = _asset(
            session,
            business,
            brand,
            version=3,
            replaces_brand_asset_id=second.id,
        )
        third.approved_at = datetime(2026, 8, 4, tzinfo=UTC)
        session.commit()

        assert is_brand_asset_superseded(session, first.id) is True
        assert is_brand_asset_superseded(session, second.id) is True
        assert is_brand_asset_superseded(session, third.id) is False
        with pytest.raises(HTTPException, match="superseded"):
            assign_identity_asset(
                session,
                identity.id,
                asset_id=first.id,
                slot="header_logo",
                assigned_by="Selection Operator",
                rationale="An older version must never reopen.",
            )


def test_long_replacement_chain_remains_monotonic_after_intermediate_retirements():
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, brand, _, _ = _scope(session, "long-version-chain")
        chain = [_asset(session, business, brand)]
        for version in range(2, 6):
            predecessor = chain[-1]
            status = "approved" if version == 5 else "retired"
            asset = _asset(
                session,
                business,
                brand,
                version=version,
                status=status,
                replaces_brand_asset_id=predecessor.id,
            )
            if status == "retired":
                asset.approved_by = f"Version {version} Operator"
                asset.approved_at = datetime(2026, 8, version, tzinfo=UTC)
                asset.retired_by = f"Version {version} Operator"
                asset.retirement_rationale = f"Replaced by version {version + 1}."
                asset.retired_at = datetime(2026, 8, version + 1, tzinfo=UTC)
            else:
                asset.approved_at = datetime(2026, 8, version, tzinfo=UTC)
            chain.append(asset)
        session.commit()

        assert [is_brand_asset_superseded(session, asset.id) for asset in chain] == [
            True,
            True,
            True,
            True,
            False,
        ]

        latest = chain[-1]
        latest.status = "retired"
        latest.retired_by = "Version 5 Operator"
        latest.retirement_rationale = "Retired after governed use."
        latest.retired_at = datetime(2026, 8, 6, tzinfo=UTC)
        session.add(latest)
        session.commit()
        assert [is_brand_asset_superseded(session, asset.id) for asset in chain[:-1]] == [
            True,
            True,
            True,
            True,
        ]


def _pending_managed_asset(
    session: Session,
    business: Business,
    brand: Brand,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[BrandAsset, Settings]:
    settings = Settings(
        _env_file=None,
        media_root=tmp_path,
        media_public_url="http://testserver/media",
        media_max_upload_bytes=1024 * 1024,
        media_max_pixels=1_000_000,
    )
    monkeypatch.setattr(brand_asset_service, "get_settings", lambda: settings)
    asset = asyncio.run(create_brand_asset(
        session,
        file=_upload("operator-supplied-logo.png", _image_bytes(), "image/png"),
        business_id=business.id,
        brand_id=brand.id,
        asset_key="operator-supplied-logo",
        asset_type="primary_logo",
        variant_key="default",
        purpose="Identify the approved Brand in the Website header.",
        approved_usage=["website_header"],
        restrictions=["social_preview"],
        accessibility_description="Approved Brand logo",
        provenance_type="company_original",
        provenance_notes="Supplied directly by the company operator.",
        rights_status="owned",
        rights_holder=business.company_name,
        rights_notes="Operator confirmed company ownership.",
        created_by="Source Operator",
        replaces_brand_asset_id=None,
    ))
    return asset, settings


def test_approval_rereads_managed_original_and_records_operator_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, brand, _, _ = _scope(session, "approval-revalidation")
        asset, _ = _pending_managed_asset(session, business, brand, tmp_path, monkeypatch)

        approved = approve_brand_asset(session, asset.id, "Approval Operator")

        assert approved.status == "approved"
        assert approved.approved_by == "Approval Operator"
        assert approved.approved_at is not None


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing", "Managed original is missing"),
        ("checksum", "checksum_sha256"),
        ("invalid_signature", "valid image"),
        ("detected_mime", "file signature"),
        ("recorded_width", "width"),
        ("recorded_size", "file_size"),
        ("unsafe_stored_name", "filename is unsafe"),
        ("unsafe_original_name", "filename is unsafe"),
        ("control_character_original_name", "filename is unsafe"),
        ("external_original_url", "original URL"),
        ("external_optimized_url", "optimized URL"),
        ("external_thumbnail_url", "thumbnail URL"),
        ("size_limit", "upload size limit"),
        ("pixel_limit", "pixel limit"),
    ],
)
def test_approval_fails_closed_when_managed_original_identity_is_not_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    message: str,
):
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, brand, _, _ = _scope(session, f"binary-{mutation}")
        asset, settings = _pending_managed_asset(session, business, brand, tmp_path, monkeypatch)
        original = settings.media_root / "originals" / asset.stored_filename
        if mutation == "missing":
            original.unlink()
        elif mutation == "checksum":
            original.write_bytes(_image_bytes(size=(31, 16)))
        elif mutation == "invalid_signature":
            original.write_bytes(b"not an image")
        elif mutation == "detected_mime":
            original.write_bytes(_image_bytes("JPEG"))
        elif mutation == "recorded_width":
            asset.width += 1
        elif mutation == "recorded_size":
            asset.file_size += 1
        elif mutation == "unsafe_stored_name":
            asset.stored_filename = "../operator-supplied-logo.png"
        elif mutation == "unsafe_original_name":
            asset.original_filename = "../operator-supplied-logo.png"
        elif mutation == "control_character_original_name":
            asset.original_filename = "operator-supplied-logo\n.png"
        elif mutation == "external_original_url":
            asset.asset_url = "https://unapproved.example.test/logo.png"
        elif mutation == "external_optimized_url":
            asset.optimized_url = "https://unapproved.example.test/logo.webp"
        elif mutation == "external_thumbnail_url":
            asset.thumbnail_url = "https://unapproved.example.test/logo.webp"
        elif mutation == "size_limit":
            stricter = settings.model_copy(update={"media_max_upload_bytes": 8})
            monkeypatch.setattr(brand_asset_service, "get_settings", lambda: stricter)
        elif mutation == "pixel_limit":
            stricter = settings.model_copy(update={"media_max_pixels": 100})
            monkeypatch.setattr(brand_asset_service, "get_settings", lambda: stricter)
        session.add(asset)
        session.commit()

        with pytest.raises(HTTPException, match=message):
            approve_brand_asset(session, asset.id, "Approval Operator")
        session.refresh(asset)
        assert asset.status == "pending_review"
        assert asset.approved_by is None
        assert asset.approved_at is None


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("ownership", "ownership is invalid"),
        ("purpose", "purpose is invalid"),
        ("usage", "approved usage is invalid"),
        ("empty_restrictions", "restrictions is invalid"),
        ("restrictions", "usage and restrictions conflict"),
        ("accessibility", "accessibility intent is invalid"),
        ("provenance", "provenance notes are incomplete"),
        ("rights", "rights holder is incomplete"),
        ("rights_notes", "rights notes are incomplete"),
        ("creator", "creator or source identity is invalid"),
    ],
)
def test_approval_fails_closed_when_governed_metadata_is_incomplete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    message: str,
):
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, brand, _, _ = _scope(session, f"governance-{mutation}")
        asset, _ = _pending_managed_asset(session, business, brand, tmp_path, monkeypatch)
        if mutation == "ownership":
            other = Business(company_name="Unrelated Business", business_type="Service", state="FL")
            session.add(other); session.flush()
            asset.business_id = other.id
        elif mutation == "purpose":
            asset.purpose = " "
        elif mutation == "usage":
            asset.approved_usage = []
        elif mutation == "empty_restrictions":
            asset.restrictions = []
        elif mutation == "restrictions":
            asset.restrictions = ["website_header"]
        elif mutation == "accessibility":
            asset.accessibility_description = " "
        elif mutation == "provenance":
            asset.provenance_type = "commissioned"
            asset.provenance_notes = None
        elif mutation == "rights":
            asset.rights_holder = None
        elif mutation == "rights_notes":
            asset.rights_notes = None
        elif mutation == "creator":
            asset.created_by = " "
        session.add(asset)
        session.commit()

        with pytest.raises(HTTPException, match=message):
            approve_brand_asset(session, asset.id, "Approval Operator")
        session.refresh(asset)
        assert asset.status == "pending_review"
        assert asset.approved_by is None
        assert asset.approved_at is None


def test_backup_051_includes_asset_and_assignment_provenance(tmp_path: Path):
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, brand, _, identity = _scope(session, "backup")
        asset = _asset(session, business, brand)
        session.commit()
        assign_identity_asset(session, identity.id, asset_id=asset.id, slot="header_logo", assigned_by="Operator", rationale="Approved")
        result = export_backup(session, backup_dir=tmp_path)
    payload = load_backup(Path(result["path"]))
    assert BACKUP_VERSION == "0.52"
    assert payload["metadata"]["version"] == "0.52"
    assert payload["data"]["brand_assets"][0]["purpose"]
    assert payload["data"]["brand_assets"][0]["accessibility_description"]
    assert payload["data"]["brand_assets"][0]["provenance_notes"]
    assert payload["data"]["brand_assets"][0]["rights_holder"]
    assert payload["data"]["brand_assets"][0]["rights_notes"]
    assert payload["data"]["website_identity_asset_assignments"][0]["assigned_by"] == "Operator"

    target_engine = _engine(); SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as target:
        restored = restore_backup(target, Path(result["path"]))
        restored_asset = target.exec(select(BrandAsset)).one()
        restored_assignment = target.exec(select(WebsiteIdentityAssetAssignment)).one()
        assert restored["status"] == "restored"
        assert payload["metadata"]["version"] == "0.52"
        assert restored_asset.checksum_sha256 == asset.checksum_sha256
        assert restored_asset.approved_usage == ["website_header"]
        assert restored_asset.restrictions == ["social_preview"]
        assert restored_assignment.assigned_by == "Operator"
        assert restored_assignment.brand_asset_id == restored_asset.id


def _governed_backup_payload(tmp_path: Path) -> tuple[dict, dict[str, int]]:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        one_business, one_brand, one_website, one_identity = _scope(session, "integrity-one")
        one_asset = _asset(session, one_business, one_brand, key="governed-logo")
        two_business, two_brand, two_website, two_identity = _scope(session, "integrity-two")
        two_asset = _asset(session, two_business, two_brand, key="other-logo")
        session.commit()
        assignment = assign_identity_asset(
            session,
            one_identity.id,
            asset_id=one_asset.id,
            slot="header_logo",
            assigned_by="Integrity Operator",
            rationale="Validate backup ownership boundaries.",
        )
        result = export_backup(session, backup_dir=tmp_path)
        identifiers = {
            "one_business": one_business.id,
            "one_brand": one_brand.id,
            "one_website": one_website.id,
            "one_identity": one_identity.id,
            "one_asset": one_asset.id,
            "two_business": two_business.id,
            "two_brand": two_brand.id,
            "two_website": two_website.id,
            "two_identity": two_identity.id,
            "two_asset": two_asset.id,
            "assignment": assignment.id,
        }
    return json.loads(Path(result["path"]).read_text(encoding="utf-8")), identifiers


def _write_tampered_backup(tmp_path: Path, payload: dict, name: str) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _record(payload: dict, group: str, record_id: int) -> dict:
    return next(item for item in payload["data"][group] if item["id"] == record_id)


def test_backup_050_rejects_non_lowercase_hex_asset_checksum(tmp_path: Path):
    payload, identifiers = _governed_backup_payload(tmp_path)
    asset = _record(payload, "brand_assets", identifiers["one_asset"])
    asset["checksum_sha256"] = "A" * 64

    with pytest.raises(BackupValidationError, match="invalid governed Brand Asset"):
        load_backup(_write_tampered_backup(tmp_path, payload, "checksum-tampered.json"))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("asset_key", "Unsafe Asset Key"),
        ("version", 0),
        ("approved_usage", ["Website_Header"]),
        ("restrictions", []),
        ("provenance_notes", None),
        ("rights_status", "unknown"),
        ("rights_holder", None),
        ("rights_notes", None),
        ("original_filename", "../logo.png"),
        ("original_filename", "logo\n.png"),
        ("original_filename", " logo.png"),
        ("stored_filename", "../logo.png"),
        ("stored_filename", "logo\x7f.png"),
        ("mime_type", "image/gif"),
        ("file_size", 0),
        ("width", 0),
        ("height", 0),
        ("asset_url", "https://unapproved.example.test/not-managed/logo.png"),
        ("asset_url", "javascript:/media/originals/logo.png"),
        ("asset_url", "file:///media/originals/logo.png"),
        ("asset_url", "//unapproved.example.test/media/originals/logo.png"),
        ("asset_url", "https://operator:secret@example.test/media/originals/logo.png"),
        ("asset_url", "https://different-origin.example.test/media/originals/logo.png"),
        ("optimized_url", "https://unapproved.example.test/media/optimized/wrong-optimized.webp"),
        ("thumbnail_url", "https://unapproved.example.test/media/thumbnails/wrong-thumbnail.webp"),
    ],
)
def test_backup_050_rejects_invalid_approved_asset_governance_or_binary_identity(
    tmp_path: Path,
    field: str,
    value: object,
):
    payload, identifiers = _governed_backup_payload(tmp_path)
    asset = _record(payload, "brand_assets", identifiers["one_asset"])
    asset[field] = value

    with pytest.raises(BackupValidationError, match="invalid governed Brand Asset"):
        load_backup(_write_tampered_backup(tmp_path, payload, f"asset-{field}-tampered.json"))


@pytest.mark.parametrize("limit", ["file_size", "pixels"])
def test_backup_050_rejects_asset_above_current_configured_binary_limits(
    tmp_path: Path,
    limit: str,
):
    payload, identifiers = _governed_backup_payload(tmp_path)
    asset = _record(payload, "brand_assets", identifiers["one_asset"])
    settings = backup_service.get_settings()
    if limit == "file_size":
        asset["file_size"] = settings.media_max_upload_bytes + 1
    else:
        asset["width"] = settings.media_max_pixels + 1
        asset["height"] = 1

    with pytest.raises(BackupValidationError, match="invalid governed Brand Asset"):
        load_backup(_write_tampered_backup(tmp_path, payload, f"asset-{limit}-limit.json"))


def test_backup_050_uses_configured_binary_limits_and_accepts_same_origin_http_urls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    payload, identifiers = _governed_backup_payload(tmp_path)
    asset = _record(payload, "brand_assets", identifiers["one_asset"])
    configured_size = 12 * 1024 * 1024
    asset["file_size"] = configured_size
    for governed_asset in payload["data"]["brand_assets"]:
        stored_filename = governed_asset["stored_filename"]
        stem = Path(stored_filename).stem
        governed_asset["asset_url"] = (
            f"https://assets.example.test/atlas-assets/originals/{stored_filename}"
        )
        governed_asset["optimized_url"] = (
            f"https://assets.example.test/atlas-assets/optimized/{stem}-optimized.webp"
        )
        governed_asset["thumbnail_url"] = (
            f"https://assets.example.test/atlas-assets/thumbnails/{stem}-thumbnail.webp"
        )
    custom_settings = Settings(
        _env_file=None,
        media_public_url="https://assets.example.test/atlas-assets",
        media_max_upload_bytes=20 * 1024 * 1024,
        media_max_pixels=40_000_000,
    )
    monkeypatch.setattr(backup_service, "get_settings", lambda: custom_settings)

    loaded = load_backup(_write_tampered_backup(tmp_path, payload, "custom-media-limits.json"))

    restored_asset = _record(loaded, "brand_assets", identifiers["one_asset"])
    assert restored_asset["file_size"] == configured_size
    assert restored_asset["asset_url"].startswith("https://assets.example.test/atlas-assets/")


@pytest.mark.parametrize("field", ["approved_by", "approved_at"])
def test_backup_050_rejects_approved_asset_without_provenance(tmp_path: Path, field: str):
    payload, identifiers = _governed_backup_payload(tmp_path)
    asset = _record(payload, "brand_assets", identifiers["one_asset"])
    asset[field] = None

    with pytest.raises(BackupValidationError, match="without approval provenance"):
        load_backup(_write_tampered_backup(tmp_path, payload, f"approved-{field}-tampered.json"))


@pytest.mark.parametrize("field", ["retired_by", "retirement_rationale", "retired_at"])
def test_backup_050_rejects_retired_asset_without_provenance(tmp_path: Path, field: str):
    payload, identifiers = _governed_backup_payload(tmp_path)
    asset = _record(payload, "brand_assets", identifiers["two_asset"])
    asset.update(
        status="retired",
        retired_by="Retirement Operator",
        retirement_rationale="Governed retirement test.",
        retired_at="2026-08-01T12:00:00+00:00",
    )
    asset[field] = None

    with pytest.raises(BackupValidationError, match="without retirement provenance"):
        load_backup(_write_tampered_backup(tmp_path, payload, f"retired-{field}-tampered.json"))


def test_backup_050_rejects_brand_asset_cross_business_ownership(tmp_path: Path):
    payload, identifiers = _governed_backup_payload(tmp_path)
    asset = _record(payload, "brand_assets", identifiers["one_asset"])
    asset["business_id"] = identifiers["two_business"]

    with pytest.raises(BackupValidationError, match="Business or Brand ownership boundary"):
        load_backup(_write_tampered_backup(tmp_path, payload, "asset-owner-tampered.json"))


@pytest.mark.parametrize(
    ("field", "value"),
    [("asset_key", "changed-key"), ("version", 3)],
)
def test_backup_050_rejects_invalid_replacement_chain(
    tmp_path: Path,
    field: str,
    value: str | int,
):
    payload, identifiers = _governed_backup_payload(tmp_path)
    original = _record(payload, "brand_assets", identifiers["one_asset"])
    replacement = _record(payload, "brand_assets", identifiers["two_asset"])
    replacement.update(
        business_id=identifiers["one_business"],
        brand_id=identifiers["one_brand"],
        asset_key=original["asset_key"],
        version=2,
        replaces_brand_asset_id=identifiers["one_asset"],
    )
    replacement[field] = value

    with pytest.raises(BackupValidationError, match="replacement crosses ownership"):
        load_backup(_write_tampered_backup(tmp_path, payload, f"replacement-{field}-tampered.json"))


def test_backup_050_rejects_root_asset_that_does_not_begin_at_version_one(tmp_path: Path):
    payload, identifiers = _governed_backup_payload(tmp_path)
    root_asset = _record(payload, "brand_assets", identifiers["one_asset"])
    root_asset["version"] = 2

    with pytest.raises(BackupValidationError, match="root Brand Asset must begin at version 1"):
        load_backup(_write_tampered_backup(tmp_path, payload, "root-version-tampered.json"))


@pytest.mark.parametrize("tamper", ["identity_website", "assignment_asset"])
def test_backup_050_rejects_cross_owner_identity_assignment(tmp_path: Path, tamper: str):
    payload, identifiers = _governed_backup_payload(tmp_path)
    assignment = _record(
        payload,
        "website_identity_asset_assignments",
        identifiers["assignment"],
    )
    if tamper == "identity_website":
        assignment["website_id"] = identifiers["two_website"]
    else:
        assignment["brand_asset_id"] = identifiers["two_asset"]

    with pytest.raises(BackupValidationError, match="Website, Business, or Brand ownership boundary"):
        load_backup(_write_tampered_backup(tmp_path, payload, f"assignment-{tamper}-tampered.json"))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("version", 0, "invalid Website Identity asset selection"),
        ("assigned_at", "not-a-timestamp", "invalid timestamp"),
    ],
)
def test_backup_050_rejects_invalid_assignment_version_or_timestamp(
    tmp_path: Path,
    field: str,
    value: str | int,
    message: str,
):
    payload, identifiers = _governed_backup_payload(tmp_path)
    assignment = _record(
        payload,
        "website_identity_asset_assignments",
        identifiers["assignment"],
    )
    assignment[field] = value

    with pytest.raises(BackupValidationError, match=message):
        load_backup(_write_tampered_backup(tmp_path, payload, f"assignment-{field}-tampered.json"))


def test_backup_050_rejects_replaced_assignment_without_lifecycle_provenance(tmp_path: Path):
    payload, identifiers = _governed_backup_payload(tmp_path)
    assignment = _record(
        payload,
        "website_identity_asset_assignments",
        identifiers["assignment"],
    )
    assignment["status"] = "replaced"
    assignment["replaced_at"] = None

    with pytest.raises(BackupValidationError, match="without replacement provenance"):
        load_backup(_write_tampered_backup(tmp_path, payload, "assignment-replaced-missing-time.json"))


def test_backup_050_rejects_identity_assignment_without_operator_rationale(tmp_path: Path):
    payload, identifiers = _governed_backup_payload(tmp_path)
    assignment = _record(
        payload,
        "website_identity_asset_assignments",
        identifiers["assignment"],
    )
    assignment["rationale"] = " "

    with pytest.raises(BackupValidationError, match="invalid Website Identity asset selection"):
        load_backup(_write_tampered_backup(tmp_path, payload, "assignment-rationale-tampered.json"))


def test_backup_050_rejects_replacement_timestamp_before_assignment(tmp_path: Path):
    payload, identifiers = _governed_backup_payload(tmp_path)
    assignment = _record(
        payload,
        "website_identity_asset_assignments",
        identifiers["assignment"],
    )
    assignment["status"] = "replaced"
    assignment["replaced_at"] = "2000-01-01T00:00:00+00:00"

    with pytest.raises(BackupValidationError, match="before its assignment"):
        load_backup(_write_tampered_backup(tmp_path, payload, "assignment-replaced-before-assigned.json"))


def test_backup_050_rejects_assignment_slot_contract_tampering(tmp_path: Path):
    payload, identifiers = _governed_backup_payload(tmp_path)
    asset = _record(payload, "brand_assets", identifiers["one_asset"])
    asset["asset_type"] = "favicon"

    with pytest.raises(BackupValidationError, match="slot type, usage, or restriction contract"):
        load_backup(_write_tampered_backup(tmp_path, payload, "assignment-slot-contract.json"))


def test_backup_050_rejects_assignment_that_predates_asset_approval(tmp_path: Path):
    payload, identifiers = _governed_backup_payload(tmp_path)
    asset = _record(payload, "brand_assets", identifiers["one_asset"])
    asset["approved_at"] = "2099-01-01T00:00:00+00:00"

    with pytest.raises(BackupValidationError, match="predates Brand Asset approval"):
        load_backup(_write_tampered_backup(tmp_path, payload, "assignment-before-approval.json"))


def test_backup_050_rejects_active_assignment_to_retired_asset(tmp_path: Path):
    payload, identifiers = _governed_backup_payload(tmp_path)
    asset = _record(payload, "brand_assets", identifiers["one_asset"])
    asset.update(
        status="retired",
        retired_by="Retirement Operator",
        retirement_rationale="Retired after governed use.",
        retired_at="2026-08-02T00:00:00+00:00",
    )

    with pytest.raises(BackupValidationError, match="currently approved asset"):
        load_backup(_write_tampered_backup(tmp_path, payload, "active-assignment-retired-asset.json"))


def test_backup_049_compatibility_does_not_require_brand_asset_groups(tmp_path: Path):
    payload, _ = _governed_backup_payload(tmp_path)
    payload["metadata"]["version"] = "0.49"
    for group in ("brand_assets", "website_identity_asset_assignments"):
        payload["metadata"]["table_counts"].pop(group)
        payload["data"].pop(group)

    loaded = load_backup(_write_tampered_backup(tmp_path, payload, "compatible-049.json"))

    assert loaded["metadata"]["version"] == "0.49"
    assert loaded["data"]["brand_assets"] == []
    assert loaded["data"]["website_identity_asset_assignments"] == []
