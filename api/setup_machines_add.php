<?php
header('Content-Type: application/json');
require_once __DIR__ . '/../config/db.php';

try {
    $db = get_db();
    $input = json_decode(file_get_contents('php://input'), true);

    $name    = trim($input['name'] ?? '');
    $company = trim($input['company'] ?? '');
    $model   = trim($input['model'] ?? '');
    $ip      = trim($input['ip'] ?? '');
    $hash    = trim($input['hash'] ?? '');
    $type    = trim($input['machine_type'] ?? 'mill');

    if ($name === '' || $company === '' || $model === '' || $ip === '' || $hash === '') {
        echo json_encode(['success' => false, 'error' => 'Missing required fields']);
        exit;
    }

    $controlType = strtoupper($company);

    // The `machines` table also has NOT NULL columns (ip_address, operator_ip,
    // vfj_no, control_model) that this simplified setup-wizard flow doesn't
    // collect directly. Fill them with sensible values derived from what we
    // do have, so the insert doesn't fail on a constraint violation. These
    // can be edited later via machines.php's PATCH /machines/{id}.
    $ipAddress    = $ip;
    $operatorIp   = $ip;
    $vfjNo        = '';
    $controlModel = $model;
    $status       = 'active';

    $stmt = $db->prepare(
        "INSERT INTO machines
            (oem_name, company, model, control_type, cnc_ip, cnc_hash, machine_type,
             ip_address, operator_ip, vfj_no, control_model, status)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    );

    if (!$stmt) {
        echo json_encode(['success' => false, 'error' => 'Prepare failed: ' . $db->error]);
        exit;
    }

    $stmt->bind_param(
        'ssssssssssss',
        $name, $company, $model, $controlType, $ip, $hash, $type,
        $ipAddress, $operatorIp, $vfjNo, $controlModel, $status
    );

    if ($stmt->execute()) {
        echo json_encode(['success' => true, 'machine_id' => $db->insert_id]);
    } else {
        echo json_encode(['success' => false, 'error' => $stmt->error]);
    }
    $stmt->close();

} catch (\Throwable $e) {
    // PHP 8.1+ mysqli throws exceptions on DB errors by default instead of
    // returning false. Without this catch, that exception becomes an
    // uncaught fatal error — PHP prints its raw HTML error page into a
    // response the frontend expects to be JSON, which is exactly the
    // "Unexpected token '<'" error you were seeing. Any DB failure now
    // returns a proper JSON error instead.
    http_response_code(500);
    echo json_encode(['success' => false, 'error' => $e->getMessage()]);
}