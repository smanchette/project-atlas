from __future__ import annotations

from collections.abc import Mapping
from typing import Any


DISPLAY_PRESETS = frozenset(
    {
        "hero_desktop",
        "hero_mobile",
        "card_thumbnail",
        "square",
        "original",
    }
)

ASPECT_RATIO_DISPLAY_PRESETS: dict[str, str] = {
    "16:9": "hero_desktop",
    "4:5": "hero_mobile",
    "4:3": "card_thumbnail",
    "1:1": "square",
    "any": "original",
    "auto": "original",
    "original": "original",
}


class DisplayPresetError(ValueError):
    """A governed media display preset is missing, stale, or unsupported."""


def resolve_requirement_display_preset(
    requirement: object | Mapping[str, Any] | None,
    *,
    requested_preset: str | None = None,
    semantic_role: str | None = None,
) -> str:
    """Resolve the only valid assignment preset for one media requirement.

    Current V2 requirements derive their preset exclusively from their exact
    aspect-ratio contract. A supplied preset is an optimistic assertion and must
    match that derived value. For a newly created legacy assignment, the
    established semantic-role default remains available; reading a historical
    assignment whose stored preset is genuinely absent uses the separate,
    role-independent ``original`` fallback below.
    """

    contract_version = _positive_int(_value(requirement, "contract_version"))
    if contract_version is not None and contract_version >= 2:
        aspect_ratio = _normalized(_value(requirement, "aspect_ratio"))
        preset = ASPECT_RATIO_DISPLAY_PRESETS.get(aspect_ratio)
        if preset is None:
            raise DisplayPresetError(
                "Current V2 Page Media requirement has a missing or unsupported "
                "aspect-ratio display preset contract."
            )
        if requested_preset is not None:
            requested = _supported_preset(requested_preset)
            if requested != preset:
                raise DisplayPresetError(
                    "Page-media display preset does not match the exact current "
                    "V2 requirement aspect ratio."
                )
        return preset

    if requested_preset is not None:
        return _supported_preset(requested_preset)
    if not _normalized(semantic_role):
        # A legacy requirement has no complete canonical preset contract. When
        # no assignment-specific semantic role is available, expose the same
        # role-independent, non-cropping fallback used for historical reads.
        return "original"
    return "hero_desktop" if _normalized(semantic_role) == "hero" else "card_thumbnail"


def effective_assignment_display_preset(
    assignment: object | Mapping[str, Any],
    *,
    requirement: object | Mapping[str, Any] | None,
    semantic_role: str | None = None,
) -> str:
    """Return a truthful effective preset for a stored assignment.

    A current V2 governed assignment must persist its canonical requirement
    preset. Legacy records may omit the field and remain readable through the
    role-independent, non-cropping ``original`` fallback.
    """

    stored_value = _value(assignment, "display_preset")
    stored_preset = (
        str(stored_value).strip().lower()
        if stored_value is not None and str(stored_value).strip()
        else None
    )
    contract_version = _positive_int(_value(requirement, "contract_version"))
    if contract_version is not None and contract_version >= 2 and stored_preset is None:
        raise DisplayPresetError(
            "Current V2 governed media assignment is missing its stored display preset."
        )
    if stored_preset is None:
        # Historical records without a durable preset use the one explicitly
        # non-cropping fallback shared by preview and export consumers.
        return "original"
    return resolve_requirement_display_preset(
        requirement,
        requested_preset=stored_preset,
        semantic_role=semantic_role,
    )


def _supported_preset(value: object) -> str:
    preset = _normalized(value)
    if preset not in DISPLAY_PRESETS:
        raise DisplayPresetError("Page-media display preset is unsupported.")
    return preset


def _value(record: object | Mapping[str, Any] | None, field: str) -> Any:
    if isinstance(record, Mapping):
        return record.get(field)
    return getattr(record, field, None) if record is not None else None


def _normalized(value: object) -> str:
    return str(value).strip().lower() if value is not None else ""


def _positive_int(value: object) -> int | None:
    return value if isinstance(value, int) and value >= 1 else None
