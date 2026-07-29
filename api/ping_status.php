<?php
// api/ping_status.php  — GET /api/machines/ping-status

$db   = get_db();
$rows = $db->query('SELECT vfj_no, oem_name, ip_address FROM machines ORDER BY id')->fetch_all(MYSQLI_ASSOC);

function ping_host(string $ip): bool {
    if (!$ip) return false;
    $is_win = strtolower(PHP_OS_FAMILY) === 'windows';
    $cmd    = $is_win ? "ping -n 1 -w 1000 " . escapeshellarg($ip) : "ping -c 1 -W 1 " . escapeshellarg($ip);
    exec($cmd . ' 2>&1', $out, $code);
    return $code === 0;
}

$results = [];
foreach ($rows as $r) {
    $results[] = [
        'vfj_no'       => $r['vfj_no'],
        'machine_name' => $r['oem_name'],
        'ip_address'   => $r['ip_address'],
        'ip_status'    => ($r['ip_address'] && ping_host($r['ip_address'])) ? 'active' : 'inactive',
    ];
}

json_response(['success' => true, 'count' => count($results), 'machines' => $results]);
