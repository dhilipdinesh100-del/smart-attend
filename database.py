import sqlite3
import shutil
import threading
import os
import random
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
from contextlib import contextmanager

from config import DB_PATH, DEFAULT_SETTINGS, QR_DIR, FACES_DIR, BACKUP_DIR, logger
import security

@contextmanager
def db_session():
    """Context manager for SQLite connections that ensures commit, foreign key enforcement, and clean close."""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def get_db_connection() -> sqlite3.Connection:
    """Create and return a SQLite database connection with row factory and foreign keys on."""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    """Initialize database tables, unique indexes, migrations, default settings, and default admin user."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    
    with db_session() as conn:
        cursor = conn.cursor()
        
        # 1. Users Table (Admin authentication)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL DEFAULT '',
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'admin',
                created_at TEXT NOT NULL
            );
        """)
        
        # Schema migration: check if 'full_name' or 'email' column exists in existing users table
        cursor.execute("PRAGMA table_info(users);")
        user_cols = [col[1] for col in cursor.fetchall()]
        if "full_name" not in user_cols and len(user_cols) > 0:
            cursor.execute("ALTER TABLE users ADD COLUMN full_name TEXT NOT NULL DEFAULT '';")
        if "email" not in user_cols and len(user_cols) > 0:
            cursor.execute("ALTER TABLE users ADD COLUMN email TEXT DEFAULT '';")
            
        # 2. Students Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                roll_no TEXT UNIQUE NOT NULL,
                student_id_code INTEGER,
                created_at TEXT NOT NULL
            );
        """)
        
        # Schema migration: check if 'student_id_code' column exists in existing students table
        cursor.execute("PRAGMA table_info(students);")
        student_cols = [col[1] for col in cursor.fetchall()]
        if "student_id_code" not in student_cols and len(student_cols) > 0:
            cursor.execute("ALTER TABLE students ADD COLUMN student_id_code INTEGER;")
            cursor.execute("UPDATE students SET student_id_code = id WHERE student_id_code IS NULL OR student_id_code = 0;")

        # 2b. Student ID History Table (Tracks ownership, released queue, and recycling)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS student_id_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id_code INTEGER NOT NULL,
                internal_student_id INTEGER,
                student_name TEXT NOT NULL,
                roll_no TEXT NOT NULL,
                event TEXT NOT NULL,
                assigned_date TEXT NOT NULL,
                released_date TEXT DEFAULT '',
                status TEXT NOT NULL,
                previous_owner TEXT DEFAULT '',
                current_owner TEXT DEFAULT ''
            );
        """)
        
        # 3. Attendance Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                method TEXT NOT NULL,
                date TEXT NOT NULL DEFAULT '',
                date_time TEXT NOT NULL,
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
            );
        """)
        
        # Schema migration: check if 'date' column exists in existing attendance table
        cursor.execute("PRAGMA table_info(attendance);")
        columns = [col[1] for col in cursor.fetchall()]
        if "date" not in columns and len(columns) > 0:
            cursor.execute("ALTER TABLE attendance ADD COLUMN date TEXT NOT NULL DEFAULT '';")
            cursor.execute("UPDATE attendance SET date = substr(date_time, 1, 10) WHERE date = '' OR date IS NULL;")
            
        # 4. Settings Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        
        # 5. Database-Level Unique Constraint / Indexes for strict attendance & auth integrity
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_student_date ON attendance(student_id, date);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_attendance_student_id ON attendance(student_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(date);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_attendance_method ON attendance(method);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_students_roll ON students(roll_no);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_students_code ON students(student_id_code);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_student_id_hist_status ON student_id_history(status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_student_id_hist_code ON student_id_history(student_id_code);")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username);")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email) WHERE email IS NOT NULL AND email != '';")
        
        # 6. Default Admin User creation if none exists
        admin = cursor.execute("SELECT id FROM users WHERE username = 'admin';").fetchone()
        if not admin:
            default_pw_hash = security.hash_password("admin123")
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                "INSERT INTO users (full_name, username, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?, ?);",
                ("System Administrator", "admin", "admin@smartattend.local", default_pw_hash, "admin", now_str)
            )
            logger.info("Initialized default administrator account (username: admin)")
        else:
            cursor.execute("UPDATE users SET full_name = 'System Administrator' WHERE (full_name = '' OR full_name IS NULL) AND username = 'admin';")
            
        # 7. Populate default settings if not present
        for key, val in DEFAULT_SETTINGS.items():
            cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?);", (key, val))

# ==========================================
# USER & AUTHENTICATION HELPERS
# ==========================================

def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    if not username:
        return None
    with db_session() as conn:
        row = conn.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(?);", (username.strip(),)).fetchone()
        return dict(row) if row else None

def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    if not email:
        return None
    with db_session() as conn:
        row = conn.execute("SELECT * FROM users WHERE LOWER(email) = LOWER(?);", (email.strip(),)).fetchone()
        return dict(row) if row else None

def get_user_by_username_or_email(identifier: str) -> Optional[Dict[str, Any]]:
    if not identifier:
        return None
    clean = identifier.strip()
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE LOWER(username) = LOWER(?) OR LOWER(email) = LOWER(?);",
            (clean, clean)
        ).fetchone()
        return dict(row) if row else None

def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    with db_session() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?;", (user_id,)).fetchone()
        return dict(row) if row else None

def verify_user_credentials(identifier: str, password: str) -> Optional[Dict[str, Any]]:
    user = get_user_by_username_or_email(identifier)
    if not user:
        return None
    if security.verify_password(user["password_hash"], password):
        return user
    return None

def create_admin_user(full_name: str, username: str, email: str, password: str, role: str = "admin") -> Tuple[bool, str, Optional[int]]:
    valid_name, full_name, err_name = security.validate_admin_full_name(full_name)
    if not valid_name:
        return False, err_name, None
        
    valid_user, username, err_user = security.validate_admin_username(username)
    if not valid_user:
        return False, err_user, None
        
    valid_email, email, err_email = security.validate_admin_email(email)
    if not valid_email:
        return False, err_email, None
        
    valid_pw, err_pw = security.validate_admin_password(password)
    if not valid_pw:
        return False, err_pw, None
        
    # Pre-check duplicates with clear messages
    if get_user_by_username(username):
        return False, "Username already exists.", None
        
    if get_user_by_email(email):
        return False, "Email already registered.", None
        
    pw_hash = security.hash_password(password)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (full_name, username, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?, ?);",
                (full_name, username, email, pw_hash, role, now_str)
            )
            user_id = cursor.lastrowid
            logger.info(f"Admin account created: {username} ({full_name}, {email}, ID: {user_id})")
            return True, "Admin account created successfully. Please sign in.", user_id
    except sqlite3.IntegrityError as e:
        err_msg = str(e).lower()
        if "username" in err_msg:
            return False, "Username already exists.", None
        elif "email" in err_msg:
            return False, "Email already registered.", None
        return False, "An account with these credentials already exists.", None
    except Exception as e:
        logger.error(f"Database error creating admin user: {e}")
        return False, f"Database error: {str(e)}", None

def create_user(username: str, password: str, role: str = "admin") -> Tuple[bool, str]:
    return create_admin_user("Administrator", username, f"{username}@smartattend.local", password, role)[:2]

def get_all_admin_users() -> List[Dict[str, Any]]:
    """Retrieve all administrator accounts without password hashes."""
    with db_session() as conn:
        rows = conn.execute(
            "SELECT id, full_name, username, email, role, created_at FROM users ORDER BY id ASC;"
        ).fetchall()
        return [dict(r) for r in rows]

# In-memory caches for high-performance camera loops
_settings_cache: Dict[str, str] = {}
_student_cache: Dict[int, Dict[str, Any]] = {}
_student_roll_cache: Dict[str, Dict[str, Any]] = {}
_cache_lock = threading.Lock()

def invalidate_student_cache(student_id: Optional[int] = None, roll_no: Optional[str] = None):
    with _cache_lock:
        if student_id is not None:
            _student_cache.pop(int(student_id), None)
        else:
            _student_cache.clear()
            
        if roll_no is not None:
            _student_roll_cache.pop(roll_no.strip(), None)
        else:
            _student_roll_cache.clear()

# ==========================================
# SETTINGS HELPERS
# ==========================================

def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    with _cache_lock:
        if key in _settings_cache:
            return _settings_cache[key]

    with db_session() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?;", (key,)).fetchone()
        val = row["value"] if row else (default or DEFAULT_SETTINGS.get(key))
        if val is not None:
            with _cache_lock:
                _settings_cache[key] = str(val)
        return val

def set_setting(key: str, value: str) -> None:
    with _cache_lock:
        _settings_cache[key] = str(value)
    with db_session() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?);", (key, str(value)))

def get_all_settings() -> Dict[str, str]:
    with db_session() as conn:
        rows = conn.execute("SELECT key, value FROM settings;").fetchall()
        result = dict(DEFAULT_SETTINGS)
        for r in rows:
            result[r["key"]] = r["value"]
            with _cache_lock:
                _settings_cache[r["key"]] = r["value"]
        return result

# ==========================================
# STUDENT MANAGEMENT & ID HISTORY HELPERS
# ==========================================

def get_next_available_student_id(conn: sqlite3.Connection) -> Tuple[int, Optional[str], Optional[int]]:
    """
    Determine the Student ID code for a new registration following strict priority:
    1. Check for RELEASED IDs in student_id_history (FIFO: oldest released ID first).
    2. If found, reuse that released ID.
    3. If no released IDs exist, generate a brand-new random 6-digit integer (100000..999999)
       with collision check against all active and historical student IDs.
    Returns: (student_id_code, previous_owner_name, released_history_row_id)
    """
    # 1. Look for oldest released ID (FIFO queue)
    released = conn.execute(
        "SELECT id, student_id_code, student_name, previous_owner FROM student_id_history WHERE status = 'RELEASED' ORDER BY id ASC LIMIT 1;"
    ).fetchone()
    
    if released:
        prev_name = released["student_name"] or released["previous_owner"] or ""
        return int(released["student_id_code"]), prev_name, int(released["id"])
    
    # 2. Query all existing active student_id_codes and historical student_id_codes to avoid collision
    active_rows = conn.execute("SELECT student_id_code FROM students WHERE student_id_code IS NOT NULL;").fetchall()
    hist_rows = conn.execute("SELECT student_id_code FROM student_id_history;").fetchall()
    used_ids = set([r["student_id_code"] for r in active_rows if r["student_id_code"] is not None] + 
                   [r["student_id_code"] for r in hist_rows if r["student_id_code"] is not None])
    
    # Generate non-colliding random 6-digit ID
    for _ in range(10000):
        candidate = random.randint(100000, 999999)
        if candidate not in used_ids:
            return candidate, None, None
            
    max_id = max(used_ids) if used_ids else 100000
    return max_id + 1, None, None

def add_student(name: str, roll_no: str) -> Tuple[bool, str, Optional[int]]:
    valid_name, name, err_name = security.validate_student_name(name)
    if not valid_name:
        return False, err_name, None
        
    valid_roll, roll_no, err_roll = security.validate_roll_no(roll_no)
    if not valid_roll:
        return False, err_roll, None
        
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        with db_session() as conn:
            cursor = conn.cursor()
            
            # Check duplicate roll number first
            existing = cursor.execute("SELECT id FROM students WHERE roll_no = ?;", (roll_no,)).fetchone()
            if existing:
                return False, f"A student with Roll Number '{roll_no}' already exists.", None

            student_code, prev_owner, released_hist_id = get_next_available_student_id(conn)
            
            cursor.execute(
                "INSERT INTO students (name, roll_no, student_id_code, created_at) VALUES (?, ?, ?, ?);",
                (name, roll_no, student_code, created_at)
            )
            student_id = cursor.lastrowid
            
            if released_hist_id is not None:
                # Mark previous released history record as consumed/reassigned
                cursor.execute(
                    "UPDATE student_id_history SET status = 'DELETED' WHERE id = ?;",
                    (released_hist_id,)
                )
                event_type = "REASSIGNED"
                prev_name = prev_owner or ""
            else:
                event_type = "ASSIGNED"
                prev_name = ""
                
            cursor.execute(
                """
                INSERT INTO student_id_history 
                (student_id_code, internal_student_id, student_name, roll_no, event, assigned_date, released_date, status, previous_owner, current_owner)
                VALUES (?, ?, ?, ?, ?, ?, '', 'ACTIVE', ?, ?);
                """,
                (student_code, student_id, name, roll_no, event_type, created_at, prev_name, name)
            )
            
            invalidate_student_cache()
            logger.info(f"Student registered: {name} (Roll: {roll_no}, Internal ID: {student_id}, Student ID Code: {student_code})")
            return True, "Student registered successfully.", student_id
    except sqlite3.IntegrityError:
        return False, f"A student with Roll Number '{roll_no}' already exists.", None
    except Exception as e:
        logger.error(f"Database error registering student: {e}")
        return False, f"Database error: {str(e)}", None

def get_student_by_id(student_id: int) -> Optional[Dict[str, Any]]:
    try:
        sid = int(student_id)
    except (ValueError, TypeError):
        return None
        
    with _cache_lock:
        if sid in _student_cache:
            return _student_cache[sid]

    with db_session() as conn:
        row = conn.execute("SELECT * FROM students WHERE id = ?;", (sid,)).fetchone()
        if row:
            s_dict = dict(row)
            if not s_dict.get("student_id_code"):
                s_dict["student_id_code"] = s_dict["id"]
            with _cache_lock:
                _student_cache[sid] = s_dict
                _student_roll_cache[s_dict["roll_no"]] = s_dict
            return s_dict
        return None

def get_student_by_roll(roll_no: str) -> Optional[Dict[str, Any]]:
    if not roll_no:
        return None
    r_key = roll_no.strip()
    with _cache_lock:
        if r_key in _student_roll_cache:
            return _student_roll_cache[r_key]

    with db_session() as conn:
        row = conn.execute("SELECT * FROM students WHERE roll_no = ?;", (r_key,)).fetchone()
        if row:
            s_dict = dict(row)
            if not s_dict.get("student_id_code"):
                s_dict["student_id_code"] = s_dict["id"]
            with _cache_lock:
                _student_cache[s_dict["id"]] = s_dict
                _student_roll_cache[r_key] = s_dict
            return s_dict
        return None

def get_all_students(search_query: Optional[str] = None) -> List[Dict[str, Any]]:
    with db_session() as conn:
        if search_query:
            query = f"%{search_query.strip()}%"
            rows = conn.execute(
                "SELECT * FROM students WHERE name LIKE ? OR roll_no LIKE ? ORDER BY id ASC;",
                (query, query)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM students ORDER BY id ASC;").fetchall()
            
        students = []
        for r in rows:
            s = dict(r)
            if not s.get("student_id_code"):
                s["student_id_code"] = s["id"]
            sid_str = str(s["id"])
            face_dir = FACES_DIR / sid_str
            sample_count = 0
            if face_dir.exists():
                try:
                    with os.scandir(str(face_dir)) as it:
                        sample_count = sum(1 for entry in it if entry.is_file() and entry.name.endswith(('.jpg', '.png')))
                except Exception:
                    sample_count = 0
            s["face_samples"] = sample_count
            s["face_status"] = "Ready" if sample_count >= 10 else ("Partial" if sample_count > 0 else "Pending")
            qr_file = QR_DIR / f"student_{s['id']}.png"
            s["qr_status"] = "Available" if qr_file.exists() else "Missing"
            students.append(s)
        return students

def update_student(student_id: int, name: str, roll_no: str) -> Tuple[bool, str]:
    valid_name, name, err_name = security.validate_student_name(name)
    if not valid_name:
        return False, err_name
        
    valid_roll, roll_no, err_roll = security.validate_roll_no(roll_no)
    if not valid_roll:
        return False, err_roll
        
    try:
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE students SET name = ?, roll_no = ? WHERE id = ?;",
                (name, roll_no, int(student_id))
            )
            if cursor.rowcount == 0:
                return False, "Student not found."
            invalidate_student_cache(student_id=student_id)
            logger.info(f"Student updated: ID #{student_id} -> {name} ({roll_no})")
            return True, "Student updated successfully."
    except sqlite3.IntegrityError:
        return False, f"Roll Number '{roll_no}' is already taken by another student."
    except Exception as e:
        logger.error(f"Database error updating student #{student_id}: {e}")
        return False, f"Database error: {str(e)}"

def delete_student(student_id: int) -> Tuple[bool, str]:
    try:
        sid = int(student_id)
        student = get_student_by_id(sid)
        if not student:
            return False, "Student not found."
            
        student_code = student.get("student_id_code") or student["id"]
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        assigned_date = student.get("created_at") or now_str

        with db_session() as conn:
            cursor = conn.cursor()
            
            # 1. Update existing active history records for this student_id_code to DELETED
            cursor.execute(
                "UPDATE student_id_history SET status = 'DELETED', released_date = ? WHERE student_id_code = ? AND (status = 'ACTIVE' OR internal_student_id = ?);",
                (now_str, student_code, sid)
            )
            
            # 2. Record the RELEASED event in ID history so it enters the FIFO queue
            cursor.execute(
                """
                INSERT INTO student_id_history 
                (student_id_code, internal_student_id, student_name, roll_no, event, assigned_date, released_date, status, previous_owner, current_owner)
                VALUES (?, ?, ?, ?, 'RELEASED', ?, ?, 'RELEASED', ?, '');
                """,
                (student_code, sid, student["name"], student["roll_no"], assigned_date, now_str, student["name"])
            )
            
            # 3. Delete from active students table
            cursor.execute("DELETE FROM students WHERE id = ?;", (sid,))
            
        invalidate_student_cache(student_id=sid, roll_no=student.get("roll_no"))
        
        # Clean up files: QR code and Face dataset
        qr_file = QR_DIR / f"student_{sid}.png"
        if qr_file.exists():
            try: qr_file.unlink()
            except Exception: pass
                
        faces_dir = FACES_DIR / str(sid)
        if faces_dir.exists():
            try: shutil.rmtree(faces_dir)
            except Exception: pass
                
        logger.info(f"Student deleted: #{sid} ({student['name']}, Roll: {student['roll_no']}, ID Code: {student_code})")
        return True, "Student and all associated data deleted successfully."
    except Exception as e:
        logger.error(f"Error deleting student #{student_id}: {e}")
        return False, f"Database error: {str(e)}"

def get_student_id_history() -> List[Dict[str, Any]]:
    """Retrieve complete chronological student ID assignment and recycling history."""
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM student_id_history ORDER BY id ASC;"
        ).fetchall()
        return [dict(r) for r in rows]

# ==========================================
# ATTENDANCE MANAGEMENT & INTEGRITY
# ==========================================

def is_attendance_marked_today(student_id: int, target_date: Optional[str] = None) -> bool:
    if not target_date:
        target_date = datetime.now().strftime("%Y-%m-%d")
    with db_session() as conn:
        row = conn.execute(
            "SELECT id FROM attendance WHERE student_id = ? AND date = ? LIMIT 1;",
            (int(student_id), target_date.strip())
        ).fetchone()
        return row is not None

def mark_attendance(student_id: int, method: str, date_time: Optional[str] = None) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Mark attendance for a student with double-layer duplicate protection:
    1. Fast pre-check query
    2. Atomic SQLite unique constraint on (student_id, date)
    Returns (success, message, record_dict).
    """
    student = get_student_by_id(student_id)
    if not student:
        return False, f"Student ID #{student_id} not found in database.", None
        
    if not date_time:
        date_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
    date_str = date_time[:10]
    time_str = date_time[11:] if len(date_time) > 10 else ""
    method_val = security.validate_method(method)
    
    # Layer 1: Check existing record
    if is_attendance_marked_today(student_id, date_str):
        with db_session() as conn:
            existing = conn.execute(
                """
                SELECT a.*, s.name, s.roll_no 
                FROM attendance a 
                JOIN students s ON a.student_id = s.id 
                WHERE a.student_id = ? AND a.date = ? 
                LIMIT 1;
                """,
                (student_id, date_str)
            ).fetchone()
            record = dict(existing) if existing else None
        return False, f"Already marked today for {student['name']} ({student['roll_no']}).", record

    # Layer 2: Atomic parameterized insert guarded by UNIQUE(student_id, date)
    try:
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO attendance (student_id, method, date, date_time) VALUES (?, ?, ?, ?);",
                (student_id, method_val, date_str, date_time)
            )
            att_id = cursor.lastrowid
            
            record = {
                "id": att_id,
                "student_id": student_id,
                "name": student["name"],
                "roll_no": student["roll_no"],
                "method": method_val,
                "date_time": date_time,
                "date": date_str,
                "time": time_str
            }
            logger.info(f"Attendance marked: {student['name']} ({student['roll_no']}) via {method_val.upper()} at {time_str}")
            return True, f"Attendance marked for {student['name']} ({student['roll_no']}) via {method_val.upper()}.", record
    except sqlite3.IntegrityError:
        # Caught concurrent race condition collision
        with db_session() as conn:
            existing = conn.execute(
                "SELECT a.*, s.name, s.roll_no FROM attendance a JOIN students s ON a.student_id = s.id WHERE a.student_id = ? AND a.date = ? LIMIT 1;",
                (student_id, date_str)
            ).fetchone()
            record = dict(existing) if existing else None
        return False, f"Already marked today for {student['name']} ({student['roll_no']}).", record
    except Exception as e:
        logger.error(f"Error saving attendance for student #{student_id}: {e}")
        return False, f"Error saving attendance: {str(e)}", None

def delete_attendance(attendance_id: int) -> Tuple[bool, str]:
    try:
        aid = int(attendance_id)
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM attendance WHERE id = ?;", (aid,))
            if cursor.rowcount == 0:
                return False, "Attendance record not found."
            logger.info(f"Attendance record deleted: Log #{aid}")
            return True, "Attendance record deleted successfully."
    except Exception as e:
        logger.error(f"Error deleting attendance #{attendance_id}: {e}")
        return False, f"Database error: {str(e)}"

# ==========================================
# REPORTING & ANALYTICS
# ==========================================

def get_daily_attendance(target_date: Optional[str] = None, method_filter: Optional[str] = None, search_query: Optional[str] = None) -> Dict[str, Any]:
    if not target_date or not security.validate_date(target_date):
        target_date = datetime.now().strftime("%Y-%m-%d")
        
    target_dt = datetime.strptime(target_date, "%Y-%m-%d").date()
    today_dt = datetime.now().date()
    is_future = target_dt > today_dt

    with db_session() as conn:
        all_students = conn.execute("SELECT * FROM students ORDER BY roll_no ASC, name ASC;").fetchall()
        records = conn.execute(
            """
            SELECT a.id as attendance_id, a.student_id, a.method, a.date, a.date_time, s.name, s.roll_no
            FROM attendance a
            JOIN students s ON a.student_id = s.id
            WHERE a.date = ?
            ORDER BY a.date_time DESC;
            """,
            (target_date,)
        ).fetchall()
        
        att_map = {}
        for r in records:
            att_map[r["student_id"]] = dict(r)
            
        student_list = []
        present_count = 0
        face_count = 0
        qr_count = 0
        manual_count = 0
        
        for s in all_students:
            s_dict = dict(s)
            sid = s_dict["id"]
            if sid in att_map:
                att_info = att_map[sid]
                s_dict["status"] = "PRESENT"
                s_dict["attendance_id"] = att_info["attendance_id"]
                s_dict["method"] = att_info["method"].upper()
                s_dict["date_time"] = att_info["date_time"]
                s_dict["time"] = att_info["date_time"][11:] if len(att_info["date_time"]) > 10 else ""
                present_count += 1
                if att_info["method"].lower() == "face":
                    face_count += 1
                elif att_info["method"].lower() == "qr":
                    qr_count += 1
                elif att_info["method"].lower() == "manual":
                    manual_count += 1
            else:
                s_dict["status"] = "UPCOMING" if is_future else "ABSENT"
                s_dict["attendance_id"] = None
                s_dict["method"] = "-"
                s_dict["date_time"] = "-"
                s_dict["time"] = "-"
                
            if method_filter and method_filter.lower() != "all":
                if s_dict["method"].lower() != method_filter.lower():
                    continue
                    
            if search_query:
                q = search_query.strip().lower()
                if q not in s_dict["name"].lower() and q not in s_dict["roll_no"].lower():
                    continue
                    
            student_list.append(s_dict)
            
        total_students = len(all_students)
        absent_count = 0 if is_future else max(0, total_students - present_count)
        if is_future and present_count == 0:
            attendance_rate = 0.0
        else:
            attendance_rate = round((present_count / total_students * 100), 1) if total_students > 0 else 0.0
        
        return {
            "date": target_date,
            "is_future": is_future,
            "total_students": total_students,
            "present_count": present_count,
            "absent_count": absent_count,
            "attendance_rate": attendance_rate,
            "face_count": face_count,
            "qr_count": qr_count,
            "manual_count": manual_count,
            "records": student_list
        }

def get_monthly_attendance(student_id: Optional[int] = None, year_month: Optional[str] = None) -> Dict[str, Any]:
    if not year_month or not security.validate_month(year_month):
        year_month = datetime.now().strftime("%Y-%m")
        
    year, month = map(int, year_month.split("-"))
    import calendar
    days_in_month = calendar.monthrange(year, month)[1]
    today_dt = datetime.now().date()
    
    with db_session() as conn:
        if student_id:
            student = conn.execute("SELECT * FROM students WHERE id = ?;", (int(student_id),)).fetchone()
            students = [student] if student else []
        else:
            students = conn.execute("SELECT * FROM students ORDER BY roll_no ASC;").fetchall()
            
        query = """
            SELECT a.id, a.student_id, a.method, a.date, a.date_time, s.name, s.roll_no
            FROM attendance a
            JOIN students s ON a.student_id = s.id
            WHERE substr(a.date, 1, 7) = ?
            ORDER BY a.date_time ASC;
        """
        records = conn.execute(query, (year_month,)).fetchall()
        
        attendance_by_student_date = {}
        for r in records:
            attendance_by_student_date[(r["student_id"], r["date"])] = dict(r)

        student_data = None
        if student_id and students:
            s = dict(students[0])
            present_days = 0
            absent_days = 0
            upcoming_days = 0
            face_count = 0
            qr_count = 0
            manual_count = 0
            
            day_records = []
            for day in range(1, days_in_month + 1):
                cur_date = date(year, month, day)
                cur_date_str = f"{year:04d}-{month:02d}-{day:02d}"
                weekday_name = calendar.day_name[calendar.weekday(year, month, day)]
                
                key = (s["id"], cur_date_str)
                if cur_date <= today_dt:
                    if key in attendance_by_student_date:
                        att = attendance_by_student_date[key]
                        status = "PRESENT"
                        present_days += 1
                        method = att["method"].upper()
                        time_val = att["date_time"][11:]
                        if att["method"].lower() == "face":
                            face_count += 1
                        elif att["method"].lower() == "qr":
                            qr_count += 1
                        elif att["method"].lower() == "manual":
                            manual_count += 1
                        att_id = att["id"]
                    else:
                        status = "ABSENT"
                        absent_days += 1
                        method = "-"
                        time_val = "-"
                        att_id = None
                else:
                    # Future date
                    status = "UPCOMING"
                    upcoming_days += 1
                    method = "-"
                    time_val = "-"
                    att_id = None
                    
                day_records.append({
                    "date": cur_date_str,
                    "day": f"{day:02d}",
                    "weekday": weekday_name,
                    "status": status,
                    "method": method,
                    "time": time_val,
                    "attendance_id": att_id
                })
                
            elapsed_days = present_days + absent_days
            att_percentage = round((present_days / elapsed_days * 100), 1) if elapsed_days > 0 else 0.0
            
            student_data = {
                "student": s,
                "present_days": present_days,
                "absent_days": absent_days,
                "upcoming_days": upcoming_days,
                "upcoming_count": upcoming_days,
                "elapsed_days": elapsed_days,
                "total_days": days_in_month,
                "attendance_percentage": att_percentage,
                "face_count": face_count,
                "qr_count": qr_count,
                "manual_count": manual_count,
                "calendar_days": day_records
            }

        return {
            "year_month": year_month,
            "year": year,
            "month": month,
            "days_in_month": days_in_month,
            "student_data": student_data,
            "all_students": [dict(st) for st in conn.execute("SELECT * FROM students ORDER BY roll_no ASC;").fetchall()]
        }

def get_attendance_history(student_id: Optional[int] = None, method: Optional[str] = None,
                           start_date: Optional[str] = None, end_date: Optional[str] = None,
                           search_query: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    with db_session() as conn:
        conditions = []
        params = []
        
        if student_id:
            conditions.append("a.student_id = ?")
            params.append(int(student_id))
            
        if method and method.lower() != "all":
            conditions.append("LOWER(a.method) = ?")
            params.append(method.lower().strip())
            
        if start_date and security.validate_date(start_date):
            conditions.append("a.date >= ?")
            params.append(start_date)
            
        if end_date and security.validate_date(end_date):
            conditions.append("a.date <= ?")
            params.append(end_date)
            
        if search_query:
            conditions.append("(s.name LIKE ? OR s.roll_no LIKE ?)")
            q = f"%{search_query.strip()}%"
            params.extend([q, q])
            
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        
        count_query = f"SELECT COUNT(*) as total FROM attendance a JOIN students s ON a.student_id = s.id {where_clause};"
        total_count = conn.execute(count_query, params).fetchone()["total"]
        
        query = f"""
            SELECT a.id, a.student_id, a.method, a.date, a.date_time, s.name, s.roll_no
            FROM attendance a
            JOIN students s ON a.student_id = s.id
            {where_clause}
            ORDER BY a.date_time DESC
            LIMIT ? OFFSET ?;
        """
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        
        records = []
        for r in rows:
            d = dict(r)
            d["time"] = d["date_time"][11:] if len(d["date_time"]) > 10 else ""
            d["method"] = d["method"].upper()
            records.append(d)
            
        return {
            "total": total_count,
            "records": records,
            "limit": limit,
            "offset": offset
        }

def get_dashboard_stats() -> Dict[str, Any]:
    today_str = datetime.now().strftime("%Y-%m-%d")
    with db_session() as conn:
        total_students = conn.execute("SELECT COUNT(*) as c FROM students;").fetchone()["c"]
        total_records = conn.execute("SELECT COUNT(*) as c FROM attendance;").fetchone()["c"]
        
        # Single aggregate query for today's summary metrics
        today_agg = conn.execute(
            """
            SELECT 
                COUNT(*) as present_count,
                SUM(CASE WHEN LOWER(method) = 'face' THEN 1 ELSE 0 END) as face_today,
                SUM(CASE WHEN LOWER(method) = 'qr' THEN 1 ELSE 0 END) as qr_today,
                SUM(CASE WHEN LOWER(method) = 'manual' THEN 1 ELSE 0 END) as manual_today
            FROM attendance
            WHERE date = ?;
            """,
            (today_str,)
        ).fetchone()
        
        today_present = today_agg["present_count"] or 0
        face_today = today_agg["face_today"] or 0
        qr_today = today_agg["qr_today"] or 0
        manual_today = today_agg["manual_today"] or 0
        today_absent = max(0, total_students - today_present)
        attendance_rate = round((today_present / total_students * 100), 1) if total_students > 0 else 0.0
        
        # Overall method totals
        totals_agg = conn.execute(
            """
            SELECT 
                SUM(CASE WHEN LOWER(method) = 'face' THEN 1 ELSE 0 END) as face_total,
                SUM(CASE WHEN LOWER(method) = 'qr' THEN 1 ELSE 0 END) as qr_total,
                SUM(CASE WHEN LOWER(method) = 'manual' THEN 1 ELSE 0 END) as manual_total
            FROM attendance;
            """
        ).fetchone()
        face_total = totals_agg["face_total"] or 0
        qr_total = totals_agg["qr_total"] or 0
        manual_total = totals_agg["manual_total"] or 0
        
        recent_rows = conn.execute(
            """
            SELECT a.id, a.student_id, a.method, a.date, a.date_time, s.name, s.roll_no
            FROM attendance a
            JOIN students s ON a.student_id = s.id
            ORDER BY a.date_time DESC
            LIMIT 10;
            """
        ).fetchall()
        
        recent_records = []
        for r in recent_rows:
            d = dict(r)
            d["time"] = d["date_time"][11:] if len(d["date_time"]) > 10 else ""
            d["method"] = d["method"].upper()
            d["status"] = "PRESENT"
            recent_records.append(d)
            
        return {
            "total_students": total_students,
            "today_present": today_present,
            "today_absent": today_absent,
            "attendance_rate": attendance_rate,
            "total_records": total_records,
            "face_today": face_today,
            "qr_today": qr_today,
            "manual_today": manual_today,
            "face_total": face_total,
            "qr_total": qr_total,
            "manual_total": manual_total,
            "recent_records": recent_records
        }

def get_attendance_trends(days: int = 7) -> Dict[str, Any]:
    from datetime import timedelta
    today = datetime.now().date()
    dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days - 1, -1, -1)]
    
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT date as att_date, 
                   COUNT(DISTINCT student_id) as present_count,
                   SUM(CASE WHEN LOWER(method) = 'face' THEN 1 ELSE 0 END) as face_count,
                   SUM(CASE WHEN LOWER(method) = 'qr' THEN 1 ELSE 0 END) as qr_count,
                   SUM(CASE WHEN LOWER(method) = 'manual' THEN 1 ELSE 0 END) as manual_count
            FROM attendance
            WHERE date >= ?
            GROUP BY date;
            """,
            (dates[0],)
        ).fetchall()
        
        data_map = {r["att_date"]: dict(r) for r in rows}
        
        labels = []
        present_series = []
        face_series = []
        qr_series = []
        manual_series = []
        
        for d in dates:
            labels.append(datetime.strptime(d, "%Y-%m-%d").strftime("%b %d"))
            item = data_map.get(d, {"present_count": 0, "face_count": 0, "qr_count": 0, "manual_count": 0})
            present_series.append(item["present_count"])
            face_series.append(item["face_count"])
            qr_series.append(item["qr_count"])
            manual_series.append(item.get("manual_count", 0))
            
        return {
            "labels": labels,
            "dates": dates,
            "present": present_series,
            "face": face_series,
            "qr": qr_series,
            "manual": manual_series
        }

def get_top_students(limit: int = 5) -> List[Dict[str, Any]]:
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.name, s.roll_no, COUNT(a.id) as attendance_count
            FROM students s
            LEFT JOIN attendance a ON s.id = a.student_id
            GROUP BY s.id, s.name, s.roll_no
            ORDER BY attendance_count DESC, s.name ASC
            LIMIT ?;
            """,
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

# ==========================================
# DATABASE BACKUP HELPER
# ==========================================

def backup_database() -> Tuple[bool, str, Optional[Path]]:
    """Create a safe snapshot backup of the SQLite database into backups/."""
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUP_DIR / f"attendance_backup_{timestamp}.db"
        
        # SQLite online backup API
        with db_session() as src_conn:
            dst_conn = sqlite3.connect(str(backup_path))
            src_conn.backup(dst_conn)
            dst_conn.close()
            
        logger.info(f"Database backup created successfully: {backup_path.name}")
        return True, "Backup created successfully.", backup_path
    except Exception as e:
        logger.error(f"Database backup failed: {e}")
        return False, f"Backup failed: {str(e)}", None
