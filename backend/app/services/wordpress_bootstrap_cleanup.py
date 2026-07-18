"""Fail-closed dispatcher for version-bound upgrade-bootstrap cleanup profiles."""

from fastapi import HTTPException
from sqlmodel import Session

from app.schemas.wordpress import (
    WordPressBootstrapCleanupApplyRequest,
    WordPressBootstrapCleanupPreflightRequest,
    WordPressBootstrapDeletionPreflightRequest,
)
from app.services import wordpress_bootstrap_cleanup_0575 as profile_0575
from app.services import wordpress_bootstrap_cleanup_0576 as profile_0576


def cleanup_preflight(session: Session, page_id: int, request: WordPressBootstrapCleanupPreflightRequest):
    if request.expected_bootstrap_version == profile_0576.BOOTSTRAP_VERSION:
        return profile_0576.cleanup_preflight(session, page_id, request)
    if request.expected_bootstrap_version == profile_0575.BOOTSTRAP_VERSION:
        return profile_0575.cleanup_preflight(session, page_id, request)
    raise HTTPException(422, "The requested bootstrap cleanup profile is unsupported.")


def deletion_preflight(session: Session, page_id: int, request: WordPressBootstrapDeletionPreflightRequest):
    if request.expected_bootstrap_version == profile_0576.BOOTSTRAP_VERSION:
        return profile_0576.deletion_preflight(session, page_id, request)
    if request.expected_bootstrap_version == profile_0575.BOOTSTRAP_VERSION:
        return profile_0575.deletion_preflight(session, page_id, request)
    raise HTTPException(422, "The requested bootstrap deletion profile is unsupported.")


def deactivate_bootstrap(session: Session, page_id: int, request: WordPressBootstrapCleanupApplyRequest):
    if request.confirmation_phrase == profile_0576.DEACTIVATION_PHRASE:
        return profile_0576.deactivate_bootstrap(session, page_id, request)
    return profile_0575.deactivate_bootstrap(session, page_id, request)


def delete_bootstrap(session: Session, page_id: int, request: WordPressBootstrapCleanupApplyRequest):
    if request.confirmation_phrase == profile_0576.DELETION_PHRASE:
        return profile_0576.delete_bootstrap(session, page_id, request)
    return profile_0575.delete_bootstrap(session, page_id, request)


def _clear_cleanup_handles() -> None:
    profile_0575._clear_cleanup_handles()
    profile_0576._clear_cleanup_handles()
