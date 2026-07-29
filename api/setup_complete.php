<?php
header('Content-Type: application/json');
require_once __DIR__ . '/../config/db.php';

$db = get_db();
$db->query("UPDATE app_settings SET setting_value='1' WHERE setting_key='setup_complete'");
echo json_encode(['success' => true]);