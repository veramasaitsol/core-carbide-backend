<?php
// api/machines.php

$current_user = require_auth();
$db           = get_db();
$path         = $GLOBALS['route_path'];
$params       = $GLOBALS['url_params'];
$method       = $_SERVER['REQUEST_METHOD'];

function machines_admin_check(mysqli $db, string $emp): void {
    $s = $db->prepare('SELECT role FROM users WHERE employee_id = ?');
    $s->bind_param('s', $emp); $s->execute();
    $r = $s->get_result()->fetch_assoc(); $s->close();
    if (!$r || $r['role'] !== 'admin') json_response(['message' => 'Admin access required'], 403);
}

// POST /add_machine
if ($method === 'POST' && str_ends_with($path, '/add_machine')) {
    machines_admin_check($db, $current_user);
    $data     = json_decode(file_get_contents('php://input'), true) ?? [];
    $required = ['oem_name', 'ip_address', 'operator_ip', 'vfj_no', 'control_type', 'control_model'];
    $missing  = array_filter($required, fn($k) => empty($data[$k]));
    if ($missing) json_response(['error' => 'Missing required field(s): ' . implode(', ', $missing)], 400);

    $s = $db->prepare('INSERT INTO machines (oem_name, ip_address, operator_ip, port, vfj_no, control_type, control_details, control_model, status) VALUES (?,?,?,?,?,?,?,?,?)');
    $port   = $data['port'] ?? null;
    $status = $data['status'] ?? 'active';
    $s->bind_param('sssssssss', $data['oem_name'], $data['ip_address'], $data['operator_ip'], $port, $data['vfj_no'], $data['control_type'], $data['control_details'], $data['control_model'], $status);
    $s->execute();
    $machine_id = $db->insert_id; $s->close();

    $offline = 'OFFLINE';
    $s2 = $db->prepare('INSERT INTO machine_data (machine_id, machine_state) VALUES (?,?)');
    $s2->bind_param('is', $machine_id, $offline); $s2->execute(); $s2->close();

    json_response(['message' => 'Machine added successfully', 'machine_id' => $machine_id], 201);
}

// GET /machines
if ($method === 'GET' && $path === '/machines') {
    machines_admin_check($db, $current_user);
    $res      = $db->query("SELECT id, oem_name, ip_address, operator_ip, port, vfj_no, control_type, control_details, control_model, status, created_at, updated_at FROM machines WHERE status = 'active' ORDER BY id DESC");
    $machines = $res->fetch_all(MYSQLI_ASSOC);
    json_response(['machines' => $machines]);
}

// GET /machines/{id}
if ($method === 'GET' && isset($params[0]) && !str_contains($path, '/restore') && !str_contains($path, '/status')) {
    machines_admin_check($db, $current_user);
    $mid = (int)$params[0];
    $s   = $db->prepare("SELECT id, oem_name, ip_address, operator_ip, port, vfj_no, control_type, control_details, control_model, status, created_at, updated_at FROM machines WHERE id = ? AND status = 'active'");
    $s->bind_param('i', $mid); $s->execute();
    $machine = $s->get_result()->fetch_assoc(); $s->close();
    if (!$machine) json_response(['message' => 'Machine not found'], 404);
    json_response($machine);
}

// PATCH /machines/{id}
if ($method === 'PATCH' && isset($params[0])) {
    machines_admin_check($db, $current_user);
    $mid     = (int)$params[0];
    $data    = json_decode(file_get_contents('php://input'), true) ?? [];
    $allowed = ['oem_name', 'ip_address', 'operator_ip', 'port', 'vfj_no', 'control_type', 'control_details', 'control_model', 'status'];
    $sets = []; $vals = []; $types = '';
    foreach ($allowed as $k) {
        if (array_key_exists($k, $data)) { $sets[] = "$k = ?"; $vals[] = $data[$k]; $types .= 's'; }
    }
    if (!$sets) json_response(['error' => 'No valid fields provided to update'], 400);
    $s = $db->prepare('SELECT id FROM machines WHERE id = ?');
    $s->bind_param('i', $mid); $s->execute();
    if (!$s->get_result()->fetch_assoc()) json_response(['message' => 'Machine not found'], 404);
    $s->close();
    $vals[] = $mid; $types .= 'i';
    $s = $db->prepare('UPDATE machines SET ' . implode(', ', $sets) . ' WHERE id = ?');
    $s->bind_param($types, ...$vals); $s->execute(); $s->close();
    json_response(['message' => 'Machine updated successfully']);
}

// DELETE /machines/{id}  — soft delete
if ($method === 'DELETE' && isset($params[0])) {
    machines_admin_check($db, $current_user);
    $mid = (int)$params[0];
    $s   = $db->prepare('SELECT status FROM machines WHERE id = ?');
    $s->bind_param('i', $mid); $s->execute();
    $row = $s->get_result()->fetch_assoc(); $s->close();
    if (!$row) json_response(['message' => 'Machine not found'], 404);
    if (strtolower($row['status']) === 'inactive') json_response(['message' => 'Machine already inactive']);
    $s = $db->prepare("UPDATE machines SET status = 'inactive' WHERE id = ?");
    $s->bind_param('i', $mid); $s->execute(); $s->close();
    json_response(['message' => 'Machine deactivated (soft deleted) successfully']);
}

// POST /machines/{id}/restore
if ($method === 'POST' && str_contains($path, '/restore') && isset($params[0])) {
    machines_admin_check($db, $current_user);
    $mid = (int)$params[0];
    $s   = $db->prepare('SELECT status FROM machines WHERE id = ?');
    $s->bind_param('i', $mid); $s->execute();
    $row = $s->get_result()->fetch_assoc(); $s->close();
    if (!$row) json_response(['message' => 'Machine not found'], 404);
    if (strtolower($row['status']) === 'active') json_response(['message' => 'Machine already active']);
    $s = $db->prepare("UPDATE machines SET status = 'active' WHERE id = ?");
    $s->bind_param('i', $mid); $s->execute(); $s->close();
    json_response(['message' => 'Machine restored successfully']);
}

// PUT /machines/{id}/status
if ($method === 'PUT' && str_contains($path, '/status') && isset($params[0])) {
    $mid    = (int)$params[0];
    $data   = json_decode(file_get_contents('php://input'), true) ?? [];
    $status = $data['status'] ?? '';
    if (!$status) json_response(['message' => 'Missing status field'], 400);
    $s = $db->prepare('UPDATE machines SET status = ? WHERE id = ?');
    $s->bind_param('si', $status, $mid); $s->execute(); $s->close();
    json_response(['message' => 'Status updated', 'machine_id' => $mid, 'new_status' => $status]);
}

json_response(['error' => 'Not found'], 404);
