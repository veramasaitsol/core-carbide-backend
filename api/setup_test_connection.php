<?php
header('Content-Type: application/json');
require_once __DIR__ . '/../config/db.php';

$input = json_decode(file_get_contents('php://input'), true);
$ip = trim($input['ip'] ?? ($_GET['ip'] ?? ''));

if ($ip === '') {
    echo json_encode(['success' => false, 'error' => 'No IP provided']);
    exit;
}

$exePath = 'C:\\MachineWin\\Collector\\CoreCarbideTools.exe';

if (!file_exists($exePath)) {
    echo json_encode(['success' => false, 'error' => 'Collector EXE not found at: ' . $exePath]);
    exit;
}

$cmd = '"' . $exePath . '" --test ' . escapeshellarg($ip) . ' 2>&1';
$output = shell_exec($cmd);

if ($output === null) {
    echo json_encode(['success' => false, 'error' => 'shell_exec failed or is disabled in php.ini']);
    exit;
}

$resultLine = null;
foreach (explode("\n", $output) as $line) {
    $line = trim($line);
    if (strpos($line, 'RESULT_JSON:') === 0) {
        $resultLine = substr($line, strlen('RESULT_JSON:'));
        break;
    }
}

if ($resultLine === null) {
    echo json_encode(['success' => false, 'error' => 'No result from collector', 'raw' => $output]);
    exit;
}

echo $resultLine;