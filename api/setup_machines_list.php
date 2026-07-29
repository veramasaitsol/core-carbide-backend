<?php
header('Content-Type: application/json');
require_once __DIR__ . '/../config/db.php';

$db = get_db();
$result = $db->query(
    "SELECT id, oem_name, company, model, control_type, cnc_ip, cnc_hash, machine_type, vfj_no
     FROM machines
     WHERE cnc_ip IS NOT NULL AND cnc_ip != ''
     ORDER BY id"
);

if (!$result) {
    echo json_encode(['machines' => []]);
    exit;
}

echo json_encode(['machines' => $result->fetch_all(MYSQLI_ASSOC)]);