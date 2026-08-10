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
    PlannedPageMediaRequirement,
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
from app.services.brand_assets import identity_asset_contract_error
from app.services.page_media_roles import (
    SemanticMediaRoleError,
    resolve_semantic_media_role,
)
from app.services.scoped_media_authorizations import (
    asset_requires_exact_scoped_use,
    current_scoped_media_authorization,
)
from app.services.website_context import build_website_context
from app.services.website_media_safety import (
    is_image_metadata_excluded,
)


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
        if value.action == "suppress" and any(
            generated.get("component_key") == "media_placement"
            and (generated.get("input_bindings") or {}).get(
                "target_component_instance_key"
            )
            == value.instance_key
            and (generated.get("input_bindings") or {}).get(
                "media_requirement_id"
            )
            for generated in composition.generated_components
        ):
            raise PageCompositionError(
                "Component instance cannot be suppressed while an active Page Media "
                f"placement targets it: {value.instance_key}."
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
    from app.services.page_media_planning import validate_required_media_for_page

    # The controlled regeneration path may inspect the stale predecessor's
    # stable instance identities. The newly generated composition is validated
    # again below with the normal strict-current rule before it can persist.
    media_errors = validate_required_media_for_page(
        session,
        planned,
        require_approved_assignments=False,
        allow_composition_refresh_predecessor=True,
    )
    if media_errors:
        raise PageCompositionError(" ".join(media_errors))
    snapshot = _source_snapshot(session, plan, planned, generated)
    source_hash = _hash(snapshot)
    existing = session.exec(select(PageComposition).where(PageComposition.planned_page_id == planned.id)).first()
    suppressed_instance_keys = {
        str(value.get("instance_key") or "").strip()
        for value in (existing.operator_decisions if existing else [])
        if isinstance(value, dict)
        and value.get("action") == "suppress"
        and str(value.get("instance_key") or "").strip()
    }
    components = _generate_components(
        session,
        plan,
        planned,
        generated,
        suppressed_instance_keys=suppressed_instance_keys,
    )
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


def _generate_components(
    session: Session,
    plan: SitePlan,
    planned: PlannedPage,
    generated: GeneratedPage,
    *,
    suppressed_instance_keys: set[str],
) -> list[dict[str, Any]]:
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
        _require_authoritative_navigation_set(nav, plan)
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
    from app.services.page_media_planning import (
        effective_media_requirements,
        governed_assignment_for_requirement,
    )

    media_requirements = effective_media_requirements(session, planned.id or 0)
    if media_requirements:
        for requirement in media_requirements:
            if requirement.requirement_state in {"excluded", "deferred"}:
                continue
            assignment = governed_assignment_for_requirement(
                session,
                requirement.id or 0,
            )
            if assignment:
                assigned_image = session.get(
                    ImageMetadata,
                    assignment.image_metadata_id,
                )
                website = session.get(Website, plan.website_id)
                if is_image_metadata_excluded(website, assigned_image):
                    assignment = None
            bindings: dict[str, Any] = {
                "media_requirement_id": requirement.id,
                "target_component_key": requirement.component_or_section,
                "target_component_instance_key": (
                    requirement.target_component_instance_key
                ),
                "placement_contract_version": requirement.contract_version,
            }
            if assignment:
                bindings["page_image_assignment_id"] = assignment.id
            add(
                "media_placement",
                "main",
                bindings,
                "approved_media" if assignment else "placeholder",
                f"requirement-{requirement.id}",
            )
    else:
        # Preserve legacy compositions exactly until an operator creates a governed
        # Page Media plan for this Site Plan.
        assignments = list(session.exec(select(PageImageAssignment).where(
            PageImageAssignment.generated_page_id == generated.id,
            PageImageAssignment.status == "active",
        ).order_by(PageImageAssignment.sort_order, PageImageAssignment.id)).all())
        website = session.get(Website, plan.website_id)
        for assignment in assignments:
            image = session.get(ImageMetadata, assignment.image_metadata_id)
            if is_image_metadata_excluded(website, image):
                continue
            if image is not None and asset_requires_exact_scoped_use(session, image):
                raise PageCompositionError(
                    "Scoped governed media cannot enter a legacy or fallback composition path."
                )
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
    _require_authoritative_navigation_set(footer, plan)
    add("footer_navigation", "footer", {"navigation_set_id": footer.id})
    add("website_footer", "footer", {"website_id": plan.website_id})
    return _bind_governed_media_regions(
        items,
        suppressed_instance_keys=suppressed_instance_keys,
    )


def _bind_governed_media_regions(
    items: list[dict[str, Any]],
    *,
    suppressed_instance_keys: set[str],
) -> list[dict[str, Any]]:
    governed_media: list[dict[str, Any]] = []
    base_items: list[dict[str, Any]] = []
    for item in items:
        bindings = item.get("input_bindings") or {}
        if (
            item.get("component_key") == "media_placement"
            and bindings.get("media_requirement_id")
        ):
            governed_media.append(item)
        else:
            base_items.append(item)

    media_by_target: dict[str, list[dict[str, Any]]] = {}
    base_by_instance: dict[str, dict[str, Any]] = {}
    for item in base_items:
        instance_key = str(item.get("instance_key") or "").strip()
        if not instance_key:
            raise PageCompositionError(
                "Page Composition contains a component without an exact instance key."
            )
        if instance_key in base_by_instance:
            raise PageCompositionError(
                "Page Composition contains a duplicate exact component instance: "
                f"{instance_key}."
            )
        base_by_instance[instance_key] = item
    for media in governed_media:
        bindings = media["input_bindings"]
        target_key = bindings.get("target_component_key")
        target_instance_key = str(
            bindings.get("target_component_instance_key") or ""
        ).strip()
        contract_version = int(bindings.get("placement_contract_version") or 1)
        if target_instance_key:
            target = base_by_instance.get(target_instance_key)
            if (
                target is None
                or target_instance_key in suppressed_instance_keys
            ):
                raise PageCompositionError(
                    "Approved Page Media placement cannot resolve its exact component "
                    f"instance: {target_instance_key}."
                )
            if target.get("component_key") != target_key:
                raise PageCompositionError(
                    "Approved Page Media placement exact instance no longer matches "
                    f"component {target_key}: {target_instance_key}."
                )
        elif contract_version >= 2:
            raise PageCompositionError(
                "V2 Page Media placement is missing its exact component-instance selector."
            )
        else:
            candidates = [
                item
                for item in base_items
                if item.get("component_key") == target_key
                and item.get("instance_key") not in suppressed_instance_keys
            ]
            if not candidates:
                raise PageCompositionError(
                    "Legacy Page Media placement cannot resolve its semantic component "
                    f"or region: {target_key}."
                )
            target = candidates[-1]
            target_instance_key = str(target["instance_key"])
            bindings["target_component_instance_key"] = target_instance_key
        bindings["target_region"] = target["region"]
        media["region"] = target["region"]
        if target_instance_key in media_by_target:
            raise PageCompositionError(
                "Multiple governed Page Media placements target the same exact "
                f"component instance: {target_instance_key}."
            )
        media_by_target.setdefault(target_instance_key, []).append(media)

    ordered: list[dict[str, Any]] = []
    for item in base_items:
        ordered.append(item)
        ordered.extend(media_by_target.get(item["instance_key"], []))
    for position, item in enumerate(ordered):
        item["position"] = position
    return ordered


def _read(session: Session, composition: PageComposition, *, require_current: bool) -> PageCompositionRead:
    plan = _plan(session, composition.site_plan_id)
    planned = session.get(PlannedPage, composition.planned_page_id)
    generated = session.get(GeneratedPage, composition.generated_page_id)
    if not planned or not generated:
        raise PageCompositionError("Composition source records are missing.")
    errors = _validate(session, composition, plan, planned, generated, raise_on_error=False)
    try:
        current_hash = _hash(_source_snapshot(session, plan, planned, generated))
    except PageCompositionError as exc:
        errors.append(str(exc))
    else:
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
    suppressed_instance_keys = {
        instance_key
        for instance_key, decision in decisions.items()
        if decision.get("action") == "suppress"
    }
    effective: list[dict[str, Any]] = []
    for generated in composition.generated_components:
        decision = decisions.get(generated["instance_key"])
        if decision and decision.get("action") == "suppress":
            continue
        if (
            generated.get("component_key") == "media_placement"
            and (generated.get("input_bindings") or {}).get(
                "target_component_instance_key"
            )
            in suppressed_instance_keys
        ):
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
    from app.services.page_media_planning import validate_required_media_for_page

    errors.extend(
        validate_required_media_for_page(
            session,
            planned,
            require_approved_assignments=False,
        )
    )
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
        bindings = item.get("input_bindings") or {}
        if (
            item.get("component_key") == "media_placement"
            and bindings.get("media_requirement_id")
        ):
            requirement = session.get(
                PlannedPageMediaRequirement,
                bindings["media_requirement_id"],
            )
            if (
                requirement is not None
                and bindings.get("placement_contract_version")
                != requirement.contract_version
            ):
                errors.append(
                    f"Page Media component {instance_key} placement contract version "
                    "does not match its governed requirement."
                )
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
    requirement_id = bindings.get("media_requirement_id")
    requirement = None
    if requirement_id:
        requirement = session.get(PlannedPageMediaRequirement, requirement_id)
        if (
            requirement
            and requirement.website_id == plan.website_id
            and requirement.site_plan_id == plan.id
            and requirement.planned_page_id == planned.id
            and requirement.lifecycle_status == "active"
            and requirement.requirement_state in {"required", "advisory"}
            and bindings.get("target_component_key")
            == requirement.component_or_section
            and bindings.get("placement_contract_version")
            == requirement.contract_version
            and (
                requirement.contract_version < 2
                or (
                    requirement.target_component_instance_key
                    and bindings.get("target_component_instance_key")
                    == requirement.target_component_instance_key
                )
            )
        ):
            available.add("media_placement")
    assignment_id = bindings.get("page_image_assignment_id")
    if assignment_id:
        assignment = session.get(PageImageAssignment, assignment_id)
        image = session.get(ImageMetadata, assignment.image_metadata_id) if assignment else None
        website = session.get(Website, plan.website_id)
        governed_binding_valid = (
            requirement is not None
            and assignment is not None
            and assignment.media_requirement_id == requirement.id
            and assignment.website_id == plan.website_id
            and assignment.site_plan_id == plan.id
            and assignment.planned_page_id == planned.id
            and image is not None
            and assignment.media_version == image.media_version
            and assignment.placement_contract_version == requirement.contract_version
            and image.website_id == plan.website_id
            and image.governance_status == "approved"
            and image.retired_at is None
        )
        legacy_binding_valid = (
            requirement is None
            and assignment is not None
            and image is not None
            and image.review_status == "reviewed"
        )
        if (
            assignment
            and assignment.generated_page_id == generated.id
            and assignment.status == "active"
            and image
            and image.business_id == generated.business_id
            and not is_image_metadata_excluded(website, image)
            and (governed_binding_valid or legacy_binding_valid)
        ):
            available.add("media_placement")
    nav_id = bindings.get("navigation_set_id")
    if nav_id:
        nav, _ = _resolved_navigation_items(
            session,
            website_id=plan.website_id,
            site_plan_id=plan.id or 0,
            navigation_set_id=nav_id,
        )
        available.add(f"navigation:{nav.set_type}")
    link_ids = bindings.get("internal_link_intent_ids", [])
    if link_ids:
        _resolved_internal_links(
            session,
            website_id=plan.website_id,
            site_plan_id=plan.id or 0,
            source_planned_page_id=planned.id or 0,
            internal_link_intent_ids=link_ids,
        )
        available.add("related_pages")
    draft_related_ids = bindings.get("draft_related_page_ids", [])
    if draft_related_ids:
        _resolved_draft_related_targets(
            session,
            website_id=plan.website_id,
            site_plan_id=plan.id or 0,
            source_planned_page_id=planned.id or 0,
            target_planned_page_ids=draft_related_ids,
        )
        available.add("related_pages")
    return available


def _required_record_id(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PageCompositionError(f"{label} is missing or invalid.")
    return value


def _decision_provenance_complete(record: Any) -> bool:
    version = getattr(record, "decision_version", None)
    return (
        isinstance(getattr(record, "decided_by", None), str)
        and bool(record.decided_by.strip())
        and isinstance(getattr(record, "rationale", None), str)
        and bool(record.rationale.strip())
        and isinstance(version, int)
        and not isinstance(version, bool)
        and version >= 1
        and getattr(record, "decided_at", None) is not None
    )


def _require_authoritative_navigation_set(
    nav: NavigationSet,
    plan: SitePlan,
) -> None:
    if nav.website_id != plan.website_id or nav.site_plan_id != plan.id:
        raise PageCompositionError(
            "Navigation Set crosses the Website or Site Plan boundary."
        )
    if nav.status != "active":
        raise PageCompositionError("Navigation Set is not active.")
    if not _decision_provenance_complete(nav):
        raise PageCompositionError(
            "Active Navigation Set lacks authoritative operator decision provenance."
        )


def _resolved_target_page(
    session: Session,
    *,
    website_id: int,
    site_plan_id: int,
    target_planned_page_id: Any,
    role: str,
) -> PlannedPage:
    target_id = _required_record_id(target_planned_page_id, f"{role} target")
    target = session.get(PlannedPage, target_id)
    if target is None:
        raise PageCompositionError(f"{role} target Planned Page is missing.")
    if target.website_id != website_id or target.site_plan_id != site_plan_id:
        raise PageCompositionError(
            f"{role} target crosses the Website or Site Plan boundary."
        )
    if target.generated_page_id is not None:
        target_generated = session.get(GeneratedPage, target.generated_page_id)
        if target_generated is None:
            raise PageCompositionError(f"{role} target Generated Page is missing.")
        if target_generated.website_id != website_id:
            raise PageCompositionError(
                f"{role} target Generated Page crosses the Website boundary."
            )
    return target


def _resolved_navigation_items(
    session: Session,
    *,
    website_id: int,
    site_plan_id: int,
    navigation_set_id: Any,
) -> tuple[NavigationSet, list[tuple[NavigationItem, PlannedPage]]]:
    nav_id = _required_record_id(navigation_set_id, "Navigation Set binding")
    nav = session.get(NavigationSet, nav_id)
    if nav is None:
        raise PageCompositionError("Navigation Set binding is missing.")
    if nav.website_id != website_id or nav.site_plan_id != site_plan_id:
        raise PageCompositionError(
            "Navigation Set crosses the Website or Site Plan boundary."
        )
    if nav.status != "active":
        raise PageCompositionError("Navigation Set is not active.")
    if not _decision_provenance_complete(nav):
        raise PageCompositionError(
            "Active Navigation Set lacks authoritative operator decision provenance."
        )
    items = list(
        session.exec(
            select(NavigationItem)
            .where(
                NavigationItem.navigation_set_id == nav.id,
                NavigationItem.status == "active",
            )
            .order_by(NavigationItem.position, NavigationItem.id)
        ).all()
    )
    resolved: list[tuple[NavigationItem, PlannedPage]] = []
    for nav_item in items:
        if (
            nav_item.id is None
            or nav_item.website_id != website_id
            or nav_item.site_plan_id != site_plan_id
            or nav_item.navigation_set_id != nav.id
        ):
            raise PageCompositionError(
                "Navigation Item crosses the Website, Site Plan, or Navigation Set boundary."
            )
        target = _resolved_target_page(
            session,
            website_id=website_id,
            site_plan_id=site_plan_id,
            target_planned_page_id=nav_item.target_planned_page_id,
            role="Navigation Item",
        )
        resolved.append((nav_item, target))
    items_by_id = {
        item.id: item
        for item, _ in resolved
        if item.id is not None
    }
    for nav_item, _ in resolved:
        parent_id = nav_item.parent_navigation_item_id
        if parent_id is None:
            continue
        parent = items_by_id.get(parent_id)
        if parent is None:
            raise PageCompositionError(
                "Active Navigation Item parent is missing or inactive."
            )
        if not _decision_provenance_complete(parent):
            raise PageCompositionError(
                "Active Navigation Item parent lacks authoritative operator decision provenance."
            )
    for nav_item, _ in resolved:
        if not _decision_provenance_complete(nav_item):
            raise PageCompositionError(
                "Active Navigation Item lacks authoritative operator decision provenance."
            )

    target_owners: dict[int, int] = {}
    sibling_position_owners: dict[tuple[int | None, int], int] = {}
    sibling_label_owners: dict[tuple[int | None, str], int] = {}
    for nav_item, target in resolved:
        nav_item_id = nav_item.id or 0
        target_id = target.id or 0
        if target_id in target_owners:
            raise PageCompositionError(
                "Active Navigation Items cannot share the same target Planned Page."
            )
        target_owners[target_id] = nav_item_id
        position_key = (nav_item.parent_navigation_item_id, nav_item.position)
        if position_key in sibling_position_owners:
            raise PageCompositionError(
                "Active sibling Navigation Items cannot share the same position."
            )
        sibling_position_owners[position_key] = nav_item_id
        label_key = (
            nav_item.parent_navigation_item_id,
            nav_item.label.strip().casefold(),
        )
        if label_key in sibling_label_owners:
            raise PageCompositionError(
                "Active sibling Navigation Items cannot share a case-insensitive label."
            )
        sibling_label_owners[label_key] = nav_item_id
    parent_by_id = {
        item.id: item.parent_navigation_item_id
        for item, _ in resolved
        if item.id is not None
    }
    for start in parent_by_id:
        current: int | None = start
        seen: set[int] = set()
        while current is not None:
            if current in seen:
                raise PageCompositionError(
                    "Active Navigation Item hierarchy contains a cycle."
                )
            seen.add(current)
            current = parent_by_id.get(current)
    return nav, resolved


def _resolved_internal_links(
    session: Session,
    *,
    website_id: int,
    site_plan_id: int,
    source_planned_page_id: int,
    internal_link_intent_ids: list[Any],
) -> list[tuple[InternalLinkIntent, PlannedPage]]:
    resolved: list[tuple[InternalLinkIntent, PlannedPage]] = []
    seen_ids: set[int] = set()
    seen_target_ids: set[int] = set()
    for raw_link_id in internal_link_intent_ids:
        link_id = _required_record_id(raw_link_id, "Internal-link intent binding")
        if link_id in seen_ids:
            raise PageCompositionError("Internal-link intent binding is duplicated.")
        seen_ids.add(link_id)
        link = session.get(InternalLinkIntent, link_id)
        if link is None:
            raise PageCompositionError("Internal-link intent binding is missing.")
        if (
            link.website_id != website_id
            or link.site_plan_id != site_plan_id
            or link.source_planned_page_id != source_planned_page_id
        ):
            raise PageCompositionError(
                "Internal-link intent crosses the Website, Site Plan, or source-page boundary."
            )
        if link.approval_state != "approved":
            raise PageCompositionError("Internal-link intent is not approved.")
        if not _decision_provenance_complete(link):
            raise PageCompositionError(
                "Approved internal-link intent lacks authoritative operator decision provenance."
            )
        target = _resolved_target_page(
            session,
            website_id=website_id,
            site_plan_id=site_plan_id,
            target_planned_page_id=link.target_planned_page_id,
            role="Internal-link intent",
        )
        if target.id == source_planned_page_id:
            raise PageCompositionError("Internal-link intent cannot target its source page.")
        target_id = target.id or 0
        if target_id in seen_target_ids:
            raise PageCompositionError(
                "Approved internal-link intents for one source cannot share a target Planned Page."
            )
        seen_target_ids.add(target_id)
        resolved.append((link, target))
    return resolved


def _resolved_draft_related_targets(
    session: Session,
    *,
    website_id: int,
    site_plan_id: int,
    source_planned_page_id: int,
    target_planned_page_ids: list[Any],
) -> list[PlannedPage]:
    resolved: list[PlannedPage] = []
    seen_ids: set[int] = set()
    for raw_target_id in target_planned_page_ids:
        target = _resolved_target_page(
            session,
            website_id=website_id,
            site_plan_id=site_plan_id,
            target_planned_page_id=raw_target_id,
            role="Draft-related page",
        )
        if target.id == source_planned_page_id:
            raise PageCompositionError("Draft-related page cannot target its source page.")
        if target.id in seen_ids:
            raise PageCompositionError("Draft-related page binding is duplicated.")
        seen_ids.add(target.id or 0)
        resolved.append(target)
    return resolved


def _target_source_identity(
    session: Session,
    *,
    website_id: int,
    site_plan_id: int,
    target_planned_page_id: Any,
    role: str,
) -> dict[str, Any]:
    target = _resolved_target_page(
        session,
        website_id=website_id,
        site_plan_id=site_plan_id,
        target_planned_page_id=target_planned_page_id,
        role=role,
    )
    return {
        "planned_page_id": target.id,
        "website_id": target.website_id,
        "site_plan_id": target.site_plan_id,
        "generated_page_id": target.generated_page_id,
        "working_name": target.working_name,
        "intended_slug": target.intended_slug,
        "updated_at": target.updated_at.isoformat(),
    }


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
        nav, nav_items = _resolved_navigation_items(
            session,
            website_id=composition.website_id,
            site_plan_id=composition.site_plan_id,
            navigation_set_id=nav_id,
        )
        data = {
            "label": nav.label,
            "items": [
                {
                    "navigation_item_id": value.id,
                    "target_planned_page_id": target.id,
                    "target_generated_page_id": target.generated_page_id,
                    "label": value.label,
                    "slug": target.intended_slug,
                    "parent_navigation_item_id": value.parent_navigation_item_id,
                    "position": value.position,
                    "status": value.status,
                }
                for value, target in nav_items
            ],
        }
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
                website = session.get(Website, composition.website_id)
                if is_image_metadata_excluded(website, image):
                    raise PageCompositionError(
                        "Page composition references media excluded by the Website-scoped "
                        "external-media safety policy."
                    )
                requirement = (
                    session.get(
                        PlannedPageMediaRequirement,
                        bindings["media_requirement_id"],
                    )
                    if bindings.get("media_requirement_id")
                    else None
                )
                try:
                    semantic_role = resolve_semantic_media_role(
                        assignment,
                        session=session,
                        requirement=requirement,
                    )
                except SemanticMediaRoleError as exc:
                    raise PageCompositionError(str(exc)) from exc
                authorization = (
                    current_scoped_media_authorization(session, requirement.id or 0)
                    if requirement
                    else None
                )
                data = {
                    "purpose": (
                        requirement.purpose
                        if requirement
                        else semantic_role.replace("_", " ").title()
                    ),
                    "customer_outcome": requirement.customer_outcome if requirement else None,
                    "placement_key": requirement.placement_key if requirement else None,
                    "component_or_section": (
                        requirement.component_or_section if requirement else None
                    ),
                    "target_component_instance_key": bindings.get(
                        "target_component_instance_key"
                    ),
                    "target_region": bindings.get("target_region"),
                    "media_requirement_id": requirement.id if requirement else None,
                    "placement_contract_version": (
                        requirement.contract_version if requirement else None
                    ),
                    "image_role": semantic_role,
                    "scoped_authorization_id": (
                        authorization.id if authorization else None
                    ),
                    "scoped_authorization_version": (
                        authorization.authorization_version
                        if authorization
                        else None
                    ),
                    "scoped_authorization_fingerprint": (
                        authorization.authorization_fingerprint
                        if authorization
                        else None
                    ),
                    "asset_url": image.optimized_url or image.asset_url,
                    "alt_text": assignment.override_alt_text or image.reviewed_alt_text or image.alt_text,
                    "image_title": image.image_title,
                    "caption": image.caption,
                    "media_key": image.media_key,
                    "media_version": image.media_version,
                    "provenance_type": image.provenance_type,
                    "rights_status": image.rights_status,
                    "focal_x": assignment.override_focal_x if assignment.override_focal_x is not None else image.focal_x,
                    "focal_y": assignment.override_focal_y if assignment.override_focal_y is not None else image.focal_y,
                }
        elif bindings.get("media_requirement_id"):
            requirement = session.get(
                PlannedPageMediaRequirement,
                bindings["media_requirement_id"],
            )
            if requirement:
                data = {
                    "purpose": requirement.purpose,
                    "customer_outcome": requirement.customer_outcome,
                    "placement_key": requirement.placement_key,
                    "component_or_section": requirement.component_or_section,
                    "target_component_instance_key": bindings.get(
                        "target_component_instance_key"
                    ),
                    "target_region": bindings.get("target_region"),
                    "intended_subject": requirement.intended_subject,
                    "accessibility_intent": requirement.accessibility_intent,
                    "requirement_state": requirement.requirement_state,
                    "media_requirement_id": requirement.id,
                    "placement_contract_version": requirement.contract_version,
                }
        else:
            data = next(value for value in draft.get("image_placements", []) if value.get("key") == bindings["placement_key"])
    elif key in {"related_page_links", "destination_cards"}:
        links = _resolved_internal_links(
            session,
            website_id=composition.website_id,
            site_plan_id=composition.site_plan_id,
            source_planned_page_id=composition.planned_page_id,
            internal_link_intent_ids=bindings.get("internal_link_intent_ids", []),
        )
        resolved_links = [
            {
                "target_planned_page_id": target.id,
                "target_generated_page_id": target.generated_page_id,
                "label": target.working_name,
                "slug": target.intended_slug,
                "purpose": link.purpose,
                "relationship_type": link.relationship_type,
            }
            for link, target in links
        ]
        seen_targets = {
            link.target_planned_page_id
            for link, _ in links
        }
        draft_related = _resolved_draft_related_targets(
            session,
            website_id=composition.website_id,
            site_plan_id=composition.site_plan_id,
            source_planned_page_id=composition.planned_page_id,
            target_planned_page_ids=bindings.get("draft_related_page_ids", []),
        )
        for target in draft_related:
            if target.id not in seen_targets:
                resolved_links.append({
                    "target_planned_page_id": target.id,
                    "target_generated_page_id": target.generated_page_id,
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
    links = list(session.exec(select(InternalLinkIntent).where(
        InternalLinkIntent.site_plan_id == plan.id,
        InternalLinkIntent.source_planned_page_id == planned.id,
        InternalLinkIntent.approval_state == "approved",
    ).order_by(InternalLinkIntent.id)).all())
    resolved_internal_links = _resolved_internal_links(
        session,
        website_id=plan.website_id,
        site_plan_id=plan.id or 0,
        source_planned_page_id=planned.id or 0,
        internal_link_intent_ids=[item.id for item in links],
    )
    resolved_navigation_items: list[tuple[NavigationItem, PlannedPage]] = []
    for nav_set in nav_sets:
        _require_authoritative_navigation_set(nav_set, plan)
        _, resolved_items = _resolved_navigation_items(
            session,
            website_id=plan.website_id,
            site_plan_id=plan.id or 0,
            navigation_set_id=nav_set.id,
        )
        resolved_navigation_items.extend(resolved_items)
    resolved_navigation_items.sort(key=lambda value: value[0].id or 0)
    nav_items = [item for item, _ in resolved_navigation_items]
    navigation_targets = {
        item.id: _target_source_identity(
            session,
            website_id=plan.website_id,
            site_plan_id=plan.id or 0,
            target_planned_page_id=item.target_planned_page_id,
            role="Navigation Item",
        )
        for item, _ in resolved_navigation_items
    }
    internal_link_targets = {
        item.id: _target_source_identity(
            session,
            website_id=plan.website_id,
            site_plan_id=plan.id or 0,
            target_planned_page_id=item.target_planned_page_id,
            role="Internal-link intent",
        )
        for item, _ in resolved_internal_links
    }
    draft_related_targets = [
        _target_source_identity(
            session,
            website_id=plan.website_id,
            site_plan_id=plan.id or 0,
            target_planned_page_id=target.id or 0,
            role="Draft-related page",
        )
        for target in _approved_draft_related_pages(session, plan, planned, generated)
    ]
    website = session.get(Website, plan.website_id)
    assignments = list(session.exec(select(PageImageAssignment).where(PageImageAssignment.generated_page_id == generated.id).order_by(PageImageAssignment.id)).all())
    assignments = [
        assignment
        for assignment in assignments
        if not is_image_metadata_excluded(
            website,
            session.get(ImageMetadata, assignment.image_metadata_id),
        )
    ]
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
        "navigation_sets": [
            {
                "id": item.id,
                "type": item.set_type,
                "label": item.label,
                "status": item.status,
                "version": item.version,
                "updated_at": item.updated_at.isoformat(),
            }
            for item in nav_sets
        ],
        "navigation_items": [
            {
                "id": item.id,
                "navigation_set_id": item.navigation_set_id,
                "target": navigation_targets[item.id],
                "parent_navigation_item_id": item.parent_navigation_item_id,
                "label": item.label,
                "position": item.position,
                "status": item.status,
                "updated_at": item.updated_at.isoformat(),
            }
            for item in nav_items
        ],
        "internal_links": [
            {
                "id": item.id,
                "target": internal_link_targets[item.id],
                "purpose": item.purpose,
                "relationship_type": item.relationship_type,
                "anchor_guidance": item.anchor_guidance,
                "approval_state": item.approval_state,
                "updated_at": item.updated_at.isoformat(),
            }
            for item in links
        ],
        "draft_related_targets": draft_related_targets,
        "media_assignments": [
            _media_assignment_source_identity(
                session,
                item,
                images[item.image_metadata_id],
            )
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
    from app.services.page_media_planning import (
        PageMediaPlanningError,
        media_source_snapshot,
    )

    try:
        page_media = media_source_snapshot(session, planned)
    except PageMediaPlanningError as exc:
        raise PageCompositionError(
            f"Page Media composition source failed closed: {exc}"
        ) from exc
    if page_media["planning_record"] is not None or page_media["requirements"]:
        snapshot["page_media"] = page_media
    return snapshot


def _semantic_role(
    session: Session,
    assignment: PageImageAssignment,
) -> str:
    try:
        return resolve_semantic_media_role(assignment, session=session)
    except SemanticMediaRoleError as exc:
        raise PageCompositionError(str(exc)) from exc


def _media_assignment_source_identity(
    session: Session,
    assignment: PageImageAssignment,
    image: ImageMetadata | None,
) -> dict[str, Any]:
    """Preserve legacy source hashes while binding governed semantic identity."""

    value: dict[str, Any] = {
        "id": assignment.id,
        "image_metadata_id": assignment.image_metadata_id,
        "role": (
            assignment.image_role
            if assignment.media_requirement_id is None
            else _semantic_role(session, assignment)
        ),
        "status": assignment.status,
        "updated_at": assignment.updated_at.isoformat(),
        "image_updated_at": image.updated_at.isoformat() if image else None,
    }
    if assignment.media_requirement_id is not None:
        value["storage_role_token"] = assignment.image_role
    return value


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
    links = list(session.exec(select(InternalLinkIntent).where(
        InternalLinkIntent.website_id == plan.website_id,
        InternalLinkIntent.site_plan_id == plan.id,
        InternalLinkIntent.source_planned_page_id == planned.id,
        InternalLinkIntent.approval_state == "approved",
    ).order_by(InternalLinkIntent.id)).all())
    for link in links:
        if not _decision_provenance_complete(link):
            raise PageCompositionError(
                "Approved internal-link intent lacks authoritative operator decision provenance."
            )
    return links


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
