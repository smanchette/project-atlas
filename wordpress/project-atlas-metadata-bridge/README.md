# Project Atlas Metadata Bridge 0.57.4

This plugin is deliberately limited to WordPress page 8 and media 31. Installation performs no write. Activation and reactivation perform exactly one Atlas-owned safety-option write that rotates the activation generation and disables rendering; they never touch page 8 metadata. Rendering begins only after the guarded apply authorizes the current generation.

The plugin does not change the WordPress Site Title, Tagline, title, H1, content, excerpt, slug, canonical URL, post status, featured image, or any media record. Media 32 is rejected from the payload and is never modified.
