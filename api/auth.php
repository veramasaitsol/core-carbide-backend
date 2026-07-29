<?php
// api/auth.php  — POST /login

$data        = json_decode(file_get_contents('php://input'), true) ?? [];
$employee_id = $data['employee_id'] ?? $data['username'] ?? '';
$password    = $data['password'] ?? '';

if (!$employee_id || !$password) {
    json_response(['message' => 'employee_id and password are required'], 400);
}

$db   = get_db();
$stmt = $db->prepare('SELECT * FROM users WHERE employee_id = ?');
$stmt->bind_param('s', $employee_id);
$stmt->execute();
$user = $stmt->get_result()->fetch_assoc();
$stmt->close();

if (!$user) json_response(['message' => 'Invalid credentials'], 401);

$stored_hash = $user['password_hash'] ?? $user['password'] ?? '';
if (!$stored_hash) json_response(['message' => 'Server password config error'], 500);

if (!verify_password($password, $stored_hash)) {
    json_response(['message' => 'Invalid credentials'], 401);
}

$payload = ['sub' => (string)$user['employee_id'], 'exp' => time() + 8 * 3600];
$token   = jwt_encode($payload);

$stmt2 = $db->prepare('SELECT machine_id FROM user_machines WHERE user_id = ?');
$stmt2->bind_param('i', $user['id']);
$stmt2->execute();
$res         = $stmt2->get_result();
$machine_ids = [];
while ($r = $res->fetch_assoc()) $machine_ids[] = $r['machine_id'];
$stmt2->close();

$created_at = $user['created_at'] ?? null;

json_response([
    'token' => $token,
    'user'  => [
        'id'          => $user['id'],
        'employee_id' => $user['employee_id'],
        'name'        => $user['name'],
        'plant'       => $user['plant'],
        'role'        => $user['role'],
        'status'      => $user['status'],
        'created_at'  => $created_at,
        'machine_ids' => $machine_ids,
    ],
]);
