# Project Atlas Metadata Bridge 0.57.7

This plugin is deliberately limited to WordPress page 8 and media 31. Installation performs no write. Activation and reactivation rotate the Atlas-owned safety generation and force rendering off. Version 0.57.7 preserves the separated lifecycle and cache-aware operations while making the metadata serializer a pure, query-context-independent renderer. The public `wp_head` wrapper retains strict page-8 and non-admin guards; the authenticated read-only preview calls the same pure renderer directly and no longer depends on `is_page()` during REST execution. The fixed SiteGround purge remains limited to the Orlando canonical URL. The legacy combined apply endpoint remains fail-closed.

The plugin does not change the WordPress Site Title, Tagline, title, H1, content, excerpt, slug, canonical URL, post status, featured image, or any media record. Media 32 is rejected from the payload and is never modified.
