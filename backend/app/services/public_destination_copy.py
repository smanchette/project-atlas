from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from app.models import (
    City,
    County,
    GeneratedPage,
    InternalLinkIntent,
    PlannedPage,
    Service,
    SitePlan,
)
from app.schemas.public_copy import PublicDestinationCopy
from app.services.website_context import build_website_context


PUBLIC_COPY_RULESET_KEY = "project-atlas-public-copy-ruleset"
PUBLIC_COPY_RULESET_VERSION = "1.0.0"
PUBLIC_COPY_RULESET_IDENTITY = (
    "project-atlas-public-copy-ruleset/source-only/1.0.0"
)
PUBLIC_COPY_RULESET_HASH = (
    "3019e45fb33a31c4c023d110375232ea7bc44eb93eb9f2fbab7f8029847e70ae"
)


class PublicDestinationCopyError(ValueError):
    pass


def build_public_copy_reconciled_draft(
    session: Session,
    planned_page: PlannedPage,
    current_draft: dict[str, Any],
) -> dict[str, Any]:
    """Lazy public re-export of the page-type source reconciliation builder."""

    # Planned-page drafting owns the page-type templates and imports this module
    # for destination derivation. Keep this import local to avoid an import cycle
    # while exposing one stable reconciliation API.
    from app.services.planned_page_drafting import (
        build_public_copy_reconciled_draft as build_reconciled_draft,
    )

    return build_reconciled_draft(session, planned_page, current_draft)


def build_public_destination_copy(
    session: Session,
    plan: SitePlan,
    planned: PlannedPage,
    generated: GeneratedPage,
    *,
    draft_content: dict[str, Any] | None = None,
) -> list[PublicDestinationCopy]:
    """Derive customer copy from exact, governed destination identities.

    Internal-link purposes remain operator evidence. They are deliberately not
    inputs to this projection and are never rewritten by this service.
    """

    _require_source_ownership(plan, planned, generated)
    context = build_website_context(session, website_id=plan.website_id)
    draft = draft_content if draft_content is not None else generated.draft_content or {}
    result: list[PublicDestinationCopy] = []
    seen_target_ids: set[int] = set()

    links = list(
        session.exec(
            select(InternalLinkIntent)
            .where(
                InternalLinkIntent.website_id == plan.website_id,
                InternalLinkIntent.site_plan_id == plan.id,
                InternalLinkIntent.source_planned_page_id == planned.id,
                InternalLinkIntent.approval_state == "approved",
            )
            .order_by(InternalLinkIntent.id)
        ).all()
    )
    for link in links:
        if link.id is None or not _decision_provenance_complete(link):
            raise PublicDestinationCopyError(
                "Approved internal-link intent lacks authoritative operator decision provenance."
            )
        target = _target_page(
            session,
            plan=plan,
            target_planned_page_id=link.target_planned_page_id,
        )
        if target.id == planned.id:
            raise PublicDestinationCopyError(
                "Public destination cannot target its source Planned Page."
            )
        target_id = target.id or 0
        if target_id in seen_target_ids:
            raise PublicDestinationCopyError(
                "Approved internal-link intents for one source cannot share a target Planned Page."
            )
        result.append(
            _projection_item(
                session,
                context=context,
                target=target,
                source_kind="internal_link_intent",
                source_record_id=link.id,
            )
        )
        seen_target_ids.add(target_id)

    for target in _draft_related_targets(session, plan, planned, draft):
        target_id = target.id or 0
        if target_id in seen_target_ids:
            continue
        result.append(
            _projection_item(
                session,
                context=context,
                target=target,
                source_kind="draft_related_page",
                source_record_id=target_id,
            )
        )
        seen_target_ids.add(target_id)
    return result


def require_public_destination_copy(
    session: Session,
    plan: SitePlan,
    planned: PlannedPage,
    generated: GeneratedPage,
    *,
    draft_content: dict[str, Any] | None = None,
) -> list[PublicDestinationCopy]:
    """Validate one revision-owned projection against current exact sources."""

    draft = draft_content if draft_content is not None else generated.draft_content or {}
    raw = draft.get("public_destination_copy")
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise PublicDestinationCopyError(
            "Public destination copy must be a structured list."
        )
    try:
        actual = [PublicDestinationCopy.model_validate(item) for item in raw]
    except Exception as exc:
        raise PublicDestinationCopyError(
            "Public destination copy is malformed."
        ) from exc
    expected = build_public_destination_copy(
        session,
        plan,
        planned,
        generated,
        draft_content=draft,
    )
    actual_payload = [item.model_dump(mode="json") for item in actual]
    expected_payload = [item.model_dump(mode="json") for item in expected]
    if actual_payload != expected_payload:
        raise PublicDestinationCopyError(
            "Public destination copy is missing, stale, reordered, or crosses an exact source boundary."
        )
    return actual


def _projection_item(
    session: Session,
    *,
    context,
    target: PlannedPage,
    source_kind: str,
    source_record_id: int,
) -> PublicDestinationCopy:
    if target.id is None:
        raise PublicDestinationCopyError("Destination Planned Page has no identity.")
    return PublicDestinationCopy(
        source_kind=source_kind,
        source_record_id=source_record_id,
        target_planned_page_id=target.id,
        target_generated_page_id=target.generated_page_id,
        label=_required_text(target.working_name, "Destination label"),
        slug=_required_text(target.intended_slug, "Destination slug"),
        description=_destination_description(session, context, target),
        ruleset_key=PUBLIC_COPY_RULESET_KEY,
        ruleset_version=PUBLIC_COPY_RULESET_VERSION,
        ruleset_hash=PUBLIC_COPY_RULESET_HASH,
    )


def _destination_description(session: Session, context, target: PlannedPage) -> str:
    brand_name = _required_text(
        context.identity.display_name,
        "Website Identity display name",
    )
    service_name = _service_name(session, context, target)
    if target.page_type == "home":
        return f"Return to the {brand_name} home page."
    if target.page_type == "about":
        return f"Learn more about {brand_name}."
    if target.page_type == "contact":
        return f"Contact {brand_name}."
    if target.page_type == "faq" and service_name:
        return f"Read answers to common questions about {service_name}."
    if target.page_type == "service" and service_name:
        return f"View information about {service_name}."
    if target.page_type == "county" and service_name and target.county_id:
        county = session.get(County, target.county_id)
        if county is not None:
            return (
                f"Explore {service_name} service throughout "
                f"{_required_text(county.county_name, 'County name')}."
            )
    if target.page_type in {"city", "city_service"} and service_name and target.city_id:
        city = session.get(City, target.city_id)
        if city is not None:
            return (
                f"View {service_name} information for "
                f"{_required_text(city.city_name, 'City name')}, "
                f"{_state_name(context, city.state)}."
            )
    return f"Learn more about {_required_text(target.working_name, 'Destination label')}."


def _service_name(session: Session, context, target: PlannedPage) -> str | None:
    if target.service_id is not None:
        service = session.get(Service, target.service_id)
        if service is None:
            raise PublicDestinationCopyError("Destination Service is missing.")
        return _required_text(service.service_name, "Service name")
    active = [item for item in context.services if item.status == "active"]
    if len(active) == 1:
        return _required_text(active[0].service_name, "Service name")
    return None


def _state_name(context, state_code: str) -> str:
    configured = context.website.configuration.get("state_name")
    market_codes = context.website.configuration.get("market_state_codes")
    if (
        isinstance(configured, str)
        and configured.strip()
        and isinstance(market_codes, list)
        and len(market_codes) == 1
        and str(market_codes[0]).strip().casefold() == state_code.strip().casefold()
    ):
        return configured.strip()
    return _required_text(state_code, "State name")


def _target_page(
    session: Session,
    *,
    plan: SitePlan,
    target_planned_page_id: int,
) -> PlannedPage:
    target = session.get(PlannedPage, target_planned_page_id)
    if target is None:
        raise PublicDestinationCopyError("Destination Planned Page is missing.")
    if target.website_id != plan.website_id or target.site_plan_id != plan.id:
        raise PublicDestinationCopyError(
            "Destination crosses its Website or Site Plan boundary."
        )
    if target.generated_page_id is None:
        raise PublicDestinationCopyError(
            "Destination Planned Page lacks an exact Generated Page identity."
        )
    generated = session.get(GeneratedPage, target.generated_page_id)
    if generated is None:
        raise PublicDestinationCopyError("Destination Generated Page is missing.")
    if (
        generated.website_id != plan.website_id
        or generated.page_type != target.page_type
        or generated.page_slug != target.intended_slug
        or generated.service_id != target.service_id
        or generated.city_id != target.city_id
        or generated.county_id != target.county_id
    ):
        raise PublicDestinationCopyError(
            "Destination Generated Page crosses or diverges from its exact Website, "
            "page-type, slug, Service, City, or County identity."
        )
    return target


def _draft_related_targets(
    session: Session,
    plan: SitePlan,
    planned: PlannedPage,
    draft: dict[str, Any],
) -> list[PlannedPage]:
    raw = draft.get("related_pages", [])
    if not raw:
        return []
    if not isinstance(raw, list):
        raise PublicDestinationCopyError("Draft related pages must be a list.")
    pages = list(
        session.exec(
            select(PlannedPage).where(
                PlannedPage.website_id == plan.website_id,
                PlannedPage.site_plan_id == plan.id,
            )
        ).all()
    )
    by_slug = {item.intended_slug.strip("/"): item for item in pages}
    result: list[PlannedPage] = []
    seen_ids: set[int] = set()
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("slug"), str):
            raise PublicDestinationCopyError("Draft related-page identity is malformed.")
        target = by_slug.get(item["slug"].strip("/"))
        if target is None or target.id == planned.id:
            raise PublicDestinationCopyError(
                "Approved draft related page is missing or crosses the Website boundary: "
                f"{item['slug']}."
            )
        target = _target_page(
            session,
            plan=plan,
            target_planned_page_id=target.id or 0,
        )
        target_id = target.id or 0
        if target_id not in seen_ids:
            result.append(target)
            seen_ids.add(target_id)
    return result


def _require_source_ownership(
    plan: SitePlan,
    planned: PlannedPage,
    generated: GeneratedPage,
) -> None:
    if plan.id is None or planned.id is None or generated.id is None:
        raise PublicDestinationCopyError(
            "Public destination copy requires persisted source identities."
        )
    if (
        planned.website_id != plan.website_id
        or planned.site_plan_id != plan.id
        or planned.generated_page_id != generated.id
        or generated.website_id != plan.website_id
        or generated.page_type != planned.page_type
        or generated.page_slug != planned.intended_slug
        or generated.service_id != planned.service_id
        or generated.city_id != planned.city_id
        or generated.county_id != planned.county_id
    ):
        raise PublicDestinationCopyError(
            "Public destination source crosses or diverges from its exact Website, "
            "Site Plan, page-type, slug, Service, City, or County identity."
        )


def _decision_provenance_complete(link: InternalLinkIntent) -> bool:
    return bool(
        link.decision_version is not None
        and link.decision_version >= 1
        and isinstance(link.decided_by, str)
        and link.decided_by.strip()
        and isinstance(link.rationale, str)
        and link.rationale.strip()
        and link.decided_at is not None
    )


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PublicDestinationCopyError(f"{label} is missing.")
    return value.strip()
