"""Add universal Website form-delivery modes and minimal outbox evidence.

Revision ID: 20260817_0047
Revises: 20260815_0046
Create Date: 2026-08-17
"""

from __future__ import annotations

from alembic import op
import json
import re
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "20260817_0047"
down_revision = "20260815_0046"
branch_labels = None
depends_on = None


TABLES = (
    "websiteformdeliverymoderevision",
    "websiteformrecipientrevision",
    "formsubmissionenvelope",
    "formdeliveryoutbox",
    "formdeliveryattempt",
    "formdeliveryconfigurationaudit",
)

_INDEX_TABLE_PREFIXES = {
    "websiteformdeliverymoderevision": "fdm",
    "websiteformrecipientrevision": "frr",
    "formsubmissionenvelope": "fse",
    "formdeliveryoutbox": "fdo",
    "formdeliveryattempt": "fda",
    "formdeliveryconfigurationaudit": "fca",
}

_EXPECTED_COLUMNS = {
    "websiteformdeliverymoderevision": (
        "created_at", "updated_at", "id", "website_id",
        "form_component_configuration_id", "form_instance_key", "revision",
        "supersedes_delivery_mode_revision_id", "lifecycle_status", "mode",
        "enabled", "provider_key", "adapter_version", "destination_identity",
        "configuration_payload", "privacy_policy_reference",
        "consent_policy_reference", "retention_policy_reference",
        "abuse_policy_reference", "success_behavior", "failure_behavior",
        "idempotency_policy_reference", "audit_identity", "approval_identity",
        "approved_at", "activation_identity", "activated_at", "created_by",
        "updated_by", "integrity_fingerprint",
    ),
    "websiteformrecipientrevision": (
        "created_at", "updated_at", "id", "delivery_mode_revision_id",
        "website_id", "form_component_configuration_id", "form_instance_key",
        "recipient_key", "revision", "supersedes_recipient_revision_id",
        "email", "normalized_email", "label", "recipient_role", "enabled",
        "verification_status", "verified_at", "verified_by",
        "verification_method", "created_by", "updated_by",
        "integrity_fingerprint",
    ),
    "formsubmissionenvelope": (
        "id", "website_id", "form_component_configuration_id",
        "delivery_mode_revision_id", "submission_contract_version",
        "consent_accepted", "consent_version", "privacy_policy_reference",
        "retention_policy_reference", "abuse_policy_reference",
        "anti_spam_decision", "idempotency_digest", "received_at",
        "audit_identity", "request_identity", "source_page_identity",
        "destination_adapter_key", "secure_payload_reference",
        "encryption_key_reference", "expires_at", "integrity_fingerprint",
    ),
    "formdeliveryoutbox": (
        "created_at", "updated_at", "id", "envelope_id",
        "delivery_mode_revision_id", "adapter_key", "adapter_version",
        "destination_identity", "status", "attempt_count", "next_attempt_at",
        "last_safe_error_code", "state_version", "delivered_at", "failed_at",
        "expired_at",
    ),
    "formdeliveryattempt": (
        "id", "outbox_id", "attempt_number", "started_at", "completed_at",
        "outcome", "safe_error_code", "safe_provider_reference",
        "next_retry_at", "integrity_fingerprint",
    ),
    "formdeliveryconfigurationaudit": (
        "id", "delivery_mode_revision_id", "recipient_revision_id",
        "action_type", "actor", "rationale", "snapshot", "snapshot_hash",
        "created_at",
    ),
}

_NULLABLE_COLUMNS = {
    "websiteformdeliverymoderevision": frozenset({
        "supersedes_delivery_mode_revision_id", "provider_key",
        "adapter_version", "destination_identity", "privacy_policy_reference",
        "consent_policy_reference", "retention_policy_reference",
        "abuse_policy_reference", "success_behavior", "failure_behavior",
        "idempotency_policy_reference", "approval_identity", "approved_at",
        "activation_identity", "activated_at",
    }),
    "websiteformrecipientrevision": frozenset({
        "supersedes_recipient_revision_id", "label", "verified_at",
        "verified_by", "verification_method",
    }),
    "formsubmissionenvelope": frozenset({
        "consent_accepted", "consent_version", "source_page_identity",
        "secure_payload_reference", "encryption_key_reference", "expires_at",
    }),
    "formdeliveryoutbox": frozenset({
        "next_attempt_at", "last_safe_error_code", "delivered_at", "failed_at",
        "expired_at",
    }),
    "formdeliveryattempt": frozenset({
        "safe_error_code", "safe_provider_reference", "next_retry_at",
    }),
    "formdeliveryconfigurationaudit": frozenset({
        "delivery_mode_revision_id", "recipient_revision_id",
    }),
}

_EXPECTED_FOREIGN_KEYS = {
    "websiteformdeliverymoderevision": {
        (("website_id",), "website", ("id",)),
        (("form_component_configuration_id",), "websitethemecomponentconfiguration", ("id",)),
        (("supersedes_delivery_mode_revision_id",), "websiteformdeliverymoderevision", ("id",)),
    },
    "websiteformrecipientrevision": {
        (("delivery_mode_revision_id",), "websiteformdeliverymoderevision", ("id",)),
        (("website_id",), "website", ("id",)),
        (("form_component_configuration_id",), "websitethemecomponentconfiguration", ("id",)),
        (("supersedes_recipient_revision_id",), "websiteformrecipientrevision", ("id",)),
    },
    "formsubmissionenvelope": {
        (("website_id",), "website", ("id",)),
        (("form_component_configuration_id",), "websitethemecomponentconfiguration", ("id",)),
        (("delivery_mode_revision_id",), "websiteformdeliverymoderevision", ("id",)),
    },
    "formdeliveryoutbox": {
        (("envelope_id",), "formsubmissionenvelope", ("id",)),
        (("delivery_mode_revision_id",), "websiteformdeliverymoderevision", ("id",)),
    },
    "formdeliveryattempt": {
        (("outbox_id",), "formdeliveryoutbox", ("id",)),
    },
    "formdeliveryconfigurationaudit": {
        (("delivery_mode_revision_id",), "websiteformdeliverymoderevision", ("id",)),
        (("recipient_revision_id",), "websiteformrecipientrevision", ("id",)),
    },
}

_EXPECTED_FOREIGN_KEY_NAMES = {
    "websiteformdeliverymoderevision": {
        (("website_id",), "website", ("id",)): "fk_fdm_website",
        (("form_component_configuration_id",), "websitethemecomponentconfiguration", ("id",)): "fk_fdm_component",
        (("supersedes_delivery_mode_revision_id",), "websiteformdeliverymoderevision", ("id",)): "fk_fdm_predecessor",
    },
    "websiteformrecipientrevision": {
        (("delivery_mode_revision_id",), "websiteformdeliverymoderevision", ("id",)): "fk_frr_mode",
        (("website_id",), "website", ("id",)): "fk_frr_website",
        (("form_component_configuration_id",), "websitethemecomponentconfiguration", ("id",)): "fk_frr_component",
        (("supersedes_recipient_revision_id",), "websiteformrecipientrevision", ("id",)): "fk_frr_predecessor",
    },
    "formsubmissionenvelope": {
        (("website_id",), "website", ("id",)): "fk_fse_website",
        (("form_component_configuration_id",), "websitethemecomponentconfiguration", ("id",)): "fk_fse_component",
        (("delivery_mode_revision_id",), "websiteformdeliverymoderevision", ("id",)): "fk_fse_mode",
    },
    "formdeliveryoutbox": {
        (("envelope_id",), "formsubmissionenvelope", ("id",)): "fk_fdo_envelope",
        (("delivery_mode_revision_id",), "websiteformdeliverymoderevision", ("id",)): "fk_fdo_mode",
    },
    "formdeliveryattempt": {
        (("outbox_id",), "formdeliveryoutbox", ("id",)): "fk_fda_outbox",
    },
    "formdeliveryconfigurationaudit": {
        (("delivery_mode_revision_id",), "websiteformdeliverymoderevision", ("id",)): "fk_fca_mode",
        (("recipient_revision_id",), "websiteformrecipientrevision", ("id",)): "fk_fca_recipient",
    },
}

_EXPECTED_CHECKS = {
    "websiteformdeliverymoderevision": {
        "ck_formdeliverymode_lifecycle", "ck_formdeliverymode_mode",
        "ck_formdeliverymode_revision", "ck_formdeliverymode_lineage",
        "ck_formdeliverymode_not_self", "ck_formdeliverymode_approval_pair",
        "ck_formdeliverymode_approval_evidence",
        "ck_formdeliverymode_activation_pair",
        "ck_formdeliverymode_active_evidence",
        "ck_formdeliverymode_disabled_empty", "ck_formdeliverymode_enabled_state",
        "ck_formdeliverymode_fingerprint",
    },
    "websiteformrecipientrevision": {
        "ck_formrecipient_role", "ck_formrecipient_verification",
        "ck_formrecipient_revision", "ck_formrecipient_lineage",
        "ck_formrecipient_not_self", "ck_formrecipient_verification_evidence",
        "ck_formrecipient_fingerprint",
    },
    "formsubmissionenvelope": {
        "ck_formenvelope_contract_version", "ck_formenvelope_idempotency_digest",
        "ck_formenvelope_payload_pair", "ck_formenvelope_expiry",
        "ck_formenvelope_fingerprint",
    },
    "formdeliveryoutbox": {
        "ck_formoutbox_status", "ck_formoutbox_counts",
        "ck_formoutbox_delivered_evidence", "ck_formoutbox_failed_evidence",
        "ck_formoutbox_expired_evidence", "ck_formoutbox_retry_evidence",
    },
    "formdeliveryattempt": {
        "ck_formattempt_number", "ck_formattempt_outcome",
        "ck_formattempt_chronology", "ck_formattempt_retry_evidence",
        "ck_formattempt_fingerprint",
    },
    "formdeliveryconfigurationaudit": {
        "ck_formdeliveryaudit_exact_target", "ck_formdeliveryaudit_action",
        "ck_formdeliveryaudit_action_target", "ck_formdeliveryaudit_hash",
    },
}

_EXPECTED_CHECK_SQL = {
    "websiteformdeliverymoderevision": {
        "ck_formdeliverymode_lifecycle": "lifecycle_status IN ('draft','approved','active','retired')",
        "ck_formdeliverymode_mode": "mode IN ('disabled','atlas_email','provider_owned','atlasops360_native','external_adapter')",
        "ck_formdeliverymode_revision": "revision >= 1",
        "ck_formdeliverymode_lineage": "(revision = 1 AND supersedes_delivery_mode_revision_id IS NULL) OR (revision > 1 AND supersedes_delivery_mode_revision_id IS NOT NULL)",
        "ck_formdeliverymode_not_self": "supersedes_delivery_mode_revision_id IS NULL OR supersedes_delivery_mode_revision_id != id",
        "ck_formdeliverymode_approval_pair": "(approval_identity IS NULL AND approved_at IS NULL) OR (approval_identity IS NOT NULL AND approved_at IS NOT NULL)",
        "ck_formdeliverymode_approval_evidence": "lifecycle_status NOT IN ('approved','active') OR (approval_identity IS NOT NULL AND approved_at IS NOT NULL)",
        "ck_formdeliverymode_activation_pair": "(activation_identity IS NULL AND activated_at IS NULL) OR (activation_identity IS NOT NULL AND activated_at IS NOT NULL)",
        "ck_formdeliverymode_active_evidence": "lifecycle_status != 'active' OR (activation_identity IS NOT NULL AND activated_at IS NOT NULL)",
        "ck_formdeliverymode_disabled_empty": "mode != 'disabled' OR (enabled = false AND provider_key IS NULL AND adapter_version IS NULL AND destination_identity IS NULL AND privacy_policy_reference IS NULL AND consent_policy_reference IS NULL AND retention_policy_reference IS NULL AND abuse_policy_reference IS NULL AND success_behavior IS NULL AND failure_behavior IS NULL AND idempotency_policy_reference IS NULL)",
        "ck_formdeliverymode_enabled_state": "enabled = false OR (mode != 'disabled' AND lifecycle_status = 'active')",
        "ck_formdeliverymode_fingerprint": "length(integrity_fingerprint) = 64 AND integrity_fingerprint = lower(integrity_fingerprint)",
    },
    "websiteformrecipientrevision": {
        "ck_formrecipient_role": "recipient_role IN ('primary','secondary')",
        "ck_formrecipient_verification": "verification_status IN ('unverified','verified','revoked')",
        "ck_formrecipient_revision": "revision >= 1",
        "ck_formrecipient_lineage": "(revision = 1 AND supersedes_recipient_revision_id IS NULL) OR (revision > 1 AND supersedes_recipient_revision_id IS NOT NULL)",
        "ck_formrecipient_not_self": "supersedes_recipient_revision_id IS NULL OR supersedes_recipient_revision_id != id",
        "ck_formrecipient_verification_evidence": "(verification_status = 'unverified' AND verified_at IS NULL AND verified_by IS NULL AND verification_method IS NULL) OR (verification_status IN ('verified','revoked') AND verified_at IS NOT NULL AND verified_by IS NOT NULL AND verification_method IS NOT NULL)",
        "ck_formrecipient_fingerprint": "length(integrity_fingerprint) = 64 AND integrity_fingerprint = lower(integrity_fingerprint)",
    },
    "formsubmissionenvelope": {
        "ck_formenvelope_contract_version": "submission_contract_version >= 1",
        "ck_formenvelope_idempotency_digest": "length(idempotency_digest) = 64 AND idempotency_digest = lower(idempotency_digest)",
        "ck_formenvelope_payload_pair": "(secure_payload_reference IS NULL AND encryption_key_reference IS NULL) OR (secure_payload_reference IS NOT NULL AND encryption_key_reference IS NOT NULL)",
        "ck_formenvelope_expiry": "expires_at IS NULL OR expires_at >= received_at",
        "ck_formenvelope_fingerprint": "length(integrity_fingerprint) = 64 AND integrity_fingerprint = lower(integrity_fingerprint)",
    },
    "formdeliveryoutbox": {
        "ck_formoutbox_status": "status IN ('queued','processing','retrying','delivered','terminal_failed','expired')",
        "ck_formoutbox_counts": "attempt_count >= 0 AND state_version >= 1",
        "ck_formoutbox_delivered_evidence": "(status = 'delivered' AND delivered_at IS NOT NULL) OR (status != 'delivered' AND delivered_at IS NULL)",
        "ck_formoutbox_failed_evidence": "(status = 'terminal_failed' AND failed_at IS NOT NULL) OR (status != 'terminal_failed' AND failed_at IS NULL)",
        "ck_formoutbox_expired_evidence": "(status = 'expired' AND expired_at IS NOT NULL) OR (status != 'expired' AND expired_at IS NULL)",
        "ck_formoutbox_retry_evidence": "(status = 'retrying' AND next_attempt_at IS NOT NULL) OR (status != 'retrying' AND next_attempt_at IS NULL)",
    },
    "formdeliveryattempt": {
        "ck_formattempt_number": "attempt_number >= 1",
        "ck_formattempt_outcome": "outcome IN ('delivered','transient_failure','permanent_failure')",
        "ck_formattempt_chronology": "completed_at >= started_at",
        "ck_formattempt_retry_evidence": "(outcome = 'transient_failure' AND next_retry_at IS NOT NULL) OR (outcome != 'transient_failure' AND next_retry_at IS NULL)",
        "ck_formattempt_fingerprint": "length(integrity_fingerprint) = 64 AND integrity_fingerprint = lower(integrity_fingerprint)",
    },
    "formdeliveryconfigurationaudit": {
        "ck_formdeliveryaudit_exact_target": "(CASE WHEN delivery_mode_revision_id IS NULL THEN 0 ELSE 1 END + CASE WHEN recipient_revision_id IS NULL THEN 0 ELSE 1 END) = 1",
        "ck_formdeliveryaudit_action": "action_type IN ('mode_revision_created','mode_revision_approved','mode_revision_activated','mode_revision_retired','recipient_revision_created','recipient_verified','recipient_revoked')",
        "ck_formdeliveryaudit_action_target": "(delivery_mode_revision_id IS NOT NULL AND recipient_revision_id IS NULL AND action_type LIKE 'mode_revision_%') OR (recipient_revision_id IS NOT NULL AND delivery_mode_revision_id IS NULL AND (action_type LIKE 'recipient_revision_%' OR action_type IN ('recipient_verified','recipient_revoked')))",
        "ck_formdeliveryaudit_hash": "length(snapshot_hash) = 64 AND snapshot_hash = lower(snapshot_hash)",
    },
}

_EXPECTED_UNIQUES = {
    "websiteformdeliverymoderevision": {
        "uq_formdeliverymode_scope_revision": ("website_id", "form_instance_key", "revision"),
        "uq_formdeliverymode_successor": ("supersedes_delivery_mode_revision_id",),
    },
    "websiteformrecipientrevision": {
        "uq_formrecipient_scope_revision": ("website_id", "form_instance_key", "recipient_key", "revision"),
        "uq_formrecipient_successor": ("supersedes_recipient_revision_id",),
    },
    "formsubmissionenvelope": {
        "uq_formenvelope_idempotency": ("website_id", "form_component_configuration_id", "idempotency_digest"),
    },
    "formdeliveryoutbox": {"uq_formoutbox_envelope": ("envelope_id",)},
    "formdeliveryattempt": {"uq_formattempt_outbox_number": ("outbox_id", "attempt_number")},
    "formdeliveryconfigurationaudit": {"uq_formdeliveryaudit_hash": ("snapshot_hash",)},
}

_INDEX_COLUMNS = {
    "websiteformdeliverymoderevision": (
        "website_id", "form_component_configuration_id", "form_instance_key",
        "supersedes_delivery_mode_revision_id", "lifecycle_status", "mode",
        "provider_key", "integrity_fingerprint",
    ),
    "websiteformrecipientrevision": (
        "delivery_mode_revision_id", "website_id",
        "form_component_configuration_id", "form_instance_key", "recipient_key",
        "supersedes_recipient_revision_id", "normalized_email", "recipient_role",
        "verification_status", "integrity_fingerprint",
    ),
    "formsubmissionenvelope": (
        "website_id", "form_component_configuration_id", "delivery_mode_revision_id",
        "idempotency_digest", "received_at", "destination_adapter_key",
        "expires_at", "integrity_fingerprint",
    ),
    "formdeliveryoutbox": (
        "envelope_id", "delivery_mode_revision_id", "adapter_key", "status",
        "next_attempt_at",
    ),
    "formdeliveryattempt": ("outbox_id", "outcome", "integrity_fingerprint"),
    "formdeliveryconfigurationaudit": (
        "delivery_mode_revision_id", "recipient_revision_id", "action_type",
        "snapshot_hash", "created_at",
    ),
}

_INTEGER_COLUMNS = {
    "websiteformdeliverymoderevision": {
        "id", "website_id", "form_component_configuration_id", "revision",
        "supersedes_delivery_mode_revision_id",
    },
    "websiteformrecipientrevision": {
        "id", "delivery_mode_revision_id", "website_id",
        "form_component_configuration_id", "revision",
        "supersedes_recipient_revision_id",
    },
    "formsubmissionenvelope": {
        "id", "website_id", "form_component_configuration_id",
        "delivery_mode_revision_id", "submission_contract_version",
    },
    "formdeliveryoutbox": {
        "id", "envelope_id", "delivery_mode_revision_id", "attempt_count",
        "state_version",
    },
    "formdeliveryattempt": {"id", "outbox_id", "attempt_number"},
    "formdeliveryconfigurationaudit": {
        "id", "delivery_mode_revision_id", "recipient_revision_id",
    },
}

_BOOLEAN_COLUMNS = {
    "websiteformdeliverymoderevision": {"enabled"},
    "websiteformrecipientrevision": {"enabled"},
    "formsubmissionenvelope": {"consent_accepted"},
    "formdeliveryoutbox": set(),
    "formdeliveryattempt": set(),
    "formdeliveryconfigurationaudit": set(),
}

_DATETIME_COLUMNS = {
    "websiteformdeliverymoderevision": {
        "created_at", "updated_at", "approved_at", "activated_at",
    },
    "websiteformrecipientrevision": {"created_at", "updated_at", "verified_at"},
    "formsubmissionenvelope": {"received_at", "expires_at"},
    "formdeliveryoutbox": {
        "created_at", "updated_at", "next_attempt_at", "delivered_at",
        "failed_at", "expired_at",
    },
    "formdeliveryattempt": {"started_at", "completed_at", "next_retry_at"},
    "formdeliveryconfigurationaudit": {"created_at"},
}

_JSON_COLUMNS = {
    "websiteformdeliverymoderevision": {"configuration_payload"},
    "websiteformrecipientrevision": set(),
    "formsubmissionenvelope": set(),
    "formdeliveryoutbox": set(),
    "formdeliveryattempt": set(),
    "formdeliveryconfigurationaudit": {"snapshot"},
}

_STRING_LENGTHS = {
    "websiteformdeliverymoderevision": {
        "form_instance_key": 120, "lifecycle_status": 24, "mode": 32,
        "provider_key": 120, "adapter_version": 80,
        "destination_identity": 1000, "privacy_policy_reference": 1000,
        "consent_policy_reference": 240, "retention_policy_reference": 240,
        "abuse_policy_reference": 240, "success_behavior": 1000,
        "failure_behavior": 1000, "idempotency_policy_reference": 240,
        "audit_identity": 160, "approval_identity": 160,
        "activation_identity": 160, "created_by": 160, "updated_by": 160,
        "integrity_fingerprint": 64,
    },
    "websiteformrecipientrevision": {
        "form_instance_key": 120, "recipient_key": 120, "email": 320,
        "normalized_email": 320, "label": 160, "recipient_role": 16,
        "verification_status": 20, "verified_by": 160,
        "verification_method": 120, "created_by": 160, "updated_by": 160,
        "integrity_fingerprint": 64,
    },
    "formsubmissionenvelope": {
        "consent_version": 160, "privacy_policy_reference": 1000,
        "retention_policy_reference": 240, "abuse_policy_reference": 240,
        "anti_spam_decision": 120, "idempotency_digest": 64,
        "audit_identity": 160, "request_identity": 240,
        "source_page_identity": 240, "destination_adapter_key": 120,
        "secure_payload_reference": 500, "encryption_key_reference": 260,
        "integrity_fingerprint": 64,
    },
    "formdeliveryoutbox": {
        "adapter_key": 120, "adapter_version": 80,
        "destination_identity": 1000, "status": 24,
        "last_safe_error_code": 120,
    },
    "formdeliveryattempt": {
        "outcome": 24, "safe_error_code": 120,
        "safe_provider_reference": 240, "integrity_fingerprint": 64,
    },
    "formdeliveryconfigurationaudit": {
        "action_type": 48, "actor": 160, "rationale": 2000,
        "snapshot_hash": 64,
    },
}


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    precreated = existing.intersection(TABLES)
    if precreated:
        raise RuntimeError(
            "Universal form-delivery migration refuses pre-created governed tables."
        )

    op.create_table(
        "websiteformdeliverymoderevision",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("website_id", sa.Integer(), nullable=False),
        sa.Column("form_component_configuration_id", sa.Integer(), nullable=False),
        sa.Column("form_instance_key", sa.String(length=120), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("supersedes_delivery_mode_revision_id", sa.Integer(), nullable=True),
        sa.Column("lifecycle_status", sa.String(length=24), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("provider_key", sa.String(length=120), nullable=True),
        sa.Column("adapter_version", sa.String(length=80), nullable=True),
        sa.Column("destination_identity", sa.String(length=1000), nullable=True),
        sa.Column("configuration_payload", sa.JSON(), nullable=False),
        sa.Column("privacy_policy_reference", sa.String(length=1000), nullable=True),
        sa.Column("consent_policy_reference", sa.String(length=240), nullable=True),
        sa.Column("retention_policy_reference", sa.String(length=240), nullable=True),
        sa.Column("abuse_policy_reference", sa.String(length=240), nullable=True),
        sa.Column("success_behavior", sa.String(length=1000), nullable=True),
        sa.Column("failure_behavior", sa.String(length=1000), nullable=True),
        sa.Column("idempotency_policy_reference", sa.String(length=240), nullable=True),
        sa.Column("audit_identity", sa.String(length=160), nullable=False),
        sa.Column("approval_identity", sa.String(length=160), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activation_identity", sa.String(length=160), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=160), nullable=False),
        sa.Column("updated_by", sa.String(length=160), nullable=False),
        sa.Column("integrity_fingerprint", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "lifecycle_status IN ('draft','approved','active','retired')",
            name="ck_formdeliverymode_lifecycle",
        ),
        sa.CheckConstraint(
            "mode IN ('disabled','atlas_email','provider_owned',"
            "'atlasops360_native','external_adapter')",
            name="ck_formdeliverymode_mode",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_formdeliverymode_revision"),
        sa.CheckConstraint(
            "(revision = 1 AND supersedes_delivery_mode_revision_id IS NULL) "
            "OR (revision > 1 AND supersedes_delivery_mode_revision_id IS NOT NULL)",
            name="ck_formdeliverymode_lineage",
        ),
        sa.CheckConstraint(
            "supersedes_delivery_mode_revision_id IS NULL "
            "OR supersedes_delivery_mode_revision_id != id",
            name="ck_formdeliverymode_not_self",
        ),
        sa.CheckConstraint(
            "(approval_identity IS NULL AND approved_at IS NULL) "
            "OR (approval_identity IS NOT NULL AND approved_at IS NOT NULL)",
            name="ck_formdeliverymode_approval_pair",
        ),
        sa.CheckConstraint(
            "lifecycle_status NOT IN ('approved','active') "
            "OR (approval_identity IS NOT NULL AND approved_at IS NOT NULL)",
            name="ck_formdeliverymode_approval_evidence",
        ),
        sa.CheckConstraint(
            "(activation_identity IS NULL AND activated_at IS NULL) "
            "OR (activation_identity IS NOT NULL AND activated_at IS NOT NULL)",
            name="ck_formdeliverymode_activation_pair",
        ),
        sa.CheckConstraint(
            "lifecycle_status != 'active' "
            "OR (activation_identity IS NOT NULL AND activated_at IS NOT NULL)",
            name="ck_formdeliverymode_active_evidence",
        ),
        sa.CheckConstraint(
            "mode != 'disabled' OR (enabled = false AND provider_key IS NULL "
            "AND adapter_version IS NULL AND destination_identity IS NULL "
            "AND privacy_policy_reference IS NULL "
            "AND consent_policy_reference IS NULL "
            "AND retention_policy_reference IS NULL "
            "AND abuse_policy_reference IS NULL "
            "AND success_behavior IS NULL AND failure_behavior IS NULL "
            "AND idempotency_policy_reference IS NULL)",
            name="ck_formdeliverymode_disabled_empty",
        ),
        sa.CheckConstraint(
            "enabled = false OR (mode != 'disabled' AND lifecycle_status = 'active')",
            name="ck_formdeliverymode_enabled_state",
        ),
        sa.CheckConstraint(
            "length(integrity_fingerprint) = 64 "
            "AND integrity_fingerprint = lower(integrity_fingerprint)",
            name="ck_formdeliverymode_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["website_id"], ["website.id"], name="fk_fdm_website"
        ),
        sa.ForeignKeyConstraint(
            ["form_component_configuration_id"],
            ["websitethemecomponentconfiguration.id"],
            name="fk_fdm_component",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_delivery_mode_revision_id"],
            ["websiteformdeliverymoderevision.id"],
            name="fk_fdm_predecessor",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "website_id",
            "form_instance_key",
            "revision",
            name="uq_formdeliverymode_scope_revision",
        ),
        sa.UniqueConstraint(
            "supersedes_delivery_mode_revision_id",
            name="uq_formdeliverymode_successor",
        ),
    )
    for column in (
        "website_id",
        "form_component_configuration_id",
        "form_instance_key",
        "supersedes_delivery_mode_revision_id",
        "lifecycle_status",
        "mode",
        "provider_key",
        "integrity_fingerprint",
    ):
        _index("websiteformdeliverymoderevision", column)

    op.create_table(
        "websiteformrecipientrevision",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("delivery_mode_revision_id", sa.Integer(), nullable=False),
        sa.Column("website_id", sa.Integer(), nullable=False),
        sa.Column("form_component_configuration_id", sa.Integer(), nullable=False),
        sa.Column("form_instance_key", sa.String(length=120), nullable=False),
        sa.Column("recipient_key", sa.String(length=120), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("supersedes_recipient_revision_id", sa.Integer(), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("normalized_email", sa.String(length=320), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=True),
        sa.Column("recipient_role", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("verification_status", sa.String(length=20), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_by", sa.String(length=160), nullable=True),
        sa.Column("verification_method", sa.String(length=120), nullable=True),
        sa.Column("created_by", sa.String(length=160), nullable=False),
        sa.Column("updated_by", sa.String(length=160), nullable=False),
        sa.Column("integrity_fingerprint", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "recipient_role IN ('primary','secondary')",
            name="ck_formrecipient_role",
        ),
        sa.CheckConstraint(
            "verification_status IN ('unverified','verified','revoked')",
            name="ck_formrecipient_verification",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_formrecipient_revision"),
        sa.CheckConstraint(
            "(revision = 1 AND supersedes_recipient_revision_id IS NULL) "
            "OR (revision > 1 AND supersedes_recipient_revision_id IS NOT NULL)",
            name="ck_formrecipient_lineage",
        ),
        sa.CheckConstraint(
            "supersedes_recipient_revision_id IS NULL "
            "OR supersedes_recipient_revision_id != id",
            name="ck_formrecipient_not_self",
        ),
        sa.CheckConstraint(
            "(verification_status = 'unverified' AND verified_at IS NULL "
            "AND verified_by IS NULL AND verification_method IS NULL) "
            "OR (verification_status IN ('verified','revoked') "
            "AND verified_at IS NOT NULL AND verified_by IS NOT NULL "
            "AND verification_method IS NOT NULL)",
            name="ck_formrecipient_verification_evidence",
        ),
        sa.CheckConstraint(
            "length(integrity_fingerprint) = 64 "
            "AND integrity_fingerprint = lower(integrity_fingerprint)",
            name="ck_formrecipient_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["delivery_mode_revision_id"],
            ["websiteformdeliverymoderevision.id"],
            name="fk_frr_mode",
        ),
        sa.ForeignKeyConstraint(
            ["website_id"], ["website.id"], name="fk_frr_website"
        ),
        sa.ForeignKeyConstraint(
            ["form_component_configuration_id"],
            ["websitethemecomponentconfiguration.id"],
            name="fk_frr_component",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_recipient_revision_id"],
            ["websiteformrecipientrevision.id"],
            name="fk_frr_predecessor",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "website_id",
            "form_instance_key",
            "recipient_key",
            "revision",
            name="uq_formrecipient_scope_revision",
        ),
        sa.UniqueConstraint(
            "supersedes_recipient_revision_id",
            name="uq_formrecipient_successor",
        ),
    )
    for column in (
        "delivery_mode_revision_id",
        "website_id",
        "form_component_configuration_id",
        "form_instance_key",
        "recipient_key",
        "supersedes_recipient_revision_id",
        "normalized_email",
        "recipient_role",
        "verification_status",
        "integrity_fingerprint",
    ):
        _index("websiteformrecipientrevision", column)

    op.create_table(
        "formsubmissionenvelope",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("website_id", sa.Integer(), nullable=False),
        sa.Column("form_component_configuration_id", sa.Integer(), nullable=False),
        sa.Column("delivery_mode_revision_id", sa.Integer(), nullable=False),
        sa.Column("submission_contract_version", sa.Integer(), nullable=False),
        sa.Column("consent_accepted", sa.Boolean(), nullable=True),
        sa.Column("consent_version", sa.String(length=160), nullable=True),
        sa.Column("privacy_policy_reference", sa.String(length=1000), nullable=False),
        sa.Column("retention_policy_reference", sa.String(length=240), nullable=False),
        sa.Column("abuse_policy_reference", sa.String(length=240), nullable=False),
        sa.Column("anti_spam_decision", sa.String(length=120), nullable=False),
        sa.Column("idempotency_digest", sa.String(length=64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("audit_identity", sa.String(length=160), nullable=False),
        sa.Column("request_identity", sa.String(length=240), nullable=False),
        sa.Column("source_page_identity", sa.String(length=240), nullable=True),
        sa.Column("destination_adapter_key", sa.String(length=120), nullable=False),
        sa.Column("secure_payload_reference", sa.String(length=500), nullable=True),
        sa.Column("encryption_key_reference", sa.String(length=260), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("integrity_fingerprint", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "submission_contract_version >= 1",
            name="ck_formenvelope_contract_version",
        ),
        sa.CheckConstraint(
            "length(idempotency_digest) = 64 "
            "AND idempotency_digest = lower(idempotency_digest)",
            name="ck_formenvelope_idempotency_digest",
        ),
        sa.CheckConstraint(
            "(secure_payload_reference IS NULL AND encryption_key_reference IS NULL) "
            "OR (secure_payload_reference IS NOT NULL "
            "AND encryption_key_reference IS NOT NULL)",
            name="ck_formenvelope_payload_pair",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at >= received_at",
            name="ck_formenvelope_expiry",
        ),
        sa.CheckConstraint(
            "length(integrity_fingerprint) = 64 "
            "AND integrity_fingerprint = lower(integrity_fingerprint)",
            name="ck_formenvelope_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["website_id"], ["website.id"], name="fk_fse_website"
        ),
        sa.ForeignKeyConstraint(
            ["form_component_configuration_id"],
            ["websitethemecomponentconfiguration.id"],
            name="fk_fse_component",
        ),
        sa.ForeignKeyConstraint(
            ["delivery_mode_revision_id"],
            ["websiteformdeliverymoderevision.id"],
            name="fk_fse_mode",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "website_id",
            "form_component_configuration_id",
            "idempotency_digest",
            name="uq_formenvelope_idempotency",
        ),
    )
    for column in (
        "website_id",
        "form_component_configuration_id",
        "delivery_mode_revision_id",
        "idempotency_digest",
        "received_at",
        "destination_adapter_key",
        "expires_at",
        "integrity_fingerprint",
    ):
        _index("formsubmissionenvelope", column)

    op.create_table(
        "formdeliveryoutbox",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("envelope_id", sa.Integer(), nullable=False),
        sa.Column("delivery_mode_revision_id", sa.Integer(), nullable=False),
        sa.Column("adapter_key", sa.String(length=120), nullable=False),
        sa.Column("adapter_version", sa.String(length=80), nullable=False),
        sa.Column("destination_identity", sa.String(length=1000), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_safe_error_code", sa.String(length=120), nullable=True),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued','processing','retrying','delivered',"
            "'terminal_failed','expired')",
            name="ck_formoutbox_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND state_version >= 1",
            name="ck_formoutbox_counts",
        ),
        sa.CheckConstraint(
            "(status = 'delivered' AND delivered_at IS NOT NULL) OR "
            "(status != 'delivered' AND delivered_at IS NULL)",
            name="ck_formoutbox_delivered_evidence",
        ),
        sa.CheckConstraint(
            "(status = 'terminal_failed' AND failed_at IS NOT NULL) OR "
            "(status != 'terminal_failed' AND failed_at IS NULL)",
            name="ck_formoutbox_failed_evidence",
        ),
        sa.CheckConstraint(
            "(status = 'expired' AND expired_at IS NOT NULL) OR "
            "(status != 'expired' AND expired_at IS NULL)",
            name="ck_formoutbox_expired_evidence",
        ),
        sa.CheckConstraint(
            "(status = 'retrying' AND next_attempt_at IS NOT NULL) OR "
            "(status != 'retrying' AND next_attempt_at IS NULL)",
            name="ck_formoutbox_retry_evidence",
        ),
        sa.ForeignKeyConstraint(
            ["envelope_id"],
            ["formsubmissionenvelope.id"],
            name="fk_fdo_envelope",
        ),
        sa.ForeignKeyConstraint(
            ["delivery_mode_revision_id"],
            ["websiteformdeliverymoderevision.id"],
            name="fk_fdo_mode",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("envelope_id", name="uq_formoutbox_envelope"),
    )
    for column in (
        "envelope_id",
        "delivery_mode_revision_id",
        "adapter_key",
        "status",
        "next_attempt_at",
    ):
        _index("formdeliveryoutbox", column)

    op.create_table(
        "formdeliveryattempt",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("outbox_id", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("safe_error_code", sa.String(length=120), nullable=True),
        sa.Column("safe_provider_reference", sa.String(length=240), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("integrity_fingerprint", sa.String(length=64), nullable=False),
        sa.CheckConstraint("attempt_number >= 1", name="ck_formattempt_number"),
        sa.CheckConstraint(
            "outcome IN ('delivered','transient_failure','permanent_failure')",
            name="ck_formattempt_outcome",
        ),
        sa.CheckConstraint(
            "completed_at >= started_at",
            name="ck_formattempt_chronology",
        ),
        sa.CheckConstraint(
            "(outcome = 'transient_failure' AND next_retry_at IS NOT NULL) OR "
            "(outcome != 'transient_failure' AND next_retry_at IS NULL)",
            name="ck_formattempt_retry_evidence",
        ),
        sa.CheckConstraint(
            "length(integrity_fingerprint) = 64 "
            "AND integrity_fingerprint = lower(integrity_fingerprint)",
            name="ck_formattempt_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["outbox_id"], ["formdeliveryoutbox.id"], name="fk_fda_outbox"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "outbox_id",
            "attempt_number",
            name="uq_formattempt_outbox_number",
        ),
    )
    for column in ("outbox_id", "outcome", "integrity_fingerprint"):
        _index("formdeliveryattempt", column)

    op.create_table(
        "formdeliveryconfigurationaudit",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("delivery_mode_revision_id", sa.Integer(), nullable=True),
        sa.Column("recipient_revision_id", sa.Integer(), nullable=True),
        sa.Column("action_type", sa.String(length=48), nullable=False),
        sa.Column("actor", sa.String(length=160), nullable=False),
        sa.Column("rationale", sa.String(length=2000), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(CASE WHEN delivery_mode_revision_id IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN recipient_revision_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="ck_formdeliveryaudit_exact_target",
        ),
        sa.CheckConstraint(
            "action_type IN ('mode_revision_created','mode_revision_approved',"
            "'mode_revision_activated','mode_revision_retired',"
            "'recipient_revision_created','recipient_verified','recipient_revoked')",
            name="ck_formdeliveryaudit_action",
        ),
        sa.CheckConstraint(
            "(delivery_mode_revision_id IS NOT NULL AND recipient_revision_id IS NULL "
            "AND action_type LIKE 'mode_revision_%') OR "
            "(recipient_revision_id IS NOT NULL AND delivery_mode_revision_id IS NULL "
            "AND (action_type LIKE 'recipient_revision_%' "
            "OR action_type IN ('recipient_verified','recipient_revoked')))",
            name="ck_formdeliveryaudit_action_target",
        ),
        sa.CheckConstraint(
            "length(snapshot_hash) = 64 AND snapshot_hash = lower(snapshot_hash)",
            name="ck_formdeliveryaudit_hash",
        ),
        sa.ForeignKeyConstraint(
            ["delivery_mode_revision_id"],
            ["websiteformdeliverymoderevision.id"],
            name="fk_fca_mode",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_revision_id"],
            ["websiteformrecipientrevision.id"],
            name="fk_fca_recipient",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_hash", name="uq_formdeliveryaudit_hash"),
    )
    for column in (
        "delivery_mode_revision_id",
        "recipient_revision_id",
        "action_type",
        "snapshot_hash",
        "created_at",
    ):
        _index("formdeliveryconfigurationaudit", column)

    _assert_exact_owned_shape(op.get_bind())


def downgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    if existing.intersection(TABLES) != set(TABLES):
        raise RuntimeError(
            "Cannot downgrade universal form-delivery migration because its "
            "owned table set is partial or missing."
        )
    if bind.dialect.name == "postgresql":
        # One deterministic statement prevents inserts between the all-table
        # empty preflight and the first DROP. The Alembic transaction retains
        # these locks through the complete downgrade.
        bind.execute(
            text(
                "LOCK TABLE "
                + ", ".join(TABLES)
                + " IN ACCESS EXCLUSIVE MODE"
            )
        )
    _assert_exact_owned_shape(bind)
    populated = [
        table
        for table in TABLES
        if bind.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
    ]
    if populated:
        raise RuntimeError(
            "Cannot downgrade universal form-delivery migration while governed records exist."
        )
    for table in reversed(TABLES):
        if table in existing:
            op.drop_table(table)


def _index(table: str, column: str) -> None:
    op.create_index(_index_identifier(table, column), table, [column], unique=False)


def _index_identifier(table: str, column: str) -> str:
    name = f"ix_{_INDEX_TABLE_PREFIXES[table]}_{column}"
    if len(name.encode("utf-8")) > 63:
        raise RuntimeError(
            f"Migration index identifier exceeds PostgreSQL's 63-byte limit: {name}"
        )
    return name


def _strip_outer_parentheses(value: str) -> str:
    result = value.strip()
    while result.startswith("(") and result.endswith(")"):
        depth = 0
        quoted = False
        closes_at_end = False
        index = 0
        while index < len(result):
            character = result[index]
            if character == "'":
                if quoted and index + 1 < len(result) and result[index + 1] == "'":
                    index += 2
                    continue
                quoted = not quoted
            elif not quoted:
                if character == "(":
                    depth += 1
                elif character == ")":
                    depth -= 1
                    if depth == 0:
                        closes_at_end = index == len(result) - 1
                        break
            index += 1
        if not closes_at_end:
            break
        result = result[1:-1].strip()
    return result


def _normalized_check_sql(
    value: object,
    *,
    text_columns: frozenset[str] = frozenset(),
    boolean_columns: frozenset[str] = frozenset(),
) -> str:
    """Normalize only proven PostgreSQL textual deparse aliases.

    Literal and quoted-identifier spelling is encoded before any case folding.
    Integer/boolean casts and every unknown expression remain significant.
    """

    raw = str("" if value is None else value).strip()
    if "\x00" in raw:
        return "\x00invalid-raw-nul\x00"
    quoted_values: list[str] = []
    sentinel_prefix = "__atlas_0047_quoted_"
    while sentinel_prefix in raw.lower():
        sentinel_prefix = "_" + sentinel_prefix

    def protect(match: re.Match[str]) -> str:
        quoted_values.append(match.group(0))
        return f"{sentinel_prefix}{len(quoted_values) - 1}__"

    normalized = re.sub(
        r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`",
        protect,
        raw,
    )
    normalized = " ".join(normalized.lower().split())
    if normalized.startswith("check "):
        normalized = normalized[6:].strip()

    token = re.escape(sentinel_prefix) + r"\d+__"
    textual_type = r"(?:text|varchar|character\s+varying)"
    whole_item = rf"{token}\s*::\s*{textual_type}"
    whole_items = rf"{whole_item}(?:\s*,\s*{whole_item})*"
    per_item = rf"\(\s*{token}\s*::\s*{textual_type}\s*\)\s*::\s*text"
    per_items = rf"{per_item}(?:\s*,\s*{per_item})*"
    pg_prefix = (
        r"\(\(\s*(?P<column>[a-z_][a-z0-9_]*)\s*\)\s*::\s*text\s*"
        r"(?P<operator>=\s*any|(?:<>|!=)\s*all)\s*"
    )
    pg_whole = re.compile(
        pg_prefix
        + rf"\(\s*\(\s*array\[(?P<items>{whole_items})\]\s*\)\s*::\s*"
        + rf"{textual_type}\s*\[\s*\]\s*\)\s*\)"
    )
    pg_per_item = re.compile(
        pg_prefix
        + rf"\(\s*array\[(?P<items>{per_items})\]\s*\)\s*\)"
    )
    pg_bare_prefix = (
        r"(?<![a-z0-9_])(?P<column>[a-z_][a-z0-9_]*)\s*::\s*text\s*"
        r"(?P<operator>=\s*any|(?:<>|!=)\s*all)\s*"
    )
    pg_bare_whole = re.compile(
        pg_bare_prefix
        + rf"\(\s*array\[(?P<items>{whole_items})\]\s*::\s*"
        + rf"{textual_type}\s*\[\s*\]\s*\)"
    )
    pg_bare_per_item = re.compile(
        pg_bare_prefix
        + rf"\(\s*array\[(?P<items>{per_items})\]\s*\)"
    )
    expected_membership = re.compile(
        rf"(?P<column>[a-z_][a-z0-9_]*)\s+"
        rf"(?P<operator>in|not\s+in)\s*"
        rf"\(\s*(?P<items>{token}(?:\s*,\s*{token})*)\s*\)"
    )

    def membership(match: re.Match[str]) -> str:
        indices = tuple(
            int(item)
            for item in re.findall(
                re.escape(sentinel_prefix) + r"(\d+)__",
                match.group("items"),
            )
        )
        if not indices or any(
            index >= len(quoted_values)
            or not quoted_values[index].startswith("'")
            for index in indices
        ):
            return match.group(0)
        if match.group("column") not in text_columns:
            return match.group(0)
        operator = match.group("operator").replace(" ", "")
        operation = "not_in" if operator in {"<>all", "!=all", "notin"} else "in"
        identity = json.dumps(
            {
                "column": match.group("column"),
                "operation": operation,
                "literals": [quoted_values[index] for index in indices],
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        return "\x00m" + identity.encode("utf-8").hex() + "\x00"

    normalized = pg_whole.sub(membership, normalized)
    normalized = pg_per_item.sub(membership, normalized)
    normalized = pg_bare_whole.sub(membership, normalized)
    normalized = pg_bare_per_item.sub(membership, normalized)
    normalized = expected_membership.sub(membership, normalized)

    # PostgreSQL adds text casts when a VARCHAR participates in a textual
    # operator. Only exact known VARCHAR columns and protected string literals
    # may shed that representation-only cast. No numeric or Boolean cast is
    # ever normalized.
    for column in sorted(text_columns, key=len, reverse=True):
        escaped = re.escape(column)
        normalized = re.sub(
            rf"\(\s*{escaped}\s*\)\s*::\s*{textual_type}",
            column,
            normalized,
        )
        normalized = re.sub(
            rf"\b{escaped}\b\s*::\s*{textual_type}",
            column,
            normalized,
        )
    for index, quoted in enumerate(quoted_values):
        if not quoted.startswith("'"):
            continue
        protected = f"{sentinel_prefix}{index}__"
        normalized = re.sub(
            rf"{re.escape(protected)}\s*::\s*{textual_type}",
            protected,
            normalized,
        )
    for column in sorted(boolean_columns, key=len, reverse=True):
        escaped = re.escape(column)
        normalized = re.sub(
            rf"\b{escaped}\b\s*=\s*true\b",
            column,
            normalized,
        )
        normalized = re.sub(
            rf"\b{escaped}\b\s*=\s*false\b",
            f"not {column}",
            normalized,
        )

    normalized = normalized.replace("<>", "!=")
    normalized = re.sub(r"\s*~~\s*", " like ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    for index, quoted in enumerate(quoted_values):
        encoded = "\x00l" + quoted.encode("utf-8").hex() + "\x00"
        normalized = normalized.replace(f"{sentinel_prefix}{index}__", encoded)
    return _strip_outer_parentheses(normalized)


def _split_top_level_boolean(value: str, operator: str) -> list[str]:
    marker = f" {operator} "
    parts: list[str] = []
    start = 0
    depth = 0
    quoted = False
    index = 0
    while index < len(value):
        character = value[index]
        if character == "'":
            if quoted and index + 1 < len(value) and value[index + 1] == "'":
                index += 2
                continue
            quoted = not quoted
            index += 1
            continue
        if not quoted:
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
            elif depth == 0 and value.startswith(marker, index):
                parts.append(value[start:index].strip())
                index += len(marker)
                start = index
                continue
        index += 1
    if not parts:
        return [value]
    parts.append(value[start:].strip())
    return parts


def _check_contract_ast(
    value: object,
    *,
    text_columns: frozenset[str] = frozenset(),
    boolean_columns: frozenset[str] = frozenset(),
) -> tuple[object, ...]:
    expression = _strip_outer_parentheses(
        _normalized_check_sql(
            value,
            text_columns=text_columns,
            boolean_columns=boolean_columns,
        )
    )

    def parse(normalized_expression: str) -> tuple[object, ...]:
        normalized_expression = _strip_outer_parentheses(normalized_expression)
        or_parts = _split_top_level_boolean(normalized_expression, "or")
        if len(or_parts) > 1:
            return ("or", *tuple(parse(item) for item in or_parts))
        and_parts = _split_top_level_boolean(normalized_expression, "and")
        if len(and_parts) > 1:
            return ("and", *tuple(parse(item) for item in and_parts))
        tokens: list[str] = []
        position = 0
        token_pattern = re.compile(
            r"\x00(?:l|m)[0-9a-f]+\x00"
            r"|>=|<=|!=|::|[a-z_][a-z0-9_]*|[0-9]+|[(),+\-*/\[\]=<>]"
        )
        for match in token_pattern.finditer(normalized_expression):
            if normalized_expression[position : match.start()].strip():
                return ("invalid", normalized_expression)
            tokens.append(match.group(0))
            position = match.end()
        if normalized_expression[position:].strip() or not tokens:
            return ("invalid", normalized_expression)
        return ("atom", *tokens)

    return parse(expression)


def _normalized_index_predicate(
    index: dict[str, object],
    *,
    text_columns: frozenset[str] = frozenset(),
    boolean_columns: frozenset[str] = frozenset(),
) -> tuple[object, ...] | None:
    dialect_options = index.get("dialect_options") or {}
    predicate = dialect_options.get("postgresql_where")  # type: ignore[union-attr]
    if predicate is None:
        predicate = dialect_options.get("sqlite_where")  # type: ignore[union-attr]
    if predicate is None:
        return None
    return _check_contract_ast(
        predicate,
        text_columns=text_columns,
        boolean_columns=boolean_columns,
    )


def _column_type_matches(bind: object, table: str, column: dict[str, object]) -> bool:
    name = str(column["name"])
    observed_type = column["type"]
    type_name = type(observed_type).__name__.lower()
    if name in _INTEGER_COLUMNS[table]:
        return type_name == "integer"
    if name in _BOOLEAN_COLUMNS[table]:
        return type_name == "boolean"
    if name in _DATETIME_COLUMNS[table]:
        if bind.dialect.name == "postgresql":
            return type_name == "timestamp" and observed_type.timezone is True
        return type_name in {"datetime", "timestamp"}
    if name in _JSON_COLUMNS[table]:
        return type_name == "json"
    expected_length = _STRING_LENGTHS[table].get(name)
    return bool(
        expected_length is not None
        and type_name in {"varchar", "string"}
        and observed_type.length == expected_length
    )


def _assert_exact_postgresql_catalog(bind: object, mismatches: list[str]) -> None:
    schema = bind.execute(text("SELECT current_schema()" )).scalar_one()
    table_rows = bind.execute(
        text(
            "SELECT r.relname, r.relkind, r.relpersistence, r.relrowsecurity, "
            "r.relforcerowsecurity, r.relispartition, r.relreplident, "
            "r.reloptions, am.amname AS access_method, ts.spcname AS tablespace, "
            "parent.relname AS inheritance_parent, "
            "pg_get_expr(r.relpartbound, r.oid, false) AS partition_bound "
            "FROM pg_class r JOIN pg_namespace n ON n.oid = r.relnamespace "
            "LEFT JOIN pg_am am ON am.oid = r.relam "
            "LEFT JOIN pg_tablespace ts ON ts.oid = r.reltablespace "
            "LEFT JOIN pg_inherits inh ON inh.inhrelid = r.oid "
            "LEFT JOIN pg_class parent ON parent.oid = inh.inhparent "
            "WHERE n.nspname = :schema AND r.relkind IN ('r','p')"
        ),
        {"schema": schema},
    ).mappings().all()
    owned_table_rows = {
        str(row["relname"]): row for row in table_rows if row["relname"] in TABLES
    }
    if set(owned_table_rows) != set(TABLES):
        mismatches.append("postgresql:owned-table-inventory")
    for table, row in owned_table_rows.items():
        if (
            row["relkind"] != "r"
            or row["relpersistence"] != "p"
            or row["relrowsecurity"]
            or row["relforcerowsecurity"]
            or row["relispartition"]
            or row["relreplident"] != "d"
            or row["reloptions"] not in (None, [])
            or row["access_method"] != "heap"
            or row["tablespace"] is not None
            or row["inheritance_parent"] is not None
            or row["partition_bound"] is not None
        ):
            mismatches.append(f"{table}:postgresql-table-contract")
    for table in TABLES:
        column_rows = bind.execute(
            text(
                "SELECT a.attname, pg_catalog.format_type(a.atttypid, a.atttypmod) "
                "AS formatted_type, a.attidentity, a.attgenerated, "
                "a.attcollation = t.typcollation AS default_type_collation, "
                "a.attstorage::text AS storage_strategy, "
                "a.attcompression::text AS compression_method, "
                "a.attstattarget, a.attislocal, a.attinhcount, a.atthasmissing, "
                "ic.datetime_precision "
                "FROM pg_class r JOIN pg_namespace n ON n.oid = r.relnamespace "
                "JOIN pg_attribute a ON a.attrelid = r.oid "
                "JOIN pg_type t ON t.oid = a.atttypid "
                "LEFT JOIN information_schema.columns ic "
                "ON ic.table_schema = n.nspname AND ic.table_name = r.relname "
                "AND ic.column_name = a.attname "
                "WHERE n.nspname = :schema AND r.relname = :table "
                "AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum"
            ),
            {"schema": schema, "table": table},
        ).mappings().all()
        expected_types: dict[str, str] = {}
        for name in _EXPECTED_COLUMNS[table]:
            if name in _INTEGER_COLUMNS[table]:
                expected_types[name] = "integer"
            elif name in _BOOLEAN_COLUMNS[table]:
                expected_types[name] = "boolean"
            elif name in _DATETIME_COLUMNS[table]:
                expected_types[name] = "timestamp with time zone"
            elif name in _JSON_COLUMNS[table]:
                expected_types[name] = "json"
            else:
                expected_types[name] = (
                    f"character varying({_STRING_LENGTHS[table][name]})"
                )
        if tuple(row["attname"] for row in column_rows) != _EXPECTED_COLUMNS[table]:
            mismatches.append(f"{table}:postgresql-column-order")
        for row in column_rows:
            name = str(row["attname"])
            if (
                row["formatted_type"] != expected_types.get(name)
                or row["attidentity"] != ""
                or row["attgenerated"] != ""
                or not row["default_type_collation"]
                or row["storage_strategy"]
                != ("x" if name in _JSON_COLUMNS[table] or name in _STRING_LENGTHS[table] else "p")
                or row["compression_method"] not in ("", "\x00")
                or row["attstattarget"] != -1
                or not row["attislocal"]
                or row["attinhcount"] != 0
                or row["atthasmissing"]
                or (
                    name in _DATETIME_COLUMNS[table]
                    and row["datetime_precision"] != 6
                )
                or (
                    name not in _DATETIME_COLUMNS[table]
                    and row["datetime_precision"] is not None
                )
            ):
                mismatches.append(f"{table}.{name}:postgresql-column-contract")

        expected_sequence = f"{table}_id_seq"
        qualified_table = f"{schema}.{table}"
        serial_sequence = bind.execute(
            text("SELECT pg_get_serial_sequence(:table_name, 'id')"),
            {"table_name": qualified_table},
        ).scalar_one_or_none()
        if serial_sequence is None or str(serial_sequence).split(".")[-1].strip('"') != expected_sequence:
            mismatches.append(f"{table}:sequence-ownership")
        else:
            sequence = bind.execute(
                text(
                    "SELECT data_type, start_value, min_value, max_value, "
                    "increment_by, cycle, cache_size FROM pg_sequences "
                    "WHERE schemaname = :schema AND sequencename = :sequence"
                ),
                {"schema": schema, "sequence": expected_sequence},
            ).mappings().one_or_none()
            expected_options = {
                "data_type": "integer",
                "start_value": 1,
                "min_value": 1,
                "max_value": 2147483647,
                "increment_by": 1,
                "cycle": False,
                "cache_size": 1,
            }
            if sequence is None or any(
                sequence[key] != value for key, value in expected_options.items()
            ):
                mismatches.append(f"{table}:sequence-options")

        constraints = bind.execute(
            text(
                "SELECT c.conname, c.contype, c.condeferrable, c.condeferred, "
                "c.convalidated, c.connoinherit, c.conislocal, c.coninhcount, "
                "c.confupdtype, c.confdeltype, c.confmatchtype, "
                "rn.nspname AS referred_schema, "
                "COALESCE(i.indnullsnotdistinct, false) "
                "AS indnullsnotdistinct "
                "FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
                "JOIN pg_namespace n ON n.oid = t.relnamespace "
                "LEFT JOIN pg_class rt ON rt.oid = c.confrelid "
                "LEFT JOIN pg_namespace rn ON rn.oid = rt.relnamespace "
                "LEFT JOIN pg_index i ON i.indexrelid = c.conindid "
                "WHERE n.nspname = :schema AND t.relname = :table"
            ),
            {"schema": schema, "table": table},
        ).mappings().all()
        expected_constraint_types = {
            f"{table}_pkey": "p",
            **{name: "c" for name in _EXPECTED_CHECKS[table]},
            **{name: "u" for name in _EXPECTED_UNIQUES[table]},
            **{
                name: "f"
                for name in _EXPECTED_FOREIGN_KEY_NAMES[table].values()
            },
        }
        observed_constraint_types = {
            str(item["conname"]): str(item["contype"])
            for item in constraints
        }
        if observed_constraint_types != expected_constraint_types:
            mismatches.append(f"{table}:postgresql-constraint-inventory")
        for constraint in constraints:
            expected_no_inherit = constraint["contype"] in {"p", "u", "f"}
            if (
                constraint["condeferrable"]
                or constraint["condeferred"]
                or not constraint["convalidated"]
                or bool(constraint["connoinherit"]) != expected_no_inherit
                or not constraint["conislocal"]
                or constraint["coninhcount"] != 0
                or constraint["indnullsnotdistinct"]
            ):
                mismatches.append(f"{table}.{constraint['conname']}:constraint-options")
            if constraint["contype"] == "f" and (
                constraint["confupdtype"] != "a"
                or constraint["confdeltype"] != "a"
                or constraint["confmatchtype"] != "s"
                or constraint["referred_schema"] != schema
            ):
                mismatches.append(f"{table}.{constraint['conname']}:foreign-key-actions")

        indexes = bind.execute(
            text(
                "SELECT ci.relname AS name, am.amname AS access_method, "
                "i.indisunique, i.indisprimary, i.indisexclusion, "
                "i.indimmediate, i.indisclustered, i.indisvalid, i.indisready, "
                "i.indislive, i.indisreplident, i.indnkeyatts, "
                "i.indnatts, i.indnullsnotdistinct, ci.relpersistence, "
                "pg_get_expr(i.indpred, i.indrelid) AS predicate, "
                "pg_get_expr(i.indexprs, i.indrelid) AS expressions, "
                "ci.reloptions, ci.reltablespace, "
                "ARRAY(SELECT pg_get_indexdef(i.indexrelid, slot, true) "
                "FROM generate_series(1, i.indnatts) AS slot ORDER BY slot) "
                "AS key_definitions, "
                "ARRAY(SELECT opc.opcdefault FROM "
                "generate_series(0, i.indnkeyatts - 1) AS slot "
                "JOIN pg_opclass opc ON opc.oid = i.indclass[slot] "
                "ORDER BY slot) AS default_operator_classes, "
                "ARRAY(SELECT i.indoption[slot] FROM "
                "generate_series(0, i.indnkeyatts - 1) AS slot "
                "ORDER BY slot) AS key_options, "
                "ARRAY(SELECT i.indcollation[slot] = a.attcollation FROM "
                "generate_series(0, i.indnkeyatts - 1) AS slot "
                "JOIN pg_attribute a ON a.attrelid = i.indrelid "
                "AND a.attnum = i.indkey[slot] ORDER BY slot) "
                "AS column_collations_match "
                "FROM pg_index i JOIN pg_class t ON t.oid = i.indrelid "
                "JOIN pg_namespace n ON n.oid = t.relnamespace "
                "JOIN pg_class ci ON ci.oid = i.indexrelid "
                "JOIN pg_am am ON am.oid = ci.relam "
                "WHERE n.nspname = :schema AND t.relname = :table"
            ),
            {"schema": schema, "table": table},
        ).mappings().all()
        by_name = {str(item["name"]): item for item in indexes}
        expected_indexes: dict[str, tuple[str, ...]] = {
            _index_identifier(table, column): (column,)
            for column in _INDEX_COLUMNS[table]
        }
        expected_indexes[f"{table}_pkey"] = ("id",)
        expected_indexes.update(_EXPECTED_UNIQUES[table])
        if set(by_name) != set(expected_indexes):
            mismatches.append(f"{table}:postgresql-index-inventory")
        for name, columns in expected_indexes.items():
            item = by_name.get(name)
            if item is None:
                mismatches.append(f"{table}.{name}:postgresql-index")
                continue
            if (
                item["access_method"] != "btree"
                or item["relpersistence"] != "p"
                or item["indisexclusion"]
                or not item["indimmediate"]
                or item["indisclustered"]
                or not item["indisvalid"]
                or not item["indisready"]
                or not item["indislive"]
                or item["indisreplident"]
                or item["indnkeyatts"] != len(columns)
                or item["indnatts"] != len(columns)
                or item["expressions"] is not None
                or item["reloptions"] not in (None, [])
                or item["reltablespace"] != 0
                or tuple(
                    str(value).strip('"') for value in item["key_definitions"]
                ) != columns
                or tuple(item["default_operator_classes"])
                != (True,) * len(columns)
                or tuple(item["key_options"]) != (0,) * len(columns)
                or tuple(item["column_collations_match"])
                != (True,) * len(columns)
                or bool(item["indnullsnotdistinct"])
            ):
                mismatches.append(f"{table}.{name}:postgresql-index-options")
            expected_unique = bool(
                name == f"{table}_pkey"
                or name in _EXPECTED_UNIQUES[table]
            )
            if bool(item["indisunique"]) != expected_unique:
                mismatches.append(f"{table}.{name}:postgresql-index-uniqueness")
            if bool(item["indisprimary"]) != (name == f"{table}_pkey"):
                mismatches.append(f"{table}.{name}:postgresql-index-primary")
            predicate = item["predicate"]
            if predicate is not None:
                mismatches.append(f"{table}.{name}:postgresql-index-predicate")

    ri_trigger_rows = bind.execute(
        text(
            "SELECT c.conname AS constraint_name, child.relname AS child_table, "
            "host.relname AS trigger_table, proc.proname AS function_name, "
            "g.tgenabled, g.tgisinternal, g.tgdeferrable, g.tginitdeferred "
            "FROM pg_trigger g JOIN pg_constraint c ON c.oid = g.tgconstraint "
            "JOIN pg_class child ON child.oid = c.conrelid "
            "JOIN pg_namespace child_ns ON child_ns.oid = child.relnamespace "
            "JOIN pg_class host ON host.oid = g.tgrelid "
            "JOIN pg_proc proc ON proc.oid = g.tgfoid "
            "WHERE child_ns.nspname = :schema AND c.contype = 'f'"
        ),
        {"schema": schema},
    ).mappings().all()
    expected_ri_triggers: set[tuple[str, str, str]] = set()
    owned_fk_names: set[str] = set()
    for child_table, records in _EXPECTED_FOREIGN_KEY_NAMES.items():
        for (_columns, referred_table, _referred_columns), constraint_name in records.items():
            owned_fk_names.add(constraint_name)
            expected_ri_triggers.update(
                {
                    (constraint_name, child_table, "RI_FKey_check_ins"),
                    (constraint_name, child_table, "RI_FKey_check_upd"),
                    (constraint_name, referred_table, "RI_FKey_noaction_del"),
                    (constraint_name, referred_table, "RI_FKey_noaction_upd"),
                }
            )
    owned_ri_rows = [
        row for row in ri_trigger_rows if row["constraint_name"] in owned_fk_names
    ]
    observed_ri_triggers = {
        (
            str(row["constraint_name"]),
            str(row["trigger_table"]),
            str(row["function_name"]),
        )
        for row in owned_ri_rows
    }
    if (
        observed_ri_triggers != expected_ri_triggers
        or len(owned_ri_rows) != len(expected_ri_triggers)
        or any(
            row["tgenabled"] != "O"
            or not row["tgisinternal"]
            or row["tgdeferrable"]
            or row["tginitdeferred"]
            for row in owned_ri_rows
        )
    ):
        mismatches.append("postgresql:foreign-key-trigger-contract")

    expected_sequences = {f"{table}_id_seq": table for table in TABLES}
    sequence_rows = bind.execute(
        text(
            "SELECT seq.relname AS sequence_name, seq.relpersistence, "
            "seq.reloptions, ts.spcname AS tablespace, "
            "pg_catalog.format_type(s.seqtypid, NULL) AS type_name, "
            "s.seqstart, s.seqincrement, s.seqmin, s.seqmax, s.seqcache, "
            "s.seqcycle, owner_ns.nspname AS owner_schema, "
            "owner.relname AS owner_table, attr.attname AS owner_column, "
            "dep.deptype::text AS dependency_type "
            "FROM pg_sequence s JOIN pg_class seq ON seq.oid = s.seqrelid "
            "JOIN pg_namespace ns ON ns.oid = seq.relnamespace "
            "LEFT JOIN pg_tablespace ts ON ts.oid = seq.reltablespace "
            "LEFT JOIN pg_depend dep ON dep.classid = 'pg_class'::regclass "
            "AND dep.objid = seq.oid AND dep.objsubid = 0 "
            "AND dep.refclassid = 'pg_class'::regclass "
            "AND dep.deptype IN ('a','i') "
            "LEFT JOIN pg_class owner ON owner.oid = dep.refobjid "
            "LEFT JOIN pg_namespace owner_ns ON owner_ns.oid = owner.relnamespace "
            "LEFT JOIN pg_attribute attr ON attr.attrelid = dep.refobjid "
            "AND attr.attnum = dep.refobjsubid "
            "WHERE ns.nspname = :schema"
        ),
        {"schema": schema},
    ).mappings().all()
    owned_sequences = [
        row
        for row in sequence_rows
        if row["sequence_name"] in expected_sequences
        or row["owner_table"] in TABLES
    ]
    if {str(row["sequence_name"]) for row in owned_sequences} != set(
        expected_sequences
    ) or len(owned_sequences) != len(expected_sequences):
        mismatches.append("postgresql:owned-sequence-inventory")
    for row in owned_sequences:
        sequence_name = str(row["sequence_name"])
        if (
            row["relpersistence"] != "p"
            or row["reloptions"] not in (None, [])
            or row["tablespace"] is not None
            or row["type_name"] != "integer"
            or row["seqstart"] != 1
            or row["seqincrement"] != 1
            or row["seqmin"] != 1
            or row["seqmax"] != 2147483647
            or row["seqcache"] != 1
            or row["seqcycle"]
            or row["owner_schema"] != schema
            or row["owner_table"] != expected_sequences.get(sequence_name)
            or row["owner_column"] != "id"
            or row["dependency_type"] != "a"
        ):
            mismatches.append(f"{sequence_name}:postgresql-sequence-contract")

    trigger_tables = {
        str(row["table_name"])
        for row in bind.execute(
            text(
                "SELECT t.relname AS table_name FROM pg_trigger g "
                "JOIN pg_class t ON t.oid = g.tgrelid "
                "JOIN pg_namespace n ON n.oid = t.relnamespace "
                "WHERE n.nspname = :schema AND NOT g.tgisinternal"
            ),
            {"schema": schema},
        ).mappings()
        if row["table_name"] in TABLES
    }
    if trigger_tables:
        mismatches.append("postgresql:unexpected-owned-trigger")
    policy_tables = {
        str(row["table_name"])
        for row in bind.execute(
            text(
                "SELECT t.relname AS table_name FROM pg_policy p "
                "JOIN pg_class t ON t.oid = p.polrelid "
                "JOIN pg_namespace n ON n.oid = t.relnamespace "
                "WHERE n.nspname = :schema"
            ),
            {"schema": schema},
        ).mappings()
        if row["table_name"] in TABLES
    }
    if policy_tables:
        mismatches.append("postgresql:unexpected-owned-policy")
    rule_tables = {
        str(row["table_name"])
        for row in bind.execute(
            text(
                "SELECT t.relname AS table_name FROM pg_rewrite r "
                "JOIN pg_class t ON t.oid = r.ev_class "
                "JOIN pg_namespace n ON n.oid = t.relnamespace "
                "WHERE n.nspname = :schema AND r.rulename <> '_RETURN'"
            ),
            {"schema": schema},
        ).mappings()
        if row["table_name"] in TABLES
    }
    if rule_tables:
        mismatches.append("postgresql:unexpected-owned-rule")
    statistics_tables = {
        str(row["table_name"])
        for row in bind.execute(
            text(
                "SELECT t.relname AS table_name FROM pg_statistic_ext s "
                "JOIN pg_class t ON t.oid = s.stxrelid "
                "JOIN pg_namespace n ON n.oid = t.relnamespace "
                "WHERE n.nspname = :schema"
            ),
            {"schema": schema},
        ).mappings()
        if row["table_name"] in TABLES
    }
    if statistics_tables:
        mismatches.append("postgresql:unexpected-owned-statistics")
    publication_tables = {
        str(row["table_name"])
        for row in bind.execute(
            text(
                "SELECT t.relname AS table_name FROM pg_publication_rel p "
                "JOIN pg_class t ON t.oid = p.prrelid "
                "JOIN pg_namespace n ON n.oid = t.relnamespace "
                "WHERE n.nspname = :schema"
            ),
            {"schema": schema},
        ).mappings()
        if row["table_name"] in TABLES
    }
    if publication_tables:
        mismatches.append("postgresql:unexpected-owned-publication")


def _assert_exact_owned_shape(bind: object) -> None:
    inspector = inspect(bind)
    mismatches: list[str] = []
    for table in TABLES:
        columns = inspector.get_columns(table)
        primary_key = inspector.get_pk_constraint(table)
        primary_columns = tuple(primary_key.get("constrained_columns") or ())
        observed_names = tuple(item["name"] for item in columns)
        if observed_names != _EXPECTED_COLUMNS[table]:
            mismatches.append(f"{table}:columns")
            continue
        for column in columns:
            name = column["name"]
            if bool(column["nullable"]) != (name in _NULLABLE_COLUMNS[table]):
                mismatches.append(f"{table}.{name}:nullability")
            if (name in primary_columns) != (name == "id"):
                mismatches.append(f"{table}.{name}:primary-key")
            default = column.get("default")
            if name == "id" and bind.dialect.name == "postgresql":
                expected_default = f"nextval('{table}_id_seq'::regclass)"
                if str(default).replace('"', "") != expected_default:
                    mismatches.append(f"{table}.{name}:server-default")
            elif default is not None:
                mismatches.append(f"{table}.{name}:server-default")
            if not _column_type_matches(bind, table, column):
                mismatches.append(f"{table}.{name}:type")

        if (
            primary_columns != ("id",)
            or (
                bind.dialect.name == "postgresql"
                and primary_key.get("name") != f"{table}_pkey"
            )
        ):
            mismatches.append(f"{table}:primary-key")
        inspected_foreign_keys = inspector.get_foreign_keys(table)
        foreign_keys = {
            (
                (
                    item.get("name")
                    if bind.dialect.name == "postgresql"
                    else None
                ),
                tuple(item.get("constrained_columns") or ()),
                item.get("referred_schema"),
                item["referred_table"],
                tuple(item.get("referred_columns") or ()),
                tuple(
                    sorted(
                        (str(key), str(value))
                        for key, value in (item.get("options") or {}).items()
                    )
                ),
            )
            for item in inspected_foreign_keys
        }
        expected_foreign_keys = {
            (
                (
                    _EXPECTED_FOREIGN_KEY_NAMES[table][
                        (columns, referred_table, referred_columns)
                    ]
                    if bind.dialect.name == "postgresql"
                    else None
                ),
                columns,
                None,
                referred_table,
                referred_columns,
                (),
            )
            for columns, referred_table, referred_columns in _EXPECTED_FOREIGN_KEYS[
                table
            ]
        }
        if (
            len(inspected_foreign_keys) != len(expected_foreign_keys)
            or foreign_keys != expected_foreign_keys
        ):
            mismatches.append(f"{table}:foreign-keys")
        inspected_checks = inspector.get_check_constraints(table)
        checks = {
            item["name"]: str(item.get("sqltext") or "")
            for item in inspected_checks
        }
        if (
            len(inspected_checks) != len(_EXPECTED_CHECKS[table])
            or set(checks) != _EXPECTED_CHECKS[table]
        ):
            mismatches.append(f"{table}:checks")
        else:
            for name, expected_sql in _EXPECTED_CHECK_SQL[table].items():
                text_columns = frozenset(_STRING_LENGTHS[table])
                boolean_columns = frozenset(_BOOLEAN_COLUMNS[table])
                if _check_contract_ast(
                    checks[name],
                    text_columns=text_columns,
                    boolean_columns=boolean_columns,
                ) != _check_contract_ast(
                    expected_sql,
                    text_columns=text_columns,
                    boolean_columns=boolean_columns,
                ):
                    mismatches.append(f"{table}.{name}:check-expression")
        inspected_uniques = inspector.get_unique_constraints(table)
        uniques = {
            item["name"]: (
                tuple(item.get("column_names") or ()),
                tuple(
                    sorted(
                        (str(key), str(value))
                        for key, value in (item.get("options") or {}).items()
                    )
                ),
            )
            for item in inspected_uniques
        }
        expected_uniques = {
            name: (columns, ())
            for name, columns in _EXPECTED_UNIQUES[table].items()
        }
        if (
            len(inspected_uniques) != len(expected_uniques)
            or uniques != expected_uniques
        ):
            mismatches.append(f"{table}:unique-constraints")

        indexes = {
            item["name"]: item
            for item in inspector.get_indexes(table)
            if not item.get("duplicates_constraint")
        }
        expected_indexes = {
            _index_identifier(table, column): ((column,), False)
            for column in _INDEX_COLUMNS[table]
        }
        observed_indexes = {
            name: (
                tuple(item.get("column_names") or ()),
                bool(item["unique"]),
                _normalized_index_predicate(
                    item,
                    text_columns=frozenset(_STRING_LENGTHS[table]),
                    boolean_columns=frozenset(_BOOLEAN_COLUMNS[table]),
                ),
                tuple(sorted((item.get("column_sorting") or {}).items())),
            )
            for name, item in indexes.items()
        }
        expected_index_contracts = {
            name: (columns, unique, None, ())
            for name, (columns, unique) in expected_indexes.items()
        }
        if observed_indexes != expected_index_contracts:
            mismatches.append(f"{table}:indexes")
    if bind.dialect.name == "postgresql":
        _assert_exact_postgresql_catalog(bind, mismatches)
    if mismatches:
        raise RuntimeError(
            "Cannot downgrade universal form-delivery migration because its "
            "owned schema does not match the exact 0047 contract: "
            + ", ".join(sorted(set(mismatches)))
        )
