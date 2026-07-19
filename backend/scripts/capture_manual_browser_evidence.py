"""Sign a byte-exact credential-free public-browser DOM capture.

Live input must be an unpredictable temporary file under the approved ignored
runtime directory. The helper independently hashes and strictly decodes its bytes,
then removes the raw DOM on every exit path. Standard input is intentionally not
supported because host shells can transcode native-pipeline text. Use
--dry-run-fixture only for local/static validation.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import uuid

from app.services.wordpress_browser_evidence_transport import (
    BrowserEvidenceTransportError,
    consume_browser_evidence_input,
    decode_browser_evidence_utf8,
    remove_browser_evidence_input,
)
from app.services.wordpress_rendered_state import EXPECTED_URL, build_manual_browser_evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Signed evidence JSON output path")
    parser.add_argument("--final-url", default=EXPECTED_URL)
    parser.add_argument("--evidence-id", default=f"orlando-{uuid.uuid4()}")
    parser.add_argument("--schema-version", type=int, choices=(1, 2), default=1)
    parser.add_argument("--input-file", type=Path, help="Byte-exact live DOM staged under the approved .runtime directory")
    parser.add_argument("--expected-input-sha256", help="Capture-side SHA-256; independently recomputed by this helper")
    parser.add_argument("--dry-run-fixture", type=Path, help="Local/static HTML fixture; forbidden for live evidence")
    args = parser.parse_args()
    live_input = args.input_file
    try:
        signing_key = os.getenv("ATLAS_BROWSER_EVIDENCE_HMAC_KEY", "")
        if not signing_key:
            parser.error("ATLAS_BROWSER_EVIDENCE_HMAC_KEY must be present only in the local helper environment")
        if bool(args.input_file) == bool(args.dry_run_fixture):
            parser.error("Select exactly one of --input-file or --dry-run-fixture; standard input is forbidden")
        if args.dry_run_fixture and args.expected_input_sha256:
            parser.error("--expected-input-sha256 is reserved for byte-exact live input")
        if args.input_file and not args.expected_input_sha256:
            parser.error("--expected-input-sha256 is required with --input-file")
        if args.dry_run_fixture:
            html = decode_browser_evidence_utf8(args.dry_run_fixture.read_bytes())
        else:
            consumed = consume_browser_evidence_input(live_input, args.expected_input_sha256)
            html = consumed.html
        evidence = build_manual_browser_evidence(
            html,
            final_url=args.final_url,
            evidence_identifier=args.evidence_id,
            signing_key=signing_key,
            schema_version=args.schema_version,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    except BrowserEvidenceTransportError as exc:
        parser.error(exc.reason)
    finally:
        if live_input is not None:
            try:
                remove_browser_evidence_input(live_input)
            except BrowserEvidenceTransportError as exc:
                parser.error(exc.reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
