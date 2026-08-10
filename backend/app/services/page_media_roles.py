from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, cast

from sqlmodel import Session

from app.models import PageImageAssignment, PlannedPage, PlannedPageMediaRequirement


SemanticMediaRole = Literal["hero", "service", "support"]
SEMANTIC_MEDIA_ROLES = frozenset({"hero", "service", "support"})

# Closed semantic projection of the current PAGE_TYPE_MEDIA_CONTRACTS registry.
# The full tuple is deliberate: neither a placement-name substring nor a fabricated
# component/target pair may acquire hero semantics. A focused parity test keeps this
# lookup synchronized with the source-controlled planning contract registry.
SEMANTIC_MEDIA_ROLE_CONTRACTS: dict[
    tuple[str, str, int, str, str],
    SemanticMediaRole,
] = {
    ("home", "home-hero", 2, "hero", "hero"): "hero",
    ("home", "home-trust", 2, "trust_license", "trust_license"): "support",
    (
        "home",
        "home-service-overview",
        2,
        "related_page_links",
        "related_page_links",
    ): "support",
    ("about", "about-company", 2, "hero", "hero"): "hero",
    ("about", "about-trust", 2, "trust_license", "trust_license"): "support",
    (
        "about",
        "about-credibility",
        2,
        "content_section",
        "content_section:experience",
    ): "support",
    (
        "contact",
        "contact-context",
        2,
        "contact_pathways",
        "contact_pathways",
    ): "support",
    (
        "contact",
        "contact-service-area",
        2,
        "content_section",
        "content_section:service_area",
    ): "support",
    (
        "contact",
        "contact-estimate-support",
        2,
        "content_section",
        "content_section:ways_to_contact",
    ): "support",
    ("faq", "faq-guidance", 2, "faq", "faq"): "support",
    ("faq", "faq-preparation", 2, "hero", "hero"): "hero",
    (
        "faq",
        "faq-coordination",
        2,
        "content_section",
        "content_section:contact",
    ): "support",
    ("service", "service-hero", 2, "hero", "hero"): "hero",
    (
        "service",
        "service-process",
        2,
        "service_summary",
        "service_summary:service_overview",
    ): "service",
    (
        "service",
        "service-guidance",
        2,
        "content_section",
        "content_section:approved_guidance",
    ): "support",
    (
        "service_county",
        "service-county-hero",
        2,
        "hero",
        "hero",
    ): "hero",
    (
        "service_county",
        "service-county-property",
        2,
        "content_section",
        "content_section:cities_served",
    ): "support",
    (
        "service_county",
        "service-county-guidance",
        2,
        "service_summary",
        "service_summary:service_county_intro",
    ): "service",
    (
        "city_service",
        "city-service-hero",
        2,
        "hero",
        "hero",
    ): "hero",
    (
        "city_service",
        "city-service-process",
        2,
        "service_summary",
        "service_summary:why_it_matters",
    ): "service",
    (
        "city_service",
        "city-service-evidence",
        2,
        "content_section",
        "content_section:signs_section",
    ): "support",
    (
        "informational",
        "informational-hero",
        2,
        "hero",
        "hero",
    ): "hero",
    (
        "informational",
        "informational-support",
        2,
        "content_section",
        "content_section:approved_information",
    ): "support",
}

# Historical V1 requirements predate exact component-instance targets. They are
# readable only through an explicit audit path; active rendering/readiness/export
# must continue to require the current V2 contract above.
HISTORICAL_SEMANTIC_MEDIA_ROLE_CONTRACTS: dict[
    tuple[str, str, int, str, str],
    SemanticMediaRole,
] = {
    (page_type, placement_key, 1, component_key, ""): semantic_role
    for (
        page_type,
        placement_key,
        _contract_version,
        component_key,
        _instance_key,
    ), semantic_role in SEMANTIC_MEDIA_ROLE_CONTRACTS.items()
}

_GOVERNED_ASSIGNMENT_FIELDS = (
    "website_id",
    "site_plan_id",
    "planned_page_id",
    "media_requirement_id",
    "assignment_version",
    "media_version",
    "placement_contract_version",
)


class SemanticMediaRoleError(ValueError):
    """The persisted assignment cannot resolve to one exact semantic media role."""


def resolve_semantic_media_role(
    assignment: PageImageAssignment | Mapping[str, Any],
    *,
    session: Session | None = None,
    requirement: PlannedPageMediaRequirement | Mapping[str, Any] | None = None,
    planned_page: PlannedPage | Mapping[str, Any] | None = None,
    allow_historical: bool = False,
) -> SemanticMediaRole:
    """Resolve the public media role without interpreting a governed storage token.

    Legacy assignments have no governed binding, so their literal role remains the
    authoritative semantic role. Governed assignments instead derive their role from
    the exact requirement/component-instance binding. Their persisted ``image_role``
    is deliberately an opaque, versioned uniqueness token and must never be used as a
    semantic-role fallback.
    """

    requirement_id = _value(assignment, "media_requirement_id")
    governed_values = [_value(assignment, field) for field in _GOVERNED_ASSIGNMENT_FIELDS]
    if requirement_id is None:
        if any(value is not None for value in governed_values):
            raise SemanticMediaRoleError(
                "Page media assignment has partial governed binding provenance."
            )
        stored_role = _normalized(_value(assignment, "image_role"))
        if stored_role not in SEMANTIC_MEDIA_ROLES:
            raise SemanticMediaRoleError(
                "Legacy page media assignment has an unsupported semantic role."
            )
        return cast(SemanticMediaRole, stored_role)

    if not all(value is not None for value in governed_values):
        raise SemanticMediaRoleError(
            "Governed page media assignment has incomplete binding provenance."
        )
    if requirement is None and session is not None:
        requirement = session.get(PlannedPageMediaRequirement, requirement_id)
    planned_page_id = _value(assignment, "planned_page_id")
    if planned_page is None and session is not None:
        planned_page = session.get(PlannedPage, planned_page_id)
    if requirement is None or planned_page is None:
        raise SemanticMediaRoleError(
            "Governed page media role cannot resolve its requirement and Planned Page."
        )

    assignment_scope = (
        _value(assignment, "website_id"),
        _value(assignment, "site_plan_id"),
        planned_page_id,
        requirement_id,
    )
    requirement_scope = (
        _value(requirement, "website_id"),
        _value(requirement, "site_plan_id"),
        _value(requirement, "planned_page_id"),
        _value(requirement, "id"),
    )
    page_scope = (
        _value(planned_page, "website_id"),
        _value(planned_page, "site_plan_id"),
        _value(planned_page, "id"),
        _value(planned_page, "generated_page_id"),
    )
    if assignment_scope != requirement_scope or assignment_scope[:3] != page_scope[:3]:
        raise SemanticMediaRoleError(
            "Governed page media role crosses its Website, Site Plan, Planned Page, or requirement binding."
        )
    if _value(assignment, "generated_page_id") != page_scope[3]:
        raise SemanticMediaRoleError(
            "Governed page media role targets the wrong Generated Page."
        )
    contract_version = _value(requirement, "contract_version")
    if (
        not isinstance(contract_version, int)
        or contract_version < 1
        or _value(assignment, "placement_contract_version") != contract_version
    ):
        raise SemanticMediaRoleError(
            "Governed page media role loses its exact placement-contract version."
        )

    semantic_role = resolve_requirement_semantic_media_role(
        requirement,
        planned_page,
        allow_historical=allow_historical,
    )

    # Hero is intentionally narrow: filenames, rationale text, placement-name
    # substrings, and first-image ordering are never semantic evidence. In
    # particular, city-service-hero resolves only through its complete registry
    # identity; city-service-evidence is independently fixed to support media.
    return semantic_role


def resolve_requirement_semantic_media_role(
    requirement: PlannedPageMediaRequirement | Mapping[str, Any],
    planned_page: PlannedPage | Mapping[str, Any],
    *,
    allow_historical: bool = False,
) -> SemanticMediaRole:
    """Resolve one candidate/readiness role from the exact requirement contract."""

    lifecycle_status = _normalized(_value(requirement, "lifecycle_status"))
    requirement_state = _normalized(_value(requirement, "requirement_state"))
    allowed_lifecycle = {"active", "superseded"} if allow_historical else {"active"}
    if (
        lifecycle_status not in allowed_lifecycle
        or requirement_state not in {"required", "advisory"}
    ):
        raise SemanticMediaRoleError(
            "Governed page media role requires an active required or advisory placement."
        )
    if (
        _value(requirement, "website_id") != _value(planned_page, "website_id")
        or _value(requirement, "site_plan_id")
        != _value(planned_page, "site_plan_id")
        or _value(requirement, "planned_page_id") != _value(planned_page, "id")
    ):
        raise SemanticMediaRoleError(
            "Governed page media role crosses its Planned Page contract scope."
        )
    contract_version = _value(requirement, "contract_version")
    if not isinstance(contract_version, int) or contract_version < 1:
        raise SemanticMediaRoleError(
            "Governed page media role has an invalid placement-contract version."
        )
    contract_identity = (
        _contract_page_type(planned_page),
        _normalized(_value(requirement, "placement_key")),
        contract_version,
        _normalized(_value(requirement, "component_or_section")),
        _normalized(_value(requirement, "target_component_instance_key")),
    )
    registry = (
        {
            **SEMANTIC_MEDIA_ROLE_CONTRACTS,
            **HISTORICAL_SEMANTIC_MEDIA_ROLE_CONTRACTS,
        }
        if allow_historical
        else SEMANTIC_MEDIA_ROLE_CONTRACTS
    )
    semantic_role = registry.get(contract_identity)
    if semantic_role is None:
        raise SemanticMediaRoleError(
            "Governed page media role does not match an exact current Page Media contract."
        )
    return semantic_role


def _value(record: object | Mapping[str, Any], field: str) -> Any:
    if isinstance(record, Mapping):
        return record.get(field)
    return getattr(record, field, None)


def _normalized(value: Any) -> str:
    return str(value).strip().lower() if value is not None else ""


def _contract_page_type(planned_page: object | Mapping[str, Any]) -> str:
    page_type = _normalized(_value(planned_page, "page_type"))
    if page_type == "county" and _value(planned_page, "service_id") is not None:
        return "service_county"
    return page_type
