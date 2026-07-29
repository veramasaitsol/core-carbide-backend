<?php
// api/oee_calculate.php  — GET /api/oee/calculate

$machine_id              = isset($_GET['machine_id']) ? (int)$_GET['machine_id'] : null;
$start_date              = $_GET['start_date'] ?? null;
$end_date                = $_GET['end_date']   ?? null;
$decimals                = max(0, min(6, (int)($_GET['decimals'] ?? 3)));
$ideal_cycle_time_seconds = isset($_GET['ideal_cycle_time_seconds']) ? (int)$_GET['ideal_cycle_time_seconds'] : null;
$export_type             = strtolower($_GET['export'] ?? '');

$db  = get_db();
$now = date('Y-m-d');

// Normalize window
$start_dt = $start_date ? date('Y-m-d 00:00:00', strtotime($start_date)) : "$now 00:00:00";
$end_dt   = $end_date   ? date('Y-m-d 23:59:59', strtotime($end_date))   : date('Y-m-d 23:59:59', strtotime($start_dt));

// Get machines
$machines = $machine_id
    ? $db->query("SELECT id, oem_name AS mname, vfj_no FROM machines WHERE id = $machine_id")->fetch_all(MYSQLI_ASSOC)
    : $db->query("SELECT id, oem_name AS mname, vfj_no FROM machines ORDER BY id")->fetch_all(MYSQLI_ASSOC);

$individual = [];

foreach ($machines as $m) {
    $mid   = $m['id'];
    $label = $m['mname'] ? ($m['vfj_no'] ? "{$m['mname']} #{$m['vfj_no']}" : $m['mname']) : "Machine $mid";

    // Planned seconds (from shift windows)
    $s = $db->prepare("SELECT shift_start, shift_end FROM machine_production WHERE machine_id = ? AND shift_start IS NOT NULL AND shift_start <= ? AND COALESCE(shift_end, ?) >= ? ORDER BY shift_start ASC");
    $s->bind_param('isss', $mid, $end_dt, $end_dt, $start_dt); $s->execute();
    $shift_rows = $s->get_result()->fetch_all(MYSQLI_ASSOC); $s->close();
    $intervals = [];
    foreach ($shift_rows as $sr) {
        $s_ts = max(strtotime($sr['shift_start']), strtotime($start_dt));
        $e_ts = min(strtotime($sr['shift_end'] ?? $end_dt), strtotime($end_dt));
        if ($e_ts > $s_ts) $intervals[] = [$s_ts, $e_ts];
    }
    // merge intervals
    usort($intervals, fn($a,$b) => $a[0] <=> $b[0]);
    $merged = []; foreach ($intervals as $iv) { if (!$merged || $iv[0] > end($merged)[1]) $merged[] = $iv; else $merged[count($merged)-1][1] = max(end($merged)[1], $iv[1]); }
    $planned_s = array_sum(array_map(fn($iv) => $iv[1] - $iv[0], $merged));

    // Downtime seconds
    $s = $db->prepare("SELECT COALESCE(SUM(GREATEST(TIMESTAMPDIFF(SECOND, GREATEST(COALESCE(start_time,timestamp), ?), LEAST(COALESCE(end_time,NOW()), ?)), 0)), 0) AS ds FROM downtime_entries WHERE machine_id = ? AND COALESCE(start_time,timestamp) < ? AND COALESCE(end_time,NOW()) > ?");
    $s->bind_param('ssiss', $start_dt, $end_dt, $mid, $end_dt, $start_dt); $s->execute();
    $downtime_s = (int)$s->get_result()->fetch_assoc()['ds']; $s->close();

    // Breakdown seconds
    $s = $db->prepare("SELECT machine_state, timestamp FROM machine_data WHERE machine_id = ? AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp ASC");
    $s->bind_param('iss', $mid, $start_dt, $end_dt); $s->execute();
    $md_rows = $s->get_result()->fetch_all(MYSQLI_ASSOC); $s->close();
    $breakdown_s = 0; $in_bd = false; $bd_start = null;
    foreach ($md_rows as $r) {
        $state = strtoupper($r['machine_state'] ?? '');
        $ts    = strtotime($r['timestamp']);
        if ($state === 'BREAKDOWN' && !$in_bd) { $in_bd = true; $bd_start = $ts; }
        elseif (in_array($state, ['IDLE','RUNNING']) && $in_bd && $bd_start) { $breakdown_s += $ts - $bd_start; $in_bd = false; $bd_start = null; }
    }
    if ($in_bd && $bd_start) $breakdown_s += min(time(), strtotime($end_dt)) - $bd_start;

    $machine_on_s = max($planned_s - $downtime_s - $breakdown_s, 0);

    // Parts & quality
    $s = $db->prepare("SELECT COALESCE(SUM(CASE WHEN results IS NOT NULL AND LOWER(results)='pass' THEN 1 ELSE 0 END),0) AS good_parts, NULLIF(MIN(NULLIF(TIME_TO_SEC(total_cycle_time),0)),0) AS min_cycle_s FROM machine_production WHERE machine_id = ? AND COALESCE(shift_start,timestamp) >= ? AND COALESCE(shift_start,timestamp) <= ?");
    $s->bind_param('iss', $mid, $start_dt, $end_dt); $s->execute();
    $pq = $s->get_result()->fetch_assoc(); $s->close();
    $good_parts   = (int)($pq['good_parts'] ?? 0);
    $min_cycle_s  = $pq['min_cycle_s'] !== null ? (int)$pq['min_cycle_s'] : null;

    $s = $db->prepare("SELECT COALESCE(SUM(CASE WHEN LOWER(TRIM(results)) IN ('pass','fail') AND TIME_TO_SEC(total_cycle_time)>0 THEN 1 ELSE 0 END),0) AS total_parts FROM machine_production WHERE machine_id = ? AND COALESCE(shift_start,timestamp) >= ? AND COALESCE(shift_start,timestamp) <= ?");
    $s->bind_param('iss', $mid, $start_dt, $end_dt); $s->execute();
    $total_parts = (int)$s->get_result()->fetch_assoc()['total_parts']; $s->close();

    $quality_pct      = $total_parts > 0 ? $good_parts / $total_parts * 100.0 : 0.0;
    $availability_pct = $planned_s > 0 ? $machine_on_s / $planned_s * 100.0 : 0.0;
    $ict              = $ideal_cycle_time_seconds ?? $min_cycle_s ?? 0;
    $performance_pct  = ($machine_on_s > 0 && $ict > 0) ? min(($ict * $total_parts) / $machine_on_s * 100.0, 100.0) : 0.0;
    $oee              = $availability_pct * $performance_pct * $quality_pct / 10000.0;

    $s = $db->prepare("SELECT COUNT(*) AS c FROM machine_data WHERE machine_id = ? AND timestamp >= ? AND timestamp <= ?");
    $s->bind_param('iss', $mid, $start_dt, $end_dt); $s->execute();
    $data_points = (int)$s->get_result()->fetch_assoc()['c']; $s->close();

    $individual[] = [
        'machine_id'               => $mid,
        'machine_name'             => $label,
        'oem_name'                 => $m['mname'],
        'vfj_no'                   => $m['vfj_no'],
        'availability'             => round($availability_pct / 100.0, $decimals),
        'performance'              => round($performance_pct / 100.0, $decimals),
        'quality'                  => round($quality_pct / 100.0, $decimals),
        'overall_oee'              => round($oee / 100.0, $decimals),
        'parts_produced'           => $total_parts,
        'good_parts'               => $good_parts,
        'total_downtime_minutes'   => round($downtime_s / 60.0, 2),
        'total_production_minutes' => round($machine_on_s / 60.0, 2),
        'period_start'             => $start_dt,
        'period_end'               => $end_dt,
        'data_points'              => $data_points,
    ];
}

$n = count($individual);
$fleet = $n > 0 ? [
    'total_machines'              => $n,
    'fleet_availability'          => round(array_sum(array_column($individual, 'availability')) / $n, $decimals),
    'fleet_performance'           => round(array_sum(array_column($individual, 'performance')) / $n, $decimals),
    'fleet_quality'               => round(array_sum(array_column($individual, 'quality')) / $n, $decimals),
    'fleet_overall_oee'           => round(array_sum(array_column($individual, 'overall_oee')) / $n, $decimals),
    'total_parts_produced'        => array_sum(array_column($individual, 'parts_produced')),
    'total_fleet_downtime'        => array_sum(array_column($individual, 'total_downtime_minutes')),
    'total_fleet_production_time' => array_sum(array_column($individual, 'total_production_minutes')),
] : [];

if ($export_type === 'csv' || $export_type === 'pdf') {
    $date_info    = "$start_dt to $end_dt";
    $machine_info = $machine_id ? "Machine $machine_id" : 'All Machines';
    $stamp        = date('Ymd_His');
    if ($export_type === 'csv') csv_response($individual, "oee_calculate_$stamp.csv", 'OEE Calculate', $date_info, $machine_info);
    pdf_response($individual, 'OEE Calculate', "oee_calculate_$stamp.pdf", $date_info, $machine_info);
}

json_response(['success' => true, 'timestamp' => date('c'), 'fleet_summary' => $fleet, 'individual_machines' => $individual]);
