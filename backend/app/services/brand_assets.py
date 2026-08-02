import json
import re
from datetime import UTC, datetime

from fastapi import HTTPException, UploadFile
from sqlmodel import Session, select

from app.core.config import get_settings
from app.models import (
    Brand,
    BrandAsset,
    Website,
    WebsiteIdentity,
    WebsiteIdentityAssetAssignment,
)
from app.services.media_uploads import remove_stored_media_files, store_uploaded_image


ASSET_TYPES = {
    "primary_logo",
    "alternate_logo",
    "brand_mark",
    "favicon",
    "browser_icon",
    "apple_touch_icon",
    "open_graph_image",
}
APPROVED_USAGES = {
    "website_header",
    "website_footer",
    "browser_tab",
    "social_preview",
    "reports",
    "login_screen",
}
PROVENANCE_TYPES = {"company_original", "commissioned", "licensed", "public_domain"}
RIGHTS_STATUSES = {"owned", "licensed", "commissioned", "public_domain"}
IDENTITY_SLOTS = {
    "header_logo": ({"primary_logo", "alternate_logo", "brand_mark"}, "website_header"),
    "footer_logo": ({"primary_logo", "alternate_logo", "brand_mark"}, "website_footer"),
    "favicon": ({"favicon"}, "browser_tab"),
    "browser_icon": ({"browser_icon"}, "browser_tab"),
    "apple_touch_icon": ({"apple_touch_icon"}, "browser_tab"),
    "open_graph_image": ({"open_graph_image"}, "social_preview"),
}
ASSET_KEY_PATTERN = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")


def parse_string_list(raw: str, label: str) -> list[str]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"{label} must be a JSON array") from exc
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item.strip() for item in value):
        raise HTTPException(status_code=422, detail=f"{label} must be a non-empty array of strings")
    normalized = list(dict.fromkeys(item.strip().lower() for item in value))
    return normalized


def identity_asset_contract_error(asset: BrandAsset, slot: str) -> str | None:
    """Return the exact semantic-slot incompatibility without changing state."""

    normalized_slot = slot.strip().lower()
    contract = IDENTITY_SLOTS.get(normalized_slot)
    if contract is None:
        return "Unsupported Website Identity asset slot"
    allowed_types, required_usage = contract
    if asset.asset_type not in allowed_types or required_usage not in asset.approved_usage:
        return "Brand Asset type or approved usage is incompatible with this identity slot"
    if required_usage in asset.restrictions:
        return "Brand Asset restrictions prohibit this identity slot"
    return None


def is_brand_asset_superseded(session: Session, asset_id: int) -> bool:
    """An approved replacement closes only new selection of the prior version."""

    return session.exec(
        select(BrandAsset).where(
            BrandAsset.replaces_brand_asset_id == asset_id,
            BrandAsset.status == "approved",
        )
    ).first() is not None


async def create_brand_asset(
    session: Session,
    *,
    file: UploadFile,
    business_id: int,
    brand_id: int,
    asset_key: str,
    asset_type: str,
    variant_key: str,
    purpose: str,
    approved_usage: list[str],
    restrictions: list[str],
    accessibility_description: str,
    provenance_type: str,
    provenance_notes: str | None,
    rights_status: str,
    rights_holder: str | None,
    rights_notes: str | None,
    created_by: str,
    replaces_brand_asset_id: int | None,
) -> BrandAsset:
    brand = session.get(Brand, brand_id)
    if not brand or brand.business_id != business_id:
        raise HTTPException(status_code=422, detail="Brand does not belong to the selected business")
    key = asset_key.strip().lower()
    if not ASSET_KEY_PATTERN.fullmatch(key):
        raise HTTPException(status_code=422, detail="Asset key must contain only lowercase letters, numbers, hyphens, or underscores")
    kind = asset_type.strip().lower()
    if kind not in ASSET_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported Brand Asset type")
    approved_usage = list(dict.fromkeys(value.strip().lower() for value in approved_usage if value.strip()))
    restrictions = list(dict.fromkeys(value.strip().lower() for value in restrictions if value.strip()))
    if not approved_usage or not set(approved_usage) <= APPROVED_USAGES:
        raise HTTPException(status_code=422, detail="Approved usage contains unsupported values")
    if not set(restrictions) <= APPROVED_USAGES:
        raise HTTPException(status_code=422, detail="Restrictions contain unsupported values")
    if set(approved_usage) & set(restrictions):
        raise HTTPException(status_code=422, detail="Approved usage and restrictions cannot overlap")
    if provenance_type not in PROVENANCE_TYPES or rights_status not in RIGHTS_STATUSES:
        raise HTTPException(status_code=422, detail="Approved provenance and rights information is required")
    if provenance_type in {"commissioned", "licensed", "public_domain"} and not _clean(provenance_notes):
        raise HTTPException(status_code=422, detail="Provenance notes are required for this source classification")
    if rights_status in {"owned", "licensed", "commissioned"} and not _clean(rights_holder):
        raise HTTPException(status_code=422, detail="Rights holder is required for this rights status")
    if rights_status == "licensed" and not _clean(rights_notes):
        raise HTTPException(status_code=422, detail="Rights notes are required for a licensed asset")
    required_text = {
        "purpose": purpose,
        "accessibility description": accessibility_description,
        "created by": created_by,
    }
    for label, value in required_text.items():
        if not value.strip():
            raise HTTPException(status_code=422, detail=f"Brand Asset {label} is required")

    version = 1
    replacement = None
    if replaces_brand_asset_id is not None:
        replacement = session.get(BrandAsset, replaces_brand_asset_id)
        if not replacement or replacement.brand_id != brand_id or replacement.asset_key != key:
            raise HTTPException(status_code=422, detail="Replacement must reference the same Brand and asset key")
        version = replacement.version + 1
    existing = session.exec(
        select(BrandAsset).where(BrandAsset.brand_id == brand_id, BrandAsset.asset_key == key).order_by(BrandAsset.version.desc())
    ).first()
    if existing and replacement is None:
        raise HTTPException(status_code=409, detail="Asset key already exists; create an explicit replacement version")
    if existing and version <= existing.version:
        raise HTTPException(status_code=409, detail="Replacement version is not current")

    settings = get_settings()
    stored = await store_uploaded_image(file, settings)
    original_url = f"{settings.media_public_url.rstrip('/')}/originals/{stored.stored_filename}"
    asset = BrandAsset(
        business_id=business_id,
        brand_id=brand_id,
        asset_key=key,
        version=version,
        asset_type=kind,
        variant_key=variant_key.strip().lower() or "default",
        purpose=purpose.strip(),
        approved_usage=approved_usage,
        restrictions=restrictions,
        accessibility_description=accessibility_description.strip(),
        original_filename=stored.original_filename,
        stored_filename=stored.stored_filename,
        asset_url=original_url,
        optimized_url=stored.optimized_url,
        thumbnail_url=stored.thumbnail_url,
        mime_type=stored.mime_type,
        file_size=stored.file_size,
        width=stored.width,
        height=stored.height,
        checksum_sha256=stored.checksum_sha256,
        provenance_type=provenance_type,
        provenance_notes=_clean(provenance_notes),
        rights_status=rights_status,
        rights_holder=_clean(rights_holder),
        rights_notes=_clean(rights_notes),
        status="pending_review",
        created_by=created_by.strip(),
        replaces_brand_asset_id=replaces_brand_asset_id,
    )
    try:
        session.add(asset)
        session.commit()
        session.refresh(asset)
    except Exception:
        session.rollback()
        remove_stored_media_files(stored, settings)
        raise
    return asset


def approve_brand_asset(session: Session, asset_id: int, approved_by: str) -> BrandAsset:
    asset = _asset(session, asset_id)
    approved_by = _required_operator(approved_by, "Asset approval operator")
    if asset.status not in {"draft", "pending_review"}:
        raise HTTPException(status_code=409, detail="Only a draft or pending-review asset can be approved")
    asset.status = "approved"
    asset.approved_by = approved_by
    asset.approved_at = datetime.now(UTC)
    asset.updated_at = datetime.now(UTC)
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


def assign_identity_asset(
    session: Session,
    identity_id: int,
    *,
    asset_id: int,
    slot: str,
    assigned_by: str,
    rationale: str | None,
) -> WebsiteIdentityAssetAssignment:
    identity = session.get(WebsiteIdentity, identity_id)
    if not identity:
        raise HTTPException(status_code=404, detail="Website Identity not found")
    website = session.get(Website, identity.website_id)
    if not website or website.brand_id is None:
        raise HTTPException(status_code=409, detail="Website must select a Brand before assigning identity assets")
    asset = _asset(session, asset_id)
    if asset.status != "approved":
        raise HTTPException(status_code=409, detail="Website Identity may select only approved Brand Assets")
    if is_brand_asset_superseded(session, asset.id):
        raise HTTPException(status_code=409, detail="A superseded Brand Asset version cannot be newly assigned")
    if asset.brand_id != website.brand_id or asset.business_id != website.business_id:
        raise HTTPException(status_code=422, detail="Brand Asset does not belong to this Website's Business and Brand")
    normalized_slot = slot.strip().lower()
    contract_error = identity_asset_contract_error(asset, normalized_slot)
    if contract_error:
        raise HTTPException(status_code=422, detail=contract_error)
    assigned_by = _required_operator(assigned_by, "Identity selection operator")

    now = datetime.now(UTC)
    previous = session.exec(
        select(WebsiteIdentityAssetAssignment).where(
            WebsiteIdentityAssetAssignment.website_identity_id == identity_id,
            WebsiteIdentityAssetAssignment.slot == normalized_slot,
            WebsiteIdentityAssetAssignment.status == "active",
        )
    ).first()
    if previous and previous.brand_asset_id == asset_id:
        raise HTTPException(status_code=409, detail="This Brand Asset is already active in the selected slot")
    version = 1
    latest = session.exec(
        select(WebsiteIdentityAssetAssignment).where(
            WebsiteIdentityAssetAssignment.website_identity_id == identity_id,
            WebsiteIdentityAssetAssignment.slot == normalized_slot,
        ).order_by(WebsiteIdentityAssetAssignment.version.desc())
    ).first()
    if latest:
        version = latest.version + 1
    if previous:
        previous.status = "replaced"
        previous.replaced_at = now
        previous.updated_at = now
        session.add(previous)
    assignment = WebsiteIdentityAssetAssignment(
        website_identity_id=identity_id,
        website_id=website.id,
        brand_id=website.brand_id,
        brand_asset_id=asset.id,
        slot=normalized_slot,
        version=version,
        status="active",
        assigned_by=assigned_by,
        rationale=_clean(rationale),
        assigned_at=now,
    )
    session.add(assignment)
    session.commit()
    session.refresh(assignment)
    return assignment


def retire_brand_asset(session: Session, asset_id: int, *, retired_by: str, rationale: str) -> BrandAsset:
    asset = _asset(session, asset_id)
    retired_by = _required_operator(retired_by, "Asset retirement operator")
    rationale = _required_operator(rationale, "Asset retirement rationale")
    active = session.exec(
        select(WebsiteIdentityAssetAssignment).where(
            WebsiteIdentityAssetAssignment.brand_asset_id == asset_id,
            WebsiteIdentityAssetAssignment.status == "active",
        )
    ).first()
    if active:
        raise HTTPException(status_code=409, detail="Replace or retire active Website Identity assignments before retiring this asset")
    if asset.status == "retired":
        raise HTTPException(status_code=409, detail="Brand Asset is already retired")
    asset.status = "retired"
    asset.retired_by = retired_by
    asset.retirement_rationale = rationale
    asset.retired_at = datetime.now(UTC)
    asset.updated_at = asset.retired_at
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


def _asset(session: Session, asset_id: int) -> BrandAsset:
    asset = session.get(BrandAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Brand Asset not found")
    return asset


def _clean(value: str | None) -> str | None:
    cleaned = value.strip() if value else ""
    return cleaned or None


def _required_operator(value: str, label: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail=f"{label} is required")
    return cleaned
