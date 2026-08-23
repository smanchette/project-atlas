from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any, Literal, Mapping, Sequence
import unicodedata


PUBLIC_COPY_RULESET_KEY = "project-atlas-public-copy-ruleset"
PUBLIC_COPY_RULESET_VERSION = "1.0.0"
PUBLIC_COPY_RULESET_IDENTITY = (
    "project-atlas-public-copy-ruleset/source-only/1.0.0"
)
PUBLIC_COPY_RULESET_CANONICAL_PAYLOAD_SHA256 = (
    "3019e45fb33a31c4c023d110375232ea7bc44eb93eb9f2fbab7f8029847e70ae"
)

PUBLIC_COPY_AUDIT_ALGORITHM_KEY = "project-atlas-public-copy-audit"
PUBLIC_COPY_AUDIT_ALGORITHM_VERSION = "1.0.2"
PUBLIC_COPY_NORMALIZATION_IDENTITY = (
    "unicode-nfkc+casefold+smart-punctuation+dash-underscore-equivalence+"
    "collapse-whitespace+trim@1"
)

Severity = Literal["BLOCKER", "WARNING", "INFORMATIONAL"]
SafeCorrectionStatus = Literal[
    "source_repair_required",
    "expert_review_required",
    "no_automatic_change",
]


_SMART_PUNCTUATION_TRANSLATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u2032": "'",
        "\u2035": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u2033": '"',
        "\u2036": '"',
        "\u00a0": " ",
        "\u1680": " ",
        "\u2000": " ",
        "\u2001": " ",
        "\u2002": " ",
        "\u2003": " ",
        "\u2004": " ",
        "\u2005": " ",
        "\u2006": " ",
        "\u2007": " ",
        "\u2008": " ",
        "\u2009": " ",
        "\u200a": " ",
        "\u202f": " ",
        "\u205f": " ",
        "\u3000": " ",
    }
)
_DASH_OR_UNDERSCORE_PATTERN = re.compile(
    r"[_\-\u058a\u05be\u1400\u1806\u2010-\u2015\u2e17\u2e1a\u2e3a-\u2e3b"
    r"\u2e40\u301c\u3030\u30a0\ufe31-\ufe32\ufe58\ufe63\uff0d\u2212]+"
)
_WHITESPACE_PATTERN = re.compile(r"\s+")
_RAW_URL_PATTERN = re.compile(r"(?i)(?:https?://|www\.)\S+")
_TECHNICAL_CONTEXT_PATTERN = re.compile(
    r"(?i)\b(?:vikane|sulfuryl fluoride|fumigant|fumigation|tenting|aeration|"
    r"clearance|re-entry|reentry|drywood termite|preparation instruction)\b"
)
_STRONG_TECHNICAL_CONTEXT_PATTERN = re.compile(
    r"(?i)\b(?:vikane|sulfuryl fluoride|fumigant|fumigation|aeration|clearance|"
    r"re-entry|reentry)\b"
)
_TECHNICAL_CLAIM_PATTERN = re.compile(
    r"(?i)(?:\b(?:always|never|proven|most complete|completely|eliminates?|"
    r"guarantees?|safe for|fee)\b|\b\d+(?:\s*(?:-|to)\s*\d+)?\s*"
    r"(?:hours?|days?)\b|\b100\s*%)"
)
_SENTENCE_PATTERN = re.compile(r"[^.!?]+[.!?]")


_INTERNAL_PHRASES = (
    "approved service",
    "approved destination",
    "approved city-service destination",
    "approved service-county owner",
    "exact service-county owner",
    "connect the page",
    "connect the service-county page",
    "connect the city-service page",
    "guide visitors",
    "provide a useful path",
    "conversion path",
    "return from the page",
    "review answers drawn from approved business knowledge",
    "target counties",
    "public-facing brand",
    "explain the business identity",
    "source-bound",
    "operator-only",
    "governed route",
    "governed destination",
    "generated page",
    "planned page",
    "site plan",
    "page composition",
    "component instance",
    "source component",
    "page-type layout",
    "layout contract",
    "route ownership",
    "exact owner",
    "placeholder",
    "demo media",
    "review mode",
    "draft preview",
    "internal conversion path",
    "template logic",
    "generation instructions",
    "seo instructions",
    "review instructions",
    "approved service area",
    "approved contact method",
    "approved channel",
    "approved questions",
    "service overview to approved",
    "public service wording",
    "separately reviewed and approved for use",
    "atlas",
)

_INTERNAL_CONTEXT_PATTERNS = (
    r"\b(?:guide\s+visitors?|provide\s+(?:a\s+)?(?:useful\s+)?"
    r"(?:conversion\s+)?path|return\s+from\s+(?:the\s+)?(?:home|about|"
    r"contact|faq|service|city service|service county|page)|connect\s+"
    r"(?:the\s+)?(?:home|about|contact|faq|service|city service|service county|"
    r"page)\b.{0,80}\b(?:page|destination|owner|path|route|overview)\b)",
    r"\b(?:home|about|contact|faq|service|city service|service county)\s+to\s+"
    r"(?:home|contact|service|county|city service)\b",
    r"\b(?:composition|component|renderer|diagnostic)\b",
)

_PLACEHOLDER_PATTERNS = (
    r"\b(?:placeholder|lorem ipsum|demo media|sample copy|todo|tbd)\b",
    r"[\[{]\s*(?:city|county|state|service|brand|business|phone|email)\s*[\]}]",
    r"\b(?:insert|replace|enter)\s+(?:copy|text|content)\s+here\b",
)

_UNSUPPORTED_CLAIM_PATTERNS = (
    r"\b(?:best|number one|top rated|fastest|cheapest)\b",
    r"\b(?:guaranteed|permanent solution|complete protection|same day|"
    r"instant quote|free quote)\b",
    r"\b(?:award winning|five star|5 star|open 24 7|24 hours a day)\b",
    r"\b(?:customer reviews?|customer ratings?|years in business|success rate|"
    r"limited time discount|limited time special)\b",
    r"\b(?:100 percent|100\s*%)\s+(?:effective|safe|successful)\b",
)

_MALFORMED_PATTERNS = (
    r"\bprepa\.$",
    r"(?:^|\s)[.?!](?:\s|$)",
)

_PUBLIC_METADATA_KEYS = (
    "title",
    "page_title",
    "meta_title",
    "meta_description",
    "h1",
    "open_graph_title",
    "open_graph_description",
    "og_title",
    "og_description",
    "canonical_url",
    "navigation_label",
    "navigation_description",
    "description",
)
_DRAFT_TEXT_KEYS = (
    "title",
    "meta_title",
    "meta_description",
    "h1",
    "intro",
    "why_it_matters",
    "signs_section",
    "process_section",
    "prep_section",
    "realtor_property_manager_section",
    "service_explanation",
    "local_city_section",
    "why_choose_section",
    "call_to_action",
)
_IDENTITY_COMPONENT_KEYS = {
    "website_header",
    "website_footer",
    "trust_license",
    "contact_pathways",
}
_NAVIGATION_COMPONENT_KEYS = {
    "primary_navigation",
    "utility_navigation",
    "footer_navigation",
}
_NAVIGATION_IDENTITY_ALLOWANCE_PATH_PATTERN = re.compile(
    r"^composition\.effective_components\[[0-9]+\]\.resolved_data\.items"
    r"\[[0-9]+\]\.label$"
)
_KNOWN_COMPONENT_KEYS = {
    *_IDENTITY_COMPONENT_KEYS,
    *_NAVIGATION_COMPONENT_KEYS,
    "hero",
    "content_section",
    "service_summary",
    "media_placement",
    "related_page_links",
    "destination_cards",
    "faq",
    "final_cta",
}
_STRUCTURED_EXCLUDED_KEYS = {
    "diagnostics",
    "internal_notes",
    "operator_decisions",
    "planning_record",
    "planning_record_id",
    "source_snapshot",
    "input_bindings",
    "readiness",
    "warnings",
}
_FORM_TEXT_KEYS = {
    "title",
    "heading",
    "description",
    "label",
    "cta_label",
    "submit_label",
    "helper",
    "helper_text",
    "help_text",
    "notice",
    "preview_notice",
    "provider_disabled_notice",
    "safety_notice",
    "placeholder",
    "error_message",
    "empty_message",
}
_FORM_CONTAINER_KEYS = {"fields", "options", "choices", "items"}
_EXACT_PROVIDER_DISABLED_NOTICE = (
    "Draft preview only. This form does not submit or store data."
)
_NORMALIZED_PROVIDER_DISABLED_NOTICE = ""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def normalize_public_copy(value: str) -> str:
    """Normalize copy for detection and identity without changing the source value."""

    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.translate(_SMART_PUNCTUATION_TRANSLATION)
    normalized = _DASH_OR_UNDERSCORE_PATTERN.sub(" ", normalized)
    normalized = _WHITESPACE_PATTERN.sub(" ", normalized.casefold())
    return normalized.strip()


_NORMALIZED_PROVIDER_DISABLED_NOTICE = normalize_public_copy(
    _EXACT_PROVIDER_DISABLED_NOTICE
)


def normalized_public_copy_fingerprint(value: str) -> str:
    return hashlib.sha256(normalize_public_copy(value).encode("utf-8")).hexdigest()


def _algorithm_payload() -> dict[str, Any]:
    return {
        "algorithm_key": PUBLIC_COPY_AUDIT_ALGORITHM_KEY,
        "algorithm_version": PUBLIC_COPY_AUDIT_ALGORITHM_VERSION,
        "normalization": PUBLIC_COPY_NORMALIZATION_IDENTITY,
        "ruleset": {
            "key": PUBLIC_COPY_RULESET_KEY,
            "version": PUBLIC_COPY_RULESET_VERSION,
            "identity": PUBLIC_COPY_RULESET_IDENTITY,
            "canonical_payload_sha256": PUBLIC_COPY_RULESET_CANONICAL_PAYLOAD_SHA256,
        },
        "projection_schema": "project-atlas-public-copy-projection@1",
        "identity_scope_policy": (
            "page-and-destination-default+exact-governed-navigation-path-target@2"
        ),
        "internal_phrases": list(_INTERNAL_PHRASES),
        "internal_context_patterns": list(_INTERNAL_CONTEXT_PATTERNS),
        "placeholder_patterns": list(_PLACEHOLDER_PATTERNS),
        "unsupported_claim_patterns": list(_UNSUPPORTED_CLAIM_PATTERNS),
        "malformed_patterns": list(_MALFORMED_PATTERNS),
        "technical_context_pattern": _TECHNICAL_CONTEXT_PATTERN.pattern,
        "strong_technical_context_pattern": _STRONG_TECHNICAL_CONTEXT_PATTERN.pattern,
        "technical_claim_pattern": _TECHNICAL_CLAIM_PATTERN.pattern,
        "provider_disabled_notice": _EXACT_PROVIDER_DISABLED_NOTICE,
    }


PUBLIC_COPY_AUDIT_ALGORITHM_SHA256 = _canonical_hash(_algorithm_payload())


@dataclass(frozen=True)
class PublicCopyAuditInput:
    website_id: int
    generated_page_id: int
    page_type: str
    planned_page_id: int | None = None
    public_metadata: Mapping[str, Any] = field(default_factory=dict)
    draft_content: Mapping[str, Any] = field(default_factory=dict)
    composition: Any = None
    export_payload: Any = None
    structured_data: Any = None
    form_helper_copy: Any = None
    alt_text: Any = None
    source_owner_by_path: Mapping[str, str] = field(default_factory=dict)
    site_identity_terms: Sequence[str] = field(default_factory=tuple)
    allowed_identity_terms: Sequence[str] = field(default_factory=tuple)
    allowed_navigation_identity_terms_by_path: Mapping[
        str, Sequence[str]
    ] = field(
        default_factory=dict
    )
    ruleset_key: str = PUBLIC_COPY_RULESET_KEY
    ruleset_version: str = PUBLIC_COPY_RULESET_VERSION
    ruleset_identity: str = PUBLIC_COPY_RULESET_IDENTITY
    ruleset_canonical_payload_sha256: str = (
        PUBLIC_COPY_RULESET_CANONICAL_PAYLOAD_SHA256
    )


@dataclass(frozen=True)
class ProjectedPublicCopy:
    surface: str
    field_path: str
    exact_text: str
    context: str
    source_owner: str

    @property
    def normalized_text(self) -> str:
        return normalize_public_copy(self.exact_text)

    @property
    def normalized_fingerprint(self) -> str:
        return normalized_public_copy_fingerprint(self.exact_text)

    def as_dict(self) -> dict[str, str]:
        return {
            "surface": self.surface,
            "field_path": self.field_path,
            "exact_text": self.exact_text,
            "normalized_text": self.normalized_text,
            "normalized_fingerprint": self.normalized_fingerprint,
            "context": self.context,
            "source_owner": self.source_owner,
        }


@dataclass(frozen=True)
class PublicCopyFinding:
    ruleset_key: str
    ruleset_version: str
    ruleset_identity: str
    ruleset_canonical_payload_sha256: str
    audit_algorithm_key: str
    audit_algorithm_version: str
    audit_algorithm_sha256: str
    website_id: int
    planned_page_id: int | None
    generated_page_id: int
    page_type: str
    field_path: str
    exact_text: str
    normalized_text: str
    normalized_fingerprint: str
    source_owner: str
    rule_id: str
    category: str
    severity: Severity
    message: str
    safe_correction_status: SafeCorrectionStatus
    fingerprint: str

    def as_dict(self) -> dict[str, Any]:
        return {
            key: getattr(self, key)
            for key in self.__dataclass_fields__
        }


@dataclass(frozen=True)
class PublicCopyAuditResult:
    ruleset_key: str
    ruleset_version: str
    ruleset_identity: str
    ruleset_canonical_payload_sha256: str
    audit_algorithm_key: str
    audit_algorithm_version: str
    audit_algorithm_sha256: str
    website_id: int
    planned_page_id: int | None
    generated_page_id: int
    page_type: str
    projected_text_count: int
    blocker_count: int
    warning_count: int
    informational_count: int
    public_copy_clean: bool
    identity_scope_authorization_sha256: str
    findings: tuple[PublicCopyFinding, ...]
    fingerprint: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "ruleset_key": self.ruleset_key,
            "ruleset_version": self.ruleset_version,
            "ruleset_identity": self.ruleset_identity,
            "ruleset_canonical_payload_sha256": (
                self.ruleset_canonical_payload_sha256
            ),
            "audit_algorithm_key": self.audit_algorithm_key,
            "audit_algorithm_version": self.audit_algorithm_version,
            "audit_algorithm_sha256": self.audit_algorithm_sha256,
            "website_id": self.website_id,
            "planned_page_id": self.planned_page_id,
            "generated_page_id": self.generated_page_id,
            "page_type": self.page_type,
            "projected_text_count": self.projected_text_count,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "informational_count": self.informational_count,
            "public_copy_clean": self.public_copy_clean,
            "identity_scope_authorization_sha256": (
                self.identity_scope_authorization_sha256
            ),
            "findings": [item.as_dict() for item in self.findings],
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True)
class PublicCopyAuditBatchResult:
    ruleset_key: str
    ruleset_version: str
    ruleset_identity: str
    ruleset_canonical_payload_sha256: str
    audit_algorithm_key: str
    audit_algorithm_version: str
    audit_algorithm_sha256: str
    evaluated_page_count: int
    public_copy_clean_count: int
    public_copy_blocked_count: int
    warning_page_count: int
    blocker_finding_count: int
    warning_finding_count: int
    informational_finding_count: int
    identity_scope_authorization_sha256: str
    results: tuple[PublicCopyAuditResult, ...]
    fingerprint: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "ruleset_key": self.ruleset_key,
            "ruleset_version": self.ruleset_version,
            "ruleset_identity": self.ruleset_identity,
            "ruleset_canonical_payload_sha256": (
                self.ruleset_canonical_payload_sha256
            ),
            "audit_algorithm_key": self.audit_algorithm_key,
            "audit_algorithm_version": self.audit_algorithm_version,
            "audit_algorithm_sha256": self.audit_algorithm_sha256,
            "evaluated_page_count": self.evaluated_page_count,
            "public_copy_clean_count": self.public_copy_clean_count,
            "public_copy_blocked_count": self.public_copy_blocked_count,
            "warning_page_count": self.warning_page_count,
            "blocker_finding_count": self.blocker_finding_count,
            "warning_finding_count": self.warning_finding_count,
            "informational_finding_count": self.informational_finding_count,
            "identity_scope_authorization_sha256": (
                self.identity_scope_authorization_sha256
            ),
            "results": [item.as_dict() for item in self.results],
            "fingerprint": self.fingerprint,
        }


def public_copy_audit_identity() -> dict[str, str]:
    return {
        "ruleset_key": PUBLIC_COPY_RULESET_KEY,
        "ruleset_version": PUBLIC_COPY_RULESET_VERSION,
        "ruleset_identity": PUBLIC_COPY_RULESET_IDENTITY,
        "ruleset_canonical_payload_sha256": (
            PUBLIC_COPY_RULESET_CANONICAL_PAYLOAD_SHA256
        ),
        "audit_algorithm_key": PUBLIC_COPY_AUDIT_ALGORITHM_KEY,
        "audit_algorithm_version": PUBLIC_COPY_AUDIT_ALGORITHM_VERSION,
        "audit_algorithm_sha256": PUBLIC_COPY_AUDIT_ALGORITHM_SHA256,
        "normalization_identity": PUBLIC_COPY_NORMALIZATION_IDENTITY,
    }


def project_public_copy(value: PublicCopyAuditInput) -> tuple[ProjectedPublicCopy, ...]:
    """Project only source fields that can enter a public page or public payload."""

    _validate_ruleset_binding(value)
    result: list[ProjectedPublicCopy] = []

    def add(
        surface: str,
        path: str,
        raw: Any,
        context: str,
        *,
        include_empty: bool = False,
    ) -> None:
        if not isinstance(raw, str):
            return
        if not raw and not include_empty:
            return
        result.append(
            ProjectedPublicCopy(
                surface=surface,
                field_path=path,
                exact_text=raw,
                context=context,
                source_owner=_source_owner(value, path, surface),
            )
        )

    _project_metadata(value.public_metadata, add)
    _project_draft(value.draft_content, add)
    _project_composition(value.composition, add)
    _project_export(value.export_payload, add)
    _project_structured(value.structured_data, "structured_data", add)
    _project_form(value.form_helper_copy, add)
    _project_alt_text(value.alt_text, add)
    projected = tuple(
        sorted(result, key=lambda item: (item.field_path, item.exact_text))
    )
    _validate_navigation_identity_allowances(value, projected)
    return projected


def audit_public_copy(value: PublicCopyAuditInput) -> PublicCopyAuditResult:
    projected = project_public_copy(value)
    identity_scope_authorization_sha256 = (
        _identity_scope_authorization_sha256(value)
    )
    findings: list[PublicCopyFinding] = []
    for item in projected:
        findings.extend(_audit_projected_text(value, item))
    findings.extend(_duplicate_findings(value, projected))
    findings = _deduplicated_sorted_findings(findings)
    blocker_count = sum(item.severity == "BLOCKER" for item in findings)
    warning_count = sum(item.severity == "WARNING" for item in findings)
    informational_count = sum(item.severity == "INFORMATIONAL" for item in findings)
    result_payload = {
        **public_copy_audit_identity(),
        "website_id": value.website_id,
        "planned_page_id": value.planned_page_id,
        "generated_page_id": value.generated_page_id,
        "page_type": value.page_type,
        "projected_text_count": len(projected),
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "informational_count": informational_count,
        "public_copy_clean": blocker_count == 0,
        "identity_scope_authorization_sha256": (
            identity_scope_authorization_sha256
        ),
        "finding_fingerprints": [item.fingerprint for item in findings],
    }
    return PublicCopyAuditResult(
        ruleset_key=value.ruleset_key,
        ruleset_version=value.ruleset_version,
        ruleset_identity=value.ruleset_identity,
        ruleset_canonical_payload_sha256=(
            value.ruleset_canonical_payload_sha256
        ),
        audit_algorithm_key=PUBLIC_COPY_AUDIT_ALGORITHM_KEY,
        audit_algorithm_version=PUBLIC_COPY_AUDIT_ALGORITHM_VERSION,
        audit_algorithm_sha256=PUBLIC_COPY_AUDIT_ALGORITHM_SHA256,
        website_id=value.website_id,
        planned_page_id=value.planned_page_id,
        generated_page_id=value.generated_page_id,
        page_type=value.page_type,
        projected_text_count=len(projected),
        blocker_count=blocker_count,
        warning_count=warning_count,
        informational_count=informational_count,
        public_copy_clean=blocker_count == 0,
        identity_scope_authorization_sha256=(
            identity_scope_authorization_sha256
        ),
        findings=tuple(findings),
        fingerprint=_canonical_hash(result_payload),
    )


def audit_public_copy_pages(
    values: Sequence[PublicCopyAuditInput],
) -> PublicCopyAuditBatchResult:
    """Evaluate a complete page set with stable ordering and duplicate-scope guards."""

    identities: set[tuple[int, int]] = set()
    for value in values:
        identity = (value.website_id, value.generated_page_id)
        if identity in identities:
            raise ValueError(
                "Public-copy audit page scope contains a duplicate Website/Page identity."
            )
        identities.add(identity)
    results = tuple(
        audit_public_copy(item)
        for item in sorted(
            values,
            key=lambda item: (
                item.website_id,
                item.planned_page_id or 0,
                item.generated_page_id,
            ),
        )
    )
    payload = {
        **public_copy_audit_identity(),
        "result_fingerprints": [item.fingerprint for item in results],
        "identity_scope_authorization_sha256": _canonical_hash(
            [item.identity_scope_authorization_sha256 for item in results]
        ),
        "evaluated_page_count": len(results),
    }
    return PublicCopyAuditBatchResult(
        ruleset_key=PUBLIC_COPY_RULESET_KEY,
        ruleset_version=PUBLIC_COPY_RULESET_VERSION,
        ruleset_identity=PUBLIC_COPY_RULESET_IDENTITY,
        ruleset_canonical_payload_sha256=(
            PUBLIC_COPY_RULESET_CANONICAL_PAYLOAD_SHA256
        ),
        audit_algorithm_key=PUBLIC_COPY_AUDIT_ALGORITHM_KEY,
        audit_algorithm_version=PUBLIC_COPY_AUDIT_ALGORITHM_VERSION,
        audit_algorithm_sha256=PUBLIC_COPY_AUDIT_ALGORITHM_SHA256,
        evaluated_page_count=len(results),
        public_copy_clean_count=sum(item.public_copy_clean for item in results),
        public_copy_blocked_count=sum(not item.public_copy_clean for item in results),
        warning_page_count=sum(item.warning_count > 0 for item in results),
        blocker_finding_count=sum(item.blocker_count for item in results),
        warning_finding_count=sum(item.warning_count for item in results),
        informational_finding_count=sum(item.informational_count for item in results),
        identity_scope_authorization_sha256=payload[
            "identity_scope_authorization_sha256"
        ],
        results=results,
        fingerprint=_canonical_hash(payload),
    )


def _validate_ruleset_binding(value: PublicCopyAuditInput) -> None:
    expected = (
        PUBLIC_COPY_RULESET_KEY,
        PUBLIC_COPY_RULESET_VERSION,
        PUBLIC_COPY_RULESET_IDENTITY,
        PUBLIC_COPY_RULESET_CANONICAL_PAYLOAD_SHA256,
    )
    actual = (
        value.ruleset_key,
        value.ruleset_version,
        value.ruleset_identity,
        value.ruleset_canonical_payload_sha256,
    )
    if actual != expected:
        raise ValueError(
            "Public-copy audit input is not bound to the accepted sealed ruleset."
        )


def _validate_navigation_identity_allowances(
    value: PublicCopyAuditInput,
    projected: Sequence[ProjectedPublicCopy],
) -> None:
    allowances = value.allowed_navigation_identity_terms_by_path
    if not isinstance(allowances, Mapping):
        raise ValueError(
            "Navigation identity allowances must be an exact path mapping."
        )
    projected_by_path: dict[str, list[ProjectedPublicCopy]] = {}
    for item in projected:
        projected_by_path.setdefault(item.field_path, []).append(item)
    normalized_site_terms = {
        normalize_public_copy(term)
        for term in value.site_identity_terms
        if isinstance(term, str) and normalize_public_copy(term)
    }
    for path, terms in allowances.items():
        if (
            not isinstance(path, str)
            or _NAVIGATION_IDENTITY_ALLOWANCE_PATH_PATTERN.fullmatch(path) is None
        ):
            raise ValueError(
                "Navigation identity allowance path is outside an exact resolved navigation label."
            )
        matches = projected_by_path.get(path, [])
        if (
            len(matches) != 1
            or matches[0].surface != "composition"
            or matches[0].context != "navigation_label"
        ):
            raise ValueError(
                "Navigation identity allowance path does not resolve one projected navigation label."
            )
        if isinstance(terms, (str, bytes, bytearray)) or not isinstance(
            terms, Sequence
        ):
            raise ValueError(
                "Navigation identity allowance terms must be an exact sequence."
            )
        exact_terms: list[str] = []
        normalized_terms: list[str] = []
        for term in terms:
            if (
                not isinstance(term, str)
                or not term
                or term != term.strip()
            ):
                raise ValueError(
                    "Navigation identity allowance contains a malformed exact term."
                )
            normalized = normalize_public_copy(term)
            if not normalized or normalized not in normalized_site_terms:
                raise ValueError(
                    "Navigation identity allowance is outside the governed site identity scope."
                )
            exact_terms.append(term)
            normalized_terms.append(normalized)
        if (
            not exact_terms
            or exact_terms != sorted(exact_terms)
            or len(normalized_terms) != len(set(normalized_terms))
        ):
            raise ValueError(
                "Navigation identity allowance terms must be nonempty, unique, and sorted."
            )


def _identity_scope_authorization_sha256(value: PublicCopyAuditInput) -> str:
    return _canonical_hash(
        {
            "site_identity_terms": sorted(set(value.site_identity_terms)),
            "allowed_identity_terms": sorted(set(value.allowed_identity_terms)),
            "allowed_navigation_identity_terms_by_path": {
                path: list(terms)
                for path, terms in sorted(
                    value.allowed_navigation_identity_terms_by_path.items()
                )
            },
        }
    )


def _source_owner(value: PublicCopyAuditInput, path: str, surface: str) -> str:
    candidates = [
        (prefix, owner)
        for prefix, owner in value.source_owner_by_path.items()
        if path == prefix or path.startswith(f"{prefix}.") or path.startswith(f"{prefix}[")
    ]
    if candidates:
        return max(candidates, key=lambda item: len(item[0]))[1]
    return {
        "metadata": "GeneratedPage.public_metadata",
        "draft": "GeneratedPage.draft_content",
        "composition": "PageComposition.effective_components.resolved_data",
        "export": "PageExportPackage.public_projection",
        "structured_data": "PublicStructuredData",
        "form": "ProviderDisabledForm.public_helper_copy",
        "alt_text": "PublicMedia.alt_text",
    }[surface]


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="python")
        return dumped if isinstance(dumped, Mapping) else {}
    return {}


def _as_sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _project_metadata(value: Any, add: Any) -> None:
    payload = _as_mapping(value)
    for key in _PUBLIC_METADATA_KEYS:
        if key in payload:
            context = "heading" if key in {"title", "page_title", "h1"} else (
                "url" if key == "canonical_url" else "metadata"
            )
            add(
                "metadata",
                f"public_metadata.{key}",
                payload[key],
                context,
                include_empty=key in {"title", "page_title", "h1"},
            )


def _project_draft(value: Any, add: Any) -> None:
    payload = _as_mapping(value)
    for key in _DRAFT_TEXT_KEYS:
        if key in payload:
            context = (
                "heading"
                if key in {"title", "h1"}
                else "metadata"
                if key in {"meta_title", "meta_description"}
                else "cta_body"
                if key == "call_to_action"
                else "intro"
                if key == "intro"
                else "body"
            )
            add(
                "draft",
                f"draft_content.{key}",
                payload[key],
                context,
                include_empty=key in {"title", "h1"},
            )
    for index, raw in enumerate(_as_sequence(payload.get("sections"))):
        item = _as_mapping(raw)
        if "heading" in item:
            add(
                "draft",
                f"draft_content.sections[{index}].heading",
                item["heading"],
                "heading",
                include_empty=bool(item.get("body")),
            )
        if "body" in item:
            add(
                "draft",
                f"draft_content.sections[{index}].body",
                item["body"],
                "body",
            )
    for index, raw in enumerate(_as_sequence(payload.get("faq_items"))):
        item = _as_mapping(raw)
        for key, context in (("question", "heading"), ("answer", "faq_answer")):
            if key in item:
                add(
                    "draft",
                    f"draft_content.faq_items[{index}].{key}",
                    item[key],
                    context,
                    include_empty=True,
                )
    for collection in ("related_pages", "public_destination_copy"):
        for index, raw in enumerate(_as_sequence(payload.get(collection))):
            item = _as_mapping(raw)
            for key in ("label", "title", "slug", "description", "purpose"):
                if key in item:
                    context = (
                        "destination_label"
                        if key in {"label", "title"}
                        else "destination_slug"
                        if key == "slug"
                        else "destination_description"
                    )
                    add(
                        "draft",
                        f"draft_content.{collection}[{index}].{key}",
                        item[key],
                        context,
                        include_empty=key in {"label", "title"},
                    )
    for index, raw in enumerate(_as_sequence(payload.get("image_placements"))):
        item = _as_mapping(raw)
        for key in ("alt_text", "caption", "image_title", "accessibility_description"):
            if key in item:
                add(
                    "draft",
                    f"draft_content.image_placements[{index}].{key}",
                    item[key],
                    "alt_text" if key == "alt_text" else "media_copy",
                )


def _project_composition(value: Any, add: Any) -> None:
    payload = _as_mapping(value)
    components = payload.get("effective_components")
    if components is None and isinstance(value, Sequence) and not isinstance(value, str):
        components = value
    for index, raw in enumerate(_as_sequence(components)):
        item = _as_mapping(raw)
        component_key = item.get("component_key")
        base = f"composition.effective_components[{index}]"
        if not isinstance(component_key, str) or component_key not in _KNOWN_COMPONENT_KEYS:
            add(
                "composition",
                f"{base}.component_key",
                f"Unhandled public component: {component_key!s}.",
                "unclassified_component",
                include_empty=True,
            )
            continue
        data = _as_mapping(item.get("resolved_data"))
        resolved = f"{base}.resolved_data"
        if component_key in _IDENTITY_COMPONENT_KEYS:
            for key in (
                "display_name",
                "tagline",
                "company_name",
                "business_type",
                "phone",
                "email",
                "license_number",
                "certified_operator",
            ):
                if key in data:
                    add(
                        "composition",
                        f"{resolved}.{key}",
                        data[key],
                        "credential" if key in {"license_number", "certified_operator"} else "identity",
                    )
            assets = _as_mapping(data.get("identity_assets"))
            for slot in sorted(assets, key=str):
                asset = _as_mapping(assets[slot])
                if "accessibility_description" in asset:
                    add(
                        "composition",
                        f"{resolved}.identity_assets.{slot}.accessibility_description",
                        asset["accessibility_description"],
                        "alt_text",
                    )
        elif component_key in _NAVIGATION_COMPONENT_KEYS:
            if "label" in data:
                add("composition", f"{resolved}.label", data["label"], "navigation_label")
            for item_index, raw_nav in enumerate(_as_sequence(data.get("items"))):
                nav = _as_mapping(raw_nav)
                for key in ("label", "description"):
                    if key in nav:
                        add(
                            "composition",
                            f"{resolved}.items[{item_index}].{key}",
                            nav[key],
                            "navigation_label" if key == "label" else "navigation_description",
                            include_empty=key == "label",
                        )
        elif component_key == "hero":
            for key, context in (("title", "heading"), ("intro", "intro")):
                if key in data:
                    add(
                        "composition",
                        f"{resolved}.{key}",
                        data[key],
                        context,
                        include_empty=key == "title",
                    )
        elif component_key in {"content_section", "service_summary"}:
            for key in ("heading", "body", "title", "description"):
                if key in data:
                    add(
                        "composition",
                        f"{resolved}.{key}",
                        data[key],
                        "heading" if key in {"heading", "title"} else "body",
                        include_empty=key in {"heading", "title"} and bool(data.get("body")),
                    )
            for step_index, raw_step in enumerate(_as_sequence(data.get("steps"))):
                step = _as_mapping(raw_step)
                for key in ("heading", "title", "label", "body", "description"):
                    if key in step:
                        add(
                            "composition",
                            f"{resolved}.steps[{step_index}].{key}",
                            step[key],
                            "heading" if key in {"heading", "title", "label"} else "body",
                        )
        elif component_key == "media_placement":
            for key in ("alt_text", "caption", "image_title"):
                if key in data:
                    add(
                        "composition",
                        f"{resolved}.{key}",
                        data[key],
                        "alt_text" if key == "alt_text" else "media_copy",
                    )
        elif component_key in {"related_page_links", "destination_cards"}:
            for link_index, raw_link in enumerate(_as_sequence(data.get("links"))):
                link = _as_mapping(raw_link)
                for key in ("label", "slug", "description", "purpose"):
                    if key in link:
                        add(
                            "composition",
                            f"{resolved}.links[{link_index}].{key}",
                            link[key],
                            "destination_label"
                            if key == "label"
                            else "destination_slug"
                            if key == "slug"
                            else "destination_description",
                            include_empty=key == "label",
                        )
        elif component_key == "faq":
            for faq_index, raw_faq in enumerate(_as_sequence(data.get("items"))):
                faq = _as_mapping(raw_faq)
                for key, context in (("question", "heading"), ("answer", "faq_answer")):
                    if key in faq:
                        add(
                            "composition",
                            f"{resolved}.items[{faq_index}].{key}",
                            faq[key],
                            context,
                            include_empty=True,
                        )
        elif component_key == "final_cta":
            for key, context in (("heading", "heading"), ("body", "cta_body")):
                if key in data:
                    add(
                        "composition",
                        f"{resolved}.{key}",
                        data[key],
                        context,
                        include_empty=key == "heading" and bool(data.get("body")),
                    )


def _project_export(value: Any, add: Any) -> None:
    payload = _as_mapping(value)
    if not payload:
        return
    direct = {
        "page_title": "heading",
        "h1": "heading",
        "cta_block": "cta_body",
        "city": "identity",
        "county": "identity",
        "state": "identity",
        "service": "identity",
        "business_name": "identity",
        "phone": "identity",
        "website": "url",
        "email": "identity",
        "license_number": "credential",
        "certified_operator": "credential",
        "canonical_url_preview": "url",
    }
    for key, context in direct.items():
        if key in payload:
            add(
                "export",
                f"export_payload.{key}",
                payload[key],
                context,
                include_empty=key in {"page_title", "h1"},
            )
    seo = _as_mapping(payload.get("seo"))
    for key in ("meta_title", "meta_description", "social_title", "social_description"):
        if key in seo:
            add("export", f"export_payload.seo.{key}", seo[key], "metadata")
    sections = _as_mapping(payload.get("content_sections"))
    for key in sorted(sections, key=str):
        add(
            "export",
            f"export_payload.content_sections.{key}",
            sections[key],
            "body",
        )
    for index, raw in enumerate(_as_sequence(payload.get("faq_items"))):
        item = _as_mapping(raw)
        for key, context in (("question", "heading"), ("answer", "faq_answer")):
            if key in item:
                add(
                    "export",
                    f"export_payload.faq_items[{index}].{key}",
                    item[key],
                    context,
                    include_empty=True,
                )
    for index, raw in enumerate(_as_sequence(payload.get("assigned_media"))):
        item = _as_mapping(raw)
        for key in ("alt_text", "image_title"):
            if key in item:
                add(
                    "export",
                    f"export_payload.assigned_media[{index}].{key}",
                    item[key],
                    "alt_text" if key == "alt_text" else "media_copy",
                )
    _project_structured(payload.get("json_ld"), "export_payload.json_ld", add, surface="export")


def _project_structured(
    value: Any,
    path: str,
    add: Any,
    *,
    surface: str = "structured_data",
) -> None:
    if isinstance(value, str):
        add(surface, path, value, "structured_data")
        return
    payload = _as_mapping(value)
    if payload:
        for key in sorted(payload, key=str):
            if str(key) in _STRUCTURED_EXCLUDED_KEYS:
                continue
            _project_structured(payload[key], f"{path}.{key}", add, surface=surface)
        return
    for index, item in enumerate(_as_sequence(value)):
        _project_structured(item, f"{path}[{index}]", add, surface=surface)


def _project_form(value: Any, add: Any, path: str = "form_helper_copy") -> None:
    payload = _as_mapping(value)
    if not payload:
        return
    for key in sorted(payload, key=str):
        raw = payload[key]
        child_path = f"{path}.{key}"
        if key in _FORM_TEXT_KEYS:
            context = (
                "provider_disabled_form_notice"
                if key in {"preview_notice", "provider_disabled_notice", "safety_notice", "notice"}
                else "form_label"
                if key in {"label", "cta_label", "submit_label", "title", "heading"}
                else "form_helper"
            )
            add("form", child_path, raw, context, include_empty=context == "form_label")
        elif key in _FORM_CONTAINER_KEYS:
            for index, child in enumerate(_as_sequence(raw)):
                _project_form(child, add, f"{child_path}[{index}]")
            child_mapping = _as_mapping(raw)
            if child_mapping:
                _project_form(child_mapping, add, child_path)


def _project_alt_text(value: Any, add: Any, path: str = "alt_text") -> None:
    if isinstance(value, str):
        add("alt_text", path, value, "alt_text")
        return
    payload = _as_mapping(value)
    if payload:
        for key in sorted(payload, key=str):
            _project_alt_text(payload[key], add, f"{path}.{key}")
        return
    for index, item in enumerate(_as_sequence(value)):
        _project_alt_text(item, add, f"{path}[{index}]")


def _audit_projected_text(
    audit_input: PublicCopyAuditInput,
    item: ProjectedPublicCopy,
) -> list[PublicCopyFinding]:
    normalized = item.normalized_text
    findings: list[PublicCopyFinding] = []
    if item.context == "unclassified_component":
        return [
            _finding(
                audit_input,
                item,
                rule_id="PC-BLOCK-PROJECTION-000",
                category="unclassified_public_component",
                severity="BLOCKER",
                message="A public component has no source-audit projection contract.",
                correction="source_repair_required",
            )
        ]
    if item.context in {"heading", "destination_label", "navigation_label", "form_label"}:
        if not normalized or normalized in {"untitled", "heading", "section", "content"}:
            findings.append(
                _finding(
                    audit_input,
                    item,
                    rule_id="PC-BLOCK-EMPTY-008",
                    category="empty_or_meaningless_heading",
                    severity="BLOCKER",
                    message="Public headings and labels must be meaningful and nonempty.",
                    correction="source_repair_required",
                )
            )
    provider_notice_exception = (
        item.context == "provider_disabled_form_notice"
        and normalized == _NORMALIZED_PROVIDER_DISABLED_NOTICE
    )
    matched_internal = [
        phrase for phrase in _INTERNAL_PHRASES if _contains_phrase(normalized, phrase)
    ]
    if provider_notice_exception:
        matched_internal = [
            phrase for phrase in matched_internal if normalize_public_copy(phrase) != "draft preview"
        ]
        findings.append(
            _finding(
                audit_input,
                item,
                rule_id="EX-FORM-NO-SUBMISSION-001",
                category="provider_disabled_safety_notice",
                severity="INFORMATIONAL",
                message="Exact provider-disabled no-submission safety notice is preserved.",
                correction="no_automatic_change",
            )
        )
    if matched_internal:
        findings.append(
            _finding(
                audit_input,
                item,
                rule_id="PC-BLOCK-INTERNAL-EXACT-001",
                category="internal_instruction",
                severity="BLOCKER",
                message=(
                    "Public copy contains internal workflow language: "
                    + ", ".join(sorted(set(matched_internal)))
                    + "."
                ),
                correction="source_repair_required",
            )
        )
    if any(re.search(pattern, normalized) for pattern in _INTERNAL_CONTEXT_PATTERNS):
        findings.append(
            _finding(
                audit_input,
                item,
                rule_id="PC-BLOCK-ROUTING-002",
                category="routing_or_component_instruction",
                severity="BLOCKER",
                message="Public copy contains a routing, component, or implementation instruction.",
                correction="source_repair_required",
            )
        )
    if any(re.search(pattern, normalized) for pattern in _PLACEHOLDER_PATTERNS):
        findings.append(
            _finding(
                audit_input,
                item,
                rule_id="PC-BLOCK-PLACEHOLDER-003",
                category="placeholder_or_demo_copy",
                severity="BLOCKER",
                message="Placeholder, demo, or unfinished copy is visible publicly.",
                correction="source_repair_required",
            )
        )
    if any(re.search(pattern, normalized) for pattern in _UNSUPPORTED_CLAIM_PATTERNS):
        findings.append(
            _finding(
                audit_input,
                item,
                rule_id="PC-BLOCK-UNSUPPORTED-CLAIM-004",
                category="unsupported_business_claim",
                severity="BLOCKER",
                message="Public copy contains a claim that requires an exact governed fact.",
                correction="source_repair_required",
            )
        )
    if any(re.search(pattern, normalized) for pattern in _MALFORMED_PATTERNS):
        findings.append(
            _finding(
                audit_input,
                item,
                rule_id="PC-BLOCK-MALFORMED-005",
                category="malformed_copy",
                severity="BLOCKER",
                message="Public copy contains a known malformed sentence or fragment.",
                correction="source_repair_required",
            )
        )
    findings.extend(_identity_leakage_findings(audit_input, item))
    if item.context in {"body", "intro", "cta_body", "destination_description", "faq_answer"}:
        if _RAW_URL_PATTERN.search(item.exact_text):
            findings.append(
                _finding(
                    audit_input,
                    item,
                    rule_id="PC-WARN-RAW-URL-012",
                    category="raw_url_in_body_copy",
                    severity="WARNING",
                    message="A raw Website URL appears in body prose.",
                    correction="source_repair_required",
                )
            )
        if len(normalized) > 650:
            findings.append(
                _finding(
                    audit_input,
                    item,
                    rule_id="PC-WARN-STRUCTURE-013",
                    category="overlong_public_paragraph",
                    severity="WARNING",
                    message="A public paragraph is overlong and should be reviewed for structure.",
                    correction="no_automatic_change",
                )
            )
        sentences = [normalize_public_copy(match.group()) for match in _SENTENCE_PATTERN.finditer(item.exact_text)]
        repeated = {sentence for sentence in sentences if len(sentence) >= 25 and sentences.count(sentence) > 1}
        if repeated:
            findings.append(
                _finding(
                    audit_input,
                    item,
                    rule_id="PC-WARN-REPETITION-011",
                    category="repeated_public_sentence",
                    severity="WARNING",
                    message="A substantive sentence is repeated within one public field.",
                    correction="source_repair_required",
                )
            )
    if item.context == "destination_description" and (
        normalized in {"learn more", "click here", "more information", "explore more"}
        or len(normalized) < 16
    ):
        findings.append(
            _finding(
                audit_input,
                item,
                rule_id="PC-WARN-ROBOTIC-010",
                category="vague_destination_description",
                severity="WARNING",
                message="Destination copy does not identify a useful customer-facing destination.",
                correction="source_repair_required",
            )
        )
    technical = (
        item.context in {"body", "intro", "faq_answer"}
        and bool(_TECHNICAL_CONTEXT_PATTERN.search(item.exact_text))
        and (
            len(normalized) >= 60
            or bool(_STRONG_TECHNICAL_CONTEXT_PATTERN.search(item.exact_text))
        )
    )
    if technical:
        findings.append(
            _finding(
                audit_input,
                item,
                rule_id="PC-INFO-SHARED-014",
                category="shared_technical_copy",
                severity="INFORMATIONAL",
                message="Technical service copy is preserved rather than rewritten for variation.",
                correction="no_automatic_change",
            )
        )
        if _TECHNICAL_CLAIM_PATTERN.search(item.exact_text):
            findings.append(
                _finding(
                    audit_input,
                    item,
                    rule_id="PC-WARN-TECHNICAL-015",
                    category="technical_claim_expert_review",
                    severity="WARNING",
                    message="A technical claim is preserved and queued for expert review.",
                    correction="expert_review_required",
                )
            )
    return findings


def _identity_leakage_findings(
    audit_input: PublicCopyAuditInput,
    item: ProjectedPublicCopy,
) -> list[PublicCopyFinding]:
    if not audit_input.site_identity_terms:
        return []
    allowed = {
        normalize_public_copy(value)
        for value in audit_input.allowed_identity_terms
        if normalize_public_copy(value)
    }
    if item.surface == "composition" and item.context == "navigation_label":
        path_terms = (
            audit_input.allowed_navigation_identity_terms_by_path.get(
                item.field_path,
                (),
            )
        )
        allowed.update(
            normalize_public_copy(value)
            for value in path_terms
            if normalize_public_copy(value)
        )
    leaked: list[str] = []
    for raw in audit_input.site_identity_terms:
        term = normalize_public_copy(raw)
        if len(term) < 3 or term in allowed:
            continue
        if _contains_identity_outside_allowed_terms(
            item.normalized_text,
            term,
            allowed,
        ):
            leaked.append(raw)
    if not leaked:
        return []
    return [
        _finding(
            audit_input,
            item,
            rule_id="PC-BLOCK-CROSS-PAGE-006",
            category="cross_page_identity_leakage",
            severity="BLOCKER",
            message=(
                "Public copy contains an identity outside this page's governed source "
                f"or destination scope: {', '.join(sorted(set(leaked)))}."
            ),
            correction="source_repair_required",
        )
    ]


def _duplicate_findings(
    audit_input: PublicCopyAuditInput,
    projected: Sequence[ProjectedPublicCopy],
) -> list[PublicCopyFinding]:
    eligible_contexts = {
        "body",
        "intro",
        "cta_body",
        "destination_description",
        "faq_answer",
    }
    seen: dict[tuple[str, str], ProjectedPublicCopy] = {}
    findings: list[PublicCopyFinding] = []
    for item in projected:
        normalized = item.normalized_text
        if item.context not in eligible_contexts or len(normalized) < 60:
            continue
        key = (item.surface, normalized)
        first = seen.get(key)
        if first is None:
            seen[key] = item
            continue
        if first.field_path == item.field_path:
            continue
        findings.append(
            _finding(
                audit_input,
                item,
                rule_id="PC-BLOCK-DUPLICATE-007",
                category="same_page_duplicate_public_block",
                severity="BLOCKER",
                message=f"Public block duplicates {first.field_path} on the same surface.",
                correction="source_repair_required",
            )
        )
    return findings


def _contains_phrase(normalized_text: str, phrase: str) -> bool:
    return _contains_normalized(normalized_text, normalize_public_copy(phrase))


def _contains_normalized(normalized_text: str, normalized_phrase: str) -> bool:
    return bool(_normalized_phrase_spans(normalized_text, normalized_phrase))


def _normalized_phrase_spans(
    normalized_text: str,
    normalized_phrase: str,
) -> tuple[tuple[int, int], ...]:
    if not normalized_phrase:
        return ()
    return tuple(
        match.span()
        for match in re.finditer(
            rf"(?<![\w]){re.escape(normalized_phrase)}(?![\w])",
            normalized_text,
        )
    )


def _contains_identity_outside_allowed_terms(
    normalized_text: str,
    normalized_identity: str,
    allowed_terms: Sequence[str],
) -> bool:
    identity_spans = _normalized_phrase_spans(
        normalized_text,
        normalized_identity,
    )
    if not identity_spans:
        return False
    covering_spans = tuple(
        span
        for allowed_term in allowed_terms
        if len(allowed_term) > len(normalized_identity)
        for span in _normalized_phrase_spans(normalized_text, allowed_term)
    )
    return any(
        not any(
            allowed_start <= identity_start and identity_end <= allowed_end
            for allowed_start, allowed_end in covering_spans
        )
        for identity_start, identity_end in identity_spans
    )


def _finding(
    audit_input: PublicCopyAuditInput,
    item: ProjectedPublicCopy,
    *,
    rule_id: str,
    category: str,
    severity: Severity,
    message: str,
    correction: SafeCorrectionStatus,
) -> PublicCopyFinding:
    fingerprint_payload = {
        "ruleset_canonical_payload_sha256": audit_input.ruleset_canonical_payload_sha256,
        "audit_algorithm_sha256": PUBLIC_COPY_AUDIT_ALGORITHM_SHA256,
        "website_id": audit_input.website_id,
        "planned_page_id": audit_input.planned_page_id,
        "generated_page_id": audit_input.generated_page_id,
        "page_type": audit_input.page_type,
        "field_path": item.field_path,
        "exact_text": item.exact_text,
        "source_owner": item.source_owner,
        "rule_id": rule_id,
        "category": category,
        "severity": severity,
        "safe_correction_status": correction,
    }
    return PublicCopyFinding(
        ruleset_key=audit_input.ruleset_key,
        ruleset_version=audit_input.ruleset_version,
        ruleset_identity=audit_input.ruleset_identity,
        ruleset_canonical_payload_sha256=(
            audit_input.ruleset_canonical_payload_sha256
        ),
        audit_algorithm_key=PUBLIC_COPY_AUDIT_ALGORITHM_KEY,
        audit_algorithm_version=PUBLIC_COPY_AUDIT_ALGORITHM_VERSION,
        audit_algorithm_sha256=PUBLIC_COPY_AUDIT_ALGORITHM_SHA256,
        website_id=audit_input.website_id,
        planned_page_id=audit_input.planned_page_id,
        generated_page_id=audit_input.generated_page_id,
        page_type=audit_input.page_type,
        field_path=item.field_path,
        exact_text=item.exact_text,
        normalized_text=item.normalized_text,
        normalized_fingerprint=item.normalized_fingerprint,
        source_owner=item.source_owner,
        rule_id=rule_id,
        category=category,
        severity=severity,
        message=message,
        safe_correction_status=correction,
        fingerprint=_canonical_hash(fingerprint_payload),
    )


def _deduplicated_sorted_findings(
    findings: Sequence[PublicCopyFinding],
) -> list[PublicCopyFinding]:
    unique = {item.fingerprint: item for item in findings}
    severity_order = {"BLOCKER": 0, "WARNING": 1, "INFORMATIONAL": 2}
    return sorted(
        unique.values(),
        key=lambda item: (
            severity_order[item.severity],
            item.field_path,
            item.rule_id,
            item.fingerprint,
        ),
    )
