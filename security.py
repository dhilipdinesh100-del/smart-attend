import re
import secrets
import time
from functools import wraps
from datetime import datetime
from typing import Optional, Tuple
from flask import session, request, redirect, url_for, abort, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from config import logger

# In-memory rate limiting map: ip -> [timestamps]
_login_attempts = {}

def hash_password(password: str) -> str:
    """Generate secure salted PBKDF2/SHA256 password hash."""
    return generate_password_hash(password, method="scrypt")

def verify_password(password_hash: str, password: str) -> bool:
    """Verify password against salted hash."""
    if not password_hash or not password:
        return False
    return check_password_hash(password_hash, password)

def login_required(f):
    """Decorator to require authenticated admin session for routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("user_id"):
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({"status": "error", "message": "Authentication required. Please log in."}), 401
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("login_page", next=request.full_path))
        return f(*args, **kwargs)
    return decorated_function

# ==========================================
# CSRF PROTECTION
# ==========================================

def generate_csrf_token() -> str:
    """Generate and store CSRF token in session if not present."""
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)
    return session["_csrf_token"]

def validate_csrf():
    """Validate CSRF token on destructive state-modifying requests."""
    if request.method in ["POST", "PUT", "DELETE", "PATCH"]:
        # Allow internal video stream / camera control / capture endpoints
        if request.path.startswith("/video_feed") or request.path.startswith("/api/camera") or request.path.startswith("/api/capture"):
            return
            
        token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        
        # Also check JSON payload if applicable
        if not token and request.is_json:
            payload = request.get_json(silent=True) or {}
            token = payload.get("csrf_token")
            
        session_token = session.get("_csrf_token")
        
        # If user is authenticated, enforce matching session CSRF token
        if session.get("user_id"):
            if not token or not session_token or not secrets.compare_digest(str(token), str(session_token)):
                logger.warning(f"CSRF validation failed for path {request.path} from IP {request.remote_addr}")
                abort(400, description="Invalid or missing CSRF token. Please refresh and try again.")

# ==========================================
# RATE LIMITING
# ==========================================

def check_login_rate_limit(ip_address: str, max_attempts: int = 5, window_seconds: int = 60) -> Tuple[bool, int]:
    """
    Check if IP has exceeded login attempts.
    Returns (is_allowed, seconds_remaining).
    """
    now = time.time()
    attempts = _login_attempts.get(ip_address, [])
    # Filter attempts within window
    attempts = [t for t in attempts if now - t < window_seconds]
    _login_attempts[ip_address] = attempts
    
    if len(attempts) >= max_attempts:
        oldest = attempts[0]
        retry_after = int(window_seconds - (now - oldest))
        return False, max(1, retry_after)
        
    return True, 0

def record_login_attempt(ip_address: str):
    """Record a failed login attempt for rate limiting."""
    now = time.time()
    if ip_address not in _login_attempts:
        _login_attempts[ip_address] = []
    _login_attempts[ip_address].append(now)

def clear_login_attempts(ip_address: str):
    """Clear failed attempts upon successful login."""
    if ip_address in _login_attempts:
        del _login_attempts[ip_address]

# ==========================================
# INPUT VALIDATION HELPERS
# ==========================================

def validate_student_name(name: str) -> Tuple[bool, str, str]:
    """Validate student full name. Returns (is_valid, cleaned_name, error_msg)."""
    cleaned = (name or "").strip()
    if not cleaned:
        return False, "", "Student full name is required."
    if len(cleaned) < 2 or len(cleaned) > 100:
        return False, "", "Student name must be between 2 and 100 characters."
    # Prevent HTML / script injection
    if "<" in cleaned or ">" in cleaned or '"' in cleaned:
        return False, "", "Student name contains invalid characters."
    return True, cleaned, ""

def validate_roll_no(roll_no: str) -> Tuple[bool, str, str]:
    """Validate student roll number. Returns (is_valid, cleaned_roll, error_msg)."""
    cleaned = (roll_no or "").strip()
    if not cleaned:
        return False, "", "Roll number is required."
    if len(cleaned) < 1 or len(cleaned) > 50:
        return False, "", "Roll number must be between 1 and 50 characters."
    if not re.match(r"^[A-Za-z0-9_\-\.\/ ]+$", cleaned):
        return False, "", "Roll number contains invalid characters (letters, numbers, hyphens only)."
    return True, cleaned, ""

def validate_date(date_str: str) -> bool:
    """Validate YYYY-MM-DD format."""
    if not date_str:
        return False
    try:
        datetime.strptime(date_str.strip(), "%Y-%m-%d")
        return True
    except ValueError:
        return False

def validate_month(month_str: str) -> bool:
    """Validate YYYY-MM format."""
    if not month_str:
        return False
    try:
        datetime.strptime(month_str.strip(), "%Y-%m")
        return True
    except ValueError:
        return False

def validate_method(method: str) -> str:
    """Validate and normalize attendance method ('face', 'qr', or 'manual')."""
    m = (method or "").strip().lower()
    if m in ["face", "qr", "manual"]:
        return m
    return "face"

def validate_admin_full_name(name: str) -> Tuple[bool, str, str]:
    """Validate admin full name. Returns (is_valid, cleaned_name, error_msg)."""
    cleaned = (name or "").strip()
    if not cleaned:
        return False, "", "Full Name is required."
    if len(cleaned) < 2 or len(cleaned) > 100:
        return False, "", "Full Name must be between 2 and 100 characters."
    if "<" in cleaned or ">" in cleaned or '"' in cleaned:
        return False, "", "Full Name contains invalid characters."
    return True, cleaned, ""

def validate_admin_username(username: str) -> Tuple[bool, str, str]:
    """Validate admin username. Returns (is_valid, cleaned_username, error_msg)."""
    cleaned = (username or "").strip()
    if not cleaned:
        return False, "", "Username is required."
    if len(cleaned) < 3 or len(cleaned) > 30:
        return False, "", "Username must be between 3 and 30 characters."
    if not re.match(r"^[a-zA-Z0-9_]+$", cleaned):
        return False, "", "Username can only contain letters, numbers, and underscores."
    return True, cleaned, ""

def validate_admin_email(email: str) -> Tuple[bool, str, str]:
    """Validate admin email address. Returns (is_valid, cleaned_email, error_msg)."""
    cleaned = (email or "").strip().lower()
    if not cleaned:
        return False, "", "Email is required."
    if len(cleaned) > 120:
        return False, "", "Email address is too long."
    email_regex = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    if not re.match(email_regex, cleaned):
        return False, "", "Please enter a valid email address."
    return True, cleaned, ""

def validate_admin_password(password: str, confirm_password: Optional[str] = None) -> Tuple[bool, str]:
    """Validate admin password and confirmation. Returns (is_valid, error_msg)."""
    if not password:
        return False, "Password is required."
    if len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if confirm_password is not None and password != confirm_password:
        return False, "Passwords do not match."
    return True, ""
