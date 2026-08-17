from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys

import pytest
from fastapi import HTTPException
from sqlalchemy import inspect
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import backup as backup_service
from app.db import session as db_session
from app.db.backup import (
    BACKUP_VERSION,
    BackupValidationError,
    export_backup,
    load_backup,
    restore_backup,
)
from app.models import (
    Business,
    Brand,
    GeneratedPage,
    PlannedPage,
    SitePlan,
    Theme,
    ThemeConfigurationAudit,
    ThemeFamily,
    ThemeFamilyVersion,
    Website,
    WebsiteThemeSelection,
    WebsiteThemeComponentConfiguration,
    WebsiteThemeConfiguration,
)
from app.schemas.page_export import ExportSEO, PageExportPackage
from app.schemas.themes import ThemeCreate
from app.schemas.theme_families import (
    PERFORMANCE_LOCAL_V2_COMPONENT_CONTRACTS,
    ThemeDraftBundleCreate,
    ThemeFamilyVersionCreate,
    WebsiteThemeComponentConfigurationCreate,
    WebsiteThemeComponentConfigurationRevisionCreate,
    WebsiteThemeConfigurationCreate,
    validate_component_payload,
)
from app.services.theme_configurations import (
    PERFORMANCE_LOCAL_V2_SOURCE_COMMIT,
    _append_audit,
    _component_fingerprint_from_record,
    _component_fingerprint_payload,
    _family_fingerprint_from_record,
    _family_fingerprint_payload,
    _family_version_fingerprint_from_record,
    _family_version_fingerprint_payload,
    _website_configuration_fingerprint_from_record,
    _website_configuration_fingerprint_payload,
    create_inactive_theme_draft_bundle,
    create_component_configuration,
    create_website_theme_configuration,
    register_theme_family,
    register_theme_family_version,
    revise_component_configuration,
    validate_theme_configuration_records,
)
from app.schemas.theme_families import ThemeFamilyCreate
from app.services import page_export
from app.services.themes import (
    DEFAULT_THEME_TOKENS,
    approve_theme,
    create_theme,
    retire_theme,
    select_website_theme,
)


THEME_MODELS = (
    ThemeFamily,
    ThemeFamilyVersion,
    WebsiteThemeConfiguration,
    WebsiteThemeComponentConfiguration,
    ThemeConfigurationAudit,
)


def _engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _write_payload(tmp_path: Path, payload: dict, name: str) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _compact_form_payload() -> dict:
    field_specs = (
        ("name", "Name", True, "input", "text", 1, "nonempty_text", 1, 120),
        ("phone", "Phone", True, "input", "tel", 2, "phone", 6, 40),
        (
            "postal-code",
            "ZIP code",
            True,
            "input",
            "text",
            3,
            "postal_code",
            5,
            12,
        ),
        (
            "requested-service",
            "Requested service",
            True,
            "input",
            "text",
            4,
            "nonempty_text",
            1,
            160,
        ),
        (
            "message",
            "Optional message",
            False,
            "textarea",
            "text",
            5,
            "free_text",
            0,
            1000,
        ),
    )
    return {
        "submission_state": "disabled_pending_provider_configuration",
        "fields": [
            {
                "field_key": key,
                "label": label,
                "required": required,
                "control": control,
                "input_type": input_type,
                "order": order,
                "accessibility_label": label,
                "autocomplete_policy": "off",
                "maximum_length": maximum_length,
                "validation_contract": {
                    "rule": rule,
                    "minimum_length": minimum_length,
                    "maximum_length": maximum_length,
                },
                "responsive_layout": "full" if key == "message" else "half",
                "provider_mapping": key,
            }
            for (
                key,
                label,
                required,
                control,
                input_type,
                order,
                rule,
                minimum_length,
                maximum_length,
            ) in field_specs
        ],
        "submit_label": "Request an estimate",
        "preview_notice": "Preview only. Submission delivery is not configured.",
        "provider_key": None,
        "destination": None,
        "privacy_policy_destination": None,
        "consent_language": None,
        "data_retention_policy": None,
        "spam_strategy": None,
        "success_behavior": None,
        "failure_behavior": None,
        "audit_identity": None,
    }


def _contract(component_key: str) -> dict:
    return next(
        item
        for item in PERFORMANCE_LOCAL_V2_COMPONENT_CONTRACTS
        if item["component_key"] == component_key
    )


def _draft_bundle() -> ThemeDraftBundleCreate:
    form_contract = _contract("compact_estimate_form")
    banner_contract = _contract("campaign_banner")
    sticky_contract = _contract("sticky_mobile_action_bar")
    return ThemeDraftBundleCreate.model_validate(
        {
            "theme_family": {
                "family_key": "performance-local",
                "display_name": "Performance Local",
                "description": "Reusable local-service performance Theme family.",
                "provider_source_identity": "atlas-source:performance-local-v2",
                "created_by": "backup-test-operator",
            },
            "theme_version": {
                "version": 2,
                "lifecycle_status": "preview_candidate",
                "production_ready": False,
                "source_commit": PERFORMANCE_LOCAL_V2_SOURCE_COMMIT,
                "supported_component_contracts": list(
                    PERFORMANCE_LOCAL_V2_COMPONENT_CONTRACTS
                ),
                "created_by": "backup-test-operator",
            },
            "website_configuration": {
                "configuration_key": "performance-local-preview",
                "created_by": "backup-test-operator",
                "creation_rationale": "Exercise exact durable backup and restore identity.",
            },
            "components": [
                {
                    "component_instance_key": "estimate-form",
                    "component_key": "compact_estimate_form",
                    "component_contract_version": 2,
                    "enabled": True,
                    "variant": form_contract["variant"],
                    "placement": form_contract["placement"],
                    "responsive_visibility": form_contract[
                        "responsive_visibility"
                    ],
                    "configuration_payload": _compact_form_payload(),
                    "approval_identity": "backup-test-form-approval",
                    "created_by": "backup-test-operator",
                },
                {
                    "component_instance_key": "campaign-banner",
                    "component_key": "campaign_banner",
                    "component_contract_version": 2,
                    "enabled": True,
                    "variant": banner_contract["variant"],
                    "placement": banner_contract["placement"],
                    "responsive_visibility": banner_contract[
                        "responsive_visibility"
                    ],
                    "configuration_payload": {
                        "intent": "evergreen_conversion",
                        "message": "Request a local service estimate.",
                        "cta_label": "Request an estimate",
                        "approval_identity": "backup-test-banner-approval",
                    },
                    "approval_identity": "backup-test-banner-approval",
                    "created_by": "backup-test-operator",
                    "destination_component_instance_key": "estimate-form",
                },
                {
                    "component_instance_key": "sticky-actions",
                    "component_key": "sticky_mobile_action_bar",
                    "component_contract_version": 2,
                    "enabled": True,
                    "variant": sticky_contract["variant"],
                    "placement": sticky_contract["placement"],
                    "responsive_visibility": sticky_contract[
                        "responsive_visibility"
                    ],
                    "configuration_payload": {
                        "call_source": "governed_website_identity",
                        "call_label": "Call",
                        "estimate_label": "Request an estimate",
                        "desktop_sticky_header": False,
                        "mobile_sticky_bottom": True,
                        "hide_while_hero_actions_visible": True,
                        "hide_while_navigation_open": True,
                        "protect_form_focus": True,
                        "safe_area_support": True,
                        "prevent_content_obstruction": True,
                    },
                    "approval_identity": "backup-test-sticky-approval",
                    "created_by": "backup-test-operator",
                    "destination_component_instance_key": "estimate-form",
                },
            ],
        }
    )


def _seed_bundle(
    session: Session,
    *,
    company_name: str = "Backup Theme Company",
    domain: str = "backup-theme.test",
) -> dict[str, int]:
    business = Business(
        company_name=company_name,
        business_type="Local service company",
        state="FL",
        phone="(407) 555-0142",
    )
    session.add(business)
    session.flush()
    brand = Brand(
        business_id=business.id,
        brand_name=f"{company_name} Brand",
        status="active",
    )
    session.add(brand)
    session.flush()
    website = Website(
        business_id=business.id,
        brand_id=brand.id,
        website_name=f"{company_name} Website",
        domain=domain,
        public_url=f"https://{domain}",
        status="active",
    )
    session.add(website)
    session.commit()
    preview = create_inactive_theme_draft_bundle(
        session,
        website.id,
        _draft_bundle(),
    )
    return {
        "business_id": business.id,
        "website_id": website.id,
        "family_id": preview.theme_family.id,
        "version_id": preview.theme_version.id,
        "configuration_id": preview.website_configuration.id,
    }


def _theme_records(session: Session) -> dict[str, list[dict]]:
    return {
        model.__tablename__: [
            row.model_dump(mode="json")
            for row in session.exec(select(model).order_by(model.id)).all()
        ]
        for model in THEME_MODELS
    }


def _activate_theme_graph(
    session: Session,
    source_ids: dict[str, int],
) -> tuple[Theme, WebsiteThemeSelection]:
    theme = create_theme(
        session,
        source_ids["website_id"],
        ThemeCreate(
            theme_key="performance-local",
            theme_name="Performance Local Materialized",
            description="Test-only materialized Theme identity.",
            token_contract_version=1,
            design_tokens=DEFAULT_THEME_TOKENS.model_copy(deep=True),
            created_by="backup-test-theme-operator",
            provenance_type="operator_configured",
            provenance_notes="Created only in disposable backup lifecycle tests.",
        ),
    )
    theme = approve_theme(
        session,
        theme.id,
        approved_by="backup-test-theme-approver",
    )
    selection = select_website_theme(
        session,
        source_ids["website_id"],
        theme_id=theme.id,
        selected_by="backup-test-theme-selector",
        rationale="Bind exact active Theme identity for backup lifecycle testing.",
    )
    theme_id = theme.id
    selection_id = selection.id
    now = datetime.now(UTC)
    version = session.get(ThemeFamilyVersion, source_ids["version_id"])
    configuration = session.get(
        WebsiteThemeConfiguration,
        source_ids["configuration_id"],
    )
    assert version is not None
    assert configuration is not None
    version.lifecycle_status = "approved"
    version.production_ready = True
    version.updated_at = now
    version.integrity_fingerprint = _family_version_fingerprint_from_record(
        version
    )
    configuration.lifecycle_status = "active"
    configuration.updated_by = "backup-test-configuration-activator"
    configuration.approved_by = "backup-test-configuration-approver"
    configuration.approved_at = now
    configuration.activated_by = "backup-test-configuration-activator"
    configuration.activated_at = now
    configuration.materialized_theme_id = theme_id
    configuration.website_theme_selection_id = selection_id
    configuration.integrity_fingerprint = (
        _website_configuration_fingerprint_from_record(configuration)
    )
    session.add(version)
    session.add(configuration)
    components = list(
        session.exec(
            select(WebsiteThemeComponentConfiguration).where(
                WebsiteThemeComponentConfiguration.website_theme_configuration_id
                == configuration.id,
                WebsiteThemeComponentConfiguration.lifecycle_status == "current",
            )
        ).all()
    )
    for component in components:
        component.updated_by = "backup-test-component-activator"
        component.activation_identity = "backup-test-component-activation"
        component.activated_at = now
        component.integrity_fingerprint = _component_fingerprint_from_record(
            component
        )
        session.add(component)
    _append_audit(
        session,
        action_type="family_version_approved",
        actor="backup-test-version-approver",
        rationale="Exercise approved Theme Family Version backup identity.",
        snapshot=_family_version_fingerprint_payload(version),
        theme_family_version_id=version.id,
    )
    _append_audit(
        session,
        action_type="website_configuration_approved",
        actor="backup-test-configuration-approver",
        rationale="Exercise approved Website Theme configuration backup identity.",
        snapshot=_website_configuration_fingerprint_payload(configuration),
        website_theme_configuration_id=configuration.id,
    )
    _append_audit(
        session,
        action_type="website_configuration_activated",
        actor="backup-test-configuration-activator",
        rationale="Exercise active Website Theme configuration backup identity.",
        snapshot=_website_configuration_fingerprint_payload(configuration),
        website_theme_configuration_id=configuration.id,
    )
    for component in components:
        _append_audit(
            session,
            action_type="component_activated",
            actor="backup-test-component-activator",
            rationale="Exercise active Theme component backup identity.",
            snapshot=_component_fingerprint_payload(component),
            component_configuration_id=component.id,
        )
    session.commit()
    return theme, selection


def _retire_theme_graph(
    session: Session,
    source_ids: dict[str, int],
    theme: Theme,
    selection: WebsiteThemeSelection,
) -> None:
    now = datetime.now(UTC)
    selection.status = "retired"
    selection.replaced_at = now
    session.add(selection)
    session.commit()
    retire_theme(
        session,
        theme.id,
        retired_by="backup-test-theme-retirer",
        rationale="Exercise retired Theme backup identity.",
    )

    family = session.get(ThemeFamily, source_ids["family_id"])
    version = session.get(ThemeFamilyVersion, source_ids["version_id"])
    configuration = session.get(
        WebsiteThemeConfiguration,
        source_ids["configuration_id"],
    )
    assert family is not None
    assert version is not None
    assert configuration is not None
    family.lifecycle_status = "retired"
    family.retired_by = "backup-test-family-retirer"
    family.retired_at = now
    family.integrity_fingerprint = _family_fingerprint_from_record(family)
    version.lifecycle_status = "retired"
    version.production_ready = False
    version.retired_by = "backup-test-version-retirer"
    version.retired_at = now
    version.integrity_fingerprint = _family_version_fingerprint_from_record(
        version
    )
    configuration.lifecycle_status = "retired"
    configuration.updated_by = "backup-test-configuration-retirer"
    configuration.updated_at = now
    configuration.rollback_by = "backup-test-configuration-rollback"
    configuration.rollback_at = now
    configuration.integrity_fingerprint = (
        _website_configuration_fingerprint_from_record(configuration)
    )
    session.add(family)
    session.add(version)
    session.add(configuration)
    components = list(
        session.exec(
            select(WebsiteThemeComponentConfiguration).where(
                WebsiteThemeComponentConfiguration.website_theme_configuration_id
                == configuration.id,
                WebsiteThemeComponentConfiguration.lifecycle_status == "current",
            )
        ).all()
    )
    for component in components:
        component.updated_by = "backup-test-component-rollback"
        component.updated_at = now
        component.rollback_identity = "backup-test-component-rollback"
        component.rollback_at = now
        component.integrity_fingerprint = _component_fingerprint_from_record(
            component
        )
        session.add(component)
    _append_audit(
        session,
        action_type="website_configuration_rolled_back",
        actor="backup-test-configuration-rollback",
        rationale="Exercise rolled-back Website Theme configuration backup identity.",
        snapshot=_website_configuration_fingerprint_payload(configuration),
        website_theme_configuration_id=configuration.id,
    )
    _append_audit(
        session,
        action_type="website_configuration_retired",
        actor="backup-test-configuration-retirer",
        rationale="Exercise retired Website Theme configuration backup identity.",
        snapshot=_website_configuration_fingerprint_payload(configuration),
        website_theme_configuration_id=configuration.id,
    )
    for component in components:
        _append_audit(
            session,
            action_type="component_rolled_back",
            actor="backup-test-component-rollback",
            rationale="Exercise rolled-back Theme component backup identity.",
            snapshot=_component_fingerprint_payload(component),
            component_configuration_id=component.id,
        )
    _append_audit(
        session,
        action_type="family_retired",
        actor="backup-test-family-retirer",
        rationale="Exercise retired Theme Family backup identity.",
        snapshot=_family_fingerprint_payload(family),
        theme_family_id=family.id,
    )
    _append_audit(
        session,
        action_type="family_version_retired",
        actor="backup-test-version-retirer",
        rationale="Exercise retired Theme Family Version backup identity.",
        snapshot=_family_version_fingerprint_payload(version),
        theme_family_version_id=version.id,
    )
    session.commit()


def test_backup_057_round_trip_preserves_inactive_theme_graph_exactly_and_replays(
    tmp_path: Path,
) -> None:
    assert BACKUP_VERSION == "0.58"
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        source_ids = _seed_bundle(session)
        source_records = _theme_records(session)
        exported = export_backup(session, backup_dir=tmp_path)
        loaded = load_backup(Path(exported["path"]))

    assert loaded["metadata"]["version"] == "0.58"
    expected_theme_counts = {
        "theme_families": 1,
        "theme_family_versions": 1,
        "website_theme_configurations": 1,
        "website_theme_component_configurations": 3,
        "theme_configuration_audits": 6,
    }
    assert {
        group: loaded["metadata"]["table_counts"][group]
        for group in expected_theme_counts
    } == expected_theme_counts

    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        first = restore_backup(session, exported["path"])
        assert first["status"] == "restored"
        assert _theme_records(session) == source_records
        assert validate_theme_configuration_records(session) == {
            "theme_families": 1,
            "theme_family_versions": 1,
            "website_theme_configurations": 1,
            "website_theme_component_configurations": 3,
            "theme_configuration_audits": 6,
        }
        family_version = session.get(ThemeFamilyVersion, source_ids["version_id"])
        configuration = session.get(
            WebsiteThemeConfiguration,
            source_ids["configuration_id"],
        )
        assert family_version is not None
        assert family_version.lifecycle_status == "preview_candidate"
        assert family_version.production_ready is False
        assert configuration is not None
        assert configuration.lifecycle_status == "draft"
        assert configuration.materialized_theme_id is None
        assert configuration.website_theme_selection_id is None

        second = restore_backup(session, exported["path"])
        assert second["status"] == "restored"
        assert _theme_records(session) == source_records


def test_backup_057_cli_restore_creates_migration_owned_tables_only_after_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        _seed_bundle(session)
        exported = export_backup(session, backup_dir=tmp_path)

    target_engine = _engine()
    assert inspect(target_engine).get_table_names() == []
    monkeypatch.setattr(db_session, "engine", target_engine)
    monkeypatch.setattr(backup_service, "engine", target_engine)
    monkeypatch.setattr(
        sys,
        "argv",
        ["atlas-backup", "restore", exported["path"]],
    )

    backup_service.main()

    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "restored"
    assert db_session.ALEMBIC_OWNED_DURABLE_THEME_TABLES <= set(
        inspect(target_engine).get_table_names()
    )
    with Session(target_engine) as session:
        assert validate_theme_configuration_records(session) == {
            "theme_families": 1,
            "theme_family_versions": 1,
            "website_theme_configurations": 1,
            "website_theme_component_configurations": 3,
            "theme_configuration_audits": 6,
        }


def test_backup_057_cli_restore_accepts_canonical_backup_basename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        _seed_bundle(session)
        exported = export_backup(session, backup_dir=tmp_path)

    target_engine = _engine()
    monkeypatch.setattr(db_session, "engine", target_engine)
    monkeypatch.setattr(backup_service, "engine", target_engine)
    monkeypatch.setattr(backup_service, "BACKUP_DIR", tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["atlas-backup", "restore", exported["file_name"]],
    )

    backup_service.main()

    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "restored"
    assert result["file_name"] == exported["file_name"]
    with Session(target_engine) as session:
        assert validate_theme_configuration_records(session)[
            "website_theme_configurations"
        ] == 1


def test_backup_057_cli_restore_rejects_invalid_payload_before_schema_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        _seed_bundle(session)
        exported = export_backup(session, backup_dir=tmp_path)
    payload = json.loads(Path(exported["path"]).read_text(encoding="utf-8"))
    payload["data"]["theme_configuration_audits"][0]["snapshot_hash"] = "0" * 64
    invalid_path = _write_payload(tmp_path, payload, "invalid-restore.json")

    target_engine = _engine()
    assert inspect(target_engine).get_table_names() == []
    monkeypatch.setattr(db_session, "engine", target_engine)
    monkeypatch.setattr(backup_service, "engine", target_engine)
    monkeypatch.setattr(
        sys,
        "argv",
        ["atlas-backup", "restore", str(invalid_path)],
    )

    with pytest.raises(SystemExit) as caught:
        backup_service.main()

    assert caught.value.code == 1
    assert inspect(target_engine).get_table_names() == []
    assert "Theme configuration audit identity or hash is invalid" in (
        capsys.readouterr().err
    )


def test_backup_057_nonempty_restore_remaps_theme_graph_and_replays(
    tmp_path: Path,
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        _seed_bundle(session)
        exported = export_backup(session, backup_dir=tmp_path)

    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        filler_business = Business(
            company_name="Filler Company",
            business_type="Local service company",
            state="FL",
        )
        session.add(filler_business)
        session.flush()
        session.add(
            Website(
                business_id=filler_business.id,
                website_name="Filler Website",
                domain="filler.test",
                public_url="https://filler.test",
                status="active",
            )
        )
        session.commit()
        filler_family = register_theme_family(
            session,
            ThemeFamilyCreate(
                family_key="filler-family",
                display_name="Filler Family",
                description="Forces a nonempty-target Theme identity remap.",
                provider_source_identity="backup-test:filler-family",
                created_by="backup-test-operator",
            ),
        )
        assert filler_family.id == 1

        restore_backup(session, exported["path"])
        restored_family = session.exec(
            select(ThemeFamily).where(
                ThemeFamily.family_key == "performance-local"
            )
        ).one()
        restored_configuration = session.exec(
            select(WebsiteThemeConfiguration).where(
                WebsiteThemeConfiguration.configuration_key
                == "performance-local-preview"
            )
        ).one()
        assert restored_family.id != 1
        assert restored_configuration.website_id != 1
        assert validate_theme_configuration_records(session) == {
            "theme_families": 2,
            "theme_family_versions": 1,
            "website_theme_configurations": 1,
            "website_theme_component_configurations": 3,
            "theme_configuration_audits": 7,
        }
        first_records = _theme_records(session)

        restore_backup(session, exported["path"])
        assert _theme_records(session) == first_records


def test_backup_057_nonempty_restore_rejects_divergent_durable_theme_identity(
    tmp_path: Path,
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        _seed_bundle(session)
        exported = export_backup(session, backup_dir=tmp_path)

    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        restore_backup(session, exported["path"])
        family = session.exec(
            select(ThemeFamily).where(
                ThemeFamily.family_key == "performance-local"
            )
        ).one()
        family.description = "A valid but divergent governed target identity."
        family.integrity_fingerprint = _family_fingerprint_from_record(family)
        divergent_fingerprint = family.integrity_fingerprint
        session.add(family)
        session.commit()

        with pytest.raises(
            BackupValidationError,
            match="Target Theme Family immutable state diverges",
        ):
            restore_backup(session, exported["path"])

        session.expire_all()
        preserved = session.get(ThemeFamily, family.id)
        assert preserved is not None
        assert preserved.description == (
            "A valid but divergent governed target identity."
        )
        assert preserved.integrity_fingerprint == divergent_fingerprint


def test_backup_057_preserves_configuration_and_component_lineage(
    tmp_path: Path,
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        source_ids = _seed_bundle(session)
        banner = session.exec(
            select(WebsiteThemeComponentConfiguration).where(
                WebsiteThemeComponentConfiguration.component_key
                == "campaign_banner"
            )
        ).one()
        replacement = revise_component_configuration(
            session,
            source_ids["website_id"],
            source_ids["configuration_id"],
            banner.id,
            WebsiteThemeComponentConfigurationRevisionCreate(
                enabled=banner.enabled,
                variant=banner.variant,
                placement=banner.placement,
                responsive_visibility=banner.responsive_visibility,
                configuration_payload={
                    **banner.configuration_payload,
                    "message": "Request a governed local estimate.",
                },
                effective_at=banner.effective_at,
                expires_at=banner.expires_at,
                approval_identity=banner.approval_identity,
                updated_by="backup-test-revision-operator",
                revision_rationale="Exercise component revision backup lineage.",
                destination_component_configuration_id=(
                    banner.destination_component_configuration_id
                ),
            ),
        )
        plan = SitePlan(
            website_id=source_ids["website_id"],
            plan_key="theme-backup-lineage",
            plan_name="Theme Backup Lineage",
            status="active",
            version=1,
        )
        session.add(plan)
        session.flush()
        planned_page = PlannedPage(
            website_id=source_ids["website_id"],
            site_plan_id=plan.id,
            page_type="home",
            working_name="Theme Override Test",
            intended_slug="theme-override-test",
            planning_status="planned",
        )
        session.add(planned_page)
        session.commit()
        page_override = create_component_configuration(
            session,
            source_ids["website_id"],
            source_ids["configuration_id"],
            WebsiteThemeComponentConfigurationCreate(
                component_instance_key="campaign-banner:page-override",
                component_key="campaign_banner",
                component_contract_version=2,
                scope_type="page_override",
                planned_page_id=planned_page.id,
                enabled=True,
                variant=replacement.variant,
                placement=replacement.placement,
                responsive_visibility=replacement.responsive_visibility,
                configuration_payload={
                    **replacement.configuration_payload,
                    "message": "Request a Page-scoped governed estimate.",
                },
                approval_identity=replacement.approval_identity,
                created_by="backup-test-page-override-operator",
                destination_component_configuration_id=(
                    replacement.destination_component_configuration_id
                ),
                overrides_component_configuration_id=replacement.id,
            ),
        )
        successor = create_website_theme_configuration(
            session,
            source_ids["website_id"],
            WebsiteThemeConfigurationCreate(
                theme_family_version_id=source_ids["version_id"],
                configuration_key="performance-local-preview",
                created_by="backup-test-successor-operator",
                creation_rationale="Exercise Website configuration backup lineage.",
                supersedes_configuration_id=source_ids["configuration_id"],
            ),
        )
        assert replacement.revision == 2
        assert page_override.scope_type == "page_override"
        assert successor.version == 2
        source_records = _theme_records(session)
        exported = export_backup(session, backup_dir=tmp_path)

    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        restore_backup(session, exported["path"])
        assert _theme_records(session) == source_records
        configurations = list(
            session.exec(
                select(WebsiteThemeConfiguration).order_by(
                    WebsiteThemeConfiguration.version
                )
            ).all()
        )
        components = list(
            session.exec(
                select(WebsiteThemeComponentConfiguration).where(
                    WebsiteThemeComponentConfiguration.component_key
                    == "campaign_banner",
                    WebsiteThemeComponentConfiguration.scope_type
                    == "website_default",
                ).order_by(WebsiteThemeComponentConfiguration.revision)
            ).all()
        )
        assert [item.lifecycle_status for item in configurations] == [
            "superseded",
            "draft",
        ]
        assert configurations[1].supersedes_configuration_id == configurations[0].id
        assert [item.lifecycle_status for item in components] == [
            "superseded",
            "current",
        ]
        assert components[1].supersedes_component_configuration_id == components[0].id
        restored_override = session.exec(
            select(WebsiteThemeComponentConfiguration).where(
                WebsiteThemeComponentConfiguration.scope_type == "page_override"
            )
        ).one()
        assert restored_override.overrides_component_configuration_id == components[1].id
        assert restored_override.destination_component_configuration_id is not None
        assert validate_theme_configuration_records(session) == {
            "theme_families": 1,
            "theme_family_versions": 1,
            "website_theme_configurations": 2,
            "website_theme_component_configurations": 5,
            "theme_configuration_audits": 11,
        }

        restore_backup(session, exported["path"])
        assert _theme_records(session) == source_records


def test_backup_057_preserves_approved_active_theme_lifecycle_exactly(
    tmp_path: Path,
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        source_ids = _seed_bundle(session)
        theme, selection = _activate_theme_graph(session, source_ids)
        source_records = _theme_records(session)
        exported = export_backup(session, backup_dir=tmp_path)
        source_theme_identity = theme.model_dump(mode="json")
        source_selection_identity = selection.model_dump(mode="json")

    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        restore_backup(session, exported["path"])
        assert _theme_records(session) == source_records
        version = session.get(ThemeFamilyVersion, source_ids["version_id"])
        configuration = session.get(
            WebsiteThemeConfiguration,
            source_ids["configuration_id"],
        )
        restored_theme = session.get(Theme, theme.id)
        restored_selection = session.get(WebsiteThemeSelection, selection.id)
        assert version is not None
        assert version.lifecycle_status == "approved"
        assert version.production_ready is True
        assert configuration is not None
        assert configuration.lifecycle_status == "active"
        assert configuration.approved_by is not None
        assert configuration.activated_by is not None
        assert configuration.rollback_by is None
        assert configuration.materialized_theme_id == theme.id
        assert configuration.website_theme_selection_id == selection.id
        assert restored_theme is not None
        assert restored_theme.model_dump(mode="json") == source_theme_identity
        assert restored_selection is not None
        assert restored_selection.model_dump(mode="json") == (
            source_selection_identity
        )
        assert all(
            record.activation_identity == "backup-test-component-activation"
            and record.activated_at is not None
            and record.rollback_identity is None
            for record in session.exec(
                select(WebsiteThemeComponentConfiguration).where(
                    WebsiteThemeComponentConfiguration.lifecycle_status == "current"
                )
            ).all()
        )

        restore_backup(session, exported["path"])
        assert _theme_records(session) == source_records


def test_backup_057_preserves_retired_and_rollback_lifecycle_exactly(
    tmp_path: Path,
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        source_ids = _seed_bundle(session)
        theme, selection = _activate_theme_graph(session, source_ids)
        _retire_theme_graph(session, source_ids, theme, selection)
        source_records = _theme_records(session)
        exported = export_backup(session, backup_dir=tmp_path)

    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        restore_backup(session, exported["path"])
        assert _theme_records(session) == source_records
        family = session.get(ThemeFamily, source_ids["family_id"])
        version = session.get(ThemeFamilyVersion, source_ids["version_id"])
        configuration = session.get(
            WebsiteThemeConfiguration,
            source_ids["configuration_id"],
        )
        assert family is not None
        assert family.lifecycle_status == "retired"
        assert family.retired_by is not None
        assert family.retired_at is not None
        assert version is not None
        assert version.lifecycle_status == "retired"
        assert version.production_ready is False
        assert version.retired_by is not None
        assert version.retired_at is not None
        assert configuration is not None
        assert configuration.lifecycle_status == "retired"
        assert configuration.rollback_by is not None
        assert configuration.rollback_at is not None
        assert all(
            record.rollback_identity == "backup-test-component-rollback"
            and record.rollback_at is not None
            for record in session.exec(
                select(WebsiteThemeComponentConfiguration).where(
                    WebsiteThemeComponentConfiguration.lifecycle_status == "current"
                )
            ).all()
        )
        assert validate_theme_configuration_records(session)[
            "theme_configuration_audits"
        ] == 19

        restore_backup(session, exported["path"])
        assert _theme_records(session) == source_records


def test_backup_057_rejects_lifecycle_evidence_tampering(
    tmp_path: Path,
) -> None:
    active_engine = _engine()
    SQLModel.metadata.create_all(active_engine)
    with Session(active_engine) as session:
        source_ids = _seed_bundle(session)
        _activate_theme_graph(session, source_ids)
        active_export = export_backup(session, backup_dir=tmp_path)
    active_payload = load_backup(Path(active_export["path"]))

    active_selection_tamper = deepcopy(active_payload)
    active_selection_tamper["data"]["website_theme_selections"][0][
        "status"
    ] = "replaced"
    active_activation_tamper = deepcopy(active_payload)
    active_activation_tamper["data"]["website_theme_configurations"][0][
        "activated_at"
    ] = None
    active_component_tamper = deepcopy(active_payload)
    active_component_tamper["data"][
        "website_theme_component_configurations"
    ][0]["rollback_identity"] = "unpaired-rollback"

    source_commit_tamper = deepcopy(active_payload)
    source_version = source_commit_tamper["data"]["theme_family_versions"][0]
    source_version["source_commit"] = "f" * 40
    source_version["integrity_fingerprint"] = backup_service._canonical_json_hash(
        backup_service._theme_family_version_fingerprint_payload(source_version)
    )

    binding_tamper = deepcopy(active_payload)
    original_theme = binding_tamper["data"]["themes"][0]
    forged_theme = deepcopy(original_theme)
    forged_theme["id"] = original_theme["id"] + 1000
    forged_theme["theme_key"] = "forged-family"
    forged_theme["created_at"] = original_theme["created_at"]
    forged_theme["updated_at"] = original_theme["updated_at"]
    binding_tamper["data"]["themes"].append(forged_theme)
    original_selection = binding_tamper["data"]["website_theme_selections"][0]
    forged_selection = deepcopy(original_selection)
    forged_selection["id"] = original_selection["id"] + 1000
    forged_selection["theme_id"] = forged_theme["id"]
    forged_selection["version"] = original_selection["version"] + 1
    forged_selection["status"] = "retired"
    binding_tamper["data"]["website_theme_selections"].append(forged_selection)
    bound_configuration = binding_tamper["data"][
        "website_theme_configurations"
    ][0]
    bound_configuration["materialized_theme_id"] = forged_theme["id"]
    bound_configuration["website_theme_selection_id"] = forged_selection["id"]
    bound_configuration["integrity_fingerprint"] = (
        backup_service._canonical_json_hash(
            backup_service._website_theme_configuration_fingerprint_payload(
                bound_configuration
            )
        )
    )
    binding_tamper["metadata"]["table_counts"]["themes"] += 1
    binding_tamper["metadata"]["table_counts"][
        "website_theme_selections"
    ] += 1

    chronology_tamper = deepcopy(active_payload)
    chronology_configuration = chronology_tamper["data"][
        "website_theme_configurations"
    ][0]
    chronology_configuration["approved_at"] = (
        datetime.fromisoformat(chronology_configuration["created_at"])
        - timedelta(days=1)
    ).isoformat()
    chronology_configuration["integrity_fingerprint"] = (
        backup_service._canonical_json_hash(
            backup_service._website_theme_configuration_fingerprint_payload(
                chronology_configuration
            )
        )
    )

    retired_engine = _engine()
    SQLModel.metadata.create_all(retired_engine)
    with Session(retired_engine) as session:
        retired_ids = _seed_bundle(
            session,
            company_name="Retired Tamper Company",
            domain="retired-tamper.test",
        )
        theme, selection = _activate_theme_graph(session, retired_ids)
        _retire_theme_graph(session, retired_ids, theme, selection)
        retired_export = export_backup(session, backup_dir=tmp_path)
    retired_payload = load_backup(Path(retired_export["path"]))
    retired_pair_tamper = deepcopy(retired_payload)
    retired_pair_tamper["data"]["theme_families"][0]["retired_at"] = None
    retired_audit_tamper = deepcopy(retired_payload)
    retired_audits = retired_audit_tamper["data"][
        "theme_configuration_audits"
    ]
    retired_audit_tamper["data"]["theme_configuration_audits"] = [
        record
        for record in retired_audits
        if record["action_type"] != "family_version_retired"
    ]
    retired_audit_tamper["metadata"]["table_counts"][
        "theme_configuration_audits"
    ] -= 1

    expected_messages = {
        "source-commit": "source commit or contract is not canonical",
        "materialized-binding": "exact governed Theme-selection identity",
        "chronology": "approval precedes its creation",
    }
    for name, payload in (
        ("active-selection", active_selection_tamper),
        ("active-activation", active_activation_tamper),
        ("active-component", active_component_tamper),
        ("source-commit", source_commit_tamper),
        ("materialized-binding", binding_tamper),
        ("chronology", chronology_tamper),
        ("retired-pair", retired_pair_tamper),
        ("retired-audit", retired_audit_tamper),
    ):
        with pytest.raises(
            BackupValidationError,
            match=expected_messages.get(name),
        ):
            load_backup(_write_payload(tmp_path, payload, f"{name}.json"))


def test_backup_057_rejects_rehashed_family_version_lineage_chronology(
    tmp_path: Path,
) -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        family = register_theme_family(
            session,
            ThemeFamilyCreate(
                family_key="backup-chronology-family",
                display_name="Backup Chronology Family",
                description="Disposable backup lineage chronology fixture.",
                provider_source_identity="test-only",
                created_by="backup-test-operator",
            ),
        )
        contracts = list(PERFORMANCE_LOCAL_V2_COMPONENT_CONTRACTS)
        predecessor_contracts = [
            {**deepcopy(item), "contract_version": 1} for item in contracts
        ]
        predecessor = register_theme_family_version(
            session,
            family.id,
            ThemeFamilyVersionCreate(
                version=1,
                source_commit="a" * 40,
                supported_component_contracts=predecessor_contracts,
                created_by="backup-test-operator",
            ),
        )
        successor = register_theme_family_version(
            session,
            family.id,
            ThemeFamilyVersionCreate(
                version=2,
                source_commit="b" * 40,
                supported_component_contracts=contracts,
                created_by="backup-test-operator",
                supersedes_theme_family_version_id=predecessor.id,
            ),
        )
        exported = export_backup(session, backup_dir=tmp_path)
    payload = load_backup(Path(exported["path"]))
    versions = payload["data"]["theme_family_versions"]
    predecessor_record = next(item for item in versions if item["version"] == 1)
    successor_record = next(item for item in versions if item["version"] == 2)
    predecessor_record["updated_at"] = (
        datetime.fromisoformat(successor_record["created_at"]) + timedelta(days=1)
    ).isoformat()
    predecessor_record["integrity_fingerprint"] = (
        backup_service._canonical_json_hash(
            backup_service._theme_family_version_fingerprint_payload(
                predecessor_record
            )
        )
    )

    with pytest.raises(BackupValidationError, match="predates predecessor transition"):
        load_backup(
            _write_payload(
                tmp_path,
                payload,
                "family-version-chronology-tamper.json",
            )
        )


def test_backup_057_rejects_theme_tampering_before_restore_mutation(
    tmp_path: Path,
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        _seed_bundle(session)
        exported = export_backup(session, backup_dir=tmp_path)
    payload = load_backup(Path(exported["path"]))

    component_records = payload["data"][
        "website_theme_component_configurations"
    ]
    banner_index = next(
        index
        for index, record in enumerate(component_records)
        if record["component_key"] == "campaign_banner"
    )
    sticky = next(
        record
        for record in component_records
        if record["component_key"] == "sticky_mobile_action_bar"
    )
    form_index = next(
        index
        for index, record in enumerate(component_records)
        if record["component_key"] == "compact_estimate_form"
    )

    tampered_payloads: list[tuple[str, dict]] = []
    fingerprint_tamper = deepcopy(payload)
    fingerprint_tamper["data"]["theme_families"][0][
        "integrity_fingerprint"
    ] = "0" * 64
    tampered_payloads.append(("fingerprint", fingerprint_tamper))

    ownership_tamper = deepcopy(payload)
    ownership_tamper["data"]["website_theme_configurations"][0][
        "business_id"
    ] = 999_999
    tampered_payloads.append(("ownership", ownership_tamper))

    destination_tamper = deepcopy(payload)
    destination_tamper["data"]["website_theme_component_configurations"][
        banner_index
    ]["destination_component_configuration_id"] = sticky["id"]
    tampered_payloads.append(("destination", destination_tamper))

    provider_tamper = deepcopy(payload)
    provider_tamper["data"]["website_theme_component_configurations"][
        form_index
    ]["configuration_payload"]["provider_key"] = "not-authorized"
    tampered_payloads.append(("provider", provider_tamper))

    audit_tamper = deepcopy(payload)
    audit_tamper["data"]["theme_configuration_audits"][0][
        "snapshot_hash"
    ] = "f" * 64
    tampered_payloads.append(("audit", audit_tamper))

    updater_tamper = deepcopy(payload)
    updater_configuration = updater_tamper["data"][
        "website_theme_configurations"
    ][0]
    updater_configuration["updated_by"] = " "
    updater_configuration["integrity_fingerprint"] = (
        backup_service._canonical_json_hash(
            backup_service._website_theme_configuration_fingerprint_payload(
                updater_configuration
            )
        )
    )
    tampered_payloads.append(("blank-updater", updater_tamper))

    audit_actor_tamper = deepcopy(payload)
    controlled_audit = audit_actor_tamper["data"][
        "theme_configuration_audits"
    ][0]
    controlled_audit["actor"] = "Forged\nActor"
    controlled_audit["snapshot_hash"] = backup_service._canonical_json_hash(
        backup_service._theme_configuration_audit_hash_payload(controlled_audit)
    )
    tampered_payloads.append(("controlled-audit-actor", audit_actor_tamper))

    duplicate_audit_tamper = deepcopy(payload)
    duplicate = deepcopy(
        duplicate_audit_tamper["data"]["theme_configuration_audits"][0]
    )
    duplicate["id"] = max(
        record["id"]
        for record in duplicate_audit_tamper["data"][
            "theme_configuration_audits"
        ]
    ) + 1
    duplicate["actor"] = "backup-test-duplicate-audit"
    duplicate["snapshot_hash"] = hashlib.sha256(
        json.dumps(
            {
                key: duplicate.get(key)
                for key in (
                    "theme_family_id",
                    "theme_family_version_id",
                    "website_theme_configuration_id",
                    "component_configuration_id",
                    "action_type",
                    "actor",
                    "rationale",
                    "snapshot",
                    "created_at",
                )
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    duplicate_audit_tamper["data"]["theme_configuration_audits"].append(
        duplicate
    )
    duplicate_audit_tamper["metadata"]["table_counts"][
        "theme_configuration_audits"
    ] += 1
    tampered_payloads.append(("duplicate-audit", duplicate_audit_tamper))

    expected_messages = {
        "blank-updater": "configuration updater",
        "controlled-audit-actor": "audit actor",
    }
    for name, tampered in tampered_payloads:
        path = _write_payload(tmp_path, tampered, f"tampered-{name}.json")
        with pytest.raises(
            BackupValidationError,
            match=expected_messages.get(name),
        ):
            load_backup(path)


def test_backup_057_rejects_rehashed_component_schedule_tampering(
    tmp_path: Path,
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        _seed_bundle(session)
        exported = export_backup(session, backup_dir=tmp_path)
    payload = load_backup(Path(exported["path"]))

    evergreen_dates = deepcopy(payload)
    evergreen_banner = next(
        item
        for item in evergreen_dates["data"][
            "website_theme_component_configurations"
        ]
        if item["component_key"] == "campaign_banner"
    )
    evergreen_banner["effective_at"] = "2026-08-14T12:00:00+00:00"
    evergreen_banner["expires_at"] = "2026-08-15T12:00:00+00:00"
    evergreen_banner["integrity_fingerprint"] = backup_service._canonical_json_hash(
        backup_service._theme_component_configuration_fingerprint_payload(
            evergreen_banner
        )
    )

    time_bound_mismatch = deepcopy(payload)
    time_bound_banner = next(
        item
        for item in time_bound_mismatch["data"][
            "website_theme_component_configurations"
        ]
        if item["component_key"] == "campaign_banner"
    )
    time_bound_banner["configuration_payload"] = validate_component_payload(
        "campaign_banner",
        {
            "intent": "time_bound_campaign",
            "message": "Approved campaign",
            "cta_label": "Review details",
            "approved_offer_details": "Approved details",
            "terms_reference": "Approved terms record",
            "start_at": "2026-08-14T12:00:00+00:00",
            "end_at": "2026-08-15T12:00:00+00:00",
            "approval_identity": "Theme Lab Operator",
        },
    )
    time_bound_banner["effective_at"] = "2026-08-14T12:00:00+00:00"
    time_bound_banner["expires_at"] = "2026-08-16T12:00:00+00:00"
    time_bound_banner["integrity_fingerprint"] = backup_service._canonical_json_hash(
        backup_service._theme_component_configuration_fingerprint_payload(
            time_bound_banner
        )
    )

    for name, tampered, expected in (
        (
            "evergreen-fake-dates",
            evergreen_dates,
            "Evergreen conversion configuration cannot define effective dates",
        ),
        (
            "time-bound-row-mismatch",
            time_bound_mismatch,
            "must match its approved payload",
        ),
    ):
        with pytest.raises(BackupValidationError, match=expected):
            load_backup(
                _write_payload(
                    tmp_path,
                    tampered,
                    f"{name}.json",
                )
            )


def test_backup_056_loads_with_empty_durable_theme_groups(tmp_path: Path) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        business = Business(
            company_name="Legacy Backup Company",
            business_type="Local service company",
            state="FL",
        )
        session.add(business)
        session.commit()
        exported = export_backup(session, backup_dir=tmp_path)
    payload = json.loads(Path(exported["path"]).read_text(encoding="utf-8"))
    payload["metadata"]["version"] = "0.56"
    for group in (
        "theme_families",
        "theme_family_versions",
        "website_theme_configurations",
        "website_theme_component_configurations",
        "theme_configuration_audits",
    ):
        payload["data"].pop(group)
        payload["metadata"]["table_counts"].pop(group)
    legacy_path = _write_payload(tmp_path, payload, "legacy-056.json")

    loaded = load_backup(legacy_path)
    for group in (
        "theme_families",
        "theme_family_versions",
        "website_theme_configurations",
        "website_theme_component_configurations",
        "theme_configuration_audits",
    ):
        assert loaded["data"][group] == []
        assert loaded["metadata"]["table_counts"][group] == 0

    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        restore_backup(session, legacy_path)
        assert session.exec(select(Business)).one().company_name == (
            "Legacy Backup Company"
        )
        assert validate_theme_configuration_records(session) == {
            "theme_families": 0,
            "theme_family_versions": 0,
            "website_theme_configurations": 0,
            "website_theme_component_configurations": 0,
            "theme_configuration_audits": 0,
        }


def _draft_page(session: Session, source_ids: dict[str, int]) -> GeneratedPage:
    page = GeneratedPage(
        business_id=source_ids["business_id"],
        website_id=source_ids["website_id"],
        page_type="home",
        page_title="Theme Export Test",
        page_slug="theme-export-test",
        draft_content={"title": "Theme Export Test", "h1": "Theme Export Test"},
        generation_status="generated",
    )
    session.add(page)
    session.flush()
    plan = SitePlan(
        website_id=source_ids["website_id"],
        plan_key="theme-export",
        plan_name="Theme Export",
        status="active",
        version=1,
    )
    session.add(plan)
    session.flush()
    session.add(
        PlannedPage(
            website_id=source_ids["website_id"],
            site_plan_id=plan.id,
            page_type="home",
            working_name="Theme Export Test",
            intended_slug="theme-export-test",
            planning_status="planned",
            generated_page_id=page.id,
        )
    )
    session.commit()
    session.refresh(page)
    return page


def test_explicit_theme_export_rejects_inactive_draft_before_package_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        source_ids = _seed_bundle(session)
        page = _draft_page(session, source_ids)

        def _unexpected_package_build(*_args, **_kwargs):
            raise AssertionError("Draft eligibility must fail before package construction")

        monkeypatch.setattr(
            page_export,
            "build_page_export_package",
            _unexpected_package_build,
        )
        with pytest.raises(HTTPException) as caught:
            page_export.build_theme_configured_page_export_package(
                session,
                page.id,
                source_ids["configuration_id"],
            )

    assert caught.value.status_code == 409
    assert caught.value.detail == {
        "code": "theme_configuration_export_blocked",
        "message": (
            "Draft or preview-candidate Theme configuration is not eligible for "
            "public export."
        ),
    }
    assert "theme_configuration_identity" not in PageExportPackage.model_fields


def test_explicit_theme_export_adds_identity_without_changing_base_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        source_ids = _seed_bundle(session)
        page = _draft_page(session, source_ids)
        theme, selection = _activate_theme_graph(session, source_ids)
        base = PageExportPackage(
            page_id=page.id,
            page_status="draft",
            qa_status="not_run",
            page_title="Theme Export Test",
            url_slug="theme-export-test",
            h1="Theme Export Test",
            seo=ExportSEO(
                meta_title="Theme Export Test",
                meta_description="Theme export test description.",
                social_title="Theme Export Test",
                social_description="Theme export test description.",
                suggested_url_slug="theme-export-test",
            ),
            content_sections={"intro": "Existing content remains unchanged."},
            faq_items=[],
            cta_block="Request an estimate.",
            business_name="Backup Theme Company",
            assigned_media=[],
            json_ld={},
            canonical_url_preview="https://backup-theme.test/theme-export-test/",
            slug_conflicts=[],
            export_ready=False,
            warnings=[],
        )
        monkeypatch.setattr(
            page_export,
            "build_page_export_package",
            lambda *_args, **_kwargs: base,
        )

        configured = page_export.build_theme_configured_page_export_package(
            session,
            page.id,
            source_ids["configuration_id"],
        )
        family = session.get(ThemeFamily, source_ids["family_id"])
        version = session.get(ThemeFamilyVersion, source_ids["version_id"])
        configuration = session.get(
            WebsiteThemeConfiguration,
            source_ids["configuration_id"],
        )
        planned_page = session.exec(
            select(PlannedPage).where(PlannedPage.generated_page_id == page.id)
        ).one()
        components = sorted(
            session.exec(
                select(WebsiteThemeComponentConfiguration)
                .where(
                    WebsiteThemeComponentConfiguration.website_theme_configuration_id
                    == source_ids["configuration_id"],
                    WebsiteThemeComponentConfiguration.lifecycle_status == "current",
                )
            ).all(),
            key=lambda item: (item.placement, item.component_instance_key),
        )
        audit_hashes = sorted(
            item.snapshot_hash
            for item in session.exec(
                select(ThemeConfigurationAudit).order_by(
                    ThemeConfigurationAudit.id
                )
            ).all()
        )
        assert family is not None
        assert version is not None
        assert configuration is not None

    configured_payload = configured.model_dump(mode="json")
    configured_identity = configured_payload.pop("theme_configuration_identity")
    assert configured_payload == base.model_dump(mode="json")
    assert configured_identity == {
        "website_id": source_ids["website_id"],
        "business_id": source_ids["business_id"],
        "theme_family_id": source_ids["family_id"],
        "family_key": family.family_key,
        "theme_family_version_id": source_ids["version_id"],
        "family_version": version.version,
        "theme_compatibility_identity": version.compatibility_identity,
        "theme_family_version_integrity_fingerprint": (
            version.integrity_fingerprint
        ),
        "website_theme_configuration_id": source_ids["configuration_id"],
        "configuration_key": configuration.configuration_key,
        "configuration_version": configuration.version,
        "configuration_lifecycle_status": "active",
        "configuration_integrity_fingerprint": (
            configuration.integrity_fingerprint
        ),
        "theme_id": theme.id,
        "website_theme_selection_id": selection.id,
        "generated_page_id": page.id,
        "planned_page_id": planned_page.id,
        "effective_components": [
            {
                "component_configuration_id": item.id,
                "component_instance_key": item.component_instance_key,
                "component_key": item.component_key,
                "component_contract_version": item.component_contract_version,
                "revision": item.revision,
                "scope_type": item.scope_type,
                "planned_page_id": item.planned_page_id,
                "destination_component_configuration_id": (
                    item.destination_component_configuration_id
                ),
                "overrides_component_configuration_id": (
                    item.overrides_component_configuration_id
                ),
                "integrity_fingerprint": item.integrity_fingerprint,
            }
            for item in components
        ],
        "audit_snapshot_hashes": audit_hashes,
    }
