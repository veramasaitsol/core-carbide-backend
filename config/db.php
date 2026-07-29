<?php
define('DB_HOST', '127.0.0.1');
define('DB_PORT', 3306);
define('DB_USER', 'root');
define('DB_PASSWORD', '');
define('DB_NAME', 'machine_monitoring');

function get_db(): mysqli {
    static $conn = null;
    if ($conn && $conn->ping()) return $conn;

    // Since PHP 8.1, mysqli throws mysqli_sql_exception on any connection
    // error by default (MYSQLI_REPORT_ERROR | MYSQLI_REPORT_STRICT) instead
    // of just setting ->connect_error. Left uncaught, that exception becomes
    // PHP's raw HTML fatal-error page inside a response every endpoint
    // expects to be JSON — this is the exact "Unexpected token '<'" /
    // blank-page bug seen throughout this session. Catching it once, here,
    // protects every setup_*.php and api file that calls get_db(), instead
    // of needing a try/catch repeated in each one individually.
    try {
        $conn = mysqli_init();
        $conn->options(MYSQLI_OPT_CONNECT_TIMEOUT, 5);
        $conn->real_connect(DB_HOST, DB_USER, DB_PASSWORD, DB_NAME, DB_PORT);
        $conn->set_charset('utf8mb4');
        return $conn;
    } catch (\mysqli_sql_exception $e) {
        http_response_code(500);
        header('Content-Type: application/json');
        die(json_encode(['error' => 'Database connection failed: ' . $e->getMessage()]));
    }
}