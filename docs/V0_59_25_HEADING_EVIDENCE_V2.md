# v0.59.25 heading observation diagnostics and evidence schema v2

This local-only release keeps the existing manual browser evidence subsystem and adds one explicitly routed version for the pre-correction Orlando duplicate-H1 state.

## Versioned evidence semantics

- Schema v1 is unchanged. It means exactly one visible H1 with the locked primary text and remains the expected post-correction evidence format. Existing v1 payloads and signatures retain their original meaning.
- Schema v2 is limited to the verified pre-correction state. It signs the complete v1 payload plus `h1_inventory`, `h1_count`, `primary_h1`, and `body_h1`.
- The ordered v2 inventory contains each H1's exact text, ordinal, deterministic DOM path, element and ancestor classes, visibility result, and deterministic source classification.
- V2 requires the theme-owned Post Title first and the Atlas body-content H1 second. Hidden, missing, reordered, altered, or additional H1 elements fail closed.
- Validators dispatch explicitly by schema version. V1 is never promoted to v2, unknown versions are rejected, and v2 is not accepted as the expected post-correction one-H1 state.

The approved helper defaults to schema v1. `--schema-version 2` must be selected explicitly for a pre-correction duplicate-H1 capture. The signature covers every evidence field except the signature itself, including the complete ordered inventory and all existing identity, metadata, hash, privacy, and absence fields.

## Heading-correction observation boundary

The dry run reports independent, safe diagnostics for authenticated page 8, media 31, media 32, and the credential-free rendered page. Each diagnostic records whether acquisition was attempted, its source, safe HTTP/final-URL details, success, and an exact failure code without retaining credentials, headers, cookies, or authenticated HTML.

Authenticated WordPress GETs remain mandatory for page identity, page body and hash, protected fields, media 31, and media 32. Signed evidence cannot replace any failed page or media observation.

Only a recognized bot-protection HTTP 403 may use valid schema-v2 evidence for the rendered portion. Generic errors, redirects, challenge documents, missing evidence, invalid signatures, expired evidence, and identity mismatches remain blocked. Missing page content produces a null body hash and explicit dependency failures rather than the SHA-256 of an empty string.

The dry run remains GET/read-only. A blocked run issues no token, consumes no nonce, creates no audit, and performs no Atlas or WordPress write. The apply workflow and its content-only request contract are unchanged.
