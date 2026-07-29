<?php
// index.php  — Front controller / router

require_once __DIR__ . '/config/db.php';
require_once __DIR__ . '/config/helpers.php';

set_cors();
header('Content-Type: application/json');

$method = $_SERVER['REQUEST_METHOD'];
$uri    = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
// Strip base path if running in a sub-folder
$base = rtrim(dirname($_SERVER['SCRIPT_NAME']), '/');
$path = '/' . ltrim(substr($uri, strlen($base)), '/');

// ── Route table ──────────────────────────────────────────────────────────────
// [METHOD, regex, file]
$routes = [
    ['POST',   '#^/login$#',                                          'api/auth.php'],
    ['POST',   '#^/create_user$#',                                    'api/users.php'],
    ['GET',    '#^/users$#',                                          'api/users.php'],
    ['GET',    '#^/users/me/reset_password$#',                        'api/users.php'],  // catch before /<id>
    ['POST',   '#^/users/me/reset_password$#',                        'api/users.php'],
    ['GET',    '#^/users/(\d+)$#',                                    'api/users.php'],
    ['PATCH',  '#^/users/(\d+)$#',                                    'api/users.php'],
    ['DELETE', '#^/users/(\d+)$#',                                    'api/users.php'],

    ['POST',   '#^/add_machine$#',                                    'api/machines.php'],
    ['GET',    '#^/machines$#',                                       'api/machines.php'],
    ['GET',    '#^/machines/(\d+)$#',                                 'api/machines.php'],
    ['PATCH',  '#^/machines/(\d+)$#',                                 'api/machines.php'],
    ['DELETE', '#^/machines/(\d+)$#',                                 'api/machines.php'],
    ['POST',   '#^/machines/(\d+)/restore$#',                         'api/machines.php'],
    ['PUT',    '#^/machines/(\d+)/status$#',                          'api/machines.php'],

    ['POST',   '#^/api/machine_data$#',                               'api/machine_data_insert.php'],
    ['GET',    '#^/machine_data/(\d+)$#',                             'api/machine_data_get.php'],
    ['GET',    '#^/api/machines/live-status$#',                       'api/live_status.php'],
    ['GET',    '#^/api/machines/ping-status$#',                       'api/ping_status.php'],

    ['POST',   '#^/add_production$#',                                 'api/production.php'],
    ['GET',    '#^/get_production$#',                                 'api/production.php'],
    ['POST',   '#^/api/machine-production/upload-mpf$#',              'api/mpf.php'],
    ['GET',    '#^/api/machine-production/mpf$#',                     'api/mpf.php'],

    ['POST',   '#^/api/production/target$#',                          'api/production_entries.php'],
    ['GET',    '#^/api/production/entries$#',                         'api/production_entries.php'],
    ['POST',   '#^/api/production/entries/update-quality$#',          'api/production_entries.php'],

    ['GET',    '#^/reports/oee$#',                                    'api/reports.php'],
    ['GET',    '#^/reports/production$#',                             'api/reports.php'],
    ['GET',    '#^/reports/downtime$#',                               'api/reports.php'],
    ['GET',    '#^/reports/energy$#',                                 'api/reports.php'],
    ['GET',    '#^/reports/breakdowns$#',                             'api/reports.php'],

    ['GET',    '#^/metrics/mtbf-mttr$#',                              'api/mtbf_mttr.php'],
    ['GET',    '#^/api/oee/calculate$#',                              'api/oee_calculate.php'],

    ['GET',    '#^/api/alarms$#',                                     'api/alerts.php'],
    ['GET',    '#^/api/warnings$#',                                   'api/alerts.php'],
    ['GET',    '#^/api/alerts$#',                                     'api/alerts.php'],

    ['GET',    '#^/health$#',                                         'api/health.php'],
];

foreach ($routes as [$rm, $pattern, $file]) {
    if ($rm !== $method && !($rm === 'GET' && $method === 'HEAD')) continue;
    if (preg_match($pattern, $path, $matches)) {
        // expose captured groups as $url_params
        $GLOBALS['url_params'] = array_slice($matches, 1);
        $GLOBALS['route_path'] = $path;
        require __DIR__ . '/' . $file;
        exit;
    }
}

json_response(['error' => 'Not found', 'path' => $path], 404);
