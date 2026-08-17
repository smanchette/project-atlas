from __future__ import annotations

import re
from typing import Any


KEY_PATTERN = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
INSTANCE_KEY_PATTERN = re.compile(r"^[a-z0-9]+(?:[-_:][a-z0-9]+)*$")
FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SECRET_REFERENCE_PATTERN = re.compile(
    r"^secret-ref://[a-z0-9][a-z0-9/_-]{2,239}$"
)
DESTINATION_REFERENCE_PATTERN = re.compile(
    r"^(?:destination|recipient-set|binding)-ref://[a-z0-9][a-z0-9/_-]{2,239}$"
)
POLICY_REFERENCE_PATTERN = re.compile(
    r"^policy-ref://[a-z0-9][a-z0-9/_-]{2,227}$"
)
SOURCE_REFERENCE_PATTERN = re.compile(
    r"^source-ref://[a-z0-9][a-z0-9/_-]{2,239}$"
)

_SECRET_KEY_MARKERS = (
    "api_key",
    "access_token",
    "refresh_token",
    "password",
    "private_key",
    "secret",
    "credential",
    "token",
)
_ALLOWED_SECRET_REFERENCE_KEYS = frozenset(
    {
        "provider_secret_reference",
        "transport_secret_reference",
        "adapter_secret_reference",
    }
)


def clean_text(value: str, label: str) -> str:
    cleaned = value.strip()
    if not cleaned or any(
        ord(character) < 32 or ord(character) == 127 for character in cleaned
    ):
        raise ValueError(f"{label} must be non-empty text without control characters")
    return cleaned


def validate_key(value: str, label: str, *, instance: bool = False) -> str:
    cleaned = value.strip().lower()
    pattern = INSTANCE_KEY_PATTERN if instance else KEY_PATTERN
    if not pattern.fullmatch(cleaned):
        raise ValueError(f"{label} must be a lowercase stable key")
    return cleaned


def reject_secret_configuration(
    value: Any,
    *,
    path: str = "configuration_payload",
) -> None:
    """Reject credential-shaped values while allowing exact opaque references."""

    if isinstance(value, dict):
        for key, nested in value.items():
            camel_separated = re.sub(
                r"(?<=[a-z0-9])(?=[A-Z])",
                "_",
                str(key).strip(),
            )
            normalized = re.sub(
                r"[^A-Za-z0-9]+", "_", camel_separated
            ).lower().strip("_")
            if normalized in _ALLOWED_SECRET_REFERENCE_KEYS:
                if nested is not None and (
                    not isinstance(nested, str)
                    or not SECRET_REFERENCE_PATTERN.fullmatch(nested)
                ):
                    raise ValueError(
                        f"{path}.{key} must be an opaque secret-manager reference, never a secret value"
                    )
                continue
            if any(marker in normalized for marker in _SECRET_KEY_MARKERS):
                raise ValueError(f"{path}.{key} may not contain credentials or secrets")
            reject_secret_configuration(nested, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            reject_secret_configuration(nested, path=f"{path}[{index}]")
