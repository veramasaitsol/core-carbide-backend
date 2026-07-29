<?php
header('Content-Type: application/json');
require_once __DIR__ . '/../config/db.php';

$db = get_db();
$input = json_decode(file_get_contents('php://input'), true);
$password = $input['password'] ?? '';

$result = $db->query("SELECT setting_value FROM app_settings WHERE setting_key='technician_password_hash'");
$row = $result ? $result->fetch_assoc() : null;
$hash = $row['setting_value'] ?? '';

if ($hash !== '' && password_verify($password, $hash)) {
    echo json_encode(['valid' => true]);
} else {
    echo json_encode(['valid' => false]);
}