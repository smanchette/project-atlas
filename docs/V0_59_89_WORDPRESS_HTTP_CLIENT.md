# Project Atlas v0.59.89 — WordPress HTTP Client Policy

## Incident and correction

The SiteGround/nginx edge returned a 52-byte HTML HTTP 403 response when Atlas
used httpx 0.27.2's default `python-httpx/0.27.2` User-Agent. From the same
backend container, DNS result, TLS path, and outbound address, both a browser
User-Agent and an explicit non-browser Atlas User-Agent reached WordPress JSON.
No SiteGround setting, WAF rule, allowlist, REST permission, or security plugin
was changed.

The single supported WordPress User-Agent is:

`Project-Atlas-WordPress/<verified-atlas-version>`

For this source release it is `Project-Atlas-WordPress/v0.59.89`. The version is
read from the checksum-verified runtime release identity. Before publication, or
in isolated tests where a matching runtime manifest cannot exist, the source
compatibility identity supplies the fail-safe release version. The policy never
falls back to `python-httpx/*` and never impersonates a browser.

## Shared client policy

`backend/app/services/wordpress_http.py` owns:

* the exact User-Agent and `Accept: application/json` defaults;
* construction of WordPress application-password `BasicAuth`;
* a 15-second default timeout and no-redirect default, with existing stricter
  workflow-specific timeout and redirect choices preserved explicitly within
  the fail-closed 1-to-60-second timeout range;
* TLS verification through httpx's verified default;
* exact configured-origin validation before every request and redirect;
* rejection of caller-supplied User-Agent overrides;
* rejection of caller-supplied, duplicate, or non-policy Authorization headers;
* safe response-source classification and sanitized diagnostic headers.

An authenticated redirect cannot forward credentials to another origin because
the request hook rejects the new origin before transmission. Mutation callers
retain their existing fixed methods, paths, bodies, handles, phrases, deadlines,
and no-retry behavior.

## Active request inventory

The shared policy covers Sandbox readiness and identity, draft create/review/
update/publish, deployment inspection, heading correction, media synchronization,
metadata lifecycle, rendered-state acquisition, activation, bootstrap
establishment, bootstrap cleanup for 0.57.5/0.57.6/0.57.7, plugin upgrades for
0.57.5/0.57.6/0.57.7, cache-aware rendering, SiteGround cache operations, and
recovery/reconciliation helpers used by those workflows. No active WordPress
caller directly constructs a production `httpx.Client` or `httpx.BasicAuth`.
Unrelated non-WordPress HTTP behavior was not changed.

## Connection result semantics

The Sandbox connection test reports independent facts:

1. credentials loaded in backend process memory;
2. anonymous REST reachability;
3. authenticated `/wp-json/wp/v2/users/me?context=edit` identity;
4. optional authenticated `/wp-json/project-atlas/v1/status` availability.

An HTML 403 before WordPress is `security_layer_block`, not an invalid password.
A WordPress JSON 401 is `wordpress_json_authentication_error`. A WordPress JSON
403 after reaching WordPress is `wordpress_json_authorization_error`. Credentials
remain reported as present when an earlier anonymous reachability request fails.
Timeout, TLS, and DNS/network failures retain distinct safe classifications, and
an authenticated-stage transport failure does not erase a successful anonymous
REST observation.

The application password remains process-memory only. It is never returned,
logged, included in diagnostics, written to Atlas records, placed in the runtime
manifest, or included in Program Backup.
