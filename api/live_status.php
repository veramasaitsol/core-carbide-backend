<?php
// api/live_status.php  — GET /api/machines/live-status

$db  = get_db();
$sql = "SELECT m.id AS machine_id, m.oem_name, m.control_type, m.control_details, m.vfj_no,
  md.machine_state, md.cycle_time, md.total_production AS part_count, md.spindle_load,
  md.timestamp AS last_updated, TIMESTAMPDIFF(SECOND, md.timestamp, NOW()) AS seconds_since_update
FROM machines m
LEFT JOIN (
  SELECT machine_id, machine_state, cycle_time, total_production, spindle_load, timestamp,
    ROW_NUMBER() OVER (PARTITION BY machine_id ORDER BY timestamp DESC, id DESC) AS rn
  FROM machine_data
) md ON m.id = md.machine_id AND md.rn = 1
ORDER BY m.id";

$rows    = $db->query($sql)->fetch_all(MYSQLI_ASSOC);
$result  = [];
$server_time = date('c');

foreach ($rows as $row) {
    $mid = $row['machine_id'];
    $s   = $db->prepare("SELECT COUNT(*) AS parts_produced FROM machine_production WHERE machine_id = ? AND total_cycle_time != '00:00:00' AND results = 'PASS' AND DATE(timestamp) = CURDATE()");
    $s->bind_param('i', $mid); $s->execute();
    $real_part_count = (int)($s->get_result()->fetch_assoc()['parts_produced'] ?? 0);
    $s->close();

    $result[] = [
        'machine_id'          => $mid,
        'machine_name'        => $row['oem_name'],
        'control_type'        => $row['control_type'],
        'control_details'     => $row['control_details'],
        'vfj_no'              => $row['vfj_no'],
        'machine_state'       => $row['machine_state'],
        'cycle_time'          => $row['cycle_time'],
        'part_count'          => $real_part_count,
        'spindle_load'        => $row['spindle_load'],
        'last_updated'        => $row['last_updated'],
        'server_time'         => $server_time,
        'seconds_since_update'=> $row['seconds_since_update'],
    ];
}

json_response(['success' => true, 'count' => count($result), 'server_timestamp' => $server_time, 'machines' => $result]);
