<?php
declare(strict_types=1);

/**
 * Process-local proof for the 0.57.16 Page 8 governed-public-contact exception.
 * All addresses are reserved synthetic fixtures.
 */

final class WP_Post {}
final class WP_Error {}
final class WP_REST_Request {}
final class WP_REST_Response {}

define('ABSPATH', __DIR__ . '/');
define('ATLAS_METADATA_BRIDGE_VERSION', '0.57.16');

$public_contact = 'public-contact' . '@' . 'example.test';
$private_from = 'private-from' . '@' . 'example.test';
$other_recipient = 'other-recipient' . '@' . 'example.test';
$GLOBALS['atlas_public_contact_privacy_test'] = [
    'checks' => [],
    'config' => [
        'recipient_email' => $public_contact,
        'from_email' => $private_from,
    ],
];

function add_action(string $hook, $callback): bool { return true; }
function get_option(string $name, $default = false) {
    return $GLOBALS['atlas_public_contact_privacy_test']['config'] ?? $default;
}
function wp_json_encode($value, int $flags = 0, int $depth = 512) {
    return json_encode($value, $flags, $depth);
}

require dirname(__DIR__)
    . '/project-atlas-metadata-bridge-0.57.16/includes/performance-local-v5-page-payload.php';

function atlas_public_contact_privacy_check(bool $condition, string $identity): void {
    if (!$condition) { throw new RuntimeException($identity); }
    $GLOBALS['atlas_public_contact_privacy_test']['checks'][] = $identity;
}

$final_body = 'Contact the synthetic service team at ' . $public_contact . '.';
$prior = [
    'website' => ['contact_email' => $public_contact],
    'footer' => ['contact_email' => $public_contact],
    'hero' => ['introduction' => 'Synthetic governed introduction.'],
    'sections' => [
        [
            'key' => 'why_it_matters',
            'heading' => 'Synthetic context',
            'body' => 'Synthetic body without an address.',
        ],
        [
            'key' => 'final_conversion',
            'heading' => 'Request synthetic service',
            'body' => $final_body,
        ],
    ],
];
$candidate = $prior;

atlas_public_contact_privacy_check(
    atlas_performance_local_v5_page_payload_final_conversion_index($prior) === 1,
    'single_final_conversion_index_identified'
);
atlas_public_contact_privacy_check(
    !atlas_performance_local_v5_page_payload_contains_private_delivery_value(
        $candidate,
        $prior
    ),
    'byte_preserved_governed_public_contact_and_final_body_allowed'
);

$contact_paths_only = $candidate;
$contact_paths_only['sections'][1]['body'] = 'Synthetic final body without an address.';
atlas_public_contact_privacy_check(
    !atlas_performance_local_v5_page_payload_contains_private_delivery_value(
        $contact_paths_only,
        $contact_paths_only
    ),
    'byte_preserved_governed_public_contact_paths_remain_allowed'
);

$changed_body = $candidate;
$changed_body['sections'][1]['body'] .= ' Changed candidate.';
atlas_public_contact_privacy_check(
    atlas_performance_local_v5_page_payload_contains_private_delivery_value(
        $changed_body,
        $prior
    ),
    'changed_final_conversion_body_rejected'
);

$changed_section = $candidate;
$changed_section['sections'][1]['heading'] .= ' Changed candidate.';
atlas_public_contact_privacy_check(
    atlas_performance_local_v5_page_payload_contains_private_delivery_value(
        $changed_section,
        $prior
    ),
    'changed_final_conversion_section_rejected'
);

$candidate_only_occurrence_prior = $contact_paths_only;
$candidate_only_occurrence = $candidate_only_occurrence_prior;
$candidate_only_occurrence['sections'][1]['body'] .= ' ' . $public_contact;
atlas_public_contact_privacy_check(
    atlas_performance_local_v5_page_payload_contains_private_delivery_value(
        $candidate_only_occurrence,
        $candidate_only_occurrence_prior
    ),
    'candidate_only_final_conversion_occurrence_rejected'
);

$moved_final = $candidate;
$moved_final['sections'] = array_reverse($moved_final['sections']);
atlas_public_contact_privacy_check(
    atlas_performance_local_v5_page_payload_contains_private_delivery_value(
        $moved_final,
        $prior
    ),
    'moved_final_conversion_body_rejected'
);

$duplicate_final = $candidate;
$duplicate_final['sections'][] = $duplicate_final['sections'][1];
atlas_public_contact_privacy_check(
    atlas_performance_local_v5_page_payload_final_conversion_index($duplicate_final) === null
        && atlas_performance_local_v5_page_payload_contains_private_delivery_value(
            $duplicate_final,
            $prior
        ),
    'duplicate_final_conversion_sections_rejected'
);

$prior_without_final = $prior;
$prior_without_final['sections'] = [$prior_without_final['sections'][0]];
atlas_public_contact_privacy_check(
    atlas_performance_local_v5_page_payload_final_conversion_index($prior_without_final) === null
        && atlas_performance_local_v5_page_payload_contains_private_delivery_value(
            $candidate,
            $prior_without_final
        ),
    'missing_prior_final_conversion_rejected'
);

$candidate_without_final = $candidate;
$candidate_without_final['sections'][0]['body'] = $candidate_without_final['sections'][1]['body'];
array_pop($candidate_without_final['sections']);
atlas_public_contact_privacy_check(
    atlas_performance_local_v5_page_payload_final_conversion_index(
        $candidate_without_final
    ) === null
        && atlas_performance_local_v5_page_payload_contains_private_delivery_value(
            $candidate_without_final,
            $prior
        ),
    'missing_candidate_final_conversion_with_off_path_occurrence_rejected'
);

$recipient_in_heading = $candidate;
$recipient_in_heading['sections'][1]['heading'] .= ' ' . $public_contact;
atlas_public_contact_privacy_check(
    atlas_performance_local_v5_page_payload_contains_private_delivery_value(
        $recipient_in_heading,
        $recipient_in_heading
    ),
    'recipient_in_final_conversion_heading_rejected'
);

$recipient_in_other_section = $candidate;
$recipient_in_other_section['sections'][0]['body'] .= ' ' . $public_contact;
atlas_public_contact_privacy_check(
    atlas_performance_local_v5_page_payload_contains_private_delivery_value(
        $recipient_in_other_section,
        $recipient_in_other_section
    ),
    'recipient_in_other_section_rejected'
);

$recipient_in_hero = $candidate;
$recipient_in_hero['hero']['introduction'] .= ' ' . $public_contact;
atlas_public_contact_privacy_check(
    atlas_performance_local_v5_page_payload_contains_private_delivery_value(
        $recipient_in_hero,
        $recipient_in_hero
    ),
    'recipient_in_hero_rejected'
);

$mismatched_footer = $candidate;
$mismatched_footer['footer']['contact_email'] = $other_recipient;
atlas_public_contact_privacy_check(
    atlas_performance_local_v5_page_payload_contains_private_delivery_value(
        $mismatched_footer,
        $prior
    ),
    'nonmatching_public_contact_paths_rejected'
);

$case_mismatched_contact = $candidate;
$case_mismatched_contact['website']['contact_email'] = strtoupper($public_contact);
$case_mismatched_contact['footer']['contact_email'] = strtoupper($public_contact);
$case_mismatched_contact['sections'][1]['body'] = str_replace(
    $public_contact,
    strtoupper($public_contact),
    $case_mismatched_contact['sections'][1]['body']
);
atlas_public_contact_privacy_check(
    atlas_performance_local_v5_page_payload_contains_private_delivery_value(
        $case_mismatched_contact,
        $case_mismatched_contact
    ),
    'configured_recipient_case_mismatch_rejected'
);

atlas_public_contact_privacy_check(
    atlas_performance_local_v5_page_payload_contains_private_delivery_value(
        $candidate,
        null
    ),
    'missing_valid_prior_rejected'
);

$from_in_preserved_body = $candidate;
$from_in_preserved_body['sections'][1]['body'] .= ' ' . $private_from;
atlas_public_contact_privacy_check(
    atlas_performance_local_v5_page_payload_contains_private_delivery_value(
        $from_in_preserved_body,
        $from_in_preserved_body
    ),
    'from_address_rejected_before_preserved_body_scrub'
);

$GLOBALS['atlas_public_contact_privacy_test']['config'] = [
    'recipient_email' => $other_recipient,
    'from_email' => $public_contact,
];
atlas_public_contact_privacy_check(
    atlas_performance_local_v5_page_payload_contains_private_delivery_value(
        $candidate,
        $prior
    ),
    'from_address_rejected_even_at_public_contact_paths'
);

echo json_encode([
    'status' => 'PASS',
    'version' => ATLAS_METADATA_BRIDGE_VERSION,
    'check_count' => count($GLOBALS['atlas_public_contact_privacy_test']['checks']),
    'private_values_redacted' => true,
], JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR) . "\n";
