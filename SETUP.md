# MachineWin Backend — Core PHP Setup Guide

## Project Structure
```
machinewin_php/
├── index.php           ← Front controller / router
├── .htaccess           ← URL rewriting rules
├── config/
│   ├── db.php          ← DB connection config
│   └── helpers.php     ← JWT, auth, CSV/PDF, type helpers
├── api/
│   ├── auth.php                ← POST /login
│   ├── users.php               ← CRUD /users, /create_user
│   ├── machines.php            ← CRUD /machines, /add_machine
│   ├── machine_data_insert.php ← POST /api/machine_data
│   ├── machine_data_get.php    ← GET  /machine_data/{id}
│   ├── live_status.php         ← GET  /api/machines/live-status
│   ├── ping_status.php         ← GET  /api/machines/ping-status
│   ├── production.php          ← POST /add_production, GET /get_production
│   ├── mpf.php                 ← Upload & read MPF files
│   ├── production_entries.php  ← Production targets & quality
│   ├── reports.php             ← OEE, Production, Downtime, Energy, Breakdowns
│   ├── mtbf_mttr.php           ← GET  /metrics/mtbf-mttr
│   ├── oee_calculate.php       ← GET  /api/oee/calculate
│   ├── alerts.php              ← GET  /api/alarms, /api/warnings, /api/alerts
│   └── health.php              ← GET  /health
└── uploads/mpf/        ← Uploaded CNC program files
```

---

## Step 1 — Requirements

| Requirement | Version |
|-------------|---------|
| XAMPP       | 8.2+    |
| PHP         | 8.1+    |
| MariaDB     | 10.4+   |
| Apache mod_rewrite | enabled |

---

## Step 2 — Database Setup

### 2a. Start XAMPP
1. Open **XAMPP Control Panel**
2. Start **Apache** and **MySQL**

### 2b. Create the database
Open **phpMyAdmin** → `http://localhost/phpmyadmin`

```sql
CREATE DATABASE machine_monitoring CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
```

### 2c. Import the schema
1. In phpMyAdmin, select `machine_monitoring` database
2. Click **Import** tab
3. Choose the file: `machinewin_php/schema.sql`
4. Click **Go**

### 2d. Create a default admin user
Run this SQL in phpMyAdmin → SQL tab:

```sql
-- Password is: Password@123
INSERT INTO users (plant, employee_id, name, password_hash, role, status)
VALUES (
  'Plant A',
  'admin001',
  'Admin User',
  '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi',
  'admin',
  'active'
);
```

> **Note:** The hash above is bcrypt for `password`. To use a custom password, run this PHP snippet:
> ```php
> echo password_hash('YourPassword', PASSWORD_BCRYPT);
> ```

---

## Step 3 — Configure DB Connection

Edit `config/db.php` and update these values to match your setup:

```php
define('DB_HOST', '127.0.0.1');
define('DB_PORT', 3306);      // Default MySQL port; change to 3307 if needed
define('DB_USER', 'root');
define('DB_PASSWORD', '');    // Your MySQL root password
define('DB_NAME', 'machine_monitoring');
```

> **Port note:** XAMPP default MySQL port is **3306**. The Python project used **3307** (custom). Check your XAMPP MySQL port in `xampp/mysql/bin/my.ini` → `port=`.

---

## Step 4 — Enable mod_rewrite

### 4a. Enable the module
Open `c:\xampp82\apache\conf\httpd.conf` and ensure this line is **uncommented**:
```
LoadModule rewrite_module modules/mod_rewrite.so
```

### 4b. Allow .htaccess overrides
In the same file, find the `<Directory "c:/xampp82/htdocs">` block and set:
```apache
AllowOverride All
```

### 4c. Restart Apache in XAMPP Control Panel

---

## Step 5 — Run the Project

Open your browser:
```
http://localhost/machinewin_php/health
```

Expected response:
```json
{"status":"healthy","timestamp":"...","service":"machine_monitoring_api","database":"connected"}
```

---

## Step 6 — Test the API

### Login
```bash
curl -X POST http://localhost/machinewin_php/login \
  -H "Content-Type: application/json" \
  -d '{"employee_id":"admin001","password":"password"}'
```

Response:
```json
{
  "token": "eyJ...",
  "user": { "id": 1, "role": "admin", ... }
}
```

### Use the token
```bash
curl http://localhost/machinewin_php/machines \
  -H "Authorization: Bearer eyJ..."
```

---

## Step 7 — (Optional) PDF Export with TCPDF

The Python project used ReportLab for PDF. In PHP, install **TCPDF**:

### Option A — Composer (recommended)
```bash
cd c:\xampp82\htdocs\machinewin_php
composer require tecnickcom/tcpdf
```

### Option B — Manual download
1. Download from https://tcpdf.org
2. Extract to `machinewin_php/vendor/tecnickcom/tcpdf/`
3. Create `machinewin_php/vendor/autoload.php`:
```php
<?php
require_once __DIR__ . '/tecnickcom/tcpdf/tcpdf.php';
```

> Without TCPDF, PDF export endpoints automatically fall back to CSV format.

---

## API Endpoints Reference

| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| POST | `/login` | No | Login, get JWT token |
| GET | `/health` | No | Health check |
| POST | `/create_user` | Admin | Create user |
| GET | `/users` | Admin | List all users |
| GET | `/users/{id}` | Admin | Get user |
| PATCH | `/users/{id}` | Admin | Update user |
| DELETE | `/users/{id}` | Admin | Delete user |
| POST | `/users/me/reset_password` | Yes | Change own password |
| POST | `/add_machine` | Admin | Add machine |
| GET | `/machines` | Admin | List machines |
| GET | `/machines/{id}` | Admin | Get machine |
| PATCH | `/machines/{id}` | Admin | Update machine |
| DELETE | `/machines/{id}` | Admin | Soft-delete machine |
| POST | `/machines/{id}/restore` | Admin | Restore machine |
| PUT | `/machines/{id}/status` | Admin | Update status |
| POST | `/api/machine_data` | No | Insert machine sensor data |
| GET | `/machine_data/{id}` | No | Get machine data |
| GET | `/api/machines/live-status` | No | Live dashboard |
| GET | `/api/machines/ping-status` | No | Network ping status |
| POST | `/add_production` | Yes | Add production record |
| GET | `/get_production` | Yes | Get production records |
| POST | `/api/machine-production/upload-mpf` | No | Upload MPF file |
| GET | `/api/machine-production/mpf` | No | Read MPF file |
| POST | `/api/production/target` | Yes | Set production target |
| GET | `/api/production/entries` | Yes | List production entries |
| POST | `/api/production/entries/update-quality` | Yes | Update quality counts |
| GET | `/reports/oee` | Yes | OEE report |
| GET | `/reports/production` | Yes | Production report |
| GET | `/reports/downtime` | Yes | Downtime report |
| GET | `/reports/energy` | Yes | Energy report |
| GET | `/reports/breakdowns` | Yes | Breakdowns report |
| GET | `/metrics/mtbf-mttr` | No | MTBF/MTTR metrics |
| GET | `/api/oee/calculate` | No | Advanced OEE |
| GET | `/api/alarms` | Yes | Machine alarms |
| GET | `/api/warnings` | Yes | CNC warnings |
| GET | `/api/alerts` | Yes | All alerts combined |

---

## Key Differences from Python Version

| Feature | Python (Flask) | PHP (Core) |
|---------|---------------|------------|
| JWT | `PyJWT` library | Custom HS256 implementation |
| Password hash | `werkzeug pbkdf2:sha256` | `password_hash()` bcrypt + pbkdf2 fallback |
| DB connection | Connection pool (25) | mysqli persistent static |
| PDF export | ReportLab | TCPDF (optional, falls back to CSV) |
| Ping | `subprocess` parallel | `exec()` sequential |
| Thermal model | Python class | Removed (no state between requests) |
| cProfile | Built-in decorator | Not applicable |

---

## Troubleshooting

**404 on all routes**
→ mod_rewrite not enabled or `AllowOverride All` not set. See Step 4.

**Database connection failed**
→ Check port in `config/db.php`. XAMPP default is 3306, not 3307.

**Token is invalid**
→ Tokens from the Python app won't work (different secret key format). Login fresh via PHP.

**Password login fails for existing users**
→ Python used `pbkdf2:sha256` format. The PHP `verify_password()` helper supports both bcrypt and pbkdf2. If it still fails, reset the password via phpMyAdmin using `password_hash()`.
