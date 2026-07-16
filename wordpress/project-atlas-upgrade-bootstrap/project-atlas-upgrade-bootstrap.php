<?php
/**
 * Plugin Name: Project Atlas Upgrade Bootstrap
 * Description: Single-purpose authenticated bootstrap for the fixed Metadata Bridge 0.57.4 to 0.57.5 replacement.
 * Version: 0.1.0
 * Author: Project Atlas
 */

declare(strict_types=1);

if (!defined('ABSPATH')) {
    exit;
}

const ATLAS_UPGRADE_BOOTSTRAP_VERSION = '0.1.0';
const ATLAS_UPGRADE_BOOTSTRAP_ROUTE_NAMESPACE = 'project-atlas-deployment/v1';
const ATLAS_UPGRADE_BOOTSTRAP_ROUTE = '/metadata-bridge/upgrade-0575';
const ATLAS_UPGRADE_BOOTSTRAP_STATUS_ROUTE = '/metadata-bridge/upgrade-0575/status';
const ATLAS_UPGRADE_BOOTSTRAP_TARGET_PLUGIN = 'project-atlas-metadata-bridge/project-atlas-metadata-bridge.php';
const ATLAS_UPGRADE_BOOTSTRAP_CURRENT_VERSION = '0.57.4';
const ATLAS_UPGRADE_BOOTSTRAP_TARGET_VERSION = '0.57.5';
const ATLAS_UPGRADE_BOOTSTRAP_TARGET_ZIP = 'project-atlas-metadata-bridge-0.57.5.zip';
const ATLAS_UPGRADE_BOOTSTRAP_TARGET_ZIP_SHA256 = '09ec2903cd8367fafef97a8999d816245e8865694010929c6aa498c6abbf12b7';
const ATLAS_UPGRADE_BOOTSTRAP_TARGET_ENTRY_SHA256 = '64a20b6d6a03cef5430dd19fdc1e7eebfd6a3a0f8dcb201eaae5ee30250a3d5c';
const ATLAS_UPGRADE_BOOTSTRAP_TARGET_README_SHA256 = '1fe57ecff9906707ae84e6b725f44f59d6e1195d9e4bf6300cce7b1667ca71ab';

function atlas_upgrade_bootstrap_permission(): bool
{
    return current_user_can('update_plugins');
}

function atlas_upgrade_bootstrap_plugin_data(): array
{
    require_once ABSPATH . 'wp-admin/includes/plugin.php';
    $path = WP_PLUGIN_DIR . '/' . ATLAS_UPGRADE_BOOTSTRAP_TARGET_PLUGIN;
    if (!is_file($path)) {
        return ['installed' => false, 'active' => false, 'version' => null, 'checksum' => null];
    }
    $data = get_plugin_data($path, false, false);
    return [
        'installed' => true,
        'active' => is_plugin_active(ATLAS_UPGRADE_BOOTSTRAP_TARGET_PLUGIN),
        'version' => (string) ($data['Version'] ?? ''),
        'checksum' => hash_file('sha256', $path),
    ];
}

function atlas_upgrade_bootstrap_status(): WP_REST_Response
{
    $plugin = atlas_upgrade_bootstrap_plugin_data();
    return rest_ensure_response([
        'bootstrap' => 'project-atlas-upgrade-bootstrap',
        'bootstrap_version' => ATLAS_UPGRADE_BOOTSTRAP_VERSION,
        'bootstrap_checksum' => hash_file('sha256', __FILE__),
        'operation' => 'upgrade_metadata_bridge_0.57.4_to_0.57.5',
        'application_password_compatible' => true,
        'target_plugin' => ATLAS_UPGRADE_BOOTSTRAP_TARGET_PLUGIN,
        'current_version' => ATLAS_UPGRADE_BOOTSTRAP_CURRENT_VERSION,
        'target_version' => ATLAS_UPGRADE_BOOTSTRAP_TARGET_VERSION,
        'target_zip' => ATLAS_UPGRADE_BOOTSTRAP_TARGET_ZIP,
        'target_zip_sha256' => ATLAS_UPGRADE_BOOTSTRAP_TARGET_ZIP_SHA256,
        'available' => (
            $plugin['installed'] === true
            && $plugin['active'] === true
            && hash_equals(ATLAS_UPGRADE_BOOTSTRAP_CURRENT_VERSION, (string) $plugin['version'])
        ),
        'plugin' => $plugin,
    ]);
}

function atlas_upgrade_bootstrap_validate_archive(string $path)
{
    if (!class_exists('ZipArchive')) {
        return new WP_Error('atlas_zip_unavailable', 'ZipArchive is unavailable.', ['status' => 503]);
    }
    if (!is_file($path) || !hash_equals(ATLAS_UPGRADE_BOOTSTRAP_TARGET_ZIP_SHA256, (string) hash_file('sha256', $path))) {
        return new WP_Error('atlas_artifact_mismatch', 'The fixed upgrade artifact checksum is invalid.', ['status' => 422]);
    }
    $zip = new ZipArchive();
    if ($zip->open($path) !== true) {
        return new WP_Error('atlas_archive_invalid', 'The fixed upgrade artifact cannot be opened.', ['status' => 422]);
    }
    $expected = [
        'project-atlas-metadata-bridge/project-atlas-metadata-bridge.php' => ATLAS_UPGRADE_BOOTSTRAP_TARGET_ENTRY_SHA256,
        'project-atlas-metadata-bridge/README.md' => ATLAS_UPGRADE_BOOTSTRAP_TARGET_README_SHA256,
    ];
    $seen = [];
    for ($index = 0; $index < $zip->numFiles; $index++) {
        $name = $zip->getNameIndex($index);
        if (
            !is_string($name)
            || isset($seen[$name])
            || str_contains($name, '\\')
            || str_starts_with($name, '/')
            || preg_match('~(^|/)\.\.(/|$)~', $name)
            || !array_key_exists($name, $expected)
        ) {
            $zip->close();
            return new WP_Error('atlas_archive_scope', 'The fixed upgrade artifact has an unauthorized path or wrapper.', ['status' => 422]);
        }
        $contents = $zip->getFromIndex($index);
        if (!is_string($contents) || !hash_equals($expected[$name], hash('sha256', $contents))) {
            $zip->close();
            return new WP_Error('atlas_archive_file_mismatch', 'A fixed upgrade artifact file differs.', ['status' => 422]);
        }
        $seen[$name] = true;
    }
    $zip->close();
    if (array_keys($seen) !== array_keys($expected)) {
        return new WP_Error('atlas_archive_incomplete', 'The fixed upgrade artifact file set differs.', ['status' => 422]);
    }
    return true;
}

function atlas_upgrade_bootstrap_apply(WP_REST_Request $request)
{
    $before = atlas_upgrade_bootstrap_plugin_data();
    if (
        $before['installed'] !== true
        || $before['active'] !== true
        || !hash_equals(ATLAS_UPGRADE_BOOTSTRAP_CURRENT_VERSION, (string) $before['version'])
    ) {
        return new WP_Error('atlas_current_state_mismatch', 'Metadata Bridge must be active at exactly version 0.57.4.', ['status' => 409]);
    }
    $files = $request->get_file_params();
    if (array_keys($files) !== ['artifact'] || !is_array($files['artifact'])) {
        return new WP_Error('atlas_upload_shape', 'Exactly one fixed artifact upload is required.', ['status' => 422]);
    }
    $upload = $files['artifact'];
    if (
        ($upload['name'] ?? '') !== ATLAS_UPGRADE_BOOTSTRAP_TARGET_ZIP
        || (int) ($upload['error'] ?? UPLOAD_ERR_NO_FILE) !== UPLOAD_ERR_OK
        || !is_uploaded_file((string) ($upload['tmp_name'] ?? ''))
    ) {
        return new WP_Error('atlas_upload_identity', 'The fixed artifact upload identity is invalid.', ['status' => 422]);
    }
    $archive = (string) $upload['tmp_name'];
    $valid = atlas_upgrade_bootstrap_validate_archive($archive);
    if (is_wp_error($valid)) {
        return $valid;
    }

    require_once ABSPATH . 'wp-admin/includes/file.php';
    require_once ABSPATH . 'wp-admin/includes/class-wp-upgrader.php';
    if (!WP_Filesystem() || !isset($GLOBALS['wp_filesystem']) || $GLOBALS['wp_filesystem']->method !== 'direct') {
        return new WP_Error('atlas_filesystem_unavailable', 'Direct WordPress filesystem access is required.', ['status' => 503]);
    }
    $skin = new Automatic_Upgrader_Skin();
    $upgrader = new Plugin_Upgrader($skin);
    $result = $upgrader->install($archive, ['overwrite_package' => true]);
    if (is_wp_error($result) || $result !== true) {
        return new WP_Error('atlas_upgrade_failed', 'The fixed Metadata Bridge replacement failed.', ['status' => 500]);
    }
    wp_clean_plugins_cache(true);
    $after = atlas_upgrade_bootstrap_plugin_data();
    if (
        $after['installed'] !== true
        || $after['active'] !== true
        || !hash_equals(ATLAS_UPGRADE_BOOTSTRAP_TARGET_VERSION, (string) $after['version'])
        || !hash_equals(ATLAS_UPGRADE_BOOTSTRAP_TARGET_ENTRY_SHA256, (string) $after['checksum'])
    ) {
        return new WP_Error('atlas_upgrade_verification_failed', 'The fixed Metadata Bridge replacement could not be verified.', ['status' => 500]);
    }
    return rest_ensure_response([
        'operation' => 'upgrade_metadata_bridge_0.57.4_to_0.57.5',
        'accepted' => true,
        'plugin' => ATLAS_UPGRADE_BOOTSTRAP_TARGET_PLUGIN,
        'previous_version' => ATLAS_UPGRADE_BOOTSTRAP_CURRENT_VERSION,
        'target_version' => ATLAS_UPGRADE_BOOTSTRAP_TARGET_VERSION,
        'active' => true,
        'entry_sha256' => ATLAS_UPGRADE_BOOTSTRAP_TARGET_ENTRY_SHA256,
        'bootstrap_reusable' => false,
    ]);
}

add_action('rest_api_init', static function (): void {
    register_rest_route(ATLAS_UPGRADE_BOOTSTRAP_ROUTE_NAMESPACE, ATLAS_UPGRADE_BOOTSTRAP_STATUS_ROUTE, [
        'methods' => WP_REST_Server::READABLE,
        'permission_callback' => 'atlas_upgrade_bootstrap_permission',
        'callback' => 'atlas_upgrade_bootstrap_status',
    ]);
    register_rest_route(ATLAS_UPGRADE_BOOTSTRAP_ROUTE_NAMESPACE, ATLAS_UPGRADE_BOOTSTRAP_ROUTE, [
        'methods' => WP_REST_Server::CREATABLE,
        'permission_callback' => 'atlas_upgrade_bootstrap_permission',
        'callback' => 'atlas_upgrade_bootstrap_apply',
    ]);
});
