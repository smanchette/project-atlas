<?php
$html = wp_remote_retrieve_body(wp_remote_get('http://wordpress/drywood-termite-tenting-orlando-fl/?local_verify=1', ['headers'=>['Cache-Control'=>'no-cache']]));
$dom = new DOMDocument(); libxml_use_internal_errors(true); $dom->loadHTML($html); $xpath = new DOMXPath($dom);
$payload = atlas_metadata_approved_payload();
$count_meta = static function(string $attribute, string $key, string $value) use ($xpath): int {
    $nodes=$xpath->query('//meta[@'.$attribute.'="'.$key.'" and @content="'.$value.'"]'); return $nodes ? $nodes->length : 0;
};
$checks = [
    'title_count'=>$xpath->query('//title')->length,
    'canonical_count'=>$xpath->query('//link[@rel="canonical"]')->length,
    'description_count'=>$count_meta('name','description',$payload['meta_description']),
    'h1_count'=>$xpath->query('//h1[normalize-space()="Original Orlando H1"]')->length,
    'body_content'=>str_contains($html,'Original visible local body content.'),
    'media31_count'=>substr_count($html,'orlando-drywood-termite-tenting-hero.png'),
    'media32_count'=>substr_count($html,'orlando-drywood-termite-tenting-hero-1.png'),
];
foreach ($payload['open_graph'] as $key=>$value) $checks[$key]=$count_meta('property',$key,$value);
foreach ($payload['twitter'] as $key=>$value) $checks[$key]=$count_meta('name',$key,$value);
$scripts=$xpath->query('//script[@type="application/ld+json" and @data-project-atlas="metadata"]');
$checks['atlas_json_ld_count']=$scripts->length;
$checks['json_ld_exact']=$scripts->length===1 && json_decode($scripts->item(0)->textContent,true)===$payload['json_ld'];
$checks['post']=['slug'=>get_post(8)->post_name,'status'=>get_post(8)->post_status,'excerpt'=>get_post(8)->post_excerpt,'featured_media'=>(int)get_post_thumbnail_id(8)];
echo wp_json_encode($checks,JSON_PRETTY_PRINT|JSON_UNESCAPED_SLASHES)."\n";
