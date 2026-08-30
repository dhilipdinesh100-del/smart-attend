import os
import io
import csv
import json
import time
from datetime import datetime
from pathlib import Path
from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, jsonify, send_file, Response, stream_with_context, session, abort
)

from config import (
    BASE_DIR, DATA_DIR, QR_DIR, FACES_DIR, MODEL_DIR, MODEL_PATH,
    HAAR_CASCADE_PATH, BACKUP_DIR, DEFAULT_SETTINGS, SECRET_KEY,
    SESSION_COOKIE_HTTPONLY, SESSION_COOKIE_SAMESITE, SESSION_COOKIE_SECURE,
    PERMANENT_SESSION_LIFETIME, HOST, PORT, FLASK_DEBUG,
    logger
)
import database
import security
import qr_engine
import face_engine
import admin_audit
from camera import camera_manager

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["SESSION_COOKIE_HTTPONLY"] = SESSION_COOKIE_HTTPONLY
app.config["SESSION_COOKIE_SAMESITE"] = SESSION_COOKIE_SAMESITE
app.config["SESSION_COOKIE_SECURE"] = SESSION_COOKIE_SECURE
app.config["PERMANENT_SESSION_LIFETIME"] = PERMANENT_SESSION_LIFETIME

# Initialize database schema, default admin, and admin audit registry
database.init_db()
admin_audit.init_admin_registry()

# Global CSRF validation before modifying requests
@app.before_request
def csrf_protection():
    # Only validate CSRF on state-changing methods
    security.validate_csrf()

# Global template context processor
@app.context_processor
def inject_global_context():
    settings = database.get_all_settings()
    user_id = session.get("user_id")
    current_user = database.get_user_by_id(user_id) if user_id else None
    
    current_user_name = ""
    if current_user and current_user.get("full_name"):
        current_user_name = current_user["full_name"]
    elif current_user and current_user.get("username"):
        current_user_name = current_user["username"]
    elif session.get("full_name"):
        current_user_name = session.get("full_name")
    elif session.get("username"):
        current_user_name = session.get("username")
    elif user_id:
        current_user_name = "Administrator"
    
    return {
        "app_name": settings.get("app_name", "SmartAttend"),
        "now": datetime.now(),
        "today_str": datetime.now().strftime("%Y-%m-%d"),
        "model_exists": MODEL_PATH.exists(),
        "csrf_token": security.generate_csrf_token,
        "current_user": current_user,
        "current_user_name": current_user_name
    }

# ==================================================
# AUTHENTICATION & SESSION ROUTES
# ==================================================

@app.route("/login", methods=["GET", "POST"])
def login_page():
    next_url = request.args.get("next") or request.form.get("next") or url_for("dashboard_page")
    
    # If already logged in, redirect
    if session.get("user_id"):
        return redirect(url_for("dashboard_page"))

    if request.method == "POST":
        ip_addr = request.remote_addr or "127.0.0.1"
        allowed, wait_secs = security.check_login_rate_limit(ip_addr)
        if not allowed:
            flash(f"Too many failed login attempts. Please wait {wait_secs} seconds.", "error")
            return render_template("login.html", next_url=next_url)

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = database.verify_user_credentials(username, password)
        if user:
            security.clear_login_attempts(ip_addr)
            session.permanent = True
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            session["full_name"] = user.get("full_name") or user["username"]
            
            # Record last login in private Excel registry audit
            admin_audit.record_admin_login(user["username"])

            logger.info(f"User '{username}' logged in successfully from {ip_addr}")
            flash(f"Welcome back, {user['username']}!", "success")
            return redirect(next_url)
        else:
            security.record_login_attempt(ip_addr)
            logger.warning(f"Failed login attempt for username '{username}' from {ip_addr}")
            flash("Invalid username or password.", "error")

    return render_template("login.html", next_url=next_url)

@app.route("/register", methods=["GET", "POST"])
def register_admin_page():
    if session.get("user_id"):
        return redirect(url_for("dashboard_page"))

    if request.method == "POST":
        ip_addr = request.remote_addr or "127.0.0.1"
        allowed, wait_secs = security.check_login_rate_limit(ip_addr)
        if not allowed:
            flash(f"Too many attempts. Please wait {wait_secs} seconds.", "error")
            return render_template("register.html")

        full_name = request.form.get("full_name", "").strip()
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        # 1. Full name validation
        valid_name, full_name, err_name = security.validate_admin_full_name(full_name)
        if not valid_name:
            flash(err_name, "error")
            return render_template("register.html", full_name=full_name, username=username, email=email)

        # 2. Username validation
        valid_user, username, err_user = security.validate_admin_username(username)
        if not valid_user:
            flash(err_user, "error")
            return render_template("register.html", full_name=full_name, username=username, email=email)

        # 3. Email validation
        valid_email, email, err_email = security.validate_admin_email(email)
        if not valid_email:
            flash(err_email, "error")
            return render_template("register.html", full_name=full_name, username=username, email=email)

        # 4. Password validation
        valid_pw, err_pw = security.validate_admin_password(password, confirm_password)
        if not valid_pw:
            flash(err_pw, "error")
            return render_template("register.html", full_name=full_name, username=username, email=email)

        # 5. Create user in database
        success, msg, user_id = database.create_admin_user(full_name, username, email, password)
        if success and user_id:
            # Append registration record to private Excel audit
            admin_audit.record_admin_registration(
                admin_id=user_id,
                full_name=full_name,
                username=username,
                email=email
            )
            flash("Admin account created successfully. Please sign in.", "success")
            return redirect(url_for("login_page"))
        else:
            flash(msg, "error")
            return render_template("register.html", full_name=full_name, username=username, email=email)

    return render_template("register.html")

@app.route("/logout", methods=["GET", "POST"])
def logout_action():
    username = session.get("username", "Unknown")
    session.clear()
    logger.info(f"User '{username}' logged out.")
    flash("You have been logged out securely.", "info")
    return redirect(url_for("login_page"))

# ==================================================
# PAGE ROUTES (AUTHENTICATED)
# ==================================================

@app.route("/")
@app.route("/dashboard")
@security.login_required
def dashboard_page():
    user_id = session.get("user_id")
    user = database.get_user_by_id(user_id) if user_id else None
    current_user_name = (user.get("full_name") if user and user.get("full_name") else None) or session.get("full_name") or session.get("username") or "Administrator"
    
    stats = database.get_dashboard_stats()
    trends = database.get_attendance_trends(days=7)
    top_students = database.get_top_students(limit=5)
    return render_template(
        "dashboard.html",
        active_page="dashboard",
        current_user=user,
        current_user_name=current_user_name,
        stats=stats,
        trends=trends,
        top_students=top_students
    )

@app.route("/students")
@security.login_required
def students_page():
    search = request.args.get("search", "").strip()
    students = database.get_all_students(search_query=search if search else None)
    return render_template(
        "students.html",
        active_page="students",
        students=students,
        search_query=search
    )

@app.route("/students/<int:student_id>")
@security.login_required
def student_detail_page(student_id: int):
    student = database.get_student_by_id(student_id)
    if not student:
        flash(f"Student ID #{student_id} not found.", "error")
        return redirect(url_for("students_page"))
        
    qr_engine.get_or_create_qr(student_id)
    face_count = face_engine.get_student_sample_count(student_id)
    monthly_summary = database.get_monthly_attendance(student_id=student_id)
    
    return render_template(
        "student_detail.html",
        active_page="students",
        student=student,
        face_count=face_count,
        monthly_summary=monthly_summary
    )

@app.route("/students/register", methods=["GET", "POST"])
@app.route("/students/add", methods=["GET", "POST"])
@security.login_required
def register_student_page():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        roll_no = request.form.get("roll_no", "").strip()
        
        valid_name, name, err_name = security.validate_student_name(name)
        if not valid_name:
            flash(err_name, "error")
            return render_template("register_student.html", active_page="register", name=name, roll_no=roll_no)
            
        valid_roll, roll_no, err_roll = security.validate_roll_no(roll_no)
        if not valid_roll:
            flash(err_roll, "error")
            return render_template("register_student.html", active_page="register", name=name, roll_no=roll_no)
            
        success, message, student_id = database.add_student(name, roll_no)
        if success and student_id:
            qr_engine.generate_qr_code(student_id)
            flash(f"Student '{name}' registered successfully! Unique QR pass generated.", "success")
            return redirect(url_for("student_detail_page", student_id=student_id))
        else:
            flash(message, "error")
            return render_template("register_student.html", active_page="register", name=name, roll_no=roll_no)
            
    return render_template("register_student.html", active_page="register")

@app.route("/students/edit/<int:student_id>", methods=["POST"])
@security.login_required
def edit_student_action(student_id: int):
    name = request.form.get("name", "").strip()
    roll_no = request.form.get("roll_no", "").strip()
    
    success, message = database.update_student(student_id, name, roll_no)
    if success:
        qr_engine.generate_qr_code(student_id, force_regenerate=True)
        flash("Student details updated successfully.", "success")
    else:
        flash(message, "error")
        
    return redirect(url_for("students_page"))

@app.route("/students/delete/<int:student_id>", methods=["POST"])
@security.login_required
def delete_student_action(student_id: int):
    success, message = database.delete_student(student_id)
    if success:
        flash("Student deleted and Student ID released to recycling queue.", "success")
    else:
        flash(message, "error")
    return redirect(url_for("students_page"))

@app.route("/students/id-history")
@security.login_required
def student_id_history_page():
    history = database.get_student_id_history()
    return render_template(
        "student_id_history.html",
        active_page="students",
        history=history
    )

@app.route("/students/id-history/export/csv")
@security.login_required
def export_student_id_history_csv_action():
    history = database.get_student_id_history()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Student ID",
        "Student Name",
        "Event",
        "Assigned Date",
        "Released Date",
        "Status",
        "Previous Owner",
        "Current Owner"
    ])
    for h in history:
        writer.writerow([
            h.get("student_id_code", ""),
            h.get("student_name", ""),
            h.get("event", ""),
            h.get("assigned_date", ""),
            h.get("released_date", ""),
            h.get("status", ""),
            h.get("previous_owner", ""),
            h.get("current_owner", "")
        ])
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=student_id_history.csv"}
    )

@app.route("/qr/view/<int:student_id>")
@security.login_required
def view_qr_page(student_id: int):
    student = database.get_student_by_id(student_id)
    if not student:
        flash(f"Student #{student_id} not found.", "error")
        return redirect(url_for("students_page"))
        
    qr_path = qr_engine.get_or_create_qr(student_id)
    if request.args.get("raw") == "1":
        return send_file(str(qr_path), mimetype="image/png")
        
    return render_template("view_qr.html", active_page="students", student=student)

@app.route("/qr/download/<int:student_id>")
@security.login_required
def download_qr_file(student_id: int):
    student = database.get_student_by_id(student_id)
    if not student:
        flash(f"Student #{student_id} not found.", "error")
        return redirect(url_for("students_page"))
        
    qr_path = qr_engine.get_or_create_qr(student_id)
    download_name = f"student_{student_id}_qr.png"
    return send_file(
        str(qr_path),
        mimetype="image/png",
        as_attachment=True,
        download_name=download_name
    )

@app.route("/qr/print/<int:student_id>")
@security.login_required
def print_qr_page(student_id: int):
    student = database.get_student_by_id(student_id)
    if not student:
        flash(f"Student #{student_id} not found.", "error")
        return redirect(url_for("students_page"))
        
    qr_engine.get_or_create_qr(student_id)
    return render_template("print_qr.html", student=student)

@app.route("/capture/<int:student_id>")
@security.login_required
def face_capture_page(student_id: int):
    student = database.get_student_by_id(student_id)
    if not student:
        flash(f"Student #{student_id} not found.", "error")
        return redirect(url_for("students_page"))
        
    sample_count = face_engine.get_student_sample_count(student_id)
    target_samples = int(database.get_setting("samples_per_student", "30"))
    return render_template(
        "capture.html",
        active_page="capture",
        student=student,
        sample_count=sample_count,
        target_samples=target_samples
    )

@app.route("/train", methods=["GET", "POST"])
@security.login_required
def train_model_page():
    all_students = database.get_all_students()
    ready_students = [s for s in all_students if s["face_samples"] > 0]
    total_samples = sum(s["face_samples"] for s in ready_students)
    
    train_result = None
    if request.method == "POST":
        train_result = face_engine.train_lbph_model()
        if train_result["success"]:
            logger.info(f"Model trained: {train_result['message']}")
            flash(train_result["message"], "success")
        else:
            logger.warning(f"Model training warning: {train_result['message']}")
            flash(train_result["message"], "error")
            
    return render_template(
        "train.html",
        active_page="train",
        all_students=all_students,
        ready_students=ready_students,
        total_samples=total_samples,
        train_result=train_result,
        model_exists=MODEL_PATH.exists()
    )

@app.route("/face-attendance")
@security.login_required
def face_attendance_page():
    model_ready = MODEL_PATH.exists()
    conf_thresh = database.get_setting("face_confidence_threshold", "60")
    recent = database.get_dashboard_stats().get("recent_records", [])
    return render_template(
        "face_attendance.html",
        active_page="face_attendance",
        model_ready=model_ready,
        conf_thresh=conf_thresh,
        recent=recent
    )

@app.route("/qr-attendance")
@security.login_required
def qr_attendance_page():
    recent = database.get_dashboard_stats().get("recent_records", [])
    return render_template(
        "qr_attendance.html",
        active_page="qr_attendance",
        recent=recent
    )

@app.route("/daily-attendance")
@security.login_required
def daily_attendance_page():
    target_date = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))
    if not security.validate_date(target_date):
        target_date = datetime.now().strftime("%Y-%m-%d")
        
    method_filter = request.args.get("method", "all")
    search = request.args.get("search", "").strip()
    
    report = database.get_daily_attendance(
        target_date=target_date,
        method_filter=method_filter,
        search_query=search if search else None
    )
    return render_template(
        "daily_attendance.html",
        active_page="daily_attendance",
        report=report,
        target_date=target_date,
        method_filter=method_filter,
        search_query=search
    )

@app.route("/monthly-attendance")
@security.login_required
def monthly_attendance_page():
    student_id_str = request.args.get("student_id")
    year_month = request.args.get("month", datetime.now().strftime("%Y-%m"))
    
    if not security.validate_month(year_month):
        year_month = datetime.now().strftime("%Y-%m")
        
    student_id = int(student_id_str) if (student_id_str and student_id_str.isdigit()) else None
    
    report = database.get_monthly_attendance(student_id=student_id, year_month=year_month)
    return render_template(
        "monthly_attendance.html",
        active_page="monthly_attendance",
        report=report,
        selected_student_id=student_id,
        selected_month=year_month
    )

@app.route("/attendance-history")
@security.login_required
def attendance_history_page():
    student_id_str = request.args.get("student_id")
    student_id = int(student_id_str) if (student_id_str and student_id_str.isdigit()) else None
    method = request.args.get("method", "all")
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    search = request.args.get("search", "").strip()
    
    history = database.get_attendance_history(
        student_id=student_id,
        method=method,
        start_date=start_date if start_date else None,
        end_date=end_date if end_date else None,
        search_query=search if search else None,
        limit=200
    )
    
    all_students = database.get_all_students()
    
    return render_template(
        "attendance.html",
        active_page="attendance_history",
        history=history,
        all_students=all_students,
        student_id=student_id,
        method=method,
        start_date=start_date,
        end_date=end_date,
        search_query=search
    )

@app.route("/attendance/export/csv")
@app.route("/attendance/export")
@security.login_required
def export_attendance_csv():
    """Export attendance audit log in standard CSV format without sensitive credentials."""
    import io
    import csv
    
    student_id_str = request.args.get("student_id")
    student_id = int(student_id_str) if (student_id_str and student_id_str.isdigit()) else None
    method = request.args.get("method", "all")
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    search = request.args.get("search", "").strip()
    
    history = database.get_attendance_history(
        student_id=student_id,
        method=method,
        start_date=start_date if start_date else None,
        end_date=end_date if end_date else None,
        search_query=search if search else None,
        limit=10000
    )
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Student ID", "Student Name", "Roll Number", "Date", "Time", "Method", "Status"])
    
    for r in history["records"]:
        writer.writerow([
            r["student_id"],
            r["name"],
            r["roll_no"],
            r["date"],
            r["time"],
            r["method"],
            "PRESENT"
        ])
        
    output.seek(0)
    filename = f"attendance_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.route("/attendance/delete/<int:attendance_id>", methods=["POST"])
@security.login_required
def delete_attendance_action(attendance_id: int):
    success, msg = database.delete_attendance(attendance_id)
    if success:
        flash("Attendance record deleted successfully.", "success")
    else:
        flash(msg, "error")
        
    next_url = request.form.get("next_url") or request.referrer or url_for("daily_attendance_page")
    return redirect(next_url)

@app.route("/settings", methods=["GET", "POST"])
@security.login_required
def settings_page():
    if request.method == "POST":
        app_name = request.form.get("app_name", "SmartAttend").strip()
        face_conf = request.form.get("face_confidence_threshold", "60").strip()
        cam_idx = request.form.get("camera_index", "0").strip()
        cooldown = request.form.get("recognition_cooldown", "5").strip()
        samples = request.form.get("samples_per_student", "30").strip()
        
        # Validation
        if not app_name: app_name = "SmartAttend"
        try:
            fc = float(face_conf)
            if fc < 10 or fc > 150: face_conf = "60"
        except ValueError: face_conf = "60"
        
        database.set_setting("app_name", app_name)
        database.set_setting("face_confidence_threshold", face_conf)
        database.set_setting("camera_index", cam_idx)
        database.set_setting("recognition_cooldown", cooldown)
        database.set_setting("samples_per_student", samples)
        
        camera_manager.release_camera()
        logger.info("System settings updated by administrator")
        flash("Settings saved successfully.", "success")
    settings = database.get_all_settings()
    audit_records = admin_audit.get_all_audit_records()
    return render_template(
        "settings.html",
        active_page="settings",
        settings=settings,
        audit_records=audit_records
    )

@app.route("/users")
@security.login_required
def users_page():
    users = admin_audit.get_all_audit_records()
    return render_template(
        "users.html",
        active_page="users",
        users=users
    )

@app.route("/users/new", methods=["GET", "POST"])
@app.route("/users/create", methods=["GET", "POST"])
@security.login_required
def new_user_page():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        # 1. Full name validation
        valid_name, full_name, err_name = security.validate_admin_full_name(full_name)
        if not valid_name:
            flash(err_name, "error")
            return render_template("create_user.html", active_page="new_user", full_name=full_name, username=username, email=email)

        # 2. Username validation
        valid_user, username, err_user = security.validate_admin_username(username)
        if not valid_user:
            flash(err_user, "error")
            return render_template("create_user.html", active_page="new_user", full_name=full_name, username=username, email=email)

        # 3. Email validation
        valid_email, email, err_email = security.validate_admin_email(email)
        if not valid_email:
            flash(err_email, "error")
            return render_template("create_user.html", active_page="new_user", full_name=full_name, username=username, email=email)

        # 4. Password validation
        valid_pw, err_pw = security.validate_admin_password(password, confirm_password)
        if not valid_pw:
            flash(err_pw, "error")
            return render_template("create_user.html", active_page="new_user", full_name=full_name, username=username, email=email)

        # 5. Create user in database
        success, msg, user_id = database.create_admin_user(full_name, username, email, password)
        if success and user_id:
            # Append registration record to private Excel audit
            admin_audit.record_admin_registration(
                admin_id=user_id,
                full_name=full_name,
                username=username,
                email=email
            )
            flash(f"Administrator account '{username}' created successfully.", "success")
            return redirect(url_for("users_page"))
        else:
            flash(msg, "error")
            return render_template("create_user.html", active_page="new_user", full_name=full_name, username=username, email=email)

    return render_template("create_user.html", active_page="new_user")

@app.route("/settings/export/admin-registry")
@security.login_required
def export_admin_registry_action():
    """Export the private Excel admin registry for authenticated administrators."""
    admin_audit.init_admin_registry()
    if not admin_audit.EXCEL_REGISTRY_PATH.exists():
        flash("Admin registry file could not be generated.", "error")
        return redirect(url_for("settings_page"))
    return send_file(
        str(admin_audit.EXCEL_REGISTRY_PATH),
        as_attachment=True,
        download_name="admin_registry.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.route("/backup", methods=["POST"])
@security.login_required
def backup_database_action():
    success, msg, backup_path = database.backup_database()
    if success and backup_path:
        response = send_file(
            str(backup_path),
            as_attachment=True,
            download_name=backup_path.name,
            mimetype="application/x-sqlite3"
        )
        response.headers["X-Backup-Filename"] = backup_path.name
        response.headers["Access-Control-Expose-Headers"] = "Content-Disposition, X-Backup-Filename"
        return response
    else:
        flash(msg, "error")
        return redirect(url_for("settings_page"))

# ==================================================
# VIDEO STREAMING ROUTES (AUTHENTICATED)
# ==================================================

@app.route("/video_feed/face")
@security.login_required
def video_feed_face():
    return Response(
        camera_manager.generate_face_stream(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )

@app.route("/video_feed/qr")
@security.login_required
def video_feed_qr():
    return Response(
        camera_manager.generate_qr_stream(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )

@app.route("/video_feed/capture/<int:student_id>")
@security.login_required
def video_feed_capture(student_id: int):
    return Response(
        camera_manager.generate_capture_stream(student_id),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )

# ==================================================
# HEALTH CHECK & REST APIs
# ==================================================

@app.route("/health")
def health_check():
    """System health check endpoint returning status of database and model."""
    db_ok = False
    try:
        with database.db_session() as conn:
            conn.execute("SELECT 1;").fetchone()
            db_ok = True
    except Exception:
        db_ok = False
        
    model_ok = MODEL_PATH.exists()
    
    status_code = 200 if db_ok else 503
    return jsonify({
        "status": "ok" if db_ok else "degraded",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "database": "ok" if db_ok else "error",
        "model": "ok" if model_ok else "not_trained"
    }), status_code

@app.route("/api/dashboard")
@security.login_required
def api_dashboard_stats():
    stats = database.get_dashboard_stats()
    trends = database.get_attendance_trends(days=7)
    return jsonify({
        "status": "success",
        "stats": stats,
        "trends": trends,
        "last_detection": camera_manager.last_detection_event,
        "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

@app.route("/api/students")
@security.login_required
def api_get_students():
    search = request.args.get("search", "").strip()
    students = database.get_all_students(search_query=search if search else None)
    return jsonify({"status": "success", "count": len(students), "students": students})

@app.route("/api/attendance")
@security.login_required
def api_get_attendance():
    method = request.args.get("method")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    search = request.args.get("search")
    history = database.get_attendance_history(
        method=method,
        start_date=start_date if start_date else None,
        end_date=end_date if end_date else None,
        search_query=search if search else None,
        limit=100
    )
    return jsonify({"status": "success", "data": history})

@app.route("/api/attendance/today")
@security.login_required
def api_get_today_attendance():
    report = database.get_daily_attendance()
    return jsonify({"status": "success", "data": report})

@app.route("/api/attendance/<string:date_str>")
@security.login_required
def api_get_date_attendance(date_str: str):
    if not security.validate_date(date_str):
        return jsonify({"status": "error", "message": "Invalid date format. Expected YYYY-MM-DD."}), 400
    report = database.get_daily_attendance(target_date=date_str)
    return jsonify({"status": "success", "data": report})

@app.route("/api/attendance/scan-qr", methods=["POST"])
@security.login_required
def api_scan_qr_payload():
    payload = request.get_json(silent=True) or request.form
    qr_data = payload.get("qr_data") or payload.get("data") or payload.get("payload")
    if not qr_data:
        return jsonify({"success": False, "status": "ERROR", "message": "No QR payload data provided."}), 400
        
    result = qr_engine.process_qr_attendance(str(qr_data))
    return jsonify(result)

@app.route("/api/attendance/mark-manual", methods=["POST"])
@security.login_required
def api_mark_attendance_manual():
    payload = request.get_json(silent=True) or request.form
    student_id = payload.get("student_id")
    method = payload.get("method", "manual")
    if not student_id:
        return jsonify({"success": False, "message": "student_id is required."}), 400
        
    try:
        sid = int(student_id)
    except ValueError:
        return jsonify({"success": False, "message": "Invalid student_id."}), 400
        
    success, msg, rec = database.mark_attendance(sid, method=method)
    return jsonify({"success": success, "message": msg, "record": rec})

@app.route("/api/capture/start/<int:student_id>", methods=["POST"])
@security.login_required
def api_start_capture(student_id: int):
    target = int(database.get_setting("samples_per_student", "30"))
    camera_manager.is_capturing = True
    camera_manager.capture_student_id = student_id
    camera_manager.target_samples = target
    return jsonify({"success": True, "message": f"Capture started for student #{student_id}"})

@app.route("/api/capture/status/<int:student_id>")
@security.login_required
def api_capture_status(student_id: int):
    count = face_engine.get_student_sample_count(student_id)
    target = int(database.get_setting("samples_per_student", "30"))
    return jsonify({
        "student_id": student_id,
        "sample_count": count,
        "target_samples": target,
        "is_capturing": camera_manager.is_capturing and camera_manager.capture_student_id == student_id,
        "completed": count >= target
    })

@app.route("/api/capture/reset/<int:student_id>", methods=["POST"])
@security.login_required
def api_reset_capture(student_id: int):
    student = database.get_student_by_id(student_id)
    if not student:
        return jsonify({"success": False, "message": "Student not found."}), 404
    face_engine.reset_student_dataset(student_id)
    return jsonify({"success": True, "message": f"Dataset reset for {student['name']}", "sample_count": 0})

@app.route("/api/camera/status")
@security.login_required
def api_camera_status():
    """Return real-time hardware camera and recognition engine status."""
    return jsonify({"status": "success", **camera_manager.get_status()})

@app.route("/api/camera/start", methods=["GET", "POST"])
@security.login_required
def api_start_camera():
    """Trigger camera start/wake."""
    cam_idx = int(database.get_setting("camera_index", "0"))
    cap = camera_manager.get_camera(cam_idx)
    return jsonify({
        "success": cap is not None and cap.isOpened(),
        "message": "Camera started." if cap is not None and cap.isOpened() else "Could not open camera."
    })

@app.route("/api/camera/stop", methods=["GET", "POST"])
@security.login_required
def api_stop_camera():
    """Explicitly release hardware camera and destroy all OpenCV windows."""
    camera_manager.stop_capture_session()
    return jsonify({"success": True, "message": "Camera stopped and released."})

@app.route("/api/face/scan-frame", methods=["POST"])
@security.login_required
def api_scan_face_frame():
    """
    Cloud-compatible face recognition endpoint.
    Processes browser webcam frames, detects face ROI, runs LBPH recognition, and logs attendance.
    """
    file_or_data = None
    if "frame" in request.files:
        file_or_data = request.files["frame"]
    elif "image" in request.files:
        file_or_data = request.files["image"]
    elif request.is_json:
        payload = request.get_json(silent=True) or {}
        file_or_data = payload.get("frame") or payload.get("image")
    elif request.form.get("frame") or request.form.get("image"):
        file_or_data = request.form.get("frame") or request.form.get("image")

    if not file_or_data:
        return jsonify({"success": False, "status": "ERROR", "message": "No frame image payload provided."}), 400

    is_valid, img, err = security.validate_uploaded_image(file_or_data)
    if not is_valid or img is None:
        return jsonify({"success": False, "status": "INVALID_IMAGE", "message": err or "Invalid image."}), 400

    # Check if model exists
    if not MODEL_PATH.exists():
        return jsonify({
            "success": False,
            "status": "MODEL_MISSING",
            "message": "Face model is not trained yet. Please train the model in Model Training."
        }), 200

    # Detect faces
    bboxes = face_engine.detect_faces(img)
    if not bboxes:
        return jsonify({
            "success": False,
            "status": "NO_FACE",
            "message": "No face detected in camera frame. Please face the camera directly."
        }), 200

    # Extract ROI from primary face bounding box
    face_roi = face_engine.extract_face_roi(img, bboxes[0])
    pred_id, conf, is_match = face_engine.recognize_face(face_roi)

    if is_match and pred_id is not None:
        result = face_engine.process_face_attendance_event(pred_id)
        return jsonify({
            "success": result["success"],
            "status": result["status"],
            "message": result["message"],
            "student": result.get("student"),
            "record": result.get("record"),
            "confidence": round(float(conf), 2)
        })
    else:
        return jsonify({
            "success": False,
            "status": "NOT_FOUND",
            "message": "Face not recognized or match confidence too low.",
            "confidence": round(float(conf), 2)
        }), 200

@app.route("/api/capture/frame", methods=["POST"])
@app.route("/api/capture/frame/<int:student_id>", methods=["POST"])
@security.login_required
def api_capture_frame(student_id: Optional[int] = None):
    """
    Cloud-compatible face dataset capture endpoint.
    Accepts browser webcam snapshot, extracts normalized 200x200 grayscale face ROI, and saves sample.
    """
    sid_val = student_id or request.form.get("student_id")
    if sid_val is None and request.is_json:
        payload = request.get_json(silent=True) or {}
        sid_val = payload.get("student_id")

    if not sid_val:
        return jsonify({"success": False, "message": "student_id is required."}), 400

    try:
        sid = int(sid_val)
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Invalid student_id. Expected integer."}), 400

    student = database.get_student_by_id(sid)
    if not student:
        return jsonify({"success": False, "message": f"Student ID #{sid} not found in database."}), 404

    file_or_data = None
    if "frame" in request.files:
        file_or_data = request.files["frame"]
    elif "image" in request.files:
        file_or_data = request.files["image"]
    elif request.is_json:
        payload = request.get_json(silent=True) or {}
        file_or_data = payload.get("frame") or payload.get("image")
    elif request.form.get("frame") or request.form.get("image"):
        file_or_data = request.form.get("frame") or request.form.get("image")

    if not file_or_data:
        return jsonify({"success": False, "message": "No frame image payload provided."}), 400

    is_valid, img, err = security.validate_uploaded_image(file_or_data)
    if not is_valid or img is None:
        return jsonify({"success": False, "message": err or "Invalid image."}), 400

    target = int(database.get_setting("samples_per_student", "30"))
    current_count = face_engine.get_student_sample_count(sid)

    bboxes = face_engine.detect_faces(img)
    if not bboxes:
        return jsonify({
            "success": False,
            "face_detected": False,
            "sample_count": current_count,
            "target_samples": target,
            "completed": current_count >= target,
            "message": "No face detected in camera frame. Please align student's face with the camera."
        }), 200

    face_roi = face_engine.extract_face_roi(img, bboxes[0])
    if current_count < target:
        _, new_count, _ = face_engine.save_face_sample(sid, face_roi)
    else:
        new_count = current_count

    return jsonify({
        "success": True,
        "face_detected": True,
        "sample_count": new_count,
        "target_samples": target,
        "completed": new_count >= target,
        "message": f"Sample {new_count}/{target} captured successfully."
    })

@app.route("/api/capture/upload/<int:student_id>", methods=["POST"])
@security.login_required
def api_upload_face_sample(student_id: int):
    student = database.get_student_by_id(student_id)
    if not student:
        return jsonify({"success": False, "message": f"Student ID #{student_id} not found."}), 404

    file_or_data = request.files.get("image") or request.files.get("frame")
    if not file_or_data:
        return jsonify({"success": False, "message": "No image file uploaded."}), 400
        
    is_valid, img, err = security.validate_uploaded_image(file_or_data)
    if not is_valid or img is None:
        return jsonify({"success": False, "message": err or "Invalid image format."}), 400
        
    bboxes = face_engine.detect_faces(img)
    if not bboxes:
        return jsonify({"success": False, "message": "No face detected in image."}), 400
        
    face_roi = face_engine.extract_face_roi(img, bboxes[0])
    _, count, path = face_engine.save_face_sample(student_id, face_roi)
    
    return jsonify({
        "success": True,
        "message": f"Face sample saved. Total: {count}",
        "sample_count": count
    })

@app.route("/api/attendance/scan-qr-frame", methods=["POST"])
@security.login_required
def api_scan_qr_frame():
    """
    Cloud-compatible QR scanner frame decoding endpoint.
    """
    file_or_data = None
    if "frame" in request.files:
        file_or_data = request.files["frame"]
    elif "image" in request.files:
        file_or_data = request.files["image"]
    elif request.is_json:
        payload = request.get_json(silent=True) or {}
        file_or_data = payload.get("frame") or payload.get("image")
    elif request.form.get("frame") or request.form.get("image"):
        file_or_data = request.form.get("frame") or request.form.get("image")

    if not file_or_data:
        return jsonify({"success": False, "status": "ERROR", "message": "No frame image payload provided."}), 400

    is_valid, img, err = security.validate_uploaded_image(file_or_data)
    if not is_valid or img is None:
        return jsonify({"success": False, "status": "INVALID_IMAGE", "message": err or "Invalid image."}), 400

    import cv2
    detector = cv2.QRCodeDetector()
    data, bbox, _ = detector.detectAndDecode(img)
    if data:
        result = qr_engine.process_qr_attendance(data)
        return jsonify(result)
    else:
        return jsonify({"success": False, "status": "NO_QR", "message": "No valid QR code detected in frame."})

@app.route("/api/train", methods=["POST"])
@security.login_required
def api_train_model():
    result = face_engine.train_lbph_model()
    return jsonify(result)

@app.route("/api/stream")
@security.login_required
def api_sse_events():
    def event_stream():
        last_stat_hash = None
        while True:
            try:
                stats = database.get_dashboard_stats()
                stat_str = json.dumps(stats)
                if stat_str != last_stat_hash:
                    last_stat_hash = stat_str
                    yield f"data: {stat_str}\n\n"
                time.sleep(2.0)
            except Exception:
                break
    return Response(stream_with_context(event_stream()), mimetype="text/event-stream")

# ==================================================
# GLOBAL ERROR HANDLERS
# ==================================================

@app.errorhandler(400)
def handle_bad_request(e):
    if request.is_json or request.path.startswith("/api/"):
        return jsonify({"status": "error", "error": 400, "message": str(e.description if hasattr(e, "description") else "Bad Request")}), 400
    return render_template("error.html", error_code=400, error_title="Bad Request", error_message=str(e.description if hasattr(e, "description") else "The request was invalid or incomplete.")), 400

@app.errorhandler(401)
def handle_unauthorized(e):
    if request.is_json or request.path.startswith("/api/"):
        return jsonify({"status": "error", "error": 401, "message": "Authentication required."}), 401
    return redirect(url_for("login_page", next=request.full_path))

@app.errorhandler(403)
def handle_forbidden(e):
    if request.is_json or request.path.startswith("/api/"):
        return jsonify({"status": "error", "error": 403, "message": "Forbidden."}), 403
    return render_template("error.html", error_code=403, error_title="Access Forbidden", error_message="You do not have permission to access this resource."), 403

@app.errorhandler(404)
def handle_not_found(e):
    if request.is_json or request.path.startswith("/api/"):
        return jsonify({"status": "error", "error": 404, "message": "Resource not found."}), 404
    return render_template("error.html", error_code=404, error_title="Page Not Found", error_message="The requested URL or resource was not found on this server."), 404

@app.errorhandler(405)
def handle_method_not_allowed(e):
    if request.is_json or request.path.startswith("/api/"):
        return jsonify({"status": "error", "error": 405, "message": "Method not allowed."}), 405
    return render_template("error.html", error_code=405, error_title="Method Not Allowed", error_message="The HTTP method used is not allowed for this endpoint."), 405

@app.errorhandler(500)
def handle_server_error(e):
    logger.error(f"Internal Server Error on {request.path}: {e}")
    if request.is_json or request.path.startswith("/api/"):
        return jsonify({"status": "error", "error": 500, "message": "An internal server error occurred."}), 500
    return render_template("error.html", error_code=500, error_title="Internal Server Error", error_message="An unexpected server error occurred. Our team has been notified."), 500

if __name__ == "__main__":
    print("=" * 60)
    print(" Starting SmartAttend — Production-Ready Attendance Management System")
    print(f" Server running at: http://{HOST}:{PORT}")
    print(f" Production Debug Mode: {'ON' if FLASK_DEBUG else 'OFF'}")
    print("=" * 60)
    app.run(host=HOST, port=PORT, debug=FLASK_DEBUG, threaded=True)
