"""Provider-neutral Website Builder contracts.

This package is deliberately pure: persistence, FastAPI, AtlasOps360, and
provider SDKs belong outside this dependency boundary.
"""

from app.website_builder_core.contracts import (
    ATLAS_OWNED_FORM_MODES,
    FORM_DELIVERY_MODES,
    DeliveryAdapterContext,
    DeliveryAttemptResult,
    DeliveryRecipientSnapshot,
    FormDeliveryMode,
    FormDeliveryPresentation,
    FormRequestSecurityPolicy,
    NormalizedFormDefinition,
    NormalizedFormFieldDefinition,
    NormalizedSubmissionEnvelope,
    ProviderDeliveryContext,
    UNIVERSAL_ESTIMATE_FORM_DEFINITION,
    UNIVERSAL_FORM_REQUEST_SECURITY,
)
from app.website_builder_core.readiness import (
    FormDeliveryReadiness,
    FormDeliveryReadinessBlocker,
    FormDeliveryReadinessInput,
    evaluate_form_delivery_readiness,
)
from app.website_builder_core.registry import (
    ProviderDescriptor,
    ProviderRegistration,
    ProviderRegistry,
)

__all__ = [
    "ATLAS_OWNED_FORM_MODES",
    "FORM_DELIVERY_MODES",
    "DeliveryAdapterContext",
    "DeliveryAttemptResult",
    "DeliveryRecipientSnapshot",
    "FormDeliveryMode",
    "FormDeliveryPresentation",
    "FormDeliveryReadiness",
    "FormDeliveryReadinessBlocker",
    "FormDeliveryReadinessInput",
    "FormRequestSecurityPolicy",
    "NormalizedFormDefinition",
    "NormalizedFormFieldDefinition",
    "NormalizedSubmissionEnvelope",
    "ProviderDeliveryContext",
    "ProviderDescriptor",
    "ProviderRegistration",
    "ProviderRegistry",
    "UNIVERSAL_ESTIMATE_FORM_DEFINITION",
    "UNIVERSAL_FORM_REQUEST_SECURITY",
    "evaluate_form_delivery_readiness",
]
