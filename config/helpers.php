<?php
// config/helpers.php

define('JWT_SECRET', '2J8cdKgm4cB4gzuZ-mPD5WUUOp5fTZrIHLTXuY9gnxw=');
define('UPLOAD_FOLDER', __DIR__ . '/../uploads/mpf');
define('MPF_BASE', __DIR__ . '/../uploads/mpf');
define('MAX_RETURN_BYTES', 2000000);
define('ALLOWED_EXTS', ['.mpf', '.txt', '.nc', '.tap']);

// ---------- JWT ----------
function jwt_encode(array $payload): string {
    $header  = base64url_encode(json_encode(['alg'=>'HS256','typ'=>'JWT']));
    $payload = base64url_encode(json_encode($payload));
    $sig     = base64url_encode(hash_hmac('sha256', "$header.$payload", JWT_SECRET, true));
    return "$header.$payload.$sig";
}

function jwt_decode(string $token): ?array {
    $parts = explode('.', $token);
    if (count($parts) !== 3) return null;
    [$header, $payload, $sig] = $parts;
    $expected = base64url_encode(hash_hmac('sha256', "$header.$payload", JWT_SECRET, true));
    if (!hash_equals($expected, $sig)) return null;
    $data = json_decode(base64url_decode($payload), true);
    if (!$data || (isset($data['exp']) && $data['exp'] < time())) return null;
    return $data;
}

function base64url_encode(string $data): string {
    return rtrim(strtr(base64_encode($data), '+/', '-_'), '=');
}
function base64url_decode(string $data): string {
    return base64_decode(strtr($data, '-_', '+/') . str_repeat('=', (4 - strlen($data) % 4) % 4));
}

// ---------- Auth middleware ----------
// function require_auth(): string {
//     $auth = $_SERVER['HTTP_AUTHORIZATION'] ?? '';
//     if (!$auth || !str_starts_with($auth, 'Bearer ')) {
//         json_response(['message' => 'Token is missing'], 401);
//     }
//     $token = substr($auth, 7);
//     $data  = jwt_decode($token);
//     if (!$data || empty($data['sub'])) {
//         json_response(['message' => 'Token is invalid'], 401);
//     }
//     return $data['sub'];
// }

function require_auth(): string {
    $auth = '';

    if (!empty($_SERVER['HTTP_AUTHORIZATION'])) {
        $auth = trim($_SERVER['HTTP_AUTHORIZATION']);
    } elseif (!empty($_SERVER['REDIRECT_HTTP_AUTHORIZATION'])) {
        $auth = trim($_SERVER['REDIRECT_HTTP_AUTHORIZATION']);
    } elseif (function_exists('getallheaders')) {
        $headers = getallheaders();
        foreach ($headers as $key => $value) {
            if (strtolower($key) === 'authorization') {
                $auth = trim($value);
                break;
            }
        }
    }

    if (empty($auth) || stripos($auth, 'Bearer ') !== 0) {
        json_response(['message' => 'Token is missing'], 401);
    }

    $token = trim(substr($auth, 7));
    if ($token === '') {
        json_response(['message' => 'Token is missing'], 401);
    }

    $data = jwt_decode($token);

    if (!$data || empty($data['sub'])) {
        json_response(['message' => 'Token is invalid'], 401);
    }

    return $data['sub'];
}

// ---------- Response ----------
function json_response(mixed $data, int $code = 200): never {
    http_response_code($code);
    header('Content-Type: application/json');
    echo json_encode($data, JSON_UNESCAPED_UNICODE);
    exit;
}

// ---------- Type helpers ----------
function as_int(mixed $v): ?int {
    if ($v === null || $v === '') return null;
    return is_numeric($v) ? (int)$v : null;
}
function as_float(mixed $v): ?float {
    if ($v === null || $v === '') return null;
    return is_numeric($v) ? (float)$v : null;
}
function as_time(mixed $v): ?string {
    if ($v === null || $v === '') return null;
    $s = trim((string)$v);
    $parts = explode(':', $s);
    return count($parts) === 3 ? $s : null;
}
function as_json_text(mixed $v): ?string {
    if ($v === null) return null;
    if (is_array($v)) return json_encode($v, JSON_UNESCAPED_UNICODE);
    return (string)$v;
}

// ---------- Password ----------
function hash_password(string $plain): string {
    return password_hash($plain, PASSWORD_BCRYPT);
}
function verify_password(string $plain, string $hash): bool {
    // support werkzeug pbkdf2:sha256 hashes stored from Python
    if (str_starts_with($hash, 'pbkdf2:sha256:')) {
        $parts = explode('$', $hash);
        // format: pbkdf2:sha256:iterations$salt$hash
        if (count($parts) === 3) {
            [, $salt, $stored] = $parts;
            $meta = explode(':', str_replace('pbkdf2:sha256:', '', explode('$', $hash)[0]));
            $iterations = (int)($meta[0] ?? 260000);
            $derived = hash_pbkdf2('sha256', $plain, $salt, $iterations, 0, true);
            return hash_equals($stored, base64_encode($derived));
        }
    }
    return password_verify($plain, $hash);
}

// ---------- File helpers ----------
function allowed_file(string $filename): bool {
    $ext = strtolower(pathinfo($filename, PATHINFO_EXTENSION));
    return in_array('.' . $ext, ALLOWED_EXTS);
}

function secure_filename(string $name): string {
    $name = basename($name);
    $name = preg_replace('/[^a-zA-Z0-9._\-]/', '_', $name);
    return $name ?: 'file';
}

function is_allowed_path(string $rel_path): ?string {
    if (!$rel_path) return null;
    $base    = realpath(MPF_BASE);
    $abs     = realpath(__DIR__ . '/../' . ltrim($rel_path, '/\\'));
    if (!$abs || !$base) return null;
    if (!str_starts_with($abs, $base)) return null;
    $ext = strtolower(pathinfo($abs, PATHINFO_EXTENSION));
    if (!in_array('.' . $ext, ALLOWED_EXTS)) return null;
    return $abs;
}

// ---------- Axis filter ----------
function filter_axis_positions(string $s): string {
    if (!$s) return $s;
    $kept = [];
    foreach (preg_split('/\s*,\s*/', trim($s)) as $p) {
        if (preg_match('/\s*([A-Za-z]+)\s*:\s*(-?\d+(?:\.\d+)?)\s*$/', $p, $m)) {
            if (abs((float)$m[2]) > 1e-6) $kept[] = "{$m[1]}: " . number_format((float)$m[2], 3, '.', '');
        }
    }
    return implode(', ', $kept);
}

// ---------- Date info builder ----------
function build_date_info(?string $from_datetime, ?string $to_datetime, ?string $from_date, ?string $to_date): string {
    if ($from_datetime && $to_datetime) return "$from_datetime to $to_datetime";
    if ($from_date && $to_date)         return "$from_date to $to_date";
    if ($from_date)                     return "From $from_date";
    if ($to_date)                       return "Until $to_date";
    return 'Today (' . date('Y-m-d') . ')';
}

// ---------- HH:MM:SS formatter ----------
function hms(int $seconds): string {
    $h = intdiv($seconds, 3600);
    $m = intdiv($seconds % 3600, 60);
    $s = $seconds % 60;
    return sprintf('%02d:%02d:%02d', $h, $m, $s);
}

// ---------- Readable duration ----------
function fmt_hms(?float $total_seconds): ?string {
    if ($total_seconds === null) return null;
    $secs = (int)round($total_seconds);
    $h = intdiv($secs, 3600); $rem = $secs % 3600;
    $m = intdiv($rem, 60);    $s   = $rem % 60;
    $parts = [];
    if ($h) $parts[] = "$h hour" . ($h !== 1 ? 's' : '');
    if ($m) $parts[] = "$m min";
    if ($s || !$parts) $parts[] = "$s sec";
    return implode(' ', $parts);
}

// ---------- CORS ----------
function set_cors(): void {
    header('Access-Control-Allow-Origin: *');
    header('Access-Control-Allow-Methods: GET, POST, PATCH, PUT, DELETE, OPTIONS');
    header('Access-Control-Allow-Headers: Content-Type, Authorization');
    if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') { http_response_code(204); exit; }
}

// ---------- CSV export ----------
function csv_response(array $data, string $filename, string $title, string $date_info = '', string $machine_info = 'All Machines'): never {
    header('Content-Type: text/csv');
    header("Content-Disposition: attachment; filename=\"$filename\"");
    $out = fopen('php://output', 'w');
    fputcsv($out, [$title]);
    fputcsv($out, ['Generated on: ' . date('Y-m-d H:i:s')]);
    if ($date_info) fputcsv($out, ["Date Range: $date_info"]);
    fputcsv($out, ["Machine Filter: $machine_info"]);
    fputcsv($out, ['Total Records: ' . count($data) . ' records found']);
    fputcsv($out, []);
    if ($data) {
        $keys = array_keys($data[0]);
        fputcsv($out, array_map(fn($k) => ucwords(str_replace('_', ' ', $k)), $keys));
        foreach ($data as $row) fputcsv($out, array_map(fn($k) => $row[$k] ?? '', $keys));
    }
    fclose($out);
    exit;
}

// ---------- PDF export (simple HTML→text fallback, no ReportLab) ----------
// We use a plain-text table approach since PHP doesn't have ReportLab.
// For real PDF, install TCPDF: composer require tecnickcom/tcpdf
function pdf_response(array $data, string $title, string $filename, string $date_info = '', string $machine_info = 'All Machines'): never {
    // Check if TCPDF is available
    $tcpdf_path = __DIR__ . '/../vendor/autoload.php';
    if (file_exists($tcpdf_path)) {
        require_once $tcpdf_path;
        $pdf = new TCPDF('L', 'mm', 'A4', true, 'UTF-8');
        $pdf->SetCreator('MachineWin');
        $pdf->SetTitle($title);
        $pdf->AddPage();
        $pdf->SetFont('helvetica', 'B', 14);
        $pdf->Cell(0, 10, $title, 0, 1, 'C');
        $pdf->SetFont('helvetica', '', 9);
        $pdf->Cell(0, 6, 'Generated: ' . date('Y-m-d H:i:s'), 0, 1);
        if ($date_info) $pdf->Cell(0, 6, "Date Range: $date_info", 0, 1);
        $pdf->Cell(0, 6, "Machine: $machine_info", 0, 1);
        $pdf->Cell(0, 6, 'Records: ' . count($data), 0, 1);
        $pdf->Ln(4);
        if ($data) {
            $keys = array_keys($data[0]);
            $w    = 270 / count($keys);
            $pdf->SetFont('helvetica', 'B', 8);
            foreach ($keys as $k) $pdf->Cell($w, 7, ucwords(str_replace('_', ' ', $k)), 1, 0, 'C');
            $pdf->Ln();
            $pdf->SetFont('helvetica', '', 7);
            foreach ($data as $row) {
                foreach ($keys as $k) $pdf->Cell($w, 6, (string)($row[$k] ?? ''), 1);
                $pdf->Ln();
            }
        }
        header('Content-Type: application/pdf');
        header("Content-Disposition: attachment; filename=\"$filename\"");
        echo $pdf->Output($filename, 'S');
        exit;
    }
    // Fallback: return CSV with .pdf name (inform user to install TCPDF)
    csv_response($data, str_replace('.pdf', '.csv', $filename), $title, $date_info, $machine_info);
}
