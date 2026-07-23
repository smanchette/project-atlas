# Project Atlas v0.59.92 — Retirement public-observation contract

v0.59.92 repairs the data contract between rendered-state acquisition and guarded Bootstrap-authorization retirement. A verified public acquisition now returns the same rendered identity at the top level and within a sanitized `public_http_observation`. A later successful authenticated acquisition retains the preceding credential-free public transport observation rather than discarding it.

The canonical nested observation is `project-atlas-public-http-observation-v1`. It contains only the exact requested/final URL, origin, redirect and HTTP facts, sanitized provider signals, cache and response-source classification, challenge/privacy classification, rendered identity hashes, and safe transport category. It excludes credentials, cookies, authorization headers, raw evidence signatures, response bodies, and volatile request identifiers.

Transport failures remain fail-closed but are no longer mislabeled as origin drift. DNS, connect timeout, read timeout, TLS, generic network, and other acquisition failures retain stable safe reason codes. Only a real response whose final origin or redirect state is wrong maps to origin drift.

SiteGround cache qualification is unchanged: only `HIT` can satisfy the retirement cache gate. `EXPIRED`, `MISS`, `BYPASS`, missing cache state, invalid values, unverified providers, mismatched rendered identities, and incompatible response sources all block retirement without issuing a handle or writing Atlas or WordPress state.
