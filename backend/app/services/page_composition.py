from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from typing import Any

from sqlmodel import Session, select

from app.models import (
    BrandAsset,
    GeneratedPage,
    ImageMetadata,
    InternalLinkIntent,
    NavigationItem,
    NavigationSet,
    PageComposition,
    PageImageAssignment,
    PlannedPage,
    SemanticComponentDefinition,
    Service,
    SitePlan,
    Website,
    WebsiteIdentity,
    WebsiteIdentityAssetAssignment,
)
from app.schemas.page_composition import (
    PageComponentInstance,
    PageCompositionDecisionUpdate,
    PageCompositionRead,
    SemanticComponentDefinitionRead,
    SitePlanCompositionRefreshResult,
)
from app.services.website_context import build_website_context
from app.services.brand_assets import identity_asset_contract_error


ALL_PAGE_TYPES = {
    "home", "about", "contact", "service", "county", "city_service",
    "informational", "faq",
}
NON_SUPPRESSIBLE_COMPONENTS = {
    "website_header",
    "primary_navigation",
    "hero",
    "final_cta",
    "website_footer",
}


class PageCompositionError(ValueError):
    pass


def list_component_registry(session: Session) -> list[SemanticComponentDefinitionRead]:
    definitions = list(session.exec(
        select(SemanticComponentDefinition)
        .where(SemanticComponentDefinition.status == "active")
        .order_by(
            SemanticComponentDefinition.component_key,
            SemanticComponentDefinition.contract_version,
        )
    ).all())
    if not definitions:
        raise PageCompositionError("Semantic Component Registry is missing; apply migration 20260801_0037.")
    return [SemanticComponentDefinitionRead.model_validate(item) for item in definitions]


def refresh_site_plan_compositions(
    session: Session,
    plan_id: int,
    *,
    commit: bool = True,
) -> SitePlanCompositionRefreshResult:
    plan = _plan(session, plan_id)
    _definitions(session)
    pages = list(session.exec(
        select(PlannedPage).where(PlannedPage.site_plan_id == plan.id).order_by(PlannedPage.id)
    ).all())
    created = refreshed = unchanged = 0
    blocked: list[dict[str, Any]] = []
    compositions: list[PageComposition] = []
    for planned in pages:
        if not planned.generated_page_id:
            blocked.append({"planned_page_id": planned.id, "reason": "A Generated Page draft is required before composition."})
            continue
        try:
            composition, outcome = _compose(session, plan, planned)
        except PageCompositionError as exc:
            blocked.append({"planned_page_id": planned.id, "reason": str(exc)})
            continue
        compositions.append(composition)
        if outcome == "created":
            created += 1
        elif outcome == "refreshed":
            refreshed += 1
        else:
            unchanged += 1
    if commit:
        session.commit()
    return SitePlanCompositionRefreshResult(
        website_id=plan.website_id,
        site_plan_id=plan.id or plan_id,
        created=created,
        refreshed=refreshed,
        unchanged=unchanged,
        blocked=blocked,
        compositions=[_read(session, item, require_current=True) for item in compositions],
    )


def read_composition_for_generated_page(
    session: Session,
    generated_page_id: int,
) -> PageCompositionRead:
    composition = session.exec(
        select(PageComposition).where(PageComposition.generated_page_id == generated_page_id)
    ).first()
    if not composition:
        raise PageCompositionError(
            "No current semantic composition exists for this draft; refresh the Site Plan composition first."
        )
    return _read(session, composition, require_current=True)


def read_site_plan_compositions(session: Session, plan_id: int) -> list[PageCompositionRead]:
    plan = _plan(session, plan_id)
    rows = list(session.exec(
        select(PageComposition).where(PageComposition.site_plan_id == plan.id).order_by(PageComposition.planned_page_id)
    ).all())
    return [_read(session, row, require_current=False) for row in rows]


def update_operator_composition_decisions(
    session: Session,
    composition_id: int,
    payload: PageCompositionDecisionUpdate,
) -> PageCompositionRead:
    composition = session.get(PageComposition, composition_id)
    if not composition:
        raise PageCompositionError("Page composition not found.")
    generated_by_key = {item["instance_key"]: item for item in composition.generated_components}
    seen: set[str] = set()
    decisions: list[dict[str, Any]] = []
    definitions = _definitions(session)
    for value in payload.decisions:
        if value.instance_key in seen:
            raise PageCompositionError("Operator decisions cannot duplicate a component instance.")
        seen.add(value.instance_key)
        instance = generated_by_key.get(value.instance_key)
        if not instance:
            raise PageCompositionError(
                f"Operator decision references unknown generated instance: {value.instance_key}."
            )
        if (
            value.action == "suppress"
            and instance["component_key"] in NON_SUPPRESSIBLE_COMPONENTS
        ):
            raise PageCompositionError(
                f"Required structural component cannot be suppressed: {value.instance_key}."
            )
        if value.variant is not None:
            definition = definitions.get(
                (instance["component_key"], instance["contract_version"])
            )
            if definition is None:
                raise PageCompositionError(
                    f"Component contract is no longer active: {instance['component_key']}."
                )
            if value.variant not in definition.supported_variants:
                raise PageCompositionError(
                    f"Variant {value.variant!r} is not permitted for {definition.component_key}."
                )
        decision = value.model_dump(exclude_none=True)
        decision["provenance"] = "operator"
        decision["decided_by"] = payload.decided_by.strip()
        decision["decided_at"] = datetime.now(UTC).isoformat()
        decisions.append(decision)
    if not payload.decided_by.strip():
        raise PageCompositionError("Operator identity is required.")
    composition.operator_decisions = decisions
    composition.decided_by = payload.decided_by.strip()
    composition.decided_at = datetime.now(UTC)
    composition.composition_version += 1
    composition.updated_at = datetime.now(UTC)
    session.add(composition)
    session.commit()
    session.refresh(composition)
    return _read(session, composition, require_current=True)


def composition_diagnostics(session: Session, plan: SitePlan) -> tuple[list[int], list[int]]:
    pages = list(session.exec(select(PlannedPage).where(PlannedPage.site_plan_id == plan.id)).all())
    by_page = {
        item.planned_page_id: item
        for item in session.exec(select(PageComposition).where(PageComposition.site_plan_id == plan.id)).all()
    }
    missing: list[int] = []
    stale_or_invalid: list[int] = []
    for page in pages:
        if not page.generated_page_id:
            continue
        composition = by_page.get(page.id or -1)
        if not composition:
            missing.append(page.id or 0)
            continue
        try:
            _read(session, composition, require_current=True)
        except PageCompositionError:
            stale_or_invalid.append(page.id or 0)
    return missing, stale_or_invalid


def _compose(session: Session, plan: SitePlan, planned: PlannedPage) -> tuple[PageComposition, str]:
    if planned.website_id != plan.website_id:
        raise PageCompositionError("Planned Page crosses the Site Plan Website boundary.")
    generated = session.get(GeneratedPage, planned.generated_page_id)
    if not generated or generated.website_id != plan.website_id or not generated.draft_content:
        raise PageCompositionError("Generated draft is missing or crosses the Website boundary.")
    if generated.page_type not in ALL_PAGE_TYPES:
        raise PageCompositionError(f"Unsupported page type: {generated.page_type}.")
    snapshot = _source_snapshot(session, plan, planned, generated)
    source_hash = _hash(snapshot)
    components = _generate_components(session, plan, planned, generated)
    existing = session.exec(select(PageComposition).where(PageComposition.planned_page_id == planned.id)).first()
    if existing and existing.source_hash == source_hash and existing.generated_components == components:
        return existing, "unchanged"
    if existing:
        existing.generated_components = components
        existing.source_snapshot = snapshot
        existing.source_hash = source_hash
        existing.status = "current"
        existing.generated_at = datetime.now(UTC)
        existing.composition_version += 1
        existing.updated_at = datetime.now(UTC)
        row = existing
        outcome = "refreshed"
    else:
        row = PageComposition(
            website_id=plan.website_id,
            site_plan_id=plan.id or 0,
            planned_page_id=planned.id or 0,
            generated_page_id=generated.id or 0,
            generated_components=components,
            source_snapshot=snapshot,
            source_hash=source_hash,
        )
        session.add(row)
        outcome = "created"
    session.flush()
    _validate(session, row, plan, planned, generated)
    return row, outcome


def _generate_components(session: Session, plan: SitePlan, planned: PlannedPage, generated: GeneratedPage) -> list[dict[str, Any]]:
    draft = generated.draft_content or {}
    definitions = _definitions(session)
    current_versions = {
        key: max(version for component_key, version in definitions if component_key == key)
        for key, _ in definitions
    }
    items: list[dict[str, Any]] = []
    position = 0

    def add(key: str, region: str, bindings: dict[str, Any], variant: str = "default", suffix: str | None = None) -> None:
        nonlocal position
        contract_version = current_versions.get(key)
        if contract_version is None:
            raise PageCompositionError(
                f"Required semantic component contract is missing: {key}."
            )
        instance_key = key if suffix is None else f"{key}:{suffix}"
        items.append({
            "instance_key": instance_key,
            "component_key": key,
            "contract_version": contract_version,
            "region": region,
            "position": position,
            "variant": variant,
            "input_bindings": bindings,
            "provenance": "atlas_generated",
        })
        position += 1

    nav_sets = {item.set_type: item for item in session.exec(
        select(NavigationSet).where(NavigationSet.site_plan_id == plan.id)
    ).all()}
    for nav_type in ("utility", "primary"):
        nav = nav_sets.get(nav_type)
        if not nav:
            raise PageCompositionError(f"Required {nav_type} Navigation Set is missing.")
    add("website_header", "header", {"website_id": plan.website_id})
    add("utility_navigation", "header", {"navigation_set_id": nav_sets["utility"].id})
    add("primary_navigation", "header", {"navigation_set_id": nav_sets["primary"].id})
    add("hero", "main", {"generated_page_id": generated.id}, "local" if planned.city_id or planned.county_id else "default")
    if _has_trust(session, generated):
        add("trust_license", "main", {"website_id": plan.website_id})
    sections = _draft_sections(draft)
    for index, section in enumerate(sections):
        key = "service_summary" if index == 0 and planned.page_type in {"service", "county", "city_service"} else "content_section"
        add(key, "main", {"generated_page_id": generated.id, "section_key": section["key"]}, "muted" if index % 2 else "default", section["key"])
    assignments = list(session.exec(select(PageImageAssignment).where(
        PageImageAssignment.generated_page_id == generated.id,
        PageImageAssignment.status == "active",
    ).order_by(PageImageAssignment.sort_order, PageImageAssignment.id)).all())
    for assignment in assignments:
        add(
            "media_placement",
            "main",
            {"page_image_assignment_id": assignment.id},
            "approved_media",
            f"assignment-{assignment.id}",
        )
    for placement in draft.get("image_placements", []) if isinstance(draft, dict) else []:
        if isinstance(placement, dict) and placement.get("key"):
            add("media_placement", "main", {"generated_page_id": generated.id, "placement_key": placement["key"]}, "placeholder", str(placement["key"]))
    approved_links = _approved_links(session, plan, planned)
    draft_related_pages = _approved_draft_related_pages(session, plan, planned, generated)
    if approved_links or draft_related_pages:
        key = "destination_cards" if planned.page_type in {"service", "county", "city_service"} else "related_page_links"
        add(
            key,
            "main",
            {
                "internal_link_intent_ids": [item.id for item in approved_links],
                "draft_related_page_ids": [item.id for item in draft_related_pages],
            },
        )
    faq_items = draft.get("faq_items") if isinstance(draft, dict) else None
    if isinstance(faq_items, list) and faq_items:
        add("faq", "main", {"generated_page_id": generated.id})
    if planned.page_type == "contact":
        add("contact_pathways", "main", {"website_id": plan.website_id})
    add("final_cta", "main", {"generated_page_id": generated.id, "website_id": plan.website_id})
    footer = nav_sets.get("footer")
    if not footer:
        raise PageCompositionError("Required footer Navigation Set is missing.")
    add("footer_navigation", "footer", {"navigation_set_id": footer.id})
    add("website_footer", "footer", {"website_id": plan.website_id})
    return items


def _read(session: Session, composition: PageComposition, *, require_current: bool) -> PageCompositionRead:
    plan = _plan(session, composition.site_plan_id)
    planned = session.get(PlannedPage, composition.planned_page_id)
    generated = session.get(GeneratedPage, composition.generated_page_id)
    if not planned or not generated:
        raise PageCompositionError("Composition source records are missing.")
    errors = _validate(session, composition, plan, planned, generated, raise_on_error=False)
    current_hash = _hash(_source_snapshot(session, plan, planned, generated))
    if current_hash != composition.source_hash:
        errors.append("Composition is stale because an authoritative source changed.")
    if require_current and errors:
        raise PageCompositionError(" ".join(errors))
    effective = _effective(composition)
    resolved = [_resolve_instance(session, composition, generated, item) for item in effective]
    resolved_theme = _resolved_theme(session, composition.website_id)
    values = composition.model_dump()
    values["status"] = "current" if not errors else "stale"
    return PageCompositionRead(
        **values,
        effective_components=resolved,
        resolved_theme=resolved_theme.model_dump(mode="json"),
        validation_errors=errors,
    )


def _effective(composition: PageComposition) -> list[dict[str, Any]]:
    decisions = {item["instance_key"]: item for item in composition.operator_decisions}
    effective: list[dict[str, Any]] = []
    for generated in composition.generated_components:
        decision = decisions.get(generated["instance_key"])
        if decision and decision.get("action") == "suppress":
            continue
        value = dict(generated)
        if decision:
            if decision.get("variant") is not None:
                value["variant"] = decision["variant"]
            if decision.get("position") is not None:
                value["position"] = decision["position"]
            value["operator_decision"] = decision
        effective.append(value)
    return sorted(effective, key=lambda item: (item["position"], item["instance_key"]))


def _validate(session: Session, composition: PageComposition, plan: SitePlan, planned: PlannedPage, generated: GeneratedPage, *, raise_on_error: bool = True) -> list[str]:
    errors: list[str] = []
    if composition.website_id != plan.website_id or planned.website_id != plan.website_id or generated.website_id != plan.website_id:
        errors.append("Composition crosses a Website ownership boundary.")
    if composition.site_plan_id != planned.site_plan_id or composition.generated_page_id != planned.generated_page_id:
        errors.append("Composition source relationships do not match.")
    try:
        _active_identity_assets(session, plan.website_id)
    except PageCompositionError as exc:
        errors.append(str(exc))
    definitions = _definitions(session)
    generated_keys = {
        item.get("instance_key") for item in composition.generated_components
    }
    decision_keys = [
        item.get("instance_key") for item in composition.operator_decisions
    ]
    if len(decision_keys) != len(set(decision_keys)):
        errors.append("Operator decisions contain duplicate component instances.")
    if any(key not in generated_keys for key in decision_keys):
        errors.append("An operator decision references a component no longer generated by Atlas.")
    generated_by_key = {
        item.get("instance_key"): item for item in composition.generated_components
    }
    if any(
        item.get("action") == "suppress"
        and generated_by_key.get(item.get("instance_key"), {}).get("component_key")
        in NON_SUPPRESSIBLE_COMPONENTS
        for item in composition.operator_decisions
    ):
        errors.append("A required structural component has an invalid suppression decision.")
    seen: set[str] = set()
    for item in _effective(composition):
        instance_key = item.get("instance_key")
        if not instance_key or instance_key in seen:
            errors.append("Component instance keys must be present and unique.")
            continue
        seen.add(instance_key)
        definition = definitions.get(
            (item.get("component_key"), item.get("contract_version"))
        )
        if not definition or definition.contract_version != item.get("contract_version"):
            errors.append(f"Unknown component contract for {instance_key}.")
            continue
        if "all" not in definition.compatible_page_types and planned.page_type not in definition.compatible_page_types:
            errors.append(f"Component {instance_key} is incompatible with {planned.page_type} pages.")
        if item.get("variant") not in definition.supported_variants:
            errors.append(f"Component {instance_key} uses an unsupported variant.")
        available = _available_inputs(session, plan, planned, generated, item)
        missing = [required for required in definition.required_inputs if required not in available]
        if missing:
            errors.append(f"Component {instance_key} is missing approved inputs: {', '.join(missing)}.")
    if raise_on_error and errors:
        raise PageCompositionError(" ".join(errors))
    return errors


def _available_inputs(session: Session, plan: SitePlan, planned: PlannedPage, generated: GeneratedPage, item: dict[str, Any]) -> set[str]:
    draft = generated.draft_content or {}
    context = build_website_context(session, page_id=generated.id)
    available = {"website_identity"} if context.identity.display_name else set()
    if context.business.id and context.business.company_name and context.business.business_type:
        available.add("business_identity")
    if context.brand.id and context.brand.public_name:
        available.add("brand")
    if context.business.phone or context.business.email:
        available.add("contact_information")
    if context.business.license_number or context.business.certified_operator:
        available.add("trust_information")
    if planned.service_id and session.get(Service, planned.service_id):
        available.add("service")
    if draft.get("h1"):
        available.add("draft:h1")
    if draft.get("intro"):
        available.add("draft:intro")
    if draft.get("call_to_action"):
        available.add("draft:call_to_action")
    if draft.get("title") or generated.page_title:
        available.add("draft:title")
    if draft.get("faq_items"):
        available.add("draft:faq_items")
    bindings = item.get("input_bindings", {})
    if bindings.get("section_key") in {section["key"] for section in _draft_sections(draft)}:
        available.add("draft:section")
    placement_keys = {value.get("key") for value in draft.get("image_placements", []) if isinstance(value, dict)}
    if bindings.get("placement_key") in placement_keys:
        available.add("media_placement")
    assignment_id = bindings.get("page_image_assignment_id")
    if assignment_id:
        assignment = session.get(PageImageAssignment, assignment_id)
        image = session.get(ImageMetadata, assignment.image_metadata_id) if assignment else None
        if (
            assignment
            and assignment.generated_page_id == generated.id
            and assignment.status == "active"
            and image
            and image.business_id == generated.business_id
            and image.review_status == "reviewed"
        ):
            available.add("media_placement")
    nav_id = bindings.get("navigation_set_id")
    if nav_id:
        nav = session.get(NavigationSet, nav_id)
        nav_items = list(session.exec(select(NavigationItem).where(
            NavigationItem.navigation_set_id == nav_id,
            NavigationItem.status == "active",
        )).all())
        nav_targets = [session.get(PlannedPage, value.target_planned_page_id) for value in nav_items]
        if (
            nav
            and nav.website_id == plan.website_id
            and nav.site_plan_id == plan.id
            and all(
                target
                and target.website_id == plan.website_id
                and target.site_plan_id == plan.id
                for target in nav_targets
            )
        ):
            available.add(f"navigation:{nav.set_type}")
    link_ids = bindings.get("internal_link_intent_ids", [])
    links = [session.get(InternalLinkIntent, link_id) for link_id in link_ids]
    if link_ids and all(
        link
        and link.website_id == plan.website_id
        and link.site_plan_id == plan.id
        and link.source_planned_page_id == planned.id
        and link.approval_state == "approved"
        and (target := session.get(PlannedPage, link.target_planned_page_id))
        and target.website_id == plan.website_id
        and target.site_plan_id == plan.id
        for link in links
    ):
        available.add("related_pages")
    draft_related_ids = bindings.get("draft_related_page_ids", [])
    draft_related = [session.get(PlannedPage, page_id) for page_id in draft_related_ids]
    if draft_related_ids and all(
        target
        and target.id != planned.id
        and target.website_id == plan.website_id
        and target.site_plan_id == plan.id
        for target in draft_related
    ):
        available.add("related_pages")
    return available


def _resolve_instance(session: Session, composition: PageComposition, generated: GeneratedPage, item: dict[str, Any]) -> PageComponentInstance:
    context = build_website_context(session, page_id=generated.id)
    draft = generated.draft_content or {}
    bindings = item.get("input_bindings", {})
    data: dict[str, Any] = {}
    key = item["component_key"]
    if key in {"website_header", "website_footer", "trust_license", "contact_pathways"}:
        data.update({
            "display_name": context.identity.display_name,
            "tagline": context.brand.tagline,
            "company_name": context.business.company_name,
            "business_type": context.business.business_type,
            "phone": context.business.phone,
            "email": context.business.email,
            "license_number": context.business.license_number,
            "certified_operator": context.business.certified_operator,
        })
        identity_assets = _active_identity_assets(session, composition.website_id)
        data["identity_assets"] = {
            slot: {
                "asset_id": asset.id,
                "asset_key": asset.asset_key,
                "version": asset.version,
                "asset_type": asset.asset_type,
                "asset_url": (
                    asset.asset_url
                    if slot in {"favicon", "browser_icon", "apple_touch_icon"}
                    else asset.optimized_url or asset.asset_url
                ),
                "accessibility_description": asset.accessibility_description,
            }
            for slot, asset in identity_assets.items()
        }
    elif key.endswith("navigation"):
        nav_id = bindings["navigation_set_id"]
        nav = session.get(NavigationSet, nav_id)
        nav_items = list(session.exec(select(NavigationItem).where(NavigationItem.navigation_set_id == nav_id, NavigationItem.status == "active").order_by(NavigationItem.position, NavigationItem.id)).all())
        targets = {page.id: page for page in session.exec(select(PlannedPage).where(PlannedPage.site_plan_id == composition.site_plan_id)).all()}
        data = {"label": nav.label if nav else key.replace("_", " ").title(), "items": [
            {"label": value.label, "slug": targets[value.target_planned_page_id].intended_slug, "parent_navigation_item_id": value.parent_navigation_item_id}
            for value in nav_items if value.target_planned_page_id in targets
        ]}
    elif key == "hero":
        data = {"title": draft.get("h1"), "intro": draft.get("intro"), "phone": context.business.phone, "email": context.business.email, "page_type": generated.page_type}
    elif key in {"content_section", "service_summary"}:
        section = next(value for value in _draft_sections(draft) if value["key"] == bindings["section_key"])
        data = dict(section)
        if generated.service_id:
            service = session.get(Service, generated.service_id)
            data["service_name"] = service.service_name if service else None
    elif key == "media_placement":
        if bindings.get("page_image_assignment_id"):
            assignment = session.get(
                PageImageAssignment,
                bindings["page_image_assignment_id"],
            )
            image = session.get(ImageMetadata, assignment.image_metadata_id) if assignment else None
            if assignment and image:
                data = {
                    "purpose": assignment.image_role.replace("_", " ").title(),
                    "image_role": assignment.image_role,
                    "asset_url": image.optimized_url or image.asset_url,
                    "alt_text": assignment.override_alt_text or image.reviewed_alt_text or image.alt_text,
                    "image_title": image.image_title,
                    "caption": image.caption,
                    "focal_x": assignment.override_focal_x if assignment.override_focal_x is not None else image.focal_x,
                    "focal_y": assignment.override_focal_y if assignment.override_focal_y is not None else image.focal_y,
                }
        else:
            data = next(value for value in draft.get("image_placements", []) if value.get("key") == bindings["placement_key"])
    elif key in {"related_page_links", "destination_cards"}:
        links = [session.get(InternalLinkIntent, value) for value in bindings.get("internal_link_intent_ids", [])]
        targets = {page.id: page for page in session.exec(select(PlannedPage).where(PlannedPage.site_plan_id == composition.site_plan_id)).all()}
        resolved_links = [
            {"label": targets[link.target_planned_page_id].working_name, "slug": targets[link.target_planned_page_id].intended_slug, "purpose": link.purpose, "relationship_type": link.relationship_type}
            for link in links if link and link.target_planned_page_id in targets
        ]
        seen_targets = {
            link.target_planned_page_id
            for link in links
            if link and link.target_planned_page_id in targets
        }
        for target_id in bindings.get("draft_related_page_ids", []):
            target = targets.get(target_id)
            if target and target.id not in seen_targets:
                resolved_links.append({
                    "label": target.working_name,
                    "slug": target.intended_slug,
                    "purpose": "Explore approved related service information.",
                    "relationship_type": "approved_draft_relationship",
                })
                seen_targets.add(target.id)
        data = {"links": resolved_links}
    elif key == "faq":
        data = {"items": draft.get("faq_items", [])}
    elif key == "final_cta":
        data = {"heading": draft.get("title") or generated.page_title, "body": draft.get("call_to_action"), "phone": context.business.phone, "email": context.business.email}
    return PageComponentInstance(**item, resolved_data=data)


def _source_snapshot(session: Session, plan: SitePlan, planned: PlannedPage, generated: GeneratedPage) -> dict[str, Any]:
    nav_sets = list(session.exec(select(NavigationSet).where(NavigationSet.site_plan_id == plan.id).order_by(NavigationSet.id)).all())
    nav_items = list(session.exec(select(NavigationItem).where(NavigationItem.site_plan_id == plan.id).order_by(NavigationItem.id)).all())
    links = list(session.exec(select(InternalLinkIntent).where(InternalLinkIntent.site_plan_id == plan.id, InternalLinkIntent.source_planned_page_id == planned.id).order_by(InternalLinkIntent.id)).all())
    assignments = list(session.exec(select(PageImageAssignment).where(PageImageAssignment.generated_page_id == generated.id).order_by(PageImageAssignment.id)).all())
    images = {
        assignment.image_metadata_id: session.get(ImageMetadata, assignment.image_metadata_id)
        for assignment in assignments
    }
    context = build_website_context(session, page_id=generated.id)
    identity_assets = _active_identity_assets(session, plan.website_id)
    resolved_theme = _resolved_theme(session, plan.website_id)
    snapshot = {
        "website_id": plan.website_id,
        "site_plan_id": plan.id,
        "site_plan_version": plan.version,
        "planned_page_id": planned.id,
        "planned_page_updated_at": planned.updated_at.isoformat(),
        "generated_page_id": generated.id,
        "generated_page_updated_at": generated.updated_at.isoformat(),
        "draft_hash": _hash(generated.draft_content),
        "website_identity_id": context.identity.id,
        "website_context_hash": _hash(context.model_dump(mode="json")),
        "theme": resolved_theme.source_identity,
        "navigation_sets": [{"id": item.id, "type": item.set_type, "version": item.version, "updated_at": item.updated_at.isoformat()} for item in nav_sets],
        "navigation_items": [{"id": item.id, "target": item.target_planned_page_id, "position": item.position, "status": item.status, "updated_at": item.updated_at.isoformat()} for item in nav_items],
        "internal_links": [{"id": item.id, "target": item.target_planned_page_id, "approval_state": item.approval_state, "updated_at": item.updated_at.isoformat()} for item in links],
        "media_assignments": [
            {
                "id": item.id,
                "image_metadata_id": item.image_metadata_id,
                "role": item.image_role,
                "status": item.status,
                "updated_at": item.updated_at.isoformat(),
                "image_updated_at": images[item.image_metadata_id].updated_at.isoformat()
                if images[item.image_metadata_id]
                else None,
            }
            for item in assignments
        ],
    }
    if identity_assets:
        snapshot["website_identity_assets"] = [
            {
                "slot": slot,
                "asset_id": asset.id,
                "asset_key": asset.asset_key,
                "asset_version": asset.version,
                "checksum_sha256": asset.checksum_sha256,
                "status": asset.status,
                "updated_at": asset.updated_at.isoformat(),
            }
            for slot, asset in sorted(identity_assets.items())
        ]
    return snapshot


def _resolved_theme(session: Session, website_id: int):
    """Resolve the single authoritative Website Theme or its explicit neutral fallback."""

    from app.services.themes import ThemeError, resolve_website_theme

    try:
        return resolve_website_theme(session, website_id)
    except ThemeError as exc:
        raise PageCompositionError(f"Website Theme resolution failed closed: {exc}") from exc


def _active_identity_assets(session: Session, website_id: int) -> dict[str, BrandAsset]:
    website = session.get(Website, website_id)
    if not website:
        raise PageCompositionError("Website Identity asset resolution requires an existing Website.")
    identity = session.exec(
        select(WebsiteIdentity).where(WebsiteIdentity.website_id == website_id)
    ).first()
    if not identity:
        raise PageCompositionError("Website Identity asset resolution requires Website Identity.")
    rows = list(session.exec(
        select(WebsiteIdentityAssetAssignment).where(
            WebsiteIdentityAssetAssignment.website_identity_id == identity.id,
            WebsiteIdentityAssetAssignment.status == "active",
        )
    ).all())
    result: dict[str, BrandAsset] = {}
    for row in rows:
        if row.slot in result:
            raise PageCompositionError(f"Website Identity has multiple active selections for {row.slot}.")
        asset = session.get(BrandAsset, row.brand_asset_id)
        if (
            not asset
            or asset.status != "approved"
            or asset.brand_id != website.brand_id
            or asset.business_id != website.business_id
            or row.website_id != website.id
            or row.brand_id != website.brand_id
            or identity_asset_contract_error(asset, row.slot) is not None
        ):
            raise PageCompositionError(f"Website Identity selection for {row.slot} is invalid or crosses an ownership boundary.")
        result[row.slot] = asset
    return result


def _definitions(
    session: Session,
) -> dict[tuple[str, int], SemanticComponentDefinition]:
    values = list(session.exec(select(SemanticComponentDefinition).where(SemanticComponentDefinition.status == "active")).all())
    if not values:
        raise PageCompositionError("Semantic Component Registry is missing; apply migration 20260801_0037.")
    return {
        (value.component_key, value.contract_version): value for value in values
    }


def _approved_links(session: Session, plan: SitePlan, planned: PlannedPage) -> list[InternalLinkIntent]:
    return list(session.exec(select(InternalLinkIntent).where(
        InternalLinkIntent.website_id == plan.website_id,
        InternalLinkIntent.site_plan_id == plan.id,
        InternalLinkIntent.source_planned_page_id == planned.id,
        InternalLinkIntent.approval_state == "approved",
    ).order_by(InternalLinkIntent.id)).all())


def _approved_draft_related_pages(
    session: Session,
    plan: SitePlan,
    planned: PlannedPage,
    generated: GeneratedPage,
) -> list[PlannedPage]:
    raw = generated.draft_content.get("related_pages", []) if generated.draft_content else []
    if not raw:
        return []
    if not isinstance(raw, list):
        raise PageCompositionError("Approved draft related pages must be a list.")
    pages = list(session.exec(
        select(PlannedPage).where(
            PlannedPage.website_id == plan.website_id,
            PlannedPage.site_plan_id == plan.id,
        )
    ).all())
    by_slug = {page.intended_slug.strip("/"): page for page in pages}
    resolved: list[PlannedPage] = []
    seen: set[int] = set()
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("slug"), str):
            raise PageCompositionError("Approved draft related page identity is malformed.")
        target = by_slug.get(item["slug"].strip("/"))
        if not target or target.id == planned.id:
            raise PageCompositionError(
                f"Approved draft related page is missing or crosses the Website boundary: {item['slug']}."
            )
        if target.id not in seen:
            resolved.append(target)
            seen.add(target.id)
    return resolved


def _draft_sections(draft: dict[str, Any]) -> list[dict[str, str]]:
    if draft.get("schema_version") == "planned-page-draft-v1":
        return [value for value in draft.get("sections", []) if isinstance(value, dict) and value.get("key") and value.get("heading") and value.get("body")]
    fields = (
        ("why_it_matters", "Why It Matters"), ("signs_section", "What to Look For"),
        ("process_section", "How Service Works"), ("prep_section", "Preparing the Property"),
        ("local_city_section", "Local Service"), ("realtor_property_manager_section", "Coordinated Service"),
        ("why_choose_section", "Why Choose This Business"),
    )
    return [{"key": key, "heading": heading, "body": str(draft[key])} for key, heading in fields if draft.get(key)]


def _has_trust(session: Session, generated: GeneratedPage) -> bool:
    context = build_website_context(session, page_id=generated.id)
    return bool(context.business.license_number or context.business.certified_operator)


def _plan(session: Session, plan_id: int) -> SitePlan:
    plan = session.get(SitePlan, plan_id)
    if not plan:
        raise PageCompositionError("Site Plan not found.")
    return plan


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
