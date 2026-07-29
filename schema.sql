-- Database schema for MachineWin PHP backend
-- Run this file after creating the machine_monitoring database.

CREATE DATABASE IF NOT EXISTS `machine_monitoring` CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
USE `machine_monitoring`;

DROP TABLE IF EXISTS `energy_data`;
CREATE TABLE `energy_data` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `machine_id` INT UNSIGNED NOT NULL,
  `timestamp` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `voltage1` DECIMAL(8,3) DEFAULT NULL,
  `voltage2` DECIMAL(8,3) DEFAULT NULL,
  `voltage3` DECIMAL(8,3) DEFAULT NULL,
  `current1` DECIMAL(8,3) DEFAULT NULL,
  `current2` DECIMAL(8,3) DEFAULT NULL,
  `current3` DECIMAL(8,3) DEFAULT NULL,
  `power_factor1` DECIMAL(5,3) DEFAULT NULL,
  `power_factor2` DECIMAL(5,3) DEFAULT NULL,
  `power_factor3` DECIMAL(5,3) DEFAULT NULL,
  `servo_load` INT DEFAULT NULL,
  `servo_temperature` DECIMAL(6,2) DEFAULT NULL,
  PRIMARY KEY (`id`),
  INDEX `idx_energy_machine_ts` (`machine_id`, `timestamp`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

DROP TABLE IF EXISTS `downtime_entries`;
CREATE TABLE `downtime_entries` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `machine_id` INT UNSIGNED NOT NULL,
  `reason` TEXT DEFAULT NULL,
  `start_time` DATETIME DEFAULT NULL,
  `end_time` DATETIME DEFAULT NULL,
  `timestamp` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  INDEX `idx_downtime_machine` (`machine_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

DROP TABLE IF EXISTS `machine_data`;
CREATE TABLE `machine_data` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `machine_id` INT UNSIGNED NOT NULL,
  `axis_positions` TEXT DEFAULT NULL,
  `coolant_status` VARCHAR(64) DEFAULT NULL,
  `machine_state` VARCHAR(64) DEFAULT NULL,
  `emergency_signal` INT DEFAULT NULL,
  `machine_mode` VARCHAR(64) DEFAULT NULL,
  `main_program_number` VARCHAR(128) DEFAULT NULL,
  `executing_program_number` VARCHAR(128) DEFAULT NULL,
  `sequence_number` VARCHAR(128) DEFAULT NULL,
  `actual_spindle_speed` INT DEFAULT NULL,
  `actual_feed_rate` INT DEFAULT NULL,
  `set_speed` INT DEFAULT NULL,
  `set_feed_rate` DOUBLE DEFAULT NULL,
  `feed_override` INT DEFAULT NULL,
  `speed_override` INT DEFAULT NULL,
  `cycle_time` TIME DEFAULT NULL,
  `cutting_time` TIME DEFAULT NULL,
  `operate_time` TIME DEFAULT NULL,
  `power_on_time` TIME DEFAULT NULL,
  `pulse_coder_temps` JSON DEFAULT NULL,
  `servo_current` JSON DEFAULT NULL,
  `servo_load` JSON DEFAULT NULL,
  `servo_temperature` JSON DEFAULT NULL,
  `spindle_load` INT DEFAULT NULL,
  `spindle_temperature` INT DEFAULT NULL,
  `current_tool_number` INT DEFAULT NULL,
  `total_production` INT DEFAULT NULL,
  `machine_alarms` JSON DEFAULT NULL,
  `cnc_warnings` JSON DEFAULT NULL,
  `battery_low_alarm` INT DEFAULT NULL,
  `tool_offset_geometry` DOUBLE DEFAULT NULL,
  `tool_offset_wear` DOUBLE DEFAULT NULL,
  `macro_values` JSON DEFAULT NULL,
  `timestamp` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  INDEX `idx_machine_data_machine_ts` (`machine_id`, `timestamp`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

DROP TABLE IF EXISTS `machine_production`;
CREATE TABLE `machine_production` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `machine_id` INT UNSIGNED NOT NULL,
  `shift_operator_name` VARCHAR(128) DEFAULT NULL,
  `operator_id` VARCHAR(64) DEFAULT NULL,
  `shift_type` VARCHAR(64) DEFAULT NULL,
  `job_order_no` VARCHAR(64) DEFAULT NULL,
  `batch_quantity` INT DEFAULT NULL,
  `checklist` TEXT DEFAULT NULL,
  `machine_name` VARCHAR(128) DEFAULT NULL,
  `machine_no` VARCHAR(64) DEFAULT NULL,
  `product_component_name` VARCHAR(128) DEFAULT NULL,
  `product_component_no` VARCHAR(64) DEFAULT NULL,
  `section_code_name` VARCHAR(128) DEFAULT NULL,
  `shift_production_details` TEXT DEFAULT NULL,
  `machine_status` VARCHAR(64) DEFAULT NULL,
  `results` VARCHAR(32) DEFAULT NULL,
  `total_cycle_time` TIME DEFAULT NULL,
  `shift_start` DATETIME DEFAULT NULL,
  `shift_end` DATETIME DEFAULT NULL,
  `mpf_path` VARCHAR(255) DEFAULT NULL,
  `timestamp` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  INDEX `idx_production_machine_ts` (`machine_id`, `timestamp`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

DROP TABLE IF EXISTS `production_entries`;
CREATE TABLE `production_entries` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `machine_id` INT UNSIGNED NOT NULL,
  `start_time` DATETIME NOT NULL,
  `end_time` DATETIME NOT NULL,
  `machine_name` VARCHAR(255) DEFAULT NULL,
  `vfj_no` VARCHAR(100) DEFAULT NULL,
  `ip_address` VARCHAR(50) DEFAULT NULL,
  `control_type` VARCHAR(100) DEFAULT NULL,
  `control_details` VARCHAR(255) DEFAULT NULL,
  `control_model` VARCHAR(255) DEFAULT NULL,
  `product_target` INT DEFAULT NULL,
  `good_products` INT DEFAULT 0,
  `bad_products` INT DEFAULT 0,
  `production_done` INT DEFAULT 0,
  `deviation` JSON DEFAULT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_production_machine_period` (`machine_id`, `start_time`, `end_time`),
  INDEX `idx_production_machine` (`machine_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

DROP TABLE IF EXISTS `machines`;
CREATE TABLE `machines` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `oem_name` VARCHAR(255) NOT NULL,
  `ip_address` VARCHAR(50) DEFAULT NULL,
  `operator_ip` VARCHAR(50) DEFAULT NULL,
  `port` VARCHAR(16) DEFAULT NULL,
  `vfj_no` VARCHAR(100) DEFAULT NULL,
  `control_type` VARCHAR(100) DEFAULT NULL,
  `control_details` VARCHAR(255) DEFAULT NULL,
  `control_model` VARCHAR(255) DEFAULT NULL,
  `status` VARCHAR(32) NOT NULL DEFAULT 'active',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  INDEX `idx_machines_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

DROP TABLE IF EXISTS `user_machines`;
CREATE TABLE `user_machines` (
  `user_id` INT UNSIGNED NOT NULL,
  `machine_id` INT UNSIGNED NOT NULL,
  PRIMARY KEY (`user_id`, `machine_id`),
  INDEX `idx_user_machine` (`machine_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

DROP TABLE IF EXISTS `users`;
CREATE TABLE `users` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `plant` VARCHAR(128) NOT NULL,
  `employee_id` VARCHAR(64) NOT NULL,
  `name` VARCHAR(128) NOT NULL,
  `password_hash` VARCHAR(255) NOT NULL,
  `role` VARCHAR(32) NOT NULL,
  `status` VARCHAR(32) NOT NULL DEFAULT 'active',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_users_employee_id` (`employee_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
