<?php
global $wpdb;
$last_id = static fn() => (int) $wpdb->get_var("SELECT COALESCE(MAX(ID),0) FROM {$wpdb->posts}");
while ($last_id() < 7) wp_insert_post(['post_title'=>'Filler','post_status'=>'draft','post_type'=>'post']);
$page_id = wp_insert_post(['post_title'=>'Drywood Termite Tenting in Orlando, FL','post_name'=>'drywood-termite-tenting-orlando-fl','post_status'=>'publish','post_type'=>'page','post_excerpt'=>'Original local excerpt','post_content'=>'<h1>Original Orlando H1</h1><p>Original visible local body content.</p>']);
if ($page_id !== 8) throw new RuntimeException('Expected page ID 8, got '.$page_id);
while ($last_id() < 30) wp_insert_post(['post_title'=>'Filler','post_status'=>'draft','post_type'=>'post']);
foreach ([31=>'orlando-drywood-termite-tenting-hero.png',32=>'orlando-drywood-termite-tenting-hero-1.png'] as $expected=>$name) {
    $id=wp_insert_attachment(['post_title'=>$name,'post_status'=>'inherit','post_type'=>'attachment','post_mime_type'=>'image/png','guid'=>'https://www.drywoodtenting.com/wp-content/uploads/2026/07/'.$name],false,0,true);
    if ($id !== $expected) throw new RuntimeException("Expected media $expected, got $id");
    update_post_meta($id,'_wp_attached_file','2026/07/'.$name);
}
set_post_thumbnail(8,31); update_option('permalink_structure','/%postname%/'); flush_rewrite_rules(false); echo "FIXTURES_OK\n";
