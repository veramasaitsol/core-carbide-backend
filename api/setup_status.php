<?php
header('Content-Type: application/json');
require_once __DIR__ . '/../config/db.php';

$db = get_db();
$result = $db->query("SELECT setting_value FROM app_settings WHERE setting_key='setup_complete'");
$row = $result ? $result->fetch_assoc() : null;
echo json_encode(['setup_complete' => ($row && $row['setting_value'] === '1')]);