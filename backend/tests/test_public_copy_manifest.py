from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import unicodedata

import pytest
from sqlalchemy import DateTime

from app.models import InternalLinkIntent, PageCompositionRevision

from app.services.public_copy_manifest import (
    PUBLIC_COPY_ACTIVE_ATLAS_REVISION,
    PUBLIC_COPY_AUTHORIZATION_LINE_COUNT,
    PUBLIC_COPY_AUTHORIZATION_ORIGINAL_0046_BOUNDARY,
    PUBLIC_COPY_AUTHORIZATION_PATH,
    PUBLIC_COPY_AUTHORIZATION_SHA256,
    PUBLIC_COPY_AUTHORIZATION_SIZE_BYTES,
    PUBLIC_COPY_DATABASE_ROW_TIMESTAMP_CONTRACT,
    PUBLIC_COPY_LOCKED_SOURCE_TABLE_NAMES,
    PUBLIC_COPY_MANIFEST_SCHEMA,
    PUBLIC_COPY_RESUME_AUTHORIZATION_CANONICAL_ENCODING,
    PUBLIC_COPY_RESUME_AUTHORIZATION_EFFECT,
    PUBLIC_COPY_RESUME_AUTHORIZATION_LINE_COUNT,
    PUBLIC_COPY_RESUME_AUTHORIZATION_SHA256,
    PUBLIC_COPY_RESUME_AUTHORIZATION_SIZE_BYTES,
    PUBLIC_COPY_RESUME_AUTHORIZATION_SOURCE,
    PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_PATH,
    PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_SCHEMA,
    PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_SHA256,
    PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_SIZE_BYTES,
    PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_STATUS,
    PUBLIC_COPY_RULESET_SCHEMA,
    PublicCopyManifestError,
    canonical_json_sha256,
    canonical_model_row_sha256,
    canonical_model_rows_sha256,
    canonicalize_model_row_timestamps,
    load_public_copy_manifest_package,
    model_datetime_field_contract,
)


def _sealed_ruleset() -> dict:
    ruleset = {
        "schema": PUBLIC_COPY_RULESET_SCHEMA,
        "key": "project-atlas-public-copy-ruleset",
        "version": "1.0.0",
        "identity": "project-atlas-public-copy-ruleset/source-only/1.0.0",
        "customer_data": False,
        "normalization": {
            "unicode": "NFKC",
            "case": "casefold",
            "whitespace": "collapse",
        },
        "blockers": ["approved destination", "generated page", "atlas"],
    }
    ruleset["seal"] = {
        "canonical_payload_sha256": canonical_json_sha256(ruleset),
        "customer_data": False,
    }
    return ruleset


def _sealed_manifest(ruleset: dict, source_root: Path) -> dict:
    current_draft = {
        "schema_version": "planned-page-draft-v1",
        "page_type": "service",
        "title": "Drywood Termite Tenting",
        "intro": "Original service intro.",
        "sections": [
            {
                "key": "approved_guidance",
                "heading": "Guidance",
                "body": "Preserved sentence. Internal exact sentence.",
            }
        ],
        "related_pages": [],
        "public_destination_copy": [],
        "status": "approved",
    }
    expected_draft = deepcopy(current_draft)
    expected_draft["public_destination_copy"] = [
        {
            "source_kind": "internal_link_intent",
            "source_record_id": 71,
            "target_planned_page_id": 11,
            "target_generated_page_id": 21,
            "label": "Drywood Termite Tenting",
            "slug": "drywood-termite-tenting",
            "description": "View information about Drywood Termite Tenting.",
            "ruleset_key": ruleset["key"],
            "ruleset_version": ruleset["version"],
            "ruleset_hash": ruleset["seal"]["canonical_payload_sha256"],
        }
    ]
    current_hash = canonical_json_sha256(current_draft)
    expected_hash = canonical_json_sha256(expected_draft)
    entry_id = "public-copy-correction-0001"
    original_text = "Return from the Service page to its overview."
    replacement_text = "View information about Drywood Termite Tenting."
    generated_updated_at = "2026-08-20T12:00:00+00:00"
    manifest = {
        "schema": PUBLIC_COPY_MANIFEST_SCHEMA,
        "database_row_timestamp_contract": (
            PUBLIC_COPY_DATABASE_ROW_TIMESTAMP_CONTRACT
        ),
        "status": "sealed_pending_disposable_clone_rehearsal",
        "customer_data": False,
        "external_request_count": 0,
        "database_read_count": 0,
        "database_write_count": 0,
        "authorization": {
            "original": {
                "path": PUBLIC_COPY_AUTHORIZATION_PATH,
                "size_bytes": PUBLIC_COPY_AUTHORIZATION_SIZE_BYTES,
                "line_count": PUBLIC_COPY_AUTHORIZATION_LINE_COUNT,
                "sha256": PUBLIC_COPY_AUTHORIZATION_SHA256,
                "historical_boundary_note": (
                    PUBLIC_COPY_AUTHORIZATION_ORIGINAL_0046_BOUNDARY
                ),
            },
            "resume_authorization": {
                "source": PUBLIC_COPY_RESUME_AUTHORIZATION_SOURCE,
                "canonical_encoding": (
                    PUBLIC_COPY_RESUME_AUTHORIZATION_CANONICAL_ENCODING
                ),
                "size_bytes": PUBLIC_COPY_RESUME_AUTHORIZATION_SIZE_BYTES,
                "line_count": PUBLIC_COPY_RESUME_AUTHORIZATION_LINE_COUNT,
                "sha256": PUBLIC_COPY_RESUME_AUTHORIZATION_SHA256,
                "active_atlas_revision": PUBLIC_COPY_ACTIVE_ATLAS_REVISION,
                "authority_effect": PUBLIC_COPY_RESUME_AUTHORIZATION_EFFECT,
            },
            "accepted_resume_preflight_seal": {
                "path": PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_PATH,
                "size_bytes": PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_SIZE_BYTES,
                "sha256": PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_SHA256,
                "schema": PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_SCHEMA,
                "status": PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_STATUS,
                "cross_binding": {
                    "original_authorization_sha256": (
                        PUBLIC_COPY_AUTHORIZATION_SHA256
                    ),
                    "resume_authorization_sha256": (
                        PUBLIC_COPY_RESUME_AUTHORIZATION_SHA256
                    ),
                    "active_atlas_revision": PUBLIC_COPY_ACTIVE_ATLAS_REVISION,
                },
            },
        },
        "ruleset": {
            "schema": ruleset["schema"],
            "identity": ruleset["identity"],
            "canonical_payload_sha256": ruleset["seal"][
                "canonical_payload_sha256"
            ],
        },
        "scope": {
            "website_id": 1,
            "site_plan_id": 2,
            "planned_page_count": 1,
            "generated_page_count": 1,
            "affected_page_count": 1,
            "customer_data": False,
        },
        "execution_source_snapshot": _execution_source_snapshot(source_root),
        "governed_fact_snapshot": _governed_fact_snapshot(),
        "immutable_history_snapshot": {
            "generated_page_revisions": {
                "row_count": 1,
                "maximum_id": 31,
                "canonical_rows_sha256": "c" * 64,
            },
            "page_composition_revisions": {
                "row_count": 1,
                "maximum_id": 51,
                "canonical_rows_sha256": "d" * 64,
            },
            "generated_page_qa_results": {
                "row_count": 1,
                "maximum_id": 61,
                "canonical_rows_sha256": "e" * 64,
                "current_row_ids": [61],
                "canonical_noncurrent_rows_sha256": "f" * 64,
                "canonical_current_preserved_rows_sha256": "1" * 64,
            },
        },
        "corrections": [
            {
                "entry_id": entry_id,
                "website_id": 1,
                "site_plan_id": 2,
                "planned_page_id": 11,
                "generated_page_id": 21,
                "page_type": "service",
                "current_revision_id": 31,
                "latest_page_revision_id": 31,
                "current_content_hash": current_hash,
                "current_composition_id": 41,
                "current_composition_version": 7,
                "current_composition_source_hash": "1" * 64,
                "current_composition_history_revision_id": 51,
                "current_qa_id": 61,
                "current_qa_result_hash": "4" * 64,
                "expected_page_content_hash": expected_hash,
                "operation": "add_destination_derived_public_projection",
                "field_path": (
                    "draft_content.public_destination_copy"
                    "[source_kind=internal_link_intent,source_record_id=71]"
                    ".description"
                ),
                "mirrored_generated_page_field": None,
                "original_text": original_text,
                "normalized_original_fingerprint": _fingerprint(original_text),
                "finding_category": "related_link_description_defect",
                "finding_severity": "BLOCKER",
                "replacement_text": replacement_text,
                "omission_decision": False,
                "normalized_expected_fingerprint": _fingerprint(replacement_text),
                "source_owner": "app.services.page_composition._resolve_instance",
                "source_template_identity": "public-destination-copy-v1/service",
                "governed_facts_used": [
                    {"fact": "target_planned_page.id", "value": 11}
                ],
                "provenance": {
                    "classification": (
                        "operator_governed_internal_intent_with_generator_owned_public_projection"
                    ),
                    "automatic_correction_authorized": True,
                    "operator_authored_content_changed": False,
                    "operator_internal_link_intent_preserved": True,
                },
                "rationale": "Project exact governed destination copy.",
                "destination_identity": {
                    "website_id": 1,
                    "site_plan_id": 2,
                    "planned_page_id": 11,
                    "generated_page_id": 21,
                    "page_type": "service",
                    "working_name": "Drywood Termite Tenting",
                    "slug": "drywood-termite-tenting",
                    "service_id": 1,
                    "county_id": None,
                    "city_id": None,
                },
                "public_destination_item": deepcopy(
                    expected_draft["public_destination_copy"][0]
                ),
                "reconciliation_status": (
                    "sealed_pending_disposable_clone_rehearsal"
                ),
                "customer_data": False,
            }
        ],
        "page_bindings": [
            {
                "website_id": 1,
                "site_plan_id": 2,
                "planned_page_id": 11,
                "generated_page_id": 21,
                "page_type": "service",
                "working_name": "Drywood Termite Tenting",
                "slug": "drywood-termite-tenting",
                "page_identity": {
                    "planned_page_status": "generated",
                    "planned_page_parent_id": None,
                    "service_id": 1,
                    "county_id": None,
                    "city_id": None,
                    "generated_page_type": "service",
                    "generated_page_slug": "drywood-termite-tenting",
                    "generated_page_title": "Drywood Termite Tenting",
                    "generated_page_status": "approved",
                    "generated_page_generation_status": "generated",
                    "generated_page_qa_status": "passed",
                    "generated_page_meta_title": "Drywood Termite Tenting",
                    "generated_page_meta_description": "Service information.",
                    "generated_page_h1": "Drywood Termite Tenting",
                    "generated_page_content_body_sha256": "a" * 64,
                    "generated_page_preserved_state_sha256": "c" * 64,
                    "generated_page_updated_at": generated_updated_at,
                },
                "current_revision": {
                    "bound_generated_page_revision_id": 31,
                    "latest_page_revision_id": 31,
                    "latest_page_revision_hash_after": current_hash,
                    "latest_page_revision_row_sha256": "b" * 64,
                    "binding_kind": "canonical_bound",
                    "content_hash": current_hash,
                    "generated_page_updated_at": generated_updated_at,
                },
                "current_composition": {
                    "id": 41,
                    "version": 7,
                    "source_hash": "1" * 64,
                    "history_revision_id": 51,
                    "history_revision_hash": "2" * 64,
                    "history_revision_row_sha256": "3" * 64,
                    "content_hash": current_hash,
                },
                "current_qa": {
                    "id": 61,
                    "result_hash": "4" * 64,
                    "source_hash": "5" * 64,
                    "ruleset_key": "atlas-page-qa-rules",
                    "ruleset_version": "2",
                    "ruleset_hash": "6" * 64,
                    "readiness_status": "passed",
                    "preserved_evidence_sha256": "7" * 64,
                },
                "expected_draft_content": expected_draft,
                "expected_new_content_hash": expected_hash,
                "expected_revision_required": True,
                "correction_entry_ids": [entry_id],
                "expected_changed_top_level_fields": [
                    "public_destination_copy"
                ],
                "expected_public_block_distinctness": {
                    "planned_page_id": 11,
                    "public_block_count": 1,
                    "inventory_sha256": "7" * 64,
                    "duplicate_group_count": 0,
                },
            }
        ],
    }
    projection_corrections = [
        correction
        for correction in manifest["corrections"]
        if correction["operation"]
        == "add_destination_derived_public_projection"
    ]
    projection_payload = [
        {
            "source_planned_page_id": correction["planned_page_id"],
            **correction["public_destination_item"],
        }
        for correction in projection_corrections
    ]
    manifest["operator_intent_preservation"] = {
        "row_count": len(projection_corrections),
        "canonical_snapshot_sha256": "2" * 64,
        "mutation_allowed": False,
        "public_projection_field": "draft_content.public_destination_copy",
        "projection_item_count": len(projection_corrections),
        "projection_sha256": canonical_json_sha256(projection_payload),
        "destination_target_type_counts": {"service": 1},
        "source_page_type_item_counts": {"service": 1},
    }
    _reseal_manifest(manifest, ruleset)
    return manifest


def _governed_fact_snapshot() -> dict:
    return {
        "business": {
            "id": 1,
            "brand_name": "Example Brand",
            "company_name": "Example Company",
            "business_type": "Test business",
            "phone": "407-555-0100",
            "email": "office@example.test",
            "website": "https://example.test",
            "main_city": "Orlando",
            "state": "FL",
            "license_number": "TEST-1",
            "certified_operator": "Test Operator",
            "description": "Example governed description.",
        },
        "brand": {
            "id": 2,
            "business_id": 1,
            "brand_name": "Example Brand",
            "tagline": "Example tagline",
            "description": "Example brand description.",
            "status": "active",
        },
        "website": {
            "id": 1,
            "business_id": 1,
            "brand_id": 2,
            "website_name": "Example Website",
            "domain": "example.test",
            "public_url": "https://example.test",
            "locale": "en-US",
        },
        "services_sha256": "8" * 64,
        "counties_sha256": "9" * 64,
        "cities_sha256": "a" * 64,
        "knowledge_blocks_sha256": "b" * 64,
        "locked_source_table_sha256": {
            table_name: hashlib.sha256(table_name.encode("utf-8")).hexdigest()
            for table_name in PUBLIC_COPY_LOCKED_SOURCE_TABLE_NAMES
        },
    }


def _fixture_source_root(tmp_path: Path) -> Path:
    backend_root = Path(__file__).resolve().parents[1]
    repository_root = backend_root.parent
    layout_candidates = (
        repository_root
        / "frontend/src/components/performanceLocalV5LayoutContract.ts",
        Path("/atlas-program/frontend/src/components/performanceLocalV5LayoutContract.ts"),
    )
    layout_source = next(
        (candidate for candidate in layout_candidates if candidate.is_file()),
        layout_candidates[0],
    )
    source_root = tmp_path / "source-root"
    sources = {
        "backend/app/services/public_copy_manifest.py": backend_root
        / "app/services/public_copy_manifest.py",
        "frontend/src/components/performanceLocalV5LayoutContract.ts": layout_source,
    }
    for relative, source in sources.items():
        target = source_root.joinpath(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    runner = source_root / "backend/scripts/frozen_runner.py"
    runner.parent.mkdir(parents=True, exist_ok=True)
    runner.write_bytes(b"# frozen fixture runner\n")
    return source_root


def _execution_source_snapshot(root: Path) -> dict:
    paths = sorted(
        [
            "backend/app/services/public_copy_manifest.py",
            "backend/scripts/frozen_runner.py",
            "frontend/src/components/performanceLocalV5LayoutContract.ts",
        ]
    )
    modules = []
    for relative in paths:
        body = root.joinpath(*relative.split("/")).read_bytes()
        modules.append(
            {
                "path": relative,
                "size_bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        )
    return {
        "snapshot_role": "final_execution_source_after_production_freeze",
        "source_root_contract": {
            "root": "repository_root",
            "path_format": "repo_relative_posix",
            "allowed_paths": paths,
            "ordering": "lexicographic_path",
            "regular_files_only": True,
            "reject_symlinks": True,
            "hash_algorithm": "sha256-bytes",
        },
        "modules": modules,
        "canonical_module_list_sha256": canonical_json_sha256(modules),
        "git_baseline_commit": "150e022135e5564319b6b4c3e8ce6362be3f49db",
        "production_freeze_ack": "public-copy-production-source-frozen-v1",
        "performance_local_v5_layout_contract": {
            "path": "frontend/src/components/performanceLocalV5LayoutContract.ts",
            "mutation_allowed": False,
            "must_equal_pre_repair_source_baseline": True,
        },
        "customer_data": False,
    }


def _fingerprint(value: str | None) -> str:
    normalized = " ".join(
        unicodedata.normalize("NFKC", value or "").casefold().split()
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _reseal_ruleset(ruleset: dict) -> None:
    ruleset.pop("seal", None)
    ruleset["seal"] = {
        "canonical_payload_sha256": canonical_json_sha256(ruleset),
        "customer_data": False,
    }


def _reseal_manifest(manifest: dict, ruleset: dict) -> None:
    manifest.pop("seal", None)
    manifest["seal"] = {
        "algorithm": "sha256",
        "canonicalization": (
            "UTF-8 JSON; sorted keys; separators comma/colon; "
            "ensure_ascii=true; seal excluded"
        ),
        "canonical_manifest_payload_sha256": canonical_json_sha256(manifest),
        "ruleset_canonical_payload_sha256": ruleset["seal"][
            "canonical_payload_sha256"
        ],
        "source_backup_sha256": "8" * 64,
        "original_authorization_sha256": PUBLIC_COPY_AUTHORIZATION_SHA256,
        "resume_authorization_sha256": (
            PUBLIC_COPY_RESUME_AUTHORIZATION_SHA256
        ),
        "resume_preflight_seal_sha256": (
            PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_SHA256
        ),
        "operator_intents_snapshot_sha256": "9" * 64,
        "expected_page_hashes_sha256": "a" * 64,
        "pre_repair_source_module_snapshot_sha256": "b" * 64,
        "execution_source_module_list_sha256": "c" * 64,
        "locked_source_table_sha256_package_sha256": "d" * 64,
        "immutable_history_snapshot_sha256": "e" * 64,
        "customer_data": False,
    }


def _refresh_expected_hash(manifest: dict) -> None:
    binding = manifest["page_bindings"][0]
    expected_hash = canonical_json_sha256(binding["expected_draft_content"])
    binding["expected_new_content_hash"] = expected_hash
    for correction in manifest["corrections"]:
        correction["expected_page_content_hash"] = expected_hash


def _set_replace_variant(manifest: dict) -> None:
    correction = deepcopy(manifest["corrections"][0])
    correction["entry_id"] = "public-copy-correction-0002"
    replacement = "Repaired service intro."
    correction.update(
        {
            "field_path": "draft_content.intro",
            "mirrored_generated_page_field": None,
            "operation": "replace_exact_value",
            "original_text": "Original service intro.",
            "normalized_original_fingerprint": _fingerprint(
                "Original service intro."
            ),
            "finding_category": "reusable_source_template_defect",
            "replacement_text": replacement,
            "omission_decision": False,
            "normalized_expected_fingerprint": _fingerprint(replacement),
            "source_template_identity": "planned-page-draft-v1/service.intro",
            "governed_facts_used": [
                {"fact": "service.service_name", "value": "Drywood Termite Tenting"}
            ],
            "provenance": {
                "classification": "generator_owned_exact_template",
                "operator_authored_content_changed": False,
                "automatic_correction_authorized": True,
            },
            "destination_identity": None,
            "public_destination_item": None,
        }
    )
    binding = manifest["page_bindings"][0]
    binding["expected_draft_content"]["intro"] = replacement
    binding["correction_entry_ids"].append(correction["entry_id"])
    binding["expected_changed_top_level_fields"] = [
        "intro",
        "public_destination_copy",
    ]
    manifest["corrections"].append(correction)
    _refresh_expected_hash(manifest)


def _set_omission_variant(manifest: dict) -> None:
    correction = deepcopy(manifest["corrections"][0])
    correction["entry_id"] = "public-copy-correction-0002"
    sentence = "Internal exact sentence."
    correction.update(
        {
            "field_path": (
                "draft_content.sections[key=approved_guidance].body"
                "::exact_sentence[knowledge_block_id=6]"
            ),
            "mirrored_generated_page_field": None,
            "operation": "remove_exact_sentence",
            "original_text": sentence,
            "normalized_original_fingerprint": _fingerprint(sentence),
            "finding_category": "technical_content_internal_instruction",
            "replacement_text": None,
            "omission_decision": True,
            "normalized_expected_fingerprint": _fingerprint(None),
            "source_template_identity": (
                "planned-page-draft-v1/service.approved_guidance/knowledge-block-6"
            ),
            "governed_facts_used": [
                {"fact": "knowledge_block.id", "value": 6}
            ],
            "provenance": {
                "classification": "generator_owned_exact_template",
                "operator_authored_content_changed": False,
                "automatic_correction_authorized": True,
            },
            "destination_identity": None,
            "public_destination_item": None,
        }
    )
    binding = manifest["page_bindings"][0]
    binding["expected_draft_content"]["sections"][0]["body"] = (
        "Preserved sentence."
    )
    binding["correction_entry_ids"].append(correction["entry_id"])
    binding["expected_changed_top_level_fields"] = [
        "public_destination_copy",
        "sections",
    ]
    manifest["corrections"].append(correction)
    _refresh_expected_hash(manifest)


def _write(path: Path, value: dict) -> str:
    payload = (json.dumps(value, indent=2, ensure_ascii=True) + "\n").encode("utf-8")
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _package_files(tmp_path: Path) -> tuple[Path, str, Path, str, dict, dict]:
    source_root = _fixture_source_root(tmp_path)
    ruleset = _sealed_ruleset()
    manifest = _sealed_manifest(ruleset, source_root)
    ruleset_path = tmp_path / "public-copy-ruleset.json"
    manifest_path = tmp_path / "public-copy-correction-manifest.json"
    ruleset_sha = _write(ruleset_path, ruleset)
    manifest_sha = _write(manifest_path, manifest)
    return manifest_path, manifest_sha, ruleset_path, ruleset_sha, manifest, ruleset


def _load(
    manifest_path: Path,
    manifest_sha: str,
    ruleset_path: Path,
    ruleset_sha: str,
):
    return load_public_copy_manifest_package(
        manifest_path,
        manifest_sha256=manifest_sha,
        ruleset_path=ruleset_path,
        ruleset_sha256=ruleset_sha,
        source_root=manifest_path.parent / "source-root",
    )


def test_loads_strict_sha_pinned_canonically_sealed_package(tmp_path: Path) -> None:
    paths = _package_files(tmp_path)

    package = _load(*paths[:4])

    assert package.manifest_file_sha256 == paths[1]
    assert package.ruleset_file_sha256 == paths[3]
    assert package.manifest_payload_sha256 == paths[4]["seal"][
        "canonical_manifest_payload_sha256"
    ]
    assert package.ruleset_payload_sha256 == paths[5]["seal"][
        "canonical_payload_sha256"
    ]
    package.manifest["scope"]["website_id"] = 999
    assert paths[4]["scope"]["website_id"] == 1


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("missing_authorization", "authorization must be an object"),
        ("authorization_type", "authorization must be an object"),
        ("authorization_missing", "authorization has an unknown or incomplete contract"),
        ("authorization_extra", "authorization has an unknown or incomplete contract"),
        ("original_type", "authorization.original must be an object"),
        ("original_missing", "authorization.original has an unknown or incomplete contract"),
        ("original_extra", "authorization.original has an unknown or incomplete contract"),
        ("resume_type", "authorization.resume_authorization must be an object"),
        ("resume_missing", "authorization.resume_authorization has an unknown or incomplete contract"),
        ("resume_extra", "authorization.resume_authorization has an unknown or incomplete contract"),
        ("preflight_type", "authorization.accepted_resume_preflight_seal must be an object"),
        ("preflight_missing", "authorization.accepted_resume_preflight_seal has an unknown or incomplete contract"),
        ("preflight_extra", "authorization.accepted_resume_preflight_seal has an unknown or incomplete contract"),
        ("cross_type", "authorization.accepted_resume_preflight_seal.cross_binding must be an object"),
        ("cross_missing", "authorization.accepted_resume_preflight_seal.cross_binding has an unknown or incomplete contract"),
        ("cross_extra", "authorization.accepted_resume_preflight_seal.cross_binding has an unknown or incomplete contract"),
    ],
)
def test_rejects_caller_resealed_authorization_bundle_structure_drift(
    tmp_path: Path,
    mutation: str,
    expected: str,
) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, manifest, ruleset = _package_files(
        tmp_path
    )
    authorization = manifest["authorization"]
    original = authorization["original"]
    resume = authorization["resume_authorization"]
    preflight = authorization["accepted_resume_preflight_seal"]
    cross_binding = preflight["cross_binding"]
    if mutation == "missing_authorization":
        manifest.pop("authorization")
    elif mutation == "authorization_type":
        manifest["authorization"] = []
    elif mutation == "authorization_missing":
        authorization.pop("original")
    elif mutation == "authorization_extra":
        authorization["unexpected"] = "not authorized"
    elif mutation == "original_type":
        authorization["original"] = []
    elif mutation == "original_missing":
        original.pop("path")
    elif mutation == "original_extra":
        original["unexpected"] = "not authorized"
    elif mutation == "resume_type":
        authorization["resume_authorization"] = []
    elif mutation == "resume_missing":
        resume.pop("source")
    elif mutation == "resume_extra":
        resume["unexpected"] = "not authorized"
    elif mutation == "preflight_type":
        authorization["accepted_resume_preflight_seal"] = []
    elif mutation == "preflight_missing":
        preflight.pop("path")
    elif mutation == "preflight_extra":
        preflight["unexpected"] = "not authorized"
    elif mutation == "cross_type":
        preflight["cross_binding"] = []
    elif mutation == "cross_missing":
        cross_binding.pop("original_authorization_sha256")
    elif mutation == "cross_extra":
        cross_binding["unexpected"] = "not authorized"

    _reseal_manifest(manifest, ruleset)
    manifest_sha = _write(manifest_path, manifest)

    with pytest.raises(PublicCopyManifestError, match=expected):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


@pytest.mark.parametrize(
    ("field_path", "value", "expected"),
    [
        (("original", "path"), "/authorization/other.txt", "original authorization path"),
        (("original", "path"), 1, "original authorization path"),
        (("original", "size_bytes"), 55756, "original authorization size"),
        (("original", "size_bytes"), True, "authorization.original.size_bytes must be"),
        (("original", "line_count"), 2121, "original authorization line count"),
        (("original", "line_count"), True, "authorization.original.line_count must be"),
        (("original", "sha256"), "f" * 64, "original authorization identity"),
        (("original", "sha256"), 1, "original authorization identity"),
        (("original", "historical_boundary_note"), "historical", "historical note"),
        (("resume_authorization", "source"), "other", "resume authorization source"),
        (("resume_authorization", "canonical_encoding"), "UTF-8", "resume authorization encoding"),
        (("resume_authorization", "size_bytes"), 1412, "resume authorization size"),
        (("resume_authorization", "size_bytes"), True, "authorization.resume_authorization.size_bytes must be"),
        (("resume_authorization", "line_count"), 35, "resume authorization line count"),
        (("resume_authorization", "line_count"), True, "authorization.resume_authorization.line_count must be"),
        (("resume_authorization", "sha256"), "f" * 64, "resume authorization identity"),
        (("resume_authorization", "active_atlas_revision"), "20260817_0047", "Atlas revision"),
        (("resume_authorization", "authority_effect"), "resume everything", "authorization effect"),
        (("accepted_resume_preflight_seal", "path"), "other.json", "resume-preflight seal path"),
        (("accepted_resume_preflight_seal", "size_bytes"), 20951, "resume-preflight seal size"),
        (("accepted_resume_preflight_seal", "size_bytes"), True, "accepted_resume_preflight_seal.size_bytes must be"),
        (("accepted_resume_preflight_seal", "sha256"), "f" * 64, "resume-preflight seal identity"),
        (("accepted_resume_preflight_seal", "schema"), "seal@2", "resume-preflight seal schema"),
        (("accepted_resume_preflight_seal", "status"), "FAIL", "resume-preflight seal status"),
        (("accepted_resume_preflight_seal", "cross_binding", "original_authorization_sha256"), "f" * 64, "cross-binding"),
        (("accepted_resume_preflight_seal", "cross_binding", "resume_authorization_sha256"), "f" * 64, "cross-binding"),
        (("accepted_resume_preflight_seal", "cross_binding", "active_atlas_revision"), "20260817_0047", "cross-binding"),
    ],
)
def test_rejects_caller_resealed_authorization_bundle_value_drift(
    tmp_path: Path,
    field_path: tuple[str, ...],
    value: object,
    expected: str,
) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, manifest, ruleset = _package_files(
        tmp_path
    )
    target = manifest["authorization"]
    for field in field_path[:-1]:
        target = target[field]
    target[field_path[-1]] = value
    _reseal_manifest(manifest, ruleset)
    manifest_sha = _write(manifest_path, manifest)

    with pytest.raises(PublicCopyManifestError, match=expected):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("original_mismatch", "different authorization bundle"),
        ("resume_mismatch", "different authorization bundle"),
        ("preflight_mismatch", "different authorization bundle"),
        ("original_type", "manifest.seal.original_authorization_sha256 must be"),
        ("resume_type", "manifest.seal.resume_authorization_sha256 must be"),
        ("preflight_type", "manifest.seal.resume_preflight_seal_sha256 must be"),
        ("missing", "manifest.seal has an unknown or incomplete contract"),
        ("extra", "manifest.seal has an unknown or incomplete contract"),
    ],
)
def test_rejects_authorization_bundle_seal_drift(
    tmp_path: Path,
    mutation: str,
    expected: str,
) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, manifest, ruleset = _package_files(
        tmp_path
    )
    _reseal_manifest(manifest, ruleset)
    seal = manifest["seal"]
    if mutation == "original_mismatch":
        seal["original_authorization_sha256"] = "f" * 64
    elif mutation == "resume_mismatch":
        seal["resume_authorization_sha256"] = "f" * 64
    elif mutation == "preflight_mismatch":
        seal["resume_preflight_seal_sha256"] = "f" * 64
    elif mutation == "original_type":
        seal["original_authorization_sha256"] = True
    elif mutation == "resume_type":
        seal["resume_authorization_sha256"] = True
    elif mutation == "preflight_type":
        seal["resume_preflight_seal_sha256"] = True
    elif mutation == "missing":
        seal.pop("resume_authorization_sha256")
    elif mutation == "extra":
        seal["unexpected"] = "not authorized"
    manifest_sha = _write(manifest_path, manifest)

    with pytest.raises(PublicCopyManifestError, match=expected):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


@pytest.mark.parametrize("seal_name", ["manifest", "ruleset"])
def test_rejects_file_tampering_against_explicit_sha_pin(
    tmp_path: Path,
    seal_name: str,
) -> None:
    manifest_path, manifest_sha, ruleset_path, ruleset_sha, *_ = _package_files(
        tmp_path
    )
    path = manifest_path if seal_name == "manifest" else ruleset_path
    path.write_bytes(path.read_bytes() + b" ")

    with pytest.raises(PublicCopyManifestError, match="explicit caller seal"):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


@pytest.mark.parametrize("document", ["manifest", "ruleset"])
def test_rejects_tampering_even_when_caller_recomputes_file_sha(
    tmp_path: Path,
    document: str,
) -> None:
    manifest_path, manifest_sha, ruleset_path, ruleset_sha, manifest, ruleset = (
        _package_files(tmp_path)
    )
    if document == "manifest":
        manifest["scope"]["website_id"] = 999
        manifest_sha = _write(manifest_path, manifest)
        expected = "Correction-manifest canonical seal is invalid"
    else:
        ruleset["identity"] = "tampered-ruleset"
        ruleset_sha = _write(ruleset_path, ruleset)
        expected = "ruleset canonical seal is invalid"

    with pytest.raises(PublicCopyManifestError, match=expected):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


@pytest.mark.parametrize("document", ["manifest", "ruleset"])
def test_rejects_duplicate_json_keys(tmp_path: Path, document: str) -> None:
    manifest_path, manifest_sha, ruleset_path, ruleset_sha, *_ = _package_files(
        tmp_path
    )
    path = manifest_path if document == "manifest" else ruleset_path
    payload = path.read_text(encoding="utf-8")
    payload = payload.replace("{", '{\n  "schema": "duplicate",', 1)
    path.write_text(payload, encoding="utf-8")
    observed_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if document == "manifest":
        manifest_sha = observed_sha
    else:
        ruleset_sha = observed_sha

    with pytest.raises(PublicCopyManifestError, match="duplicate JSON key: schema"):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


def test_rejects_nonfinite_json_number(tmp_path: Path) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, *_ = _package_files(tmp_path)
    payload = manifest_path.read_text(encoding="utf-8").replace(
        '"external_request_count": 0',
        '"external_request_count": NaN',
    )
    manifest_path.write_text(payload, encoding="utf-8")
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    with pytest.raises(PublicCopyManifestError, match="non-finite JSON number: NaN"):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


def test_canonical_hash_rejects_nonfinite_python_value() -> None:
    with pytest.raises(ValueError, match="Out of range float values"):
        canonical_json_sha256({"unsafe": float("nan")})


def test_schema_datetime_contract_includes_timezone_true_and_false_columns() -> None:
    intent_contract = model_datetime_field_contract(InternalLinkIntent)
    composition_revision_contract = model_datetime_field_contract(
        PageCompositionRevision
    )

    assert intent_contract == {
        "created_at": True,
        "decided_at": True,
        "updated_at": True,
    }
    assert composition_revision_contract["generated_at"] is False
    assert composition_revision_contract["decided_at"] is False
    assert composition_revision_contract["recorded_at"] is True
    assert list(composition_revision_contract) == sorted(
        composition_revision_contract
    )


@pytest.mark.parametrize(
    "value",
    [
        "2026-08-21T01:02:03.123456",
        "2026-08-21T01:02:03.123456Z",
        "2026-08-21T01:02:03.123456+00:00",
        "2026-08-20T21:02:03.123456-04:00",
        datetime(2026, 8, 21, 1, 2, 3, 123456),
        datetime(2026, 8, 21, 1, 2, 3, 123456, tzinfo=UTC),
    ],
)
def test_schema_datetime_canonicalizer_normalizes_all_supported_forms(
    value: str | datetime,
) -> None:
    row = {
        "generated_at": value,
        "source_snapshot": {
            "generated_at": "2026-08-20T21:02:03.123456-04:00"
        },
    }

    observed = canonicalize_model_row_timestamps(
        PageCompositionRevision,
        row,
    )

    assert observed["generated_at"] == "2026-08-21T01:02:03.123456Z"
    assert observed["source_snapshot"] == row["source_snapshot"]
    assert observed["source_snapshot"] is row["source_snapshot"]


def test_schema_datetime_canonicalizer_emits_six_digits_and_preserves_null() -> None:
    observed = canonicalize_model_row_timestamps(
        PageCompositionRevision,
        {
            "generated_at": "2026-08-21T01:02:03Z",
            "decided_at": None,
        },
    )

    assert observed == {
        "generated_at": "2026-08-21T01:02:03.000000Z",
        "decided_at": None,
    }


@pytest.mark.parametrize(
    "value",
    [
        "2026-08-21 01:02:03",
        "2026-08-21T01:02:03.1234567Z",
        "2026-02-30T01:02:03Z",
        " 2026-08-21T01:02:03Z",
        123,
    ],
)
def test_schema_datetime_canonicalizer_rejects_malformed_values(value: object) -> None:
    with pytest.raises(PublicCopyManifestError, match="DateTime|ISO-8601"):
        canonicalize_model_row_timestamps(
            PageCompositionRevision,
            {"generated_at": value},
        )


def test_schema_datetime_hash_is_top_level_only_and_order_preserving() -> None:
    first = {
        "id": 1,
        "generated_at": "2026-08-21T01:02:03",
        "source_snapshot": {"recorded_at": "2026-08-21T01:02:03+00:00"},
    }
    equivalent = {
        **first,
        "generated_at": "2026-08-20T21:02:03-04:00",
    }
    second = {**first, "id": 2}

    assert canonical_model_row_sha256(
        PageCompositionRevision,
        first,
    ) == canonical_model_row_sha256(PageCompositionRevision, equivalent)
    assert canonical_json_sha256(first) != canonical_json_sha256(equivalent)
    assert canonical_model_rows_sha256(
        PageCompositionRevision,
        [first, second],
    ) != canonical_model_rows_sha256(
        PageCompositionRevision,
        [second, first],
    )


def test_schema_datetime_contract_rejects_non_table_and_ambiguous_models() -> None:
    class NotATable:
        pass

    class FakeColumn:
        def __init__(self, key: str, name: str) -> None:
            self.key = key
            self.name = name
            self.type = DateTime(timezone=True)

    class AmbiguousTable:
        columns = [FakeColumn("recorded_at", "recorded_on")]

    class AmbiguousModel:
        __table__ = AmbiguousTable()

    class DuplicateTable:
        columns = [
            FakeColumn("recorded_at", "recorded_at"),
            FakeColumn("recorded_at", "recorded_at"),
        ]

    class DuplicateModel:
        __table__ = DuplicateTable()

    with pytest.raises(PublicCopyManifestError, match="one table model"):
        model_datetime_field_contract(NotATable)
    with pytest.raises(PublicCopyManifestError, match="ambiguous"):
        model_datetime_field_contract(AmbiguousModel)
    with pytest.raises(PublicCopyManifestError, match="duplicate"):
        model_datetime_field_contract(DuplicateModel)


@pytest.mark.parametrize("contract", [None, "schema-datetime-utc-rfc3339-v0"])
def test_rejects_missing_or_v0_database_row_timestamp_contract(
    tmp_path: Path,
    contract: str | None,
) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, manifest, ruleset = _package_files(
        tmp_path
    )
    if contract is None:
        manifest.pop("database_row_timestamp_contract")
    else:
        manifest["database_row_timestamp_contract"] = contract
    _reseal_manifest(manifest, ruleset)
    manifest_sha = _write(manifest_path, manifest)

    with pytest.raises(
        PublicCopyManifestError,
        match="database-row timestamp contract",
    ):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


def test_rejects_invalid_sha_pin_before_reading_files(tmp_path: Path) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, *_ = _package_files(tmp_path)

    with pytest.raises(PublicCopyManifestError, match="manifest_sha256"):
        _load(manifest_path, "ABC", ruleset_path, ruleset_sha)


def test_rejects_manifest_bound_to_different_ruleset_identity(tmp_path: Path) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, manifest, ruleset = _package_files(
        tmp_path
    )
    manifest["ruleset"]["identity"] = "different-ruleset"
    _reseal_manifest(manifest, ruleset)
    manifest_sha = _write(manifest_path, manifest)

    with pytest.raises(PublicCopyManifestError, match="ruleset identity is inconsistent"):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


def test_rejects_unsupported_resealed_ruleset_schema(tmp_path: Path) -> None:
    manifest_path, manifest_sha, ruleset_path, _, _, ruleset = _package_files(tmp_path)
    ruleset["schema"] = "project-atlas-public-copy-ruleset@999"
    _reseal_ruleset(ruleset)
    ruleset_sha = _write(ruleset_path, ruleset)

    with pytest.raises(PublicCopyManifestError, match="Unsupported public-copy ruleset schema"):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


def test_rejects_duplicate_correction_identity_in_resealed_manifest(
    tmp_path: Path,
) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, manifest, ruleset = _package_files(
        tmp_path
    )
    manifest["corrections"].append(deepcopy(manifest["corrections"][0]))
    _reseal_manifest(manifest, ruleset)
    manifest_sha = _write(manifest_path, manifest)

    with pytest.raises(PublicCopyManifestError, match="duplicate identity"):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


def test_rejects_refingerprinted_execution_source_byte_drift(tmp_path: Path) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, manifest, ruleset = _package_files(
        tmp_path
    )
    snapshot = manifest["execution_source_snapshot"]
    snapshot["modules"][0]["sha256"] = "0" * 64
    snapshot["canonical_module_list_sha256"] = canonical_json_sha256(
        snapshot["modules"]
    )
    _reseal_manifest(manifest, ruleset)
    manifest_sha = _write(manifest_path, manifest)

    with pytest.raises(PublicCopyManifestError, match="module bytes drifted"):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


def test_rejects_execution_source_path_escape_before_read(tmp_path: Path) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, manifest, ruleset = _package_files(
        tmp_path
    )
    snapshot = manifest["execution_source_snapshot"]
    snapshot["modules"][0]["path"] = "backend/../outside.py"
    snapshot["source_root_contract"]["allowed_paths"] = [
        "backend/../outside.py"
    ]
    snapshot["canonical_module_list_sha256"] = canonical_json_sha256(
        snapshot["modules"]
    )
    _reseal_manifest(manifest, ruleset)
    manifest_sha = _write(manifest_path, manifest)

    with pytest.raises(PublicCopyManifestError, match="module path is unsafe"):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


def test_rejects_destination_projection_operation_bound_to_wrong_path(
    tmp_path: Path,
) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, manifest, ruleset = _package_files(
        tmp_path
    )
    manifest["corrections"][0]["field_path"] = "draft_content.internal_notes"
    _reseal_manifest(manifest, ruleset)
    manifest_sha = _write(manifest_path, manifest)

    with pytest.raises(PublicCopyManifestError, match=r"field[-_ ]path"):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "automatic_correction_authorized",
            False,
            "lacks exact automatic-correction authority",
        ),
        (
            "operator_authored_content_changed",
            True,
            "would change operator-authored content",
        ),
    ],
)
def test_rejects_unknown_or_operator_authored_correction_provenance(
    tmp_path: Path,
    field: str,
    value: bool,
    message: str,
) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, manifest, ruleset = _package_files(
        tmp_path
    )
    manifest["corrections"][0]["provenance"][field] = value
    _reseal_manifest(manifest, ruleset)
    manifest_sha = _write(manifest_path, manifest)

    with pytest.raises(PublicCopyManifestError, match=message):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


@pytest.mark.parametrize("mutation", ["missing", "extra", "wrong_path"])
def test_rejects_resealed_v5_layout_contract_drift(
    tmp_path: Path,
    mutation: str,
) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, manifest, ruleset = _package_files(
        tmp_path
    )
    snapshot = manifest["execution_source_snapshot"]
    if mutation == "missing":
        snapshot.pop("performance_local_v5_layout_contract")
    elif mutation == "extra":
        snapshot["performance_local_v5_layout_contract"]["unexpected"] = True
    else:
        snapshot["performance_local_v5_layout_contract"]["path"] = (
            "frontend/src/components/other.ts"
        )
    _reseal_manifest(manifest, ruleset)
    manifest_sha = _write(manifest_path, manifest)

    with pytest.raises(
        PublicCopyManifestError,
        match="Execution-source snapshot|Performance Local V5 layout contract",
    ):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


def test_rejects_resealed_v5_module_identity_contradiction(tmp_path: Path) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, manifest, ruleset = _package_files(
        tmp_path
    )
    snapshot = manifest["execution_source_snapshot"]
    v5 = next(
        item
        for item in snapshot["modules"]
        if item["path"].endswith("performanceLocalV5LayoutContract.ts")
    )
    v5["sha256"] = "0" * 64
    snapshot["canonical_module_list_sha256"] = canonical_json_sha256(
        snapshot["modules"]
    )
    _reseal_manifest(manifest, ruleset)
    manifest_sha = _write(manifest_path, manifest)

    with pytest.raises(PublicCopyManifestError, match="immutable pre-repair identity"):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


def test_rejects_nonexhaustive_resealed_execution_source_discovery(
    tmp_path: Path,
) -> None:
    manifest_path, manifest_sha, ruleset_path, ruleset_sha, *_ = _package_files(
        tmp_path
    )
    extra = tmp_path / "source-root/backend/app/unsealed.py"
    extra.write_text("VALUE = 'unsealed'\n", encoding="utf-8")

    with pytest.raises(PublicCopyManifestError, match="exhaustive frozen source"):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_rejects_unknown_or_incomplete_correction_contract(
    tmp_path: Path,
    mutation: str,
) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, manifest, ruleset = _package_files(
        tmp_path
    )
    correction = manifest["corrections"][0]
    if mutation == "missing":
        correction.pop("source_owner")
    else:
        correction["caller_resealed_override"] = True
    _reseal_manifest(manifest, ruleset)
    manifest_sha = _write(manifest_path, manifest)

    with pytest.raises(PublicCopyManifestError, match="unknown or incomplete contract"):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


@pytest.mark.parametrize(
    ("owner", "field"),
    [
        ("page_binding", "expected_public_block_distinctness"),
        ("page_identity", "generated_page_content_body_sha256"),
        ("current_revision", "latest_page_revision_row_sha256"),
    ],
)
def test_rejects_incomplete_page_binding_identity_contracts(
    tmp_path: Path,
    owner: str,
    field: str,
) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, manifest, ruleset = _package_files(
        tmp_path
    )
    binding = manifest["page_bindings"][0]
    target = binding if owner == "page_binding" else binding[owner]
    target.pop(field)
    _reseal_manifest(manifest, ruleset)
    manifest_sha = _write(manifest_path, manifest)

    with pytest.raises(PublicCopyManifestError, match="unknown or incomplete contract"):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


def test_rejects_extra_resealed_provenance_key(tmp_path: Path) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, manifest, ruleset = _package_files(
        tmp_path
    )
    manifest["corrections"][0]["provenance"]["caller_override"] = True
    _reseal_manifest(manifest, ruleset)
    manifest_sha = _write(manifest_path, manifest)

    with pytest.raises(PublicCopyManifestError, match="exact automatic-correction provenance"):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("website_id", 2),
        ("site_plan_id", 3),
        ("generated_page_id", 22),
        ("page_type", "contact"),
        ("current_content_hash", "c" * 64),
        ("expected_page_content_hash", "d" * 64),
    ],
)
def test_rejects_resealed_correction_page_binding_contradictions(
    tmp_path: Path,
    field: str,
    value,
) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, manifest, ruleset = _package_files(
        tmp_path
    )
    manifest["corrections"][0][field] = value
    _reseal_manifest(manifest, ruleset)
    manifest_sha = _write(manifest_path, manifest)

    with pytest.raises(PublicCopyManifestError, match="contradicts its Page binding"):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


def test_rejects_resealed_projection_value_not_present_in_expected_draft(
    tmp_path: Path,
) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, manifest, ruleset = _package_files(
        tmp_path
    )
    correction = manifest["corrections"][0]
    replacement = "Caller-resealed contradictory description."
    correction["replacement_text"] = replacement
    correction["normalized_expected_fingerprint"] = _fingerprint(replacement)
    correction["public_destination_item"]["description"] = replacement
    _reseal_manifest(manifest, ruleset)
    manifest_sha = _write(manifest_path, manifest)

    with pytest.raises(PublicCopyManifestError, match="projection contradicts"):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


def test_rejects_fully_rehashed_destination_identity_contradiction(
    tmp_path: Path,
) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, manifest, ruleset = _package_files(
        tmp_path
    )
    correction = manifest["corrections"][0]
    correction["destination_identity"]["generated_page_id"] = 999
    correction["public_destination_item"]["target_generated_page_id"] = 999
    manifest["page_bindings"][0]["expected_draft_content"][
        "public_destination_copy"
    ][0]["target_generated_page_id"] = 999
    _refresh_expected_hash(manifest)
    _reseal_manifest(manifest, ruleset)
    manifest_sha = _write(manifest_path, manifest)

    with pytest.raises(PublicCopyManifestError, match="destination identity contradicts"):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


def test_accepts_exact_replace_value_operation_coupling(tmp_path: Path) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, manifest, ruleset = _package_files(
        tmp_path
    )
    _set_replace_variant(manifest)
    _reseal_manifest(manifest, ruleset)
    manifest_sha = _write(manifest_path, manifest)

    _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


def test_rejects_resealed_replace_value_expected_draft_contradiction(
    tmp_path: Path,
) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, manifest, ruleset = _package_files(
        tmp_path
    )
    _set_replace_variant(manifest)
    manifest["page_bindings"][0]["expected_draft_content"]["intro"] = (
        "Caller-resealed contradictory intro."
    )
    _refresh_expected_hash(manifest)
    _reseal_manifest(manifest, ruleset)
    manifest_sha = _write(manifest_path, manifest)

    with pytest.raises(PublicCopyManifestError, match="replacement contradicts"):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


def test_accepts_exact_sentence_omission_operation_coupling(tmp_path: Path) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, manifest, ruleset = _package_files(
        tmp_path
    )
    _set_omission_variant(manifest)
    _reseal_manifest(manifest, ruleset)
    manifest_sha = _write(manifest_path, manifest)

    _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


def test_rejects_resealed_omission_that_remains_in_expected_draft(
    tmp_path: Path,
) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, manifest, ruleset = _package_files(
        tmp_path
    )
    _set_omission_variant(manifest)
    manifest["page_bindings"][0]["expected_draft_content"]["sections"][0][
        "body"
    ] = "Preserved sentence. Internal exact sentence."
    _refresh_expected_hash(manifest)
    _reseal_manifest(manifest, ruleset)
    manifest_sha = _write(manifest_path, manifest)

    with pytest.raises(PublicCopyManifestError, match="omitted sentence remains"):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


@pytest.mark.parametrize("mutation", ["missing", "extra", "ownership", "sha"])
def test_rejects_resealed_governed_fact_snapshot_contract_drift(
    tmp_path: Path,
    mutation: str,
) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, manifest, ruleset = _package_files(
        tmp_path
    )
    snapshot = manifest["governed_fact_snapshot"]
    if mutation == "missing":
        manifest.pop("governed_fact_snapshot")
    elif mutation == "extra":
        snapshot["business"]["unexpected"] = "caller value"
    elif mutation == "ownership":
        snapshot["website"]["business_id"] = 999
    else:
        snapshot["services_sha256"] = "A" * 64
    _reseal_manifest(manifest, ruleset)
    manifest_sha = _write(manifest_path, manifest)

    with pytest.raises(
        PublicCopyManifestError,
        match="governed_fact_snapshot|Governed fact snapshot",
    ):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "extra",
        "boolean_count",
        "count_mismatch",
        "mutation_allowed",
        "projection_field",
        "snapshot_hash",
        "projection_hash",
        "target_counts",
        "source_counts",
    ],
)
def test_rejects_resealed_operator_intent_preservation_drift(
    tmp_path: Path,
    mutation: str,
) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, manifest, ruleset = _package_files(
        tmp_path
    )
    contract = manifest["operator_intent_preservation"]
    if mutation == "missing":
        manifest.pop("operator_intent_preservation")
    elif mutation == "extra":
        contract["unexpected"] = False
    elif mutation == "boolean_count":
        contract["row_count"] = True
    elif mutation == "count_mismatch":
        contract["projection_item_count"] = 2
    elif mutation == "mutation_allowed":
        contract["mutation_allowed"] = True
    elif mutation == "projection_field":
        contract["public_projection_field"] = "draft_content.internal_notes"
    elif mutation == "snapshot_hash":
        contract["canonical_snapshot_sha256"] = "A" * 64
    elif mutation == "projection_hash":
        contract["projection_sha256"] = "0" * 64
    elif mutation == "target_counts":
        contract["destination_target_type_counts"] = {"service": 2}
    else:
        contract["source_page_type_item_counts"] = {"service": 2}
    _reseal_manifest(manifest, ruleset)
    manifest_sha = _write(manifest_path, manifest)

    with pytest.raises(PublicCopyManifestError, match="(?i)operator"):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_snapshot",
        "extra_snapshot_key",
        "missing_table_key",
        "extra_table_key",
        "missing_qa_key",
        "extra_qa_key",
    ],
)
def test_rejects_resealed_immutable_history_snapshot_contract_drift(
    tmp_path: Path,
    mutation: str,
) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, manifest, ruleset = _package_files(
        tmp_path
    )
    snapshot = manifest["immutable_history_snapshot"]
    if mutation == "missing_snapshot":
        manifest.pop("immutable_history_snapshot")
    elif mutation == "extra_snapshot_key":
        snapshot["unexpected_history_table"] = {}
    elif mutation == "missing_table_key":
        snapshot["generated_page_revisions"].pop("row_count")
    elif mutation == "extra_table_key":
        snapshot["page_composition_revisions"]["unexpected"] = 1
    elif mutation == "missing_qa_key":
        snapshot["generated_page_qa_results"].pop("current_row_ids")
    else:
        snapshot["generated_page_qa_results"]["unexpected"] = 1
    _reseal_manifest(manifest, ruleset)
    manifest_sha = _write(manifest_path, manifest)

    with pytest.raises(
        PublicCopyManifestError,
        match="immutable_history_snapshot|Immutable",
    ):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


@pytest.mark.parametrize(
    ("table_name", "field", "value"),
    [
        (table_name, field, value)
        for table_name in (
            "generated_page_revisions",
            "page_composition_revisions",
            "generated_page_qa_results",
        )
        for field in ("row_count", "maximum_id")
        for value in (True, 0)
    ],
)
def test_rejects_resealed_immutable_history_nonpositive_or_boolean_counts(
    tmp_path: Path,
    table_name: str,
    field: str,
    value: bool | int,
) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, manifest, ruleset = _package_files(
        tmp_path
    )
    manifest["immutable_history_snapshot"][table_name][field] = value
    _reseal_manifest(manifest, ruleset)
    manifest_sha = _write(manifest_path, manifest)

    with pytest.raises(
        PublicCopyManifestError,
        match=rf"immutable_history_snapshot\.{table_name}\.{field} must be a positive integer",
    ):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


@pytest.mark.parametrize(
    ("table_name", "field"),
    [
        ("generated_page_revisions", "canonical_rows_sha256"),
        ("page_composition_revisions", "canonical_rows_sha256"),
        ("generated_page_qa_results", "canonical_rows_sha256"),
        ("generated_page_qa_results", "canonical_noncurrent_rows_sha256"),
        (
            "generated_page_qa_results",
            "canonical_current_preserved_rows_sha256",
        ),
    ],
)
def test_rejects_resealed_immutable_history_malformed_hashes(
    tmp_path: Path,
    table_name: str,
    field: str,
) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, manifest, ruleset = _package_files(
        tmp_path
    )
    manifest["immutable_history_snapshot"][table_name][field] = "A" * 64
    _reseal_manifest(manifest, ruleset)
    manifest_sha = _write(manifest_path, manifest)

    with pytest.raises(
        PublicCopyManifestError,
        match=rf"immutable_history_snapshot\.{table_name}\.{field} must be a lowercase SHA-256",
    ):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


@pytest.mark.parametrize(
    "current_row_ids",
    [
        [61, 60],
        [61, 61],
        [62],
    ],
    ids=["unsorted", "duplicate", "different-from-binding"],
)
def test_rejects_resealed_immutable_qa_current_row_identity_drift(
    tmp_path: Path,
    current_row_ids: list[int],
) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, manifest, ruleset = _package_files(
        tmp_path
    )
    manifest["immutable_history_snapshot"]["generated_page_qa_results"][
        "current_row_ids"
    ] = current_row_ids
    _reseal_manifest(manifest, ruleset)
    manifest_sha = _write(manifest_path, manifest)

    with pytest.raises(
        PublicCopyManifestError,
        match="Immutable QA snapshot current-row identities",
    ):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


def test_rejects_resealed_immutable_qa_current_id_above_history_maximum(
    tmp_path: Path,
) -> None:
    manifest_path, _, ruleset_path, ruleset_sha, manifest, ruleset = _package_files(
        tmp_path
    )
    manifest["immutable_history_snapshot"]["generated_page_qa_results"][
        "maximum_id"
    ] = 60
    _reseal_manifest(manifest, ruleset)
    manifest_sha = _write(manifest_path, manifest)

    with pytest.raises(
        PublicCopyManifestError,
        match="Immutable QA snapshot.*maximum|maximum_id|current-row",
    ):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)


def test_rejects_manifest_path_symlink_before_dereference(tmp_path: Path) -> None:
    manifest_path, manifest_sha, ruleset_path, ruleset_sha, *_ = _package_files(
        tmp_path
    )
    link = tmp_path / "manifest-link.json"
    try:
        link.symlink_to(manifest_path)
    except OSError as exc:
        pytest.skip(f"Symlink creation is unavailable: {exc}")

    with pytest.raises(PublicCopyManifestError, match="regular non-symlink file"):
        _load(link, manifest_sha, ruleset_path, ruleset_sha)


def test_rejects_execution_source_symlink_parent_component(tmp_path: Path) -> None:
    manifest_path, manifest_sha, ruleset_path, ruleset_sha, *_ = _package_files(
        tmp_path
    )
    services = tmp_path / "source-root/backend/app/services"
    real_services = tmp_path / "source-root/backend/app/real-services"
    services.rename(real_services)
    try:
        services.symlink_to(real_services, target_is_directory=True)
    except OSError as exc:
        real_services.rename(services)
        pytest.skip(f"Directory symlink creation is unavailable: {exc}")

    with pytest.raises(PublicCopyManifestError, match="symlink|reparse"):
        _load(manifest_path, manifest_sha, ruleset_path, ruleset_sha)
