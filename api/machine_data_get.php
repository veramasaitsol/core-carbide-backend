    <?php
    // api/machine_data_get.php  — GET /machine_data/{machine_id}

    $params     = $GLOBALS['url_params'];
    $machine_id = (int)($params[0] ?? 0);
    $start_time = $_GET['start_time'] ?? null;
    $end_time   = $_GET['end_time']   ?? null;

    $db = get_db();

    $s = $db->prepare('SELECT id FROM machines WHERE id = ?');
    $s->bind_param('i', $machine_id); $s->execute();
    if (!$s->get_result()->fetch_assoc()) json_response(['message' => 'Machine not found'], 404);
    $s->close();

    $sql = 'SELECT md.*, ed1.voltage1, ed1.voltage2, ed1.voltage3, ed1.current1, ed1.current2, ed1.current3,
    ed1.power_factor1, ed1.power_factor2, ed1.power_factor3,
    COALESCE(ed1.servo_load, md.servo_load) AS servo_load,
    COALESCE(ed1.servo_temperature, md.servo_temperature) AS servo_temperature
    FROM machine_data md
    LEFT JOIN energy_data ed1 ON ed1.machine_id = md.machine_id
    AND ed1.timestamp = (SELECT MAX(ed2.timestamp) FROM energy_data ed2 WHERE ed2.machine_id = md.machine_id AND ed2.timestamp <= md.timestamp)
    WHERE md.machine_id = ?';

    $types  = 'i';
    $values = [$machine_id];

    if ($start_time) { $sql .= ' AND md.timestamp >= ?'; $types .= 's'; $values[] = $start_time; }
    if ($end_time)   { $sql .= ' AND md.timestamp <= ?'; $types .= 's'; $values[] = $end_time; }
    $sql .= ' ORDER BY md.timestamp DESC';
    if (!$start_time && !$end_time) $sql .= ' LIMIT 1';

    $s = $db->prepare($sql);
    $s->bind_param($types, ...$values);
    $s->execute();
    $rows = $s->get_result()->fetch_all(MYSQLI_ASSOC);
    $s->close();

    if (!$rows) json_response(['message' => 'No data found'], 404);

    // Real part count today
    $s = $db->prepare("SELECT COUNT(*) AS parts_produced FROM machine_production WHERE machine_id = ? AND total_cycle_time != '00:00:00' AND DATE(timestamp) = CURDATE() AND results = 'PASS'");
    $s->bind_param('i', $machine_id); $s->execute();
    $real_part_count = (int)($s->get_result()->fetch_assoc()['parts_produced'] ?? 0);
    $s->close();

    // Machine constants
    $consts_map = [
        1  => ['P_IDLE_KW' => 1.2, 'P_SP_RATED_KW' => 11.0, 'K_SERVO_KW_PER_PCT' => 0.010, 'ENC_K_OFFSET_C' => 7.0],
        15 => ['P_IDLE_KW' => 1.5, 'P_SP_RATED_KW' => 11.0, 'K_SERVO_KW_PER_PCT' => 0.010, 'ENC_K_OFFSET_C' => 7.0],
    ];
    $consts = $consts_map[$machine_id] ?? ['P_IDLE_KW' => 1.2, 'P_SP_RATED_KW' => 11.0, 'K_SERVO_KW_PER_PCT' => 0.010, 'ENC_K_OFFSET_C' => 7.0];

    foreach ($rows as &$row) {
        // servo temp floor
        $st = is_numeric($row['servo_temperature']) ? (float)$row['servo_temperature'] : null;
        if ($st !== null && $st < 27) $row['servo_temperature'] = 27.0;

        // timedelta columns (returned as string HH:MM:SS by mysqli — already fine)
        $row['part_count']                = $real_part_count;
        $row['original_total_production'] = $row['total_production'];
        $row['axis_positions']            = filter_axis_positions((string)($row['axis_positions'] ?? ''));

        // Feed override calc
        $row['feed_override_calc'] = null;
        $set_feed = is_numeric($row['set_feed_rate']) ? (float)$row['set_feed_rate'] : null;
        if ($set_feed !== null && $set_feed > 0 && is_numeric($row['actual_feed_rate'])) {
            $actual_feed = (float)$row['actual_feed_rate'];
            if ($set_feed > 1.0) {
                $row['feed_override_calc'] = round(100.0 * $actual_feed / $set_feed, 1);
            } elseif (is_numeric($row['actual_spindle_speed']) && (float)$row['actual_spindle_speed'] > 0) {
                $set_mm_min = (float)$row['actual_spindle_speed'] * $set_feed;
                if ($set_mm_min > 0) $row['feed_override_calc'] = round(100.0 * $actual_feed / $set_mm_min, 1);
            }
        }

        // Speed override calc
        $row['speed_override_calc'] = null;
        $set_sp = is_numeric($row['set_speed']) ? (float)$row['set_speed'] : null;
        if ($set_sp !== null && $set_sp > 0 && is_numeric($row['actual_spindle_speed'])) {
            $row['speed_override_calc'] = round(100.0 * (float)$row['actual_spindle_speed'] / $set_sp, 1);
        }

        // Power / spindle load calc
        $energy_cols = ['voltage1','voltage2','voltage3','current1','current2','current3','power_factor1','power_factor2','power_factor3'];
        $energy_available = false;
        foreach ($energy_cols as $ec) { if ($row[$ec] !== null) { $energy_available = true; break; } }
        $row['p_total_kw']                  = null;
        $row['p_corr_kw']                   = null;
        $row['spindle_load_pct_calc']       = null;
        $row['energy_based_calc_available'] = $energy_available;

        if ($energy_available) {
            $p_tot = ((float)($row['voltage1']??0) * (float)($row['current1']??0) * (float)($row['power_factor1']??0)
                    + (float)($row['voltage2']??0) * (float)($row['current2']??0) * (float)($row['power_factor2']??0)
                    + (float)($row['voltage3']??0) * (float)($row['current3']??0) * (float)($row['power_factor3']??0)) / 1000.0;
            $servo_load_pct = is_numeric($row['servo_load']) ? (float)$row['servo_load'] : null;
            if ($servo_load_pct !== null) {
                $p_corr = max($p_tot - $consts['P_IDLE_KW'] - ($consts['K_SERVO_KW_PER_PCT'] * $servo_load_pct), 0.0);
                $sp_load_pct = $consts['P_SP_RATED_KW'] > 0 ? 100.0 * $p_corr / $consts['P_SP_RATED_KW'] : null;
                $row['p_total_kw'] = round($p_tot, 3);
                $row['p_corr_kw']  = round($p_corr, 3);
                if ($sp_load_pct !== null) $row['spindle_load_pct_calc'] = round(max(0.0, min($sp_load_pct, 200.0)), 1);
            }
        }

        // Encoder temp
        $row['encoder_temp_est_c'] = null;
        if ($st !== null) $row['encoder_temp_est_c'] = round($st - $consts['ENC_K_OFFSET_C'], 1);

        $row['calc_constants_used'] = $consts;
        $row['spindle_temperature'] = $row['spindle_temperature']; // keep as-is (no thermal model in PHP)
    }
    unset($row);

    json_response(!$start_time && !$end_time ? [$rows[0]] : $rows);
