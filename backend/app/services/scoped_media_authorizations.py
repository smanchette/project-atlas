from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from sqlmodel import Session, select

from app.models import (
    ImageMetadata,
    PageComposition,
    PageImageAssignment,
    PlannedPage,
    PlannedPageMediaRequirement,
    ScopedMediaAuthorization,
    SitePlan,
    Website,
)
from app.schemas.scoped_media_authorizations import (
    ScopedMediaAuthorizationInternalCreate,
    ScopedMediaAuthorizationRead,
    ScopedMediaAuthorizationRequest,
    normalize_scoped_media_authorization_terms,
    scoped_media_approval_fingerprint,
    scoped_media_authorization_fingerprint,
    validate_scoped_media_authorization_policy_terms,
)


class ScopedMediaAuthorizationError(ValueError):
    """A scoped media authorization is absent, stale, corrupt, or out of scope."""


def list_scoped_media_authorizations(
    session: Session,
    plan_id: int,
    *,
    media_requirement_id: int | None = None,
    image_metadata_id: int | None = None,
) -> list[ScopedMediaAuthorizationRead]:
    if session.get(SitePlan, plan_id) is None:
        raise ScopedMediaAuthorizationError("Site Plan was not found.")
    statement = select(ScopedMediaAuthorization).where(
        ScopedMediaAuthorization.site_plan_id == plan_id
    )
    if media_requirement_id is not None:
        statement = statement.where(
            ScopedMediaAuthorization.media_requirement_id == media_requirement_id
        )
    if image_metadata_id is not None:
        statement = statement.where(
            ScopedMediaAuthorization.image_metadata_id == image_metadata_id
        )
    rows = list(
        session.exec(
            statement.order_by(
                ScopedMediaAuthorization.media_requirement_id,
                ScopedMediaAuthorization.authorization_version,
                ScopedMediaAuthorization.id,
            )
        ).all()
    )
    return [ScopedMediaAuthorizationRead.model_validate(row) for row in rows]


def current_scoped_media_authorization(
    session: Session,
    media_requirement_id: int,
) -> ScopedMediaAuthorization | None:
    rows = _authorization_history(session, media_requirement_id)
    _validate_authorization_chain(rows)
    return rows[-1] if rows and rows[-1].lifecycle_status == "current" else None


def asset_requires_exact_scoped_use(
    session: Session,
    asset: ImageMetadata,
) -> bool:
    """Return true when legacy/fallback use would bypass durable scope."""

    if getattr(asset, "usage_authorization_mode", "contract_default") == "scoped_required":
        return True
    return session.exec(
        select(ScopedMediaAuthorization.id).where(
            ScopedMediaAuthorization.image_metadata_id == asset.id,
            ScopedMediaAuthorization.media_version == asset.media_version,
        )
    ).first() is not None


def create_scoped_media_authorization(
    session: Session,
    plan_id: int,
    payload: ScopedMediaAuthorizationRequest,
) -> ScopedMediaAuthorizationRead:
    """Create the next server-derived authorization version for one exact use.

    The operator supplies policy intent only. All scope, approval, version, time,
    lineage, and integrity values are read from the current durable records.
    """

    plan = session.get(SitePlan, plan_id)
    if plan is None:
        raise ScopedMediaAuthorizationError("Site Plan was not found.")
    website = session.get(Website, plan.website_id)
    if website is None:
        raise ScopedMediaAuthorizationError("Site Plan Website was not found.")
    requirement = session.exec(
        select(PlannedPageMediaRequirement)
        .where(PlannedPageMediaRequirement.id == payload.media_requirement_id)
        .with_for_update()
    ).one_or_none()
    if requirement is None:
        raise ScopedMediaAuthorizationError("Media requirement was not found.")
    page = session.exec(
        select(PlannedPage)
        .where(PlannedPage.id == requirement.planned_page_id)
        .with_for_update()
    ).one_or_none()
    if page is None:
        raise ScopedMediaAuthorizationError("Media requirement Planned Page was not found.")
    # Serialize every authorization decision for one asset version. This makes the
    # read/check/write policy evaluation atomic on PostgreSQL and prevents two
    # concurrent requests from authorizing incompatible requirement-only or
    # page-only scopes.
    asset = session.exec(
        select(ImageMetadata)
        .where(ImageMetadata.id == payload.image_metadata_id)
        .with_for_update()
    ).one_or_none()
    if asset is None:
        raise ScopedMediaAuthorizationError("Governed media asset was not found.")
    assignment = None
    if payload.page_image_assignment_id is not None:
        assignment = session.exec(
            select(PageImageAssignment)
            .where(PageImageAssignment.id == payload.page_image_assignment_id)
            .with_for_update()
        ).one_or_none()
        if assignment is None:
            raise ScopedMediaAuthorizationError(
                "Governed media assignment was not found."
            )

    _require_current_scope(plan, website, page, requirement, asset)
    _require_current_approval(asset)
    if _asset_has_approved_successor(session, asset):
        raise ScopedMediaAuthorizationError(
            "A superseded governed media version cannot receive a scoped authorization."
        )
    if (
        requirement.version != payload.expected_requirement_version
        or requirement.contract_version
        != payload.expected_placement_contract_version
    ):
        raise ScopedMediaAuthorizationError(
            "Media requirement or placement-contract version changed."
        )
    approval_values = {
        "image_metadata_id": asset.id,
        "asset_website_id": asset.website_id,
        "asset_business_id": asset.business_id,
        "media_version": asset.media_version,
        "asset_checksum_sha256": asset.checksum_sha256,
        "approval_version": asset.approval_version,
        "asset_approved_by": asset.approved_by,
        "asset_approved_at": asset.approved_at,
        "usage_authorization_mode": asset.usage_authorization_mode,
        "required_authorization_terms": getattr(
            asset,
            "required_authorization_terms",
            [],
        ),
    }
    approval_fingerprint = scoped_media_approval_fingerprint(approval_values)
    if (
        asset.media_version != payload.expected_media_version
        or asset.checksum_sha256 != payload.expected_asset_checksum_sha256
        or asset.approval_version != payload.expected_approval_version
        or approval_fingerprint != payload.expected_approval_fingerprint
    ):
        raise ScopedMediaAuthorizationError(
            "Governed media asset or approval identity changed."
        )
    if assignment is not None:
        _require_exact_assignment(assignment, page, requirement, asset)
        if assignment.assignment_version != payload.expected_assignment_version:
            raise ScopedMediaAuthorizationError(
                "Governed media assignment version changed."
            )
    _validate_policy_terms(
        payload.reuse_policy,
        payload.authorization_terms,
        required_terms=getattr(asset, "required_authorization_terms", []),
    )
    _prevent_restrictive_cross_scope_authorization(
        session,
        asset,
        page,
        requirement,
        payload.reuse_policy,
    )

    history = _authorization_history(
        session,
        requirement.id or 0,
        lock=True,
    )
    _validate_authorization_chain(history)
    latest = history[-1] if history else None
    current = latest if latest and latest.lifecycle_status == "current" else None
    if current is None and payload.expected_current_authorization_fingerprint is not None:
        raise ScopedMediaAuthorizationError(
            "Expected scoped authorization no longer exists."
        )
    if current is not None and (
        payload.expected_current_authorization_fingerprint
        != current.authorization_fingerprint
    ):
        raise ScopedMediaAuthorizationError(
            "Current scoped authorization changed or supersession was not explicit."
        )
    version = (latest.authorization_version + 1) if latest else 1
    now = datetime.now(UTC)
    values = {
        "website_id": website.id,
        "site_plan_id": plan.id,
        "planned_page_id": page.id,
        "generated_page_id": page.generated_page_id,
        "media_requirement_id": requirement.id,
        "requirement_version": requirement.version,
        "placement_key": requirement.placement_key,
        "placement_contract_version": requirement.contract_version,
        "image_metadata_id": asset.id,
        "media_version": asset.media_version,
        "asset_checksum_sha256": asset.checksum_sha256,
        "approval_version": asset.approval_version,
        "asset_approved_by": asset.approved_by,
        "asset_approved_at": asset.approved_at,
        "approval_fingerprint": approval_fingerprint,
        "page_image_assignment_id": assignment.id if assignment else None,
        "assignment_version": assignment.assignment_version if assignment else None,
        "reuse_policy": payload.reuse_policy,
        "authorization_terms": normalize_scoped_media_authorization_terms(
            payload.authorization_terms
        ),
        "authorized_by": payload.authorized_by,
        "authorization_rationale": payload.authorization_rationale,
        "authorized_at": now,
        "authorization_version": version,
        "lifecycle_status": "current",
        "supersedes_authorization_id": latest.id if latest else None,
    }
    values["authorization_fingerprint"] = scoped_media_authorization_fingerprint(
        values
    )
    durable = ScopedMediaAuthorizationInternalCreate.model_validate(values)
    if current is not None:
        current.lifecycle_status = "superseded"
        current.updated_at = now
        session.add(current)
        session.flush()
    row = ScopedMediaAuthorization(**durable.model_dump())
    session.add(row)
    if assignment is not None:
        _mark_composition_stale(session, page.id or 0)
    session.commit()
    session.refresh(row)
    return ScopedMediaAuthorizationRead.model_validate(row)


def bind_scoped_media_authorization_to_assignment(
    session: Session,
    *,
    authorization: ScopedMediaAuthorization,
    assignment: PageImageAssignment,
) -> ScopedMediaAuthorization:
    """Append an assignment-bound successor without rewriting decision evidence."""

    requirement = session.exec(
        select(PlannedPageMediaRequirement)
        .where(
            PlannedPageMediaRequirement.id
            == authorization.media_requirement_id
        )
        .with_for_update()
    ).one_or_none()
    page = session.exec(
        select(PlannedPage)
        .where(PlannedPage.id == authorization.planned_page_id)
        .with_for_update()
    ).one_or_none()
    asset = session.exec(
        select(ImageMetadata)
        .where(ImageMetadata.id == authorization.image_metadata_id)
        .with_for_update()
    ).one_or_none()
    locked_assignment = session.exec(
        select(PageImageAssignment)
        .where(PageImageAssignment.id == assignment.id)
        .with_for_update()
    ).one_or_none()
    history = _authorization_history(
        session,
        authorization.media_requirement_id,
        lock=True,
    )
    _validate_authorization_chain(history)
    locked_authorization = history[-1] if history else None
    if (
        locked_authorization is None
        or locked_authorization.id != authorization.id
        or locked_authorization.lifecycle_status != "current"
    ):
        raise ScopedMediaAuthorizationError(
            "Only a current scoped authorization can bind an assignment."
        )
    authorization = locked_authorization
    predecessor_assignment: PageImageAssignment | None = None
    if authorization.page_image_assignment_id is not None:
        if (
            authorization.page_image_assignment_id == assignment.id
            and authorization.assignment_version == assignment.assignment_version
        ):
            if locked_assignment is None:
                raise ScopedMediaAuthorizationError(
                    "Scoped authorization assignment is missing."
                )
            assignment = locked_assignment
            website = session.get(Website, authorization.website_id)
            if (
                asset is None
                or requirement is None
                or page is None
                or website is None
            ):
                raise ScopedMediaAuthorizationError(
                    "Scoped authorization binding records are incomplete."
                )
            errors = scoped_media_authorization_errors(
                session,
                authorization,
                asset=asset,
                requirement=requirement,
                page=page,
                website=website,
                assignment=assignment,
            )
            if errors:
                raise ScopedMediaAuthorizationError("; ".join(errors))
            return authorization
        predecessor_assignment = session.exec(
            select(PageImageAssignment)
            .where(
                PageImageAssignment.id
                == authorization.page_image_assignment_id
            )
            .with_for_update()
        ).one_or_none()
    website = session.get(Website, authorization.website_id)
    if (
        asset is None
        or requirement is None
        or page is None
        or website is None
        or locked_assignment is None
    ):
        raise ScopedMediaAuthorizationError(
            "Scoped authorization binding records are incomplete."
        )
    assignment = locked_assignment
    if predecessor_assignment is not None:
        _require_exact_assignment_successor(
            authorization,
            predecessor_assignment,
            assignment,
            page,
            requirement,
            asset,
        )
    errors = scoped_media_authorization_errors(
        session,
        authorization,
        asset=asset,
        requirement=requirement,
        page=page,
        website=website,
        assignment=predecessor_assignment,
        replacement_assignment=(
            assignment if predecessor_assignment is not None else None
        ),
    )
    if errors:
        raise ScopedMediaAuthorizationError("; ".join(errors))
    _require_exact_assignment(assignment, page, requirement, asset)

    now = datetime.now(UTC)
    values = authorization.model_dump(
        exclude={"id", "created_at", "updated_at"}
    )
    values.update(
        {
            "page_image_assignment_id": assignment.id,
            "assignment_version": assignment.assignment_version,
            "authorization_version": authorization.authorization_version + 1,
            "lifecycle_status": "current",
            "supersedes_authorization_id": authorization.id,
        }
    )
    values["authorization_fingerprint"] = scoped_media_authorization_fingerprint(
        values
    )
    durable = ScopedMediaAuthorizationInternalCreate.model_validate(values)
    authorization.lifecycle_status = "superseded"
    authorization.updated_at = now
    session.add(authorization)
    session.flush()
    successor = ScopedMediaAuthorization(**durable.model_dump())
    session.add(successor)
    session.flush()
    return successor


def validate_scoped_media_authorization_assignment_successor(
    *,
    authorization: ScopedMediaAuthorization,
    predecessor: PageImageAssignment,
    successor: PageImageAssignment,
    page: PlannedPage,
    requirement: PlannedPageMediaRequirement,
    asset: ImageMetadata,
) -> None:
    """Validate an exact assignment handoff before any lifecycle mutation."""

    _require_exact_assignment_successor(
        authorization,
        predecessor,
        successor,
        page,
        requirement,
        asset,
    )


def scoped_media_asset_use_errors(
    session: Session,
    *,
    asset: ImageMetadata,
    requirement: PlannedPageMediaRequirement,
    page: PlannedPage,
    website: Website,
    assignment: PageImageAssignment | None = None,
) -> list[str]:
    """Enforce all effective policies recorded for this exact asset version."""

    requirement_authorization = current_scoped_media_authorization(
        session,
        requirement.id or 0,
    )
    if (
        requirement_authorization is not None
        and requirement_authorization.image_metadata_id != asset.id
    ):
        return [
            "Media requirement is authorized for a different exact governed asset."
        ]
    history = list(
        session.exec(
            select(ScopedMediaAuthorization).where(
                ScopedMediaAuthorization.image_metadata_id == asset.id,
                ScopedMediaAuthorization.media_version == asset.media_version,
            )
        ).all()
    )
    if not history:
        if getattr(asset, "usage_authorization_mode", "contract_default") == "scoped_required":
            return [
                "Governed media requires a current typed scoped authorization."
            ]
        return []
    current = [row for row in history if row.lifecycle_status == "current"]
    if not current:
        return ["Governed media has scoped authorization history but no current authorization."]

    integrity_errors: list[str] = []
    for row in current:
        original_requirement = session.get(
            PlannedPageMediaRequirement,
            row.media_requirement_id,
        )
        original_page = session.get(PlannedPage, row.planned_page_id)
        original_website = session.get(Website, row.website_id)
        if (
            original_requirement is None
            or original_page is None
            or original_website is None
        ):
            integrity_errors.append(
                "Scoped media authorization references missing scope records."
            )
            continue
        integrity_errors.extend(
            scoped_media_authorization_errors(
                session,
                row,
                asset=asset,
                requirement=original_requirement,
                page=original_page,
                website=original_website,
                assignment=(
                    session.get(PageImageAssignment, row.page_image_assignment_id)
                    if row.page_image_assignment_id is not None
                    else None
                ),
            )
        )
    if integrity_errors:
        return list(dict.fromkeys(integrity_errors))

    errors: list[str] = []
    for row in current:
        if row.media_requirement_id == requirement.id:
            continue
        terms = set(row.authorization_terms or [])
        if row.reuse_policy == "requirement_only" or "no_reuse" in terms:
            errors.append(
                "Governed media authorization restricts the asset to its exact requirement."
            )
        elif row.reuse_policy == "page_only" and row.planned_page_id != page.id:
            errors.append(
                "Governed media authorization restricts the asset to its authorized page."
            )
        elif row.reuse_policy == "website_limited" and row.website_id != website.id:
            errors.append(
                "Governed media authorization restricts the asset to its authorized Website."
            )
        if "contract_deviation_authorized" in terms:
            errors.append(
                "A scoped contract deviation requires a fresh exact authorization for this requirement."
            )
    if errors:
        return list(dict.fromkeys(errors))

    exact = [row for row in current if row.media_requirement_id == requirement.id]
    if (
        not exact
        and assignment is not None
        and getattr(asset, "usage_authorization_mode", "contract_default")
        == "scoped_required"
    ):
        return [
            "Governed media requires a current typed scoped authorization for this exact requirement."
        ]
    if exact:
        if len(exact) != 1:
            return ["Media requirement has multiple current scoped authorizations."]
        return scoped_media_authorization_errors(
            session,
            exact[0],
            asset=asset,
            requirement=requirement,
            page=page,
            website=website,
            assignment=assignment,
        )
    return []


def scoped_media_assignment_authorization_errors(
    session: Session,
    *,
    asset: ImageMetadata,
    requirement: PlannedPageMediaRequirement,
    page: PlannedPage,
    website: Website,
) -> list[str]:
    """Require a fresh exact authorization before any non-default reuse mutates."""

    errors = scoped_media_asset_use_errors(
        session,
        asset=asset,
        requirement=requirement,
        page=page,
        website=website,
    )
    if errors:
        return errors
    exact = current_scoped_media_authorization(session, requirement.id or 0)
    if exact is not None:
        if exact.image_metadata_id != asset.id:
            return [
                "Media requirement is authorized for a different exact governed asset."
            ]
        return scoped_media_authorization_errors(
            session,
            exact,
            asset=asset,
            requirement=requirement,
            page=page,
            website=website,
            assignment=None,
        )
    histories = list(
        session.exec(
            select(ScopedMediaAuthorization).where(
                ScopedMediaAuthorization.image_metadata_id == asset.id,
                ScopedMediaAuthorization.media_version == asset.media_version,
            )
        ).all()
    )
    requires_exact = (
        getattr(asset, "usage_authorization_mode", "contract_default")
        == "scoped_required"
        or any(
            row.reuse_policy != "contract_default"
            or "contract_deviation_authorized" in set(row.authorization_terms or [])
            for row in histories
        )
    )
    return (
        ["Direct assignment requires a fresh exact scoped authorization."]
        if requires_exact
        else []
    )


def governed_assignment_authorization_errors(
    session: Session,
    assignment: PageImageAssignment,
) -> list[str]:
    """Validate authorization at any downstream assignment consumer."""

    asset = session.get(ImageMetadata, assignment.image_metadata_id)
    if asset is None:
        return ["Governed media assignment asset is missing."]
    if assignment.media_requirement_id is None:
        return (
            ["Scoped governed media cannot use a legacy assignment path."]
            if asset_requires_exact_scoped_use(session, asset)
            else []
        )
    requirement = session.get(
        PlannedPageMediaRequirement,
        assignment.media_requirement_id,
    )
    page = session.get(PlannedPage, assignment.planned_page_id)
    website = session.get(Website, assignment.website_id)
    if requirement is None or page is None or website is None:
        return [
            "Governed media assignment cannot resolve its exact authorization scope."
        ]
    return scoped_media_asset_use_errors(
        session,
        asset=asset,
        requirement=requirement,
        page=page,
        website=website,
        assignment=assignment,
    )


def scoped_media_authorization_errors(
    session: Session,
    authorization: ScopedMediaAuthorization,
    *,
    asset: ImageMetadata,
    requirement: PlannedPageMediaRequirement,
    page: PlannedPage,
    website: Website,
    assignment: PageImageAssignment | None,
    replacement_assignment: PageImageAssignment | None = None,
) -> list[str]:
    errors: list[str] = []
    try:
        _validate_authorization_chain(
            _authorization_history(
                session,
                authorization.media_requirement_id,
            )
        )
    except ScopedMediaAuthorizationError as exc:
        errors.append(str(exc))
    if authorization.lifecycle_status != "current":
        errors.append("Scoped media authorization is stale or superseded.")
    if asset.governance_status != "approved" or asset.retired_at is not None:
        errors.append("Scoped media authorization asset approval is no longer current.")
    if _asset_has_approved_successor(session, asset):
        errors.append("Scoped media authorization asset version is superseded.")
    if (
        asset.website_id != website.id
        or asset.business_id != website.business_id
        or requirement.website_id != website.id
        or requirement.business_id != website.business_id
    ):
        errors.append(
            "Scoped media authorization asset or requirement crosses its Website or Business boundary."
        )
    if (
        requirement.lifecycle_status != "active"
        or requirement.requirement_state not in {"required", "advisory"}
    ):
        errors.append(
            "Scoped media authorization requirement is stale, excluded, or deferred."
        )
    expected_scope = (
        website.id,
        page.site_plan_id,
        page.id,
        page.generated_page_id,
        requirement.id,
        requirement.version,
        requirement.placement_key,
        requirement.contract_version,
        asset.id,
        asset.media_version,
        asset.checksum_sha256,
        asset.approval_version,
        asset.approved_by,
        _utc(asset.approved_at),
    )
    actual_scope = (
        authorization.website_id,
        authorization.site_plan_id,
        authorization.planned_page_id,
        authorization.generated_page_id,
        authorization.media_requirement_id,
        authorization.requirement_version,
        authorization.placement_key,
        authorization.placement_contract_version,
        authorization.image_metadata_id,
        authorization.media_version,
        authorization.asset_checksum_sha256,
        authorization.approval_version,
        authorization.asset_approved_by,
        _utc(authorization.asset_approved_at),
    )
    if actual_scope != expected_scope:
        errors.append(
            "Scoped media authorization does not match the exact Website, Site Plan, page, requirement, asset, or approval identity."
        )
    try:
        _validate_policy_terms(
            authorization.reuse_policy,
            authorization.authorization_terms,
            required_terms=getattr(asset, "required_authorization_terms", []),
        )
    except ScopedMediaAuthorizationError as exc:
        errors.append(str(exc))
    try:
        observed_approval = scoped_media_approval_fingerprint(
            {
                "image_metadata_id": asset.id,
                "asset_website_id": asset.website_id,
                "asset_business_id": asset.business_id,
                "media_version": asset.media_version,
                "asset_checksum_sha256": asset.checksum_sha256,
                "approval_version": asset.approval_version,
                "asset_approved_by": asset.approved_by,
                "asset_approved_at": asset.approved_at,
                "usage_authorization_mode": asset.usage_authorization_mode,
                "required_authorization_terms": getattr(
                    asset,
                    "required_authorization_terms",
                    [],
                ),
            }
        )
    except (KeyError, TypeError, ValueError):
        observed_approval = ""
    if authorization.approval_fingerprint != observed_approval:
        errors.append("Scoped media authorization approval identity is stale or corrupt.")
    try:
        observed_authorization = scoped_media_authorization_fingerprint(
            authorization.model_dump()
        )
    except (KeyError, TypeError, ValueError):
        observed_authorization = ""
    if authorization.authorization_fingerprint != observed_authorization:
        errors.append("Scoped media authorization integrity fingerprint does not match.")

    if authorization.page_image_assignment_id is not None:
        bound = session.get(
            PageImageAssignment,
            authorization.page_image_assignment_id,
        )
        if bound is None:
            errors.append("Scoped media authorization assignment is missing.")
        else:
            replaced_for_exact_successor = False
            if replacement_assignment is not None:
                try:
                    _require_exact_assignment_successor(
                        authorization,
                        bound,
                        replacement_assignment,
                        page,
                        requirement,
                        asset,
                    )
                    replaced_for_exact_successor = bound.status == "replaced"
                except ScopedMediaAuthorizationError:
                    replaced_for_exact_successor = False
            if (
                (bound.status != "active" and not replaced_for_exact_successor)
                or bound.assignment_version != authorization.assignment_version
                or bound.media_requirement_id != authorization.media_requirement_id
                or bound.image_metadata_id != authorization.image_metadata_id
            ):
                errors.append("Scoped media authorization assignment identity does not match.")
        if assignment is not None and (
            assignment.id != authorization.page_image_assignment_id
            or assignment.assignment_version != authorization.assignment_version
        ):
            errors.append("Scoped media authorization is bound to a different assignment.")
    elif assignment is not None:
        errors.append("Scoped media authorization is not bound to the active assignment.")
    if replacement_assignment is not None and authorization.page_image_assignment_id is None:
        errors.append(
            "An unbound scoped authorization cannot replace an assignment binding."
        )
    return list(dict.fromkeys(errors))


def _require_exact_assignment_successor(
    authorization: ScopedMediaAuthorization,
    predecessor: PageImageAssignment,
    successor: PageImageAssignment,
    page: PlannedPage,
    requirement: PlannedPageMediaRequirement,
    asset: ImageMetadata,
) -> None:
    predecessor_scope = (
        predecessor.website_id,
        predecessor.site_plan_id,
        predecessor.planned_page_id,
        predecessor.generated_page_id,
        predecessor.media_requirement_id,
        predecessor.image_metadata_id,
        predecessor.media_version,
        predecessor.placement_contract_version,
    )
    expected_scope = (
        page.website_id,
        page.site_plan_id,
        page.id,
        page.generated_page_id,
        requirement.id,
        asset.id,
        asset.media_version,
        requirement.contract_version,
    )
    successor_scope = (
        successor.website_id,
        successor.site_plan_id,
        successor.planned_page_id,
        successor.generated_page_id,
        successor.media_requirement_id,
        successor.image_metadata_id,
        successor.media_version,
        successor.placement_contract_version,
    )
    exact_lineage = (
        authorization.page_image_assignment_id == predecessor.id
        and authorization.assignment_version == predecessor.assignment_version
        and predecessor_scope == expected_scope
        and successor_scope == expected_scope
        and successor.status == "active"
        and predecessor.status in {"active", "replaced"}
        and successor.replaces_page_image_assignment_id == predecessor.id
        and predecessor.assignment_version is not None
        and successor.assignment_version == predecessor.assignment_version + 1
    )
    if predecessor.status == "replaced":
        exact_lineage = exact_lineage and (
            predecessor.replaced_by == successor.assigned_by
            and predecessor.replacement_rationale
            == successor.assignment_rationale
            and _utc(predecessor.replaced_at) == _utc(successor.assigned_at)
        )
    if not exact_lineage:
        raise ScopedMediaAuthorizationError(
            "Scoped authorization assignment replacement does not preserve the exact predecessor, version, scope, and asset binding."
        )


def exact_contract_deviation_terms(
    session: Session,
    *,
    asset: ImageMetadata,
    requirement: PlannedPageMediaRequirement,
    page: PlannedPage,
    website: Website,
) -> frozenset[str]:
    """Return valid typed terms for this exact scope; never propagate deviations."""

    authorization = current_scoped_media_authorization(
        session,
        requirement.id or 0,
    )
    if authorization is None or authorization.image_metadata_id != asset.id:
        return frozenset()
    if scoped_media_authorization_errors(
        session,
        authorization,
        asset=asset,
        requirement=requirement,
        page=page,
        website=website,
        assignment=None,
    ):
        return frozenset()
    return frozenset(authorization.authorization_terms or [])


def _require_current_scope(
    plan: SitePlan,
    website: Website,
    page: PlannedPage,
    requirement: PlannedPageMediaRequirement,
    asset: ImageMetadata,
) -> None:
    if (
        plan.website_id != website.id
        or page.website_id != website.id
        or page.site_plan_id != plan.id
        or requirement.website_id != website.id
        or requirement.site_plan_id != plan.id
        or requirement.planned_page_id != page.id
    ):
        raise ScopedMediaAuthorizationError(
            "Scoped authorization crosses the Website, Site Plan, page, or requirement boundary."
        )
    if requirement.lifecycle_status != "active":
        raise ScopedMediaAuthorizationError("Media requirement is stale or superseded.")
    if requirement.requirement_state not in {"required", "advisory"}:
        raise ScopedMediaAuthorizationError(
            "Only active required or advisory media requirements can be authorized."
        )
    if asset.website_id != website.id or asset.business_id != website.business_id:
        raise ScopedMediaAuthorizationError(
            "Scoped authorization asset crosses the Website or Business boundary."
        )
    if page.generated_page_id is not None:
        # The Generated Page FK is optional, but an existing binding must resolve.
        if not isinstance(page.generated_page_id, int) or page.generated_page_id < 1:
            raise ScopedMediaAuthorizationError(
                "Planned Page has an invalid Generated Page binding."
            )


def _require_current_approval(asset: ImageMetadata) -> None:
    if (
        asset.governance_status != "approved"
        or asset.retired_at is not None
        or asset.media_version is None
        or asset.approval_version is None
        or not asset.checksum_sha256
        or not asset.approved_by
        or asset.approved_at is None
    ):
        raise ScopedMediaAuthorizationError(
            "Scoped media authorization requires an exact current governed approval."
        )


def _require_exact_assignment(
    assignment: PageImageAssignment,
    page: PlannedPage,
    requirement: PlannedPageMediaRequirement,
    asset: ImageMetadata,
) -> None:
    if (
        assignment.status != "active"
        or assignment.website_id != page.website_id
        or assignment.site_plan_id != page.site_plan_id
        or assignment.planned_page_id != page.id
        or assignment.generated_page_id != page.generated_page_id
        or assignment.media_requirement_id != requirement.id
        or assignment.image_metadata_id != asset.id
        or assignment.media_version != asset.media_version
        or assignment.placement_contract_version != requirement.contract_version
        or assignment.assignment_version is None
    ):
        raise ScopedMediaAuthorizationError(
            "Scoped authorization assignment does not match the exact current binding."
        )


def _validate_policy_terms(
    reuse_policy: str,
    terms: Iterable[str],
    *,
    required_terms: Iterable[str] = (),
) -> None:
    try:
        validate_scoped_media_authorization_policy_terms(
            reuse_policy,
            terms,
            required_terms=required_terms,
        )
    except ValueError as exc:
        raise ScopedMediaAuthorizationError(str(exc)) from exc


def _prevent_restrictive_cross_scope_authorization(
    session: Session,
    asset: ImageMetadata,
    page: PlannedPage,
    requirement: PlannedPageMediaRequirement,
    new_policy: str,
) -> None:
    rows = list(
        session.exec(
            select(ScopedMediaAuthorization).where(
                ScopedMediaAuthorization.image_metadata_id == asset.id,
                ScopedMediaAuthorization.media_version == asset.media_version,
                ScopedMediaAuthorization.lifecycle_status == "current",
            )
        ).all()
    )
    other_rows = [row for row in rows if row.media_requirement_id != requirement.id]
    for row in other_rows:
        terms = set(row.authorization_terms or [])
        if row.reuse_policy == "requirement_only" or "no_reuse" in terms:
            raise ScopedMediaAuthorizationError(
                "Existing requirement-only/no-reuse authorization prohibits another scope."
            )
        if row.reuse_policy == "page_only" and row.planned_page_id != page.id:
            raise ScopedMediaAuthorizationError(
                "Existing page-only authorization prohibits another page."
            )
    if new_policy == "requirement_only" and other_rows:
        raise ScopedMediaAuthorizationError(
            "Requirement-only authorization cannot be added after another current scope."
        )
    if new_policy == "page_only" and any(
        row.planned_page_id != page.id for row in other_rows
    ):
        raise ScopedMediaAuthorizationError(
            "Page-only authorization cannot be added after use on another page."
        )


def supersede_current_scoped_media_authorization(
    session: Session,
    media_requirement_id: int,
    *,
    changed_at: datetime | None = None,
) -> None:
    """Close effective authorization when its governed requirement is retired.

    The immutable fingerprint remains valid because lifecycle is deliberately not
    fingerprinted. A later requirement must receive a fresh explicit authorization;
    no scope or assignment decision is copied forward.
    """

    requirement = session.exec(
        select(PlannedPageMediaRequirement)
        .where(PlannedPageMediaRequirement.id == media_requirement_id)
        .with_for_update()
    ).one_or_none()
    if requirement is None:
        return
    history = _authorization_history(session, media_requirement_id, lock=True)
    _validate_authorization_chain(history)
    current = history[-1] if history and history[-1].lifecycle_status == "current" else None
    if current is None:
        return
    current.lifecycle_status = "superseded"
    current.updated_at = changed_at or datetime.now(UTC)
    session.add(current)


def supersede_current_scoped_media_authorizations_for_asset(
    session: Session,
    image_metadata_id: int,
    *,
    changed_at: datetime | None = None,
) -> None:
    """Close every effective use of an exact asset version without copying it."""

    rows = list(
        session.exec(
            select(ScopedMediaAuthorization)
            .where(
                ScopedMediaAuthorization.image_metadata_id == image_metadata_id,
                ScopedMediaAuthorization.lifecycle_status == "current",
            )
            .order_by(
                ScopedMediaAuthorization.media_requirement_id,
                ScopedMediaAuthorization.authorization_version,
            )
            .with_for_update()
        ).all()
    )
    now = changed_at or datetime.now(UTC)
    for row in rows:
        history = _authorization_history(
            session,
            row.media_requirement_id,
            lock=True,
        )
        _validate_authorization_chain(history)
        if not history or history[-1].id != row.id:
            raise ScopedMediaAuthorizationError(
                "Scoped media authorization current state is not the lineage tip."
            )
        row.lifecycle_status = "superseded"
        row.updated_at = now
        session.add(row)


def _validate_authorization_chain(
    rows: list[ScopedMediaAuthorization],
) -> None:
    if not rows:
        return
    current_rows = [row for row in rows if row.lifecycle_status == "current"]
    if len(current_rows) > 1:
        raise ScopedMediaAuthorizationError(
            "Media requirement has multiple current scoped authorizations."
        )
    for index, row in enumerate(rows):
        expected_version = index + 1
        expected_predecessor = rows[index - 1].id if index else None
        if (
            row.authorization_version != expected_version
            or row.supersedes_authorization_id != expected_predecessor
            or (index < len(rows) - 1 and row.lifecycle_status != "superseded")
        ):
            raise ScopedMediaAuthorizationError(
                "Scoped media authorization lineage is incomplete or was tampered."
            )
    if current_rows and current_rows[0].id != rows[-1].id:
        raise ScopedMediaAuthorizationError(
            "Scoped media authorization current state is not the lineage tip."
        )


def _authorization_history(
    session: Session,
    media_requirement_id: int,
    *,
    lock: bool = False,
) -> list[ScopedMediaAuthorization]:
    statement = (
        select(ScopedMediaAuthorization)
        .where(
            ScopedMediaAuthorization.media_requirement_id
            == media_requirement_id,
        )
        .order_by(
            ScopedMediaAuthorization.authorization_version,
            ScopedMediaAuthorization.id,
        )
    )
    if lock:
        statement = statement.with_for_update()
    return list(session.exec(statement).all())


def _asset_has_approved_successor(
    session: Session,
    asset: ImageMetadata,
) -> bool:
    if not asset.website_id or not asset.media_key or not asset.media_version:
        return False
    later = list(
        session.exec(
            select(ImageMetadata).where(
                ImageMetadata.website_id == asset.website_id,
                ImageMetadata.media_key == asset.media_key,
                ImageMetadata.media_version > asset.media_version,
            )
        ).all()
    )
    return any(item.governance_status == "approved" or item.approved_at for item in later)


def _utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _mark_composition_stale(session: Session, planned_page_id: int) -> None:
    for composition in session.exec(
        select(PageComposition).where(
            PageComposition.planned_page_id == planned_page_id,
            PageComposition.status == "current",
        )
    ).all():
        composition.status = "stale"
        composition.updated_at = datetime.now(UTC)
        session.add(composition)
