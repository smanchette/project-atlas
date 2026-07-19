# Project Atlas Metadata Bridge 0.57.5

This plugin is deliberately limited to WordPress page 8 and media 31. Installation performs no write. Activation and reactivation rotate the Atlas-owned safety generation and force rendering off. Version 0.57.5 separates payload staging, rendering enablement, rendering disablement, and payload rollback into four fixed REST operations. The legacy combined apply endpoint is fail-closed and cannot enable rendering.

The plugin does not change the WordPress Site Title, Tagline, title, H1, content, excerpt, slug, canonical URL, post status, featured image, or any media record. Media 32 is rejected from the payload and is never modified.
