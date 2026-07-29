<?php
// api/production.php  — POST /add_production  |  GET /get_production

$current_user = require_auth();
$db           = get_db();
$method       = $_SERVER['REQUEST_METHOD'];

// POST /add_production
if ($method === 'POST') {
    $data     = json_decode(file_get_contents('php://input'), true) ?? [];
    $required = ['machine_id','shift_operator_name','machine_name','shift_production_details'];
    $missing  = array_filter($required, fn($k) => !array_key_exists($k, $data));
    if ($missing) json_response(['error' => 'Missing fields: ' . implode(', ', $missing)], 400);

    $details = $data['shift_production_details'];
    if (is_array($details)) $details = json_encode($details, JSON_UNESCAPED_UNICODE);

    $machine_no             = $data['machine_no']             ?? null;
    $product_component_name = $data['product_component_name'] ?? null;
    $product_component_no   = $data['product_component_no']   ?? null;
    $section_code_name      = $data['section_code_name']      ?? null;
    $machine_status         = $data['machine_status']         ?? null;

    $s = $db->prepare('INSERT INTO machine_production (machine_id, shift_operator_name, machine_name, machine_no, product_component_name, product_component_no, section_code_name, shift_production_details, machine_status, timestamp) VALUES (?,?,?,?,?,?,?,?,?,NOW())');
    $s->bind_param('issssssss',
        $data['machine_id'], $data['shift_operator_name'], $data['machine_name'],
        $machine_no, $product_component_name, $product_component_no,
        $section_code_name, $details, $machine_status
    );
    if (!$s->execute()) json_response(['error' => 'Database error'], 400);
    $new_id = $db->insert_id; $s->close();
    json_response(['message' => 'Production record added successfully', 'id' => $new_id], 201);
}

// GET /get_production
if ($method === 'GET') {
    $start_time = $_GET['start_time'] ?? null;
    $end_time   = $_GET['end_time']   ?? null;
    $limit      = min(max(1, (int)($_GET['limit'] ?? 200)), 10000);
    $machine_id = $_GET['machine_id'] ?? null;
    $latest     = in_array(strtolower($_GET['latest'] ?? '0'), ['1','true','yes']);

    $sql    = 'SELECT machine_id, shift_operator_name, machine_name, machine_no, product_component_name, product_component_no, section_code_name, shift_production_details, machine_status, mpf_path, timestamp FROM machine_production WHERE 1=1';
    $types  = '';
    $values = [];

    if ($start_time && $end_time) { $sql .= ' AND timestamp BETWEEN ? AND ?'; $types .= 'ss'; $values[] = $start_time; $values[] = $end_time; }
    elseif ($start_time)          { $sql .= ' AND timestamp >= ?'; $types .= 's'; $values[] = $start_time; }
    elseif ($end_time)            { $sql .= ' AND timestamp <= ?'; $types .= 's'; $values[] = $end_time; }

    if ($machine_id) { $sql .= ' AND machine_id = ?'; $types .= 's'; $values[] = $machine_id; }

    if ($latest && $machine_id) {
        $sql .= ' ORDER BY timestamp DESC LIMIT 1';
    } else {
        $sql .= ' ORDER BY timestamp DESC LIMIT ?'; $types .= 'i'; $values[] = $limit;
    }

    $s = $db->prepare($sql);
    if ($types) $s->bind_param($types, ...$values);
    $s->execute();
    $rows = $s->get_result()->fetch_all(MYSQLI_ASSOC); $s->close();

    $result = array_map(fn($r) => [
        'machine_id'               => $r['machine_id'],
        'shift_operator_name'      => $r['shift_operator_name'],
        'machine_name'             => $r['machine_name'],
        'machine_no'               => $r['machine_no'],
        'product_component_name'   => $r['product_component_name'],
        'product_component_no'     => $r['product_component_no'],
        'section_code_name'        => $r['section_code_name'],
        'shift_production_details' => $r['shift_production_details'],
        'machine_status'           => $r['machine_status'],
        'mpf_path'                 => $r['mpf_path'],
        'timestamp'                => $r['timestamp'],
    ], $rows);

    json_response($result);
}

json_response(['error' => 'Not found'], 404);
