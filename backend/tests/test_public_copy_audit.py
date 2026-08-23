from __future__ import annotations

from copy import deepcopy

import pytest

from app.services.public_copy_audit import (
    PUBLIC_COPY_AUDIT_ALGORITHM_SHA256,
    PUBLIC_COPY_RULESET_CANONICAL_PAYLOAD_SHA256,
    PUBLIC_COPY_RULESET_IDENTITY,
    PUBLIC_COPY_RULESET_KEY,
    PUBLIC_COPY_RULESET_VERSION,
    PublicCopyAuditInput,
    audit_public_copy,
    audit_public_copy_pages,
    normalize_public_copy,
    normalized_public_copy_fingerprint,
    project_public_copy,
    public_copy_audit_identity,
)


def _input(**overrides):
    values = {
        "website_id": 1,
        "planned_page_id": 41,
        "generated_page_id": 41,
        "page_type": "city_service",
        "draft_content": {
            "schema_version": "planned-page-draft-v1",
            "title": "Drywood Termite Tenting in Orlando, Florida",
            "meta_title": "Drywood Termite Tenting in Orlando, Florida",
            "meta_description": "Learn about drywood termite tenting in Orlando, Florida.",
            "h1": "Drywood Termite Tenting in Orlando, Florida",
            "intro": "Flo-Zone provides drywood termite tenting in Orlando, Florida.",
            "sections": [
                {
                    "key": "service_overview",
                    "heading": "Drywood Termite Tenting",
                    "body": "Learn about preparation and the service process.",
                }
            ],
            "faq_items": [],
            "public_destination_copy": [
                {
                    "label": "Contact Flo-Zone",
                    "slug": "contact",
                    "description": "Contact Flo-Zone.",
                    "source_record_id": 99,
                }
            ],
            "call_to_action": "Call or request an estimate.",
            "internal_notes": "Atlas operator-only planning instructions.",
            "planning_record_id": 7,
            "operator_override_keys": ["purpose"],
        },
    }
    values.update(overrides)
    return PublicCopyAuditInput(**values)


def _categories(result):
    return {item.category for item in result.findings}


def _findings(result, category):
    return [item for item in result.findings if item.category == category]


def test_ruleset_binding_and_algorithm_identity_are_exact_and_deterministic():
    identity = public_copy_audit_identity()

    assert identity["ruleset_key"] == PUBLIC_COPY_RULESET_KEY
    assert identity["ruleset_version"] == PUBLIC_COPY_RULESET_VERSION
    assert identity["ruleset_identity"] == PUBLIC_COPY_RULESET_IDENTITY
    assert identity["ruleset_canonical_payload_sha256"] == (
        "3019e45fb33a31c4c023d110375232ea7bc44eb93eb9f2fbab7f8029847e70ae"
    )
    assert identity["ruleset_canonical_payload_sha256"] == (
        PUBLIC_COPY_RULESET_CANONICAL_PAYLOAD_SHA256
    )
    assert len(PUBLIC_COPY_AUDIT_ALGORITHM_SHA256) == 64
    assert audit_public_copy(_input()).fingerprint == audit_public_copy(_input()).fingerprint


@pytest.mark.parametrize(
    "field,value",
    [
        ("ruleset_key", "different-ruleset"),
        ("ruleset_version", "2.0.0"),
        ("ruleset_identity", "different/identity"),
        ("ruleset_canonical_payload_sha256", "0" * 64),
    ],
)
def test_ruleset_binding_mismatch_fails_closed(field, value):
    with pytest.raises(ValueError, match="accepted sealed ruleset"):
        project_public_copy(_input(**{field: value}))


def test_normalization_equates_nfkc_case_smart_punctuation_dashes_underscores_and_space():
    left = "  APPROVED\u00a0City\u2011Service\u2019s   Destination  "
    right = "approved city_service's destination"

    assert normalize_public_copy(left) == "approved city service's destination"
    assert normalize_public_copy(left) == normalize_public_copy(right)
    assert normalized_public_copy_fingerprint(left) == normalized_public_copy_fingerprint(right)


def test_projection_is_schema_aware_and_excludes_internal_planning_and_diagnostics():
    value = _input(
        composition={
            "effective_components": [
                {
                    "component_key": "hero",
                    "resolved_data": {
                        "title": "Customer title",
                        "intro": "Customer introduction.",
                        "page_type": "city_service",
                        "diagnostics": "Atlas placeholder",
                    },
                    "input_bindings": {"operator_only": "Atlas"},
                }
            ],
            "operator_decisions": [{"rationale": "Atlas operator-only"}],
            "source_snapshot": {"purpose": "Guide visitors"},
        },
        structured_data={
            "name": "Flo-Zone",
            "description": "Drywood termite tenting.",
            "diagnostics": "Atlas placeholder",
            "source_snapshot": {"purpose": "Guide visitors"},
        },
    )

    projected = project_public_copy(value)
    paths = {item.field_path for item in projected}
    exact = {item.exact_text for item in projected}

    assert "draft_content.internal_notes" not in paths
    assert not any("planning_record" in path for path in paths)
    assert not any("operator" in path for path in paths)
    assert not any("source_snapshot" in path for path in paths)
    assert not any("diagnostics" in path for path in paths)
    assert "Customer introduction." in exact
    assert "Drywood termite tenting." in exact
    assert "Atlas placeholder" not in exact
    assert audit_public_copy(value).blocker_count == 0


@pytest.mark.parametrize(
    "text",
    [
        "Guide visitors from Home to the approved service.",
        "Connect the Service_County page to an approved City\u2014Service destination.",
        "Provide a useful path from Contact to Home.",
        "Return from the City-Service page to the exact Service-County owner.",
        "Review answers drawn from approved business knowledge.",
        "This copy exposes a Public\u2011Facing Brand instruction.",
        "The component_instance follows a page_type layout contract.",
        "Atlas Generated Page diagnostics.",
    ],
)
def test_exact_and_normalized_internal_instruction_variants_are_blocked(text):
    result = audit_public_copy(_input(draft_content={"title": "Page", "h1": "Page", "intro": text}))

    assert result.public_copy_clean is False
    assert "internal_instruction" in _categories(result) or (
        "routing_or_component_instruction" in _categories(result)
    )
    assert all(item.ruleset_canonical_payload_sha256 == PUBLIC_COPY_RULESET_CANONICAL_PAYLOAD_SHA256 for item in result.findings)


def test_legitimate_approved_treatment_and_label_language_is_not_blocked():
    result = audit_public_copy(
        _input(
            draft_content={
                "title": "Treatment Guidance",
                "h1": "Treatment Guidance",
                "intro": "Follow the approved treatment and the product's approved label.",
            }
        )
    )

    assert result.blocker_count == 0
    assert "internal_instruction" not in _categories(result)


def test_provider_disabled_notice_is_an_exact_contextual_exception_only():
    exact = "Draft preview only. This form does not submit or store data."
    allowed = audit_public_copy(_input(form_helper_copy={"preview_notice": exact}))
    outside_form = audit_public_copy(
        _input(draft_content={"title": "Contact", "h1": "Contact", "intro": exact})
    )
    changed = audit_public_copy(
        _input(form_helper_copy={"preview_notice": exact + " Atlas will review it."})
    )

    assert allowed.blocker_count == 0
    assert _findings(allowed, "provider_disabled_safety_notice")
    assert _findings(outside_form, "internal_instruction")
    assert _findings(changed, "internal_instruction")


@pytest.mark.parametrize(
    "text",
    [
        "Choose the best and fastest service.",
        "Request a guaranteed same-day estimate.",
        "Our award-winning team offers a permanent solution.",
        "See our five-star customer reviews.",
        "This treatment is 100% effective.",
    ],
)
def test_unsupported_marketing_claim_patterns_are_blockers(text):
    result = audit_public_copy(
        _input(draft_content={"title": "Service", "h1": "Service", "intro": text})
    )

    assert _findings(result, "unsupported_business_claim")


def test_technical_copy_is_preserved_as_information_and_claims_are_warnings():
    exact = (
        "Whole-structure fumigation commonly uses Vikane. Many jobs are completed "
        "over about 2-3 days, but timing may vary with aeration and clearance testing."
    )
    value = _input(
        draft_content={
            "title": "Fumigation Guidance",
            "h1": "Fumigation Guidance",
            "intro": "Learn what to expect.",
            "sections": [{"heading": "Timing", "body": exact}],
        }
    )
    result = audit_public_copy(value)
    projected = project_public_copy(value)

    assert exact in {item.exact_text for item in projected}
    assert _findings(result, "shared_technical_copy")
    assert _findings(result, "technical_claim_expert_review")
    assert result.blocker_count == 0
    assert all(
        item.safe_correction_status == "expert_review_required"
        for item in _findings(result, "technical_claim_expert_review")
    )


def test_shared_technical_copy_without_an_absolute_claim_is_informational_only():
    result = audit_public_copy(
        _input(
            draft_content={
                "title": "Preparation",
                "h1": "Preparation",
                "intro": "Preparation guidance for drywood termite tenting is provided before service.",
            }
        )
    )

    assert _findings(result, "shared_technical_copy")
    assert not _findings(result, "technical_claim_expert_review")
    assert result.blocker_count == 0


def test_technical_guide_wires_and_property_owner_copy_do_not_match_routing_rule():
    result = audit_public_copy(
        _input(
            draft_content={
                "title": "Preparation",
                "h1": "Preparation",
                "intro": (
                    "Awnings, cameras, antennas, guide wires, and weather vanes may "
                    "need removal. The property owner may need to remove an attached fence."
                ),
            }
        )
    )

    assert not _findings(result, "routing_or_component_instruction")
    assert result.blocker_count == 0


def test_composition_projection_audits_only_resolved_public_fields():
    result = audit_public_copy(
        _input(
            draft_content={},
            composition={
                "effective_components": [
                    {
                        "component_key": "destination_cards",
                        "input_bindings": {"internal_link_intent_ids": [1]},
                        "resolved_data": {
                            "links": [
                                {
                                    "label": "Contact Flo-Zone",
                                    "slug": "contact",
                                    "purpose": "Provide a City-Service-to-Contact conversion path.",
                                    "relationship_type": "conversion",
                                }
                            ]
                        },
                    },
                    {
                        "component_key": "media_placement",
                        "resolved_data": {
                            "purpose": "Atlas demo media planning instruction",
                            "alt_text": "A tented home",
                            "caption": "Property prepared for tenting",
                            "provenance_type": "operator_only",
                        },
                    },
                ]
            },
        )
    )

    exact = {item.exact_text for item in project_public_copy(_input(
        draft_content={},
        composition={
            "effective_components": [
                {
                    "component_key": "media_placement",
                    "resolved_data": {
                        "purpose": "Atlas demo media planning instruction",
                        "alt_text": "A tented home",
                    },
                }
            ]
        },
    ))}
    assert _findings(result, "internal_instruction")
    assert "A tented home" in exact
    assert "Atlas demo media planning instruction" not in exact


def test_unclassified_composition_component_fails_closed_without_projecting_diagnostics():
    result = audit_public_copy(
        _input(
            draft_content={},
            composition={
                "effective_components": [
                    {
                        "component_key": "future_public_widget",
                        "resolved_data": {"diagnostics": "operator-only"},
                    }
                ]
            },
        )
    )

    finding = _findings(result, "unclassified_public_component")
    assert len(finding) == 1
    assert finding[0].exact_text == "Unhandled public component: future_public_widget."


def test_export_structured_form_and_alt_text_surfaces_are_audited():
    result = audit_public_copy(
        _input(
            export_payload={
                "page_title": "Service",
                "h1": "Service",
                "content_sections": {"intro": "Customer-facing introduction."},
                "seo": {
                    "meta_title": "Service",
                    "meta_description": "Placeholder text for search.",
                },
                "json_ld": {
                    "@type": "Service",
                    "description": "Approved destination from a Site Plan.",
                    "diagnostics": "This should be excluded.",
                },
                "assigned_media": [{"alt_text": "Atlas demo media"}],
                "warnings": [{"message": "operator-only diagnostic"}],
            },
            form_helper_copy={
                "heading": "Request an Estimate",
                "fields": [
                    {
                        "label": "Name",
                        "helper_text": "Guide visitors through this form.",
                        "value": "customer value must not enter the audit",
                    }
                ],
            },
            alt_text=["Generated Page hero image"],
        )
    )
    paths = {item.field_path for item in project_public_copy(_input(
        form_helper_copy={"fields": [{"label": "Name", "value": "private value"}]}
    ))}

    assert result.blocker_count >= 4
    assert "placeholder_or_demo_copy" in _categories(result)
    assert "internal_instruction" in _categories(result)
    assert not any(path.endswith(".value") for path in paths)


def test_cross_page_leakage_uses_explicit_governed_identity_scope():
    result = audit_public_copy(
        _input(
            draft_content={
                "title": "Service in Orlando",
                "h1": "Service in Orlando",
                "intro": "Serving Tampa property owners.",
            },
            site_identity_terms=("Orlando", "Tampa"),
            allowed_identity_terms=("Orlando",),
        )
    )

    finding = _findings(result, "cross_page_identity_leakage")
    assert len(finding) == 1
    assert "Tampa" in finding[0].message


def test_governed_navigation_identity_is_allowed_only_at_its_exact_item_path():
    path = "composition.effective_components[0].resolved_data.items[0].label"
    value = _input(
        draft_content={
            "title": "Service in Altamonte Springs",
            "h1": "Service in Altamonte Springs",
            "intro": "Serving Altamonte Springs in Seminole County.",
        },
        composition={
            "effective_components": [
                {
                    "component_key": "primary_navigation",
                    "resolved_data": {
                        "label": "Primary Navigation",
                        "items": [{"label": "Orange County"}],
                    },
                }
            ]
        },
        site_identity_terms=(
            "Altamonte Springs",
            "Seminole County",
            "Orange County",
        ),
        allowed_identity_terms=("Altamonte Springs", "Seminole County"),
        allowed_navigation_identity_terms_by_path={path: ("Orange County",)},
    )

    assert not _findings(audit_public_copy(value), "cross_page_identity_leakage")


def test_governed_navigation_path_allowance_does_not_leak_into_page_body():
    path = "composition.effective_components[0].resolved_data.items[0].label"
    result = audit_public_copy(
        _input(
            draft_content={
                "title": "Service in Altamonte Springs",
                "h1": "Service in Altamonte Springs",
                "intro": "Serving Orange County property owners.",
            },
            composition={
                "effective_components": [
                    {
                        "component_key": "primary_navigation",
                        "resolved_data": {
                            "label": "Primary Navigation",
                            "items": [{"label": "Orange County"}],
                        },
                    }
                ]
            },
            site_identity_terms=("Altamonte Springs", "Orange County"),
            allowed_identity_terms=("Altamonte Springs",),
            allowed_navigation_identity_terms_by_path={path: ("Orange County",)},
        )
    )

    finding = _findings(result, "cross_page_identity_leakage")
    assert len(finding) == 1
    assert finding[0].field_path == "draft_content.intro"


def test_navigation_allowance_rejects_a_direct_draft_path_bypass():
    with pytest.raises(ValueError, match="outside an exact resolved navigation label"):
        audit_public_copy(
            _input(
                draft_content={"intro": "Serving Orange County."},
                site_identity_terms=("Orange County",),
                allowed_navigation_identity_terms_by_path={
                    "draft_content.intro": ("Orange County",)
                },
            )
        )


def test_navigation_allowance_rejects_a_non_navigation_component_path():
    path = "composition.effective_components[0].resolved_data.items[0].label"
    with pytest.raises(ValueError, match="does not resolve one projected navigation label"):
        audit_public_copy(
            _input(
                draft_content={},
                composition={
                    "effective_components": [
                        {
                            "component_key": "faq",
                            "resolved_data": {
                                "items": [{"label": "Orange County"}]
                            },
                        }
                    ]
                },
                site_identity_terms=("Orange County",),
                allowed_navigation_identity_terms_by_path={
                    path: ("Orange County",)
                },
            )
        )


def test_navigation_label_is_blocked_when_exact_target_path_allows_another_identity():
    path = "composition.effective_components[0].resolved_data.items[0].label"
    result = audit_public_copy(
        _input(
            draft_content={},
            composition={
                "effective_components": [
                    {
                        "component_key": "footer_navigation",
                        "resolved_data": {
                            "label": "Footer Navigation",
                            "items": [{"label": "Orange County"}],
                        },
                    }
                ]
            },
            site_identity_terms=("Seminole County", "Orange County"),
            allowed_navigation_identity_terms_by_path={path: ("Seminole County",)},
        )
    )

    finding = _findings(result, "cross_page_identity_leakage")
    assert len(finding) == 1
    assert "Orange County" in finding[0].message


def test_navigation_label_without_an_exact_governed_path_allowance_is_blocked():
    result = audit_public_copy(
        _input(
            draft_content={},
            composition={
                "effective_components": [
                    {
                        "component_key": "utility_navigation",
                        "resolved_data": {
                            "label": "Utility Navigation",
                            "items": [{"label": "Orange County"}],
                        },
                    }
                ]
            },
            site_identity_terms=("Orange County",),
        )
    )

    assert _findings(result, "cross_page_identity_leakage")


def test_clean_audit_fingerprint_binds_navigation_identity_authorization():
    path = "composition.effective_components[0].resolved_data.items[0].label"
    values = {
        "draft_content": {},
        "composition": {
            "effective_components": [
                {
                    "component_key": "primary_navigation",
                    "resolved_data": {
                        "label": "Primary Navigation",
                        "items": [{"label": "Service Areas"}],
                    },
                }
            ]
        },
        "site_identity_terms": ("Orange County",),
    }
    without_allowance = audit_public_copy(_input(**values))
    with_allowance = audit_public_copy(
        _input(
            **values,
            allowed_navigation_identity_terms_by_path={
                path: ("Orange County",)
            },
        )
    )

    assert without_allowance.public_copy_clean is True
    assert with_allowance.public_copy_clean is True
    assert (
        without_allowance.identity_scope_authorization_sha256
        != with_allowance.identity_scope_authorization_sha256
    )
    assert without_allowance.fingerprint != with_allowance.fingerprint


def test_cross_page_leakage_ignores_shorter_identity_inside_allowed_longer_identity():
    result = audit_public_copy(
        _input(
            draft_content={
                "title": "Service in Daytona Beach Shores",
                "h1": "Service in Daytona Beach Shores",
                "call_to_action": (
                    "Discuss service in Daytona Beach Shores with Flo-Zone."
                ),
            },
            site_identity_terms=("Daytona Beach", "Daytona Beach Shores"),
            allowed_identity_terms=("Daytona Beach Shores",),
        )
    )

    assert not _findings(result, "cross_page_identity_leakage")


def test_cross_page_leakage_still_blocks_separate_shorter_identity_occurrence():
    result = audit_public_copy(
        _input(
            draft_content={
                "title": "Service in Daytona Beach Shores",
                "h1": "Service in Daytona Beach Shores",
                "intro": (
                    "Serving Daytona Beach Shores property owners. Separate projects "
                    "in Daytona Beach require their own governed page."
                ),
            },
            site_identity_terms=("Daytona Beach", "Daytona Beach Shores"),
            allowed_identity_terms=("Daytona Beach Shores",),
        )
    )

    finding = _findings(result, "cross_page_identity_leakage")
    assert len(finding) == 1
    assert "Daytona Beach" in finding[0].message


def test_duplicate_public_blocks_are_detected_only_within_the_same_surface():
    repeated = (
        "Flo-Zone provides careful preparation guidance before drywood termite "
        "tenting begins at the property."
    )
    within_draft = audit_public_copy(
        _input(
            draft_content={
                "title": "Service",
                "h1": "Service",
                "intro": repeated,
                "sections": [{"heading": "Preparation", "body": repeated}],
            }
        )
    )
    repeated_across_projections = audit_public_copy(
        _input(
            draft_content={"title": "Service", "h1": "Service", "intro": repeated},
            export_payload={
                "page_title": "Service",
                "h1": "Service",
                "content_sections": {"intro": repeated},
            },
        )
    )

    assert _findings(within_draft, "same_page_duplicate_public_block")
    assert not _findings(repeated_across_projections, "same_page_duplicate_public_block")


def test_metadata_summary_matching_intro_is_not_a_duplicate_rendered_body_block():
    repeated = (
        "Contact Flo-Zone by phone or email to discuss drywood termite tenting "
        "and request an estimate."
    )
    result = audit_public_copy(
        _input(
            draft_content={
                "title": "Contact Flo-Zone",
                "meta_description": repeated,
                "h1": "Contact Flo-Zone",
                "intro": repeated,
            }
        )
    )

    assert not _findings(result, "same_page_duplicate_public_block")


def test_empty_public_heading_raw_url_repetition_and_malformed_copy_are_classified():
    repeated_sentence = "Call the office for current availability."
    result = audit_public_copy(
        _input(
            draft_content={
                "title": "",
                "h1": "Service",
                "intro": f"Read https://example.test. {repeated_sentence} {repeated_sentence}",
                "sections": [{"heading": "Summary", "body": "Learn how to prepa."}],
            }
        )
    )

    assert "empty_or_meaningless_heading" in _categories(result)
    assert "raw_url_in_body_copy" in _categories(result)
    assert "repeated_public_sentence" in _categories(result)
    assert "malformed_copy" in _categories(result)


def test_source_owner_uses_the_most_specific_explicit_path_binding():
    value = _input(
        source_owner_by_path={
            "draft_content": "planned_page_drafting._build_draft",
            "draft_content.public_destination_copy": "public_copy.destination_projection",
        }
    )
    projected = project_public_copy(value)
    intro = next(item for item in projected if item.field_path == "draft_content.intro")
    destination = next(
        item
        for item in projected
        if item.field_path == "draft_content.public_destination_copy[0].description"
    )

    assert intro.source_owner == "planned_page_drafting._build_draft"
    assert destination.source_owner == "public_copy.destination_projection"


def test_finding_and_result_fingerprints_are_stable_but_bind_exact_source_text():
    first = audit_public_copy(
        _input(draft_content={"h1": "Service", "title": "Service", "intro": "Atlas copy."})
    )
    reordered = audit_public_copy(
        _input(draft_content={"intro": "Atlas copy.", "title": "Service", "h1": "Service"})
    )
    changed = audit_public_copy(
        _input(draft_content={"h1": "Service", "title": "Service", "intro": "ATLAS copy."})
    )

    assert first.fingerprint == reordered.fingerprint
    assert first.findings[0].fingerprint == reordered.findings[0].fingerprint
    assert first.findings[0].normalized_fingerprint == changed.findings[0].normalized_fingerprint
    assert first.findings[0].fingerprint != changed.findings[0].fingerprint


def test_batch_audit_evaluates_all_65_pages_with_deterministic_counts_and_order():
    pages = [
        _input(
            planned_page_id=index,
            generated_page_id=index,
            draft_content={
                "title": f"Page {index}",
                "h1": f"Page {index}",
                "intro": "Customer-facing service information.",
            },
        )
        for index in range(1, 66)
    ]
    first = audit_public_copy_pages(list(reversed(pages)))
    second = audit_public_copy_pages(pages)

    assert first.evaluated_page_count == 65
    assert first.public_copy_clean_count == 65
    assert first.public_copy_blocked_count == 0
    assert first.fingerprint == second.fingerprint
    assert [item.generated_page_id for item in first.results] == list(range(1, 66))


def test_batch_audit_rejects_duplicate_page_identity():
    page = _input()

    with pytest.raises(ValueError, match="duplicate Website/Page identity"):
        audit_public_copy_pages([page, deepcopy(page)])
