# Project Atlas v0.30 Draft Improvement Repair Plan

v0.30 is a planning-only checkpoint. It does not add application features,
schema changes, WordPress actions, publishing controls, media uploads, forms,
sticky phone bars, or draft update controls.

## Current State After v0.29

- Published Atlas pages: 0.
- WordPress draft references: 8.
- Successful `create_draft` audits: 8.
- Manual review records: 8.
- All 8 existing WordPress drafts are marked `needs_changes`.
- No page is safe for future manual publish review yet.
- WordPress visual review still requires a logged-in human pass because public
  draft URLs showed "Page not found" and admin links redirected to WordPress
  login.

Existing WordPress drafts:

| City | WordPress Post ID | Manual Review Status |
| --- | ---: | --- |
| Orlando | 8 | needs_changes |
| Winter Park | 9 | needs_changes |
| Deltona | 10 | needs_changes |
| Eatonville | 11 | needs_changes |
| Apopka | 12 | needs_changes |
| Sanford | 13 | needs_changes |
| Lake Mary | 14 | needs_changes |
| Winter Garden | 15 | needs_changes |

## Known Repair Needs

### City-Specific Local Context

All 8 pages need stronger city-specific local context before future manual
publish review. Local content should be grounded, conservative, and human
reviewed. Avoid invented landmarks, fake neighborhood claims, unsupported
termite prevalence claims, guarantees, or absolute safety language.

### Media and Alt Text

Apopka, Sanford, Lake Mary, and Winter Garden currently reuse the Orlando hero
image/alt text. These pages need media or page-specific alt text repair before
future manual publish review.

Minimum acceptable repair:

- Keep existing media files intact.
- Use page-specific alt overrides when a shared image is reused.
- Prefer neutral service-area wording if the image is not truly city-specific.
- Do not upload media to WordPress yet.
- Do not delete or destructively crop existing media files.

## Source of Truth

Atlas should remain the source of truth for draft content, media assignments,
metadata, QA, export packages, and audit records.

Do not directly edit WordPress drafts unless Atlas has a future controlled draft
update flow. Direct WordPress edits would cause Atlas export payloads and audit
records to drift from the WordPress draft state.

## Version Roadmap

### v0.31 - Atlas Content Repair Pass

Repair Atlas draft content for the 8 existing WordPress draft pages only.

Goals:

- Add stronger city-specific local context.
- Keep wording safe and conservative.
- Rerun QA after edits.
- Preserve revision history.
- Do not update WordPress drafts yet.

### v0.32 - Media and Alt Repair Pass

Repair media and alt text for the 8 existing WordPress draft pages.

Goals:

- Fix reused Orlando hero/alt text on Apopka, Sanford, Lake Mary, and Winter
  Garden.
- Use reviewed media and page-specific alt overrides where appropriate.
- Keep media changes in Atlas first.
- Do not upload media to WordPress yet.

### v0.33 - Layout and Conversion Template System

Plan and implement reusable Atlas-first layout controls. Do not build this in
v0.30.

Future layout system should support:

- Sticky mobile call button.
- Desktop sticky phone/contact bar.
- Small quote/contact form block.
- CTA block after intro.
- CTA block mid-page.
- CTA block near bottom.
- Trust strip with license, certified operator, and service area.
- Realtor/property-manager CTA option.
- Emergency/fast-scheduling CTA option.
- Reusable layout settings per business, service, and page type.
- Atlas preview first.
- Export payload preview second.
- Controlled WordPress draft update later.

### v0.34 - Controlled WordPress Draft-Update Sandbox

Create a safe update sandbox for existing WordPress drafts.

Required safety gates:

- Existing `wordpress_post_id` is present.
- WordPress mode is sandbox.
- Atlas page is approved or explicitly repair-approved.
- QA is ready and current.
- Export package has no blockers.
- Dry run shows old vs new payload.
- Confirmation phrase/token is required.
- WordPress status is forced to `draft`.
- Update audit is recorded.
- No publish, delete, media upload, or bulk update endpoint exists.

### v0.35 - One-Page Controlled WordPress Draft Update Test

Use the v0.34 sandbox to update exactly one WordPress draft.

Goals:

- Run dry run first.
- Confirm exact payload.
- Require explicit confirmation.
- Update one draft only.
- Verify Atlas and WordPress references remain safe.
- Do not publish.

## Backup Requirements Before Repairs

Before any repair implementation:

- Create a Data Backup.
- Create a Media Backup.
- Create a Program Backup.
- Confirm protected paths exist and remain untouched:
  - `backend/backups`
  - `backend/media`
  - `frontend/public/media`
- Record baseline counts:
  - Total pages.
  - Published Atlas pages.
  - WordPress draft refs.
  - Successful `create_draft` audits.
  - Manual review records.

## v0.30 Safety Boundary

v0.30 is documentation only. It does not:

- Publish anything.
- Upload media.
- Update or delete WordPress pages.
- Create WordPress drafts.
- Bulk create or bulk update.
- Auto-approve pages.
- Auto-rewrite drafts.
- Add publish controls.
- Add forms.
- Add sticky phone bars.
- Add draft update controls.
- Modify protected media or backup paths.
