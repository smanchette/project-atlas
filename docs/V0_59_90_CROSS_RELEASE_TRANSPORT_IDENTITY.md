# Project Atlas v0.59.90 — Cross-Release Public Transport Identity

## Scope

This release corrects one local Atlas verification defect. It does not upload,
activate, deactivate, or delete a plugin; access live WordPress; capture browser
evidence; or mutate an existing establishment audit.

The affected workflow is the fresh, signed schema-v1 verification of a manually
installed, inactive Upgrade Bootstrap 0.3.0. Historical authorization evidence
remains immutable.

## Root cause

The v0.59.84 authorization audit stored a stable public transport observation
from the then-current HTTP client. SiteGround/nginx returned a provider-verified
HTTP 403, while signed credential-free browser evidence independently proved the
exact public Orlando page. In v0.59.89, Atlas centralized the WordPress HTTP
client and introduced the stable `Project-Atlas-WordPress/<release>` User-Agent.
That approved transport change also changed implementation and diagnostic
representation. The former verifier compared the complete normalized transport
objects for literal equality, so equivalent SiteGround/nginx provider-block
representations could be reported as
`manual_install_verification_stable_identity_mismatch`.

The failure did not identify page, metadata, privacy, origin, redirect, plugin,
backup, or runtime drift.

The historical normalized `public_transport` SHA-256 is
`413816e6bd6625146afcda70a14957e5c6a5d9e8a0ccff46e2054c2faa126e24`.
The failed run did not durably store its fresh automated HTTP observation, so
its individual transport fields cannot be recovered without another live
request and are deliberately reported as unknown. The reported HTTP 200 is the
credential-free browser navigation, not proof that the separate automated
transport observation was HTTP 200. No unknown value is fabricated.

The production-shaped regression fixture uses the stored historical transport
and the current centralized-client representation. Its fresh raw transport
SHA-256 is
`31855eb0a4e9acb6ecedbfd20b6db2221ca64d1dea06ac76c73b9a95683e4a79`;
its derived canonical stable fingerprint is
`b4a7e90503cd6c51974337d326c373a3dfbff3b57b4c3f7fab683d902c0e343d`.

## Field-level diagnosis

| Component | Authorization | Failed fresh report | Classification | Stable/security treatment |
| --- | --- | --- | --- | --- |
| Requested/final URL | Exact Orlando URL | Exact Orlando URL | stable, equal | included; drift blocks |
| Redirects | 0 | 0 | stable, equal | included; drift blocks |
| Automated HTTP status/source | 403 provider block | not persisted | stable, unknown | exact semantics required; no 403/200 equivalence |
| Browser navigation status | public page available | 200 | diagnostic, equivalent page acquisition | not substituted for automated transport status |
| Content type | HTML | browser HTML; automated value unknown | stable where automated | non-HTML blocks |
| Title/H1/canonical/image | locked Orlando identity | exact | stable, equal | included; drift blocks |
| Raw DOM | not present in durable normalized snapshot | `51571a5347272e9d5374e1b45a530bfdf6f29435a936c50713075c5346dd334a` in run report | stable where both available | mismatch blocks; unknown is not invented |
| Rendered head | `bcb0da0da59dd66b618871887cf3d4b2bc2cf1d24b958947b6cb95251e9ef570` | same | stable, equal | included |
| Visible content | `5f785c372e7c86089659c447f413b879785b5f2dc8d58e476b5a67f22a6a3900` | same | stable, equal | included |
| Metadata inventory | `258be9781b02ac428ec44abc2437654aa20ae1ef558e978a3162ca77259c048a` | same | stable, equal | included |
| Privacy/authentication | credential-free; no cookie/admin/login/challenge | same | stable, equal | included; any drift blocks |
| Schema/helper | schema-v1 approved helper | schema-v1 approved helper | stable, equal | included |
| Provider | SiteGround/nginx verified via sanitized provider headers | automated raw value not persisted | stable, unknown | SiteGround/nginx identity required |
| User-Agent/client/policy label | pre-v0.59.89 implementation | centralized Atlas client | implementation detail | excluded only as a literal/versioned diagnostic |
| Date/Age/ETag/request IDs/order | historical diagnostic values | potentially different | volatile/diagnostic | excluded |
| Runtime/backup/plugin/payload/page/media/settings | audit-bound values | all gates passed | stable, equal | existing independent gates unchanged |

This establishes the exact failing component category (`public_transport` raw
serialization) while distinguishing known values from the unavailable fresh
automated subfields. The correction does not assume that every possible raw
transport difference is compatible.

## Versioned compatibility contract

The derived comparison contract is
`project-atlas-public-transport-identity-v2`. It compares the immutable
authorization observation to the fresh observation in that direction and
applies only to manual-bootstrap verification and its subsequent fixed-entry
activation revalidation.

It accepts a cross-release representation only when all of the following remain
true:

1. Both responses retain the same permitted security source: a provider-verified
   HTTP 403 block or a provider-verified HTTP 200 public page.
2. Both observations use the exact Orlando request and final URL with zero
   redirects and HTML content.
3. Both observations prove the SiteGround provider through sanitized cache
   headers and the nginx server identity; an explicit HIT/MISS/BYPASS cache
   state, when present, must remain equal.
4. The exact response-source security meaning is unchanged: provider-verified
   HTTP 403 remains provider-verified HTTP 403, or provider-verified HTTP 200
   remains provider-verified HTTP 200.
5. For HTTP 200, both public-response head and visible-content hashes equal the
   corresponding signed schema-v1 evidence hashes.
6. The signed title, H1, canonical, featured-image, metadata-inventory, privacy,
   Atlas-marker, and media-32 findings are unchanged.
7. No challenge, error, admin, login, authenticated, cookie, authorization, or
   secret-bearing classification is present.

The compatibility fingerprint excludes only transport artifacts that cannot
define page identity: the client User-Agent, response timing, cache age, ETag,
request identifiers, blocked-response body bytes, and header order. The raw
historical and fresh observations are retained separately for diagnostics.

## Fail-closed boundaries

The following remain hard failures with deterministic reason codes:

- any response-status or response-source transition, including 403 to 200 or
  200 to 403;
- HTTP 202 or any challenge/error classification;
- request/final URL or redirect drift;
- missing or changed SiteGround/nginx provider identity;
- title, H1, canonical, image, metadata-inventory, head, visible-content, or
  raw-DOM drift;
- any privacy/authentication drift;
- page, media, plugin inventory, backup, or runtime drift.

The primary safe diagnostic codes are:

- `manual_install_verification_transport_compatibility_applied`;
- `manual_install_verification_response_source_drift`;
- `manual_install_verification_provider_identity_drift`;
- `manual_install_verification_origin_drift`;
- `manual_install_verification_privacy_transport_drift`;
- `manual_install_verification_stable_page_identity_mismatch`;
- `manual_install_verification_rendered_hash_drift`.

The global cache-aware rendering comparator is not weakened. Its status,
provider, challenge, origin, redirect, temporal, and signed-browser bindings
remain unchanged.

## Durable audit behavior

No migration is required. The existing JSON snapshots already support the
additional derived diagnostics. A successful future verification stores:

- the comparison-contract version;
- whether the narrow compatibility rule was applied;
- the deterministic comparison reason;
- raw authorization and fresh stable fingerprints;
- the derived canonical fingerprint.

The original authorization evidence, original backup, active backup renewal,
transition history, nonce, and write counts are never rewritten by the
compatibility calculation. Failure performs zero Atlas and WordPress writes.
Equivalent successful retries remain idempotent, and activation remains bound
to the same verified audit, inventories, signed evidence, backup, and runtime.

## Locked artifacts

- Metadata Bridge 0.57.7 ZIP SHA-256:
  `ada4d97ea627a148d07fda809c1776a91a87d7a7e4957de3bece423a9bb80a62`
- Upgrade Bootstrap 0.3.0 ZIP SHA-256:
  `de5bfb7875b6f84f2009ef2043c1c86c7f9d20f0f973a5cb16b478fe37e83bef`

Neither artifact changes in v0.59.90.
