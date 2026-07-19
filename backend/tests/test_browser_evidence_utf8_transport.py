from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys

import pytest

from app.services.wordpress_browser_evidence_transport import (
    BrowserEvidenceTransportError,
    consume_browser_evidence_input,
    decode_browser_evidence_utf8,
    remove_browser_evidence_input,
    stage_browser_evidence_input,
)
from app.services.wordpress_rendered_state import (
    EXPECTED_H1,
    EXPECTED_MEDIA_ALT,
    EXPECTED_MEDIA_URL,
    EXPECTED_TITLE,
    EXPECTED_URL,
    validate_manual_browser_evidence,
)


KEY = "v0.59.80-local-transport-test-signing-key"


def locked_html(*, title: str = EXPECTED_TITLE, extra: str = "", newline: str = "\n") -> str:
    lines = [
        "<!doctype html><html><head>",
        '<meta charset="utf-8">',
        f"<title>{title}</title>",
        f'<link rel="canonical" href="{EXPECTED_URL}">',
        "</head><body>",
        f"<h1>{EXPECTED_H1}</h1>",
        f'<img class="wp-image-31" src="{EXPECTED_MEDIA_URL}" alt="{EXPECTED_MEDIA_ALT}">',
        f"<p>{extra or 'Orlando service content.'}</p>",
        "</body></html>",
    ]
    return newline.join(lines)


def assert_reason(reason: str, call) -> None:
    with pytest.raises(BrowserEvidenceTransportError) as result:
        call()
    assert result.value.reason == reason


@pytest.mark.parametrize(
    "text",
    [
        "literal en dash – preserved",
        "curly apostrophe ’ and quotations “exactly”",
        "accented café, naïve, São Paulo",
        "日本語とالعربية",
        "supplementary plane emoji 🧪🚀",
    ],
)
def test_unicode_bytes_round_trip_without_normalization(tmp_path: Path, text: str):
    root = tmp_path / ".runtime"
    raw = locked_html(extra=text).encode("utf-8")
    staged = stage_browser_evidence_input(raw, runtime_root=root)
    consumed = consume_browser_evidence_input(staged.path, staged.sha256, runtime_root=root)
    assert consumed.html == raw.decode("utf-8")
    assert consumed.sha256 == hashlib.sha256(raw).hexdigest()
    assert consumed.byte_size == len(raw)
    remove_browser_evidence_input(staged.path, runtime_root=root)
    assert not staged.path.exists()


def test_literal_en_dash_and_html_entity_identity_both_pass_existing_canonical_parser(tmp_path: Path):
    from app.services.wordpress_rendered_state import build_manual_browser_evidence

    root = tmp_path / ".runtime"
    for title in (EXPECTED_TITLE, EXPECTED_TITLE.replace("–", "&#8211;")):
        raw = locked_html(title=title).encode("utf-8")
        staged = stage_browser_evidence_input(raw, runtime_root=root)
        consumed = consume_browser_evidence_input(staged.path, staged.sha256, runtime_root=root)
        assert consumed.html.encode("utf-8") == raw
        value = build_manual_browser_evidence(
            consumed.html,
            final_url=EXPECTED_URL,
            evidence_identifier="orlando-entity-equivalence",
            signing_key=KEY,
        )
        assert value["page_identity"]["document_title"] == EXPECTED_TITLE
        remove_browser_evidence_input(staged.path, runtime_root=root)


def test_crlf_and_lf_are_preserved_as_distinct_exact_byte_sequences(tmp_path: Path):
    root = tmp_path / ".runtime"
    lf = locked_html(newline="\n").encode("utf-8")
    crlf = locked_html(newline="\r\n").encode("utf-8")
    assert hashlib.sha256(lf).hexdigest() != hashlib.sha256(crlf).hexdigest()
    for raw in (lf, crlf):
        staged = stage_browser_evidence_input(raw, runtime_root=root)
        consumed = consume_browser_evidence_input(staged.path, staged.sha256, runtime_root=root)
        assert consumed.html.encode("utf-8") == raw
        remove_browser_evidence_input(staged.path, runtime_root=root)


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (b"\xef\xbb\xbf<html></html>", "browser_evidence_input_utf8_bom_forbidden"),
        ("<html>replacement \ufffd</html>".encode("utf-8"), "browser_evidence_input_replacement_character"),
        ("<html>code page café</html>".encode("cp1252"), "browser_evidence_input_invalid_utf8"),
        ("<html>utf16</html>".encode("utf-16"), "browser_evidence_input_invalid_utf8"),
        (b"<html>truncated \xf0\x9f\x9a</html>", "browser_evidence_input_invalid_utf8"),
        (b"<html>invalid \xff</html>", "browser_evidence_input_invalid_utf8"),
    ],
)
def test_invalid_or_lossy_encodings_fail_closed(tmp_path: Path, raw: bytes, reason: str):
    root = tmp_path / ".runtime"
    staged = stage_browser_evidence_input(raw, runtime_root=root)
    assert_reason(reason, lambda: consume_browser_evidence_input(staged.path, staged.sha256, runtime_root=root))
    remove_browser_evidence_input(staged.path, runtime_root=root)


def test_hash_mismatch_and_caller_hash_injection_fail_closed(tmp_path: Path):
    root = tmp_path / ".runtime"
    raw = locked_html().encode("utf-8")
    staged = stage_browser_evidence_input(raw, runtime_root=root)
    other_hash = hashlib.sha256(locked_html(extra="different").encode("utf-8")).hexdigest()
    assert_reason(
        "browser_evidence_input_byte_mismatch",
        lambda: consume_browser_evidence_input(staged.path, other_hash, runtime_root=root),
    )
    assert_reason(
        "browser_evidence_input_hash_invalid",
        lambda: consume_browser_evidence_input(staged.path, "caller-controlled", runtime_root=root),
    )
    remove_browser_evidence_input(staged.path, runtime_root=root)


def test_stale_wrong_and_missing_input_files_fail_closed(tmp_path: Path):
    root = tmp_path / ".runtime"
    staged = stage_browser_evidence_input(locked_html().encode("utf-8"), runtime_root=root)
    stale = datetime.now(UTC) - timedelta(minutes=6)
    os.utime(staged.path, (stale.timestamp(), stale.timestamp()))
    assert_reason(
        "browser_evidence_input_stale",
        lambda: consume_browser_evidence_input(staged.path, staged.sha256, runtime_root=root),
    )
    wrong = tmp_path / "browser-evidence-input-wrong.html"
    wrong.write_bytes(locked_html().encode("utf-8"))
    assert_reason(
        "browser_evidence_input_path_unapproved",
        lambda: consume_browser_evidence_input(wrong, hashlib.sha256(wrong.read_bytes()).hexdigest(), runtime_root=root),
    )
    missing = root / "browser-evidence-input-missing.html"
    assert_reason(
        "browser_evidence_input_missing",
        lambda: consume_browser_evidence_input(missing, "0" * 64, runtime_root=root),
    )
    remove_browser_evidence_input(staged.path, runtime_root=root)


def test_cleanup_refuses_outside_path_without_deleting_it(tmp_path: Path):
    root = tmp_path / ".runtime"
    root.mkdir()
    outside = tmp_path / "browser-evidence-input-outside80.html"
    outside.write_bytes(b"must remain")
    assert_reason(
        "browser_evidence_input_cleanup_path_unapproved",
        lambda: remove_browser_evidence_input(outside, runtime_root=root),
    )
    assert outside.read_bytes() == b"must remain"


def test_symlink_escape_is_rejected_when_platform_supports_symlinks(tmp_path: Path):
    root = tmp_path / ".runtime"
    root.mkdir()
    target = tmp_path / "outside.html"
    target.write_bytes(locked_html().encode("utf-8"))
    link = root / "browser-evidence-input-link.html"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Symlink creation is unavailable for this Windows test process.")
    assert_reason(
        "browser_evidence_input_symlink_forbidden",
        lambda: consume_browser_evidence_input(link, hashlib.sha256(target.read_bytes()).hexdigest(), runtime_root=root),
    )


def test_cleanup_failure_is_explicit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    root = tmp_path / ".runtime"
    root.mkdir()
    path = root / "browser-evidence-input-cleanup80.html"
    path.write_bytes(b"safe")

    def fail_unlink(self, *, missing_ok=False):
        raise PermissionError("locked")

    monkeypatch.setattr(Path, "unlink", fail_unlink)
    assert_reason(
        "browser_evidence_input_cleanup_failed",
        lambda: remove_browser_evidence_input(path, runtime_root=root),
    )


def test_live_helper_consumes_exact_orlando_utf8_bytes_and_deletes_input(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    root = tmp_path / ".runtime"
    output = tmp_path / "signed-evidence.json"
    raw = locked_html(extra="Curly ’ café 日本語 🧪").encode("utf-8")
    staged = stage_browser_evidence_input(raw, runtime_root=root)
    monkeypatch.setenv("ATLAS_BROWSER_EVIDENCE_HMAC_KEY", KEY)
    monkeypatch.setenv("ATLAS_BROWSER_EVIDENCE_RUNTIME_DIR", str(root))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "capture_manual_browser_evidence.py",
            "--input-file",
            str(staged.path),
            "--expected-input-sha256",
            staged.sha256,
            "--output",
            str(output),
            "--evidence-id",
            "orlando-utf8-transport-test",
        ],
    )
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(Path(__file__).parents[1] / "scripts/capture_manual_browser_evidence.py"), run_name="__main__")
    assert result.value.code == 0
    assert not staged.path.exists()
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["page_identity"]["document_title"] == EXPECTED_TITLE
    assert validate_manual_browser_evidence(written, KEY) == (True, "Verified.")
    assert "<!doctype" not in output.read_text(encoding="utf-8").lower()


def test_live_helper_removes_input_when_locked_identity_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    root = tmp_path / ".runtime"
    output = tmp_path / "must-not-exist.json"
    raw = locked_html(title="Genuinely different title").encode("utf-8")
    staged = stage_browser_evidence_input(raw, runtime_root=root)
    monkeypatch.setenv("ATLAS_BROWSER_EVIDENCE_HMAC_KEY", KEY)
    monkeypatch.setenv("ATLAS_BROWSER_EVIDENCE_RUNTIME_DIR", str(root))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "capture_manual_browser_evidence.py",
            "--input-file",
            str(staged.path),
            "--expected-input-sha256",
            staged.sha256,
            "--output",
            str(output),
        ],
    )
    with pytest.raises(ValueError, match="locked title, H1, or canonical"):
        runpy.run_path(str(Path(__file__).parents[1] / "scripts/capture_manual_browser_evidence.py"), run_name="__main__")
    assert not staged.path.exists()
    assert not output.exists()


def test_live_helper_removes_input_when_required_hash_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    root = tmp_path / ".runtime"
    staged = stage_browser_evidence_input(locked_html().encode("utf-8"), runtime_root=root)
    monkeypatch.setenv("ATLAS_BROWSER_EVIDENCE_HMAC_KEY", KEY)
    monkeypatch.setenv("ATLAS_BROWSER_EVIDENCE_RUNTIME_DIR", str(root))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "capture_manual_browser_evidence.py",
            "--input-file",
            str(staged.path),
            "--output",
            str(tmp_path / "must-not-exist.json"),
        ],
    )
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(Path(__file__).parents[1] / "scripts/capture_manual_browser_evidence.py"), run_name="__main__")
    assert result.value.code == 2
    assert not staged.path.exists()


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("title", "Drywood Termite Tenting in Orlando, Florida – My WordPress"),
        ("h1", "Drywood Termite Tenting in Orlando, Florida"),
        ("canonical", "https://www.drywoodtenting.com/wrong/"),
    ],
)
def test_real_identity_differences_are_not_normalized_away(field: str, replacement: str):
    html = locked_html()
    if field == "title":
        html = html.replace(EXPECTED_TITLE, replacement)
    elif field == "h1":
        html = html.replace(f"<h1>{EXPECTED_H1}</h1>", f"<h1>{replacement}</h1>")
    else:
        html = html.replace(EXPECTED_URL, replacement)
    from app.services.wordpress_rendered_state import build_manual_browser_evidence

    with pytest.raises(ValueError, match="locked title, H1, or canonical"):
        build_manual_browser_evidence(
            html,
            final_url=EXPECTED_URL,
            evidence_identifier="orlando-real-difference",
            signing_key=KEY,
        )


def test_standard_input_transport_is_absent_from_helper_source():
    source = (Path(__file__).parents[1] / "scripts/capture_manual_browser_evidence.py").read_text(encoding="utf-8")
    assert "sys.stdin" not in source
    assert "--input-file" in source
    assert "--expected-input-sha256" in source


def test_fixture_decoder_preserves_exact_bytes_and_rejects_bom():
    raw = locked_html(newline="\r\n").encode("utf-8")
    assert decode_browser_evidence_utf8(raw).encode("utf-8") == raw
    assert_reason(
        "browser_evidence_input_utf8_bom_forbidden",
        lambda: decode_browser_evidence_utf8(b"\xef\xbb\xbf" + raw),
    )
