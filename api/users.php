<?php
// api/users.php

include_once __DIR__ . '/../config/helpers.php';
include_once __DIR__ . '/../config/db.php';
require_once __DIR__ . '/../index.php';

$current_user = require_auth();
$db           = get_db();
$path         = $GLOBALS['route_path'];
$params       = $GLOBALS['url_params'];
$method       = $_SERVER['REQUEST_METHOD'];

// Helper: admin check
function is_admin(mysqli $db, string $employee_id): bool {
    $s = $db->prepare('SELECT role FROM users WHERE employee_id = ?');
    $s->bind_param('s', $employee_id);
    $s->execute();
    $r = $s->get_result()->fetch_assoc();
    $s->close();
    return $r && $r['role'] === 'admin';
}

// POST /create_user
if ($method === 'POST' && str_ends_with($path, '/create_user')) {
    if (!is_admin($db, $current_user)) json_response(['message' => 'Admin access required'], 403);
    $data     = json_decode(file_get_contents('php://input'), true) ?? [];
    $required = ['plant', 'role', 'name', 'employee_id'];
    $missing  = array_filter($required, fn($k) => empty($data[$k]));
    if ($missing) json_response(['error' => 'Missing required field(s): ' . implode(', ', $missing)], 400);

    $s = $db->prepare('SELECT id FROM users WHERE employee_id = ?');
    $s->bind_param('s', $data['employee_id']); $s->execute();
    if ($s->get_result()->fetch_assoc()) json_response(['message' => 'Employee ID already exists'], 400);
    $s->close();

    $hash   = hash_password($data['password'] ?? 'Password@123');
    $status = $data['status'] ?? null;
    $s = $db->prepare('INSERT INTO users (plant, employee_id, name, password_hash, role, status) VALUES (?,?,?,?,?,?)');
    $s->bind_param('ssssss', $data['plant'], $data['employee_id'], $data['name'], $hash, $data['role'], $status);
    $s->execute();
    $user_id     = $db->insert_id;
    $machine_ids = array_map('intval', $data['machine_ids'] ?? []);
    if ($machine_ids) {
        $s2 = $db->prepare('INSERT INTO user_machines (user_id, machine_id) VALUES (?,?)');
        foreach ($machine_ids as $mid) { $s2->bind_param('ii', $user_id, $mid); $s2->execute(); }
        $s2->close();
    }
    $s->close();
    json_response(['message' => 'User created', 'user_id' => $user_id, 'mapped_machine_count' => count($machine_ids)], 201);
}

// POST /users/me/reset_password
if ($method === 'POST' && str_contains($path, '/me/reset_password')) {
    $data    = json_decode(file_get_contents('php://input'), true) ?? [];
    $old_pwd = trim($data['old_password'] ?? '');
    $new_pwd = trim($data['new_password'] ?? '');
    $confirm = trim($data['confirm_new_password'] ?? '');
    if (!$old_pwd || !$new_pwd || !$confirm) json_response(['error' => 'old_password, new_password, confirm_new_password are required'], 400);
    if ($new_pwd !== $confirm) json_response(['error' => 'New password and confirmation do not match'], 400);
    if ($new_pwd === $old_pwd)  json_response(['error' => 'New password must be different from old password'], 400);
    if (strlen($new_pwd) < 8)   json_response(['error' => 'New password must be at least 8 characters'], 400);

    $s = $db->prepare('SELECT id, password_hash FROM users WHERE employee_id = ?');
    $s->bind_param('s', $current_user); $s->execute();
    $user = $s->get_result()->fetch_assoc(); $s->close();
    if (!$user) json_response(['error' => 'User not found'], 404);
    if (!verify_password($old_pwd, $user['password_hash'])) json_response(['error' => 'Old password is incorrect'], 401);

    $new_hash = hash_password($new_pwd);
    $s = $db->prepare('UPDATE users SET password_hash = ? WHERE id = ?');
    $s->bind_param('si', $new_hash, $user['id']); $s->execute(); $s->close();
    json_response(['message' => 'Password updated successfully. Please sign in again.']);
}

// GET /users
if ($method === 'GET' && $path === '/users') {
    if (!is_admin($db, $current_user)) json_response(['message' => 'Admin access required'], 403);
    $res   = $db->query('SELECT id, plant, employee_id, name, role, status, created_at FROM users ORDER BY id DESC');
    $users = $res->fetch_all(MYSQLI_ASSOC);

    if ($users) {
        $ids  = implode(',', array_column($users, 'id'));
        $rows = $db->query("SELECT um.user_id, um.machine_id, m.control_type FROM user_machines um JOIN machines m ON um.machine_id = m.id WHERE um.user_id IN ($ids)")->fetch_all(MYSQLI_ASSOC);
        $map  = [];
        foreach ($rows as $r) $map[$r['user_id']][] = ['machine_id' => $r['machine_id'], 'control_type' => $r['control_type']];
        foreach ($users as &$u) {
            $u['machines']    = $map[$u['id']] ?? [];
            $u['machine_ids'] = array_column($u['machines'], 'machine_id');
        }
    }
    json_response(['users' => $users]);
}

// GET /users/{id}
if ($method === 'GET' && isset($params[0])) {
    if (!is_admin($db, $current_user)) json_response(['message' => 'Admin access required'], 403);
    $uid = (int)$params[0];
    $s   = $db->prepare('SELECT id, plant, employee_id, name, role, status, created_at FROM users WHERE id = ?');
    $s->bind_param('i', $uid); $s->execute();
    $user = $s->get_result()->fetch_assoc(); $s->close();
    if (!$user) json_response(['message' => 'User not found'], 404);
    $s2 = $db->prepare('SELECT machine_id FROM user_machines WHERE user_id = ?');
    $s2->bind_param('i', $uid); $s2->execute();
    $user['machine_ids'] = array_column($s2->get_result()->fetch_all(MYSQLI_ASSOC), 'machine_id');
    $s2->close();
    json_response($user);
}

// PATCH /users/{id}
if ($method === 'PATCH' && isset($params[0])) {
    if (!is_admin($db, $current_user)) json_response(['message' => 'Admin access required'], 403);
    $uid  = (int)$params[0];
    $data = json_decode(file_get_contents('php://input'), true) ?? [];

    $s = $db->prepare('SELECT id, employee_id FROM users WHERE id = ?');
    $s->bind_param('i', $uid); $s->execute();
    $existing = $s->get_result()->fetch_assoc(); $s->close();
    if (!$existing) json_response(['message' => 'User not found'], 404);

    if (isset($data['employee_id']) && $data['employee_id'] !== $existing['employee_id']) {
        $s = $db->prepare('SELECT id FROM users WHERE employee_id = ?');
        $s->bind_param('s', $data['employee_id']); $s->execute();
        if ($s->get_result()->fetch_assoc()) json_response(['error' => 'Employee ID already exists'], 400);
        $s->close();
    }

    if (isset($data['password'])) $data['password_hash'] = hash_password($data['password']);

    $allowed = ['plant', 'name', 'employee_id', 'role', 'status', 'password_hash'];
    $sets = []; $vals = []; $types = '';
    foreach ($allowed as $k) {
        if (array_key_exists($k, $data)) { $sets[] = "$k = ?"; $vals[] = $data[$k]; $types .= 's'; }
    }
    if ($sets) {
        $vals[] = $uid; $types .= 'i';
        $s = $db->prepare('UPDATE users SET ' . implode(', ', $sets) . ' WHERE id = ?');
        $s->bind_param($types, ...$vals); $s->execute(); $s->close();
    }

    if (isset($data['machine_ids'])) {
        $machine_ids = array_map('intval', $data['machine_ids'] ?? []);
        $s = $db->prepare('DELETE FROM user_machines WHERE user_id = ?');
        $s->bind_param('i', $uid); $s->execute(); $s->close();
        if ($machine_ids) {
            $s2 = $db->prepare('INSERT INTO user_machines (user_id, machine_id) VALUES (?,?)');
            foreach ($machine_ids as $mid) { $s2->bind_param('ii', $uid, $mid); $s2->execute(); }
            $s2->close();
        }
    }
    json_response(['message' => 'User updated successfully']);
}

// DELETE /users/{id}
if ($method === 'DELETE' && isset($params[0])) {
    if (!is_admin($db, $current_user)) json_response(['message' => 'Admin access required'], 403);
    $uid = (int)$params[0];
    $s   = $db->prepare('SELECT id FROM users WHERE id = ?');
    $s->bind_param('i', $uid); $s->execute();
    if (!$s->get_result()->fetch_assoc()) json_response(['message' => 'User not found'], 404);
    $s->close();
    $s = $db->prepare('DELETE FROM users WHERE id = ?');
    $s->bind_param('i', $uid); $s->execute(); $s->close();
    json_response(['message' => 'User deleted successfully']);
}

json_response(['error' => 'Not found'], 404);
