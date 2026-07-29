<?php
// api/alerts.php  — GET /api/alarms | /api/warnings | /api/alerts

$current_user = require_auth();
$db           = get_db();
$path         = $GLOBALS['route_path'];

$machine_id    = $_GET['machine_id']    ?? null;
$from_date     = $_GET['from_date']     ?? null;
$to_date       = $_GET['to_date']       ?? null;
$from_datetime = $_GET['from_datetime'] ?? null;
$to_datetime   = $_GET['to_datetime']   ?? null;
$export_type   = strtolower($_GET['export'] ?? '');
$limit         = min(max(1, (int)($_GET['limit'] ?? 50)), 500);

$is_alarms   = str_ends_with($path, '/alarms');
$is_warnings = str_ends_with($path, '/warnings');
$is_alerts   = str_ends_with($path, '/alerts');

// Build WHERE
$col_cond = $is_alarms
    ? "(md.machine_alarms IS NOT NULL AND md.machine_alarms <> '')"
    : ($is_warnings
        ? "(md.cnc_warnings IS NOT NULL AND md.cnc_warnings <> '')"
        : "((md.machine_alarms IS NOT NULL AND md.machine_alarms <> '') OR (md.cnc_warnings IS NOT NULL AND md.cnc_warnings <> ''))");

$sql = "SELECT md.machine_id, md.machine_alarms, md.cnc_warnings, md.timestamp, m.oem_name, m.vfj_no, m.control_type FROM machine_data md JOIN machines m ON m.id = md.machine_id WHERE $col_cond";
$types = ''; $values = [];

if ($machine_id) { $sql .= ' AND md.machine_id = ?'; $types .= 'i'; $values[] = (int)$machine_id; }
if ($from_datetime) { $sql .= ' AND md.timestamp >= ?'; $types .= 's'; $values[] = $from_datetime; }
elseif ($from_date) { $sql .= ' AND md.timestamp >= ?'; $types .= 's'; $values[] = "$from_date 00:00:00"; }
if ($to_datetime)   { $sql .= ' AND md.timestamp <= ?'; $types .= 's'; $values[] = $to_datetime; }
elseif ($to_date)   { $sql .= ' AND md.timestamp <= ?'; $types .= 's'; $values[] = "$to_date 23:59:59"; }

$has_filter = $from_date || $to_date || $from_datetime || $to_datetime;
if (!$has_filter) $sql .= ' AND DATE(md.timestamp) = CURDATE()';
$sql .= ' ORDER BY md.timestamp DESC LIMIT ?'; $types .= 'i'; $values[] = $limit;

$s = $db->prepare($sql); $s->bind_param($types, ...$values); $s->execute();
$results = $s->get_result()->fetch_all(MYSQLI_ASSOC); $s->close();

function parse_alerts_from_row(array $row, string $col, string $type): array {
    $raw = $row[$col] ?? null;
    if (!$raw) return [];
    $label = ($row['oem_name'] && $row['vfj_no']) ? "{$row['oem_name']} #{$row['vfj_no']}" : "Machine {$row['machine_id']}";
    $ts    = $row['timestamp'];
    $parsed = json_decode($raw, true);
    if (!$parsed) return [];
    $items = is_array($parsed) && isset($parsed[0]) ? $parsed : [$parsed];
    return array_map(fn($a) => [
        'machine_id'   => $row['machine_id'],
        'machine_name' => $label,
        'timestamp'    => $ts,
        'code'         => $a['code']     ?? null,
        'message'      => $a['message']  ?? null,
        'severity'     => $a['severity'] ?? null,
        'line'         => $a['line']     ?? null,
        'type'         => $type,
    ], $items);
}

$out = [];
foreach ($results as $row) {
    if ($is_alarms || $is_alerts)   foreach (parse_alerts_from_row($row, 'machine_alarms', 'alarm')   as $a) $out[] = $a;
    if ($is_warnings || $is_alerts) foreach (parse_alerts_from_row($row, 'cnc_warnings',   'warning') as $a) $out[] = $a;
}
if ($is_alerts) usort($out, fn($a,$b) => strcmp($b['timestamp'] ?? '', $a['timestamp'] ?? ''));

$date_info    = build_date_info($from_datetime, $to_datetime, $from_date, $to_date);
$machine_info = $machine_id ? "Machine $machine_id" : 'All Machines';
$title        = $is_alarms ? 'Critical Alarms Report' : ($is_warnings ? 'Warnings Report' : 'All Alerts Report');
$key          = $is_alarms ? 'alarms' : ($is_warnings ? 'warnings' : 'alerts');
$stamp        = date('Ymd_His');

if ($export_type === 'csv') csv_response($out, "{$key}_export_$stamp.csv", $title, $date_info, $machine_info);
if ($export_type === 'pdf') pdf_response($out, $title, "{$key}_report_$stamp.pdf", $date_info, $machine_info);

json_response(['success' => true, 'count' => count($out), 'timestamp' => date('c'), $key => $out]);
