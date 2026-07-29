<?php
// api/reports.php

$current_user = require_auth();
$db           = get_db();
$path         = $GLOBALS['route_path'];

// ── OEE Report ────────────────────────────────────────────────────────────────
if (str_ends_with($path, '/oee')) {
    $machine_id    = $_GET['machine_id']    ?? null;
    $from_date     = $_GET['from_date']     ?? null;
    $to_date       = $_GET['to_date']       ?? null;
    $from_datetime = $_GET['from_datetime'] ?? null;
    $to_datetime   = $_GET['to_datetime']   ?? null;
    $export_type   = strtolower($_GET['export'] ?? '');

    $date_filter = ''; $params = [];
    if ($from_datetime) { $date_filter .= ' AND DATE(timestamp) >= ?'; $params[] = explode(' ', $from_datetime)[0]; }
    elseif ($from_date) { $date_filter .= ' AND DATE(timestamp) >= ?'; $params[] = $from_date; }
    if ($to_datetime)   { $date_filter .= ' AND DATE(timestamp) <= ?'; $params[] = explode(' ', $to_datetime)[0]; }
    elseif ($to_date)   { $date_filter .= ' AND DATE(timestamp) <= ?'; $params[] = $to_date; }

    if (!$from_date && !$to_date && !$from_datetime && !$to_datetime) {
        $r = $db->query("SELECT COUNT(*) AS c FROM machine_production WHERE DATE(timestamp) = CURDATE() AND total_cycle_time != '00:00:00'")->fetch_assoc();
        if ($r['c'] == 0) {
            $lr = $db->query("SELECT DATE(timestamp) AS d FROM machine_production WHERE total_cycle_time != '00:00:00' ORDER BY timestamp DESC LIMIT 1")->fetch_assoc();
            if ($lr) { $date_filter = ' AND DATE(timestamp) = ?'; $params[] = $lr['d']; }
        } else {
            $date_filter = ' AND DATE(timestamp) = CURDATE()';
        }
    }

    if ($from_date || $to_date || $from_datetime || $to_datetime) {
        $s = $db->prepare("SELECT COUNT(*) AS c FROM machine_production WHERE 1=1 $date_filter");
        if ($params) $s->bind_param(str_repeat('s', count($params)), ...$params);
        $s->execute();
        if ((int)$s->get_result()->fetch_assoc()['c'] === 0) { $s->close(); json_response([], 200); }
        $s->close();
    }

    $machines = $machine_id
        ? $db->query("SELECT id, oem_name, vfj_no FROM machines WHERE id = " . (int)$machine_id)->fetch_all(MYSQLI_ASSOC)
        : $db->query("SELECT id, oem_name, vfj_no FROM machines ORDER BY id")->fetch_all(MYSQLI_ASSOC);
    if (!$machines) json_response(['error' => 'No machines found'], 404);

    $oee_data = [];
    foreach ($machines as $machine) {
        $mid = $machine['id'];

        $dt_sql = "SELECT COALESCE(SUM(TIMESTAMPDIFF(MINUTE, start_time, end_time)), 0) AS total_downtime, MIN(timestamp) AS period_start, MAX(timestamp) AS period_end, COUNT(*) AS downtime_events FROM downtime_entries WHERE machine_id = ? $date_filter";
        $s = $db->prepare($dt_sql);
        $s->bind_param('i' . str_repeat('s', count($params)), $mid, ...$params);
        $s->execute(); $dt = $s->get_result()->fetch_assoc(); $s->close();
        $total_downtime = (float)($dt['total_downtime'] ?? 0);
        $availability   = (480.0 - $total_downtime) / 480.0;

        $pr_sql = "SELECT COALESCE(SUM(TIME_TO_SEC(total_cycle_time)/60), 0) AS total_production_minutes, COUNT(*) AS parts_produced, MIN(timestamp) AS prod_start, MAX(timestamp) AS prod_end FROM machine_production WHERE machine_id = ? AND total_cycle_time != '00:00:00' $date_filter";
        $s = $db->prepare($pr_sql);
        $s->bind_param('i' . str_repeat('s', count($params)), $mid, ...$params);
        $s->execute(); $pr = $s->get_result()->fetch_assoc(); $s->close();
        $total_prod_time = (float)($pr['total_production_minutes'] ?? 0);
        $parts_produced  = (int)($pr['parts_produced'] ?? 0);
        $performance     = $total_prod_time / 480.0;
        $quality         = 0.85;
        $overall_oee     = $availability * $performance * $quality;

        $period_start = $dt['period_start'] ?? $pr['prod_start'] ?? null;
        $period_end   = $dt['period_end']   ?? $pr['prod_end']   ?? null;

        $oee_data[] = [
            'machine_id'               => $mid,
            'machine_name'             => $machine['oem_name'],
            'vfj_no'                   => $machine['vfj_no'],
            'availability'             => round($availability, 3),
            'performance'              => round($performance, 3),
            'quality'                  => round($quality, 3),
            'overall_oee'              => round($overall_oee, 3),
            'parts_produced'           => $parts_produced,
            'total_downtime_minutes'   => $total_downtime,
            'total_production_minutes' => round($total_prod_time, 2),
            'snapshot_count'           => (int)($dt['downtime_events'] ?? 0) + $parts_produced,
            'period_start'             => $period_start,
            'period_end'               => $period_end,
        ];
    }

    $date_info    = build_date_info($from_datetime, $to_datetime, $from_date, $to_date);
    $machine_info = $machine_id ? "Machine $machine_id" : 'All Machines';
    if ($export_type === 'csv') csv_response($oee_data, 'oee_report_' . date('Ymd_His') . '.csv', 'OEE Report', $date_info, $machine_info);
    if ($export_type === 'pdf') pdf_response($oee_data, 'OEE Report', 'oee_report_' . date('Ymd_His') . '.pdf', $date_info, $machine_info);
    json_response(['success' => true, 'count' => count($oee_data), 'timestamp' => date('c'), 'oee_data' => $oee_data]);
}

// ── Production Report ─────────────────────────────────────────────────────────
if (str_ends_with($path, '/production')) {
    $machine_id    = $_GET['machine_id']    ?? null;
    $from_date     = $_GET['from_date']     ?? null;
    $to_date       = $_GET['to_date']       ?? null;
    $from_datetime = $_GET['from_datetime'] ?? null;
    $to_datetime   = $_GET['to_datetime']   ?? null;
    $export_type   = strtolower($_GET['export'] ?? '');
    $limit         = min(max(1, (int)($_GET['limit'] ?? 100)), 1000);

    $now = date('Y-m-d');
    if ($from_datetime && $to_datetime)     { $start_dt = $from_datetime; $end_dt = $to_datetime; }
    elseif ($from_datetime)                 { $start_dt = $from_datetime; $end_dt = "$now 23:59:59"; }
    elseif ($to_datetime)                   { $d = explode(' ', $to_datetime)[0]; $start_dt = "$d 00:00:00"; $end_dt = $to_datetime; }
    elseif ($from_date && $to_date)         { $start_dt = "$from_date 00:00:00"; $end_dt = "$to_date 23:59:59"; }
    elseif ($from_date)                     { $start_dt = "$from_date 00:00:00"; $end_dt = "$from_date 23:59:59"; }
    elseif ($to_date)                       { $start_dt = "$to_date 00:00:00"; $end_dt = "$to_date 23:59:59"; }
    else                                    { $start_dt = "$now 00:00:00"; $end_dt = "$now 23:59:59"; }

    $sql = "SELECT mp.machine_id, mp.shift_operator_name, mp.operator_id, mp.shift_type, mp.job_order_no, mp.batch_quantity, mp.checklist,
        m.oem_name AS machine_name, mp.machine_no, mp.product_component_name, mp.product_component_no, mp.machine_status,
        COUNT(CASE WHEN mp.total_cycle_time != '00:00:00' AND mp.results = 'PASS' THEN 1 END) AS ok_parts,
        COUNT(CASE WHEN mp.total_cycle_time != '00:00:00' AND ((mp.machine_status = 'STOPPED') OR mp.results IS NULL OR mp.results = 'FAIL') THEN 1 END) AS bad_parts,
        DATE_FORMAT(mp.timestamp, '%Y-%m-%d %H:00:00') AS timestamp
    FROM machine_production mp JOIN machines m ON m.id = CAST(mp.machine_id AS UNSIGNED)
    WHERE mp.timestamp BETWEEN ? AND ?";
    $types = 'ss'; $values = [$start_dt, $end_dt];
    if ($machine_id) { $sql .= ' AND mp.machine_id = ?'; $types .= 'i'; $values[] = (int)$machine_id; }
    $sql .= " GROUP BY mp.machine_id, mp.shift_operator_name, machine_name, mp.machine_no, mp.product_component_name, mp.product_component_no, mp.section_code_name, mp.machine_status, DATE_FORMAT(mp.timestamp, '%Y-%m-%d %H') ORDER BY timestamp DESC LIMIT ?";
    $types .= 'i'; $values[] = $limit;

    $s = $db->prepare($sql); $s->bind_param($types, ...$values); $s->execute();
    $results = $s->get_result()->fetch_all(MYSQLI_ASSOC); $s->close();

    $production_data = array_map(fn($r) => [
        'machine_id'             => (string)$r['machine_id'],
        'shift_operator_name'    => $r['shift_operator_name'],
        'machine_name'           => $r['machine_name'],
        'operator_id'            => $r['operator_id'],
        'shift_type'             => $r['shift_type'],
        'job_order_no'           => $r['job_order_no'],
        'batch_quantity'         => $r['batch_quantity'],
        'checklist'              => $r['checklist'],
        'machine_no'             => $r['machine_no'],
        'product_component_name' => $r['product_component_name'],
        'product_component_no'   => $r['product_component_no'],
        'machine_status'         => $r['machine_status'],
        'ok_parts'               => (string)$r['ok_parts'],
        'bad_parts'              => (string)$r['bad_parts'],
        'timestamp'              => $r['timestamp'],
    ], $results);

    // Totals
    $s = $db->prepare("SELECT mp.machine_id, COALESCE(SUM(TIME_TO_SEC(mp.total_cycle_time)), 0) AS total_cycle_time_seconds FROM machine_production mp WHERE mp.timestamp BETWEEN ? AND ? AND mp.total_cycle_time IS NOT NULL AND mp.total_cycle_time != '00:00:00' GROUP BY mp.machine_id");
    $s->bind_param('ss', $start_dt, $end_dt); $s->execute();
    $cycle_times = []; foreach ($s->get_result()->fetch_all(MYSQLI_ASSOC) as $r) $cycle_times[(string)$r['machine_id']] = (int)$r['total_cycle_time_seconds']; $s->close();

    $s = $db->prepare("SELECT md.machine_id, TIMESTAMPDIFF(SECOND, MIN(CASE WHEN md.machine_state='IDLE' THEN md.timestamp END), MAX(CASE WHEN md.machine_state='OFFLINE' THEN md.timestamp END)) AS total_time_seconds FROM machine_data md WHERE md.timestamp BETWEEN ? AND ? GROUP BY md.machine_id");
    $s->bind_param('ss', $start_dt, $end_dt); $s->execute();
    $total_times = []; foreach ($s->get_result()->fetch_all(MYSQLI_ASSOC) as $r) $total_times[(string)$r['machine_id']] = (int)($r['total_time_seconds'] ?? 0); $s->close();

    $s = $db->prepare("WITH ordered AS (SELECT md.machine_id, md.machine_state, md.timestamp AS ts, LEAD(md.timestamp) OVER (PARTITION BY md.machine_id ORDER BY md.timestamp) AS next_ts, LEAD(md.machine_state) OVER (PARTITION BY md.machine_id ORDER BY md.timestamp) AS next_state FROM machine_data md WHERE md.timestamp BETWEEN ? AND ?) SELECT machine_id, COALESCE(SUM(TIMESTAMPDIFF(SECOND, ts, next_ts)), 0) AS idle_seconds FROM ordered WHERE machine_state='IDLE' AND next_state='RUNNING' AND next_ts IS NOT NULL GROUP BY machine_id");
    $s->bind_param('ss', $start_dt, $end_dt); $s->execute();
    $idle_times = []; foreach ($s->get_result()->fetch_all(MYSQLI_ASSOC) as $r) $idle_times[(string)$r['machine_id']] = (int)$r['idle_seconds']; $s->close();

    $all_ids = array_unique(array_merge(array_keys($cycle_times), array_keys($total_times), array_keys($idle_times)));
    $totals  = array_map(fn($mid) => [
        'machine_id'       => $mid,
        'total_cycle_time' => hms((int)($cycle_times[$mid] ?? 0)),
        'total_time'       => hms((int)($total_times[$mid] ?? 0)),
        'total_idle_time'  => hms((int)($idle_times[$mid] ?? 0)),
    ], $all_ids);

    $date_info    = "$start_dt to $end_dt";
    $machine_info = $machine_id ? "Machine $machine_id" : 'All Machines';
    if ($export_type === 'csv') csv_response($production_data, 'production_report_' . date('Ymd_His') . '.csv', 'Production Report', $date_info, $machine_info);
    if ($export_type === 'pdf') pdf_response($production_data, 'Production Report', 'production_report_' . date('Ymd_His') . '.pdf', $date_info, $machine_info);
    json_response(['success' => true, 'count' => count($production_data), 'timestamp' => date('c'), 'shift_data' => $production_data, 'totals' => $totals]);
}

// ── Downtime Report ───────────────────────────────────────────────────────────
if (str_ends_with($path, '/downtime')) {
    $machine_id    = $_GET['machine_id']    ?? null;
    $from_date     = $_GET['from_date']     ?? null;
    $to_date       = $_GET['to_date']       ?? null;
    $from_datetime = $_GET['from_datetime'] ?? null;
    $to_datetime   = $_GET['to_datetime']   ?? null;
    $export_type   = strtolower($_GET['export'] ?? '');
    $limit         = min(max(1, (int)($_GET['limit'] ?? 100)), 1000);

    $sql = "SELECT de.machine_id, de.reason, de.start_time, de.end_time, TIMESTAMPDIFF(MINUTE, de.start_time, de.end_time) AS duration_minutes, de.timestamp, m.oem_name, m.vfj_no FROM downtime_entries de JOIN machines m ON m.id = de.machine_id WHERE 1=1";
    $types = ''; $values = [];
    if ($machine_id) { $sql .= ' AND de.machine_id = ?'; $types .= 'i'; $values[] = (int)$machine_id; }
    if ($from_datetime) { $sql .= ' AND de.timestamp >= ?'; $types .= 's'; $values[] = $from_datetime; }
    elseif ($from_date) { $sql .= ' AND de.timestamp >= ?'; $types .= 's'; $values[] = "$from_date 00:00:00"; }
    if ($to_datetime)   { $sql .= ' AND de.timestamp <= ?'; $types .= 's'; $values[] = $to_datetime; }
    elseif ($to_date)   { $sql .= ' AND de.timestamp <= ?'; $types .= 's'; $values[] = "$to_date 23:59:59"; }
    if (!$from_date && !$to_date && !$from_datetime && !$to_datetime) $sql .= ' AND DATE(de.timestamp) = CURDATE()';
    $sql .= ' ORDER BY de.timestamp DESC LIMIT ?'; $types .= 'i'; $values[] = $limit;

    $s = $db->prepare($sql); $s->bind_param($types, ...$values); $s->execute();
    $results = $s->get_result()->fetch_all(MYSQLI_ASSOC); $s->close();

    $downtime_data = array_map(fn($r) => [
        'machine_id'       => $r['machine_id'],
        'machine_name'     => ($r['oem_name'] && $r['vfj_no']) ? "{$r['oem_name']} #{$r['vfj_no']}" : "Machine {$r['machine_id']}",
        'vfj_no'           => (string)($r['vfj_no'] ?? ''),
        'reason'           => $r['reason'],
        'start_time'       => $r['start_time'],
        'end_time'         => $r['end_time'],
        'duration_minutes' => (float)($r['duration_minutes'] ?? 0),
        'timestamp'        => $r['timestamp'],
    ], $results);

    $date_info    = build_date_info($from_datetime, $to_datetime, $from_date, $to_date);
    $machine_info = $machine_id ? "Machine $machine_id" : 'All Machines';
    if ($export_type === 'csv') csv_response($downtime_data, 'downtime_report_' . date('Ymd_His') . '.csv', 'Downtime Report', $date_info, $machine_info);
    if ($export_type === 'pdf') pdf_response($downtime_data, 'Downtime Report', 'downtime_report_' . date('Ymd_His') . '.pdf', $date_info, $machine_info);
    json_response(['success' => true, 'detailed_events_count' => count($downtime_data), 'timestamp' => date('c'), 'downtime_events' => $downtime_data]);
}

// ── Energy Report ─────────────────────────────────────────────────────────────
if (str_ends_with($path, '/energy')) {
    $machine_id    = $_GET['machine_id']    ?? null;
    $from_date     = $_GET['from_date']     ?? null;
    $to_date       = $_GET['to_date']       ?? null;
    $from_datetime = $_GET['from_datetime'] ?? null;
    $to_datetime   = $_GET['to_datetime']   ?? null;
    $export_type   = strtolower($_GET['export'] ?? '');

    $inner = 'WHERE 1=1'; $types = ''; $values = [];
    if ($machine_id) { $inner .= ' AND machine_id = ?'; $types .= 'i'; $values[] = (int)$machine_id; }
    if ($from_datetime) { $inner .= ' AND timestamp >= ?'; $types .= 's'; $values[] = $from_datetime; }
    elseif ($from_date) { $inner .= ' AND timestamp >= ?'; $types .= 's'; $values[] = "$from_date 00:00:00"; }
    if ($to_datetime)   { $inner .= ' AND timestamp <= ?'; $types .= 's'; $values[] = $to_datetime; }
    elseif ($to_date)   { $inner .= ' AND timestamp <= ?'; $types .= 's'; $values[] = "$to_date 23:59:59"; }
    if (!$from_date && !$to_date && !$from_datetime && !$to_datetime) $inner .= ' AND DATE(timestamp) = CURDATE()';

    $sql = "SELECT t.* FROM energy_data t INNER JOIN (SELECT machine_id, MAX(timestamp) AS max_ts FROM energy_data $inner GROUP BY machine_id) x ON t.machine_id = x.machine_id AND t.timestamp = x.max_ts ORDER BY t.machine_id";
    $s = $db->prepare($sql); if ($types) $s->bind_param($types, ...$values); $s->execute();
    $results = $s->get_result()->fetch_all(MYSQLI_ASSOC); $s->close();

    $agg_sql = "SELECT machine_id, AVG((voltage1*current1*power_factor1+voltage2*current2*power_factor2+voltage3*current3*power_factor3)/1000.0) AS avg_power_kw, MAX((voltage1*current1*power_factor1+voltage2*current2*power_factor2+voltage3*current3*power_factor3)/1000.0) AS peak_power_kw, COUNT(*) AS reading_count, MIN(timestamp) AS period_start, MAX(timestamp) AS period_end FROM energy_data $inner GROUP BY machine_id ORDER BY machine_id";
    $s = $db->prepare($agg_sql); if ($types) $s->bind_param($types, ...$values); $s->execute();
    $agg_rows = []; foreach ($s->get_result()->fetch_all(MYSQLI_ASSOC) as $r) $agg_rows[$r['machine_id']] = $r; $s->close();

    $energy_data = [];
    foreach ($results as $row) {
        $mid  = $row['machine_id'];
        $agg  = $agg_rows[$mid] ?? [];
        $p_kw = ((float)$row['voltage1']*(float)$row['current1']*(float)$row['power_factor1']
               + (float)$row['voltage2']*(float)$row['current2']*(float)$row['power_factor2']
               + (float)$row['voltage3']*(float)$row['current3']*(float)$row['power_factor3']) / 1000.0;
        $total_kwh = 0.0;
        if (!empty($agg['avg_power_kw']) && !empty($agg['period_start']) && !empty($agg['period_end'])) {
            $dur_h = (strtotime($agg['period_end']) - strtotime($agg['period_start'])) / 3600.0;
            $total_kwh = (float)$agg['avg_power_kw'] * $dur_h;
        }
        $energy_data[] = [
            'machine_id'       => $mid,
            'voltage1'         => round((float)$row['voltage1'], 3),
            'voltage2'         => round((float)$row['voltage2'], 3),
            'voltage3'         => round((float)$row['voltage3'], 3),
            'current1'         => round((float)$row['current1'], 3),
            'current2'         => round((float)$row['current2'], 3),
            'current3'         => round((float)$row['current3'], 3),
            'power_factor1'    => round((float)$row['power_factor1'], 3),
            'power_factor2'    => round((float)$row['power_factor2'], 3),
            'power_factor3'    => round((float)$row['power_factor3'], 3),
            'latest_power_kw'  => round($p_kw, 3),
            'avg_power_kw'     => round((float)($agg['avg_power_kw'] ?? 0), 3),
            'peak_power_kw'    => round((float)($agg['peak_power_kw'] ?? 0), 3),
            'total_energy_kWh' => round($total_kwh, 3),
            'reading_count'    => (int)($agg['reading_count'] ?? 1),
            'period_start'     => $agg['period_start'] ?? null,
            'period_end'       => $agg['period_end']   ?? null,
            'latest_timestamp' => $row['timestamp'],
        ];
    }

    $date_info    = build_date_info($from_datetime, $to_datetime, $from_date, $to_date);
    $machine_info = $machine_id ? "Machine $machine_id" : 'All Machines';
    if ($export_type === 'csv') csv_response($energy_data, 'energy_report_' . date('Ymd_His') . '.csv', 'Energy Report', $date_info, $machine_info);
    if ($export_type === 'pdf') pdf_response($energy_data, 'Energy Report', 'energy_report_' . date('Ymd_His') . '.pdf', $date_info, $machine_info);
    json_response(['success' => true, 'count' => count($energy_data), 'generated_at' => date('c'), 'energy_data' => $energy_data]);
}

// ── Breakdowns Report ─────────────────────────────────────────────────────────
if (str_ends_with($path, '/breakdowns')) {
    $vfj_no    = trim($_GET['vfj_no']    ?? '');
    $from_date = $_GET['from_date'] ?? null;
    $to_date   = $_GET['to_date']   ?? null;
    $limit     = min(max(1, (int)($_GET['limit'] ?? 100)), 1000);

    $base_filters = ['1=1']; $params = [];
    if ($vfj_no)    { $base_filters[] = 'm.vfj_no = ?';       $params[] = $vfj_no; }
    if ($from_date) { $base_filters[] = 'md.timestamp >= ?';   $params[] = "$from_date 00:00:00"; }
    if ($to_date)   { $base_filters[] = 'md.timestamp <= ?';   $params[] = "$to_date 23:59:59"; }
    $where = implode(' AND ', $base_filters);

    $sql = "WITH base AS (SELECT md.machine_id, md.timestamp, md.machine_state, m.vfj_no, m.oem_name AS machine_name FROM machine_data md JOIN machines m ON m.id = md.machine_id WHERE $where),
    ordered AS (SELECT b.*, LAG(b.machine_state) OVER (PARTITION BY b.machine_id ORDER BY b.timestamp) AS prev_state, CASE WHEN LAG(b.machine_state) OVER (PARTITION BY b.machine_id ORDER BY b.timestamp) IS NULL OR b.machine_state <> LAG(b.machine_state) OVER (PARTITION BY b.machine_id ORDER BY b.timestamp) THEN 1 ELSE 0 END AS is_new_run FROM base b),
    runs AS (SELECT machine_id, vfj_no, machine_name, machine_state, timestamp, SUM(is_new_run) OVER (PARTITION BY machine_id ORDER BY timestamp ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS run_id FROM ordered),
    agg AS (SELECT machine_id, vfj_no, machine_name, run_id, MIN(timestamp) AS run_start_ts, MIN(machine_state) AS run_state FROM runs GROUP BY machine_id, vfj_no, machine_name, run_id)
    SELECT a.machine_id, a.vfj_no, a.machine_name, a.run_start_ts AS breakdown_start, n.run_start_ts AS idle_start, TIMESTAMPDIFF(SECOND, a.run_start_ts, n.run_start_ts) AS duration_seconds
    FROM agg a JOIN agg n ON n.machine_id = a.machine_id AND n.run_id = a.run_id + 1
    WHERE a.run_state = 'BREAKDOWN' AND n.run_state = 'IDLE' ORDER BY idle_start DESC LIMIT ?";

    $params[] = $limit;
    $s = $db->prepare($sql);
    $s->bind_param(str_repeat('s', count($params) - 1) . 'i', ...$params);
    $s->execute(); $rows = $s->get_result()->fetch_all(MYSQLI_ASSOC); $s->close();

    $out = array_map(fn($r) => [
        'machine_id'       => $r['machine_id'],
        'vfj_no'           => $r['vfj_no'],
        'machine_name'     => $r['machine_name'],
        'breakdown_start'  => $r['breakdown_start'],
        'idle_start'       => $r['idle_start'],
        'duration_seconds' => (int)($r['duration_seconds'] ?? 0),
        'duration_hms'     => fmt_hms((float)($r['duration_seconds'] ?? 0)),
    ], $rows);

    json_response(['success' => true, 'count' => count($out), 'filters' => ['vfj_no' => $vfj_no ?: null, 'from_date' => $from_date, 'to_date' => $to_date, 'limit' => $limit], 'breakdowns' => $out]);
}

json_response(['error' => 'Not found'], 404);
