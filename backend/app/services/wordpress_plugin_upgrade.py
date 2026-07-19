"""Fail-closed dispatcher for immutable Metadata Bridge upgrade profiles."""

from fastapi import HTTPException
from sqlmodel import Session

from app.models import WordPressPluginUpgradeAudit
from app.schemas.wordpress import (
    WordPressPluginUpgradeApplyRequest,
    WordPressPluginUpgradePreflightRequest,
    WordPressPluginUpgradeRecoveryRequest,
)
from app.services import wordpress_plugin_upgrade_0575 as profile_0575
from app.services import wordpress_plugin_upgrade_0576 as profile_0576
from app.services import wordpress_plugin_upgrade_0577 as profile_0577


def plugin_upgrade_preflight(session: Session, page_id: int, request: WordPressPluginUpgradePreflightRequest):
    pair = (request.current_plugin_version, request.target_plugin_version)
    if pair == (profile_0577.CURRENT_VERSION, profile_0577.TARGET_VERSION):
        return profile_0577.plugin_upgrade_preflight(session, page_id, request)
    if pair == (profile_0575.CURRENT_VERSION, profile_0575.TARGET_VERSION):
        return profile_0575.plugin_upgrade_preflight(session, page_id, request)
    if pair == (profile_0576.CURRENT_VERSION, profile_0576.TARGET_VERSION):
        return profile_0576.plugin_upgrade_preflight(session, page_id, request)
    raise HTTPException(422, "The requested Metadata Bridge upgrade profile is unsupported.")


def apply_plugin_upgrade(session: Session, page_id: int, request: WordPressPluginUpgradeApplyRequest):
    if request.confirmation_phrase == profile_0577.UPGRADE_PHRASE:
        return profile_0577.apply_plugin_upgrade(session, page_id, request)
    if request.confirmation_phrase == profile_0576.UPGRADE_PHRASE:
        return profile_0576.apply_plugin_upgrade(session, page_id, request)
    return profile_0575.apply_plugin_upgrade(session, page_id, request)


def assess_plugin_upgrade_recovery(session: Session, page_id: int, request: WordPressPluginUpgradeRecoveryRequest):
    audit = session.get(WordPressPluginUpgradeAudit, request.upgrade_audit_id)
    if audit and (audit.previous_version, audit.target_version) == (profile_0577.CURRENT_VERSION, profile_0577.TARGET_VERSION):
        return profile_0577.assess_plugin_upgrade_recovery(session, page_id, request)
    if audit and (audit.previous_version, audit.target_version) == (profile_0576.CURRENT_VERSION, profile_0576.TARGET_VERSION):
        return profile_0576.assess_plugin_upgrade_recovery(session, page_id, request)
    return profile_0575.assess_plugin_upgrade_recovery(session, page_id, request)


def _clear_upgrade_handles() -> None:
    profile_0575._clear_upgrade_handles()
    profile_0576._clear_upgrade_handles()
    profile_0577._clear_upgrade_handles()
