"""Sign a credential-free public-browser DOM capture without retaining its HTML.

The helper reads a rendered public DOM from standard input, validates the locked
Orlando identity, and writes only the normalized signed evidence JSON. It never
accepts credentials, cookies, authorization headers, browser profiles, or admin
session exports. Use --dry-run-fixture only for local/static validation.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import uuid

from app.services.wordpress_rendered_state import EXPECTED_URL, build_manual_browser_evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Signed evidence JSON output path")
    parser.add_argument("--final-url", default=EXPECTED_URL)
    parser.add_argument("--evidence-id", default=f"orlando-{uuid.uuid4()}")
    parser.add_argument("--dry-run-fixture", type=Path, help="Local/static HTML fixture; forbidden for live evidence")
    args = parser.parse_args()
    signing_key = os.getenv("ATLAS_BROWSER_EVIDENCE_HMAC_KEY", "")
    if not signing_key:
        parser.error("ATLAS_BROWSER_EVIDENCE_HMAC_KEY must be present only in the local helper environment")
    if args.dry_run_fixture:
        html = args.dry_run_fixture.read_text(encoding="utf-8")
    else:
        if sys.stdin.isatty():
            parser.error("Pipe the public browser's rendered DOM through standard input; HTML files are not retained")
        html = sys.stdin.read()
    evidence = build_manual_browser_evidence(
        html,
        final_url=args.final_url,
        evidence_identifier=args.evidence_id,
        signing_key=signing_key,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
