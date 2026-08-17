from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.backup import (
    BACKUP_VERSION,
    FORM_DELIVERY_BACKUP_GROUPS,
    BackupValidationError,
    _restore_target_requires_metadata_bootstrap,
    export_backup,
    load_backup,
    restore_backup,
)
from app.models import (
    Business,
    FormDeliveryAttempt,
    FormDeliveryConfigurationAudit,
    FormDeliveryOutbox,
    FormSubmissionEnvelope,
    Website,
    WebsiteFormDeliveryModeRevision,
    WebsiteFormRecipientRevision,
    WebsiteThemeComponentConfiguration,
)
from app.schemas.form_delivery import (
    WebsiteFormDeliveryModeRevisionCreate,
    WebsiteFormRecipientRevisionCreate,
)
from app.schemas.theme_families import (
    PERFORMANCE_LOCAL_V3_COMPONENT_CONTRACTS,
    ThemeFamilyCreate,
    ThemeFamilyVersionCreate,
    WebsiteThemeComponentConfigurationCreate,
    WebsiteThemeConfigurationCreate,
)
from app.services.form_delivery_modes import (
    create_form_delivery_mode_revision,
    create_form_recipient_revision,
    form_delivery_configuration_audit_hash,
    form_delivery_mode_fingerprint,
    form_delivery_readiness,
    form_recipient_fingerprint,
    validate_form_delivery_records,
)
from app.services.form_delivery_outbox import (
    enqueue_form_delivery,
    form_delivery_attempt_fingerprint,
    form_submission_envelope_fingerprint,
    process_form_delivery_outbox,
)
from app.services.form_delivery_registry import (
    PRODUCTION_PROVIDER_REGISTRY,
    SYNTHETIC_EMAIL_PROVIDER_KEY,
)
from app.services.form_payload_store import InMemoryTestPayloadStore
from app.services.theme_configurations import (
    create_component_configuration,
    create_website_theme_configuration,
    register_theme_family,
    register_theme_family_version,
)
from app.website_builder_core.contracts import NormalizedSubmissionEnvelope


FORM_DELIVERY_MODELS = {
    "website_form_delivery_mode_revisions": WebsiteFormDeliveryModeRevision,
    "website_form_recipient_revisions": WebsiteFormRecipientRevision,
    "form_submission_envelopes": FormSubmissionEnvelope,
    "form_delivery_outbox_records": FormDeliveryOutbox,
    "form_delivery_attempts": FormDeliveryAttempt,
    "form_delivery_configuration_audits": FormDeliveryConfigurationAudit,
}


def _engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _create_0046_shaped_schema(engine) -> None:
    form_tables = {model.__table__ for model in FORM_DELIVERY_MODELS.values()}
    SQLModel.metadata.create_all(
        engine,
        tables=[
            table
            for table in SQLModel.metadata.tables.values()
            if table not in form_tables
        ],
    )


def _form_fields() -> list[dict]:
    definitions = (
        ("name", "Name", True, "input", "text", 1, "nonempty_text", 1, 100, "half", "name"),
        ("phone", "Phone", True, "input", "tel", 2, "phone", 7, 40, "half", "phone"),
        ("postal-code", "ZIP code", True, "input", "text", 3, "postal_code", 5, 12, "half", "postal_code"),
        ("requested-service", "Requested service", True, "input", "text", 4, "nonempty_text", 1, 160, "half", "requested_service"),
        ("message", "Optional message", False, "textarea", "text", 5, "free_text", 0, 2000, "full", "message"),
    )
    return [
        {
            "field_key": key,
            "label": label,
            "required": required,
            "control": control,
            "input_type": input_type,
            "order": order,
            "accessibility_label": label,
            "autocomplete_policy": "off",
            "maximum_length": maximum,
            "validation_contract": {
                "rule": rule,
                "minimum_length": minimum,
                "maximum_length": maximum,
            },
            "responsive_layout": layout,
            "provider_mapping": mapping,
        }
        for (
            key,
            label,
            required,
            control,
            input_type,
            order,
            rule,
            minimum,
            maximum,
            layout,
            mapping,
        ) in definitions
    ]


def _disabled_component_payload() -> dict:
    return {
        "submission_state": "disabled_pending_provider_configuration",
        "fields": _form_fields(),
        "submit_label": "Request an Estimate",
        "preview_notice": "Synthetic test configuration; no external delivery.",
        "provider": {
            "provider_key": None,
            "destination": None,
            "provider_secret_reference": None,
            "test_only": False,
        },
        "privacy": {
            "policy_destination": None,
            "consent_mode": None,
            "consent_text": None,
            "consent_text_version": None,
        },
        "retention": {
            "duration": None,
            "deletion_expiration_behavior": None,
        },
        "spam": {"strategy": None, "configuration_reference": None},
        "success_behavior": None,
        "failure_behavior": None,
        "security": {
            "same_origin_policy": None,
            "csrf_policy": None,
            "request_size_limit_bytes": None,
            "idempotency_strategy": None,
        },
        "audit_identity": None,
    }


def _seed_form_component(
    session: Session,
    *,
    label: str,
) -> tuple[Website, WebsiteThemeComponentConfiguration]:
    token = uuid4().hex
    business = Business(
        company_name=f"{label} {token}",
        business_type="synthetic backup test",
        state="FL",
    )
    session.add(business)
    session.flush()
    website = Website(
        business_id=business.id,
        website_name=f"{label} Website",
        domain=f"{token}.example.test",
        public_url=f"https://{token}.example.test",
        status="active",
    )
    session.add(website)
    session.commit()

    family = register_theme_family(
        session,
        ThemeFamilyCreate(
            family_key=f"form-backup-{token}",
            display_name=f"{label} Theme",
            description="Synthetic Theme graph for form-delivery backup tests.",
            provider_source_identity=f"atlas-source:form-backup-{token}",
            created_by="Form Backup Test Operator",
        ),
    )
    form_contract = next(
        deepcopy(item)
        for item in PERFORMANCE_LOCAL_V3_COMPONENT_CONTRACTS
        if item["component_key"] == "compact_estimate_form"
    )
    version = register_theme_family_version(
        session,
        family.id,
        ThemeFamilyVersionCreate(
            version=3,
            source_commit="a" * 40,
            supported_component_contracts=[form_contract],
            created_by="Form Backup Test Operator",
        ),
    )
    configuration = create_website_theme_configuration(
        session,
        website.id,
        WebsiteThemeConfigurationCreate(
            theme_family_version_id=version.id,
            configuration_key="form-backup-review",
            created_by="Form Backup Test Operator",
            creation_rationale="Create an inactive synthetic form backup graph.",
        ),
    )
    component = create_component_configuration(
        session,
        website.id,
        configuration.id,
        WebsiteThemeComponentConfigurationCreate(
            component_instance_key="compact-estimate-form:website",
            component_key="compact_estimate_form",
            component_contract_version=3,
            scope_type="website_default",
            enabled=True,
            variant=form_contract["variant"],
            placement=form_contract["placement"],
            responsive_visibility=form_contract["responsive_visibility"],
            configuration_payload=_disabled_component_payload(),
            approval_identity="Form Backup Test Operator",
            created_by="Form Backup Test Operator",
        ),
    )
    return website, component


def _active_evidence() -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "lifecycle_status": "active",
        "approval_identity": "form-backup-approval",
        "approved_at": now,
        "activation_identity": "form-backup-activation",
        "activated_at": now,
    }


def _seed_complete_form_delivery_graph(session: Session) -> dict[str, int]:
    website, component = _seed_form_component(session, label="Form Backup Source")
    disabled = create_form_delivery_mode_revision(
        session,
        website.id,
        WebsiteFormDeliveryModeRevisionCreate(
            form_component_configuration_id=component.id,
            form_instance_key=component.component_instance_key,
            mode="disabled",
            enabled=False,
            configuration_payload={},
            audit_identity="form-backup-disabled-audit",
            created_by="Form Backup Test Operator",
            updated_by="Form Backup Test Operator",
            rationale="Record an explicit disabled root revision.",
            **_active_evidence(),
        ),
    )
    email = create_form_delivery_mode_revision(
        session,
        website.id,
        WebsiteFormDeliveryModeRevisionCreate(
            form_component_configuration_id=component.id,
            form_instance_key=component.component_instance_key,
            supersedes_delivery_mode_revision_id=disabled.id,
            mode="atlas_email",
            enabled=True,
            provider_key=SYNTHETIC_EMAIL_PROVIDER_KEY,
            adapter_version="test-v1",
            destination_identity="recipient-set-ref://synthetic/form-backup",
            configuration_payload={
                "transport_key_reference": "synthetic-mail",
                "transport_secret_reference": "secret-ref://synthetic/mail-transport",
                "notification_preference": "all_verified",
                "consent_required": False,
            },
            privacy_policy_reference="/privacy",
            retention_policy_reference="policy-ref://synthetic/retention",
            abuse_policy_reference="policy-ref://synthetic/abuse",
            success_behavior="Show a generic success message.",
            failure_behavior="Show a generic failure message.",
            idempotency_policy_reference="policy-ref://synthetic/idempotency",
            audit_identity="form-backup-email-audit",
            created_by="Form Backup Test Operator",
            updated_by="Form Backup Test Operator",
            rationale="Enable only the contained test email adapter.",
            **_active_evidence(),
        ),
    )
    unverified_recipient = create_form_recipient_revision(
        session,
        website.id,
        WebsiteFormRecipientRevisionCreate(
            delivery_mode_revision_id=email.id,
            recipient_key="primary-office",
            email="Synthetic.Recipient@example.com",
            label="Synthetic primary recipient",
            recipient_role="primary",
            enabled=True,
            verification_status="unverified",
            created_by="Form Backup Test Operator",
            updated_by="Form Backup Test Operator",
            rationale="Create unverified synthetic recipient configuration.",
        ),
    )
    recipient = create_form_recipient_revision(
        session,
        website.id,
        WebsiteFormRecipientRevisionCreate(
            delivery_mode_revision_id=email.id,
            recipient_key="primary-office",
            supersedes_recipient_revision_id=unverified_recipient.id,
            email="Synthetic.Recipient@example.com",
            label="Synthetic primary recipient",
            recipient_role="primary",
            enabled=True,
            verification_status="verified",
            verified_at=datetime.now(UTC),
            verified_by="Form Backup Test Verifier",
            verification_method="synthetic_test",
            created_by="Form Backup Test Operator",
            updated_by="Form Backup Test Operator",
            rationale="Append verified synthetic recipient evidence.",
        ),
    )
    readiness = form_delivery_readiness(
        session,
        email,
        allow_test_only=True,
        secure_payload_store_available=True,
    )
    assert readiness.can_submit is True
    received_at = datetime.now(UTC)
    store = InMemoryTestPayloadStore(test_environment_allowed=True)
    outbox = enqueue_form_delivery(
        session,
        mode_revision=email,
        readiness=readiness,
        envelope=NormalizedSubmissionEnvelope(
            website_id=website.id,
            component_configuration_id=component.id,
            component_revision=component.revision,
            delivery_mode_revision_id=email.id,
            submission_contract_version=3,
            name="Synthetic Person",
            phone="+14075550100",
            postal_code="32801",
            requested_service="Synthetic service",
            message="Synthetic message",
            consent_accepted=None,
            audit_identity=email.audit_identity,
            idempotency_key="form-backup-idempotency-00000001",
            privacy_policy_identity=email.privacy_policy_reference,
            retention_policy_identity=email.retention_policy_reference,
            abuse_policy_identity=email.abuse_policy_reference,
            anti_spam_decision="synthetic_allow",
            request_identity="1" * 64,
            destination_adapter_key=email.provider_key,
            received_at=received_at,
        ),
        payload_store=store,
        expires_at=received_at + timedelta(hours=1),
    )
    attempt = process_form_delivery_outbox(
        session,
        outbox.id,
        payload_store=store,
        allow_test_only=True,
        transient_retry_at=received_at + timedelta(minutes=5),
    )
    assert attempt.outcome == "delivered"
    assert store.payload_count == 0
    return {
        "website_id": website.id,
        "component_id": component.id,
        "disabled_id": disabled.id,
        "email_id": email.id,
        "recipient_id": recipient.id,
        "outbox_id": outbox.id,
    }


def _write_payload(tmp_path: Path, payload: dict, name: str) -> Path:
    path = tmp_path / name
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return path


def _export_complete_payload(tmp_path: Path) -> tuple[Path, dict, dict[str, int]]:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        identities = _seed_complete_form_delivery_graph(session)
        exported = export_backup(session, backup_dir=tmp_path)
        payload = load_backup(Path(exported["path"]))
    engine.dispose()
    return Path(exported["path"]), payload, identities


def _delivery_projection(session: Session) -> dict[str, list[dict]]:
    return {
        group: [
            record.model_dump(mode="json")
            for record in session.exec(select(model).order_by(model.id)).all()
        ]
        for group, model in FORM_DELIVERY_MODELS.items()
    }


def test_backup_058_round_trip_preserves_complete_form_delivery_graph(
    tmp_path: Path,
) -> None:
    source_path, source_payload, _ = _export_complete_payload(tmp_path)
    assert BACKUP_VERSION == "0.58"
    assert source_payload["metadata"]["version"] == "0.58"
    assert {
        group: source_payload["metadata"]["table_counts"][group]
        for group in FORM_DELIVERY_BACKUP_GROUPS
    } == {
        "website_form_delivery_mode_revisions": 2,
        "website_form_recipient_revisions": 2,
        "form_submission_envelopes": 1,
        "form_delivery_outbox_records": 1,
        "form_delivery_attempts": 1,
        "form_delivery_configuration_audits": 4,
    }

    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        first = restore_backup(session, source_path)
        assert first["status"] == "restored"
        assert validate_form_delivery_records(session) == {
            group: source_payload["metadata"]["table_counts"][group]
            for group in FORM_DELIVERY_BACKUP_GROUPS
        }
        second = restore_backup(session, source_path)
        assert second["status"] == "restored"
        target_export = export_backup(session, backup_dir=tmp_path / "reexport")
        target_payload = load_backup(Path(target_export["path"]))
    target_engine.dispose()

    assert {
        group: target_payload["data"][group]
        for group in FORM_DELIVERY_BACKUP_GROUPS
    } == {
        group: source_payload["data"][group]
        for group in FORM_DELIVERY_BACKUP_GROUPS
    }
    restored_modes = target_payload["data"]["website_form_delivery_mode_revisions"]
    restored_recipients = target_payload["data"]["website_form_recipient_revisions"]
    assert any(
        record["mode"] == "disabled" and record["enabled"] is False
        for record in restored_modes
    )
    assert [record["verification_status"] for record in restored_recipients] == [
        "unverified",
        "verified",
    ]
    assert restored_recipients[1]["supersedes_recipient_revision_id"] == (
        restored_recipients[0]["id"]
    )
    assert restored_recipients[1]["verified_at"] is not None
    serialized = json.dumps(target_payload, ensure_ascii=True)
    assert "Synthetic Person" not in serialized
    assert "+14075550100" not in serialized
    assert "Synthetic message" not in serialized
    assert not PRODUCTION_PROVIDER_REGISTRY.production


def test_backup_058_remaps_all_form_delivery_references_and_recomputes_integrity(
    tmp_path: Path,
) -> None:
    source_path, source_payload, source_ids = _export_complete_payload(tmp_path)
    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        sentinel_website, sentinel_component = _seed_form_component(
            session,
            label="Form Backup Remap Sentinel",
        )
        create_form_delivery_mode_revision(
            session,
            sentinel_website.id,
            WebsiteFormDeliveryModeRevisionCreate(
                form_component_configuration_id=sentinel_component.id,
                form_instance_key=sentinel_component.component_instance_key,
                mode="disabled",
                enabled=False,
                configuration_payload={},
                audit_identity="form-backup-remap-sentinel-audit",
                created_by="Form Backup Test Operator",
                updated_by="Form Backup Test Operator",
                rationale="Consume a target mode identity before restore.",
                **_active_evidence(),
            ),
        )
        restore_backup(session, source_path)
        source_website = session.exec(
            select(Website).where(
                Website.website_name == "Form Backup Source Website"
            )
        ).one()
        modes = list(
            session.exec(
                select(WebsiteFormDeliveryModeRevision)
                .where(
                    WebsiteFormDeliveryModeRevision.website_id
                    == source_website.id
                )
                .order_by(WebsiteFormDeliveryModeRevision.revision)
            ).all()
        )
        assert len(modes) == 2
        disabled, email = modes
        assert email.supersedes_delivery_mode_revision_id == disabled.id
        assert email.id != source_ids["email_id"]
        assert email.form_component_configuration_id != source_ids["component_id"]
        assert email.integrity_fingerprint == form_delivery_mode_fingerprint(email)

        recipients = list(
            session.exec(
                select(WebsiteFormRecipientRevision).order_by(
                    WebsiteFormRecipientRevision.revision
                )
            ).all()
        )
        envelope = session.exec(select(FormSubmissionEnvelope)).one()
        outbox = session.exec(select(FormDeliveryOutbox)).one()
        attempt = session.exec(select(FormDeliveryAttempt)).one()
        audits = list(
            session.exec(select(FormDeliveryConfigurationAudit)).all()
        )
        assert len(recipients) == 2
        assert all(recipient.delivery_mode_revision_id == email.id for recipient in recipients)
        assert recipients[1].supersedes_recipient_revision_id == recipients[0].id
        assert all(
            recipient.integrity_fingerprint == form_recipient_fingerprint(recipient)
            for recipient in recipients
        )
        assert envelope.delivery_mode_revision_id == email.id
        assert envelope.integrity_fingerprint == form_submission_envelope_fingerprint(
            envelope
        )
        assert outbox.envelope_id == envelope.id
        assert outbox.delivery_mode_revision_id == email.id
        assert attempt.outbox_id == outbox.id
        assert attempt.integrity_fingerprint == form_delivery_attempt_fingerprint(
            attempt
        )
        assert all(
            audit.snapshot_hash == form_delivery_configuration_audit_hash(audit)
            for audit in audits
        )
        assert validate_form_delivery_records(session) == {
            "website_form_delivery_mode_revisions": 3,
            "website_form_recipient_revisions": 2,
            "form_submission_envelopes": 1,
            "form_delivery_outbox_records": 1,
            "form_delivery_attempts": 1,
            "form_delivery_configuration_audits": 5,
        }
    target_engine.dispose()
    assert source_payload["data"]["form_submission_envelopes"][0].keys() == {
        *FormSubmissionEnvelope.model_fields,
    }


def test_backup_057_is_accepted_only_with_empty_form_delivery_groups(
    tmp_path: Path,
) -> None:
    _, payload, _ = _export_complete_payload(tmp_path)
    legacy = deepcopy(payload)
    legacy["metadata"]["version"] = "0.57"
    for group in FORM_DELIVERY_BACKUP_GROUPS:
        legacy["data"][group] = []
        legacy["metadata"]["table_counts"][group] = 0
    loaded = load_backup(_write_payload(tmp_path, legacy, "legacy-057-empty.json"))
    assert loaded["metadata"]["version"] == "0.57"
    assert all(not loaded["data"][group] for group in FORM_DELIVERY_BACKUP_GROUPS)

    nonempty = deepcopy(legacy)
    nonempty["data"]["website_form_delivery_mode_revisions"] = deepcopy(
        payload["data"]["website_form_delivery_mode_revisions"]
    )
    nonempty["metadata"]["table_counts"][
        "website_form_delivery_mode_revisions"
    ] = 2
    with pytest.raises(BackupValidationError, match="Legacy backup version"):
        load_backup(_write_payload(tmp_path, nonempty, "legacy-057-nonempty.json"))


def test_backup_058_exports_empty_form_groups_from_exact_0046_schema(
    tmp_path: Path,
) -> None:
    engine = _engine()
    _create_0046_shaped_schema(engine)
    with Session(engine) as session:
        exported = export_backup(session, backup_dir=tmp_path / "pre-0047-export")
        loaded = load_backup(Path(exported["path"]))
    engine.dispose()

    assert loaded["metadata"]["version"] == "0.58"
    assert all(not loaded["data"][group] for group in FORM_DELIVERY_BACKUP_GROUPS)
    assert all(
        loaded["metadata"]["table_counts"][group] == 0
        for group in FORM_DELIVERY_BACKUP_GROUPS
    )


def test_backup_058_refuses_partial_form_schema_before_creating_artifact(
    tmp_path: Path,
) -> None:
    engine = _engine()
    _create_0046_shaped_schema(engine)
    WebsiteFormDeliveryModeRevision.__table__.create(engine)
    destination = tmp_path / "partial-schema-export"
    with Session(engine) as session:
        with pytest.raises(
            BackupValidationError,
            match="partial universal form-delivery schema",
        ):
            export_backup(session, backup_dir=destination)
    engine.dispose()

    assert not destination.exists()


def test_backup_057_restores_into_exact_0046_schema_without_form_tables(
    tmp_path: Path,
) -> None:
    source_engine = _engine()
    _create_0046_shaped_schema(source_engine)
    with Session(source_engine) as session:
        exported = export_backup(session, backup_dir=tmp_path / "legacy-source")
        legacy = json.loads(Path(exported["path"]).read_text(encoding="utf-8"))
    source_engine.dispose()
    legacy["metadata"]["version"] = "0.57"
    for group in FORM_DELIVERY_BACKUP_GROUPS:
        legacy["data"].pop(group)
        legacy["metadata"]["table_counts"].pop(group)
    legacy_path = _write_payload(tmp_path, legacy, "legacy-057-pre-0047.json")

    target_engine = _engine()
    _create_0046_shaped_schema(target_engine)
    with Session(target_engine) as session:
        result = restore_backup(session, legacy_path)
        assert result["status"] == "restored"
        assert all(
            result["table_counts"][group] == 0
            for group in FORM_DELIVERY_BACKUP_GROUPS
        )
        available = set(sa_inspect(session.connection()).get_table_names())
    target_engine.dispose()

    assert not {
        model.__table__.key for model in FORM_DELIVERY_MODELS.values()
    } & available


def test_restore_cli_bootstraps_owned_metadata_only_for_unmanaged_targets() -> None:
    engine = _engine()
    assert _restore_target_requires_metadata_bootstrap(engine) is True
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
        )
    assert _restore_target_requires_metadata_bootstrap(engine) is False
    engine.dispose()


@pytest.mark.parametrize(
    "mutation",
    (
        "plaintext_envelope",
        "request_identity_plaintext",
        "audit_identity_plaintext",
        "anti_spam_plaintext",
        "adapter_identity_plaintext",
        "consent_version_plaintext",
        "source_page_plaintext",
        "literal_secret",
        "provider_identity",
        "cross_scope",
        "branched_lineage",
        "recipient_normalization",
        "recipient_scope",
        "recipient_wrong_mode_lineage",
        "lifecycle",
        "fingerprint",
        "outbox_attempt_count",
        "attempt_provider_reference",
        "attempt_error_code",
        "orphan_envelope",
        "queued_without_payload",
        "unsafe_audit_snapshot",
    ),
)
def test_backup_058_rejects_unsafe_or_inconsistent_form_delivery_graphs(
    tmp_path: Path,
    mutation: str,
) -> None:
    _, payload, _ = _export_complete_payload(tmp_path)
    candidate = deepcopy(payload)
    mode = candidate["data"]["website_form_delivery_mode_revisions"][1]
    recipient = candidate["data"]["website_form_recipient_revisions"][-1]
    envelope = candidate["data"]["form_submission_envelopes"][0]
    outbox = candidate["data"]["form_delivery_outbox_records"][0]
    attempt = candidate["data"]["form_delivery_attempts"][0]
    audit = candidate["data"]["form_delivery_configuration_audits"][0]

    if mutation == "plaintext_envelope":
        envelope["message"] = "Plaintext customer payload must never be backed up."
    elif mutation == "request_identity_plaintext":
        envelope["request_identity"] = "Synthetic Customer message"
        envelope["integrity_fingerprint"] = form_submission_envelope_fingerprint(
            envelope
        )
    elif mutation == "audit_identity_plaintext":
        envelope["audit_identity"] = "Synthetic Customer message"
        envelope["integrity_fingerprint"] = form_submission_envelope_fingerprint(
            envelope
        )
    elif mutation == "anti_spam_plaintext":
        envelope["anti_spam_decision"] = "Synthetic Customer message"
        envelope["integrity_fingerprint"] = form_submission_envelope_fingerprint(
            envelope
        )
    elif mutation == "adapter_identity_plaintext":
        envelope["destination_adapter_key"] = "Synthetic Customer message"
        envelope["integrity_fingerprint"] = form_submission_envelope_fingerprint(
            envelope
        )
    elif mutation == "consent_version_plaintext":
        envelope["consent_version"] = "Synthetic Customer message"
        envelope["integrity_fingerprint"] = form_submission_envelope_fingerprint(
            envelope
        )
    elif mutation == "source_page_plaintext":
        envelope["source_page_identity"] = "Synthetic Customer message"
        envelope["integrity_fingerprint"] = form_submission_envelope_fingerprint(
            envelope
        )
    elif mutation == "literal_secret":
        mode["configuration_payload"]["transport_secret_reference"] = (
            "literal-production-secret"
        )
        mode["integrity_fingerprint"] = form_delivery_mode_fingerprint(mode)
    elif mutation == "provider_identity":
        mode["provider_key"] = "tampered-provider"
        mode["integrity_fingerprint"] = form_delivery_mode_fingerprint(mode)
    elif mutation == "cross_scope":
        mode["form_component_configuration_id"] = 999999
        mode["integrity_fingerprint"] = form_delivery_mode_fingerprint(mode)
    elif mutation == "branched_lineage":
        mode["supersedes_delivery_mode_revision_id"] = None
        mode["integrity_fingerprint"] = form_delivery_mode_fingerprint(mode)
    elif mutation == "recipient_normalization":
        recipient["normalized_email"] = "wrong@example.com"
        recipient["integrity_fingerprint"] = form_recipient_fingerprint(recipient)
    elif mutation == "recipient_scope":
        recipient["form_instance_key"] = "compact-estimate-form:wrong-scope"
        recipient["integrity_fingerprint"] = form_recipient_fingerprint(recipient)
    elif mutation == "recipient_wrong_mode_lineage":
        successor = deepcopy(recipient)
        successor["id"] = 999998
        successor["revision"] = recipient["revision"] + 1
        successor["supersedes_recipient_revision_id"] = recipient["id"]
        successor["delivery_mode_revision_id"] = candidate["data"][
            "website_form_delivery_mode_revisions"
        ][0]["id"]
        successor["email"] = "synthetic.successor@example.com"
        successor["normalized_email"] = "synthetic.successor@example.com"
        successor["integrity_fingerprint"] = form_recipient_fingerprint(successor)
        candidate["data"]["website_form_recipient_revisions"].append(successor)
        candidate["metadata"]["table_counts"][
            "website_form_recipient_revisions"
        ] += 1
        recipient_audit = next(
            item
            for item in candidate["data"]["form_delivery_configuration_audits"]
            if item["recipient_revision_id"] == recipient["id"]
        )
        successor_audit = deepcopy(recipient_audit)
        successor_audit["id"] = 999999
        successor_audit["recipient_revision_id"] = successor["id"]
        successor_audit["snapshot"] = {
            **successor_audit["snapshot"],
            "target_id": successor["id"],
            "revision": successor["revision"],
            "integrity_fingerprint": successor["integrity_fingerprint"],
        }
        successor_audit["snapshot_hash"] = form_delivery_configuration_audit_hash(
            successor_audit
        )
        candidate["data"]["form_delivery_configuration_audits"].append(
            successor_audit
        )
        candidate["metadata"]["table_counts"][
            "form_delivery_configuration_audits"
        ] += 1
    elif mutation == "lifecycle":
        mode["lifecycle_status"] = "retired"
        mode["integrity_fingerprint"] = form_delivery_mode_fingerprint(mode)
    elif mutation == "fingerprint":
        mode["integrity_fingerprint"] = "0" * 64
    elif mutation == "outbox_attempt_count":
        outbox["attempt_count"] = 0
    elif mutation == "attempt_provider_reference":
        attempt["safe_provider_reference"] = "Synthetic Customer message"
        attempt["integrity_fingerprint"] = form_delivery_attempt_fingerprint(
            attempt
        )
    elif mutation == "attempt_error_code":
        attempt["outcome"] = "permanent_failure"
        attempt["safe_error_code"] = "Synthetic Customer message"
        attempt["safe_provider_reference"] = None
        attempt["integrity_fingerprint"] = form_delivery_attempt_fingerprint(
            attempt
        )
    elif mutation == "orphan_envelope":
        candidate["data"]["form_delivery_outbox_records"] = []
        candidate["data"]["form_delivery_attempts"] = []
        candidate["metadata"]["table_counts"]["form_delivery_outbox_records"] = 0
        candidate["metadata"]["table_counts"]["form_delivery_attempts"] = 0
    elif mutation == "queued_without_payload":
        envelope["secure_payload_reference"] = None
        envelope["encryption_key_reference"] = None
        envelope["integrity_fingerprint"] = form_submission_envelope_fingerprint(
            envelope
        )
        outbox.update(
            {
                "status": "queued",
                "attempt_count": 0,
                "next_attempt_at": None,
                "last_safe_error_code": None,
                "state_version": 1,
                "delivered_at": None,
                "failed_at": None,
                "expired_at": None,
            }
        )
        candidate["data"]["form_delivery_attempts"] = []
        candidate["metadata"]["table_counts"]["form_delivery_attempts"] = 0
    else:
        audit["snapshot"]["email"] = "customer@example.com"
        audit["snapshot_hash"] = form_delivery_configuration_audit_hash(audit)

    path = _write_payload(tmp_path, candidate, f"invalid-{mutation}.json")
    with pytest.raises(BackupValidationError):
        load_backup(path)


def test_backup_058_rejects_divergent_immutable_target_state(
    tmp_path: Path,
) -> None:
    source_path, _, _ = _export_complete_payload(tmp_path)
    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        restore_backup(session, source_path)
        recipient = session.exec(
            select(WebsiteFormRecipientRevision).order_by(
                WebsiteFormRecipientRevision.revision.desc()
            )
        ).first()
        assert recipient is not None
        recipient.label = "Divergent target label"
        session.add(recipient)
        session.commit()
        with pytest.raises(BackupValidationError, match="immutable state diverges"):
            restore_backup(session, source_path)
        session.refresh(recipient)
        assert recipient.label == "Divergent target label"
    target_engine.dispose()


def test_backup_058_rejects_divergent_exact_target_audit_and_rolls_back(
    tmp_path: Path,
) -> None:
    source_path, _, _ = _export_complete_payload(tmp_path)
    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        restore_backup(session, source_path)
        recipient = session.exec(
            select(WebsiteFormRecipientRevision).order_by(
                WebsiteFormRecipientRevision.revision.desc()
            )
        ).first()
        assert recipient is not None
        audit = session.exec(
            select(FormDeliveryConfigurationAudit).where(
                FormDeliveryConfigurationAudit.recipient_revision_id == recipient.id
            )
        ).one()
        audit.actor = "Divergent Audit Actor"
        audit.snapshot_hash = form_delivery_configuration_audit_hash(audit)
        session.add(audit)
        session.commit()

        with pytest.raises(BackupValidationError, match="immutable state diverges"):
            restore_backup(session, source_path)

        audits = list(session.exec(select(FormDeliveryConfigurationAudit)).all())
        assert len(audits) == 4
        assert next(item for item in audits if item.id == audit.id).actor == (
            "Divergent Audit Actor"
        )
    target_engine.dispose()


def test_backup_058_refuses_to_roll_back_a_newer_target_mode_lineage(
    tmp_path: Path,
) -> None:
    source_path, _, _ = _export_complete_payload(tmp_path)
    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        restore_backup(session, source_path)
        current = session.exec(
            select(WebsiteFormDeliveryModeRevision).where(
                WebsiteFormDeliveryModeRevision.revision == 2
            )
        ).one()
        create_form_delivery_mode_revision(
            session,
            current.website_id,
            WebsiteFormDeliveryModeRevisionCreate(
                form_component_configuration_id=current.form_component_configuration_id,
                form_instance_key=current.form_instance_key,
                supersedes_delivery_mode_revision_id=current.id,
                mode="disabled",
                enabled=False,
                configuration_payload={},
                audit_identity="newer-target-mode-audit",
                created_by="Form Backup Test Operator",
                updated_by="Form Backup Test Operator",
                rationale="Create newer target lineage that an older backup cannot replace.",
                **_active_evidence(),
            ),
        )
        with pytest.raises(BackupValidationError, match="newer than the backup"):
            restore_backup(session, source_path)
        revisions = list(
            session.exec(
                select(WebsiteFormDeliveryModeRevision.revision).order_by(
                    WebsiteFormDeliveryModeRevision.revision
                )
            ).all()
        )
        assert revisions == [1, 2, 3]
    target_engine.dispose()
