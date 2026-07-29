<?php
// api/health.php  — GET /health

include_once __DIR__ . '/../config/db.php';

$db_status = 'disconnected';
$error     = null;
try {
    $db = get_db();
    $db->query('SELECT 1');
    $db_status = 'connected';
} catch (Throwable $e) {
    $error = $e->getMessage();
}

$code = $db_status === 'connected' ? 200 : 500;
http_response_code($code);
echo json_encode([
    'status'    => $db_status === 'connected' ? 'healthy' : 'unhealthy',
    'timestamp' => date('c'),
    'service'   => 'machine_monitoring_api',
    'database'  => $db_status,
    ...($error ? ['error' => $error] : []),
], JSON_UNESCAPED_UNICODE);
exit;
