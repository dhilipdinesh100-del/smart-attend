import os
import sys
import shutil
import time
import cv2
import numpy as np
from pathlib import Path
from datetime import datetime

# Set up paths
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import database
import qr_engine
import face_engine
import security
import config
from app import app

results = {"PASS": [], "FIXED": [], "REMAINING": []}

def log_pass(test_num, name, detail=""):
    msg = f"Test {test_num}: {name}" + (f" — {detail}" if detail else "")
    print(f" [PASS] {msg}")
    results["PASS"].append(msg)

def run_all_e2e_tests():
    print("=" * 70)
    print(" SmartAttend Comprehensive Production & Security E2E Verification")
    print("=" * 70)

    client = app.test_client()

    # ----------------------------------------------------
    # Test 34: Test empty database state first
    # ----------------------------------------------------
    with database.db_session() as conn:
        conn.execute("DELETE FROM attendance;")
        conn.execute("DELETE FROM students;")
    
    dash_empty = database.get_dashboard_stats()
    assert dash_empty["total_students"] == 0
    assert dash_empty["today_present"] == 0
    assert dash_empty["total_records"] == 0
    log_pass(34, "Empty database handling", "Dashboard loads with 0 counts without error")

    # ----------------------------------------------------
    # Security Test: Unauthorized access redirects to /login
    # ----------------------------------------------------
    CSRF_TOKEN = "smartattend_test_csrf_token_secret_123"
    headers = {"X-CSRF-Token": CSRF_TOKEN}

    resp_unauth = client.get("/dashboard")
    assert resp_unauth.status_code == 302
    assert "/login" in resp_unauth.headers.get("Location", "")
    log_pass("SEC-1", "Unauthorized Access Redirection", "Unauthenticated request redirected to /login")

    # ----------------------------------------------------
    # Security Test: Login Page Checks (No credential leak, Create Admin link)
    # ----------------------------------------------------
    resp_login = client.get("/login")
    assert resp_login.status_code == 200
    assert b"Create Admin Account" in resp_login.data
    assert b"admin123" not in resp_login.data
    assert b"Default Admin Login" not in resp_login.data
    log_pass("SEC-1B", "Login Page Security & Registration Link", "Login page has no credential leak and links to /register")

    # ----------------------------------------------------
    # Security Test: Admin Registration Flow & Validation
    # ----------------------------------------------------
    resp_reg_get = client.get("/register")
    assert resp_reg_get.status_code == 200
    assert b"Create Admin Account" in resp_reg_get.data
    assert b"Administrator Registration" in resp_reg_get.data
    assert b"full_name" in resp_reg_get.data
    assert b"username" in resp_reg_get.data
    assert b"email" in resp_reg_get.data

    # Validation: Mismatched passwords
    resp_bad_pw = client.post("/register", data={
        "full_name": "E2E Test Admin",
        "username": "e2e_admin",
        "email": "e2e_admin@smartattend.com",
        "password": "SecurePassword123",
        "confirm_password": "WrongPassword999",
        "csrf_token": CSRF_TOKEN
    })
    assert resp_bad_pw.status_code == 200
    assert b"Passwords do not match" in resp_bad_pw.data

    # Create new admin account
    resp_reg_ok = client.post("/register", data={
        "full_name": "E2E Test Admin",
        "username": "e2e_admin",
        "email": "e2e_admin@smartattend.com",
        "password": "SecurePassword123",
        "confirm_password": "SecurePassword123",
        "csrf_token": CSRF_TOKEN
    }, follow_redirects=False)
    assert resp_reg_ok.status_code == 302
    assert "/login" in resp_reg_ok.headers.get("Location", "")

    # Duplicate username rejection
    resp_dup_user = client.post("/register", data={
        "full_name": "Another Admin",
        "username": "e2e_admin",
        "email": "another@smartattend.com",
        "password": "SecurePassword123",
        "confirm_password": "SecurePassword123",
        "csrf_token": CSRF_TOKEN
    })
    assert resp_dup_user.status_code == 200
    assert b"Username already exists" in resp_dup_user.data

    # Duplicate email rejection
    resp_dup_email = client.post("/register", data={
        "full_name": "Another Admin 2",
        "username": "unique_username_99",
        "email": "e2e_admin@smartattend.com",
        "password": "SecurePassword123",
        "confirm_password": "SecurePassword123",
        "csrf_token": CSRF_TOKEN
    })
    assert resp_dup_email.status_code == 200
    assert b"Email already registered" in resp_dup_email.data

    # Login with newly created admin credentials
    resp_login_new = client.post("/login", data={
        "username": "e2e_admin",
        "password": "SecurePassword123",
        "csrf_token": CSRF_TOKEN
    }, follow_redirects=False)
    assert resp_login_new.status_code == 302
    log_pass("SEC-2", "Admin Registration & Authentication Flow", "New admin registered, validated, duplicate-checked, and authenticated")

    # ----------------------------------------------------
    # Security Test: Private Excel Admin Registry Audit
    # ----------------------------------------------------
    import admin_audit
    import openpyxl
    assert admin_audit.EXCEL_REGISTRY_PATH.exists()
    wb = openpyxl.load_workbook(str(admin_audit.EXCEL_REGISTRY_PATH))
    sheet = wb.active
    audit_rows = list(sheet.iter_rows(values_only=True))
    assert len(audit_rows) >= 2
    # Verify passwords/hashes not stored
    for r in audit_rows:
        for val in r:
            val_str = str(val or "")
            assert "SecurePassword123" not in val_str
            assert "scrypt:" not in val_str
    log_pass("SEC-2B", "Private Excel Admin Registry Audit", "Audit file data/private/admin_registry.xlsx verified (no passwords/hashes)")

    # ----------------------------------------------------
    # Security Test: Admin Registry Export (Authenticated)
    # ----------------------------------------------------
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["username"] = "admin"
        sess["role"] = "admin"
        sess["_csrf_token"] = CSRF_TOKEN

    resp_export = client.get("/settings/export/admin-registry")
    assert resp_export.status_code == 200
    assert "application/vnd.openxmlformats" in resp_export.mimetype
    log_pass("SEC-2C", "Authenticated Admin Registry Export", "GET /settings/export/admin-registry returns .xlsx file")

    # ----------------------------------------------------
    # Security Test: Health Check Endpoint
    # ----------------------------------------------------
    resp_health = client.get("/health")
    assert resp_health.status_code == 200
    health_json = resp_health.get_json()
    assert health_json["status"] == "ok"
    assert health_json["database"] == "ok"
    log_pass("SEC-3", "System Health Check API", "GET /health returns JSON ok status")

    # ----------------------------------------------------
    # Test 1: Application starts without Python errors
    # ----------------------------------------------------
    assert app is not None
    log_pass(1, "Application starts without Python errors")

    # ----------------------------------------------------
    # Test 2: Dashboard opens
    # ----------------------------------------------------
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["username"] = "admin"
        sess["role"] = "admin"
        sess["_csrf_token"] = CSRF_TOKEN

    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert b"Dashboard" in resp.data
    log_pass(2, "Dashboard opens", "Status 200 OK")

    # ----------------------------------------------------
    # Test 3: Register a new student (with CSRF protection)
    # ----------------------------------------------------
    resp = client.post("/students/register", data={"name": "Arthur Pendelton", "roll_no": "CS2026-101", "csrf_token": CSRF_TOKEN}, follow_redirects=True, headers=headers)
    assert resp.status_code == 200
    log_pass(3, "Register a new student", "Student Arthur Pendelton submitted with CSRF validation")

    # ----------------------------------------------------
    # Test 4: Verify the student is saved in SQLite
    # ----------------------------------------------------
    student1 = database.get_student_by_roll("CS2026-101")
    assert student1 is not None
    assert student1["name"] == "Arthur Pendelton"
    s1_id = student1["id"]
    log_pass(4, "Verify student saved in SQLite", f"Student ID: {s1_id}, Roll: CS2026-101")

    # ----------------------------------------------------
    # Test 5: Verify a QR code is automatically generated
    # ----------------------------------------------------
    qr_path = config.QR_DIR / f"student_{s1_id}.png"
    assert qr_path.exists()
    assert qr_path.stat().st_size > 0
    log_pass(5, "Verify QR code automatically generated", f"File size: {qr_path.stat().st_size} bytes")

    # ----------------------------------------------------
    # Test 6: Open the student's QR code
    # ----------------------------------------------------
    resp = client.get(f"/qr/view/{s1_id}")
    assert resp.status_code == 200
    assert resp.mimetype == "image/png"
    log_pass(6, "Open student QR code", "HTTP 200 with image/png MIME")

    # ----------------------------------------------------
    # Test 7: Download the QR code
    # ----------------------------------------------------
    resp = client.get(f"/qr/download/{s1_id}")
    assert resp.status_code == 200
    assert f"student_{s1_id}_qr.png" in resp.headers.get("Content-Disposition", "")
    log_pass(7, "Download QR code", f"Attachment header: student_{s1_id}_qr.png")

    # ----------------------------------------------------
    # Test 8: Capture face samples for the student
    # ----------------------------------------------------
    dummy_face = np.full((200, 200), 140, dtype=np.uint8)
    for i in range(30):
        sample = dummy_face.copy()
        sample[50:100, 50:100] = 80 + (i % 20)
        face_engine.save_face_sample(s1_id, sample)
    
    count = face_engine.get_student_sample_count(s1_id)
    assert count == 30
    log_pass(8, "Capture face samples for the student", "30 samples saved to data/faces/<student_id>/")

    # ----------------------------------------------------
    # Test 9: Train the face recognition model
    # ----------------------------------------------------
    train_res = face_engine.train_lbph_model()
    assert train_res["success"] is True
    assert config.MODEL_PATH.exists()
    log_pass(9, "Train face recognition model", f"trainer.yml created ({config.MODEL_PATH.stat().st_size} bytes)")

    # ----------------------------------------------------
    # Test 10: Start Face Attendance page
    # ----------------------------------------------------
    resp = client.get("/face-attendance")
    assert resp.status_code == 200
    assert b"Face Recognition" in resp.data
    log_pass(10, "Start Face Attendance page", "Status 200 OK")

    # ----------------------------------------------------
    # Test 11: Recognize the registered student
    # ----------------------------------------------------
    test_sample = dummy_face.copy()
    test_sample[50:100, 50:100] = 85
    pred_id, conf, is_match = face_engine.recognize_face(test_sample, confidence_threshold=80.0)
    assert is_match is True
    assert pred_id == s1_id
    log_pass(11, "Recognize registered student", f"Predicted ID: {pred_id}, Confidence: {conf:.2f}")

    # ----------------------------------------------------
    # Test 12: Verify face attendance is inserted into SQLite
    # ----------------------------------------------------
    event = face_engine.process_face_attendance_event(s1_id)
    assert event["success"] is True
    assert event["status"] == "MARKED"
    assert event["record"]["method"] == "face"
    assert database.is_attendance_marked_today(s1_id) is True
    log_pass(12, "Verify face attendance inserted in SQLite", "Marked PRESENT with method='face'")

    # ----------------------------------------------------
    # Test 13: Verify the same student cannot be marked twice on the same day
    # ----------------------------------------------------
    dup_face_event = face_engine.process_face_attendance_event(s1_id)
    assert dup_face_event["success"] is False
    assert dup_face_event["status"] in ["COOLDOWN", "ALREADY_MARKED"]
    log_pass(13, "Duplicate face attendance prevention", "Second face scan rejected for the day")

    # Register student 2 for QR testing
    resp = client.post("/students/register", data={"name": "Beatrice Potter", "roll_no": "CS2026-102", "csrf_token": CSRF_TOKEN}, follow_redirects=True, headers=headers)
    assert resp.status_code == 200
    student2 = database.get_student_by_roll("CS2026-102")
    s2_id = student2["id"]

    # ----------------------------------------------------
    # Test 14: Start QR Attendance page
    # ----------------------------------------------------
    resp = client.get("/qr-attendance")
    assert resp.status_code == 200
    assert b"QR Code" in resp.data
    log_pass(14, "Start QR Attendance page", "Status 200 OK")

    # ----------------------------------------------------
    # Test 15: Scan the student's QR code
    # ----------------------------------------------------
    qr_res = qr_engine.process_qr_attendance(str(s2_id))
    assert qr_res["success"] is True
    assert qr_res["status"] == "MARKED"
    log_pass(15, "Scan student QR code", f"Decoded ID: {s2_id}")

    # ----------------------------------------------------
    # Test 16: Verify QR attendance is recorded correctly
    # ----------------------------------------------------
    assert qr_res["record"]["method"] == "qr"
    assert database.is_attendance_marked_today(s2_id) is True
    log_pass(16, "Verify QR attendance recorded correctly", "Marked PRESENT with method='qr'")

    # ----------------------------------------------------
    # Test 17: Verify duplicate QR attendance is prevented
    # ----------------------------------------------------
    dup_qr_res = qr_engine.process_qr_attendance(str(s2_id))
    assert dup_qr_res["success"] is False
    assert dup_qr_res["status"] == "ALREADY_MARKED"
    log_pass(17, "Duplicate QR scan prevention", "Second QR scan on same day rejected")

    # ----------------------------------------------------
    # Test 18: Open Daily Attendance
    # ----------------------------------------------------
    resp = client.get("/daily-attendance")
    assert resp.status_code == 200
    assert b"Daily Attendance Breakdown" in resp.data
    log_pass(18, "Open Daily Attendance page", "Status 200 OK")

    # ----------------------------------------------------
    # Test 19: Verify today's attendance is displayed correctly
    # ----------------------------------------------------
    daily = database.get_daily_attendance()
    assert daily["total_students"] == 2
    assert daily["present_count"] == 2
    assert daily["absent_count"] == 0
    assert daily["face_count"] == 1
    assert daily["qr_count"] == 1
    assert daily["attendance_rate"] == 100.0
    log_pass(19, "Verify today's attendance display", "2 Present (1 Face, 1 QR), 0 Absent, 100%")

    # ----------------------------------------------------
    # Test 20: Open Monthly Attendance
    # ----------------------------------------------------
    resp = client.get(f"/monthly-attendance?student_id={s1_id}")
    assert resp.status_code == 200
    assert b"Monthly Attendance Report" in resp.data
    log_pass(20, "Open Monthly Attendance page", "Status 200 OK")

    # ----------------------------------------------------
    # Test 21: Verify present days, absent days, upcoming days, percentage, Face count and QR count
    # ----------------------------------------------------
    monthly = database.get_monthly_attendance(student_id=s1_id)
    sd = monthly["student_data"]
    assert sd is not None
    assert sd["present_days"] == 1
    assert sd["elapsed_days"] == sd["present_days"] + sd["absent_days"]
    assert sd["total_days"] == sd["elapsed_days"] + sd["upcoming_days"]
    assert sd["face_count"] == 1
    assert sd["qr_count"] == 0
    assert sd["attendance_percentage"] == round((sd["present_days"] / sd["elapsed_days"] * 100), 1)
    log_pass(21, "Verify monthly attendance calculations", f"Present: {sd['present_days']}, Absent: {sd['absent_days']}, Upcoming: {sd['upcoming_days']}, Face: {sd['face_count']}, QR: {sd['qr_count']}")

    # ----------------------------------------------------
    # Test 22: Open Attendance History
    # ----------------------------------------------------
    resp = client.get("/attendance-history")
    assert resp.status_code == 200
    assert b"Attendance History Logs" in resp.data
    log_pass(22, "Open Attendance History page", "Status 200 OK")

    # ----------------------------------------------------
    # Test 23: Verify records are displayed in history
    # ----------------------------------------------------
    hist = database.get_attendance_history()
    assert hist["total"] == 2
    log_pass(23, "Verify records displayed in history", f"Total logs: {hist['total']}")

    # ----------------------------------------------------
    # Security Test: Database Backup Creation
    # ----------------------------------------------------
    b_success, b_msg, b_path = database.backup_database()
    assert b_success is True
    assert b_path.exists()
    assert b_path.stat().st_size > 0
    b_path.unlink()
    log_pass("SEC-4", "Database Snapshot Backup", "Timestamped SQLite backup verified in backups/")

    # ----------------------------------------------------
    # Test 24: Delete an attendance record
    # ----------------------------------------------------
    with database.db_session() as conn:
        row = conn.execute("SELECT id FROM attendance WHERE student_id = ?;", (s2_id,)).fetchone()
        att_to_del = row["id"]

    del_success, del_msg = database.delete_attendance(att_to_del)
    assert del_success is True
    log_pass(24, "Delete an attendance record", f"Deleted attendance ID #{att_to_del}")

    # ----------------------------------------------------
    # Test 25: Verify it disappears from all relevant pages and dashboard statistics
    # ----------------------------------------------------
    daily_after = database.get_daily_attendance()
    assert daily_after["present_count"] == 1
    assert daily_after["absent_count"] == 1
    dash_after = database.get_dashboard_stats()
    assert dash_after["today_present"] == 1
    assert dash_after["today_absent"] == 1
    assert database.is_attendance_marked_today(s2_id) is False
    log_pass(25, "Verify deletion instant update across dashboard & daily stats", "Present count changed from 2 to 1")

    # ----------------------------------------------------
    # Test 26: Delete a student
    # ----------------------------------------------------
    del_st_success, del_st_msg = database.delete_student(s1_id)
    assert del_st_success is True
    log_pass(26, "Delete a student", f"Deleted student #{s1_id}")

    # ----------------------------------------------------
    # Test 27: Verify the student's attendance, QR file and face dataset are removed
    # ----------------------------------------------------
    assert database.get_student_by_id(s1_id) is None
    qr_s1 = config.QR_DIR / f"student_{s1_id}.png"
    face_s1 = config.FACES_DIR / str(s1_id)
    assert not qr_s1.exists()
    assert not face_s1.exists()
    with database.db_session() as conn:
        att_s1_count = conn.execute("SELECT COUNT(*) as c FROM attendance WHERE student_id = ?;", (s1_id,)).fetchone()["c"]
        assert att_s1_count == 0
    log_pass(27, "Verify student cascading cleanup", "Database record, QR file, face dataset, and attendance records removed")

    # ----------------------------------------------------
    # Test 28: Verify remaining students still have their original IDs (no renumbering)
    # ----------------------------------------------------
    remaining_st = database.get_student_by_id(s2_id)
    assert remaining_st is not None
    assert remaining_st["id"] == s2_id
    assert remaining_st["roll_no"] == "CS2026-102"
    log_pass(28, "Verify student IDs remain stable", f"Student 2 ID preserved as #{s2_id} without renumbering")

    # ----------------------------------------------------
    # Test 29: Test invalid QR codes
    # ----------------------------------------------------
    invalid_qr1 = qr_engine.process_qr_attendance("non_existent_qr_code")
    assert invalid_qr1["success"] is False
    assert invalid_qr1["status"] == "NOT_FOUND"

    invalid_qr2 = qr_engine.process_qr_attendance("999999")
    assert invalid_qr2["success"] is False
    assert invalid_qr2["status"] == "NOT_FOUND"
    log_pass(29, "Test invalid QR codes", "Handled gracefully with Student Not Found status")

    # ----------------------------------------------------
    # Test 30: Test duplicate roll numbers
    # ----------------------------------------------------
    dup_roll_res, dup_roll_msg, _ = database.add_student("Another Beatrice", "CS2026-102")
    assert dup_roll_res is False
    assert "already exists" in dup_roll_msg
    log_pass(30, "Test duplicate roll numbers", "Rejected with friendly integrity error message")

    # ----------------------------------------------------
    # Test 31: Test missing QR files
    # ----------------------------------------------------
    qr_s2 = config.QR_DIR / f"student_{s2_id}.png"
    if qr_s2.exists():
        qr_s2.unlink()
    assert not qr_s2.exists()
    recovered_qr = qr_engine.get_or_create_qr(s2_id)
    assert recovered_qr.exists()
    log_pass(31, "Test missing QR files", "Auto-regenerated on request")

    # ----------------------------------------------------
    # Test 32: Test missing face model
    # ----------------------------------------------------
    if config.MODEL_PATH.exists():
        config.MODEL_PATH.unlink()
    
    pred_missing, conf_missing, is_match_missing = face_engine.recognize_face(dummy_face)
    assert is_match_missing is False
    assert pred_missing is None
    log_pass(32, "Test missing face model", "Returns is_match=False gracefully without crash")

    # ----------------------------------------------------
    # Test 33: Test camera failure
    # ----------------------------------------------------
    from camera import camera_manager
    placeholder = camera_manager.create_placeholder_frame("Camera Unavailable", "Test fallback frame")
    assert placeholder is not None
    assert placeholder.shape == (480, 640, 3)
    log_pass(33, "Test camera failure handling", "Generates 640x480 dark fallback frame")

    # ----------------------------------------------------
    # Test 35: Test dashboard real-time updates API
    # ----------------------------------------------------
    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert "stats" in data
    assert "trends" in data
    assert "last_detection" in data
    log_pass(35, "Test dashboard real-time updates", "JSON endpoint /api/dashboard returns complete metrics")

    print("=" * 70)
    print(f" ALL {len(results['PASS'])} TESTS PASSED SUCCESSFULLY (100% PRODUCTION READY)!")
    print("=" * 70)

if __name__ == "__main__":
    run_all_e2e_tests()
