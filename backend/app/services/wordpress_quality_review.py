from datetime import UTC, datetime

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import GeneratedPage, WordPressQualityReview
from app.schemas.page_export import PageExportPackage
from app.schemas.wordpress import (
    WordPressManualQualityReviewRead,
    WordPressManualQualityReviewUpdate,
    WordPressDraftQualityReviewItem,
    WordPressDraftQualityReviewList,
    WordPressDraftReviewDetail,
    WordPressQualityCheck,
)
from app.services.page_export import build_page_export_package
from app.services.wordpress_draft_review import (
    get_wordpress_draft_review,
    list_wordpress_draft_reviews,
)

UNSAFE_PHRASES = (
    "100% guaranteed",
    "always eliminates",
    "permanent protection",
    "safe for everyone",
    "no risk",
    "harmless",
    "pesticide-free",
)


def list_wordpress_draft_quality_reviews(session: Session) -> WordPressDraftQualityReviewList:
    review_list = list_wordpress_draft_reviews(session)
    items = [
        build_wordpress_draft_quality_review(session, item.page_id)
        for item in review_list.items
    ]
    return WordPressDraftQualityReviewList(
        total_count=len(items),
        ready_count=sum(item.overall_publish_readiness == "ready" for item in items),
        needs_review_count=sum(item.overall_publish_readiness == "needs_review" for item in items),
        blocked_count=sum(item.overall_publish_readiness == "blocked" for item in items),
        items=items,
    )


def build_wordpress_draft_quality_review(
    session: Session,
    page_id: int,
) -> WordPressDraftQualityReviewItem:
    detail = get_wordpress_draft_review(session, page_id)
    package = build_page_export_package(session, page_id)
    manual_review = get_manual_quality_review(session, page_id)
    checklist = _checklist(detail, package)
    fail_count = sum(item.status == "fail" for item in checklist)
    warning_count = sum(item.status == "warning" for item in checklist)
    pass_count = sum(item.status == "pass" for item in checklist)
    readiness = "blocked" if fail_count else "needs_review" if warning_count else "ready"
    issues = [
        f"{item.label}: {item.message}"
        for item in checklist
        if item.status in {"fail", "warning"}
    ]
    return WordPressDraftQualityReviewItem(
        page_id=detail.item.page_id,
        page_title=detail.item.page_title,
        city=detail.item.city,
        county=detail.item.county,
        service=detail.item.service,
        atlas_status=detail.item.atlas_status,
        qa_status=detail.item.qa_status,
        wordpress_post_id=detail.item.wordpress_post_id,
        wordpress_status=detail.item.wordpress_status,
        wordpress_url=detail.item.wordpress_url,
        admin_edit_url=detail.item.admin_edit_url,
        slug=detail.comparison.atlas_saved_slug,
        payload_hash_matches_audit=(
            bool(detail.comparison.audit_payload_hash)
            and detail.comparison.audit_payload_hash == detail.comparison.current_export_payload_hash
        ),
        pass_count=pass_count,
        warning_count=warning_count,
        fail_count=fail_count,
        overall_publish_readiness=readiness,
        blockers_or_issues=issues,
        safe_for_future_manual_review=fail_count == 0,
        manual_review=manual_review,
        checklist=checklist,
    )


def get_manual_quality_review(
    session: Session,
    page_id: int,
) -> WordPressManualQualityReviewRead:
    record = session.exec(
        select(WordPressQualityReview).where(
            WordPressQualityReview.generated_page_id == page_id
        )
    ).first()
    if record:
        return WordPressManualQualityReviewRead.model_validate(record)
    return WordPressManualQualityReviewRead(generated_page_id=page_id)


def update_manual_quality_review(
    session: Session,
    page_id: int,
    payload: WordPressManualQualityReviewUpdate,
) -> WordPressDraftQualityReviewItem:
    page = session.get(GeneratedPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Generated page not found")
    if page.wordpress_post_id is None:
        raise HTTPException(
            status_code=404,
            detail="Generated page does not have a WordPress draft reference",
        )

    record = session.exec(
        select(WordPressQualityReview).where(
            WordPressQualityReview.generated_page_id == page_id
        )
    ).first()
    now = datetime.now(UTC)
    values = payload.model_dump()
    if record is None:
        record = WordPressQualityReview(generated_page_id=page_id)
    record.review_status = values["review_status"]
    record.reviewer_notes = values.get("reviewer_notes")
    record.reviewed_by = values.get("reviewed_by")
    record.reviewed_at = now
    record.updated_at = now
    session.add(record)
    session.commit()
    session.refresh(record)
    return build_wordpress_draft_quality_review(session, page_id)


def _checklist(
    detail: WordPressDraftReviewDetail,
    package: PageExportPackage,
) -> list[WordPressQualityCheck]:
    comparison = detail.comparison
    item = detail.item
    content = _combined_text(package)
    hero_media = [media for media in package.assigned_media if media.image_role == "hero"]
    missing_media_issues = [
        warning.message
        for warning in package.warnings
        if warning.code in {"hero_missing", "alt_text_missing"}
    ]
    return [
        _check(
            "wordpress_draft_exists",
            "WordPress draft exists",
            bool(item.wordpress_post_id and item.wordpress_url),
            "Saved WordPress draft reference and URL are present.",
            "Saved WordPress draft reference or URL is missing.",
            "wordpress",
        ),
        _check(
            "wordpress_status_draft",
            "WordPress status is draft",
            item.wordpress_status == "draft",
            "Atlas saved WordPress status is draft.",
            f"Atlas saved WordPress status is {item.wordpress_status or 'missing'}.",
            "wordpress",
        ),
        _check(
            "title_match",
            "Atlas/WordPress title match",
            package.page_title == comparison.atlas_saved_title,
            "Atlas export title matches the saved draft title.",
            "Atlas export title differs from the saved draft title.",
            "content",
        ),
        _check(
            "slug_match",
            "Atlas/WordPress slug match",
            package.url_slug == comparison.atlas_saved_slug and not package.slug_conflicts,
            "Atlas export slug matches the saved draft slug and has no conflicts.",
            "Atlas export slug differs or has a conflict.",
            "seo",
        ),
        _manual_warning(
            "page_reads_naturally",
            "Page reads naturally",
            "Human review is required to confirm the page reads naturally.",
            "content",
        ),
        _manual_warning(
            "city_section_local",
            "City section feels local but not fake",
            "Human review is required to confirm local context feels appropriate and not fabricated.",
            "content",
        ),
        _check(
            "service_wording_clear",
            "Service wording is clear",
            bool(package.service and package.content_sections.get("process_section")),
            "Service name and process section are present.",
            "Service name or process section is missing.",
            "content",
        ),
        _check(
            "no_risky_absolute_claims",
            "No risky absolute claims",
            not _contains_unsafe_phrase(content),
            "No blocked absolute phrases were found.",
            "Blocked absolute wording was found.",
            "safety_wording",
        ),
        _check(
            "no_unsupported_guarantees",
            "No unsupported guarantees",
            "guarantee" not in content.lower() and "warranty" not in content.lower(),
            "No unsupported guarantee or warranty wording was found.",
            "Guarantee or warranty wording needs manual/legal review.",
            "safety_wording",
        ),
        _check(
            "no_misleading_safety_claims",
            "No misleading safety claims",
            all(phrase not in content.lower() for phrase in ("safe for everyone", "harmless", "no risk")),
            "No misleading safety claim phrases were found.",
            "Potentially misleading safety wording was found.",
            "safety_wording",
        ),
        _check(
            "prep_reentry_safety_careful",
            "Prep/re-entry/safety wording is careful",
            "re-entry" in content.lower() and "clearance" in content.lower(),
            "Re-entry and clearance wording is present.",
            "Re-entry or clearance wording should be reviewed.",
            "safety_wording",
        ),
        _check(
            "cta_clear",
            "CTA is clear",
            bool(package.cta_block and package.phone),
            "CTA and phone number are present.",
            "CTA or phone number is missing.",
            "content",
        ),
        _check(
            "contact_correct",
            "Phone/email/website correct",
            bool(package.phone and package.email and package.website),
            "Phone, email, and website are present from Atlas business data.",
            "Phone, email, or website is missing from the export package.",
            "business_info",
        ),
        _check(
            "license_operator_correct",
            "License/operator wording correct",
            bool(package.license_number and package.certified_operator),
            "License number and certified operator are present.",
            "License number or certified operator is missing.",
            "business_info",
        ),
        _check(
            "customer_wording_appropriate",
            "Realtor/property manager/customer wording appropriate",
            "realtor" in content.lower() and "property manager" in content.lower(),
            "Realtor/property manager wording is present.",
            "Customer-type wording needs review.",
            "content",
        ),
        _check(
            "meta_title_excerpt_clean",
            "Meta title/excerpt clean",
            bool(package.seo.meta_title and package.seo.meta_description)
            and len(package.seo.meta_title) <= 70
            and len(package.seo.meta_description) <= 180,
            "Meta title and description are present and within review limits.",
            "Meta title or description is missing or long.",
            "seo",
        ),
        _check(
            "hero_media_status_understood",
            "Hero/media status understood",
            bool(hero_media),
            "Hero media assignment is present.",
            "Hero media assignment is missing.",
            "media",
        ),
        _check(
            "alt_text_media_reviewed",
            "Alt text/media metadata reviewed",
            bool(hero_media) and all(media.review_status == "reviewed" and media.alt_text for media in hero_media),
            "Hero media is reviewed and has alt text.",
            "Hero media needs reviewed status or alt text.",
            "media",
        ),
        _check(
            "missing_media_issues_listed",
            "Missing media issues listed",
            not missing_media_issues,
            "No missing-media export warnings are present.",
            "; ".join(missing_media_issues) or "Media issues need review.",
            "media",
        ),
        _manual_warning(
            "manual_wordpress_visual_review_needed",
            "Manual WordPress visual review needed",
            "Open the WordPress draft and visually inspect layout, links, and formatting before publishing later.",
            "wordpress",
        ),
        _manual_warning(
            "overall_publish_readiness_status",
            "Overall publish-readiness status",
            "Computed checks are complete, but final publish-readiness requires human signoff.",
            "review",
        ),
        _manual_warning(
            "reviewer_notes",
            "Reviewer notes",
            "Manual review notes/status are saved separately from computed read-only checklist results and should capture human review before future publish consideration.",
            "review",
        ),
    ]


def _check(
    key: str,
    label: str,
    passed: bool,
    pass_message: str,
    fail_message: str,
    review_field: str,
) -> WordPressQualityCheck:
    return WordPressQualityCheck(
        key=key,
        label=label,
        status="pass" if passed else "fail",
        message=pass_message if passed else fail_message,
        review_field=review_field,
    )


def _manual_warning(key: str, label: str, message: str, review_field: str) -> WordPressQualityCheck:
    return WordPressQualityCheck(
        key=key,
        label=label,
        status="warning",
        message=message,
        review_field=review_field,
    )


def _combined_text(package: PageExportPackage) -> str:
    parts = [
        package.page_title,
        package.h1,
        package.cta_block,
        package.seo.meta_title,
        package.seo.meta_description,
        *package.content_sections.values(),
        *[
            f"{item.get('question', '')} {item.get('answer', '')}"
            for item in package.faq_items
        ],
    ]
    return "\n".join(part for part in parts if part)


def _contains_unsafe_phrase(value: str) -> bool:
    lowered = value.lower()
    return any(phrase in lowered for phrase in UNSAFE_PHRASES)
