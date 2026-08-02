from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlmodel import Session, select

from app.db.session import get_session
from app.models import BrandAsset, Website, WebsiteIdentity, WebsiteIdentityAssetAssignment
from app.schemas.brand_assets import (
    BrandAssetApprovalRequest,
    BrandAssetRead,
    BrandAssetRetirementRequest,
    IdentityAssetAssignmentCreate,
    IdentityAssetAssignmentRead,
    WebsiteIdentityAssetsRead,
)
from app.services.brand_assets import (
    IDENTITY_SLOTS,
    approve_brand_asset,
    assign_identity_asset,
    create_brand_asset,
    identity_asset_contract_error,
    parse_string_list,
    retire_brand_asset,
)

router = APIRouter(tags=["brand assets"])


@router.get("/brand-assets", response_model=list[BrandAssetRead])
def list_brand_assets(
    brand_id: int | None = Query(default=None),
    business_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[BrandAsset]:
    statement = select(BrandAsset)
    if brand_id is not None:
        statement = statement.where(BrandAsset.brand_id == brand_id)
    if business_id is not None:
        statement = statement.where(BrandAsset.business_id == business_id)
    if status is not None:
        statement = statement.where(BrandAsset.status == status)
    return list(session.exec(statement.order_by(BrandAsset.asset_key, BrandAsset.version.desc())).all())


@router.post("/brand-assets/upload", response_model=BrandAssetRead, status_code=201)
async def upload_brand_asset(
    file: UploadFile = File(...),
    business_id: int = Form(...),
    brand_id: int = Form(...),
    asset_key: str = Form(...),
    asset_type: str = Form(...),
    variant_key: str = Form(default="default"),
    purpose: str = Form(...),
    approved_usage: str = Form(...),
    restrictions: str = Form(default="[]"),
    accessibility_description: str = Form(...),
    provenance_type: str = Form(...),
    provenance_notes: str | None = Form(default=None),
    rights_status: str = Form(...),
    rights_holder: str | None = Form(default=None),
    rights_notes: str | None = Form(default=None),
    created_by: str = Form(...),
    replaces_brand_asset_id: int | None = Form(default=None),
    session: Session = Depends(get_session),
) -> BrandAsset:
    usages = parse_string_list(approved_usage, "Approved usage")
    restriction_values = [] if restrictions.strip() == "[]" else parse_string_list(restrictions, "Restrictions")
    return await create_brand_asset(
        session,
        file=file,
        business_id=business_id,
        brand_id=brand_id,
        asset_key=asset_key,
        asset_type=asset_type,
        variant_key=variant_key,
        purpose=purpose,
        approved_usage=usages,
        restrictions=restriction_values,
        accessibility_description=accessibility_description,
        provenance_type=provenance_type.strip().lower(),
        provenance_notes=provenance_notes,
        rights_status=rights_status.strip().lower(),
        rights_holder=rights_holder,
        rights_notes=rights_notes,
        created_by=created_by,
        replaces_brand_asset_id=replaces_brand_asset_id,
    )


@router.post("/brand-assets/{asset_id}/approve", response_model=BrandAssetRead)
def approve_asset(asset_id: int, payload: BrandAssetApprovalRequest, session: Session = Depends(get_session)) -> BrandAsset:
    return approve_brand_asset(session, asset_id, payload.approved_by)


@router.post("/brand-assets/{asset_id}/retire", response_model=BrandAssetRead)
def retire_asset(asset_id: int, payload: BrandAssetRetirementRequest, session: Session = Depends(get_session)) -> BrandAsset:
    return retire_brand_asset(
        session,
        asset_id,
        retired_by=payload.retired_by,
        rationale=payload.rationale,
    )


@router.get("/website-identities/{identity_id}/assets", response_model=WebsiteIdentityAssetsRead)
def identity_assets(identity_id: int, session: Session = Depends(get_session)) -> WebsiteIdentityAssetsRead:
    identity = session.get(WebsiteIdentity, identity_id)
    if not identity:
        raise HTTPException(status_code=404, detail="Website Identity not found")
    website = session.get(Website, identity.website_id)
    if not website or website.brand_id is None:
        raise HTTPException(status_code=409, detail="Website does not have a selected Brand")
    rows = list(session.exec(select(WebsiteIdentityAssetAssignment).where(
        WebsiteIdentityAssetAssignment.website_identity_id == identity_id
    ).order_by(WebsiteIdentityAssetAssignment.slot, WebsiteIdentityAssetAssignment.version.desc())).all())
    history: list[IdentityAssetAssignmentRead] = []
    active: dict[str, IdentityAssetAssignmentRead] = {}
    for row in rows:
        value = IdentityAssetAssignmentRead.model_validate(row)
        asset = session.get(BrandAsset, row.brand_asset_id)
        if (
            not asset
            or row.website_id != website.id
            or row.brand_id != website.brand_id
            or asset.business_id != website.business_id
            or asset.brand_id != website.brand_id
            or (
                row.status == "active"
                and (
                    asset.status != "approved"
                    or identity_asset_contract_error(asset, row.slot) is not None
                )
            )
        ):
            raise HTTPException(status_code=409, detail=f"Website Identity selection for {row.slot} is invalid")
        value.asset = BrandAssetRead.model_validate(asset)
        history.append(value)
        if row.status == "active":
            active[row.slot] = value
    return WebsiteIdentityAssetsRead(
        website_identity_id=identity_id,
        website_id=website.id,
        brand_id=website.brand_id,
        active=active,
        history=history,
        missing_slots=sorted(set(IDENTITY_SLOTS) - set(active)),
    )


@router.post("/website-identities/{identity_id}/assets/assign", response_model=IdentityAssetAssignmentRead, status_code=201)
def assign_asset(
    identity_id: int,
    payload: IdentityAssetAssignmentCreate,
    session: Session = Depends(get_session),
) -> IdentityAssetAssignmentRead:
    row = assign_identity_asset(
        session,
        identity_id,
        asset_id=payload.brand_asset_id,
        slot=payload.slot,
        assigned_by=payload.assigned_by,
        rationale=payload.rationale,
    )
    value = IdentityAssetAssignmentRead.model_validate(row)
    value.asset = BrandAssetRead.model_validate(session.get(BrandAsset, row.brand_asset_id))
    return value
