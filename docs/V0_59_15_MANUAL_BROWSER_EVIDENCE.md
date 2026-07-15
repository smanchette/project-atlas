# v0.59.15 manual browser evidence contract

This contract is a fail-closed fallback for the Orlando installation preflight when automated public, authenticated, and independently verified cache-bypass rendering cannot provide trusted rendered hashes. It does not authorize installation and is accepted only by the shared read-only inspection used by the token-free preflight and, later, the separately initiated authorization dry run.

## Capture boundary

The helper accepts one credential-free public browser DOM captured from exactly:

`https://www.drywoodtenting.com/drywood-termite-tenting-orlando-fl/`

It accepts no credentials, cookies, authorization header, browser profile, authenticated HTML, admin session, redirect, or non-HTML/error response. It rejects login/admin URLs, challenges, error/fallback pages, secret-like material, media 32, unexpected metadata, duplicates, and any mismatch in the locked title, H1, canonical, featured-image URL, or featured-image alt text.

The command-line helper reads live DOM through standard input so it does not require a raw HTML file. Its `--dry-run-fixture` option exists only for local/static testing. It writes only normalized signed JSON. The HMAC key is read from `ATLAS_BROWSER_EVIDENCE_HMAC_KEY` in the helper's local process and is neither accepted as an argument nor included in evidence.

## Exact schema

The top-level object is strict; unknown or missing fields fail validation.

- `evidence_schema`: `project-atlas-manual-browser-evidence`
- `evidence_schema_version`: `1`
- `capture_helper_version`: `0.59.15`
- `evidence_id`
- canonical UTC `captured_at` and `expires_at` strings in `YYYY-MM-DDTHH:MM:SS.ffffffZ` form
- `final_url` and `acquisition_source` (`credential_free_public_browser`)
- `navigation_outcome`: HTTP 200, `text/html`, zero redirects, `success`
- `page_identity`: exact title, H1, canonical, featured-image URL, and alt text
- `metadata_inventory` and its SHA-256
- inventory-derived `absence_findings`
- `normalized_head` and `normalized_visible_content`
- deterministic SHA-256 values for both normalized rendered payloads
- `privacy_attestations`
- `helper_signature`

The complete normalized inventory includes every description, canonical, `og:*`, `twitter:*`, and `application/ld+json` item; title and canonical counts; Atlas ownership markers; featured-image and media-32 references; unexpected owners; and duplicate findings. The validator independently recomputes the inventory hash and absence findings. Submitted booleans cannot override the inventory.

Privacy attestations are fixed consequences of the helper's credential-free execution mode: credentials were not used; cookies, authorization headers, and authenticated HTML were not stored; no admin session was used; and no secrets were detected. Any contrary input is rejected before signing.

## Normalization

All text is Unicode NFC-normalized and whitespace is collapsed. Attribute names are lowercased and attributes are sorted. Nonces, integrity/cross-origin values, WordPress-generated volatile ID/class tokens, and non-JSON-LD script/style/template content are excluded. URL scheme and host casing are normalized, and only recognized cache-busting query keys (`_`, `cb`, `cache`, `cachebust`, `timestamp`, `v`, and `ver`) are removed. JSON-LD is parsed into canonical JSON. Inventory list order is retained, so reorderings or duplicates alter the signed payload.

The rendered-head hash is SHA-256 over canonical JSON containing normalized page/head elements and the complete inventory. The visible-content hash is SHA-256 over NFC-normalized, whitespace-collapsed visible body text excluding scripts, styles, noscript, and templates. Both normalized values are signed, and the validator recomputes both hashes.

## Signature and lifetime

HMAC-SHA-256 covers every top-level field except `helper_signature`, using UTF-8 canonical JSON with sorted object keys. This includes all nested inventory data, derived findings, normalized rendered payloads, hashes, privacy values, identifiers, versions, and timestamps. Any altered field invalidates the signature.

Signed timestamps use UTC only, an uppercase `Z`, and exactly six fractional-second digits. Capture and validation normalize timezone-aware inputs to that representation before calculating signature bytes; neither relies on incidental JSON or Pydantic datetime serialization. Evidence generated before the v0.59.34 canonicalization correction used a different signed timestamp meaning and must be recaptured rather than reused.

Evidence is valid for exactly 15 minutes. A missing/invalid signature, unsupported schema/helper, malformed or naive timestamp, altered lifetime, future capture, or expired evidence fails closed.

## Operator workflow

1. Use a new credential-free browser context and visit only the locked public Orlando URL.
2. Confirm the final URL is exact and there was no redirect, login, admin, challenge, error, or fallback response.
3. Pipe the rendered public DOM directly to `backend/scripts/capture_manual_browser_evidence.py`; do not save cookies, credentials, authorization headers, a browser profile, or authenticated HTML.
4. Select the resulting signed JSON with **Capture signed browser evidence** in Atlas.
5. Review the displayed schema/helper, evidence ID, timestamps, identity, inventory summary, hashes, privacy findings, and signature-validation status.
6. Run **Run token-free preflight**. The server independently validates the complete contract.
7. Stop. Evidence capture and token-free preflight do not enter **Enter Authorization Phase**, sign an authorization token, consume a nonce, create an audit/transition, or write to Atlas or WordPress.

Manual evidence is not a general cache bypass and is not permitted when automated trusted rendered evidence is available. It exists solely so a credential-free real browser can provide a narrowly locked, short-lived, signed rendering observation when the deployment worker is blocked by bot protection.
