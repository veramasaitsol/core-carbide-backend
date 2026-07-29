<?php
// api/mpf.php  — POST /api/machine-production/upload-mpf  |  GET /api/machine-production/mpf

$method = $_SERVER['REQUEST_METHOD'];
$db     = get_db();

// POST upload
if ($method === 'POST') {
    $mp_id = $_POST['id'] ?? $_GET['id'] ?? null;
    if (!$mp_id) json_response(['error' => 'id is required'], 400);
    if (empty($_FILES['file']['name'])) json_response(['error' => 'file is required'], 400);

    $file = $_FILES['file'];
    if (!allowed_file($file['name'])) json_response(['error' => 'Invalid file type. Allowed: .mpf, .nc, .tap, .txt'], 400);

    $filename = secure_filename($file['name']);
    $dest_dir = UPLOAD_FOLDER;
    if (!is_dir($dest_dir)) mkdir($dest_dir, 0755, true);

    $abs_path  = $dest_dir . DIRECTORY_SEPARATOR . $filename;
    $saved_new = false;
    if (!file_exists($abs_path)) {
        move_uploaded_file($file['tmp_name'], $abs_path);
        $saved_new = true;
    }

    // relative path from project root
    $rel_path = 'uploads/mpf/' . $filename;

    $s = $db->prepare('UPDATE machine_production SET mpf_path = ? WHERE id = ?');
    $s->bind_param('ss', $rel_path, $mp_id);
    $s->execute();
    if ($s->affected_rows === 0) json_response(['error' => "No row with id=$mp_id"], 404);
    $s->close();

    json_response(['success' => true, 'id' => (string)$mp_id, 'mpf_path' => $rel_path, 'saved_new' => $saved_new]);
}

// GET read
if ($method === 'GET') {
    $mpf_path = trim($_GET['mpf_path'] ?? '');
    $abs_path = is_allowed_path($mpf_path);
    if (!$abs_path) json_response(['error' => 'Invalid or disallowed mpf_path'], 400);
    if (!file_exists($abs_path)) json_response(['error' => 'File not found', 'mpf_path' => $mpf_path], 404);

    $size = filesize($abs_path);
    if ($size > MAX_RETURN_BYTES) json_response(['error' => 'File too large to return as JSON', 'mpf_path' => $mpf_path, 'size_bytes' => $size, 'max_return_bytes' => MAX_RETURN_BYTES], 413);

    $raw = file_get_contents($abs_path);
    if (mb_detect_encoding($raw, 'UTF-8', true)) {
        $text = $raw; $encoding = 'utf-8';
    } else {
        $text = mb_convert_encoding($raw, 'UTF-8', 'ISO-8859-1'); $encoding = 'latin-1';
    }

    $normalized = str_replace(["\r\n", "\r"], "\n", $text);
    $lines      = explode("\n", $normalized);

    json_response([
        'success'    => true,
        'mpf_path'   => $mpf_path,
        'filename'   => basename($abs_path),
        'size_bytes' => $size,
        'encoding'   => $encoding,
        'line_count' => count($lines),
        'content'    => $normalized,
        'lines'      => $lines,
    ]);
}

json_response(['error' => 'Not found'], 404);
