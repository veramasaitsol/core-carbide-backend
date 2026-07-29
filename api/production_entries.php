<?php
// api/production_entries.php

$current_user = require_auth();
$db           = get_db();
$path         = $GLOBALS['route_path'];
$method       = $_SERVER['REQUEST_METHOD'];

// POST /api/production/target
if ($method === 'POST' && str_ends_with($path, '/target')) {
    $data       = json_decode(file_get_contents('php://input'), true) ?? [];
    $machine_id = (int)($data['machine_id'] ?? 0);
    if ($machine_id <= 0) json_response(['error' => 'machine_id is required and must be > 0'], 400);

    $start_time = $data['start_time'] ?? null;
    $end_time   = $data['end_time']   ?? null;
    if (!$start_time || !$end_time) json_response(['error' => 'start_time and end_time are required'], 400);

    $product_target = $data['product_target'] ?? null;
    if ($product_target === null) json_response(['error' => 'product_target is required'], 400);
    $product_target = (int)$product_target;
    if ($product_target < 0) json_response(['error' => 'product_target must be >= 0'], 400);

    $s = $db->prepare('SELECT id, oem_name, vfj_no, ip_address, control_type, control_details, control_model FROM machines WHERE id = ? LIMIT 1');
    $s->bind_param('i', $machine_id); $s->execute();
    $m = $s->get_result()->fetch_assoc(); $s->close();
    if (!$m) json_response(['error' => "Machine id=$machine_id not found"], 404);

    $sql = 'INSERT INTO production_entries (machine_id, start_time, end_time, machine_name, vfj_no, ip_address, control_type, control_details, control_model, product_target)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON DUPLICATE KEY UPDATE product_target=VALUES(product_target), machine_name=VALUES(machine_name), vfj_no=VALUES(vfj_no), ip_address=VALUES(ip_address), control_type=VALUES(control_type), control_details=VALUES(control_details), control_model=VALUES(control_model)';
    $s = $db->prepare($sql);
    $s->bind_param('issssssssi', $machine_id, $start_time, $end_time, $m['oem_name'], $m['vfj_no'], $m['ip_address'], $m['control_type'], $m['control_details'], $m['control_model'], $product_target);
    $s->execute(); $s->close();
    json_response(['success' => true, 'message' => 'Target saved/updated']);
}

// POST /api/production/entries/update-quality
if ($method === 'POST' && str_ends_with($path, '/update-quality')) {
    $data       = json_decode(file_get_contents('php://input'), true) ?? [];
    $entry_id   = (int)($data['id'] ?? 0);
    if ($entry_id <= 0) json_response(['error' => 'id is required and must be > 0'], 400);
    if (!isset($data['good_products'], $data['bad_products'])) json_response(['error' => 'good_products and bad_products are required'], 400);

    $good = max(0, (int)$data['good_products']);
    $bad  = max(0, (int)$data['bad_products']);
    $prod_done = isset($data['production_done']) ? max(0, (int)$data['production_done']) : $good + $bad;

    if ($prod_done !== $good + $bad) json_response(['status' => false, 'message' => 'production done and good, bad products count mismatch'], 400);

    $s = $db->prepare('SELECT id, product_target FROM production_entries WHERE id = ? LIMIT 1');
    $s->bind_param('i', $entry_id); $s->execute();
    $row = $s->get_result()->fetch_assoc(); $s->close();
    if (!$row) json_response(['success' => false, 'message' => "No production entry with id=$entry_id"], 404);

    $target = (int)($row['product_target'] ?? 0);
    $diff   = $prod_done - $target;
    $dev    = $diff > 0 ? ['overproduction' => $diff] : ($diff < 0 ? ['shortfall' => abs($diff)] : ['on_target' => 0]);
    $dev_text = json_encode($dev, JSON_UNESCAPED_UNICODE);

    $s = $db->prepare('UPDATE production_entries SET good_products=?, bad_products=?, production_done=?, deviation=? WHERE id=?');
    $s->bind_param('iiisi', $good, $bad, $prod_done, $dev_text, $entry_id); $s->execute(); $s->close();

    $s = $db->prepare('SELECT * FROM production_entries WHERE id = ?');
    $s->bind_param('i', $entry_id); $s->execute();
    $updated = $s->get_result()->fetch_assoc(); $s->close();

    json_response(['success' => true, 'message' => 'Quality counts updated', 'entry' => $updated]);
}

// GET /api/production/entries
if ($method === 'GET') {
    $machine_id  = $_GET['machine_id']    ?? null;
    $from_dt     = $_GET['from_datetime'] ?? null;
    $to_dt       = $_GET['to_datetime']   ?? null;
    $for_date    = $_GET['for_date']      ?? null;
    $export_type = strtolower($_GET['export'] ?? '');
    $limit       = min(max(1, (int)($_GET['limit'] ?? 100)), 5000);
    $page        = max(1, (int)($_GET['page'] ?? 1));
    $offset      = ($page - 1) * $limit;

    $date_info    = $for_date ? "$for_date 00:00:00 to $for_date 23:59:59" : (($from_dt ?? '(any)') . ' to ' . ($to_dt ?? '(any)'));
    $machine_info = $machine_id ? "Machine $machine_id" : 'All Machines';

    $where = ['1=1']; $types = ''; $values = [];
    if ($machine_id) { $where[] = 'machine_id = ?'; $types .= 'i'; $values[] = (int)$machine_id; }
    if ($for_date) {
        $where[] = 'start_time >= ?'; $types .= 's'; $values[] = "$for_date 00:00:00";
        $where[] = 'end_time <= ?';   $types .= 's'; $values[] = "$for_date 23:59:59";
    } else {
        if ($from_dt) { $where[] = 'start_time >= ?'; $types .= 's'; $values[] = $from_dt; }
        if ($to_dt)   { $where[] = 'end_time <= ?';   $types .= 's'; $values[] = $to_dt; }
    }
    $where_sql = implode(' AND ', $where);

    // parts map
    $mc_clause = $machine_id ? 'mp.machine_id = ?' : '1=1';
    $parts_sql = "SELECT mp.machine_id, COUNT(*) AS pass_parts FROM machine_production mp
        WHERE $mc_clause AND TIME_TO_SEC(mp.total_cycle_time) > 0 AND LOWER(TRIM(mp.results)) = 'pass'
        AND EXISTS (SELECT 1 FROM production_entries pe WHERE pe.machine_id = mp.machine_id AND pe.start_time IS NOT NULL AND pe.end_time IS NOT NULL AND COALESCE(mp.shift_start, mp.timestamp) >= pe.start_time AND COALESCE(mp.shift_start, mp.timestamp) < pe.end_time)
        GROUP BY mp.machine_id";
    $ps = $db->prepare($parts_sql);
    if ($machine_id) { $pt = 'i'; $pv = [(int)$machine_id]; $ps->bind_param($pt, ...$pv); }
    $ps->execute();
    $parts_map = [];
    foreach ($ps->get_result()->fetch_all(MYSQLI_ASSOC) as $r) $parts_map[(string)$r['machine_id']] = (int)$r['pass_parts'];
    $ps->close();

    $fmt = fn($x) => $x;

    if ($export_type === 'csv' || $export_type === 'pdf') {
        $s = $db->prepare("SELECT * FROM production_entries WHERE $where_sql ORDER BY start_time DESC, id DESC");
        if ($types) $s->bind_param($types, ...$values);
        $s->execute(); $rows = $s->get_result()->fetch_all(MYSQLI_ASSOC); $s->close();
        $entries = array_map(fn($r) => array_merge($r, ['production_done' => $parts_map[(string)$r['machine_id']] ?? 0, 'deviation' => $r['deviation'] ? json_decode($r['deviation'], true) : null]), $rows);
        if ($export_type === 'csv') csv_response($entries, 'production_entries_' . date('Ymd_His') . '.csv', 'Production Entries', $date_info, $machine_info);
        pdf_response($entries, 'Production Entries', 'production_entries_' . date('Ymd_His') . '.pdf', $date_info, $machine_info);
    }

    $cs = $db->prepare("SELECT COUNT(*) AS total FROM production_entries WHERE $where_sql");
    if ($types) $cs->bind_param($types, ...$values);
    $cs->execute(); $total = (int)$cs->get_result()->fetch_assoc()['total']; $cs->close();

    $ls = $db->prepare("SELECT * FROM production_entries WHERE $where_sql ORDER BY start_time DESC, id DESC LIMIT ? OFFSET ?");
    $lt = $types . 'ii'; $lv = array_merge($values, [$limit, $offset]);
    $ls->bind_param($lt, ...$lv); $ls->execute();
    $rows = $ls->get_result()->fetch_all(MYSQLI_ASSOC); $ls->close();

    $entries = array_map(fn($r) => array_merge($r, [
        'production_done' => $parts_map[(string)$r['machine_id']] ?? 0,
        'deviation'       => $r['deviation'] ? json_decode($r['deviation'], true) : null,
    ]), $rows);

    json_response(['success' => true, 'count' => count($entries), 'page' => $page, 'limit' => $limit, 'total' => $total, 'entries' => $entries]);
}

json_response(['error' => 'Not found'], 404);
