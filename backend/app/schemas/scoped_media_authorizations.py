from datetime import UTC, datetime
import hashlib
import json
from typing import Any, Iterable, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ScopedMediaReusePolicy = Literal[
    "contract_default",
    "requirement_only",
    "page_only",
    "website_limited",
    "explicitly_reusable",
]
ScopedMediaAuthorizationLifecycle = Literal["current", "superseded"]
ScopedMediaAuthorizationTerm = Literal[
    "visible_branding_allowed",
    "authorized_person_likeness",
    "representative_nonlocalized",
    "not_documentary_evidence",
    "reference_guided_synthetic_asset",
    "visible_scale_reference_allowed",
    "requirement_only_usage",
    "page_only_usage",
    "no_reuse",
    "contract_deviation_authorized",
]

SCOPED_MEDIA_AUTHORIZATION_TERMS: tuple[str, ...] = (
    "visible_branding_allowed",
    "authorized_person_likeness",
    "representative_nonlocalized",
    "not_documentary_evidence",
    "reference_guided_synthetic_asset",
    "visible_scale_reference_allowed",
    "requirement_only_usage",
    "page_only_usage",
    "no_reuse",
    "contract_deviation_authorized",
)
_TERM_ALLOWLIST = frozenset(SCOPED_MEDIA_AUTHORIZATION_TERMS)
_LOWER_SHA256_PATTERN = r"^[0-9a-f]{64}$"


def normalize_scoped_media_authorization_terms(value: object) -> list[str]:
    """Return the canonical, nonempty authorization-term list.

    Canonical storage is sorted and duplicate-free so the same typed decision has
    one deterministic fingerprint representation.
    """

    if not isinstance(value, (list, tuple, set, frozenset)):
        raise ValueError("authorization_terms must be a nonempty list")
    normalized: list[str] = []
    for raw_term in value:
        if not isinstance(raw_term, str):
            raise ValueError("authorization_terms entries must be strings")
        term = raw_term.strip()
        if term not in _TERM_ALLOWLIST:
            raise ValueError(f"Unsupported scoped-media authorization term: {term!r}")
        normalized.append(term)
    result = sorted(set(normalized))
    if not result:
        raise ValueError("authorization_terms must contain at least one typed term")
    return result


def normalize_scoped_media_required_terms(value: object) -> list[str]:
    """Return the canonical asset-declared required-term set.

    Contract-default assets declare an empty set.  Assets whose use requires a
    scoped decision persist the exact typed facts that every authorization must
    contain, so free text can never silently stand in for a required fact.
    """

    if not isinstance(value, (list, tuple, set, frozenset)):
        raise ValueError("required_authorization_terms must be a list")
    if not value:
        return []
    return normalize_scoped_media_authorization_terms(value)


def validate_scoped_media_authorization_policy_terms(
    reuse_policy: str,
    terms: Iterable[str],
    *,
    required_terms: Iterable[str] = (),
) -> list[str]:
    """Validate and return one canonical policy/term decision.

    This pure helper is shared by runtime authorization and backup validation so
    persisted, restored, and newly created decisions obey the same fail-closed
    contract.
    """

    supported_policies = {
        "contract_default",
        "requirement_only",
        "page_only",
        "website_limited",
        "explicitly_reusable",
    }
    if reuse_policy not in supported_policies:
        raise ValueError("Scoped media reuse policy is unsupported.")
    normalized = normalize_scoped_media_authorization_terms(list(terms))
    required = normalize_scoped_media_required_terms(list(required_terms))
    missing = sorted(set(required) - set(normalized))
    if missing:
        raise ValueError(
            "Scoped media authorization is missing asset-required typed terms: "
            + ", ".join(missing)
            + "."
        )
    selected = set(normalized)
    if reuse_policy == "requirement_only" and not (
        {"requirement_only_usage", "no_reuse"} & selected
    ):
        raise ValueError(
            "Requirement-only authorization lacks its typed usage restriction."
        )
    if reuse_policy == "page_only" and "page_only_usage" not in selected:
        raise ValueError("Page-only authorization lacks its typed usage restriction.")
    if "no_reuse" in selected and reuse_policy != "requirement_only":
        raise ValueError(
            "No-reuse authorization must use requirement_only reuse policy."
        )
    if "requirement_only_usage" in selected and reuse_policy != "requirement_only":
        raise ValueError(
            "requirement_only_usage conflicts with the selected reuse policy."
        )
    if "page_only_usage" in selected and reuse_policy != "page_only":
        raise ValueError("page_only_usage conflicts with the selected reuse policy.")
    if "contract_deviation_authorized" in selected and len(selected) == 1:
        raise ValueError(
            "A contract deviation requires at least one specific typed authorization term."
        )
    return normalized


def _canonical_datetime(value: object) -> str:
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise ValueError("Fingerprint datetime values must be datetime or ISO strings")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def scoped_media_approval_fingerprint(values: Mapping[str, Any]) -> str:
    """Fingerprint the exact approved asset identity bound by authorization."""

    return _fingerprint(
        {
            "approval_version": values["approval_version"],
            "asset_approved_at": _canonical_datetime(values["asset_approved_at"]),
            "asset_approved_by": str(values["asset_approved_by"]).strip(),
            "asset_business_id": values["asset_business_id"],
            "asset_checksum_sha256": str(values["asset_checksum_sha256"]).lower(),
            "asset_website_id": values["asset_website_id"],
            "image_metadata_id": values["image_metadata_id"],
            "media_version": values["media_version"],
            "required_authorization_terms": normalize_scoped_media_required_terms(
                values.get("required_authorization_terms", [])
            ),
            "usage_authorization_mode": str(
                values.get("usage_authorization_mode", "contract_default")
            ),
        }
    )


def scoped_media_authorization_fingerprint(values: Mapping[str, Any]) -> str:
    """Fingerprint immutable authorization evidence.

    Lifecycle is intentionally excluded because replacing the current row marks it
    superseded without rewriting the immutable decision evidence.
    """

    payload = {
        "approval_fingerprint": str(values["approval_fingerprint"]).lower(),
        "approval_version": values["approval_version"],
        "asset_approved_at": _canonical_datetime(values["asset_approved_at"]),
        "asset_approved_by": str(values["asset_approved_by"]).strip(),
        "asset_checksum_sha256": str(values["asset_checksum_sha256"]).lower(),
        "assignment_version": values.get("assignment_version"),
        "authorization_rationale": str(values["authorization_rationale"]).strip(),
        "authorization_terms": normalize_scoped_media_authorization_terms(
            values["authorization_terms"]
        ),
        "authorization_version": values["authorization_version"],
        "authorized_at": _canonical_datetime(values["authorized_at"]),
        "authorized_by": str(values["authorized_by"]).strip(),
        "generated_page_id": values.get("generated_page_id"),
        "image_metadata_id": values["image_metadata_id"],
        "media_requirement_id": values["media_requirement_id"],
        "media_version": values["media_version"],
        "page_image_assignment_id": values.get("page_image_assignment_id"),
        "placement_contract_version": values["placement_contract_version"],
        "placement_key": str(values["placement_key"]).strip(),
        "planned_page_id": values["planned_page_id"],
        "requirement_version": values["requirement_version"],
        "reuse_policy": values["reuse_policy"],
        "site_plan_id": values["site_plan_id"],
        "supersedes_authorization_id": values.get("supersedes_authorization_id"),
        "website_id": values["website_id"],
    }
    return _fingerprint(payload)


class _ScopedMediaAuthorizationDecision(BaseModel):
    """Typed operator decision fields shared by request and durable evidence."""

    model_config = ConfigDict(extra="forbid")

    reuse_policy: ScopedMediaReusePolicy
    authorization_terms: list[ScopedMediaAuthorizationTerm] = Field(
        min_length=1,
        max_length=len(SCOPED_MEDIA_AUTHORIZATION_TERMS),
    )
    authorized_by: str = Field(min_length=1, max_length=160)
    authorization_rationale: str = Field(min_length=1, max_length=2000)

    @field_validator("authorization_terms", mode="before")
    @classmethod
    def normalize_terms(cls, value: object) -> list[str]:
        return normalize_scoped_media_authorization_terms(value)

    @field_validator("authorized_by", "authorization_rationale")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value must contain non-whitespace text")
        return normalized

    @model_validator(mode="after")
    def validate_policy_terms(self) -> "_ScopedMediaAuthorizationDecision":
        validate_scoped_media_authorization_policy_terms(
            self.reuse_policy,
            self.authorization_terms,
        )
        return self


class ScopedMediaAuthorizationRequest(_ScopedMediaAuthorizationDecision):
    """Public request with optimistic bindings; durable evidence is server-derived."""

    media_requirement_id: int = Field(gt=0)
    expected_requirement_version: int = Field(ge=1)
    expected_placement_contract_version: int = Field(ge=1)
    image_metadata_id: int = Field(gt=0)
    expected_media_version: int = Field(ge=1)
    expected_asset_checksum_sha256: str = Field(pattern=_LOWER_SHA256_PATTERN)
    expected_approval_version: int = Field(ge=1)
    expected_approval_fingerprint: str = Field(pattern=_LOWER_SHA256_PATTERN)
    page_image_assignment_id: int | None = Field(default=None, gt=0)
    expected_assignment_version: int | None = Field(default=None, ge=1)
    expected_current_authorization_fingerprint: str | None = Field(
        default=None,
        pattern=_LOWER_SHA256_PATTERN,
    )

    @model_validator(mode="after")
    def validate_expected_assignment_pair(self) -> "ScopedMediaAuthorizationRequest":
        assignment_present = self.page_image_assignment_id is not None
        version_present = self.expected_assignment_version is not None
        if assignment_present != version_present:
            raise ValueError(
                "page_image_assignment_id and expected_assignment_version must "
                "both be null or both be populated"
            )
        return self


class ScopedMediaAuthorizationInternalCreate(_ScopedMediaAuthorizationDecision):
    """Internal persistence payload populated only from server-verified records."""

    website_id: int = Field(gt=0)
    site_plan_id: int = Field(gt=0)
    planned_page_id: int = Field(gt=0)
    generated_page_id: int | None = Field(default=None, gt=0)
    media_requirement_id: int = Field(gt=0)
    requirement_version: int = Field(ge=1)
    placement_key: str = Field(min_length=1, max_length=120)
    placement_contract_version: int = Field(ge=1)
    image_metadata_id: int = Field(gt=0)
    media_version: int = Field(ge=1)
    asset_checksum_sha256: str = Field(pattern=_LOWER_SHA256_PATTERN)
    approval_version: int = Field(ge=1)
    asset_approved_by: str = Field(min_length=1, max_length=160)
    asset_approved_at: datetime
    approval_fingerprint: str = Field(pattern=_LOWER_SHA256_PATTERN)
    page_image_assignment_id: int | None = Field(default=None, gt=0)
    assignment_version: int | None = Field(default=None, ge=1)
    authorized_at: datetime
    authorization_version: int = Field(ge=1)
    authorization_fingerprint: str = Field(pattern=_LOWER_SHA256_PATTERN)
    lifecycle_status: ScopedMediaAuthorizationLifecycle
    supersedes_authorization_id: int | None = Field(default=None, gt=0)

    @field_validator("placement_key", "asset_approved_by")
    @classmethod
    def strip_internal_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value must contain non-whitespace text")
        return normalized

    @model_validator(mode="after")
    def validate_binding_pairs(self) -> "ScopedMediaAuthorizationInternalCreate":
        assignment_present = self.page_image_assignment_id is not None
        version_present = self.assignment_version is not None
        if assignment_present != version_present:
            raise ValueError(
                "page_image_assignment_id and assignment_version must both be null "
                "or both be populated"
            )
        if self.authorization_version == 1:
            if self.supersedes_authorization_id is not None:
                raise ValueError("Authorization version 1 cannot supersede another row")
        elif self.supersedes_authorization_id is None:
            raise ValueError("Successor authorizations must bind their predecessor")
        return self


class ScopedMediaAuthorizationRead(ScopedMediaAuthorizationInternalCreate):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: int
    created_at: datetime
    updated_at: datetime
