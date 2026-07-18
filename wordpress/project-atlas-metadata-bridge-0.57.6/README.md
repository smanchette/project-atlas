# Project Atlas Metadata Bridge 0.57.6

This plugin is deliberately limited to WordPress page 8 and media 31. Installation performs no write. Activation and reactivation rotate the Atlas-owned safety generation and force rendering off. Version 0.57.6 preserves the four separated lifecycle operations and adds two guarded cache-aware operations: an authenticated read-only preview that invokes the same public-head renderer, and a fixed single-URL SiteGround purge that can target only the canonical Orlando URL. The legacy combined apply endpoint is fail-closed and cannot enable rendering.

The plugin does not change the WordPress Site Title, Tagline, title, H1, content, excerpt, slug, canonical URL, post status, featured image, or any media record. Media 32 is rejected from the payload and is never modified.
