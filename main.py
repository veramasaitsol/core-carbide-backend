from __future__ import annotations
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
import jwt
from functools import wraps
from passlib.hash import bcrypt
from dbconn import get_db_connection
from datetime import timedelta, datetime, date, time
from mysql.connector import Error
from werkzeug.security import generate_password_hash, check_password_hash
import json
import re
import platform
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from io import StringIO, BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from io import BytesIO
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from flask import make_response
import os
from werkzeug.utils import secure_filename
import traceback
from flask import request, jsonify, Response, send_file
import io, time, functools, cProfile, pstats


import json
from typing import Any, Dict, Optional

# Adjust to your project root + mpf base folder
PROJECT_ROOT = os.getcwd()
MPF_BASE = os.path.abspath(os.path.join(PROJECT_ROOT, "uploads", "mpf"))
ALLOWED_EXTS = {".mpf",".txt", ".nc", ".tap"}
# optional safety cap to avoid huge responses (in bytes)
MAX_RETURN_BYTES = 2_000_000  # 2 MB

app = Flask(__name__)
CORS(app)

# Secret key for JWT
app.config['SECRET_KEY'] = "2J8cdKgm4cB4gzuZ-mPD5WUUOp5fTZrIHLTXuY9gnxw="

# adjust as in your app
UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads", "mpf")
ALLOWED_EXTENSIONS = {".mpf", ".nc", ".tap", ".txt"}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# -------------------- Auth Utilities --------------------
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            token = request.headers['Authorization'].split(" ")[1]
        if not token:
            return jsonify({'message': 'Token is missing'}), 401

        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            current_user = data['sub']
        except:
            return jsonify({'message': 'Token is invalid'}), 401

        return f(current_user, *args, **kwargs)
    return decorated

def cprofile_this(endpoint_name: str):
    """
    Wraps a Flask view to profile with cProfile when ENABLE_CPROFILE=1.
    Writes a text .prof.txt file sorted by cumulative time.
    Adds X-Profile-File and X-Elapsed-MS headers on the response.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if os.getenv("ENABLE_CPROFILE", "1") != "1":
                return fn(*args, **kwargs)

            pr = cProfile.Profile()
            wall_start = time.perf_counter()
            pr.enable()
            try:
                rv = fn(*args, **kwargs)
                return rv
            finally:
                pr.disable()
                wall_ms = (time.perf_counter() - wall_start) * 1000.0

                s = io.StringIO()
                pstats.Stats(pr, stream=s).sort_stats("cumtime").print_stats(40)

                out_dir = os.getenv("CPROFILE_DIR", "/tmp")
                os.makedirs(out_dir, exist_ok=True)
                mid = kwargs.get("machine_id", "unknown")
                ts = time.strftime("%Y%m%d-%H%M%S")
                path = os.path.join(
                    out_dir,
                    f"{endpoint_name}_mid{mid}_{ts}_{int(wall_ms)}ms.prof.txt"
                )
                with open(path, "w", encoding="utf-8") as f:
                    f.write(f"Total wall time: {wall_ms:.2f} ms\n\n")
                    f.write(s.getvalue())

                # Try to attach headers if we got a Response
                try:
                    if isinstance(rv, Response):
                        rv.headers["X-Elapsed-MS"] = f"{wall_ms:.2f}"
                        rv.headers["X-Profile-File"] = path
                    elif isinstance(rv, tuple) and isinstance(rv[0], Response):
                        rv[0].headers["X-Elapsed-MS"] = f"{wall_ms:.2f}"
                        rv[0].headers["X-Profile-File"] = path
                except Exception:
                    pass
        return wrapper
    return decorator




def allowed_file(filename: str) -> bool:
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS

def save_mpf_file_keep_name(file_storage, subfolder: str | None = None):
    """
    Save using the ORIGINAL filename (safe version).
    If the file already exists, DO NOT overwrite — just reuse it.
    Returns (rel_path, saved_new: bool).
    """
    filename = secure_filename(file_storage.filename or "")
    if not filename:
        raise ValueError("Empty filename")
    if not allowed_file(filename):
        raise ValueError(f"Invalid file type. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}")

    base_dir = UPLOAD_FOLDER
    if subfolder:
        base_dir = os.path.join(base_dir, secure_filename(subfolder))

    os.makedirs(base_dir, exist_ok=True)

    abs_path = os.path.join(base_dir, filename)
    saved_new = False
    if not os.path.exists(abs_path):
        file_storage.save(abs_path)
        saved_new = True
    # else: skip saving, reuse existing file

    rel_path = os.path.relpath(abs_path, os.getcwd())
    return rel_path, saved_new


# ---------------- HELPERS ----------------
def _as_json_text(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)

def _as_int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except Exception:
        return None

def _as_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except Exception:
        return None

def _as_time(v: Any) -> Optional[str]:
    """Accept HH:MM:SS string for MySQL TIME."""
    if v is None or v == "":
        return None
    s = str(v).strip()
    parts = s.split(":")
    if len(parts) != 3:
        return None
    return s


# ---------------- ROUTE ----------------
@app.route("/api/machine_data", methods=["POST"])
def insert_machine_data():
    payload: Dict[str, Any] = request.get_json(silent=True) or {}

    machine_id = _as_int(payload.get("machine_id"))
    if not machine_id:
        return jsonify({"success": False, "error": "machine_id is required"}), 400

    # ---------- 1) axis_positions: store as "X: .., Y: .., Z: .." ----------
    axis = payload.get("axis_positions")
    axis_text = None
    if isinstance(axis, dict):
        # keep same formatting as your first dataset
        x = axis.get("X", 0)
        y = axis.get("Y", 0)
        z = axis.get("Z", 0)
        u = axis.get("U", None)   # ✅ read U
        try:
            if u is not None:
                axis_text = f"X: {float(x):0.3f}, Y: {float(y):0.3f}, Z: {float(z):0.3f}, U: {float(u):0.3f}"
            else:
                axis_text = f"X: {float(x):0.3f}, Y: {float(y):0.3f}, Z: {float(z):0.3f}"
        except Exception:
            if u is not None:
                axis_text = f"X: {x}, Y: {y}, Z: {z}, U: {u}"
            else:
                axis_text = f"X: {x}, Y: {y}, Z: {z}"
    else:
        # if already string
        axis_text = str(axis) if axis is not None else None

    # ---------- 2) overrides: accept raw names from your EXE ----------
    feed_ov = payload.get("feed_override")
    if feed_ov is None:
        feed_ov = payload.get("feed_override_raw")

    speed_ov = payload.get("speed_override")
    if speed_ov is None:
        speed_ov = payload.get("speed_override_raw")

    # ---------- 3) diagnostics mapping (optional) ----------
    # In your current DB rows you mostly store NULL here.
    # If you still want to store, enable mapping below.
    diag = payload.get("diagnostics") or {}

    def diag_data(name: str):
        d = diag.get(name) or {}
        return d.get("data")

    # If you want "mostly NULL like old rows", keep these as None:
    pulse_coder_temps = None
    servo_current = None
    servo_temperature = None
    spindle_temperature = None

    # But if you want to store them (remove NULLs), uncomment:
    # pulse_coder_temps = _as_json_text(diag_data("pulse_coder_temp_310"))
    # servo_current = _as_json_text(diag_data("servo_current_320"))
    # servo_temperature = _as_json_text(diag_data("servo_temp_300"))
    # try:
    #     spindle_temperature = _as_int(
    #         (diag.get("spindle_temp_330", {}).get("data", {}).get("AX1", {}) or {}).get("scaled")
    #     )
    # except Exception:
    #     spindle_temperature = None

    # ---------- 4) spindle_load: store SP0 as INT (like your table) ----------
    sp_load = payload.get("spindle_load")
    if isinstance(sp_load, dict):
        sp_load = sp_load.get("SP0")
    spindle_load = _as_int(sp_load)

    # ---------- 5) alarms: store as JSON string like "[]" ----------
    alarms = payload.get("machine_alarms")
    machine_alarms = _as_json_text(alarms if alarms is not None else [])

    # Your old rows often have cnc_warnings / battery_low_alarm NULL,
    # but you can derive them if you want:
    cnc_warnings = _as_json_text(payload.get("cnc_warnings"))  # usually None
    battery_low_alarm = _as_int(payload.get("battery_low_alarm"))  # usually None

    # ---------- 6) servo_load: you are storing it as JSON string in old rows ----------
    servo_load = _as_json_text(payload.get("servo_load"))

    row = {
        "machine_id": machine_id,
        "axis_positions": axis_text,  # ✅ string format like first dump
        "coolant_status": payload.get("coolant_status"),
        "machine_state": payload.get("machine_state"),
        "emergency_signal": _as_int(payload.get("emergency_signal")),
        "machine_mode": payload.get("machine_mode"),
        "main_program_number": payload.get("main_program_number"),
        "executing_program_number": payload.get("executing_program_number"),
        "sequence_number": payload.get("sequence_number"),
        "actual_spindle_speed": _as_int(payload.get("actual_spindle_speed")),
        "actual_feed_rate": _as_int(payload.get("actual_feed_rate")),
        "set_speed": _as_int(payload.get("set_speed")),
        "set_feed_rate": _as_float(payload.get("set_feed_rate")),

        "feed_override": _as_int(feed_ov),
        "speed_override": _as_int(speed_ov),

        "cycle_time": _as_time(payload.get("cycle_time")),
        "cutting_time": _as_time(payload.get("cutting_time")),
        "operate_time": _as_time(payload.get("operate_time")),
        "power_on_time": _as_time(payload.get("power_on_time")),

        # diagnostics (kept NULL like old rows unless you enable mapping)
        "pulse_coder_temps": pulse_coder_temps,
        "servo_current": servo_current,
        "servo_load": servo_load,  # JSON string like {"X":6,"Y":18,"Z":54}
        "servo_temperature": servo_temperature,

        "spindle_load": spindle_load,            # ✅ INT like old rows
        "spindle_temperature": spindle_temperature,  # usually NULL like old rows

        "current_tool_number": _as_int(payload.get("current_tool_number")),
        "total_production": _as_int(payload.get("total_production")),

        "machine_alarms": machine_alarms,  # ✅ "[]" style
        "cnc_warnings": cnc_warnings,
        "battery_low_alarm": battery_low_alarm,

        "tool_offset_value": _as_json_text(payload.get("tool_offset_value")),
        "macro_values": _as_json_text(payload.get("macro_values")),
    }

    sql = """
    INSERT INTO machine_data (
      machine_id, axis_positions, coolant_status, machine_state, emergency_signal, machine_mode,
      main_program_number, executing_program_number, sequence_number,
      actual_spindle_speed, actual_feed_rate, set_speed, set_feed_rate,
      feed_override, speed_override, cycle_time, cutting_time, operate_time, power_on_time,
      pulse_coder_temps, servo_current, servo_load, servo_temperature,
      spindle_load, spindle_temperature, current_tool_number, total_production,
      machine_alarms, cnc_warnings, battery_low_alarm, tool_offset_value, macro_values
    ) VALUES (
      %(machine_id)s, %(axis_positions)s, %(coolant_status)s, %(machine_state)s, %(emergency_signal)s, %(machine_mode)s,
      %(main_program_number)s, %(executing_program_number)s, %(sequence_number)s,
      %(actual_spindle_speed)s, %(actual_feed_rate)s, %(set_speed)s, %(set_feed_rate)s,
      %(feed_override)s, %(speed_override)s, %(cycle_time)s, %(cutting_time)s, %(operate_time)s, %(power_on_time)s,
      %(pulse_coder_temps)s, %(servo_current)s, %(servo_load)s, %(servo_temperature)s,
      %(spindle_load)s, %(spindle_temperature)s, %(current_tool_number)s, %(total_production)s,
      %(machine_alarms)s, %(cnc_warnings)s, %(battery_low_alarm)s, %(tool_offset_value)s, %(macro_values)s
    )
    """

    conn = get_db_connection()
    if conn is None:
        return jsonify({"success": False, "error": "DB connection failed"}), 500

    cur = None
    try:
        cur = conn.cursor()
        cur.execute(sql, row)
        conn.commit()
        return jsonify({"success": True, "id": cur.lastrowid}), 201
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

# ---------------- ROUTE ----------------
#@app.route("/api/machine_data", methods=["POST"])
def insert_machine_data():
    payload: Dict[str, Any] = request.get_json(silent=True) or {}

    machine_id = _as_int(payload.get("machine_id"))
    if not machine_id:
        return jsonify({"success": False, "error": "machine_id is required"}), 400

    # ---------- 1) axis_positions: store as "X: .., Y: .., Z: .." ----------
    axis = payload.get("axis_positions")
    axis_text = None
    if isinstance(axis, dict):
        # keep same formatting as your first dataset
        x = axis.get("X", 0)
        y = axis.get("Y", 0)
        z = axis.get("Z", 0)
        try:
            axis_text = f"X: {float(x):0.3f}, Y: {float(y):0.3f}, Z: {float(z):0.3f}"
        except Exception:
            axis_text = f"X: {x}, Y: {y}, Z: {z}"
    else:
        # if already string
        axis_text = str(axis) if axis is not None else None

    # ---------- 2) overrides: accept raw names from your EXE ----------
    feed_ov = payload.get("feed_override")
    if feed_ov is None:
        feed_ov = payload.get("feed_override_raw")

    speed_ov = payload.get("speed_override")
    if speed_ov is None:
        speed_ov = payload.get("speed_override_raw")

    # ---------- 3) diagnostics mapping (optional) ----------
    # In your current DB rows you mostly store NULL here.
    # If you still want to store, enable mapping below.
    diag = payload.get("diagnostics") or {}

    def diag_data(name: str):
        d = diag.get(name) or {}
        return d.get("data")

    # If you want "mostly NULL like old rows", keep these as None:
    pulse_coder_temps = None
    servo_current = None
    servo_temperature = None
    spindle_temperature = None

    # But if you want to store them (remove NULLs), uncomment:
    # pulse_coder_temps = _as_json_text(diag_data("pulse_coder_temp_310"))
    # servo_current = _as_json_text(diag_data("servo_current_320"))
    # servo_temperature = _as_json_text(diag_data("servo_temp_300"))
    # try:
    #     spindle_temperature = _as_int(
    #         (diag.get("spindle_temp_330", {}).get("data", {}).get("AX1", {}) or {}).get("scaled")
    #     )
    # except Exception:
    #     spindle_temperature = None

    # ---------- 4) spindle_load: store SP0 as INT (like your table) ----------
    sp_load = payload.get("spindle_load")
    if isinstance(sp_load, dict):
        sp_load = sp_load.get("SP0")
    spindle_load = _as_int(sp_load)

    # ---------- 5) alarms: store as JSON string like "[]" ----------
    alarms = payload.get("machine_alarms")
    machine_alarms = _as_json_text(alarms if alarms is not None else [])

    # Your old rows often have cnc_warnings / battery_low_alarm NULL,
    # but you can derive them if you want:
    cnc_warnings = _as_json_text(payload.get("cnc_warnings"))  # usually None
    battery_low_alarm = _as_int(payload.get("battery_low_alarm"))  # usually None

    # ---------- 6) servo_load: you are storing it as JSON string in old rows ----------
    servo_load = _as_json_text(payload.get("servo_load"))

    row = {
        "machine_id": machine_id,
        "axis_positions": axis_text,  # ✅ string format like first dump
        "coolant_status": payload.get("coolant_status"),
        "machine_state": payload.get("machine_state"),
        "emergency_signal": _as_int(payload.get("emergency_signal")),
        "machine_mode": payload.get("machine_mode"),
        "main_program_number": payload.get("main_program_number"),
        "executing_program_number": payload.get("executing_program_number"),
        "sequence_number": payload.get("sequence_number"),
        "actual_spindle_speed": _as_int(payload.get("actual_spindle_speed")),
        "actual_feed_rate": _as_int(payload.get("actual_feed_rate")),
        "set_speed": _as_int(payload.get("set_speed")),
        "set_feed_rate": _as_float(payload.get("set_feed_rate")),

        "feed_override": _as_int(feed_ov),
        "speed_override": _as_int(speed_ov),

        "cycle_time": _as_time(payload.get("cycle_time")),
        "cutting_time": _as_time(payload.get("cutting_time")),
        "operate_time": _as_time(payload.get("operate_time")),
        "power_on_time": _as_time(payload.get("power_on_time")),

        # diagnostics (kept NULL like old rows unless you enable mapping)
        "pulse_coder_temps": pulse_coder_temps,
        "servo_current": servo_current,
        "servo_load": servo_load,  # JSON string like {"X":6,"Y":18,"Z":54}
        "servo_temperature": servo_temperature,

        "spindle_load": spindle_load,            # ✅ INT like old rows
        "spindle_temperature": spindle_temperature,  # usually NULL like old rows

        "current_tool_number": _as_int(payload.get("current_tool_number")),
        "total_production": _as_int(payload.get("total_production")),

        "machine_alarms": machine_alarms,  # ✅ "[]" style
        "cnc_warnings": cnc_warnings,
        "battery_low_alarm": battery_low_alarm,

        "tool_offset_value": _as_json_text(payload.get("tool_offset_value")),
        "macro_values": _as_json_text(payload.get("macro_values")),
    }

    sql = """
    INSERT INTO machine_data (
      machine_id, axis_positions, coolant_status, machine_state, emergency_signal, machine_mode,
      main_program_number, executing_program_number, sequence_number,
      actual_spindle_speed, actual_feed_rate, set_speed, set_feed_rate,
      feed_override, speed_override, cycle_time, cutting_time, operate_time, power_on_time,
      pulse_coder_temps, servo_current, servo_load, servo_temperature,
      spindle_load, spindle_temperature, current_tool_number, total_production,
      machine_alarms, cnc_warnings, battery_low_alarm, tool_offset_value, macro_values
    ) VALUES (
      %(machine_id)s, %(axis_positions)s, %(coolant_status)s, %(machine_state)s, %(emergency_signal)s, %(machine_mode)s,
      %(main_program_number)s, %(executing_program_number)s, %(sequence_number)s,
      %(actual_spindle_speed)s, %(actual_feed_rate)s, %(set_speed)s, %(set_feed_rate)s,
      %(feed_override)s, %(speed_override)s, %(cycle_time)s, %(cutting_time)s, %(operate_time)s, %(power_on_time)s,
      %(pulse_coder_temps)s, %(servo_current)s, %(servo_load)s, %(servo_temperature)s,
      %(spindle_load)s, %(spindle_temperature)s, %(current_tool_number)s, %(total_production)s,
      %(machine_alarms)s, %(cnc_warnings)s, %(battery_low_alarm)s, %(tool_offset_value)s, %(macro_values)s
    )
    """

    conn = get_db_connection()
    if conn is None:
        return jsonify({"success": False, "error": "DB connection failed"}), 500

    cur = None
    try:
        cur = conn.cursor()
        cur.execute(sql, row)
        conn.commit()
        return jsonify({"success": True, "id": cur.lastrowid}), 201
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass






@app.route("/api/machine-production/upload-mpf", methods=["POST"])
def upload_mpf():
    mp_id = request.form.get("id") or request.args.get("id")
    if not mp_id:
        return jsonify({"error": "id is required"}), 400
    if "file" not in request.files or not request.files["file"].filename:
        return jsonify({"error": "file is required"}), 400

    file = request.files["file"]

    # Optional: let client send a subfolder like job_order_no to organize files
    #subfolder = request.form.get("job_order_no")  # or any folder hint you prefer
    subfolder = None

    try:
        rel_path, saved_new = save_mpf_file_keep_name(file, subfolder=subfolder)

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE machine_production SET mpf_path=%s WHERE id=%s",
            (rel_path, mp_id),
        )
        if cur.rowcount == 0:
            return jsonify({"error": f"No row with id={mp_id}"}), 404
        conn.commit()

        return jsonify({
            "success": True,
            "id": str(mp_id),
            "mpf_path": rel_path,
            "saved_new": saved_new,   # True if we actually wrote the file, False if reused
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    


def _is_allowed_path(rel_path: str) -> str | None:
    """
    Validate and return absolute path inside MPF_BASE.
    Prevents path traversal and enforces allowed extensions.
    """
    if not rel_path:
        return None
    # Normalize/clean the path
    safe_rel = os.path.normpath(rel_path).lstrip(os.sep)
    abs_path = os.path.abspath(os.path.join(PROJECT_ROOT, safe_rel))

    # Must live under MPF_BASE
    if not abs_path.startswith(MPF_BASE + os.sep) and abs_path != MPF_BASE:
        return None

    # Extension check
    _, ext = os.path.splitext(abs_path)
    if ext.lower() not in ALLOWED_EXTS:
        return None

    return abs_path




@app.route("/api/machine-production/mpf", methods=["GET"])
def get_mpf_program():
    mpf_path = request.args.get("mpf_path", "").strip()
    abs_path = _is_allowed_path(mpf_path)
    if not abs_path:
        return jsonify({"error": "Invalid or disallowed mpf_path"}), 400

    if not os.path.exists(abs_path):
        return jsonify({"error": "File not found", "mpf_path": mpf_path}), 404

    try:
        size = os.path.getsize(abs_path)
        if size > MAX_RETURN_BYTES:
            return jsonify({
                "error": "File too large to return as JSON",
                "mpf_path": mpf_path,
                "size_bytes": size,
                "max_return_bytes": MAX_RETURN_BYTES
            }), 413  # Payload Too Large

        with open(abs_path, "rb") as f:
            raw = f.read()

        encoding = "utf-8"
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            encoding = "latin-1"
            text = raw.decode("latin-1")

        # normalize newlines, split into lines
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = normalized.split("\n")

        return jsonify({
            "success": True,
            "mpf_path": mpf_path,
            "filename": os.path.basename(abs_path),
            "size_bytes": size,
            "encoding": encoding,
            "line_count": len(lines),
            "content": normalized,   # full program as a single string
            "lines": lines           # array of lines (no newline chars)
        }), 200

    except Exception as e:
        return jsonify({"error": "Failed to read file", "detail": str(e)}), 500

    



@app.route("/login", methods=["POST"])
def login():
    data = (request.get_json(silent=True) or {})
    employee_id = data.get("employee_id") or data.get("username")
    password = data.get("password")

    if not employee_id or not password:
        return jsonify({"message": "employee_id and password are required"}), 400

    conn = get_db_connection()
    if conn is None:
        # Helpful hint: check .env (DB_HOST/PORT/USER/PASSWORD/NAME) and that the DB is reachable
        return jsonify({"message": "Database connection failed"}), 500

    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)

        # DEBUG: show what we're querying (but not the password)
        #print(f"[LOGIN] Looking up user by employee_id='{employee_id}'")

        cursor.execute("SELECT * FROM users WHERE employee_id=%s", (employee_id,))
        user = cursor.fetchone()

        if not user:
            #print("[LOGIN] No user row found")
            return jsonify({"message": "Invalid credentials"}), 401

        # Some schemas use 'password_hash', others kept 'password'
        stored_hash = user.get("password_hash") or user.get("password")
        if not stored_hash:
            #print("[LOGIN] User row missing password hash column. Columns:", list(user.keys()))
            return jsonify({"message": "Server password config error"}), 500

        # DEBUG: do not print the actual password or hash
        #print("[LOGIN] User row fetched. id=", user.get("id"), "role=", user.get("role"))

        if not check_password_hash(stored_hash, password):
            #print("[LOGIN] Password check failed")
            return jsonify({"message": "Invalid credentials"}), 401

        # Build JWT
        payload = {
            "sub": str(user["employee_id"]),  # must be a string in many JWT consumers
            "exp": datetime.utcnow() + timedelta(hours=8),
        }
        token = jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")

        # Fetch mapped machines (ensure user.id exists)
        cursor.execute("SELECT machine_id FROM user_machines WHERE user_id=%s", (user["id"],))
        machine_ids = [row["machine_id"] for row in cursor.fetchall()]

        # created_at may be None or a datetime
        created_at = user.get("created_at")
        created_at_iso = created_at.isoformat() if hasattr(created_at, "isoformat") else None

        resp = {
            "token": token,
            "user": {
                "id": user["id"],
                "employee_id": user["employee_id"],
                "name": user.get("name"),
                "plant": user.get("plant"),
                "role": user.get("role"),
                "status": user.get("status"),
                "created_at": created_at_iso,
                "machine_ids": machine_ids,
            },
        }
        #print("[LOGIN] Success for employee_id=", employee_id, "machines:", machine_ids)
        return jsonify(resp), 200

    except Exception as e:
        # During development, log full traceback to server logs
        print("[LOGIN][ERROR]", repr(e))
        traceback.print_exc()

        # Return a more descriptive error while you debug. In production, keep it generic.
        return jsonify({
            "message": "Login failed",
            "error": str(e)  # remove this in production
        }), 500

    finally:
        try:
            if cursor: cursor.close()
        except Exception as e:
            print("[LOGIN][WARN] cursor.close() failed:", e)
        try:
            if conn: conn.close()
        except Exception as e:
            print("[LOGIN][WARN] conn.close() failed:", e)



@app.route('/api/machines/live-status', methods=['GET'])
#@token_required
@cprofile_this("live_status")
def get_machines_live_status():
    """Get live status for all machines displaying exact database machine_state"""
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        server_time = datetime.now()
        
        # Query without user joins, using row_number to get exactly one record per machine
        query = """
        SELECT 
            m.id as machine_id,
            m.oem_name,
            m.control_type,
            m.control_details,
            m.vfj_no,
            
            md.machine_state,
            md.cycle_time,
            md.total_production as part_count,
            md.spindle_load,
            md.timestamp as last_updated,
            TIMESTAMPDIFF(SECOND, md.timestamp, NOW()) as seconds_since_update
        FROM machines m
        LEFT JOIN (
            SELECT machine_id, machine_state, cycle_time, total_production, 
                   spindle_load, timestamp,
                   ROW_NUMBER() OVER (PARTITION BY machine_id ORDER BY timestamp DESC, id DESC) as rn
            FROM machine_data
        ) md ON m.id = md.machine_id AND md.rn = 1
        ORDER BY m.id;
        """
        
        cursor.execute(query)
        results = cursor.fetchall()
        
        machines_status = []
        
        for row in results:
            machine_id = row["machine_id"]
            
            # Get real part count using EXACT same logic as /api/oee/calculate
            production_query = """
                SELECT COALESCE(SUM(TIME_TO_SEC(total_cycle_time)/60), 0) as total_production_minutes,
                       COUNT(*) as parts_produced,
                       MIN(timestamp) as prod_start,
                       MAX(timestamp) as prod_end
                FROM machine_production 
                WHERE machine_id = %s AND total_cycle_time != '00:00:00'
                AND results = 'PASS' AND DATE(timestamp) = CURDATE()
            """
            cursor.execute(production_query, (machine_id,))
            production_result = cursor.fetchone()
            
            # Convert Decimal to int to avoid type errors
            real_part_count = int(production_result['parts_produced'] or 0)
            
            # Build machine status object - ALWAYS use  values directly
            machine_status = {
                "machine_id": machine_id,
                 "machine_name": row["oem_name"],
                "control_type": row["control_type"],
                "control_details": row["control_details"],
                "vfj_no": row["vfj_no"],
                "machine_state": row["machine_state"],  # Direct from database, no conditions
                "cycle_time": str(row["cycle_time"]) if row["cycle_time"] else None,
                "part_count": real_part_count,
                "spindle_load": row["spindle_load"],
                "last_updated": row["last_updated"].isoformat() if row["last_updated"] else None,
                "server_time": server_time.isoformat(),
                "seconds_since_update": row["seconds_since_update"]  # Optional: keep for monitoring
            }
            
            machines_status.append(machine_status)
        
        return jsonify({
            "success": True,
            "count": len(machines_status),
            "server_timestamp": server_time.isoformat(),
            "machines": machines_status
        })
        
    except Error as e:
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route('/api/machines/ping-status', methods=['GET'])
def get_machines_ping_status():
    """
    Return vfj_no, machine_name (oem_name), ip_address, and ip_status (active/inactive)
    for each machine in the machines table.
    """
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT vfj_no, oem_name, ip_address
            FROM machines
            ORDER BY id
        """)
        rows = cursor.fetchall()

        # Helper: cross-platform ping with short timeout
        def ping_host(ip: str, timeout_seconds: float = 1.0) -> bool:
            system = platform.system().lower()
            # Windows uses -n (count) and -w (timeout in ms)
            if 'windows' in system:
                cmd = ["ping", "-n", "1", "-w", str(int(timeout_seconds * 1000)), ip]
            else:
                # Linux/macOS use -c (count) and -W timeout (seconds on Linux, ms on macOS -> use -t on mac?).
                # Use a portable combo: -c 1 and a global timeout via subprocess.run(timeout=...)
                cmd = ["ping", "-c", "1", ip]
            try:
                completed = subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=timeout_seconds + 0.5,  # small buffer
                    check=False
                )
                return completed.returncode == 0
            except Exception:
                return False

        # Ping in parallel (faster for many machines)
        results = []
        with ThreadPoolExecutor(max_workers=16) as executor:
            future_map = {
                executor.submit(ping_host, r["ip_address"]): r for r in rows if r.get("ip_address")
            }
            for future in as_completed(future_map):
                r = future_map[future]
                ok = False
                try:
                    ok = future.result()
                except Exception:
                    ok = False
                results.append({
                    "vfj_no": r["vfj_no"],
                    "machine_name": r["oem_name"],
                    "ip_address": r["ip_address"],
                    "ip_status": "active" if ok else "inactive"
                })

        # If any rows had null/empty IPs, include them as inactive for completeness
        for r in rows:
            if not r.get("ip_address"):
                results.append({
                    "vfj_no": r["vfj_no"],
                    "machine_name": r["oem_name"],
                    "ip_address": r.get("ip_address"),
                    "ip_status": "inactive"
                })

        return jsonify({
            "success": True,
            "count": len(results),
            "machines": results
        })

    except Error as e:
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route("/create_user", methods=["POST"])
@token_required
def create_user(current_user):
    data = request.json or {}
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500
        
    cursor = None
    try:
        cursor = conn.cursor()

        # --- Admin check (current_user is assumed to be employee_id from token) ---
        cursor.execute("SELECT role FROM users WHERE employee_id=%s", (current_user,))
        row = cursor.fetchone()
        if not row or row[0] != "admin":
            return jsonify({"message": "Admin access required"}), 403

        # --- Required fields ---
        required = ["plant", "role", "name", "employee_id"]
        missing = [k for k in required if not data.get(k)]
        if missing:
            return jsonify({"error": f"Missing required field(s): {', '.join(missing)}"}), 400

        role = data["role"]
        plant = data["plant"]
        name = data["name"]
        employee_id = data["employee_id"]
        machine_ids = data.get("machine_ids", []) or []

        # --- Duplicate employee_id check ---
        cursor.execute("SELECT id FROM users WHERE employee_id=%s", (employee_id,))
        if cursor.fetchone():
            return jsonify({"message": "Employee ID already exists"}), 400

        # --- Default password hash ---
        password_hash = generate_password_hash(data['password'])
        #password_hash = generate_password_hash("Password@123")

        # --- Insert user ---
        cursor.execute("""
            INSERT INTO users (plant, employee_id, name, password_hash, role, status)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (plant, employee_id, name, password_hash, role, data.get("status")))
        user_id = cursor.lastrowid

        # --- Map user to machines (if provided) ---
        if machine_ids:
            # Ensure all are ints
            machine_ids = [int(mid) for mid in machine_ids]
            cursor.executemany(
                "INSERT INTO user_machines (user_id, machine_id) VALUES (%s, %s)",
                [(user_id, mid) for mid in machine_ids]
            )

        conn.commit()
        return jsonify({
            "message": "User created",
            "user_id": user_id,
            "mapped_machine_count": len(machine_ids)
        }), 201

    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": "Failed to create user"}), 400
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route("/users", methods=["GET"])
@token_required
def list_users(current_user):
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500
        
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        # Admin check
        cursor.execute("SELECT role FROM users WHERE employee_id=%s", (current_user,))
        row = cursor.fetchone()
        if not row or row["role"] != "admin":
            return jsonify({"message": "Admin access required"}), 403
        
        cursor.execute("""
            SELECT id, plant, employee_id, name, role, status, created_at
            FROM users
            ORDER BY id DESC
        """)
        users = cursor.fetchall()
        
        # fetch machine mappings with control type
        if users:
            user_ids = [u["id"] for u in users]
            fmt = ",".join(["%s"] * len(user_ids))
            cursor.execute(f"""
                SELECT um.user_id, um.machine_id, m.control_type
                FROM user_machines um
                JOIN machines m ON um.machine_id = m.id
                WHERE um.user_id IN ({fmt})
            """, tuple(user_ids))
            rows = cursor.fetchall()
            
            mapped_machines = {}
            for r in rows:
                if r["user_id"] not in mapped_machines:
                    mapped_machines[r["user_id"]] = []
                mapped_machines[r["user_id"]].append({
                    "machine_id": r["machine_id"],
                    "control_type": r["control_type"]
                })
            
            for u in users:
                u["machines"] = mapped_machines.get(u["id"], [])
                # Keep backward compatibility
                u["machine_ids"] = [m["machine_id"] for m in u["machines"]]
        
        return jsonify({"users": users}), 200
    except Exception as e:
        return jsonify({"error": "Failed to fetch users"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route("/users/<int:user_id>", methods=["GET"])
@token_required
def get_user(current_user, user_id):
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500
        
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        # Admin check
        cursor.execute("SELECT role FROM users WHERE employee_id=%s", (current_user,))
        row = cursor.fetchone()
        if not row or row["role"] != "admin":
            return jsonify({"message": "Admin access required"}), 403

        cursor.execute("""
            SELECT id, plant, employee_id, name, role, status, created_at
            FROM users WHERE id=%s
        """, (user_id,))
        user = cursor.fetchone()
        if not user:
            return jsonify({"message": "User not found"}), 404

        cursor.execute("SELECT machine_id FROM user_machines WHERE user_id=%s", (user_id,))
        user["machine_ids"] = [r["machine_id"] for r in cursor.fetchall()]
        return jsonify(user), 200
    except Exception as e:
        return jsonify({"error": "Failed to fetch user"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route("/users/<int:user_id>", methods=["PATCH"])
@token_required
def update_user(current_user, user_id):
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500
        
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        # --- Admin check ---
        cursor.execute("SELECT role FROM users WHERE employee_id=%s", (current_user,))
        row = cursor.fetchone()
        if not row or row["role"] != "admin":
            return jsonify({"message": "Admin access required"}), 403

        data = request.json or {}

        # --- Ensure user exists ---
        cursor.execute("SELECT id, employee_id, role FROM users WHERE id=%s", (user_id,))
        existing = cursor.fetchone()
        if not existing:
            return jsonify({"message": "User not found"}), 404

        # --- If changing employee_id, ensure no dup ---
        if "employee_id" in data and data["employee_id"] != existing["employee_id"]:
            cursor.execute("SELECT id FROM users WHERE employee_id=%s", (data["employee_id"],))
            if cursor.fetchone():
                return jsonify({"error": "Employee ID already exists"}), 400

        # --- Password handling ---
        plain_pwd = None
        if "password" in data:
            plain_pwd = (data["password"] or "").strip()
        elif "password_hash" in data:
            candidate = (data["password_hash"] or "").strip()
            if candidate.startswith("pbkdf2:"):
                data["password_hash"] = candidate
            else:
                plain_pwd = candidate

        if plain_pwd is not None:
            if not plain_pwd:
                return jsonify({"error": "Password cannot be empty"}), 400
            data["password_hash"] = generate_password_hash(
                plain_pwd, method="pbkdf2:sha256", salt_length=12
            )

        # --- Build SET clause dynamically (table columns) ---
        allowed_fields = ["plant", "name", "employee_id", "role", "status", "password_hash"]
        sets, vals = [], []
        for k in allowed_fields:
            if k in data:
                sets.append(f"{k}=%s")
                vals.append(data[k])

        if sets:
            sql = f"UPDATE users SET {', '.join(sets)} WHERE id=%s"
            vals.append(user_id)
            cursor.execute(sql, tuple(vals))

        # --- Optional machine mapping replace ---
        if "machine_ids" in data and data["machine_ids"] is not None:
            machine_ids = [int(mid) for mid in (data.get("machine_ids") or [])]
            if machine_ids:
                fmt = ",".join(["%s"] * len(machine_ids))
                cursor.execute(f"SELECT id FROM machines WHERE id IN ({fmt})", tuple(machine_ids))
                exist = {r["id"] for r in cursor.fetchall()}
                missing = [m for m in machine_ids if m not in exist]
                if missing:
                    return jsonify({"error": "Some machine_ids do not exist", "missing_machine_ids": missing}), 400

            cursor.execute("DELETE FROM user_machines WHERE user_id=%s", (user_id,))
            if machine_ids:
                cursor.executemany(
                    "INSERT INTO user_machines (user_id, machine_id) VALUES (%s, %s)",
                    [(user_id, mid) for mid in machine_ids]
                )

        conn.commit()
        return jsonify({"message": "User updated successfully"}), 200

    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": "Failed to update user"}), 400
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route("/users/me/reset_password", methods=["POST"])
@token_required
def reset_password(current_user):
    """
    Authenticated user password reset (self-service).
    """
    data = request.json or {}
    old_pwd = (data.get("old_password") or "").strip()
    new_pwd = (data.get("new_password") or "").strip()
    confirm = (data.get("confirm_new_password") or "").strip()

    # Basic validations
    if not old_pwd or not new_pwd or not confirm:
        return jsonify({"error": "old_password, new_password, confirm_new_password are required"}), 400
    if new_pwd != confirm:
        return jsonify({"error": "New password and confirmation do not match"}), 400
    if new_pwd == old_pwd:
        return jsonify({"error": "New password must be different from old password"}), 400

    # Simple policy: min length + at least one letter & number
    if len(new_pwd) < 8:
        return jsonify({"error": "New password must be at least 8 characters"}), 400
    # if not any(c.isalpha() for c in new_pwd) or not any(c.isdigit() for c in new_pwd):
    #     return jsonify({"error": "New password must include letters and numbers"}), 400

    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500
        
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        # current_user is employee_id (from your earlier endpoints)
        cursor.execute("SELECT id, password_hash FROM users WHERE employee_id=%s", (current_user,))
        user = cursor.fetchone()
        if not user:
            return jsonify({"error": "User not found"}), 404

        # Verify old password
        if not check_password_hash(user["password_hash"], old_pwd):
            return jsonify({"error": "Old password is incorrect"}), 401

        # Hash and update
        new_hash = generate_password_hash(new_pwd, method="pbkdf2:sha256", salt_length=12)
        cursor.execute("UPDATE users SET password_hash=%s WHERE id=%s", (new_hash, user["id"]))
        conn.commit()

        return jsonify({"message": "Password updated successfully. Please sign in again."}), 200

    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": "Failed to update password"}), 400
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()





@app.route("/users/<int:user_id>", methods=["DELETE"])
@token_required
def delete_user(current_user, user_id):
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500
        
    cursor = None
    try:
        cursor = conn.cursor()
        # Admin check
        cursor.execute("SELECT role FROM users WHERE employee_id=%s", (current_user,))
        row = cursor.fetchone()
        if not row or row[0] != "admin":
            return jsonify({"message": "Admin access required"}), 403

        # Ensure user exists
        cursor.execute("SELECT id, role FROM users WHERE id=%s", (user_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"message": "User not found"}), 404

        # Cascades will remove user_machines if FK ON DELETE CASCADE is on user_id
        cursor.execute("DELETE FROM users WHERE id=%s", (user_id,))
        conn.commit()
        return jsonify({"message": "User deleted successfully"}), 200

    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": "Failed to delete user"}), 400
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route("/add_machine", methods=["POST"])
@token_required
def add_machine(current_user):
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = None
    try:
        cursor = conn.cursor()

        # --- Check if current user is admin ---
        cursor.execute("SELECT role FROM users WHERE employee_id=%s", (current_user,))
        role = cursor.fetchone()
        if not role or role[0] != "admin":
            return jsonify({"message": "Admin access required"}), 403

        data = request.json

        # --- Required fields check ---
        required_fields = ["oem_name", "ip_address", "operator_ip", "vfj_no", "control_type", "control_model"]
        missing = [field for field in required_fields if not data.get(field)]
        if missing:
            return jsonify({
                "error": f"Missing required field(s): {', '.join(missing)}"
            }), 400

        # --- Insert into machines ---
        cursor.execute("""
            INSERT INTO machines 
            (oem_name, ip_address, operator_ip, port, vfj_no, 
             control_type, control_details, control_model, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            data["oem_name"],
            data["ip_address"],
            data.get("operator_ip"),
            data.get("port"),
            data["vfj_no"],
            data.get("control_type"),
            data.get("control_details"),
            data.get("control_model"),
            data.get("status", "active")   # default status active
        ))

        machine_id = cursor.lastrowid

        # --- Insert initial machine_data row with state 'idle' ---
        cursor.execute("""
            INSERT INTO machine_data (machine_id, machine_state)
            VALUES (%s, %s)
        """, (machine_id, "OFFLINE"))

        conn.commit()

        return jsonify({
            "message": "Machine added successfully",
            "machine_id": machine_id
        }), 201

    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": f"Failed to add machine: {str(e)}"}), 400
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()



@app.route("/machines", methods=["GET"])
@token_required
def list_machines(current_user):
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500
        
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        # Admin check
        cursor.execute("SELECT role FROM users WHERE employee_id=%s", (current_user,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"message": "Admin access required"}), 403

        cursor.execute("""
            SELECT id, oem_name, ip_address, operator_ip, port, vfj_no,
                   control_type, control_details, control_model, status,
                   created_at, updated_at
            FROM machines
            WHERE status = 'active'
            ORDER BY id DESC
        """)
        machines = cursor.fetchall()
        return jsonify({"machines": machines}), 200
    except Exception as e:
        return jsonify({"error": "Failed to fetch machines"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route("/machines/<int:machine_id>", methods=["GET"])
@token_required
def get_machine(current_user, machine_id):
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500
        
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT role FROM users WHERE employee_id=%s", (current_user,))
        row = cursor.fetchone()
        if not row or row["role"] != "admin":
            return jsonify({"message": "Admin access required"}), 403

        cursor.execute("""
            SELECT id, oem_name, ip_address, operator_ip, port, vfj_no,
                   control_type, control_details, control_model, status,
                   created_at, updated_at
            FROM machines       
            WHERE id=%s and status = 'active'
        """, (machine_id,))
        machine = cursor.fetchone()
        if not machine:
            return jsonify({"message": "Machine not found"}), 404
        return jsonify(machine), 200
    except Exception as e:
        return jsonify({"error": "Failed to fetch machine"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route("/machines/<int:machine_id>", methods=["PATCH"])
@token_required
def update_machine(current_user, machine_id):
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500
        
    cursor = None
    try:
        cursor = conn.cursor()
        # Admin check
        cursor.execute("SELECT role FROM users WHERE employee_id=%s", (current_user,))
        row = cursor.fetchone()
        if not row or row[0] != "admin":
            return jsonify({"message": "Admin access required"}), 403

        data = request.json or {}
        # Allowed columns to update
        allowed_fields = [
            "oem_name", "ip_address", "operator_ip", "port", "vfj_no",
            "control_type", "control_details", "control_model", "status"
        ]
        # Build SET clause 
        sets, vals = [], []
        for key in allowed_fields:
            if key in data:
                sets.append(f"{key}=%s")
                vals.append(data[key])

        if not sets:
            return jsonify({"error": "No valid fields provided to update"}), 400

        # Ensure machine exists
        cursor.execute("SELECT id FROM machines WHERE id=%s", (machine_id,))
        if not cursor.fetchone():
            return jsonify({"message": "Machine not found"}), 404

        sql = f"UPDATE machines SET {', '.join(sets)} WHERE id=%s"
        vals.append(machine_id)
        cursor.execute(sql, tuple(vals))
        conn.commit()
        return jsonify({"message": "Machine updated successfully"}), 200

    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": "Failed to update machine"}), 400
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route("/machines/<int:machine_id>", methods=["DELETE"])
@token_required
def deactivate_machine(current_user, machine_id):
    """
    Soft-delete a machine by setting status='inactive'.
    Admin-only. Idempotent if already inactive.
    """
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = None
    try:
        cursor = conn.cursor()

        # Admin check
        cursor.execute("SELECT role FROM users WHERE employee_id=%s", (current_user,))
        row = cursor.fetchone()
        if not row or row[0] != "admin":
            return jsonify({"message": "Admin access required"}), 403

        # Ensure machine exists
        cursor.execute("SELECT status FROM machines WHERE id=%s", (machine_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"message": "Machine not found"}), 404

        current_status = row[0] or ""
        if current_status.lower() == "inactive":
            return jsonify({"message": "Machine already inactive"}), 200

        # Soft delete by toggling status
        cursor.execute("UPDATE machines SET status='inactive' WHERE id=%s", (machine_id,))
        conn.commit()
        return jsonify({"message": "Machine deactivated (soft deleted) successfully"}), 200

    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"error": f"Failed to deactivate machine: {str(e)}"}), 400
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@app.route("/machines/<int:machine_id>/restore", methods=["POST"])
@token_required
def restore_machine(current_user, machine_id):
    """
    Restore a soft-deleted machine by setting status='active'.
    Admin-only. Idempotent if already active.
    """
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = None
    try:
        cursor = conn.cursor()

        # Admin check
        cursor.execute("SELECT role FROM users WHERE employee_id=%s", (current_user,))
        row = cursor.fetchone()
        if not row or row[0] != "admin":
            return jsonify({"message": "Admin access required"}), 403

        # Ensure machine exists
        cursor.execute("SELECT status FROM machines WHERE id=%s", (machine_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"message": "Machine not found"}), 404

        current_status = row[0] or ""
        if current_status.lower() == "active":
            return jsonify({"message": "Machine already active"}), 200

        # Restore by toggling status
        cursor.execute("UPDATE machines SET status='active' WHERE id=%s", (machine_id,))
        conn.commit()
        return jsonify({"message": "Machine restored successfully"}), 200

    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"error": f"Failed to restore machine: {str(e)}"}), 400
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


        




@app.route("/machines/<int:machine_id>/status", methods=["PUT"])
@token_required
def update_machine_status(current_user, machine_id):
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500
        
    cursor = None
    try:
        cursor = conn.cursor()
        data = request.json
        new_status = data.get("status")
        if not new_status:
            return jsonify({"message": "Missing status field"}), 400

        cursor.execute("UPDATE machines SET status=%s WHERE id=%s", (new_status, machine_id))
        conn.commit()
        return jsonify({"message": "Status updated", "machine_id": machine_id, "new_status": new_status})
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": "Failed to update status"}), 400
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()




def _filter_axis_positions_text(s: str, zero_tol: float = 1e-6) -> str:
    """
    Parse 'X: 86.000, Y: 0.000, ...' and keep only non-zero axes.
    Returns a string like 'X: 86.000, Z: -3.425'. Empty string if all zero/empty.
    """
    if not s:
        return s
    parts = re.split(r'\s*,\s*', s.strip())
    kept = []
    for p in parts:
        m = re.match(r'\s*([A-Za-z]+)\s*:\s*(-?\d+(?:\.\d+)?)\s*$', p)
        if not m:
            continue
        axis, val_str = m.group(1), m.group(2)
        try:
            val = float(val_str)
        except ValueError:
            continue
        if abs(val) > zero_tol:
            kept.append(f"{axis}: {val:.3f}")
    return ", ".join(kept) if kept else ""





# ---- Per-machine constants (tune once; no DB needed) ----
MACHINE_CONST = {
    # machine_id : constants
    1: dict(P_IDLE_KW=1.2, P_SP_RATED_KW=11.0, K_SERVO_KW_PER_PCT=0.010, ENC_K_OFFSET_C=7.0),
    15: dict(P_IDLE_KW=1.5, P_SP_RATED_KW=11.0, K_SERVO_KW_PER_PCT=0.010, ENC_K_OFFSET_C=7.0),
    # add more machines as needed...
}

def _get_consts(mid: int):
    # Fallback defaults if not configured
    return MACHINE_CONST.get(mid, dict(P_IDLE_KW=1.2, P_SP_RATED_KW=11.0, K_SERVO_KW_PER_PCT=0.010, ENC_K_OFFSET_C=7.0))

# ---- Power and overrides ----
def _p_total_kw(row):
    try:
        return (
            (row.get('voltage1') or 0) * (row.get('current1') or 0) * (row.get('power_factor1') or 0) +
            (row.get('voltage2') or 0) * (row.get('current2') or 0) * (row.get('power_factor2') or 0) +
            (row.get('voltage3') or 0) * (row.get('current3') or 0) * (row.get('power_factor3') or 0)
        ) / 1000.0
    except Exception:
        return None

def _spindle_load_pct_from_power(p_total_kw, servo_load_pct, P_IDLE_KW, K_SERVO_KW_PER_PCT, P_SP_RATED_KW):
    if p_total_kw is None or P_SP_RATED_KW <= 0:
        return None, None
    p_corr = max(p_total_kw - P_IDLE_KW - (K_SERVO_KW_PER_PCT * (servo_load_pct or 0.0)), 0.0)
    return (100.0 * p_corr / P_SP_RATED_KW), p_corr

def _feed_override(actual_feed_mm_min, set_feed, actual_rpm):
    """
    Heuristic:
      - If set_feed > 1.0 → assume G94 (mm/min)
      - Else → assume G95 (mm/rev) and need actual_rpm
    """
    if not set_feed or set_feed <= 0 or not actual_feed_mm_min:
        return None
    if set_feed > 1.0:
        # G94
        return 100.0 * (actual_feed_mm_min / set_feed) if set_feed > 0 else None
    else:
        # G95 (mm/rev)
        if not actual_rpm or actual_rpm <= 0:
            return None
        set_mm_min = actual_rpm * set_feed
        return 100.0 * (actual_feed_mm_min / set_mm_min) if set_mm_min > 0 else None

def _speed_override(actual_rpm, set_speed):
    """
    Assumes G97 (RPM). If you later have CSS (G96), replace with the CSS formula.
    """
    if not actual_rpm or not set_speed or set_speed <= 0:
        return None
    return 100.0 * (actual_rpm / set_speed)

def _cooling_gamma(coolant_status: str) -> float:
    if not coolant_status:
        return 1.0
    s = str(coolant_status).strip().upper()
    if "ON" in s or "TRUE" in s or s == "1":
        return 0.75  # stronger cooling
    return 1.0

from dataclasses import dataclass

@dataclass
class SpindleTempState:
    est_c: float | None = None
    last_ts: float | None = None

# Keep one per machine_id (module-level dict)
SPINDLE_TEMP_STATES: dict[int, SpindleTempState] = {}

import time

def estimate_spindle_temp(
    machine_id: int,
    p_corr_kw: float | None,
    rpm: float | None,
    coolant_status: str | None,
    ambient_c: float = 28.0,
    tau_min: float = 12.0,     # τ_sp, tune 8–20 min
    beta_c_per_kw: float = 8.0,# β, tune 6–12 °C/kW
    p_base_kw: float = 0.25,   # P_base, tune 0.15–0.4 kW
    k_wind_kw_per_rpm2: float = 1.0e-6, # k_wind, tune by idle spin tests
    eta_mech: float = 0.90     # η, tune 0.88–0.93
) -> float | None:
    # Inputs sanity
    if rpm is None: rpm = 0.0
    if p_corr_kw is None: p_corr_kw = 0.0

    # Heating power model
    p_heat = p_base_kw + k_wind_kw_per_rpm2 * (rpm ** 2) + (1.0 - eta_mech) * p_corr_kw
    gamma = _cooling_gamma(coolant_status)

    # Instantaneous steady-state temperature
    T_ss = ambient_c + beta_c_per_kw * p_heat * gamma

    # First-order thermal update
    st = SPINDLE_TEMP_STATES.setdefault(machine_id, SpindleTempState())
    now = time.time()
    #now = datetime.now().time()
    if st.est_c is None:
        # Initialize near steady-state (or ambient) on first call
        st.est_c = T_ss
        st.last_ts = now
        return st.est_c

    dt = max(0.0, now - (st.last_ts or now))
    tau_s = max(1.0, tau_min * 60.0)
    alpha = min(1.0, dt / tau_s)  # discrete-time approx
    T_new = st.est_c + alpha * (T_ss - st.est_c)

    # Optional: clamp to sane bounds
    # Never below ambient; never above ambient + 80°C (safety)
    T_new = max(ambient_c, min(T_new, ambient_c + 80.0))

    st.est_c = T_new
    st.last_ts = now
    return T_new

# Add this small helper near your other utils in the same module
def _safe_float(x):
    try:
        if x is None or x == "" or (isinstance(x, str) and x.strip().upper() == "NULL"):
            return None
        return float(x)
    except Exception:
        return None
    





@app.route("/machine_data/<int:machine_id>", methods=["GET"])
#@token_required
@cprofile_this("get_machine_data")
def get_machine_data(machine_id):
    start_time = request.args.get("start_time")
    end_time = request.args.get("end_time")

    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500
             
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)

        # Check if machine exists
        cursor.execute("SELECT id FROM machines WHERE id=%s", (machine_id,))
        if not cursor.fetchone():
            return jsonify({"message": "Machine not found"}), 404

        # ⬇️ NOTE: we also select energy columns needed for power-based spindle load
        base_query = """
        SELECT
          md.id,
          md.machine_id,
          md.axis_positions,
          md.coolant_status,
          md.machine_state,
          md.emergency_signal,
          md.machine_mode,
          md.main_program_number,
          md.executing_program_number,
          md.sequence_number,
          md.actual_spindle_speed,
          md.actual_feed_rate,
          md.set_speed,
          md.set_feed_rate,
          md.feed_override,
          md.speed_override,
          md.cycle_time,
          md.cutting_time,
          md.operate_time,
          md.power_on_time,
          md.pulse_coder_temps,
          md.servo_current,
          COALESCE(ed1.servo_load, md.servo_load)               AS servo_load,
          COALESCE(ed1.servo_temperature, md.servo_temperature) AS servo_temperature,

          -- (existing stored values if any)
          md.spindle_load,
          md.spindle_temperature,
          md.current_tool_number,
          md.total_production,
          md.machine_alarms,
          md.cnc_warnings,
          md.battery_low_alarm,
          md.tool_offset_value,
          md.macro_values,
          md.`timestamp`,

          -- ⬇️ energy columns for power calc
          ed1.voltage1, ed1.voltage2, ed1.voltage3,
          ed1.current1, ed1.current2, ed1.current3,
          ed1.power_factor1, ed1.power_factor2, ed1.power_factor3
        FROM machine_data md
        LEFT JOIN energy_data ed1
          ON ed1.machine_id = md.machine_id
         AND ed1.`timestamp` = (
              SELECT MAX(ed2.`timestamp`)
              FROM energy_data ed2
              WHERE ed2.machine_id = md.machine_id
                AND ed2.`timestamp` <= md.`timestamp`
          )
        WHERE md.machine_id = %s
        """
        params = [machine_id]

        if start_time:
            base_query += " AND md.`timestamp` >= %s"
            params.append(start_time)
        if end_time:
            base_query += " AND md.`timestamp` <= %s"
            params.append(end_time)

        base_query += " ORDER BY md.`timestamp` DESC"

        if not start_time and not end_time:
            base_query += " LIMIT 1"

        cursor.execute(base_query, tuple(params))
        rows = cursor.fetchall()

        if not rows:
            return jsonify({"message": "No data found"}), 404

        # Real part count (today)
        production_query = """
            SELECT COUNT(*) as parts_produced
            FROM machine_production 
            WHERE machine_id = %s
              AND total_cycle_time != '00:00:00'
              AND DATE(timestamp) = CURDATE()
              AND results = "PASS";
        """
        cursor.execute(production_query, (machine_id,))
        production_result = cursor.fetchone()
        real_part_count = int(production_result['parts_produced'] or 0)

        consts = _get_consts(machine_id)

        # Build response rows with computed metrics
        for row in rows:

            # Ensure minimum servo temperature = 27°C
            try:
                st = _safe_float(row.get('servo_temperature'))
                if st is not None and st < 27:
                    row['servo_temperature'] = 27.0
            except Exception:
                pass
            # Convert timedeltas to HH:MM:SS
            for key, value in row.items():
                if isinstance(value, timedelta):
                    row[key] = str(value)

            # Enrich with part count + keep original
            row['part_count'] = real_part_count
            row['original_total_production'] = row.get('total_production')

            # Clean axis positions (your existing helper)
            ap = row.get('axis_positions')
            row['axis_positions'] = _filter_axis_positions_text(ap)

  

            # Feed Override (%)
            row['feed_override_calc'] = None
            try:
                set_feed = row.get('set_feed_rate')
                if set_feed is not None:
                    row['feed_override_calc'] = round(
                        _feed_override(
                            actual_feed_mm_min=row.get('actual_feed_rate'),
                            set_feed=set_feed,
                            actual_rpm=row.get('actual_spindle_speed')
                        ),
                        1
                    )
            except Exception:
                row['feed_override_calc'] = None  # be explicit

            # Speed Override (%)
            row['speed_override_calc'] = None
            try:
                set_sp = row.get('set_speed')
                if set_sp is not None:
                    row['speed_override_calc'] = round(
                        _speed_override(
                            actual_rpm=row.get('actual_spindle_speed'),
                            set_speed=set_sp
                        ),
                        1
                    )
            except Exception:
                row['speed_override_calc'] = None

            # Determine if we have usable energy data for power-based calculations
            energy_cols = [
                'voltage1','voltage2','voltage3',
                'current1','current2','current3',
                'power_factor1','power_factor2','power_factor3'
            ]
            energy_available = any(row.get(c) is not None for c in energy_cols)

            # Default (safe) outputs
            row['p_total_kw'] = None
            row['p_corr_kw'] = None
            row['spindle_load_pct_calc'] = None
            row['energy_based_calc_available'] = bool(energy_available)

            try:
                # Only attempt power/spindle-load calc if energy columns exist
                if energy_available:
                    p_tot = _p_total_kw(row)  # should return None if it can't compute
                    consts_ok = consts and all(k in consts for k in [
                        'P_IDLE_KW','K_SERVO_KW_PER_PCT','P_SP_RATED_KW'
                    ])

                    # Don't attempt float(None)
                    servo_load_pct = _safe_float(row.get('servo_load'))

                    if p_tot is not None and consts_ok and servo_load_pct is not None:
                        sp_load_pct, p_corr_kw = _spindle_load_pct_from_power(
                            p_total_kw=p_tot,
                            servo_load_pct=servo_load_pct,
                            P_IDLE_KW=consts['P_IDLE_KW'],
                            K_SERVO_KW_PER_PCT=consts['K_SERVO_KW_PER_PCT'],
                            P_SP_RATED_KW=consts['P_SP_RATED_KW']
                        )
                        row['p_total_kw'] = round(p_tot, 3) if p_tot is not None else None
                        row['p_corr_kw']  = round(p_corr_kw, 3) if p_corr_kw is not None else None

                        if sp_load_pct is not None:
                            row['spindle_load_pct_calc'] = round(
                                max(0.0, min(sp_load_pct, 200.0)), 1
                            )
                    # else: leave as None
            except Exception:
                # If anything fails, keep energy-based outputs as None
                row['p_total_kw'] = None
                row['p_corr_kw'] = None
                row['spindle_load_pct_calc'] = None

            # Encoder temp estimate (°C) — safe cast
            try:
                enc = None
                st = _safe_float(row.get('servo_temperature'))
                if st is not None and 'ENC_K_OFFSET_C' in consts:
                    enc = st - consts['ENC_K_OFFSET_C']
                row['encoder_temp_est_c'] = round(enc, 1) if enc is not None else None
            except Exception:
                row['encoder_temp_est_c'] = None

            # (Optional) constants for debug (you already had this)
            row['calc_constants_used'] = consts

            # Spindle temperature estimate — only if inputs exist; otherwise None
            try:
                spindle_temp_est = estimate_spindle_temp(
                    machine_id=row['machine_id'],
                    p_corr_kw=row.get('p_corr_kw'),  # may be None; your function should handle it
                    rpm=row.get('actual_spindle_speed'),
                    coolant_status=row.get('coolant_status'),
                    ambient_c=28.0
                )
                row['spindle_temperature'] = round(spindle_temp_est, 1) if spindle_temp_est is not None else None
            except Exception:
                # If your estimator can't handle None internally, we still don't crash
                row['spindle_temperature'] = row.get('spindle_temperature')  # keep original if any


        # Latest only if no filters
        if not start_time and not end_time:
            return jsonify([rows[0]])

        return jsonify(rows)

    except Exception as e:
        return jsonify({"error": "Failed to fetch machine data", "details": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()






@app.route('/add_production', methods=['POST'])
@token_required
def add_production(current_user):
    data = request.get_json(silent=True) or {}

    required = [
        "machine_id",
        "shift_operator_name",
        "machine_name",
        "machine_no",
        "product_component_name",
        "product_component_no",
        "section_code_name",
        "shift_production_details",
        "machine_status",
    ]
    missing = [k for k in required if k not in data]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    # If details come as an object, store as JSON string; if already a string, keep as-is.
    details = data["shift_production_details"]
    if isinstance(details, (dict, list)):
        details = json.dumps(details, ensure_ascii=False)

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = None
    try:
        cursor = conn.cursor()
        insert_sql = """
            INSERT INTO machine_production (
                machine_id,
                shift_operator_name,
                machine_name,
                machine_no,
                product_component_name,
                product_component_no,
                section_code_name,
                shift_production_details,
                machine_status,
                timestamp
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """
        cursor.execute(
            insert_sql,
            (
                data["machine_id"],
                data["shift_operator_name"],
                data["machine_name"],
                data["machine_no"],
                data["product_component_name"],
                data["product_component_no"],
                data["section_code_name"],
                details,
                data["machine_status"],
            ),
        )
        conn.commit()
        new_id = cursor.lastrowid
        return jsonify({"message": "Production record added successfully", "id": new_id}), 201
    except Error as e:
        if conn:
            conn.rollback()
        return jsonify({"error": "Database error"}), 400
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": "Failed to add production record"}), 400
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


#from datetime import datetime  # make sure this import is present

@app.route('/get_production', methods=['GET'])
@token_required
def get_production(current_user):
    start_time = request.args.get('start_time')
    end_time = request.args.get('end_time')
    limit = request.args.get('limit', default='200')
    machine_id = request.args.get('machine_id')  # NEW: optional filter
    latest = request.args.get('latest', default='0')  # NEW: "1/true" => latest row only

    # Normalize latest flag
    latest = str(latest).strip().lower() in ('1', 'true', 'yes')

    # Validate limit (ignored when latest==True)
    try:
        limit = int(limit)
        if limit <= 0 or limit > 10000:
            raise ValueError
    except ValueError:
        return jsonify({"error": "Invalid limit. Provide a positive integer <= 10000."}), 400

    # Validate times (if provided)
    start_dt = end_dt = None
    dt_format = '%Y-%m-%d %H:%M:%S'
    try:
        if start_time:
            start_dt = datetime.strptime(start_time, dt_format)
        if end_time:
            end_dt = datetime.strptime(end_time, dt_format)
    except ValueError:
        return jsonify({"error": f"Invalid date format. Use {dt_format}"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)

        base_sql = """
            SELECT
                machine_id,
                shift_operator_name,
                machine_name,
                machine_no,
                product_component_name,
                product_component_no,
                section_code_name,
                shift_production_details,
                machine_status,
                mpf_path,
                timestamp
            FROM machine_production
        """

        where_clauses = []
        params = []

        # Time filters
        if start_dt and end_dt:
            where_clauses.append("timestamp BETWEEN %s AND %s")
            params.extend([start_dt, end_dt])
        elif start_dt:
            where_clauses.append("timestamp >= %s")
            params.append(start_dt)
        elif end_dt:
            where_clauses.append("timestamp <= %s")
            params.append(end_dt)

        # NEW: machine_id filter
        if machine_id:
            where_clauses.append("machine_id = %s")
            params.append(machine_id)

        if where_clauses:
            base_sql += " WHERE " + " AND ".join(where_clauses)

        # NEW: if latest requested and machine_id present, just return latest row for that machine
        if latest and machine_id:
            base_sql += " ORDER BY timestamp DESC LIMIT 1"
        else:
            base_sql += " ORDER BY timestamp DESC LIMIT %s"
            params.append(limit)

        cursor.execute(base_sql, params)
        rows = cursor.fetchall()

        result = []
        for r in rows:
            result.append({
                "machine_id": r["machine_id"],
                "shift_operator_name": r["shift_operator_name"],
                "machine_name": r["machine_name"],
                "machine_no": r["machine_no"],
                "product_component_name": r["product_component_name"],
                "product_component_no": r["product_component_no"],
                "section_code_name": r["section_code_name"],
                "shift_production_details": r["shift_production_details"],
                "machine_status": r["machine_status"],
                "mpf_path": r['mpf_path'],
                "timestamp": r["timestamp"].strftime('%Y-%m-%d %H:%M:%S') if r["timestamp"] else None
            })

        return jsonify(result), 200

    except Error:
        return jsonify({"error": "Database error"}), 400
    except Exception:
        return jsonify({"error": "Failed to fetch production data"}), 400
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()








@app.route("/reports/oee", methods=["GET"])
@token_required
def oee_report(current_user):
    machine_id = request.args.get("machine_id")
    from_date = request.args.get("from_date")
    to_date = request.args.get("to_date")
    from_datetime = request.args.get("from_datetime")
    to_datetime = request.args.get("to_datetime")
    export_type = request.args.get("export", "").lower()

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
        
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        
        # Determine date filter for queries
        date_filter = ""
        params = []
        
        if from_datetime:
            date_filter = " AND DATE(timestamp) >= %s"
            params.append(from_datetime.split()[0])
        elif from_date:
            date_filter = " AND DATE(timestamp) >= %s"
            params.append(from_date)
            
        if to_datetime:
            date_filter += " AND DATE(timestamp) <= %s"
            params.append(to_datetime.split()[0])
        elif to_date:
            date_filter += " AND DATE(timestamp) <= %s"
            params.append(to_date)
            
        # If no date filters, use smart fallback (today or last available date)
        if not any([from_date, to_date, from_datetime, to_datetime]):
            # Check if today has production data
            cursor.execute("SELECT COUNT(*) as count FROM machine_production WHERE DATE(timestamp) = CURDATE() AND total_cycle_time != '00:00:00'")
            if cursor.fetchone()['count'] == 0:
                # Use most recent date with data
                cursor.execute("SELECT DATE(timestamp) as latest_date FROM machine_production WHERE total_cycle_time != '00:00:00' ORDER BY timestamp DESC LIMIT 1")
                latest_row = cursor.fetchone()
                if latest_row:
                    date_filter = " AND DATE(timestamp) = %s"
                    params.append(latest_row['latest_date'])
            else:
                date_filter = " AND DATE(timestamp) = CURDATE()"
        # Now, check if any data exists for the given date filter before proceeding with the report generation.
        # Use the date filter to ensure data exists for the range.
        if any([from_date, to_date, from_datetime, to_datetime]):
            # If no filters are given, just check if today's data exists
            cursor.execute(f"SELECT COUNT(*) as count FROM machine_production WHERE 1=1 {date_filter}", params)
            if cursor.fetchone()['count'] == 0:
                return jsonify([]), 200 
                #return jsonify({"error": "No data found for the specified date range"}), 200
        
        # Get machine list (specific machine or all machines)
        if machine_id:
            cursor.execute("SELECT id, oem_name, vfj_no FROM machines WHERE id = %s", (int(machine_id),))
        else:
            cursor.execute("SELECT id, oem_name, vfj_no FROM machines ORDER BY id")
        
        machines = cursor.fetchall()
        if not machines:
            return jsonify({"error": "No machines found"}), 404
            
        oee_data = []
        
        for machine in machines:
            machine_id_current = machine['id']
            #machine_name = f"{machine['oem_name']} #{machine['vfj_no']}" if machine['oem_name'] and machine['vfj_no'] else f"Machine {machine_id_current}"
            machine_name = machine['oem_name']
            vfj_no = machine['vfj_no']
            
            # Calculate Availability: (480 - downtime) / 480
            downtime_query = """
                SELECT COALESCE(SUM(TIMESTAMPDIFF(MINUTE, start_time, end_time)), 0) as total_downtime,
                       MIN(timestamp) as period_start,
                       MAX(timestamp) as period_end,
                       COUNT(*) as downtime_events
                FROM downtime_entries 
                WHERE machine_id = %s
            """ + date_filter
            
            cursor.execute(downtime_query, [machine_id_current] + params)
            downtime_result = cursor.fetchone()
            
            # Convert Decimal to float to avoid type errors
            total_downtime = float(downtime_result['total_downtime'] or 0)
            availability = (480.0 - total_downtime) / 480.0
            
            # Calculate Performance: production_time / 480
            production_query = """
                SELECT COALESCE(SUM(TIME_TO_SEC(total_cycle_time)/60), 0) as total_production_minutes,
                       COUNT(*) as parts_produced,
                       MIN(timestamp) as prod_start,
                       MAX(timestamp) as prod_end
                FROM machine_production 
                WHERE machine_id = %s AND total_cycle_time != '00:00:00'
            """ + date_filter
            
            cursor.execute(production_query, [machine_id_current] + params)
            production_result = cursor.fetchone()
            
            # Convert Decimal to float to avoid type errors
            total_production_time = float(production_result['total_production_minutes'] or 0)
            parts_produced = int(production_result['parts_produced'] or 0)
            performance = total_production_time / 480.0
            
            # Quality: Static 85% as requested
            quality = 0.85
            
            # Overall OEE: Availability × Performance × Quality
            overall_oee = availability * performance * quality
            
            # Determine period start and end
            period_start = None
            period_end = None
            
            if downtime_result['period_start'] and production_result['prod_start']:
                period_start = min(downtime_result['period_start'], production_result['prod_start'])
            elif downtime_result['period_start']:
                period_start = downtime_result['period_start']
            elif production_result['prod_start']:
                period_start = production_result['prod_start']
                
            if downtime_result['period_end'] and production_result['prod_end']:
                period_end = max(downtime_result['period_end'], production_result['prod_end'])
            elif downtime_result['period_end']:
                period_end = downtime_result['period_end']
            elif production_result['prod_end']:
                period_end = production_result['prod_end']
            
            # Calculate snapshot count (total data points used)
            snapshot_count = (int(downtime_result['downtime_events'] or 0)) + parts_produced
            
            oee_data.append({
                "machine_id": machine_id_current,
                "machine_name": machine_name,
                "vfj_no": vfj_no,
                "availability": round(availability, 3),
                "performance": round(performance, 3),
                "quality": round(quality, 3),
                "overall_oee": round(overall_oee, 3),
                "parts_produced": parts_produced,
                "total_downtime_minutes": total_downtime,
                "total_production_minutes": round(total_production_time, 2),
                "snapshot_count": snapshot_count,
                "period_start": period_start.strftime('%Y-%m-%d %H:%M:%S') if period_start else None,
                "period_end": period_end.strftime('%Y-%m-%d %H:%M:%S') if period_end else None
            })

        # Handle export formats
        if export_type == "csv":
            # Build date range info for header
            date_info = ""
            if from_datetime and to_datetime:
                date_info = f"{from_datetime} to {to_datetime}"
            elif from_date and to_date:
                date_info = f"{from_date} to {to_date}"
            elif from_date:
                date_info = f"From {from_date}"
            elif to_date:
                date_info = f"Until {to_date}"
            else:
                date_info = f"Today ({datetime.now().strftime('%Y-%m-%d')})"
            
            machine_info = f"Machine {machine_id}" if machine_id else "All Machines"
            return generate_csv_response(oee_data, f"oee_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", 
                                       "OEE Report", date_info, machine_info)
        elif export_type == "pdf":
            # Build date range info for header
            date_info = ""
            if from_datetime and to_datetime:
                date_info = f"{from_datetime} to {to_datetime}"
            elif from_date and to_date:
                date_info = f"{from_date} to {to_date}"
            elif from_date:
                date_info = f"From {from_date}"
            elif to_date:
                date_info = f"Until {to_date}"
            else:
                date_info = f"Today ({datetime.now().strftime('%Y-%m-%d')})"
            
            machine_info = f"Machine {machine_id}" if machine_id else "All Machines"
            return generate_pdf_response(oee_data, "OEE Report", f"oee_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                                       date_info, machine_info)

        # Default JSON response
        return jsonify({
            "success": True,
            "count": len(oee_data),
            "timestamp": datetime.now().isoformat(),
            "oee_data": oee_data
        }), 200

    except Exception as e:
        return jsonify({"error": "Failed to generate OEE report", "details": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route("/reports/production", methods=["GET"])
@token_required
def production_report(current_user):
    #from datetime import datetime as dt

    machine_id = request.args.get("machine_id")
    from_date = request.args.get("from_date")
    to_date = request.args.get("to_date")
    from_datetime = request.args.get("from_datetime")
    to_datetime = request.args.get("to_datetime")
    export_type = request.args.get("export", "").lower()
    try:
        limit = min(max(1, int(request.args.get("limit", 100))), 1000)
    except:
        limit = 100

    # Build the time window (defaults to "today" if nothing provided)
    # We pass explicit start_dt and end_dt to all totals queries.
    now = datetime.now()
    if from_datetime and to_datetime:
        start_dt = from_datetime
        end_dt = to_datetime
    elif from_datetime:
        start_dt = from_datetime
        end_dt = f"{now.strftime('%Y-%m-%d')} 23:59:59"
    elif to_datetime:
        # assume start of the same day if only to_datetime provided
        d = to_datetime.split(" ")[0]
        start_dt = f"{d} 00:00:00"
        end_dt = to_datetime
    elif from_date and to_date:
        start_dt = f"{from_date} 00:00:00"
        end_dt = f"{to_date} 23:59:59"
    elif from_date:
        start_dt = f"{from_date} 00:00:00"
        end_dt = f"{from_date} 23:59:59"
    elif to_date:
        start_dt = f"{to_date} 00:00:00"
        end_dt = f"{to_date} 23:59:59"
    else:
        # Default to today
        today = now.strftime("%Y-%m-%d")
        start_dt = f"{today} 00:00:00"
        end_dt = f"{today} 23:59:59"

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)

        # ---------------- Existing hourly aggregation (kept intact) ----------------
        base_sql = """
        SELECT
            mp.machine_id,
            mp.shift_operator_name,
            mp.operator_id,
            mp.shift_type,
            mp.job_order_no,
            mp.batch_quantity,
            mp.checklist,
            m.oem_name AS machine_name,
            mp.machine_no,
            mp.product_component_name,
            mp.product_component_no,
            mp.machine_status,
            COUNT(CASE WHEN mp.total_cycle_time != '00:00:00' AND mp.results = 'PASS' THEN 1 END) AS ok_parts,
            COUNT(CASE WHEN mp.total_cycle_time != '00:00:00' AND ((mp.machine_status = 'STOPPED') OR mp.results IS NULL OR mp.results = 'FAIL') THEN 1 END) AS bad_parts,
            DATE_FORMAT(mp.timestamp, '%Y-%m-%d %H:00:00') AS timestamp
        FROM machine_production mp
        JOIN machines m ON m.id = CAST(mp.machine_id AS UNSIGNED)
        WHERE mp.timestamp BETWEEN %s AND %s
        """
        params = [start_dt, end_dt]

        if machine_id:
            base_sql += " AND mp.machine_id = %s"
            params.append(int(machine_id))

        base_sql += """
            GROUP BY 
                mp.machine_id,
                mp.shift_operator_name,
                machine_name,
                mp.machine_no,
                mp.product_component_name,
                mp.product_component_no,
                mp.section_code_name,
                mp.machine_status,
                DATE_FORMAT(mp.timestamp, '%Y-%m-%d %H')
            ORDER BY timestamp DESC
            LIMIT %s
        """
        params.append(limit)

        cursor.execute(base_sql, params)
        results = cursor.fetchall()

        production_data = []
        for row in results:
            production_data.append({
                "machine_id": str(row["machine_id"]),
                "shift_operator_name": row["shift_operator_name"],
                "machine_name": row["machine_name"],
                "operator_id": row["operator_id"],
                "shift_type" : row['shift_type'],
                "job_order_no" : row["job_order_no"],
                "batch_quantity": row["batch_quantity"],
                "checklist": row["checklist"],
                "machine_no": row["machine_no"],
                "product_component_name": row["product_component_name"],
                "product_component_no": row["product_component_no"],
                "machine_status": row["machine_status"],
                "ok_parts": str(row["ok_parts"]),
                "bad_parts": str(row["bad_parts"]),
                "timestamp": row["timestamp"]
            })



        # ---- 1) Total cycle time per machine (window) ----
        cursor.execute("""
            SELECT
                mp.machine_id,
                COALESCE(SUM(TIME_TO_SEC(mp.total_cycle_time)), 0) AS total_cycle_time_seconds
            FROM machine_production mp
            WHERE mp.timestamp BETWEEN %s AND %s
            AND mp.total_cycle_time IS NOT NULL
            AND mp.total_cycle_time != '00:00:00'
            GROUP BY mp.machine_id
        """, [start_dt, end_dt])
        cycle_times = {str(r["machine_id"]): r["total_cycle_time_seconds"] for r in cursor.fetchall()}



        # ---- 2) Total time (first IDLE to last OFFLINE) per machine (window) ----
        cursor.execute("""
            SELECT
                md.machine_id,
                TIMESTAMPDIFF(SECOND,
                    MIN(CASE WHEN md.machine_state='IDLE' THEN md.timestamp END),
                    MAX(CASE WHEN md.machine_state='OFFLINE' THEN md.timestamp END)
                ) AS total_time_seconds
            FROM machine_data md
            WHERE md.timestamp BETWEEN %s AND %s
            GROUP BY md.machine_id
        """, [start_dt, end_dt])
        total_times = {str(r["machine_id"]): (r["total_time_seconds"] or 0) for r in cursor.fetchall()}

        # ---- 4) Total setup time (sum of PAUSED/STOPPED stretches until next non-setup) ----
        cursor.execute("""
            WITH day_data AS (
                SELECT md.machine_id, md.machine_state, md.timestamp AS ts
                FROM machine_data md
                WHERE md.timestamp BETWEEN %s AND %s
            ),
            ordered AS (
                SELECT
                    machine_id,
                    machine_state,
                    ts,
                    CASE WHEN machine_state IN ('PAUSED','STOPPED') THEN 1 ELSE 0 END AS is_setup,
                    LAG(CASE WHEN machine_state IN ('PAUSED','STOPPED') THEN 1 ELSE 0 END)
                        OVER (PARTITION BY machine_id ORDER BY ts) AS prev_is_setup
                FROM day_data
            ),
            setup_starts AS (
                -- starts when we transition from non-setup to setup (or first row is setup)
                SELECT machine_id, ts AS start_ts
                FROM ordered
                WHERE is_setup = 1 AND (prev_is_setup IS NULL OR prev_is_setup = 0)
            ),
            setup_spans AS (
                SELECT
                    s.machine_id,
                    s.start_ts,
                    (
                        SELECT MIN(o2.ts)
                        FROM ordered o2
                        WHERE o2.machine_id = s.machine_id
                        AND o2.ts > s.start_ts
                        AND o2.is_setup = 0
                    ) AS end_ts
                FROM setup_starts s
            )
            SELECT
                machine_id,
                COALESCE(SUM(TIMESTAMPDIFF(SECOND, start_ts, COALESCE(end_ts, %s))), 0) AS setup_seconds
            FROM setup_spans
            GROUP BY machine_id
        """, [start_dt, end_dt, end_dt])
        setup_times = {str(r["machine_id"]): r["setup_seconds"] for r in cursor.fetchall()}




        # ---- 3) Total idle time (sum of IDLE→RUNNING gaps) per machine (window) ----
        cursor.execute("""
            WITH ordered AS (
                SELECT
                    md.machine_id,
                    md.machine_state,
                    md.timestamp AS ts,
                    LEAD(md.timestamp) OVER (PARTITION BY md.machine_id ORDER BY md.timestamp) AS next_ts,
                    LEAD(md.machine_state) OVER (PARTITION BY md.machine_id ORDER BY md.timestamp) AS next_state
                FROM machine_data md
                WHERE md.timestamp BETWEEN %s AND %s
            )
            SELECT
                machine_id,
                COALESCE(SUM(TIMESTAMPDIFF(SECOND, ts, next_ts)), 0) AS idle_seconds
            FROM ordered
            WHERE machine_state='IDLE' AND next_state='RUNNING' AND next_ts IS NOT NULL
            GROUP BY machine_id
        """, [start_dt, end_dt])
        idle_times = {str(r["machine_id"]): r["idle_seconds"] for r in cursor.fetchall()}

        mp_names_sql = """
            WITH latest_mp AS (
                SELECT
                    CAST(mp.machine_id AS UNSIGNED) AS machine_id,
                    mp.machine_name,
                    mp.machine_no,
                    ROW_NUMBER() OVER (
                        PARTITION BY CAST(mp.machine_id AS UNSIGNED)
                        ORDER BY mp.timestamp DESC
                    ) AS rn
                FROM machine_production mp
            )
            SELECT machine_id, machine_name, machine_no
            FROM latest_mp
            WHERE rn = 1
        """
        cursor.execute(mp_names_sql)
        name_map = {
            str(r["machine_id"]): {
                "machine_name": r["machine_name"],
                "vfj_no": r["machine_no"]  # treat machine_no as VFJ
            }
            for r in cursor.fetchall()
        }

        # ---- Combine results ----
        def hms(seconds: int) -> str:
            h, m, s = seconds // 3600, (seconds % 3600) // 60, seconds % 60
            return f"{h:02}:{m:02}:{s:02}"

        all_machine_ids = set(cycle_times) | set(total_times) | set(idle_times)
        totals = []
        for mid in all_machine_ids:
            meta = name_map.get(mid, {})
            totals.append({
                "machine_id": mid,
                "vfj_no": meta.get("vfj_no"),
                "machine_name": meta.get("machine_name"),
                "total_cycle_time": hms(cycle_times.get(mid, 0)),
                "total_time": hms(total_times.get(mid, 0)),
                "total_idle_time": hms(idle_times.get(mid, 0)),
                "total_setup_time": hms(setup_times.get(mid, 0))
            })

        
        # ---------------- Exports (unchanged, just use production_data) ----------------
        if export_type == "csv":
            date_info = f"{start_dt} to {end_dt}"
            machine_info = f"Machine {machine_id}" if machine_id else "All Machines"
            return generate_csv_response(
                production_data,
                f"production_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                "Production Report",
                date_info,
                machine_info
            )

        if export_type == "pdf":
            date_info = f"{start_dt} to {end_dt}"
            machine_info = f"Machine {machine_id}" if machine_id else "All Machines"
            return generate_pdf_response(
                production_data,
                "Production Report",
                f"production_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                date_info,
                machine_info
            )

        # ---------------- Final JSON ----------------
        return jsonify({
            "success": True,
            "count": len(production_data),
            "timestamp": datetime.now().isoformat(),
            "shift_data": production_data,
            "totals": totals
        }), 200

    except Exception as e:
        return jsonify({"error": "Failed to generate production report", "details": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route("/reports/breakdowns", methods=["GET"])
@token_required
def breakdowns_report(current_user):
    """List episodes where machine_state runs as BREAKDOWN and then changes to IDLE."""
    def hms(sec: int) -> str:
        if not sec or sec < 0:
            return "00:00:00"
        h = sec // 3600
        m = (sec % 3600) // 60
        s = sec % 60
        return f"{h:02}:{m:02}:{s:02}"

    vfj_no = request.args.get("vfj_no", "").strip()
    from_date = request.args.get("from_date")  # YYYY-MM-DD
    to_date = request.args.get("to_date")      # YYYY-MM-DD
    try:
        limit = min(max(1, int(request.args.get("limit", 100))), 1000)
    except:
        limit = 100

    # Build filters for base CTE
    base_filters = ["1=1"]
    params = []

    if vfj_no:
        base_filters.append("m.vfj_no = %s")
        params.append(vfj_no)

    if from_date:
        base_filters.append("md.timestamp >= %s")
        params.append(f"{from_date} 00:00:00")

    if to_date:
        base_filters.append("md.timestamp <= %s")
        params.append(f"{to_date} 23:59:59")

    sql = f"""
    WITH base AS (
        SELECT
            md.machine_id,
            md.timestamp,
            md.machine_state,
            m.vfj_no,
            m.oem_name AS machine_name
        FROM machine_data md
        JOIN machines m ON m.id = md.machine_id
        WHERE {' AND '.join(base_filters)}
    ),
    ordered AS (
        SELECT
            b.*,
            LAG(b.machine_state) OVER (PARTITION BY b.machine_id ORDER BY b.timestamp) AS prev_state,
            CASE
                WHEN LAG(b.machine_state) OVER (PARTITION BY b.machine_id ORDER BY b.timestamp) IS NULL
                     OR b.machine_state <> LAG(b.machine_state) OVER (PARTITION BY b.machine_id ORDER BY b.timestamp)
                THEN 1 ELSE 0
            END AS is_new_run
        FROM base b
    ),
    runs AS (
        SELECT
            machine_id, vfj_no, machine_name, machine_state, timestamp,
            SUM(is_new_run) OVER (
                PARTITION BY machine_id ORDER BY timestamp
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS run_id
        FROM ordered
    ),
    agg AS (
        SELECT
            machine_id, vfj_no, machine_name, run_id,
            MIN(timestamp) AS run_start_ts,
            MIN(machine_state) AS run_state     -- identical within a run
        FROM runs
        GROUP BY machine_id, vfj_no, machine_name, run_id
    )
    SELECT
        a.machine_id,
        a.vfj_no,
        a.machine_name,
        a.run_start_ts AS breakdown_start,
        n.run_start_ts AS idle_start,
        TIMESTAMPDIFF(SECOND, a.run_start_ts, n.run_start_ts) AS duration_seconds
    FROM agg a
    JOIN agg n
      ON n.machine_id = a.machine_id
     AND n.run_id = a.run_id + 1        -- next run
    WHERE a.run_state = 'BREAKDOWN'
      AND n.run_state = 'IDLE'
    ORDER BY idle_start DESC
    LIMIT %s
    """

    params2 = params + [limit]

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cur = None
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params2)
        rows = cur.fetchall() or []

        out = []
        for r in rows:
            dur = int(r["duration_seconds"] or 0)
            out.append({
                "machine_id": r["machine_id"],
                "vfj_no": r["vfj_no"],
                "machine_name": r["machine_name"],
                "breakdown_start": r["breakdown_start"].strftime("%Y-%m-%d %H:%M:%S") if r["breakdown_start"] else None,
                "idle_start": r["idle_start"].strftime("%Y-%m-%d %H:%M:%S") if r["idle_start"] else None,
                "duration_seconds": dur,
                "duration_hms": hms(dur)
            })

        return jsonify({
            "success": True,
            "count": len(out),
            "filters": {
                "vfj_no": vfj_no or None,
                "from_date": from_date or None,
                "to_date": to_date or None,
                "limit": limit
            },
            "breakdowns": out
        }), 200

    except Exception as e:
        return jsonify({"error": "Failed to fetch breakdown history", "details": str(e)}), 500
    finally:
        if cur: cur.close()
        if conn: conn.close()




def _fetch_machine_snapshot(cursor, machine_id: int):
    cursor.execute("""
        SELECT id, oem_name, vfj_no, ip_address, control_type, control_details, control_model
        FROM machines
        WHERE id = %s
        LIMIT 1
    """, (machine_id,))
    return cursor.fetchone()

def _ensure_times(payload):
    start_time = payload.get("start_time")
    end_time = payload.get("end_time")
    if not start_time or not end_time:
        raise ValueError("start_time and end_time are required (YYYY-MM-DD HH:MM:SS).")
    # Optional: validate/parse
    # datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
    # datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S")
    return start_time, end_time


# States you use in your table (adjust if your app uses different casing/values)
FAIL_STATE = "BREAKDOWN"
UP_STATES = ("RUNNING", "IDLE")

def _filters_sql_and_params(machine_id, start, end):
    where = ["1=1"]
    params = []
    if machine_id is not None:
        where.append("machine_id = %s")
        params.append(machine_id)
    if start:
        where.append("timestamp >= %s")
        params.append(start)
    if end:
        where.append("timestamp <= %s")
        params.append(end)
    return " AND ".join(where), params






FAIL_STATE = "BREAKDOWN"
UP_STATES = ("RUNNING", "IDLE")

def _filters_sql_and_params(machine_id, start, end):
    where = ["1=1"]
    params = []
    if machine_id is not None:
        where.append("machine_id = %s")
        params.append(machine_id)
    if start:
        where.append("timestamp >= %s")
        params.append(start)
    if end:
        where.append("timestamp <= %s")
        params.append(end)
    return " AND ".join(where), params

def _fmt_hms(total_seconds):
    if total_seconds is None:
        return None
    secs = int(round(total_seconds))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h} hour" + ("s" if h != 1 else ""))
    if m:
        parts.append(f"{m} min")
    # If zero hours and zero minutes, still show seconds
    if s or not parts:
        parts.append(f"{s} sec")
    return " ".join(parts)


@app.route("/metrics/mtbf-mttr", methods=["GET"])
def mtbf_mttr():
    """
    Returns MTBF and MTTR per machine, with machines.oem_name (machine_name) & vfj_no
    Query params:
      - machine_id (optional): int
      - start (optional): 'YYYY-MM-DD HH:MM:SS'
      - end   (optional): 'YYYY-MM-DD HH:MM:SS'
    """
    machine_id = request.args.get("machine_id", type=int)
    start = request.args.get("from_date")
    end = request.args.get("to_date")
    export_type = (request.args.get("export") or "").lower()

    where_sql, params = _filters_sql_and_params(machine_id, start, end)

    # ---- MTBF (avg time between consecutive BREAKDOWNs) ----
    mtbf_sql = f"""
        WITH breakdowns AS (
            SELECT machine_id, timestamp AS bd_time
            FROM machine_data
            WHERE {where_sql} AND machine_state = %s
            ORDER BY machine_id, timestamp
        ),
        numbered AS (
            SELECT
                machine_id,
                bd_time,
                ROW_NUMBER() OVER (PARTITION BY machine_id ORDER BY bd_time) AS rn
            FROM breakdowns
        ),
        joined AS (
            SELECT
                n1.machine_id,
                n1.bd_time AS curr_bd,
                n2.bd_time AS prev_bd
            FROM numbered n1
            LEFT JOIN numbered n2
              ON n1.machine_id = n2.machine_id
             AND n1.rn = n2.rn + 1
        )
        SELECT
            machine_id,
            COUNT(*) - SUM(CASE WHEN prev_bd IS NULL THEN 1 ELSE 0 END) AS failure_pairs,
            AVG(CASE WHEN prev_bd IS NOT NULL THEN TIMESTAMPDIFF(SECOND, prev_bd, curr_bd) END) AS mtbf_seconds
        FROM joined
        GROUP BY machine_id
    """
    mtbf_params = params + [FAIL_STATE]

    # ---- MTTR (avg time from BREAKDOWN to next UP state) ----
    up_placeholders = ", ".join(["%s"] * len(UP_STATES))
    mttr_sql = f"""
        WITH repairs AS (
            SELECT
                md.machine_id,
                md.timestamp AS breakdown_time,
                (
                    SELECT MIN(md2.timestamp)
                    FROM machine_data md2
                    WHERE md2.machine_id = md.machine_id
                      AND md2.timestamp > md.timestamp
                      AND md2.machine_state IN ({up_placeholders})
                      {"AND md2.timestamp >= %s" if start else ""}
                      {"AND md2.timestamp <= %s" if end else ""}
                ) AS repair_time
            FROM machine_data md
            WHERE {where_sql} AND md.machine_state = %s
        )
        SELECT
            machine_id,
            COUNT(*) AS breakdowns,
            SUM(CASE WHEN repair_time IS NOT NULL THEN 1 ELSE 0 END) AS repairs_completed,
            AVG(CASE WHEN repair_time IS NOT NULL
                     THEN TIMESTAMPDIFF(SECOND, breakdown_time, repair_time)
                END) AS mttr_seconds
        FROM repairs
        GROUP BY machine_id
    """

    mttr_params = list(UP_STATES)
    if start:
        mttr_params.append(start)
    if end:
        mttr_params.append(end)
    mttr_params.extend(params)
    mttr_params.append(FAIL_STATE)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # MTBF
            cur.execute(mtbf_sql, mtbf_params)
            mtbf_rows = cur.fetchall()

            # MTTR
            cur.execute(mttr_sql, mttr_params)
            mttr_rows = cur.fetchall()

        # Normalize MTBF
        mtbf_map = {}
        for r in mtbf_rows:
            if isinstance(r, dict):
                mid = r["machine_id"]
                failure_pairs = r["failure_pairs"] or 0
                mtbf_seconds = r["mtbf_seconds"]
            else:
                mid, failure_pairs, mtbf_seconds = r
                failure_pairs = failure_pairs or 0
            mtbf_map[mid] = {
                "machine_id": mid,
                "failures_counted_for_mtbf": int(failure_pairs),
                "mtbf_seconds": float(mtbf_seconds) if mtbf_seconds is not None else None,
            }

        # Normalize MTTR
        mttr_map = {}
        for r in mttr_rows:
            if isinstance(r, dict):
                mid = r["machine_id"]
                breakdowns = r["breakdowns"] or 0
                repairs_completed = r["repairs_completed"] or 0
                mttr_seconds = r["mttr_seconds"]
            else:
                mid, breakdowns, repairs_completed, mttr_seconds = r
                breakdowns = breakdowns or 0
                repairs_completed = repairs_completed or 0
            mttr_map[mid] = {
                "machine_id": mid,
                "breakdowns": int(breakdowns),
                "repairs_completed": int(repairs_completed),
                "mttr_seconds": float(mttr_seconds) if mttr_seconds is not None else None,
            }

        # Merge keys
        machine_ids = sorted(set(mtbf_map.keys()) | set(mttr_map.keys()))
        if machine_id is not None:
            machine_ids = [machine_id] if machine_id in machine_ids else machine_ids

        # ---- Pull machine_name (oem_name) and vfj_no from machines table ----
        machine_meta = {}
        if machine_ids:
            placeholders = ", ".join(["%s"] * len(machine_ids))
            meta_sql = f"""
                SELECT id AS machine_id, oem_name, vfj_no
                FROM machines
                WHERE id IN ({placeholders})
            """
            conn2 = get_db_connection()
            try:
                with conn2.cursor() as cur2:
                    cur2.execute(meta_sql, machine_ids)
                    rows = cur2.fetchall()
                for r in rows:
                    if isinstance(r, dict):
                        machine_meta[r["machine_id"]] = {
                            "machine_name": r["oem_name"],
                            "vfj_no": r["vfj_no"]
                        }
                    else:
                        mid, oem_name, vfj_no = r
                        machine_meta[mid] = {
                            "machine_name": oem_name,
                            "vfj_no": vfj_no
                        }
            finally:
                try:
                    conn2.close()
                except Exception:
                    pass

        # Build final response rows
        results = []
        for mid in machine_ids:
            mtbf_seconds = mtbf_map.get(mid, {}).get("mtbf_seconds")
            mttr_seconds = mttr_map.get(mid, {}).get("mttr_seconds")

            row = {
                "machine_id": mid,
                "machine_name": machine_meta.get(mid, {}).get("machine_name"),
                "vfj_no": machine_meta.get(mid, {}).get("vfj_no"),

                "breakdowns": mttr_map.get(mid, {}).get("breakdowns", 0),
                "repairs_completed": mttr_map.get(mid, {}).get("repairs_completed", 0),
                "mttr_seconds": mttr_seconds,
                "mttr_minutes": round(mttr_seconds / 60.0, 2) if mttr_seconds is not None else None,
                "mttr_readable": _fmt_hms(mttr_seconds),
                "mtbf_readable": _fmt_hms(mtbf_seconds),
                "failures_counted_for_mtbf": mtbf_map.get(mid, {}).get("failures_counted_for_mtbf", 0),
                "mtbf_seconds": mtbf_seconds,
                "mtbf_hours": round(mtbf_seconds / 3600.0, 2) if mtbf_seconds is not None else None,
                #  "mtbf_seconds": None,
                # "mtbf_hours": None
            }
            results.append(row)

        # csv/pdf export here
        if export_type in ("csv", "pdf"):
            # Prepare flat rows with nice column names
            export_rows = []
            for r in results:
                export_rows.append({
                    "Machine ID": r['machine_id'],
                    "Machine Name": r.get("machine_name"),
                    "VFJ No": r.get("vfj_no"),
                    "Breakdowns": r.get("breakdowns"),
                    "Repairs Completed": r.get("repairs_completed"),
                    "MTTR (seconds)": r.get("mttr_seconds"),
                    "MTTR (minutes)": r.get("mttr_minutes"),
                    "Failures Counted (MTBF)": r.get("failures_counted_for_mtbf"),
                    "MTBF (seconds)": r.get("mtbf_seconds"),
                    "MTBF (hours)": r.get("mtbf_hours"),
                })
             # Title & metadata
            title = "MTBF / MTTR Report"
            date_info = f"{start or '—'} to {end or '—'}"
            machine_info = f"Machine {machine_id}" if machine_id else "All Machines"

            # Filename stamp (reuse your datetime if available)
            try:
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            except:
                #from datetime import datetime as _dt
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            if export_type == "csv":
                return generate_csv_response(
                    export_rows,
                    f"mtbf_mttr_{stamp}.csv",
                    title,
                    date_info,
                    machine_info
                )
            else:  # pdf
                return generate_pdf_response(
                    export_rows,
                    title,
                    f"mtbf_mttr_{stamp}.pdf",
                    date_info,
                    machine_info
                )
        # -----------------------------------------


        payload = {
            "filters": {
                "machine_id": machine_id,
                "start": start,
                "end": end
            },
            "states": {
                "failure_state": FAIL_STATE,
                "up_states": list(UP_STATES)
            },
            "results": results
        }
        return jsonify(payload), 200

    finally:
        try:
            conn.close()
        except Exception:
            pass




@app.route("/api/production/target", methods=["POST"])
@token_required
def add_production_target(current_user):
    """
    Body JSON:
    {
      "machine_id": 3,
      "start_time": "2025-09-19 08:00:00",
      "end_time":   "2025-09-19 16:00:00",
      "product_target": 120   # required
    }
    Creates/updates the target for that (machine_id, start_time, end_time) slot.
    Snapshots machine details from machines table.
    """
    data = request.get_json(silent=True) or {}
    try:
        machine_id = int(data.get("machine_id", 0))
        if machine_id <= 0:
            return jsonify({"error": "machine_id is required and must be > 0"}), 400

        start_time, end_time = _ensure_times(data)

        product_target = data.get("product_target")
        if product_target is None:
            return jsonify({"error": "product_target is required"}), 400
        try:
            product_target = int(product_target)
            if product_target < 0:
                return jsonify({"error": "product_target must be >= 0"}), 400
        except:
            return jsonify({"error": "product_target must be an integer"}), 400

        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        cursor = conn.cursor(dictionary=True)

        # Snapshot machine details
        m = _fetch_machine_snapshot(cursor, machine_id)
        if not m:
            return jsonify({"error": f"Machine id={machine_id} not found"}), 404

        # Upsert target + snapshot
        upsert_sql = """
            INSERT INTO production_entries
                (machine_id, start_time, end_time,
                 machine_name, vfj_no, ip_address, control_type, control_details, control_model,
                 product_target)
            VALUES
                (%s, %s, %s,
                 %s, %s, %s, %s, %s, %s,
                 %s)
            ON DUPLICATE KEY UPDATE
                product_target = VALUES(product_target),
                -- in case machine snapshot changed, keep it fresh:
                machine_name   = VALUES(machine_name),
                vfj_no         = VALUES(vfj_no),
                ip_address     = VALUES(ip_address),
                control_type   = VALUES(control_type),
                control_details= VALUES(control_details),
                control_model  = VALUES(control_model)
        """
        cursor.execute(
            upsert_sql,
            (
                machine_id, start_time, end_time,
                m["oem_name"], m["vfj_no"],  m["ip_address"], m["control_type"], m["control_details"], m["control_model"],
                product_target
            )
        )
        conn.commit()
        return jsonify({"success": True, "message": "Target saved/updated"}), 200

    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        return jsonify({"error": "Failed to add/update production target", "details": str(e)}), 500
    finally:
        try:
            cursor.close()
            conn.close()
        except:
            pass

@app.route("/api/production/entries", methods=["GET"])
@token_required
def list_production_entries(current_user):
    """
    Display entries from production_entries, with CSV/PDF export.

    Query params (all optional):
      - machine_id      : int
      - from_datetime   : "YYYY-MM-DD HH:MM:SS" (filters start_time >=)
      - to_datetime     : "YYYY-MM-DD HH:MM:SS" (filters end_time <=)
      - for_date        : "YYYY-MM-DD" (convenience day filter)
      - limit           : default 100, max 5000 (ignored for exports)
      - page            : default 1 (ignored for exports)
      - export          : "csv" or "pdf" to export the filtered result set
    """
    def fmt(x):
        # Safely convert datetime/date/time to string; otherwise return as-is/str
        if isinstance(x, (datetime, date, time)):
            try:
                return x.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                return x.isoformat()
        return (str(x) if x is not None else None)

    machine_id = request.args.get("machine_id")
    from_dt = request.args.get("from_datetime")
    to_dt = request.args.get("to_datetime")
    for_date = request.args.get("for_date")
    export_type = (request.args.get("export") or "").lower()

    # Pagination only applies to JSON (non-export) responses
    try:
        limit = min(max(1, int(request.args.get("limit", 100))), 5000)
    except:
        limit = 100
    try:
        page = max(1, int(request.args.get("page", 1)))
    except:
        page = 1
    offset = (page - 1) * limit

    # Nice header text for exports
    if for_date:
        date_info = f"{for_date} 00:00:00 to {for_date} 23:59:59"
    else:
        left = from_dt or "(any)"
        right = to_dt or "(any)"
        date_info = f"{left} to {right}"
    machine_info = f"Machine {machine_id}" if machine_id else "All Machines"

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor(dictionary=True)
    try:
        where = ["1=1"]
        params = []

        if machine_id:
            try:
                mid = int(machine_id)
                where.append("machine_id = %s")
                params.append(mid)
            except:
                return jsonify({"error": "machine_id must be an integer"}), 400

        if for_date:
            where.append("start_time >= %s")
            params.append(f"{for_date} 00:00:00")
            where.append("end_time <= %s")
            params.append(f"{for_date} 23:59:59")
        else:
            if from_dt:
                where.append("start_time >= %s")
                params.append(from_dt)
            if to_dt:
                where.append("end_time <= %s")
                params.append(to_dt)

        where_sql = " AND ".join(where)

        # machine_production.machine_id is VARCHAR — keep it as-is
        parts_sql = """
            SELECT mp.machine_id, COUNT(*) AS pass_parts
            FROM machine_production mp
            WHERE {machine_clause}
            AND TIME_TO_SEC(mp.total_cycle_time) > 0
            AND LOWER(TRIM(mp.results)) = 'pass'
            AND EXISTS (
                    SELECT 1
                    FROM production_entries pe
                    WHERE pe.machine_id = mp.machine_id
                    AND pe.start_time IS NOT NULL
                    AND pe.end_time   IS NOT NULL
                    AND COALESCE(mp.shift_start, mp.`timestamp`) >= pe.start_time
                    AND COALESCE(mp.shift_start, mp.`timestamp`) <  pe.end_time
            )
            GROUP BY mp.machine_id
        """.format(
            machine_clause="mp.machine_id = %s" if machine_id else "1=1"
        )

        parts_params = [machine_id] if machine_id else []
        cursor.execute(parts_sql, parts_params)
        parts_map = {row["machine_id"]: int(row["pass_parts"] or 0)
                    for row in cursor.fetchall()}




        # If exporting, fetch the FULL filtered dataset (no pagination)
        if export_type in ("csv", "pdf"):
            list_sql_full = f"""
                SELECT *
                FROM production_entries
                WHERE {where_sql}
                ORDER BY start_time DESC, id DESC
            """
            cursor.execute(list_sql_full, params)
            rows = cursor.fetchall()

            entries = [{
                "id": r["id"],
                "machine_id": r["machine_id"],
                "start_time": fmt(r["start_time"]),
                "end_time": fmt(r["end_time"]),
                "machine_name": r["machine_name"],
                "vfj_no": r["vfj_no"],
                "ip_address": r["ip_address"],
                "control_type": r["control_type"],
                "control_details": r["control_details"],
                "control_model": r["control_model"],
                "product_target": r["product_target"],
                # CHANGED: production_done from machine_production PASS counts map
                "production_done": parts_map.get(r["machine_id"], 0),
                "good_products": r["good_products"],
                 # ✅ parse deviation safely
                "deviation": json.loads(r["deviation"]) if r.get("deviation") else None,
                "bad_products": r["bad_products"],
                "created_at": fmt(r["created_at"]),
                "updated_at": fmt(r["updated_at"]),
            } for r in rows]

            report_title = "Production Entries"
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"production_entries_{ts}.{'csv' if export_type=='csv' else 'pdf'}"

            if export_type == "csv":
                return generate_csv_response(entries, filename, report_title, date_info, machine_info)
            else:
                return generate_pdf_response(entries, report_title, filename, date_info, machine_info)

        # ---------- Regular JSON path (with pagination) ----------
        # total count
        count_sql = f"SELECT COUNT(*) AS total FROM production_entries WHERE {where_sql}"
        cursor.execute(count_sql, params)
        total = cursor.fetchone()["total"]

        # fetch page
        list_sql = f"""
            SELECT *
            FROM production_entries
            WHERE {where_sql}
            ORDER BY start_time DESC, id DESC
            LIMIT %s OFFSET %s
        """
        cursor.execute(list_sql, params + [limit, offset])
        rows = cursor.fetchall()
        #print(f"machine id : {row['machine_id']}")

        # print(f"parts count: {parts_map["3"]}")
        # print(rows)

        entries = [{
            "id": r["id"],
            "machine_id": r["machine_id"],
            "start_time": fmt(r["start_time"]),
            "end_time": fmt(r["end_time"]),
            "machine_name": r["machine_name"],
            "vfj_no": r["vfj_no"],
            "ip_address": r["ip_address"],
            "control_type": r["control_type"],
            "control_details": r["control_details"],
            "control_model": r["control_model"],
            "product_target": r["product_target"],
            # CHANGED: production_done from machine_production PASS counts map
            "production_done": parts_map.get(str(r["machine_id"]), 0),
            "good_products": r["good_products"],
            "bad_products": r["bad_products"],
            # ✅ Parse deviation if it’s JSON, otherwise pass through
            "deviation": json.loads(r["deviation"]) if r.get("deviation") else None,
            "created_at": fmt(r["created_at"]),
            "updated_at": fmt(r["updated_at"]),
        } for r in rows]

        return jsonify({
            "success": True,
            "count": len(entries),
            "page": page,
            "limit": limit,
            "total": total,
            "entries": entries
        }), 200

    except Exception as e:
        return jsonify({"error": "Failed to fetch production entries", "details": str(e)}), 500
    finally:
        try:
            cursor.close()
            conn.close()
        except:
            pass





@app.route("/api/production/entries/update-quality", methods=["POST"])
@token_required
def update_production_entry_quality_by_id(current_user):
    """
    Update quality counts for a production_entries row by ID (no insert).

    Body JSON:
    {
      "id": 1,                     # required
      "good_products": 95,         # required (int >= 0)
      "bad_products": 5,           # required (int >= 0)
      "production_done": 100       # optional; if absent -> set to good+bad
    }
    """
    data = request.get_json(silent=True) or {}

    # Validate input
    try:
        entry_id = int(data.get("id", 0))
    except:
        return jsonify({"error": "id must be an integer"}), 400
    if entry_id <= 0:
        return jsonify({"error": "id is required and must be > 0"}), 400

    if "good_products" not in data or "bad_products" not in data:
        return jsonify({"error": "good_products and bad_products are required"}), 400
    try:
        good_products = max(0, int(data["good_products"]))
        bad_products  = max(0, int(data["bad_products"]))
    except:
        return jsonify({"error": "good_products and bad_products must be integers"}), 400

    # production_done: compute if not provided
    prod_done = data.get("production_done")
    if prod_done is None:
        production_done = good_products + bad_products
    else:
        try:
            production_done = max(0, int(prod_done))
        except:
            return jsonify({"error": "production_done must be an integer"}), 400
        
    

    # DB ops
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    cursor = conn.cursor(dictionary=True)

    try:
        # Check existence
        cursor.execute("SELECT id, product_target, production_done FROM production_entries WHERE id = %s LIMIT 1", (entry_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"success": False, "message": f"No production entry with id={entry_id}"}), 404
        
        #production_done = int(row.get("production_done") or 0)

        if production_done != good_products + bad_products:
            return jsonify({"status": False, "message": "production done and good, bad products count mismatch"}), 400
        
        product_target = int(row.get("product_target") or 0)

        # Build deviation JSON
        diff = production_done - product_target
        #print(f"diff : {diff}, {production_done}, {product_target}")
        if diff > 0:
            deviation_obj = {"overproduction": diff}
        elif diff < 0:
            deviation_obj = {"shortfall": abs(diff)}
        else:
            deviation_obj = {"on_target": 0}

        deviation_text = json.dumps(deviation_obj, separators=(",", ":"))

        

        cursor.execute("""
            UPDATE production_entries
            SET good_products   = %s,
                bad_products    = %s,
                production_done = %s,
                deviation       = %s
            WHERE id = %s
        """, (good_products, bad_products, production_done, deviation_text, entry_id))
        conn.commit()

        # (Optional) return the refreshed row
        cursor.execute("SELECT * FROM production_entries WHERE id = %s", (entry_id,))
        updated = cursor.fetchone()

        # Safe formatting for datetime fields
        import datetime as dt
        def fmt(x):
            return x.strftime("%Y-%m-%d %H:%M:%S") if isinstance(x, (dt.datetime, dt.date, dt.time)) else (str(x) if x is not None else None)

        return jsonify({
            "success": True,
            "message": "Quality counts updated",
            "entry": {
                "id": updated["id"],
                "machine_id": updated["machine_id"],
                "start_time": fmt(updated["start_time"]),
                "end_time": fmt(updated["end_time"]),
                "machine_name": updated["machine_name"],
                "ip_address": updated["ip_address"],
                "control_type": updated["control_type"],
                "control_details": updated["control_details"],
                "control_model": updated["control_model"],
                "product_target": updated["product_target"],
                "production_done": updated["production_done"],
                "good_products": updated["good_products"],
                "bad_products": updated["bad_products"],
                "deviation": updated["deviation"],
                "created_at": fmt(updated["created_at"]),
                "updated_at": fmt(updated["updated_at"]),
            }
        }), 200

    except Exception as e:
        return jsonify({"error": "Failed to update quality counts", "details": str(e)}), 500
    finally:
        try:
            cursor.close()
            conn.close()
        except:
            pass


@app.route("/reports/downtime", methods=["GET"])
@token_required
def downtime_report(current_user):
    machine_id = request.args.get("machine_id")
    from_date = request.args.get("from_date")
    to_date = request.args.get("to_date")
    from_datetime = request.args.get("from_datetime")
    to_datetime = request.args.get("to_datetime")
    export_type = request.args.get("export", "").lower()
    try: limit = min(max(1, int(request.args.get("limit", 100))), 1000)
    except: limit = 100

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
        
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        
        # Build base query
        query = """
            SELECT
                de.machine_id,
                de.reason,
                de.start_time,
                de.end_time,
                TIMESTAMPDIFF(MINUTE, de.start_time, de.end_time) AS duration_minutes,
                de.timestamp,
                m.oem_name,
                m.vfj_no
            FROM downtime_entries de
            JOIN machines m ON m.id = de.machine_id
            WHERE 1=1
        """
        params = []

        # Add machine filter
        if machine_id:
            query += " AND de.machine_id = %s"
            params.append(int(machine_id))

        # Add time filters (datetime takes priority over date)
        if from_datetime:
            query += " AND de.timestamp >= %s"
            params.append(from_datetime)
        elif from_date:
            query += " AND de.timestamp >= %s"
            params.append(f"{from_date} 00:00:00")

        if to_datetime:
            query += " AND de.timestamp <= %s"
            params.append(to_datetime)
        elif to_date:
            query += " AND de.timestamp <= %s"
            params.append(f"{to_date} 23:59:59")

        # If no time filters provided, try today first, then fallback
        if not any([from_date, to_date, from_datetime, to_datetime]):
            # Try today first
            today_query = query + " AND DATE(de.timestamp) = CURDATE()"
            cursor.execute(today_query + " ORDER BY de.timestamp DESC LIMIT %s", params + [limit])
            today_results = cursor.fetchall()
            
            if not today_results:
                # Fallback to most recent date with data
                cursor.execute("""
                    SELECT DATE(timestamp) as latest_date 
                    FROM downtime_entries 
                    ORDER BY timestamp DESC 
                    LIMIT 1
                """)
                latest_date_row = cursor.fetchone()
                if latest_date_row:
                    latest_date = latest_date_row['latest_date']
                    query += " AND DATE(de.timestamp) = %s"
                    params.append(latest_date)
            else:
                # Use today's results
                results = today_results
        
        if not any([from_date, to_date, from_datetime, to_datetime]) and not today_results:
            query += " ORDER BY de.timestamp DESC LIMIT %s"
            params.append(limit)
            cursor.execute(query, params)
            results = cursor.fetchall()
        elif any([from_date, to_date, from_datetime, to_datetime]):
            query += " ORDER BY de.timestamp DESC LIMIT %s"
            params.append(limit)
            cursor.execute(query, params)
            results = cursor.fetchall()

        # Format results for individual downtime events
        downtime_data = []
        for row in results:
            machine_name = f"{row['oem_name']} #{row['vfj_no']}" if row['oem_name'] and row['vfj_no'] else f"Machine {row['machine_id']}"
            
            downtime_data.append({
                "machine_id": row["machine_id"],
                "machine_name": machine_name,
                "vfj_no": str(row["vfj_no"] or ""),
                "reason": row["reason"],
                "start_time": row["start_time"].strftime('%Y-%m-%d %H:%M:%S') if row["start_time"] else None,
                "end_time": row["end_time"].strftime('%Y-%m-%d %H:%M:%S') if row["end_time"] else None,
                "duration_minutes": float(row["duration_minutes"] or 0),
                "timestamp": row["timestamp"].strftime('%Y-%m-%d %H:%M:%S') if row["timestamp"] else None
            })

        # Also get summary statistics
        summary_query = """
            SELECT
                de.machine_id,
                de.reason,
                COUNT(*) as occurrence_count,
                SUM(TIMESTAMPDIFF(MINUTE, de.start_time, de.end_time)) as total_duration_minutes,
                AVG(TIMESTAMPDIFF(MINUTE, de.start_time, de.end_time)) as avg_duration_minutes,
                MAX(de.timestamp) as latest_occurrence,
                m.oem_name,
                m.vfj_no
            FROM downtime_entries de
            JOIN machines m ON m.id = de.machine_id
            WHERE 1=1
        """
        
        summary_params = []

        # Add same filters for summary
        if machine_id:
            summary_query += " AND de.machine_id = %s"
            summary_params.append(int(machine_id))

        if from_datetime:
            summary_query += " AND de.timestamp >= %s"
            summary_params.append(from_datetime)
        elif from_date:
            summary_query += " AND de.timestamp >= %s"
            summary_params.append(f"{from_date} 00:00:00")

        if to_datetime:
            summary_query += " AND de.timestamp <= %s"
            summary_params.append(to_datetime)
        elif to_date:
            summary_query += " AND de.timestamp <= %s"
            summary_params.append(f"{to_date} 23:59:59")

        # Apply same date fallback logic for summary
        if not any([from_date, to_date, from_datetime, to_datetime]):
            summary_query += " AND DATE(de.timestamp) = CURDATE()"

        summary_query += """
            GROUP BY de.machine_id, de.reason, m.oem_name, m.vfj_no
            ORDER BY total_duration_minutes DESC
            LIMIT 20
        """

        cursor.execute(summary_query, summary_params)
        summary_results = cursor.fetchall()

        # Format summary results
        downtime_summary = []
        for row in summary_results:
            machine_name = f"{row['oem_name']} #{row['vfj_no']}" if row['oem_name'] and row['vfj_no'] else f"Machine {row['machine_id']}"
            
            downtime_summary.append({
                "machine_id": row["machine_id"],
                "machine_name": machine_name,
                "vfj_no": str(row["vfj_no"] or ""),
                "reason": row["reason"],
                "occurrence_count": row["occurrence_count"],
                "total_duration_minutes": float(row["total_duration_minutes"] or 0),
                "avg_duration_minutes": round(float(row["avg_duration_minutes"] or 0), 2),
                "latest_occurrence": row["latest_occurrence"].strftime('%Y-%m-%d %H:%M:%S') if row["latest_occurrence"] else None
            })

        # Handle export formats
        if export_type == "csv":
            # Build date range info for header
            date_info = ""
            if from_datetime and to_datetime:
                date_info = f"{from_datetime} to {to_datetime}"
            elif from_date and to_date:
                date_info = f"{from_date} to {to_date}"
            elif from_date:
                date_info = f"From {from_date}"
            elif to_date:
                date_info = f"Until {to_date}"
            else:
                date_info = f"Today ({datetime.now().strftime('%Y-%m-%d')})"
            
            machine_info = f"Machine {machine_id}" if machine_id else "All Machines"
            # Export the detailed events for CSV
            return generate_csv_response(downtime_data, f"downtime_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", 
                                       "Downtime Report", date_info, machine_info)
        elif export_type == "pdf":
            # Build date range info for header
            date_info = ""
            if from_datetime and to_datetime:
                date_info = f"{from_datetime} to {to_datetime}"
            elif from_date and to_date:
                date_info = f"{from_date} to {to_date}"
            elif from_date:
                date_info = f"From {from_date}"
            elif to_date:
                date_info = f"Until {to_date}"
            else:
                date_info = f"Today ({datetime.now().strftime('%Y-%m-%d')})"
            
            machine_info = f"Machine {machine_id}" if machine_id else "All Machines"
            # Export the summary for PDF (more readable)
            return generate_pdf_response(downtime_summary, "Downtime Report", f"downtime_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                                       date_info, machine_info)

        # Default JSON response with both detailed events and summary
        return jsonify({
            "success": True,
            "detailed_events_count": len(downtime_data),
            "summary_count": len(downtime_summary),
            "timestamp": datetime.now().isoformat(),
            "downtime_events": downtime_data,
            "downtime_summary": downtime_summary
        }), 200

    except Exception as e:
        return jsonify({"error": "Failed to generate downtime report", "details": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()




@app.route("/reports/energy", methods=["GET"])
@token_required
def energy_report(current_user):
    machine_id = request.args.get("machine_id")
    from_date = request.args.get("from_date")
    to_date = request.args.get("to_date")
    from_datetime = request.args.get("from_datetime")
    to_datetime = request.args.get("to_datetime")
    export_type = request.args.get("export", "").lower()

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)

        # Build base query for energy data
        base_sql = """
            SELECT t.*
            FROM energy_data t
            INNER JOIN (
                SELECT machine_id, MAX(timestamp) AS max_ts
                FROM energy_data
                WHERE 1=1
        """
        params = []

        # Add machine filter
        if machine_id:
            base_sql += " AND machine_id = %s"
            params.append(int(machine_id))

        # Add time filters (datetime takes priority over date)
        if from_datetime:
            base_sql += " AND timestamp >= %s"
            params.append(from_datetime)
        elif from_date:
            base_sql += " AND timestamp >= %s"
            params.append(f"{from_date} 00:00:00")

        if to_datetime:
            base_sql += " AND timestamp <= %s"
            params.append(to_datetime)
        elif to_date:
            base_sql += " AND timestamp <= %s"
            params.append(f"{to_date} 23:59:59")

        base_sql += """
                GROUP BY machine_id
            ) x
            ON t.machine_id = x.machine_id AND t.timestamp = x.max_ts
            ORDER BY t.machine_id
        """

        # If no time filters provided, try today first, then fallback
        results = []
        if not any([from_date, to_date, from_datetime, to_datetime]):
            # Try today first
            today_query = base_sql.replace("WHERE 1=1", "WHERE DATE(timestamp) = CURDATE()")
            cursor.execute(today_query, params)
            today_results = cursor.fetchall()
            
            if not today_results:
                # Fallback to most recent date with data
                cursor.execute("""
                    SELECT DATE(timestamp) as latest_date 
                    FROM energy_data 
                    ORDER BY timestamp DESC 
                    LIMIT 1
                """)
                latest_date_row = cursor.fetchone()
                if latest_date_row:
                    latest_date = latest_date_row['latest_date']
                    fallback_query = base_sql.replace("WHERE 1=1", f"WHERE DATE(timestamp) = '{latest_date}'")
                    cursor.execute(fallback_query, params)
                    results = cursor.fetchall()
            else:
                # Use today's results
                results = today_results
        else:
            # Use specified date range
            cursor.execute(base_sql, params)
            results = cursor.fetchall()

        # Get aggregation data for energy calculations
        agg_params = []
        agg_where = ["1=1"]
        
        if machine_id:
            agg_where.append("machine_id = %s")
            agg_params.append(int(machine_id))

        # For energy calculation, determine the date range
        if not any([from_date, to_date, from_datetime, to_datetime]):
            # Default: use today's data for energy calculation
            today = datetime.now().strftime("%Y-%m-%d")
            agg_where.append("DATE(timestamp) = %s")
            agg_params.append(today)
        else:
            # Use the specified date range for energy calculation
            if from_datetime:
                agg_where.append("timestamp >= %s")
                agg_params.append(from_datetime)
            elif from_date:
                agg_where.append("timestamp >= %s")
                agg_params.append(f"{from_date} 00:00:00")

            if to_datetime:
                agg_where.append("timestamp <= %s")
                agg_params.append(to_datetime)
            elif to_date:
                agg_where.append("timestamp <= %s")
                agg_params.append(f"{to_date} 23:59:59")

        # Aggregation query for energy metrics
        agg_query = f"""
            SELECT
              machine_id,
              AVG((voltage1*current1*power_factor1
                  + voltage2*current2*power_factor2
                  + voltage3*current3*power_factor3) / 1000.0) AS avg_power_kw,
              MAX((voltage1*current1*power_factor1
                  + voltage2*current2*power_factor2
                  + voltage3*current3*power_factor3) / 1000.0) AS peak_power_kw,
              COUNT(*) AS reading_count,
              MIN(timestamp) AS period_start,
              MAX(timestamp) AS period_end
            FROM energy_data
            WHERE {" AND ".join(agg_where)}
            GROUP BY machine_id
            ORDER BY machine_id
        """
        cursor.execute(agg_query, agg_params)
        agg_rows = {r["machine_id"]: r for r in cursor.fetchall()}

        # Format results to match energy report structure
        energy_data = []
        for row in results:
            mid = row["machine_id"]
            agg = agg_rows.get(mid, {})

            # Power from latest row (kW)
            latest_power_kw = (
                (row["voltage1"] * row["current1"] * row["power_factor1"]) +
                (row["voltage2"] * row["current2"] * row["power_factor2"]) +
                (row["voltage3"] * row["current3"] * row["power_factor3"])
            ) / 1000.0

            # Energy calculation based on actual data period
            total_energy_kWh = 0.0
            if agg.get("avg_power_kw") and agg.get("period_start") and agg.get("period_end"):
                duration_hours = (agg["period_end"] - agg["period_start"]).total_seconds() / 3600.0
                total_energy_kWh = float(agg["avg_power_kw"]) * duration_hours

            energy_data.append({
                "machine_id": mid,

                # latest measured values
                "voltage1": round(float(row["voltage1"]), 3),
                "voltage2": round(float(row["voltage2"]), 3),
                "voltage3": round(float(row["voltage3"]), 3),
                "current1": round(float(row["current1"]), 3),
                "current2": round(float(row["current2"]), 3),
                "current3": round(float(row["current3"]), 3),
                "power_factor1": round(float(row["power_factor1"]), 3),
                "power_factor2": round(float(row["power_factor2"]), 3),
                "power_factor3": round(float(row["power_factor3"]), 3),

                # computed metrics
                "latest_power_kw": round(latest_power_kw, 3),
                "avg_power_kw": round(float(agg.get("avg_power_kw", 0) or 0), 3),
                "peak_power_kw": round(float(agg.get("peak_power_kw", 0) or 0), 3),
                "total_energy_kWh": round(total_energy_kWh, 3),

                # meta
                "reading_count": int(agg.get("reading_count", 1)),
                "period_start": agg.get("period_start").strftime("%Y-%m-%d %H:%M:%S") if agg.get("period_start") else None,
                "period_end": agg.get("period_end").strftime("%Y-%m-%d %H:%M:%S") if agg.get("period_end") else None,
                "latest_timestamp": row["timestamp"].strftime("%Y-%m-%d %H:%M:%S") if row.get("timestamp") else None,
            })

        # Handle export formats
        if export_type == "csv":
            # Build date range info for header
            date_info = ""
            if from_datetime and to_datetime:
                date_info = f"{from_datetime} to {to_datetime}"
            elif from_date and to_date:
                date_info = f"{from_date} to {to_date}"
            elif from_date:
                date_info = f"From {from_date}"
            elif to_date:
                date_info = f"Until {to_date}"
            else:
                date_info = f"Today ({datetime.now().strftime('%Y-%m-%d')})"

            machine_info = f"Machine {machine_id}" if machine_id else "All Machines"
            return generate_csv_response(
                energy_data,
                f"energy_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                "Energy Report",
                date_info,
                machine_info
            )

        elif export_type == "pdf":
            # Build date range info for header
            date_info = ""
            if from_datetime and to_datetime:
                date_info = f"{from_datetime} to {to_datetime}"
            elif from_date and to_date:
                date_info = f"{from_date} to {to_date}"
            elif from_date:
                date_info = f"From {from_date}"
            elif to_date:
                date_info = f"Until {to_date}"
            else:
                date_info = f"Today ({datetime.now().strftime('%Y-%m-%d')})"

            machine_info = f"Machine {machine_id}" if machine_id else "All Machines"
            return generate_pdf_response(
                energy_data,
                "Energy Report",
                f"energy_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                date_info,
                machine_info
            )

        # Default JSON response
        return jsonify({
            "success": True,
            "count": len(energy_data),
            "generated_at": datetime.now().isoformat(),
            "energy_data": energy_data
        }), 200

    except Exception as e:
        return jsonify({"error": "Failed to generate energy report", "details": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
def generate_csv_response(data, filename, report_title, date_range_info="", machine_filter="All Machines"):
    """Generate CSV response with enhanced headers"""
    output = StringIO()
    writer = csv.writer(output)
    
    # Write report metadata as header rows
    writer.writerow([report_title])
    writer.writerow([f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"])
    if date_range_info:
        writer.writerow([f"Date Range: {date_range_info}"])
    writer.writerow([f"Machine Filter: {machine_filter}"])
    writer.writerow([f"Total Records: {len(data)} records found"])
    writer.writerow([])  # Empty row separator
    
    # Write data headers and rows
    if data:
        # Get column names from first data record
        field_names = list(data[0].keys())
        # Convert field names to readable headers
        headers = [field_name.replace('_', ' ').title() for field_name in field_names]
        writer.writerow(headers)
        
        # Write data rows
        for row in data:
            writer.writerow([row.get(field_name, '') for field_name in field_names])
        
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response



def generate_pdf_response(data, title, filename, date_range_info="", machine_filter="All Machines"):
    """Generate a well-formatted PDF (landscape) with wrapped cells and dynamic column widths."""
    buffer = BytesIO()

    # True landscape, comfortable margins
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=30, rightMargin=30, topMargin=50, bottomMargin=50
    )
    styles = getSampleStyleSheet()

    # Table cell styles
    cell_style = ParagraphStyle(
        name="Cell",
        fontName="Helvetica",
        fontSize=8,
        leading=10,     # line height
    )
    header_style = ParagraphStyle(
        name="Header",
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=11,
    )

    story = []

    # Title
    story.append(Paragraph(f"<b>{title}</b>", styles['Title']))
    story.append(Spacer(1, 15))

    # Generation & filters
    story.append(Paragraph(f"<b>Generated on:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
    if date_range_info:
        story.append(Paragraph(f"<b>Date Range:</b> {date_range_info}", styles['Normal']))
    story.append(Paragraph(f"<b>Machine Filter:</b> {machine_filter}", styles['Normal']))

    # Record count
    story.append(Paragraph(f"<b>Total Records:</b> {len(data)} records found", styles['Normal']))
    story.append(Spacer(1, 20))

    if data:
        # ---- Determine column set (union of keys, preserving the order from first row) ----
        first_keys = list(data[0].keys())
        extra_keys = []
        for row in data[1:]:
            for k in row.keys():
                if k not in first_keys and k not in extra_keys:
                    extra_keys.append(k)
        field_names = first_keys + extra_keys  # union, ordered

        # ---- Build header row ----
        headers = [Paragraph(k.replace('_', ' ').title(), header_style) for k in field_names]

        # ---- Convert rows to Paragraphs and measure content lengths for width allocation ----
        table_data = [headers]
        col_lengths = [len(k.replace('_', ' ')) for k in field_names]  # seed with header lengths

        for row in data:
            row_cells = []
            for i, field in enumerate(field_names):
                txt = "" if row.get(field) is None else str(row.get(field))
                row_cells.append(Paragraph(txt, cell_style))
                # track max string length per column (for width estimation)
                col_lengths[i] = max(col_lengths[i], len(txt))
            table_data.append(row_cells)

        # ---- Compute dynamic column widths to fit the available page width ----
        page_w, _ = landscape(A4)
        available_width = page_w - doc.leftMargin - doc.rightMargin

        def weight_for(name: str, length: int) -> float:
            """Heuristic: longer text → wider column; special-case common wide/narrow fields."""
            name_l = (name or "").lower()
            cap = 60  # upper bound to prevent a single column from dominating
            base = min(max(length, 8), cap)  # keep a lower bound for visibility

            # Make path-like/comment fields wider
            if any(t in name_l for t in ("path", "mpf", "file", "comments", "section", "details")):
                base = max(base, 30)
            # IDs and small numerics narrower
            if name_l in ("id", "ok_parts", "bad_parts") or name_l.endswith("_id"):
                base = min(max(base, 12), 20)
            # Machine/status fields medium
            if any(t in name_l for t in ("status", "name", "machine", "operator", "component")):
                base = max(base, 18)

            return float(base)

        weights = [weight_for(field_names[i], col_lengths[i]) for i in range(len(field_names))]
        total_w = sum(weights) or 1.0
        unit = available_width / total_w
        col_widths = [w * unit for w in weights]

        # ---- Build table with repeat header row & clean styling ----
        table = Table(
            table_data,
            colWidths=col_widths,
            repeatRows=1,
            splitByRow=True,
            hAlign='LEFT'
        )
        table.setStyle(TableStyle([
            # Header
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),

            # Body
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),

            # Alternate row backgrounds for readability
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, colors.beige]),

            # Grid
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ]))

        story.append(table)
    else:
        story.append(Paragraph("No data found for the specified criteria.", styles['Normal']))

    # Build and return response
    doc.build(story)
    buffer.seek(0)
    response = make_response(buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response



@app.route("/api/alarms", methods=["GET"])
@token_required
def get_alarms(current_user):
    """Get critical alarms from machine_alarms column only"""
    machine_id = request.args.get("machine_id")
    from_date = request.args.get("from_date")
    to_date = request.args.get("to_date") 
    from_datetime = request.args.get("from_datetime")
    to_datetime = request.args.get("to_datetime")
    export_type = request.args.get("export", "").lower()
    try: limit = min(max(1, int(request.args.get("limit", 50))), 500)
    except: limit = 50

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
        
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        
        # Build base query
        query = """
            SELECT md.machine_id, md.machine_alarms, md.timestamp, 
                   m.oem_name, m.vfj_no, m.control_type
            FROM machine_data md
            JOIN machines m ON m.id = md.machine_id
            WHERE md.machine_alarms IS NOT NULL AND md.machine_alarms <> ''
        """
        params = []

        # Add machine filter
        if machine_id:
            query += " AND md.machine_id = %s"
            params.append(int(machine_id))

        # Add time filters (datetime takes priority over date)
        if from_datetime:
            query += " AND md.timestamp >= %s"
            params.append(from_datetime)
        elif from_date:
            query += " AND md.timestamp >= %s"
            params.append(f"{from_date} 00:00:00")

        if to_datetime:
            query += " AND md.timestamp <= %s"
            params.append(to_datetime)
        elif to_date:
            query += " AND md.timestamp <= %s"
            params.append(f"{to_date} 23:59:59")

        # If no time filters provided, try today first, then fallback
        if not any([from_date, to_date, from_datetime, to_datetime]):
            # Try today first
            today_query = query + " AND DATE(md.timestamp) = CURDATE()"
            cursor.execute(today_query + " ORDER BY md.timestamp DESC LIMIT %s", params + [limit])
            today_results = cursor.fetchall()
            
            if not today_results:
                # Fallback to most recent date with data
                query += " ORDER BY md.timestamp DESC LIMIT %s"
                params.append(limit)
            else:
                # Use today's results
                query = today_query + " ORDER BY md.timestamp DESC LIMIT %s"
                params.append(limit)
        else:
            query += " ORDER BY md.timestamp DESC LIMIT %s"
            params.append(limit)

        cursor.execute(query, params)
        results = cursor.fetchall()

        alarms = []
        for row in results:
            machine_label = f"{row['oem_name']} #{row['vfj_no']}" if row['oem_name'] and row['vfj_no'] else f"Machine {row['machine_id']}"
            timestamp = row['timestamp'].strftime('%Y-%m-%d %H:%M:%S') if row['timestamp'] else None
            
            # Parse JSON alarms
            raw_alarms = row['machine_alarms']
            if isinstance(raw_alarms, (bytes, bytearray)):
                raw_alarms = raw_alarms.decode("utf-8", errors="ignore")
            
            try:
                parsed_alarms = json.loads(raw_alarms)
            except:
                parsed_alarms = None

            if isinstance(parsed_alarms, list):
                for alarm in parsed_alarms:
                    alarms.append({
                        "machine_id": row['machine_id'],
                        "machine_name": machine_label,
                        "timestamp": timestamp,
                        "code": alarm.get("code"),
                        "message": alarm.get("message"),
                        "severity": alarm.get("severity"),
                        "line": alarm.get("line"),
                        "type": "alarm"
                    })
            elif isinstance(parsed_alarms, dict):
                alarms.append({
                    "machine_id": row['machine_id'],
                    "machine_name": machine_label,
                    "timestamp": timestamp,
                    "code": parsed_alarms.get("code"),
                    "message": parsed_alarms.get("message"),
                    "severity": parsed_alarms.get("severity"),
                    "line": parsed_alarms.get("line"),
                    "type": "alarm"
                })

        # Handle export formats
        if export_type == "csv":
            # Build date range info for header
            date_info = ""
            if from_datetime and to_datetime:
                date_info = f"{from_datetime} to {to_datetime}"
            elif from_date and to_date:
                date_info = f"{from_date} to {to_date}"
            elif from_date:
                date_info = f"From {from_date}"
            elif to_date:
                date_info = f"Until {to_date}"
            else:
                date_info = f"Today ({datetime.now().strftime('%Y-%m-%d')})"
            
            machine_info = f"Machine {machine_id}" if machine_id else "All Machines"
            return generate_csv_response(alarms, f"alarms_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", 
                                       "Critical Alarms Report", date_info, machine_info)
        elif export_type == "pdf":
            # Build date range info for header
            date_info = ""
            if from_datetime and to_datetime:
                date_info = f"{from_datetime} to {to_datetime}"
            elif from_date and to_date:
                date_info = f"{from_date} to {to_date}"
            elif from_date:
                date_info = f"From {from_date}"
            elif to_date:
                date_info = f"Until {to_date}"
            else:
                date_info = f"Today ({datetime.now().strftime('%Y-%m-%d')})"
            
            machine_info = f"Machine {machine_id}" if machine_id else "All Machines"
            return generate_pdf_response(alarms, "Critical Alarms Report", f"alarms_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                                       date_info, machine_info)
        
        # Default JSON response
        return jsonify({
            "success": True,
            "count": len(alarms),
            "timestamp": datetime.now().isoformat(),
            "alarms": alarms
        }), 200

    except Exception as e:
        return jsonify({"error": "Failed to fetch alarms"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route("/api/warnings", methods=["GET"])
@token_required
def get_warnings(current_user):
    """Get warnings from cnc_warnings column only"""
    machine_id = request.args.get("machine_id")
    from_date = request.args.get("from_date")
    to_date = request.args.get("to_date")
    from_datetime = request.args.get("from_datetime")
    to_datetime = request.args.get("to_datetime")
    export_type = request.args.get("export", "").lower()
    try: limit = min(max(1, int(request.args.get("limit", 50))), 500)
    except: limit = 50

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
        
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        
        # Build base query
        query = """
            SELECT md.machine_id, md.cnc_warnings, md.timestamp,
                   m.oem_name, m.vfj_no, m.control_type
            FROM machine_data md
            JOIN machines m ON m.id = md.machine_id
            WHERE md.cnc_warnings IS NOT NULL AND md.cnc_warnings <> ''
        """
        params = []

        # Add machine filter
        if machine_id:
            query += " AND md.machine_id = %s"
            params.append(int(machine_id))

        # Add time filters (datetime takes priority over date)
        if from_datetime:
            query += " AND md.timestamp >= %s"
            params.append(from_datetime)
        elif from_date:
            query += " AND md.timestamp >= %s"
            params.append(f"{from_date} 00:00:00")

        if to_datetime:
            query += " AND md.timestamp <= %s"
            params.append(to_datetime)
        elif to_date:
            query += " AND md.timestamp <= %s"
            params.append(f"{to_date} 23:59:59")

        # If no time filters provided, try today first, then fallback
        if not any([from_date, to_date, from_datetime, to_datetime]):
            # Try today first
            today_query = query + " AND DATE(md.timestamp) = CURDATE()"
            cursor.execute(today_query + " ORDER BY md.timestamp DESC LIMIT %s", params + [limit])
            today_results = cursor.fetchall()
            
            if not today_results:
                # Fallback to most recent date with data
                query += " ORDER BY md.timestamp DESC LIMIT %s"
                params.append(limit)
            else:
                # Use today's results
                query = today_query + " ORDER BY md.timestamp DESC LIMIT %s"
                params.append(limit)
        else:
            query += " ORDER BY md.timestamp DESC LIMIT %s"
            params.append(limit)

        cursor.execute(query, params)
        results = cursor.fetchall()

        warnings = []
        for row in results:
            machine_label = f"{row['oem_name']} #{row['vfj_no']}" if row['oem_name'] and row['vfj_no'] else f"Machine {row['machine_id']}"
            timestamp = row['timestamp'].strftime('%Y-%m-%d %H:%M:%S') if row['timestamp'] else None
            
            # Parse JSON warnings
            raw_warnings = row['cnc_warnings']
            if isinstance(raw_warnings, (bytes, bytearray)):
                raw_warnings = raw_warnings.decode("utf-8", errors="ignore")
            
            try:
                parsed_warnings = json.loads(raw_warnings)
            except:
                parsed_warnings = None

            if isinstance(parsed_warnings, list):
                for warning in parsed_warnings:
                    warnings.append({
                        "machine_id": row['machine_id'],
                        "machine_name": machine_label,
                        "timestamp": timestamp,
                        "code": warning.get("code"),
                        "message": warning.get("message"),
                        "severity": warning.get("severity"),
                        "line": warning.get("line"),
                        "type": "warning"
                    })
            elif isinstance(parsed_warnings, dict):
                warnings.append({
                    "machine_id": row['machine_id'],
                    "machine_name": machine_label,
                    "timestamp": timestamp,
                    "code": parsed_warnings.get("code"),
                    "message": parsed_warnings.get("message"),
                    "severity": parsed_warnings.get("severity"),
                    "line": parsed_warnings.get("line"),
                    "type": "warning"
                })

        # Handle export formats
        if export_type == "csv":
            # Build date range info for header
            date_info = ""
            if from_datetime and to_datetime:
                date_info = f"{from_datetime} to {to_datetime}"
            elif from_date and to_date:
                date_info = f"{from_date} to {to_date}"
            elif from_date:
                date_info = f"From {from_date}"
            elif to_date:
                date_info = f"Until {to_date}"
            else:
                date_info = f"Today ({datetime.now().strftime('%Y-%m-%d')})"
            
            machine_info = f"Machine {machine_id}" if machine_id else "All Machines"
            return generate_csv_response(warnings, f"warnings_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", 
                                       "Warnings Report", date_info, machine_info)
        elif export_type == "pdf":
            # Build date range info for header
            date_info = ""
            if from_datetime and to_datetime:
                date_info = f"{from_datetime} to {to_datetime}"
            elif from_date and to_date:
                date_info = f"{from_date} to {to_date}"
            elif from_date:
                date_info = f"From {from_date}"
            elif to_date:
                date_info = f"Until {to_date}"
            else:
                date_info = f"Today ({datetime.now().strftime('%Y-%m-%d')})"
            
            machine_info = f"Machine {machine_id}" if machine_id else "All Machines"
            return generate_pdf_response(warnings, "Warnings Report", f"warnings_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                                       date_info, machine_info)

        # Default JSON response
        return jsonify({
            "success": True,
            "count": len(warnings),
            "timestamp": datetime.now().isoformat(),
            "warnings": warnings
        }), 200

    except Exception as e:
        return jsonify({"error": "Failed to fetch warnings"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route("/api/alerts", methods=["GET"])
@token_required
def get_all_alerts(current_user):
    """Get combined view of both alarms and warnings"""
    machine_id = request.args.get("machine_id")
    from_date = request.args.get("from_date")
    to_date = request.args.get("to_date")
    from_datetime = request.args.get("from_datetime")
    to_datetime = request.args.get("to_datetime")
    export_type = request.args.get("export", "").lower()
    try: limit = min(max(1, int(request.args.get("limit", 50))), 500)
    except: limit = 50

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
        
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        
        

        query = """
            SELECT md.machine_id, md.machine_alarms, md.cnc_warnings, md.timestamp,
                m.oem_name, m.vfj_no, m.control_type
            FROM machine_data md
            JOIN machines m ON m.id = md.machine_id
            WHERE ((md.machine_alarms IS NOT NULL AND md.machine_alarms <> '') 
                OR (md.cnc_warnings IS NOT NULL AND md.cnc_warnings <> ''))
        """
        params = []

        # Add machine filter
        if machine_id:
            query += " AND md.machine_id = %s"
            params.append(int(machine_id))

        # Add time filters (datetime takes priority over date)
        if from_datetime:
            query += " AND md.timestamp >= %s"
            params.append(from_datetime)
        elif from_date:
            query += " AND md.timestamp >= %s"
            params.append(f"{from_date} 00:00:00")

        if to_datetime:
            query += " AND md.timestamp <= %s"
            params.append(to_datetime)
        elif to_date:
            query += " AND md.timestamp <= %s"
            params.append(f"{to_date} 23:59:59")


        #print(f"check {any([from_date, to_date, from_datetime, to_datetime])}")
        #print(f"query {query}")

        if any([from_date, to_date, from_datetime, to_datetime]):
          

            count_query = """
                SELECT COUNT(*) as count 
                FROM machine_data md
                JOIN machines m ON m.id = md.machine_id
                WHERE ((md.machine_alarms IS NOT NULL AND md.machine_alarms <> '') 
                    OR (md.cnc_warnings IS NOT NULL AND md.cnc_warnings <> ''))
            """
            count_params = []
            
            # Add the same filters as the main query
            if machine_id:
                count_query += " AND md.machine_id = %s"
                count_params.append(int(machine_id))
            
            if from_datetime:
                count_query += " AND md.timestamp >= %s"
                count_params.append(from_datetime)
            elif from_date:
                count_query += " AND md.timestamp >= %s"
                count_params.append(f"{from_date} 00:00:00")

            if to_datetime:
                count_query += " AND md.timestamp <= %s"
                count_params.append(to_datetime)
            elif to_date:
                count_query += " AND md.timestamp <= %s"
                count_params.append(f"{to_date} 23:59:59")
            
            cursor.execute(count_query, count_params)
            #cursor.execute(count_query, count_params)
            #print(f"count queries : {count_query}")
            #print(f"count params: {count_params}")
            count_result = cursor.fetchone()['count']
            #print(f"count: {count_result}")
            if count_result == 0:
                return jsonify({
                    "success": True,
                    "count": 0,
                    "timestamp": datetime.now().isoformat(),
                    "alerts": []
                }), 200

        

        # If no time filters provided, try today first, then fallback
        if not any([from_date, to_date, from_datetime, to_datetime]):
            # Try today first
            today_query = query + " AND DATE(md.timestamp) = CURDATE()"
            cursor.execute(today_query + " ORDER BY md.timestamp DESC LIMIT %s", params + [limit])
            today_results = cursor.fetchall()
            
            if not today_results:
                # Fallback to most recent date with data
                query += " ORDER BY md.timestamp DESC LIMIT %s"
                params.append(limit)
            else:
                # Use today's results
                query = today_query + " ORDER BY md.timestamp DESC LIMIT %s"
                params.append(limit)
        else:
            query += " ORDER BY md.timestamp DESC LIMIT %s"
            params.append(limit)

        cursor.execute(query, params)
        results = cursor.fetchall()

        all_alerts = []
        for row in results:
            machine_label = f"{row['oem_name']} #{row['vfj_no']}" if row['oem_name'] and row['vfj_no'] else f"Machine {row['machine_id']}"
            timestamp = row['timestamp'].strftime('%Y-%m-%d %H:%M:%S') if row['timestamp'] else None
            
            # Process machine_alarms
            if row['machine_alarms']:
                raw_alarms = row['machine_alarms']
                if isinstance(raw_alarms, (bytes, bytearray)):
                    raw_alarms = raw_alarms.decode("utf-8", errors="ignore")
                
                try:
                    parsed_alarms = json.loads(raw_alarms)
                except:
                    parsed_alarms = None

                if isinstance(parsed_alarms, list):
                    for alarm in parsed_alarms:
                        all_alerts.append({
                            "machine_id": row['machine_id'],
                            "machine_name": machine_label,
                            "timestamp": timestamp,
                            "code": alarm.get("code"),
                            "message": alarm.get("message"),
                            "severity": alarm.get("severity"),
                            "line": alarm.get("line"),
                            "type": "alarm"
                        })
                elif isinstance(parsed_alarms, dict):
                    all_alerts.append({
                        "machine_id": row['machine_id'],
                        "machine_name": machine_label,
                        "timestamp": timestamp,
                        "code": parsed_alarms.get("code"),
                        "message": parsed_alarms.get("message"),
                        "severity": parsed_alarms.get("severity"),
                        "line": parsed_alarms.get("line"),
                        "type": "alarm"
                    })

            # Process cnc_warnings
            if row['cnc_warnings']:
                raw_warnings = row['cnc_warnings']
                if isinstance(raw_warnings, (bytes, bytearray)):
                    raw_warnings = raw_warnings.decode("utf-8", errors="ignore")
                
                try:
                    parsed_warnings = json.loads(raw_warnings)
                except:
                    parsed_warnings = None

                if isinstance(parsed_warnings, list):
                    for warning in parsed_warnings:
                        all_alerts.append({
                            "machine_id": row['machine_id'],
                            "machine_name": machine_label,
                            "timestamp": timestamp,
                            "code": warning.get("code"),
                            "message": warning.get("message"),
                            "severity": warning.get("severity"),
                            "line": warning.get("line"),
                            "type": "warning"
                        })
                elif isinstance(parsed_warnings, dict):
                    all_alerts.append({
                        "machine_id": row['machine_id'],
                        "machine_name": machine_label,
                        "timestamp": timestamp,
                        "code": parsed_warnings.get("code"),
                        "message": parsed_warnings.get("message"),
                        "severity": parsed_warnings.get("severity"),
                        "line": parsed_warnings.get("line"),
                        "type": "warning"
                    })

        # Sort by timestamp (most recent first)
        all_alerts.sort(key=lambda x: x['timestamp'] or '', reverse=True)

        # Handle export formats
        if export_type == "csv":
            # Build date range info for header
            date_info = ""
            if from_datetime and to_datetime:
                date_info = f"{from_datetime} to {to_datetime}"
            elif from_date and to_date:
                date_info = f"{from_date} to {to_date}"
            elif from_date:
                date_info = f"From {from_date}"
            elif to_date:
                date_info = f"Until {to_date}"
            else:
                date_info = f"Today ({datetime.now().strftime('%Y-%m-%d')})"
            
            machine_info = f"Machine {machine_id}" if machine_id else "All Machines"
            return generate_csv_response(all_alerts, f"alerts_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", 
                                       "All Alerts Report", date_info, machine_info)
        elif export_type == "pdf":
            # Build date range info for header
            date_info = ""
            if from_datetime and to_datetime:
                date_info = f"{from_datetime} to {to_datetime}"
            elif from_date and to_date:
                date_info = f"{from_date} to {to_date}"
            elif from_date:
                date_info = f"From {from_date}"
            elif to_date:
                date_info = f"Until {to_date}"
            else:
                date_info = f"Today ({datetime.now().strftime('%Y-%m-%d')})"
            
            machine_info = f"Machine {machine_id}" if machine_id else "All Machines"
            return generate_pdf_response(all_alerts, "All Alerts Report", f"alerts_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                                       date_info, machine_info)

        # Default JSON response
        return jsonify({
            "success": True,
            "count": len(all_alerts),
            "timestamp": datetime.now().isoformat(),
            "alerts": all_alerts
        }), 200

    except Exception as e:
        return jsonify({"error": "Failed to fetch alerts"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()




#from datetime import datetime

def parse_dt_or_date(s: str):
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            if fmt == "%Y-%m-%d":
                return datetime.combine(dt.date(), datetime.min.time())
            return dt
        except ValueError:
            continue
    raise ValueError(f"Invalid date/datetime: {s}")

def normalize_window(start_date: str | None, end_date: str | None):
    if start_date:
        start_dt = parse_dt_or_date(start_date)
    else:
        today = datetime.now().date()
        start_dt = datetime.combine(today, datetime.min.time())

    if end_date:
        end_dt_raw = parse_dt_or_date(end_date)
        if len(end_date.strip()) == 10:
            end_dt = datetime.combine(end_dt_raw.date(), datetime.max.time())
        else:
            end_dt = end_dt_raw
    else:
        end_dt = datetime.combine(start_dt.date(), datetime.max.time())

    if end_dt <= start_dt:
        raise ValueError("end_date must be after start_date")
    return start_dt, end_dt

def _now_db(conn):
    with conn.cursor() as c:
        c.execute("SELECT NOW(3)")
        return c.fetchone()[0]

def _merge_intervals(intervals):
    arr = [(s, e) for s, e in intervals if s and e and e > s]
    if not arr:
        return []
    arr.sort(key=lambda x: x[0])
    merged = [arr[0]]
    for s, e in arr[1:]:
        ls, le = merged[-1]
        if s <= le:
            merged[-1] = (ls, max(le, e))

        else:
            merged.append((s, e))
    return merged

def r(v: float, dec: int) -> float:
    return round(float(v), dec)

# ---------------- Machine meta ----------------
def get_machines(machine_id: int | None):
    sql = "SELECT id, oem_name AS mname, vfj_no, COALESCE(vfj_no, id) AS mnum FROM machines"
    params = []
    if machine_id:
        sql += " WHERE id = %s"
        params.append(machine_id)
    else:
        sql += " ORDER BY id"
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            out = []
            for row in rows:
                name = row.get("mname")
                num  = row.get("mnum")
                if name and num:
                    label = f"{name} #{num}"
                elif name:
                    label = name
                else:
                    label = f"Machine #{num}" if num else f"Machine {row['id']}"
                out.append({"id": row["id"], "label": label, "vfj_no": row.get("vfj_no")})
            return out
    finally:
        conn.close()

# ---------------- Core building blocks (WINDOW) ----------------
def get_planned_seconds_window(machine_id: str, start_dt: datetime, end_dt: datetime) -> int:
    sql = """
        SELECT shift_start, shift_end
        FROM machine_production
        WHERE machine_id = %s
          AND shift_start IS NOT NULL
          AND shift_start <= %s
          AND COALESCE(shift_end, %s) >= %s
        ORDER BY shift_start ASC
    """
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(sql, (machine_id, end_dt, end_dt, start_dt))
            rows = cur.fetchall()
        now_ts = _now_db(conn)
        intervals = []
        for r in rows:
            s = max(r["shift_start"], start_dt)
            e = min(r["shift_end"] or now_ts, end_dt)
            if e > s:
                intervals.append((s, e))
        merged = _merge_intervals(intervals)
        return int(sum((e - s).total_seconds() for s, e in merged))
    finally:
        conn.close()

def get_downtime_seconds_window(machine_id: int, start_dt: datetime, end_dt: datetime) -> int:
    sql = """
        SELECT COALESCE(SUM(
                 GREATEST(
                   TIMESTAMPDIFF(SECOND,
                     GREATEST(COALESCE(start_time, `timestamp`), %s),
                     LEAST(COALESCE(end_time, NOW()), %s)
                   ), 0)
               ), 0) AS downtime_seconds
        FROM downtime_entries
        WHERE machine_id = %s
          AND COALESCE(start_time, `timestamp`) < %s
          AND COALESCE(end_time, NOW()) > %s
    """
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(sql, (start_dt, end_dt, machine_id, end_dt, start_dt))
            return int(cur.fetchone()["downtime_seconds"] or 0)
    finally:
        conn.close()

def get_breakdown_seconds_window(machine_id: int, start_dt: datetime, end_dt: datetime) -> int:
    seed_sql = """
        SELECT machine_state, `timestamp`
        FROM machine_data
        WHERE machine_id = %s AND `timestamp` < %s
        ORDER BY `timestamp` DESC
        LIMIT 1
    """
    sql = """
        SELECT machine_state, `timestamp`
        FROM machine_data
        WHERE machine_id = %s
          AND `timestamp` >= %s
          AND `timestamp` <= %s
        ORDER BY `timestamp` ASC
    """
    conn = get_db_connection()
    total = 0
    try:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(seed_sql, (machine_id, start_dt))
            seed = cur.fetchone()

            cur.execute(sql, (machine_id, start_dt, end_dt))
            rows = cur.fetchall()

            in_bd = (seed and (seed["machine_state"] or "").upper() == "BREAKDOWN")
            bd_start = start_dt if in_bd else None

            for r in rows:
                state = (r["machine_state"] or "").upper()
                ts = r["timestamp"]
                if state == "BREAKDOWN":
                    if not in_bd:
                        in_bd = True
                        bd_start = ts
                elif state in ("IDLE", "RUNNING"):
                    if in_bd and bd_start is not None and ts > bd_start:
                        total += int((ts - bd_start).total_seconds())
                        in_bd = False
                        bd_start = None

            if in_bd and bd_start is not None:
                now_ts = _now_db(conn)
                close_ts = min(now_ts, end_dt)
                if close_ts > bd_start:
                    total += int((close_ts - bd_start).total_seconds())

        return total
    finally:
        conn.close()
#from datetime import datetime

def get_parts_quality_window(machine_id: str, start_dt: datetime, end_dt: datetime):
    """
    - total_parts: COUNT of machine_production rows that fall inside each production_entries window
                   (TIME_TO_SEC(total_cycle_time) > 0 AND results IN ('pass','fail')),
                   summed across entries. Uses the same 'latest_day' scope as good_parts.
                   Falls back to the [start_dt, end_dt] window if no latest_day exists.
    - min/avg cycle: from machine_production within [start_dt, end_dt]
    - good_parts: from production_entries.good_products for the LATEST date for this machine_id
                  (ignores start_dt/end_dt window per your requirement)
                  Falls back to machine_production-derived good_parts if none found.
    """
    # Window stats + fallback_good_parts from MP (unchanged)
    sql_mp = """
        SELECT
          -- NOTE: We no longer trust this 'total_parts' as it only counted PASS previously.
          -- We'll compute total_parts separately with per-entry logic.
          COALESCE(SUM(CASE
            WHEN mp.results IS NOT NULL AND LOWER(mp.results) = 'pass' THEN 1
            ELSE 0 END), 0) AS fallback_good_parts,

          NULLIF(MIN(NULLIF(TIME_TO_SEC(mp.total_cycle_time), 0)), 0) AS min_cycle_s,
          AVG(NULLIF(TIME_TO_SEC(mp.total_cycle_time), 0)) AS avg_cycle_s

        FROM machine_production mp
        WHERE mp.machine_id = %s
          AND COALESCE(mp.shift_start, mp.`timestamp`) >= %s
          AND COALESCE(mp.shift_start, mp.`timestamp`) <= %s
    """

    conn = get_db_connection()
    if conn is None:
        raise RuntimeError("DB connection failed")
    conn.autocommit = True

    try:
        with conn.cursor(dictionary=True) as cur:
            # 1) MP window stats (fallback_good_parts + cycle stats)
            cur.execute(sql_mp, (machine_id, start_dt, end_dt))
            row = cur.fetchone() or {}
            fallback_good_parts = int(row.get("fallback_good_parts") or 0)
            min_cycle_s = int(row["min_cycle_s"]) if row.get("min_cycle_s") is not None else None
            avg_cycle_s = float(row["avg_cycle_s"]) if row.get("avg_cycle_s") is not None else None

            # 2) Find latest_day in production_entries for this machine_id
            cur.execute(
                """
                SELECT
                  DATE(
                    GREATEST(
                      COALESCE(updated_at, '1970-01-01'),
                      COALESCE(end_time,  '1970-01-01'),
                      COALESCE(created_at,'1970-01-01'),
                      COALESCE(start_time,'1970-01-01')
                    )
                  ) AS latest_day
                FROM production_entries
                WHERE machine_id = %s
                ORDER BY GREATEST(
                    COALESCE(updated_at, '1970-01-01'),
                    COALESCE(end_time,  '1970-01-01'),
                    COALESCE(created_at,'1970-01-01'),
                    COALESCE(start_time,'1970-01-01')
                ) DESC
                LIMIT 1
                """,
                (int(machine_id),)
            )
            latest = cur.fetchone()
            latest_day = latest["latest_day"] if latest and latest["latest_day"] else None

            # 3) good_parts from PE on latest_day (prefer >0), else fallback_good_parts
            good_parts = 0
            if latest_day:
                cur.execute(
                    """
                    SELECT COALESCE(SUM(pe.good_products), 0) AS good_parts
                    FROM production_entries pe
                    WHERE pe.machine_id = %s
                      AND DATE(
                        GREATEST(
                          COALESCE(pe.updated_at, '1970-01-01'),
                          COALESCE(pe.end_time,  '1970-01-01'),
                          COALESCE(pe.created_at,'1970-01-01'),
                          COALESCE(pe.start_time,'1970-01-01')
                        )
                      ) = %s
                    """,
                    (int(machine_id), latest_day)
                )
                gp_row = cur.fetchone() or {"good_parts": 0}
                good_from_pe = int(gp_row.get("good_parts") or 0)
                if good_from_pe > 0:
                    good_parts = good_from_pe
            if good_parts == 0:
                good_parts = fallback_good_parts

            # 4) total_parts using the SAME LOGIC as entries API (per-entry windows)
            #    Primary scope: latest_day (to match good_parts)
            total_parts = 0
            if latest_day:
                # NOTE: If pe.machine_id is INT and mp.machine_id is VARCHAR, use a CAST:
                #   ... ON CAST(mp.machine_id AS UNSIGNED) = pe.machine_id ...
                cur.execute(
                    """
                    SELECT COALESCE(SUM(entry_cnt), 0) AS total_parts
                    FROM (
                        SELECT
                            pe.id,
                            COUNT(mp.id) AS entry_cnt
                        FROM production_entries pe
                        LEFT JOIN machine_production mp
                          ON mp.machine_id = pe.machine_id
                         AND TIME_TO_SEC(mp.total_cycle_time) > 0
                         AND LOWER(TRIM(mp.results)) IN ('pass','fail')  -- total = PASS + FAIL
                         AND COALESCE(mp.shift_start, mp.`timestamp`) >= pe.start_time
                         AND COALESCE(mp.shift_start, mp.`timestamp`) <  pe.end_time
                        WHERE pe.machine_id = %s
                          AND DATE(
                                GREATEST(
                                  COALESCE(pe.updated_at, '1970-01-01'),
                                  COALESCE(pe.end_time,   '1970-01-01'),
                                  COALESCE(pe.created_at, '1970-01-01'),
                                  COALESCE(pe.start_time, '1970-01-01')
                                )
                              ) = %s
                        GROUP BY pe.id
                    ) t
                    """,
                    (int(machine_id), latest_day)
                )
                tp_row = cur.fetchone() or {"total_parts": 0}
                total_parts = int(tp_row.get("total_parts") or 0)

            # Fallback: if no latest_day (or zero), use the [start_dt, end_dt] window with the same per-entry join pattern
            if total_parts == 0:
                cur.execute(
                    """
                    SELECT COALESCE(SUM(entry_cnt), 0) AS total_parts
                    FROM (
                        SELECT
                            pe.id,
                            COUNT(mp.id) AS entry_cnt
                        FROM production_entries pe
                        LEFT JOIN machine_production mp
                          ON mp.machine_id = pe.machine_id
                         AND TIME_TO_SEC(mp.total_cycle_time) > 0
                         AND LOWER(TRIM(mp.results)) IN ('pass','fail')
                         AND COALESCE(mp.shift_start, mp.`timestamp`) >= pe.start_time
                         AND COALESCE(mp.shift_start, mp.`timestamp`) <  pe.end_time
                        WHERE pe.machine_id = %s
                          AND pe.start_time IS NOT NULL
                          AND pe.end_time   IS NOT NULL
                          AND pe.start_time >= %s
                          AND pe.end_time   <= %s
                        GROUP BY pe.id
                    ) t
                    """,
                    (int(machine_id), start_dt, end_dt)
                )
                tp_row2 = cur.fetchone() or {"total_parts": 0}
                total_parts = int(tp_row2.get("total_parts") or 0)

            return total_parts, good_parts, min_cycle_s, avg_cycle_s

    finally:
        conn.close()


def get_machine_data_points_window(machine_id: int, start_dt: datetime, end_dt: datetime) -> int:
    sql = """
        SELECT COUNT(*) AS c
        FROM machine_data
        WHERE machine_id = %s
          AND `timestamp` >= %s
          AND `timestamp` <= %s
    """
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(sql, (machine_id, start_dt, end_dt))
            return int(cur.fetchone()["c"] or 0)
    finally:
        conn.close()

# ---------------- A / P / Q per machine (window) ----------------
def compute_apq(machine_id: int, label: str, start_dt: datetime, end_dt: datetime, ideal_cycle_time_seconds: int | None, decimals: int):
    planned_s   = get_planned_seconds_window(str(machine_id), start_dt, end_dt)
    downtime_s  = get_downtime_seconds_window(int(machine_id), start_dt, end_dt)
    breakdown_s = get_breakdown_seconds_window(int(machine_id), start_dt, end_dt)
    machine_on_s = max(planned_s - downtime_s - breakdown_s, 0)

    total_parts, good_parts, min_cycle_s, _ = get_parts_quality_window(str(machine_id), start_dt, end_dt)

    #print(f"good parts: {good_parts}")
    #print(f"total parts: {total_parts}")
    quality_pct = (good_parts / total_parts * 100.0) if total_parts > 0 else 0.0

    availability_pct = (machine_on_s / planned_s * 100.0) if planned_s > 0 else 0.0

    if ideal_cycle_time_seconds is None:
        ideal_cycle_time_seconds = int(min_cycle_s) if min_cycle_s is not None else 0
    numer = ideal_cycle_time_seconds * total_parts
    performance_pct = (numer / machine_on_s * 100.0) if machine_on_s > 0 else 0.0

    A = r(availability_pct/100.0, decimals)
    P = r(performance_pct/100.0, decimals)
    Q = r(quality_pct/100.0, decimals)
    O = r(A * P * Q, decimals)

    data_points = get_machine_data_points_window(int(machine_id), start_dt, end_dt)

    return {
        "machine_id": int(machine_id),
        "machine_name": label,
        "availability": A,
        "performance": P,
        "quality": Q,
        "overall_oee": O,
        "parts_produced": int(total_parts),
        "total_downtime_minutes": r(downtime_s/60.0, 2),
        "total_production_minutes": r(machine_on_s/60.0, 2),
        "period_start": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "period_end": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "data_points": data_points
    }, {
        "A_frac": A, "P_frac": P, "Q_frac": Q,
        "downtime_min": downtime_s/60.0,
        "prod_min": machine_on_s/60.0,
        "parts": total_parts
    }



@app.route("/api/oee/calculate", methods=["GET"])
def metrics_oee_fleet():
    try:
        mid = request.args.get("machine_id")
        machine_id = int(mid) if (mid and mid.isdigit()) else None

        start_date = request.args.get("start_date")
        end_date   = request.args.get("end_date")
        start_dt, end_dt = normalize_window(start_date, end_date)

        dec = request.args.get("decimals")
        decimals = int(dec) if (dec and dec.isdigit()) else 3  # default to 3 to match your sample

        ideal_str = request.args.get("ideal_cycle_time_seconds")
        ideal_cycle_time_seconds = int(ideal_str) if (ideal_str and ideal_str.isdigit()) else None

        # Check if export format is requested
        export_format = request.args.get("export")  # 'pdf' or 'csv'

        machines = get_machines(machine_id)
        if not machines:
            return jsonify({"success": False, "error": "No machines found"}), 404

        individual = []
        fleet_A = fleet_P = fleet_Q = 0.0
        fleet_downtime = fleet_prod_min = 0.0
        fleet_parts = 0
        for m in machines:
            row, meta = compute_apq(
                m["id"], m["label"], start_dt, end_dt,
                ideal_cycle_time_seconds, decimals
            )
            row['vfj_no'] = m.get("vfj_no")
            individual.append(row)
            fleet_A += meta["A_frac"]
            fleet_P += meta["P_frac"]
            fleet_Q += meta["Q_frac"]
            fleet_downtime += meta["downtime_min"]
            fleet_prod_min += meta["prod_min"]
            fleet_parts += meta["parts"]

        n = len(machines)
        fleet_A_avg = (fleet_A / n) if n else 0.0
        fleet_P_avg = (fleet_P / n) if n else 0.0
        fleet_Q_avg = (fleet_Q / n) if n else 0.0
        fleet_OEE   = fleet_A_avg * fleet_P_avg * fleet_Q_avg

        resp = {
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "fleet_summary": {
                "fleet_availability": r(fleet_A_avg, decimals),
                "fleet_overall_oee": r(fleet_OEE, decimals),
                "fleet_performance": r(fleet_P_avg, decimals),
                "fleet_quality": r(fleet_Q_avg, decimals),
                "total_fleet_downtime": r(fleet_downtime, 2),
                "total_fleet_production_time": r(fleet_prod_min, 2),
                "total_machines": n,
                "total_parts_produced": int(fleet_parts)
            },
            "individual_machines": individual
        }

        # Handle export formats
        if export_format == 'pdf':
            return export_oee_data_as_pdf(resp, start_date, end_date)
        elif export_format == 'csv':
            return export_oee_data_as_csv(resp, start_date, end_date)
        
        return jsonify(resp), 200

    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": "internal_error", "details": str(e)}), 500


# Helper function to export OEE data as PDF
def export_oee_data_as_pdf(data, start_date=None, end_date=None):
    """
    Export OEE calculation data as PDF
    """
    try:
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=landscape(A4),
            rightMargin=30,
            leftMargin=30,
            topMargin=30,
            bottomMargin=30
        )

        # Styles
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            textColor=colors.HexColor('#1e40af'),
            spaceAfter=12,
            alignment=1,
            fontName='Helvetica-Bold'
        )
        
        subtitle_style = ParagraphStyle(
            'CustomSubtitle',
            parent=styles['Normal'],
            fontSize=12,
            textColor=colors.HexColor('#64748b'),
            spaceAfter=20,
            alignment=1
        )

        section_style = ParagraphStyle(
            'SectionTitle',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#1e40af'),
            spaceAfter=10,
            fontName='Helvetica-Bold'
        )

        elements = []
        
        # Title
        elements.append(Paragraph("OEE Performance Report", title_style))
        
        # Date range subtitle
        if start_date and end_date:
            date_text = f"Period: {start_date} to {end_date}"
            elements.append(Paragraph(date_text, subtitle_style))
        else:
            elements.append(Spacer(1, 12))

        # Fleet Summary Section
        fleet = data.get("fleet_summary", {})
        if fleet:
            elements.append(Paragraph("Fleet Summary", section_style))
            elements.append(Spacer(1, 8))
            
            fleet_data = [
                ["Metric", "Value"],
                ["Fleet OEE", f"{float(fleet.get('fleet_overall_oee', 0)) * 100:.2f}%"],
                ["Availability", f"{float(fleet.get('fleet_availability', 0)) * 100:.2f}%"],
                ["Performance", f"{float(fleet.get('fleet_performance', 0)) * 100:.2f}%"],
                ["Quality", f"{float(fleet.get('fleet_quality', 0)) * 100:.2f}%"],
                ["Total Machines", str(fleet.get('total_machines', 0))],
                ["Parts Produced", str(fleet.get('total_parts_produced', 0))],
                ["Total Downtime (min)", f"{float(fleet.get('total_fleet_downtime', 0)):.2f}"],
                ["Production Time (min)", f"{float(fleet.get('total_fleet_production_time', 0)):.2f}"],
            ]
            
            fleet_table = Table(fleet_data, colWidths=[250, 200])
            fleet_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e40af')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 11),
                ('FONTSIZE', (0, 1), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('TOPPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')])
            ]))
            elements.append(fleet_table)
            elements.append(Spacer(1, 30))

        # Individual Machines Section
        machines = data.get("individual_machines", [])
        if machines:
            elements.append(Paragraph("Individual Machine Performance", section_style))
            elements.append(Spacer(1, 8))
            
            machine_data = [["Machine", "VFJ No", "OEE %", "Avail. %", "Perf. %", "Qual. %", "Parts", "Downtime (min)"]]
            
            for m in machines:
                machine_data.append([
                    str(m.get('machine_name', 'N/A')),
                    str(m.get('vfj_no', 'N/A')),
                    f"{float(m.get('overall_oee', 0)) * 100:.1f}",
                    f"{float(m.get('availability', 0)) * 100:.1f}",
                    f"{float(m.get('performance', 0)) * 100:.1f}",
                    f"{float(m.get('quality', 0)) * 100:.1f}",
                    str(m.get('parts_produced', 0)),
                    f"{float(m.get('total_downtime_minutes', 0)):.1f}"
                ])
            
            # machine_table = Table(machine_data, colWidths=[90, 70, 60, 60, 60, 60, 60, 80])
            #machine_table = Table(machine_data, colWidths=[120, 80, 60, 60, 60, 60, 60, 80])
            machine_table = Table(machine_data, colWidths=[140, 90, 55, 55, 55, 55, 55, 75])
            machine_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e40af')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('TOPPADDING', (0, 0), (-1, 0), 12),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')])
            ]))
            elements.append(machine_table)

        # Footer
        elements.append(Spacer(1, 30))
        footer_text = f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        footer_style = ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontSize=8,
            textColor=colors.grey,
            alignment=1
        )
        elements.append(Paragraph(footer_text, footer_style))

        # Build PDF
        doc.build(elements)
        
        # Get PDF data
        pdf_data = buffer.getvalue()
        buffer.close()

        # Create response with correct headers
        response = make_response(pdf_data)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=oee_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
        response.headers['Content-Length'] = len(pdf_data)
        
        return response

    except Exception as e:
        print(f"PDF Export Error: {str(e)}")
        traceback.print_exc()
        return jsonify({"error": f"Failed to generate PDF: {str(e)}"}), 500


# Helper function to export OEE data as CSV
def export_oee_data_as_csv(data, start_date=None, end_date=None):
    """
    Export OEE calculation data as CSV
    """
    try:
        output = StringIO()
        writer = csv.writer(output)
        
        # Title and metadata
        writer.writerow(['OEE Performance Report'])
        if start_date and end_date:
            writer.writerow([f'Period: {start_date} to {end_date}'])
        writer.writerow([f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'])
        writer.writerow([])  # Empty row
        
        # Fleet Summary
        fleet = data.get("fleet_summary", {})
        if fleet:
            writer.writerow(['FLEET SUMMARY'])
            writer.writerow(['Metric', 'Value'])
            writer.writerow(['Fleet OEE', f"{float(fleet.get('fleet_overall_oee', 0)) * 100:.2f}%"])
            writer.writerow(['Fleet Availability', f"{float(fleet.get('fleet_availability', 0)) * 100:.2f}%"])
            writer.writerow(['Fleet Performance', f"{float(fleet.get('fleet_performance', 0)) * 100:.2f}%"])
            writer.writerow(['Fleet Quality', f"{float(fleet.get('fleet_quality', 0)) * 100:.2f}%"])
            writer.writerow(['Total Machines', fleet.get('total_machines', 0)])
            writer.writerow(['Total Parts Produced', fleet.get('total_parts_produced', 0)])
            writer.writerow(['Total Fleet Downtime (min)', f"{float(fleet.get('total_fleet_downtime', 0)):.2f}"])
            writer.writerow(['Total Production Time (min)', f"{float(fleet.get('total_fleet_production_time', 0)):.2f}"])
            writer.writerow([])  # Empty row
        
        # Individual Machines
        machines = data.get("individual_machines", [])
        if machines:
            writer.writerow(['INDIVIDUAL MACHINE PERFORMANCE'])
            writer.writerow([
                'Machine ID',
                'Machine Name',
                'VFJ No',
                'OEE (%)',
                'Availability (%)',
                'Performance (%)',
                'Quality (%)',
                'Parts Produced',
                'Downtime (min)',
                'Production Time (min)',
                'Period Start',
                'Period End',
                'Data Points'
            ])
            
            for m in machines:
                writer.writerow([
                    m.get('machine_id', ''),
                    m.get('machine_name', ''),
                    m.get('vfj_no', ''),
                    f"{float(m.get('overall_oee', 0)) * 100:.2f}",
                    f"{float(m.get('availability', 0)) * 100:.2f}",
                    f"{float(m.get('performance', 0)) * 100:.2f}",
                    f"{float(m.get('quality', 0)) * 100:.2f}",
                    m.get('parts_produced', 0),
                    f"{float(m.get('total_downtime_minutes', 0)):.2f}",
                    f"{float(m.get('total_production_minutes', 0)):.2f}",
                    m.get('period_start', ''),
                    m.get('period_end', ''),
                    m.get('data_points', 0)
                ])
        
        # Get CSV content
        csv_data = output.getvalue()
        output.close()
        
        # Create response
        response = make_response(csv_data)
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = f'attachment; filename=oee_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        response.headers['Content-Length'] = len(csv_data)
        
        return response
        
    except Exception as e:
        print(f"CSV Export Error: {str(e)}")
        traceback.print_exc()
        return jsonify({"error": f"Failed to generate CSV: {str(e)}"}), 500


## How to use:

# **For JSON response (default):**
# ```
# GET /api/oee/calculate?machine_id=1&start_date=2025-01-01&end_date=2025-01-31
# ```

# **For PDF export:**
# ```
# GET /api/oee/calculate?machine_id=1&start_date=2025-01-01&end_date=2025-01-31&export=pdf
# ```

# **For CSV export:**
# ```
# GET /api/oee/calculate?machine_id=1&start_date=2025-01-01&end_date=2025-01-31&export=csv

@app.route("/health")
def health():
    """Proper health check that tests database connectivity"""
    health_status = {
        "status": "healthy", 
        "timestamp": datetime.utcnow().isoformat(),
        "service": "machine_monitoring_api"
    }
    
    # Test database connection
    conn = get_db_connection()
    if conn is None:
        health_status["status"] = "unhealthy"
        health_status["database"] = "disconnected"
        health_status["error"] = "Database connection failed"
        return jsonify(health_status), 500
    
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        health_status["database"] = "connected"
        cursor.close()
        conn.close()
        return jsonify(health_status), 200
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["database"] = "error"
        health_status["error"] = "Database query failed"
        if conn:
            conn.close()
        return jsonify(health_status), 500


if __name__ == "__main__":
    # app.run(debug=False, use_reloader=False, host="0.0.0.0", port=8000)
    from waitress import serve
    serve(app, host="0.0.0.0", port=3000)