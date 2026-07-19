<?php
declare(strict_types=1);

define('ABSPATH', __DIR__ . '/');

final class WP_Error {
    public function __construct(public string $code, public string $message, public array $data = []) {}
    public function get_error_code(): string { return $this->code; }
}
class WP_REST_Request { public function get_json_params(): array { return []; } }

$GLOBALS['atlas_conditions'] = ['page' => true];
$GLOBALS['atlas_meta'] = [];
$GLOBALS['atlas_option'] = [];
$GLOBALS['atlas_write_count'] = 0;
$GLOBALS['atlas_capable'] = true;

function register_activation_hook(...$args): void {}
function add_action(...$args): void {}
function register_rest_route(...$args): void {}
function rest_ensure_response($value) { return $value; }
function current_user_can(...$args): bool { return $GLOBALS['atlas_capable']; }
function wp_generate_uuid4(): string { return '00000000-0000-4000-8000-000000000000'; }
function wp_json_encode($value, int $flags = 0): string { return json_encode($value, $flags | JSON_THROW_ON_ERROR); }
function esc_html(string $value): string { return htmlspecialchars($value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8'); }
function esc_attr(string $value): string { return htmlspecialchars($value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8'); }
function is_wp_error($value): bool { return $value instanceof WP_Error; }
function is_page($id = null): bool { return $GLOBALS['atlas_conditions']['page'] && ($id === null || $id === 8); }
function is_admin(): bool { return $GLOBALS['atlas_conditions']['admin'] ?? false; }
function wp_doing_ajax(): bool { return $GLOBALS['atlas_conditions']['ajax'] ?? false; }
function wp_doing_cron(): bool { return $GLOBALS['atlas_conditions']['cron'] ?? false; }
function is_feed(): bool { return $GLOBALS['atlas_conditions']['feed'] ?? false; }
function is_search(): bool { return $GLOBALS['atlas_conditions']['search'] ?? false; }
function is_archive(): bool { return $GLOBALS['atlas_conditions']['archive'] ?? false; }
function is_preview(): bool { return $GLOBALS['atlas_conditions']['preview'] ?? false; }
function get_post(int $id) { return $id === 8 ? (object) ['post_status' => 'publish', 'post_name' => 'drywood-termite-tenting-orlando-fl'] : null; }
function get_post_meta(int $id, string $key, bool $single = true) { return $GLOBALS['atlas_meta'][$key] ?? ''; }
function get_option(string $key, $default = false) { return $GLOBALS['atlas_option'][$key] ?? $default; }
function get_post_thumbnail_id(int $id): int { return 31; }
function update_option(...$args): bool { $GLOBALS['atlas_write_count']++; return true; }
function update_post_meta(...$args): bool { $GLOBALS['atlas_write_count']++; return true; }
function delete_post_meta(...$args): bool { $GLOBALS['atlas_write_count']++; return true; }

require dirname(__DIR__) . '/project-atlas-metadata-bridge-0.57.7/project-atlas-metadata-bridge.php';

function require_true(bool $condition, string $message): void {
    if (!$condition) { throw new RuntimeException($message); }
}

$payload = atlas_metadata_approved_payload();
$snapshot = [
    'rendering_enabled' => true,
    'enabled_metadata_state' => true,
    'activation_generation' => 'generation',
    'plugin_checksum' => atlas_metadata_plugin_checksum(),
    'payload_hash' => atlas_metadata_hash($payload),
    'revision' => '1',
    'payload' => $payload,
];
$markup = atlas_metadata_head_markup_from_snapshot($snapshot);
require_true($markup !== '', 'pure renderer returned no markup');
require_true(substr_count($markup, '<meta name="description"') === 1, 'description inventory differs');
require_true(substr_count($markup, 'application/ld+json') === 1, 'JSON-LD inventory differs');
$GLOBALS['atlas_meta'] = [
    '_atlas_metadata_payload' => $payload,
    '_atlas_metadata_payload_hash' => atlas_metadata_hash($payload),
    '_atlas_metadata_revision' => '1',
    '_atlas_metadata_enabled' => '1',
];
$GLOBALS['atlas_option'][ATLAS_METADATA_SAFETY_OPTION] = [
    'activation_generation' => 'generation',
    'enabled' => true,
    'authorized_generation' => 'generation',
    'plugin_version' => ATLAS_METADATA_BRIDGE_VERSION,
    'plugin_checksum' => atlas_metadata_plugin_checksum(),
];
require_true(atlas_metadata_head_markup() !== '', 'public page 8 did not render');

foreach (['admin', 'ajax', 'cron', 'feed', 'search', 'archive', 'preview'] as $condition) {
    $GLOBALS['atlas_conditions'][$condition] = true;
    require_true(atlas_metadata_head_markup() === '', "public guard failed for {$condition}");
    $GLOBALS['atlas_conditions'][$condition] = false;
}
$GLOBALS['atlas_conditions']['page'] = false;
require_true(atlas_metadata_head_markup() === '', 'unrelated public page rendered metadata');

define('REST_REQUEST', true);
require_true(atlas_metadata_head_markup() === '', 'REST request entered public-head emission');
$preview = atlas_metadata_rendering_preview();
require_true(is_array($preview), 'REST preview did not return HTTP-200 response data');
require_true($preview['read_only'] === true && $preview['post_id'] === 8, 'REST preview identity differs');
require_true($preview['head_sha256'] === hash('sha256', $markup), 'public and preview renderers differ');

$wrong_revision = $snapshot;
$wrong_revision['revision'] = '2';
require_true(atlas_metadata_head_markup_from_snapshot($wrong_revision) === '', 'wrong revision rendered');
$GLOBALS['atlas_meta']['_atlas_metadata_enabled'] = '';
$disabled = atlas_metadata_rendering_preview();
require_true($disabled instanceof WP_Error && $disabled->get_error_code() === 'atlas_rendering_preview_unavailable', 'disabled preview did not fail closed');
$GLOBALS['atlas_capable'] = false;
require_true(atlas_metadata_permission() === false, 'unauthorized preview permission passed');
require_true($GLOBALS['atlas_write_count'] === 0, 'preview or renderer performed a write');

echo "metadata_bridge_0577_preview_contract_passed\n";
