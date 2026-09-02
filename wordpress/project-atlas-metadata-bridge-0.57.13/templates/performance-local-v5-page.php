<?php
/**
 * Bridge-owned full-document template for the local V5 WordPress rehearsal.
 */

if (!defined('ABSPATH')) { exit; }

$atlas_v5_payload = atlas_performance_local_v5_current_payload();
if (!is_array($atlas_v5_payload)) { return; }
remove_action('wp_head', '_wp_render_title_tag', 1);
?><!doctype html>
<html <?php language_attributes(); ?>>
<head>
    <meta charset="<?php bloginfo('charset'); ?>">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title><?php echo esc_html($atlas_v5_payload['page']['meta_title']); ?></title>
    <?php wp_head(); ?>
</head>
<body <?php body_class('project-atlas-v5-template'); ?>>
<?php wp_body_open(); ?>
<?php atlas_performance_local_v5_render_page($atlas_v5_payload); ?>
<?php wp_footer(); ?>
</body>
</html>
