# Project Atlas v0.59.19 WordPress heading contract

This release separates the semantic page heading stored by Atlas from the HTML level used for the first heading inside WordPress post content.

## Explicit rendering policy

- A page without an explicit template capability retains the existing contract: the body owns the primary H1 and Atlas renders its stored `h1` value as `<h1>`.
- Atlas page 41 has an explicit capability stating that the WordPress template renders the primary H1. Its unchanged stored H1 wording is therefore rendered as `<h2>` inside post content.
- The policy is not inferred from the theme name or from heading text.

The v0.59.15 rendered-evidence contract remains unchanged and continues to require exactly one rendered H1.

## Future Orlando-only guarded correction

A later separately authorized workflow may update WordPress page 8 only after a read-only dry run verifies every locked field and the current canonical body hash `1144c89c046bfd74d3381560afdc5b7ec81f9a01e6de73fa929f2dc3b7ef7705`.

The proposed canonical body hash is `c031a7aa841b8e9a0316956dd3bf25178f390e64d01ceb9d9cd4273cc4aed195`.

The sole proposed content change is:

```html
<h1>Drywood Termite Tenting in Orlando, Florida</h1>
```

to:

```html
<h2>Drywood Termite Tenting in Orlando, Florida</h2>
```

The future WordPress request body must contain exactly one key, `content`. It must not contain title, slug, status, excerpt, featured media, template, parent, menu order, metadata, or media fields. Everything after the first heading must remain byte-for-byte or canonical-equivalent unchanged.

Before that request can be considered, the read-only planner must verify that page 8 remains published; its title, slug, URL, and featured media remain locked; the current body hash and H1 prefix match; exactly two H1 elements render in the expected order and containers; the proposed body changes only the first heading tag; the simulated result contains only the theme-owned H1; and the request shape is content-only. Any mismatch blocks.

The seven other mapped WordPress drafts retain the explicit default body-owned-H1 policy in v0.59.19. They require a separate template-capability review and explicit policy before their generated markup may change.

This document and implementation do not authorize that request. They do not authorize a WordPress edit, metadata apply, plugin installation or activation, cache purge, media change, audit, token, or nonce.
