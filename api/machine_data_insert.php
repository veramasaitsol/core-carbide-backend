<?php
// api/machine_data_insert.php  — POST /api/machine_data

$payload    = json_decode(file_get_contents('php://input'), true) ?? [];
$machine_id = as_int($payload['machine_id'] ?? null);
if (!$machine_id) json_response(['success' => false, 'error' => 'machine_id is required'], 400);

// axis_positions — dynamic: works with any axis combination (X,Y,Z,A,B,C,U etc.)
$axis      = $payload['axis_positions'] ?? null;
$axis_text = null;
if (is_array($axis)) {
    $parts = [];
    foreach ($axis as $name => $value) {
        $parts[] = sprintf('%s: %.3f', $name, (float)$value);
    }
    $axis_text = implode(', ', $parts);
} elseif ($axis !== null) {
    $axis_text = (string)$axis;
}

$feed_ov  = $payload['feed_override']  ?? $payload['feed_override_raw']  ?? null;
$speed_ov = $payload['speed_override'] ?? $payload['speed_override_raw'] ?? null;

$sp_load = $payload['spindle_load'] ?? null;
if (is_array($sp_load)) $sp_load = $sp_load['SP0'] ?? null;
$spindle_load = as_int($sp_load);

$alarms         = $payload['machine_alarms'] ?? [];
$machine_alarms = as_json_text($alarms);

$row = [
    'machine_id'               => $machine_id,
    'axis_positions'           => $axis_text,
    'coolant_status'           => $payload['coolant_status'] ?? null,
    'machine_state'            => $payload['machine_state'] ?? null,
    'emergency_signal'         => as_int($payload['emergency_signal'] ?? null),
    'machine_mode'             => $payload['machine_mode'] ?? null,
    'main_program_number'      => $payload['main_program_number'] ?? null,
    'executing_program_number' => $payload['executing_program_number'] ?? null,
    'sequence_number'          => $payload['sequence_number'] ?? null,
    'actual_spindle_speed'     => as_int($payload['actual_spindle_speed'] ?? null),
    'actual_feed_rate'         => as_int($payload['actual_feed_rate'] ?? null),
    'set_speed'                => as_int($payload['set_speed'] ?? null),
    'set_feed_rate'            => as_float($payload['set_feed_rate'] ?? null),
    'feed_override'            => as_int($feed_ov),
    'speed_override'           => as_int($speed_ov),
    'cycle_time'               => as_time($payload['cycle_time'] ?? null),
    'cutting_time'             => as_time($payload['cutting_time'] ?? null),
    'operate_time'             => as_time($payload['operate_time'] ?? null),
    'power_on_time'            => as_time($payload['power_on_time'] ?? null),

    'pulse_coder_temps'        => as_json_text($payload['pulse_coder_temps']   ?? null),
    'servo_current'            => as_json_text($payload['servo_current']        ?? null),
    'servo_temperature'        => as_json_text($payload['servo_temperature']    ?? null),
    'spindle_temperature'      => as_int($payload['spindle_temperature']        ?? null),

    'servo_load'               => as_json_text($payload['servo_load'] ?? null),
    'spindle_load'             => $spindle_load,
    'current_tool_number'      => as_int($payload['current_tool_number'] ?? null),
    'total_production'         => as_int($payload['total_production'] ?? null),
    'machine_alarms'           => $machine_alarms,
    'cnc_warnings'             => as_json_text($payload['cnc_warnings'] ?? null),
    'battery_low_alarm'        => as_int($payload['battery_low_alarm'] ?? null),
    'tool_offset_geometry'     => as_float($payload['tool_offset_geometry'] ?? null),
    'tool_offset_wear'         => as_float($payload['tool_offset_wear'] ?? null),
    'macro_values'             => as_json_text($payload['macro_values'] ?? null),
];

$db = get_db();
$sql = 'INSERT INTO machine_data (machine_id, axis_positions, coolant_status, machine_state, emergency_signal, machine_mode,
  main_program_number, executing_program_number, sequence_number, actual_spindle_speed, actual_feed_rate, set_speed, set_feed_rate,
  feed_override, speed_override, cycle_time, cutting_time, operate_time, power_on_time,
  pulse_coder_temps, servo_current, servo_load, servo_temperature, spindle_load, spindle_temperature,
  current_tool_number, total_production, machine_alarms, cnc_warnings, battery_low_alarm, tool_offset_geometry, tool_offset_wear, macro_values)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)';

$s = $db->prepare($sql);
$s->bind_param('isssississddiiissssssssiiisssidds',
    $row['machine_id'], $row['axis_positions'], $row['coolant_status'], $row['machine_state'],
    $row['emergency_signal'], $row['machine_mode'], $row['main_program_number'],
    $row['executing_program_number'], $row['sequence_number'], $row['actual_spindle_speed'],
    $row['actual_feed_rate'], $row['set_speed'], $row['set_feed_rate'],
    $row['feed_override'], $row['speed_override'],
    $row['cycle_time'], $row['cutting_time'], $row['operate_time'], $row['power_on_time'],
    $row['pulse_coder_temps'], $row['servo_current'], $row['servo_load'], $row['servo_temperature'],
    $row['spindle_load'], $row['spindle_temperature'], $row['current_tool_number'], $row['total_production'],
    $row['machine_alarms'], $row['cnc_warnings'], $row['battery_low_alarm'],
    $row['tool_offset_geometry'], $row['tool_offset_wear'], $row['macro_values']
);

if (!$s->execute()) json_response(['success' => false, 'error' => $s->error], 500);
$new_id = $db->insert_id;
$s->close();
json_response(['success' => true, 'id' => $new_id], 201);