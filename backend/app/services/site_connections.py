from __future__ import annotations

from collections import Counter, defaultdict, deque
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from app.models import (
    InternalLinkIntent,
    NavigationItem,
    NavigationSet,
    PlannedPage,
    SiteConnectionPlanningRecord,
    SitePlan,
)
from app.schemas.site_connections import (
    InternalLinkIntentCreate,
    InternalLinkIntentRead,
    InternalLinkIntentUpdate,
    NavigationItemCreate,
    NavigationItemRead,
    NavigationItemUpdate,
    NavigationSetRead,
    SiteConnectionDiagnostic,
    SiteConnectionPlanRead,
    SiteConnectionPlanningRecordRead,
)
from app.services.page_type_review import DEFERRED_PAGE_TYPES


NAVIGATION_SET_TYPES = ("primary", "utility", "footer")
NAVIGATION_SET_LABELS = {
    "primary": "Primary Navigation",
    "utility": "Utility Navigation",
    "footer": "Footer Navigation",
}
INTERNAL_LINK_RELATIONSHIP_TYPES = {
    "conversion",
    "hierarchy",
    "related_content",
    "supporting_information",
}


class SiteConnectionError(ValueError):
    pass


def ensure_site_connection_foundation(
    session: Session,
    plan: SitePlan,
    *,
    commit: bool = False,
) -> SiteConnectionPlanningRecord:
    if plan.id is None:
        session.add(plan)
        session.flush()
    for set_type in NAVIGATION_SET_TYPES:
        existing = session.exec(
            select(NavigationSet).where(
                NavigationSet.site_plan_id == plan.id,
                NavigationSet.set_type == set_type,
            )
        ).first()
        if existing is None:
            session.add(
                NavigationSet(
                    website_id=plan.website_id,
                    site_plan_id=plan.id or 0,
                    set_type=set_type,
                    label=NAVIGATION_SET_LABELS[set_type],
                    status="draft",
                )
            )
    session.flush()
    record = session.exec(
        select(SiteConnectionPlanningRecord).where(
            SiteConnectionPlanningRecord.site_plan_id == plan.id
        )
    ).first()
    if record is None:
        record = SiteConnectionPlanningRecord(
            website_id=plan.website_id,
            site_plan_id=plan.id or 0,
        )
        session.add(record)
        session.flush()
    _refresh_suggestions(session, plan, record)
    if commit:
        session.commit()
        session.refresh(record)
    return record


def refresh_site_connection_suggestions(
    session: Session,
    plan_id: int,
    *,
    commit: bool = True,
) -> SiteConnectionPlanningRecordRead:
    plan = _plan(session, plan_id)
    record = ensure_site_connection_foundation(session, plan, commit=False)
    _refresh_suggestions(session, plan, record)
    if commit:
        session.commit()
        session.refresh(record)
    return SiteConnectionPlanningRecordRead.model_validate(record)


def read_site_connection_plan(
    session: Session,
    plan_id: int,
) -> SiteConnectionPlanRead:
    plan = _plan(session, plan_id)
    sets = _sets(session, plan)
    if {item.set_type for item in sets} != set(NAVIGATION_SET_TYPES):
        raise SiteConnectionError(
            "Site connection foundation is incomplete; run the additive migration."
        )
    record = session.exec(
        select(SiteConnectionPlanningRecord).where(
            SiteConnectionPlanningRecord.site_plan_id == plan.id
        )
    ).first()
    if record is None:
        raise SiteConnectionError(
            "Site connection planning record is missing; run the additive migration."
        )
    items = _items(session, plan)
    intents = _intents(session, plan)
    diagnostics = evaluate_site_connection_diagnostics(
        session,
        plan,
        sets=sets,
        items=items,
        intents=intents,
    )
    return SiteConnectionPlanRead(
        website_id=plan.website_id,
        site_plan_id=plan.id or plan_id,
        navigation_sets=[
            NavigationSetRead.model_validate(item) for item in sets
        ],
        navigation_items=[
            NavigationItemRead.model_validate(item) for item in items
        ],
        internal_link_intents=[
            InternalLinkIntentRead.model_validate(item) for item in intents
        ],
        planning_record=SiteConnectionPlanningRecordRead.model_validate(record),
        diagnostics=diagnostics,
        ready=all(item.status == "ready" for item in diagnostics),
    )


def create_navigation_item(
    session: Session,
    payload: NavigationItemCreate,
) -> NavigationItemRead:
    plan = _plan(session, payload.site_plan_id)
    _require_website(plan, payload.website_id)
    nav_set = session.get(NavigationSet, payload.navigation_set_id)
    if (
        not nav_set
        or nav_set.site_plan_id != plan.id
        or nav_set.website_id != plan.website_id
        or nav_set.set_type not in NAVIGATION_SET_TYPES
    ):
        raise SiteConnectionError(
            "Navigation Set does not belong to the selected Website and Site Plan."
        )
    target = _eligible_page(session, plan, payload.target_planned_page_id, "target")
    parent = _navigation_parent(
        session,
        plan,
        nav_set,
        payload.parent_navigation_item_id,
    )
    label = _required_text(payload.label, "Navigation label")
    _validate_navigation_uniqueness(
        session,
        nav_set,
        target.id or 0,
        parent.id if parent else None,
        label,
        payload.position,
    )
    values = payload.model_dump()
    values["label"] = label
    item = NavigationItem(**values)
    session.add(item)
    session.commit()
    session.refresh(item)
    return NavigationItemRead.model_validate(item)


def update_navigation_item(
    session: Session,
    item_id: int,
    payload: NavigationItemUpdate,
) -> NavigationItemRead:
    item = _navigation_item(session, item_id)
    plan = _plan(session, item.site_plan_id)
    nav_set = session.get(NavigationSet, item.navigation_set_id)
    if not nav_set:
        raise SiteConnectionError("Navigation Set not found.")
    updates = payload.model_dump(exclude_unset=True)
    parent_id = updates.get(
        "parent_navigation_item_id",
        item.parent_navigation_item_id,
    )
    parent = _navigation_parent(session, plan, nav_set, parent_id)
    if parent and parent.id == item.id:
        raise SiteConnectionError("A Navigation Item cannot be its own parent.")
    label = _required_text(updates.get("label", item.label), "Navigation label")
    position = updates.get("position", item.position)
    _validate_navigation_uniqueness(
        session,
        nav_set,
        item.target_planned_page_id,
        parent.id if parent else None,
        label,
        position,
        item_id=item.id,
    )
    for key, value in updates.items():
        setattr(item, key, value)
    item.label = label
    item.updated_at = datetime.now(UTC)
    session.add(item)
    session.flush()
    if _navigation_cycle_ids(_items(session, plan)):
        session.rollback()
        raise SiteConnectionError("Navigation parent relationships cannot contain a cycle.")
    session.commit()
    session.refresh(item)
    return NavigationItemRead.model_validate(item)


def delete_navigation_item(session: Session, item_id: int) -> None:
    item = _navigation_item(session, item_id)
    child = session.exec(
        select(NavigationItem).where(
            NavigationItem.parent_navigation_item_id == item.id
        )
    ).first()
    if child:
        raise SiteConnectionError(
            "Remove or reparent child Navigation Items before deleting this item."
        )
    session.delete(item)
    session.commit()


def create_internal_link_intent(
    session: Session,
    payload: InternalLinkIntentCreate,
) -> InternalLinkIntentRead:
    plan = _plan(session, payload.site_plan_id)
    _require_website(plan, payload.website_id)
    source = _eligible_page(
        session,
        plan,
        payload.source_planned_page_id,
        "source",
    )
    target = _eligible_page(
        session,
        plan,
        payload.target_planned_page_id,
        "target",
    )
    if source.id == target.id:
        raise SiteConnectionError("An internal-link intent cannot link a page to itself.")
    relationship_type = _relationship_type(payload.relationship_type)
    purpose = _required_text(payload.purpose, "Internal-link purpose")
    _validate_link_uniqueness(
        session,
        plan,
        source.id or 0,
        target.id or 0,
        relationship_type,
    )
    values = payload.model_dump()
    values.update(
        {
            "purpose": purpose,
            "relationship_type": relationship_type,
            "anchor_guidance": _optional_text(payload.anchor_guidance),
        }
    )
    intent = InternalLinkIntent(**values)
    session.add(intent)
    session.commit()
    session.refresh(intent)
    return InternalLinkIntentRead.model_validate(intent)


def update_internal_link_intent(
    session: Session,
    intent_id: int,
    payload: InternalLinkIntentUpdate,
) -> InternalLinkIntentRead:
    intent = _internal_link_intent(session, intent_id)
    plan = _plan(session, intent.site_plan_id)
    updates = payload.model_dump(exclude_unset=True)
    relationship_type = _relationship_type(
        updates.get("relationship_type", intent.relationship_type)
    )
    purpose = _required_text(
        updates.get("purpose", intent.purpose),
        "Internal-link purpose",
    )
    _validate_link_uniqueness(
        session,
        plan,
        intent.source_planned_page_id,
        intent.target_planned_page_id,
        relationship_type,
        intent_id=intent.id,
    )
    for key, value in updates.items():
        setattr(intent, key, value)
    intent.relationship_type = relationship_type
    intent.purpose = purpose
    if "anchor_guidance" in updates:
        intent.anchor_guidance = _optional_text(updates["anchor_guidance"])
    intent.updated_at = datetime.now(UTC)
    session.add(intent)
    session.commit()
    session.refresh(intent)
    return InternalLinkIntentRead.model_validate(intent)


def delete_internal_link_intent(session: Session, intent_id: int) -> None:
    intent = _internal_link_intent(session, intent_id)
    session.delete(intent)
    session.commit()


def evaluate_site_connection_diagnostics(
    session: Session,
    plan: SitePlan,
    *,
    sets: list[NavigationSet] | None = None,
    items: list[NavigationItem] | None = None,
    intents: list[InternalLinkIntent] | None = None,
) -> list[SiteConnectionDiagnostic]:
    sets = sets if sets is not None else _sets(session, plan)
    items = items if items is not None else _items(session, plan)
    intents = intents if intents is not None else _intents(session, plan)
    pages = list(
        session.exec(
            select(PlannedPage)
            .where(PlannedPage.site_plan_id == plan.id)
            .order_by(PlannedPage.id)
        ).all()
    )
    page_by_id = {page.id: page for page in pages if page.id is not None}
    set_by_id = {item.id: item for item in sets if item.id is not None}
    invalid_records: set[int] = set()
    deferred_pages: set[int] = set()
    for item in items:
        target = page_by_id.get(item.target_planned_page_id)
        nav_set = set_by_id.get(item.navigation_set_id)
        parent = (
            next(
                (
                    candidate
                    for candidate in items
                    if candidate.id == item.parent_navigation_item_id
                ),
                None,
            )
            if item.parent_navigation_item_id
            else None
        )
        if (
            item.website_id != plan.website_id
            or item.site_plan_id != plan.id
            or not nav_set
            or nav_set.website_id != plan.website_id
            or nav_set.site_plan_id != plan.id
            or not target
            or target.website_id != plan.website_id
            or (parent and parent.navigation_set_id != item.navigation_set_id)
        ):
            invalid_records.add(item.id or 0)
        if target and target.page_type in DEFERRED_PAGE_TYPES:
            deferred_pages.add(target.id or 0)
    for intent in intents:
        source = page_by_id.get(intent.source_planned_page_id)
        target = page_by_id.get(intent.target_planned_page_id)
        if (
            intent.website_id != plan.website_id
            or intent.site_plan_id != plan.id
            or not source
            or not target
            or source.website_id != plan.website_id
            or target.website_id != plan.website_id
        ):
            invalid_records.add(intent.id or 0)
        if source and source.page_type in DEFERRED_PAGE_TYPES:
            deferred_pages.add(source.id or 0)
        if target and target.page_type in DEFERRED_PAGE_TYPES:
            deferred_pages.add(target.id or 0)

    cycles = _navigation_cycle_ids(items)
    duplicates = _duplicate_navigation_record_ids(items) | _duplicate_link_record_ids(intents)
    self_links = {
        intent.id or 0
        for intent in intents
        if intent.source_planned_page_id == intent.target_planned_page_id
    }
    active_nav_targets = {
        item.target_planned_page_id for item in items if item.status == "active"
    }
    approved_incoming = {
        intent.target_planned_page_id
        for intent in intents
        if intent.approval_state == "approved"
    }
    supported_pages = [
        page for page in pages if page.page_type not in DEFERRED_PAGE_TYPES
    ]
    orphaned = [
        page.id or 0
        for page in supported_pages
        if page.page_type != "home"
        and page.id not in active_nav_targets
        and page.id not in approved_incoming
    ]
    conversion_broken = _broken_conversion_pages(supported_pages, intents)
    missing_sets = sorted(set(NAVIGATION_SET_TYPES) - {item.set_type for item in sets})

    return [
        _diagnostic(
            "navigation_sets",
            "Required navigation sets",
            not missing_sets,
            "Primary, utility, and footer navigation sets exist.",
            (
                "Missing navigation set(s): " + ", ".join(missing_sets)
                if missing_sets
                else ""
            ),
        ),
        _diagnostic(
            "website_scope",
            "Website and Site Plan scope",
            not invalid_records,
            "All navigation and internal-link records remain inside this Website and Site Plan.",
            "One or more connection records cross or reference an invalid ownership boundary.",
            record_ids=sorted(invalid_records),
        ),
        _diagnostic(
            "navigation_cycles",
            "Navigation hierarchy cycles",
            not cycles,
            "Navigation parent relationships are acyclic.",
            "Navigation parent relationships contain a cycle.",
            record_ids=cycles,
        ),
        _diagnostic(
            "duplicates",
            "Duplicate connection records",
            not duplicates,
            "No duplicate navigation positions, labels, targets, or internal-link edges exist.",
            "Duplicate navigation or internal-link records require correction.",
            record_ids=sorted(duplicates),
        ),
        _diagnostic(
            "self_links",
            "Self-link protection",
            not self_links,
            "No internal-link intent targets its own source page.",
            "One or more internal-link intents target their own source page.",
            record_ids=sorted(self_links),
        ),
        _diagnostic(
            "deferred_targets",
            "Deferred page targets",
            not deferred_pages,
            "No navigation or internal-link decision targets a deferred page type.",
            "County or standalone City pages remain deferred and cannot be connection targets.",
            page_ids=sorted(deferred_pages),
        ),
        _diagnostic(
            "orphaned_pages",
            "Reachable planned pages",
            not orphaned,
            "Every supported non-Home page is reachable through navigation or an approved internal link.",
            "One or more supported Planned Pages are orphaned.",
            page_ids=orphaned,
        ),
        _diagnostic(
            "conversion_paths",
            "Core visitor conversion paths",
            not conversion_broken,
            "Required Home, Service, and Contact visitor paths are connected.",
            "One or more core visitor conversion paths are broken.",
            page_ids=conversion_broken,
        ),
    ]


def _refresh_suggestions(
    session: Session,
    plan: SitePlan,
    record: SiteConnectionPlanningRecord,
) -> None:
    pages = list(
        session.exec(
            select(PlannedPage)
            .where(PlannedPage.site_plan_id == plan.id)
            .order_by(PlannedPage.id)
        ).all()
    )
    record.website_id = plan.website_id
    record.generated_navigation_suggestions = _navigation_suggestions(pages)
    record.generated_internal_link_suggestions = _link_suggestions(pages)
    record.source_snapshot = {
        "site_plan_version": plan.version,
        "planned_pages": [
            {
                "id": page.id,
                "page_type": page.page_type,
                "working_name": page.working_name,
                "intended_slug": page.intended_slug,
                "parent_planned_page_id": page.parent_planned_page_id,
                "planning_status": page.planning_status,
            }
            for page in pages
        ],
    }
    now = datetime.now(UTC)
    record.generated_at = now
    record.updated_at = now
    session.add(record)
    session.flush()


def _navigation_suggestions(pages: list[PlannedPage]) -> list[dict[str, Any]]:
    mapping = {
        "home": ("primary", 0, "Primary entry point"),
        "service": ("primary", 10, "Primary service discovery"),
        "about": ("primary", 20, "Trust and company context"),
        "contact": ("utility", 0, "Primary conversion destination"),
        "faq": ("footer", 10, "Supporting customer questions"),
        "informational": ("footer", 20, "Supporting approved information"),
        "city_service": ("footer", 100, "Legitimate local service coverage"),
    }
    counters: Counter[tuple[str, int]] = Counter()
    suggestions: list[dict[str, Any]] = []
    for page in pages:
        if page.page_type not in mapping:
            continue
        set_type, base_position, rationale = mapping[page.page_type]
        position = base_position + counters[(set_type, base_position)]
        counters[(set_type, base_position)] += 1
        suggestions.append(
            {
                "suggestion_key": f"navigation:{set_type}:{page.id}",
                "set_type": set_type,
                "target_planned_page_id": page.id,
                "suggested_label": page.working_name,
                "suggested_position": position,
                "rationale": rationale,
            }
        )
    return suggestions


def _link_suggestions(pages: list[PlannedPage]) -> list[dict[str, Any]]:
    by_type: dict[str, list[PlannedPage]] = defaultdict(list)
    for page in pages:
        if page.page_type not in DEFERRED_PAGE_TYPES:
            by_type[page.page_type].append(page)
    suggestions: list[dict[str, Any]] = []

    def add(
        source: PlannedPage,
        target: PlannedPage,
        relationship_type: str,
        purpose: str,
    ) -> None:
        suggestions.append(
            {
                "suggestion_key": (
                    f"internal-link:{source.id}:{target.id}:{relationship_type}"
                ),
                "source_planned_page_id": source.id,
                "target_planned_page_id": target.id,
                "relationship_type": relationship_type,
                "purpose": purpose,
                "suggested_anchor_guidance": target.working_name,
            }
        )

    home = by_type["home"][0] if by_type["home"] else None
    contact = by_type["contact"][0] if by_type["contact"] else None
    if home:
        for service in by_type["service"]:
            add(home, service, "conversion", "Guide visitors to an approved service.")
        if contact:
            add(home, contact, "conversion", "Provide a direct contact path.")
    if contact:
        for service in by_type["service"]:
            add(service, contact, "conversion", "Continue from service review to contact.")
        for page_type in ("about", "informational", "faq"):
            for source in by_type[page_type]:
                add(source, contact, "conversion", "Offer an approved contact next step.")
    for child in pages:
        if child.parent_planned_page_id and child.parent_planned_page_id in {
            page.id for page in pages
        }:
            parent = next(
                page for page in pages if page.id == child.parent_planned_page_id
            )
            if (
                parent.page_type not in DEFERRED_PAGE_TYPES
                and child.page_type not in DEFERRED_PAGE_TYPES
            ):
                add(parent, child, "hierarchy", "Connect the parent page to its child.")
                add(child, parent, "hierarchy", "Return from the child page to its parent.")
    return suggestions


def _broken_conversion_pages(
    pages: list[PlannedPage],
    intents: list[InternalLinkIntent],
) -> list[int]:
    approved_edges: dict[int, set[int]] = defaultdict(set)
    for intent in intents:
        if intent.approval_state == "approved":
            approved_edges[intent.source_planned_page_id].add(
                intent.target_planned_page_id
            )
    homes = [page for page in pages if page.page_type == "home"]
    services = [page for page in pages if page.page_type == "service"]
    contacts = [page for page in pages if page.page_type == "contact"]
    broken: set[int] = set()
    if homes and services:
        for home in homes:
            if not _reaches_any(home.id or 0, {page.id or 0 for page in services}, approved_edges):
                broken.add(home.id or 0)
    if homes and contacts:
        for home in homes:
            if not _reaches_any(home.id or 0, {page.id or 0 for page in contacts}, approved_edges):
                broken.add(home.id or 0)
    if services and contacts:
        contact_ids = {page.id or 0 for page in contacts}
        for service in services:
            if not _reaches_any(service.id or 0, contact_ids, approved_edges):
                broken.add(service.id or 0)
    return sorted(broken)


def _reaches_any(
    start: int,
    targets: set[int],
    edges: dict[int, set[int]],
) -> bool:
    queue: deque[int] = deque([start])
    seen: set[int] = set()
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        if current != start and current in targets:
            return True
        queue.extend(edges.get(current, set()) - seen)
    return False


def _duplicate_navigation_record_ids(items: list[NavigationItem]) -> set[int]:
    groups: dict[tuple[Any, ...], list[NavigationItem]] = defaultdict(list)
    for item in items:
        groups[("target", item.navigation_set_id, item.target_planned_page_id)].append(item)
        groups[
            (
                "position",
                item.navigation_set_id,
                item.parent_navigation_item_id,
                item.position,
            )
        ].append(item)
        groups[
            (
                "label",
                item.navigation_set_id,
                item.parent_navigation_item_id,
                item.label.strip().casefold(),
            )
        ].append(item)
    return {
        item.id or 0
        for group in groups.values()
        if len(group) > 1
        for item in group
    }


def _duplicate_link_record_ids(intents: list[InternalLinkIntent]) -> set[int]:
    groups: dict[tuple[Any, ...], list[InternalLinkIntent]] = defaultdict(list)
    for intent in intents:
        groups[
            (
                intent.source_planned_page_id,
                intent.target_planned_page_id,
                intent.relationship_type,
            )
        ].append(intent)
    return {
        item.id or 0
        for group in groups.values()
        if len(group) > 1
        for item in group
    }


def _navigation_cycle_ids(items: list[NavigationItem]) -> list[int]:
    parent_by_id = {
        item.id: item.parent_navigation_item_id
        for item in items
        if item.id is not None
    }
    affected: set[int] = set()
    for start in parent_by_id:
        trail: list[int] = []
        current: int | None = start
        while current is not None and current in parent_by_id:
            if current in trail:
                affected.update(trail[trail.index(current) :])
                break
            trail.append(current)
            current = parent_by_id[current]
    return sorted(affected)


def _validate_navigation_uniqueness(
    session: Session,
    nav_set: NavigationSet,
    target_id: int,
    parent_id: int | None,
    label: str,
    position: int,
    *,
    item_id: int | None = None,
) -> None:
    items = list(
        session.exec(
            select(NavigationItem).where(
                NavigationItem.navigation_set_id == nav_set.id
            )
        ).all()
    )
    for item in items:
        if item.id == item_id:
            continue
        if item.target_planned_page_id == target_id:
            raise SiteConnectionError(
                "The target Planned Page already appears in this Navigation Set."
            )
        if (
            item.parent_navigation_item_id == parent_id
            and item.position == position
        ):
            raise SiteConnectionError(
                "Sibling Navigation Items cannot share the same position."
            )
        if (
            item.parent_navigation_item_id == parent_id
            and item.label.strip().casefold() == label.casefold()
        ):
            raise SiteConnectionError(
                "Sibling Navigation Items cannot share the same label."
            )


def _validate_link_uniqueness(
    session: Session,
    plan: SitePlan,
    source_id: int,
    target_id: int,
    relationship_type: str,
    *,
    intent_id: int | None = None,
) -> None:
    statement = select(InternalLinkIntent).where(
        InternalLinkIntent.site_plan_id == plan.id,
        InternalLinkIntent.source_planned_page_id == source_id,
        InternalLinkIntent.target_planned_page_id == target_id,
        InternalLinkIntent.relationship_type == relationship_type,
    )
    if intent_id is not None:
        statement = statement.where(InternalLinkIntent.id != intent_id)
    if session.exec(statement).first():
        raise SiteConnectionError(
            "This internal-link source, target, and relationship type already exists."
        )


def _navigation_parent(
    session: Session,
    plan: SitePlan,
    nav_set: NavigationSet,
    parent_id: int | None,
) -> NavigationItem | None:
    if parent_id is None:
        return None
    parent = session.get(NavigationItem, parent_id)
    if (
        not parent
        or parent.site_plan_id != plan.id
        or parent.website_id != plan.website_id
        or parent.navigation_set_id != nav_set.id
    ):
        raise SiteConnectionError(
            "Parent Navigation Item must belong to the same Website, Site Plan, and Navigation Set."
        )
    return parent


def _eligible_page(
    session: Session,
    plan: SitePlan,
    page_id: int,
    role: str,
) -> PlannedPage:
    page = session.get(PlannedPage, page_id)
    if (
        not page
        or page.site_plan_id != plan.id
        or page.website_id != plan.website_id
    ):
        raise SiteConnectionError(
            f"Internal {role} Planned Page does not belong to the selected Website and Site Plan."
        )
    if page.page_type in DEFERRED_PAGE_TYPES:
        raise SiteConnectionError(
            f"{page.page_type.replace('_', ' ').title()} pages remain deferred "
            "and cannot participate in connection decisions."
        )
    return page


def _relationship_type(value: str) -> str:
    normalized = "_".join(value.strip().lower().replace("-", "_").split())
    if normalized not in INTERNAL_LINK_RELATIONSHIP_TYPES:
        raise SiteConnectionError(
            "Unsupported internal-link relationship type. "
            f"Use one of: {', '.join(sorted(INTERNAL_LINK_RELATIONSHIP_TYPES))}."
        )
    return normalized


def _required_text(value: str, label: str) -> str:
    normalized = " ".join((value or "").split())
    if not normalized:
        raise SiteConnectionError(f"{label} is required.")
    return normalized


def _optional_text(value: str | None) -> str | None:
    normalized = " ".join((value or "").split())
    return normalized or None


def _diagnostic(
    key: str,
    label: str,
    passed: bool,
    pass_message: str,
    fail_message: str,
    *,
    page_ids: list[int] | None = None,
    record_ids: list[int] | None = None,
) -> SiteConnectionDiagnostic:
    return SiteConnectionDiagnostic(
        key=key,
        label=label,
        status="ready" if passed else "needs_attention",
        message=pass_message if passed else fail_message,
        affected_planned_page_ids=page_ids or [],
        affected_record_ids=record_ids or [],
    )


def _require_website(plan: SitePlan, website_id: int) -> None:
    if plan.website_id != website_id:
        raise SiteConnectionError(
            "Site Plan does not belong to the selected Website."
        )


def _plan(session: Session, plan_id: int) -> SitePlan:
    plan = session.get(SitePlan, plan_id)
    if not plan:
        raise SiteConnectionError("Site Plan not found.")
    return plan


def _sets(session: Session, plan: SitePlan) -> list[NavigationSet]:
    records = list(
        session.exec(
            select(NavigationSet)
            .where(NavigationSet.site_plan_id == plan.id)
            .order_by(NavigationSet.id)
        ).all()
    )
    order = {set_type: position for position, set_type in enumerate(NAVIGATION_SET_TYPES)}
    return sorted(
        records,
        key=lambda item: (order.get(item.set_type, len(order)), item.id or 0),
    )


def _items(session: Session, plan: SitePlan) -> list[NavigationItem]:
    return list(
        session.exec(
            select(NavigationItem)
            .where(NavigationItem.site_plan_id == plan.id)
            .order_by(
                NavigationItem.navigation_set_id,
                NavigationItem.parent_navigation_item_id,
                NavigationItem.position,
                NavigationItem.id,
            )
        ).all()
    )


def _intents(session: Session, plan: SitePlan) -> list[InternalLinkIntent]:
    return list(
        session.exec(
            select(InternalLinkIntent)
            .where(InternalLinkIntent.site_plan_id == plan.id)
            .order_by(
                InternalLinkIntent.source_planned_page_id,
                InternalLinkIntent.target_planned_page_id,
                InternalLinkIntent.id,
            )
        ).all()
    )


def _navigation_item(session: Session, item_id: int) -> NavigationItem:
    item = session.get(NavigationItem, item_id)
    if not item:
        raise SiteConnectionError("Navigation Item not found.")
    return item


def _internal_link_intent(
    session: Session,
    intent_id: int,
) -> InternalLinkIntent:
    intent = session.get(InternalLinkIntent, intent_id)
    if not intent:
        raise SiteConnectionError("Internal-link intent not found.")
    return intent
