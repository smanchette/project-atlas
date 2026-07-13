<?php
$phase = getenv('ATLAS_PHASE') ?: 'inspect';
$password = getenv('ATLAS_APP_PASSWORD');
if (!$password) throw new RuntimeException('ATLAS_APP_PASSWORD is required for the disposable integration test.');
$auth = 'Basic ' . base64_encode('atlas-admin:' . $password);
$request = static function (string $method, string $path, ?array $body = null) use ($auth): array {
    $args = ['method'=>$method, 'headers'=>['Authorization'=>$auth, 'Content-Type'=>'application/json'], 'timeout'=>15];
    if ($body !== null) $args['body'] = wp_json_encode($body, JSON_UNESCAPED_SLASHES);
    $response = wp_remote_request('http://wordpress/wp-json/project-atlas/v1'.$path, $args);
    if (is_wp_error($response)) throw new RuntimeException($response->get_error_message());
    $decoded = json_decode(wp_remote_retrieve_body($response), true);
    return ['endpoint'=>$path, 'status'=>wp_remote_retrieve_response_code($response), 'body'=>$decoded];
};
$hash = static fn(array $value): string => hash('sha256', wp_json_encode(atlas_metadata_canonicalize($value), JSON_UNESCAPED_SLASHES));

if ($phase === 'scope') {
    $payload = atlas_metadata_approved_payload();
    $valid = $request('POST','/pages/8/metadata/validate',['payload'=>$payload]);
    $payload['json_ld']['@graph'][1]['telephone'] = 'changed';
    $mutation = $request('POST','/pages/8/metadata/validate',['payload'=>$payload]);
    $payload = atlas_metadata_approved_payload(); $payload['twitter']['twitter:image'] = 'https://example.test/media-32.png';
    $media = $request('POST','/pages/8/metadata/validate',['payload'=>$payload]);
    echo wp_json_encode(['valid'=>$valid,'mutation'=>$mutation,'media32'=>$media], JSON_PRETTY_PRINT|JSON_UNESCAPED_SLASHES)."\n"; return;
}
if ($phase === 'apply') {
    $payload=atlas_metadata_approved_payload(); $snapshot=atlas_metadata_snapshot();
    $body=['payload'=>$payload,'payload_hash'=>atlas_metadata_hash($payload),'expected_revision'=>$snapshot['revision'],
        'expected_snapshot_hash'=>$hash($snapshot),'activation_generation'=>$snapshot['activation_generation'],'plugin_checksum'=>atlas_metadata_plugin_checksum()];
    echo wp_json_encode($request('PUT','/pages/8/metadata',$body), JSON_PRETTY_PRINT|JSON_UNESCAPED_SLASHES)."\n"; return;
}
if ($phase === 'guards') {
    $make_body = static function() use ($hash): array { $p=atlas_metadata_approved_payload();$s=atlas_metadata_snapshot();return ['payload'=>$p,'payload_hash'=>atlas_metadata_hash($p),'expected_revision'=>$s['revision'],'expected_snapshot_hash'=>$hash($s),'activation_generation'=>$s['activation_generation'],'plugin_checksum'=>atlas_metadata_plugin_checksum()]; };
    $original=get_post(8); $results=[];
    wp_update_post(['ID'=>8,'post_name'=>'wrong-slug']); $results['slug']=$request('PUT','/pages/8/metadata',$make_body()); wp_update_post(['ID'=>8,'post_name'=>$original->post_name]);
    wp_update_post(['ID'=>8,'post_status'=>'draft']); $results['status']=$request('PUT','/pages/8/metadata',$make_body()); wp_update_post(['ID'=>8,'post_status'=>$original->post_status]);
    set_post_thumbnail(8,32); $results['featured_media']=$request('PUT','/pages/8/metadata',$make_body()); set_post_thumbnail(8,31);
    $results['post9']=$request('PUT','/pages/9/metadata',$make_body());
    echo wp_json_encode($results,JSON_PRETTY_PRINT|JSON_UNESCAPED_SLASHES)."\n"; return;
}
if ($phase === 'rollback') {
    $current=atlas_metadata_snapshot();
    $restore=['rendering_enabled'=>false,'enabled_metadata_state'=>false,'activation_generation'=>$current['activation_generation'],
        'plugin_checksum'=>atlas_metadata_plugin_checksum(),'payload_hash'=>'','revision'=>'0','payload'=>null];
    $body=['current_payload_hash'=>$current['payload_hash'],'snapshot'=>$restore,'expected_revision'=>$current['revision'],
        'activation_generation'=>$current['activation_generation'],'expected_current_snapshot_hash'=>$hash($current),'rollback_payload_hash'=>$hash($restore)];
    echo wp_json_encode($request('PUT','/pages/8/metadata/rollback',$body), JSON_PRETTY_PRINT|JSON_UNESCAPED_SLASHES)."\n"; return;
}
echo wp_json_encode(['snapshot'=>atlas_metadata_snapshot(),'payload'=>atlas_metadata_approved_payload()], JSON_PRETTY_PRINT|JSON_UNESCAPED_SLASHES)."\n";
