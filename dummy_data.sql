-- Dummy data for machinewin_php database
-- Import this file into the machine_monitoring database using phpMyAdmin, MySQL Workbench, or mysql CLI.

INSERT INTO machines (oem_name, ip_address, operator_ip, port, vfj_no, control_type, control_details, control_model, status)
VALUES ('CNC Lathe A', '192.168.1.100', '192.168.1.150', '502', 'MCH-1001', 'FANUC', '31i-A5', 'FANUC 31i-A5', 'active');

SET @machine_id = LAST_INSERT_ID();

INSERT INTO machine_data (
  machine_id, axis_positions, coolant_status, machine_state, emergency_signal, machine_mode,
  main_program_number, executing_program_number, sequence_number, actual_spindle_speed, actual_feed_rate, set_speed, set_feed_rate,
  feed_override, speed_override, cycle_time, cutting_time, operate_time, power_on_time,
  pulse_coder_temps, servo_current, servo_load, servo_temperature, spindle_load, spindle_temperature,
  current_tool_number, total_production, machine_alarms, cnc_warnings, battery_low_alarm,
  tool_offset_geometry, tool_offset_wear, macro_values
)
VALUES (
  @machine_id,
  'X: 31.000, Y: -12.100, Z: -10.765',
  'OFF',
  'Running',
  0,
  'AUTO',
  'O172',
  '0',
  'N1',
  2000,
  10,
  2000,
  10.0,
  100,
  50,
  '00:05:30',
  '333:42:06',
  '393:41:00',
  '730:17:00',
  '{"X":41,"Y":-12,"Z":35}',
  '{"X":-1.7,"Y":1.3,"Z":9.6}',
  '{"X":3,"Y":4,"Z":28}',
  '{"X":28,"Y":29,"Z":44}',
  0,
  36,
  1,
  182,
  '[]',
  '[]',
  0,
  210.0000,
  2.8800,
  '{"500":9,"501":0,"502":0,"503":0}'
);

INSERT INTO production_entries (
  machine_id, start_time, end_time, machine_name, vfj_no, ip_address,
  control_type, control_details, control_model, product_target, good_products,
  bad_products, production_done, deviation
)
VALUES (
  @machine_id,
  '2026-04-14 00:00:00',
  '2026-04-14 23:59:59',
  'CNC Lathe A',
  'MCH-1001',
  '192.168.1.100',
  'FANUC',
  '31i-A5',
  'FANUC 31i-A5',
  250,
  182,
  0,
  182,
  '{"on_target":0}'
);

-- Optionally add production records for part count calculation if the schema contains shift_start:
-- INSERT INTO machine_production (machine_id, total_cycle_time, results, timestamp, shift_start)
-- VALUES (@machine_id, '00:12:45', 'PASS', '2026-04-14 16:17:53', '2026-04-14 16:00:00');
