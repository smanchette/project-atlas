# WordPress deployment artifacts

See `docs/V0_57_METADATA_DEPLOYMENT.md` before installing the versioned ZIP. Installation, activation, metadata apply, rollback, and any cache purge are separate controlled actions.

## Current Metadata Bridge boundary

Metadata Bridge 0.57.8 introduced the contained Performance Local V5 WordPress renderer. Metadata Bridge 0.57.9 added WordPress-native email delivery inside that same plugin family; it did not create a second plugin, a separate WordPress Theme, or another form architecture. Version 0.57.9 is the current staging target, but staging installation and activation have not occurred.

## Performance Local V5 form-delivery contract

- WordPress option: `_project_atlas_estimate_form_delivery_v1`
- Option schema: `project-atlas-estimate-form-delivery@1`
- REST route: `POST /wp-json/project-atlas/v4/performance-local-v5/estimate`
- Signed-token schema: `project-atlas-performance-local-v5-form-token@1`

Validated submissions use WordPress `wp_mail()` and a Website-configured private recipient. Atlas owns no direct SMTP transport or SMTP credentials; WordPress hosting or a separately configured SMTP plugin owns mail transport. The public Website contact email, private form-delivery recipient, and private From email are separate identities, and private delivery values must not enter public output.

Real staging delivery configuration and one controlled receipt test remain pending. Installing or activating the plugin does not authorize configuration, email delivery, publication, or deployment.

`project-atlas-upgrade-bootstrap-0.1.0.zip` is a separate single-purpose artifact for the guarded 0.57.4-to-0.57.5 bridge upgrade. Publication does not authorize its installation or activation. See `docs/V0_59_57_METADATA_BRIDGE_UPGRADE_BOOTSTRAP.md`.

`project-atlas-upgrade-bootstrap-0.2.0.zip` is a distinct, immutable helper for only the guarded 0.57.5-to-0.57.6 bridge upgrade. It preserves the staged payload and disabled rendering state, and it cannot authorize any other version transition. Publication does not authorize its installation, activation, use, or cleanup. See `docs/V0_59_71_METADATA_BRIDGE_UPGRADE.md`.

`project-atlas-upgrade-bootstrap-0.3.0.zip` is the distinct immutable helper for only the guarded 0.57.6-to-0.57.7 preview-renderer correction. It preserves the active plugin, staged payload, revision 1, disabled rendering, and protected page/media state. Publication does not authorize its installation, activation, use, cleanup, rendering, or cache operations. See `docs/V0_59_79_AUTHORITATIVE_METADATA_PREVIEW.md`.
