<?php
// api/mtbf_mttr.php  — GET /metrics/mtbf-mttr

$machine_id  = isset($_GET['machine_id']) ? (int)$_GET['machine_id'] : null;
$start       = $_GET['from_date'] ?? null;
$end         = $_GET['to_date']   ?? null;
$export_type = strtolower($_GET['export'] ?? '');

$db = get_db();

$where = ['1=1']; $params = [];
if ($machine_id) { $where[] = 'machine_id = ?'; $params[] = $machine_id; }
if ($start)      { $where[] = 'timestamp >= ?'; $params[] = $start; }
if ($end)        { $where[] = 'timestamp <= ?'; $params[] = $end; }
$where_sql = implode(' AND ', $where);
$types     = ($machine_id ? 'i' : '') . ($start ? 's' : '') . ($end ? 's' : '');

// MTBF
$mtbf_sql = "WITH breakdowns AS (SELECT machine_id, timestamp AS bd_time FROM machine_data WHERE $where_sql AND machine_state = 'BREAKDOWN' ORDER BY machine_id, timestamp),
numbered AS (SELECT machine_id, bd_time, ROW_NUMBER() OVER (PARTITION BY machine_id ORDER BY bd_time) AS rn FROM breakdowns),
joined AS (SELECT n1.machine_id, n1.bd_time AS curr_bd, n2.bd_time AS prev_bd FROM numbered n1 LEFT JOIN numbered n2 ON n1.machine_id = n2.machine_id AND n1.rn = n2.rn + 1)
SELECT machine_id, COUNT(*) - SUM(CASE WHEN prev_bd IS NULL THEN 1 ELSE 0 END) AS failure_pairs, AVG(CASE WHEN prev_bd IS NOT NULL THEN TIMESTAMPDIFF(SECOND, prev_bd, curr_bd) END) AS mtbf_seconds FROM joined GROUP BY machine_id";

$s = $db->prepare($mtbf_sql);
if ($types) $s->bind_param($types, ...$params);
$s->execute(); $mtbf_rows = $s->get_result()->fetch_all(MYSQLI_ASSOC); $s->close();

// MTTR
$up_in = "'RUNNING','IDLE'";
$sub_conds = ($start ? "AND md2.timestamp >= '$start'" : '') . ($end ? " AND md2.timestamp <= '$end'" : '');
$mttr_sql = "WITH repairs AS (SELECT md.machine_id, md.timestamp AS breakdown_time, (SELECT MIN(md2.timestamp) FROM machine_data md2 WHERE md2.machine_id = md.machine_id AND md2.timestamp > md.timestamp AND md2.machine_state IN ($up_in) $sub_conds) AS repair_time FROM machine_data md WHERE $where_sql AND md.machine_state = 'BREAKDOWN')
SELECT machine_id, COUNT(*) AS breakdowns, SUM(CASE WHEN repair_time IS NOT NULL THEN 1 ELSE 0 END) AS repairs_completed, AVG(CASE WHEN repair_time IS NOT NULL THEN TIMESTAMPDIFF(SECOND, breakdown_time, repair_time) END) AS mttr_seconds FROM repairs GROUP BY machine_id";

$s = $db->prepare($mttr_sql);
if ($types) $s->bind_param($types, ...$params);
$s->execute(); $mttr_rows = $s->get_result()->fetch_all(MYSQLI_ASSOC); $s->close();

$mtbf_map = []; foreach ($mtbf_rows as $r) $mtbf_map[$r['machine_id']] = $r;
$mttr_map = []; foreach ($mttr_rows as $r) $mttr_map[$r['machine_id']] = $r;

$machine_ids = array_unique(array_merge(array_keys($mtbf_map), array_keys($mttr_map)));
if ($machine_id && !in_array($machine_id, $machine_ids)) $machine_ids = [];

$meta = [];
if ($machine_ids) {
    $ph  = implode(',', array_fill(0, count($machine_ids), '?'));
    $s   = $db->prepare("SELECT id AS machine_id, oem_name, vfj_no FROM machines WHERE id IN ($ph)");
    $s->bind_param(str_repeat('i', count($machine_ids)), ...$machine_ids);
    $s->execute();
    foreach ($s->get_result()->fetch_all(MYSQLI_ASSOC) as $r) $meta[$r['machine_id']] = ['machine_name' => $r['oem_name'], 'vfj_no' => $r['vfj_no']];
    $s->close();
}

$results = [];
foreach ($machine_ids as $mid) {
    $mtbf_s = isset($mtbf_map[$mid]['mtbf_seconds']) ? (float)$mtbf_map[$mid]['mtbf_seconds'] : null;
    $mttr_s = isset($mttr_map[$mid]['mttr_seconds']) ? (float)$mttr_map[$mid]['mttr_seconds'] : null;
    $results[] = [
        'machine_id'                => $mid,
        'machine_name'              => $meta[$mid]['machine_name'] ?? null,
        'vfj_no'                    => $meta[$mid]['vfj_no']       ?? null,
        'breakdowns'                => (int)($mttr_map[$mid]['breakdowns'] ?? 0),
        'repairs_completed'         => (int)($mttr_map[$mid]['repairs_completed'] ?? 0),
        'mttr_seconds'              => $mttr_s,
        'mttr_minutes'              => $mttr_s !== null ? round($mttr_s / 60.0, 2) : null,
        'mttr_readable'             => fmt_hms($mttr_s),
        'failures_counted_for_mtbf' => (int)($mtbf_map[$mid]['failure_pairs'] ?? 0),
        'mtbf_seconds'              => $mtbf_s,
        'mtbf_hours'                => $mtbf_s !== null ? round($mtbf_s / 3600.0, 2) : null,
        'mtbf_readable'             => fmt_hms($mtbf_s),
    ];
}

if ($export_type === 'csv' || $export_type === 'pdf') {
    $export_rows = array_map(fn($r) => [
        'Machine ID' => $r['machine_id'], 'Machine Name' => $r['machine_name'], 'VFJ No' => $r['vfj_no'],
        'Breakdowns' => $r['breakdowns'], 'Repairs Completed' => $r['repairs_completed'],
        'MTTR (seconds)' => $r['mttr_seconds'], 'MTTR (minutes)' => $r['mttr_minutes'],
        'Failures Counted (MTBF)' => $r['failures_counted_for_mtbf'],
        'MTBF (seconds)' => $r['mtbf_seconds'], 'MTBF (hours)' => $r['mtbf_hours'],
    ], $results);
    $date_info    = ($start ?? '—') . ' to ' . ($end ?? '—');
    $machine_info = $machine_id ? "Machine $machine_id" : 'All Machines';
    $stamp        = date('Ymd_His');
    if ($export_type === 'csv') csv_response($export_rows, "mtbf_mttr_$stamp.csv", 'MTBF / MTTR Report', $date_info, $machine_info);
    pdf_response($export_rows, 'MTBF / MTTR Report', "mtbf_mttr_$stamp.pdf", $date_info, $machine_info);
}

json_response(['filters' => ['machine_id' => $machine_id, 'start' => $start, 'end' => $end], 'states' => ['failure_state' => 'BREAKDOWN', 'up_states' => ['RUNNING','IDLE']], 'results' => $results]);
