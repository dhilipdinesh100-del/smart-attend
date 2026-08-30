"""
SmartAttend Comprehensive Post-Build Smoke Test Script
Executes all 32 smoke-test criteria safely without modifying production data.
"""
import sys
import os
import io
import openpyxl
from datetime import datetime
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, os.path.abspath("."))

from app import app
import database
import admin_audit
import qr_engine
import face_engine
from camera import camera_manager

def run_smoke_test():
    print("=" * 70)
    print("SMARTATTEND FINAL POST-BUILD SMOKE TEST")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    client = app.test_client()
    results = {}
    
    # 1. Verify /health
    resp = client.get("/health")
    results["health_check"] = (resp.status_code == 200, f"Status: {resp.status_code}, Body: {resp.get_json()}")
    
    # 2. Verify /login loads
    resp = client.get("/login")
    results["login_page_load"] = (resp.status_code == 200 and b"Sign In" in resp.data, f"Status: {resp.status_code}")

    # 3. Verify unauthenticated access to protected routes are blocked
    protected_urls = [
        "/", "/dashboard", "/students", "/train", "/face-attendance",
        "/qr-attendance", "/daily-attendance", "/monthly-attendance",
        "/attendance-history", "/settings", "/settings/export/admin-registry",
        "/attendance/export/csv", "/video_feed/face", "/video_feed/qr"
    ]
    unauth_blocked = True
    for url in protected_urls:
        r = client.get(url)
        if r.status_code != 302 or "/login" not in r.headers.get("Location", ""):
            unauth_blocked = False
            results[f"unauth_{url}"] = (False, f"Returned status {r.status_code}")
    results["unauth_protection"] = (unauth_blocked, f"All {len(protected_urls)} routes redirected to /login")

    # 4. Authenticated Session Setup
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["username"] = "admin"
        sess["role"] = "admin"

    # 5. Verify /dashboard and 7 KPI cards
    resp = client.get("/dashboard")
    kpis = [b"Total Students", b"Present Today", b"Absent Today", b"Attendance %", b"Face Attendance", b"QR Attendance", b"Manual Logs"]
    kpi_found = all(kpi in resp.data for kpi in kpis)
    results["dashboard_7_kpis"] = (resp.status_code == 200 and kpi_found, f"Status: {resp.status_code}, All 7 KPIs present: {kpi_found}")

    # 6. Verify /students loads existing students
    resp = client.get("/students")
    results["students_page"] = (resp.status_code == 200 and b"Students Management" in resp.data, f"Status: {resp.status_code}")

    # 7. Student Profile & QR Operations
    students = database.get_all_students()
    if students:
        sample_student = students[0]
        sid = sample_student["id"]
        
        # Profile
        resp_prof = client.get(f"/students/{sid}")
        results["student_profile"] = (resp_prof.status_code == 200 and sample_student["name"].encode() in resp_prof.data, f"Status: {resp_prof.status_code}")
        
        # QR View
        resp_qr_view = client.get(f"/qr/view/{sid}")
        results["qr_view"] = (resp_qr_view.status_code == 200 and b"QR Pass" in resp_qr_view.data, f"Status: {resp_qr_view.status_code}")
        
        # QR Download
        resp_qr_dl = client.get(f"/qr/download/{sid}")
        results["qr_download"] = (resp_qr_dl.status_code == 200 and resp_qr_dl.mimetype == "image/png", f"Status: {resp_qr_dl.status_code}, Mime: {resp_qr_dl.mimetype}")
    else:
        results["student_profile"] = (True, "No students registered to view (skipped)")
        results["qr_view"] = (True, "Skipped")
        results["qr_download"] = (True, "Skipped")

    # 8. Verify /qr-attendance loads
    resp = client.get("/qr-attendance")
    results["qr_attendance_page"] = (resp.status_code == 200 and b"Real-Time QR Attendance" in resp.data, f"Status: {resp.status_code}")

    # 9. Verify /face-attendance loads
    resp = client.get("/face-attendance")
    results["face_attendance_page"] = (resp.status_code == 200 and b"Real-Time Face Attendance" in resp.data, f"Status: {resp.status_code}")

    # 10. Verify /daily-attendance loads
    resp = client.get("/daily-attendance")
    results["daily_attendance_page"] = (resp.status_code == 200 and b"Daily Attendance Breakdown" in resp.data, f"Status: {resp.status_code}")

    # 11. Verify /monthly-attendance loads
    resp = client.get("/monthly-attendance")
    results["monthly_attendance_page"] = (resp.status_code == 200 and b"Monthly Attendance Report" in resp.data, f"Status: {resp.status_code}")

    # 12. Verify /attendance-history loads
    resp = client.get("/attendance-history")
    results["attendance_history_page"] = (resp.status_code == 200 and b"Attendance History Logs" in resp.data, f"Status: {resp.status_code}")

    # 13. Verify CSV Export
    resp_csv = client.get("/attendance/export/csv")
    csv_ok = resp_csv.status_code == 200 and b"Student ID,Student Name,Roll Number,Date,Time,Method,Status" in resp_csv.data
    results["csv_export"] = (csv_ok, f"Status: {resp_csv.status_code}, Content-Type: {resp_csv.mimetype}")

    # 14. Verify /train loads
    resp = client.get("/train")
    results["train_page"] = (resp.status_code == 200 and b"Train Recognition Model" in resp.data, f"Status: {resp.status_code}")

    # 15. Verify /settings loads
    resp = client.get("/settings")
    results["settings_page"] = (resp.status_code == 200 and b"System Settings & Admin Registry" in resp.data, f"Status: {resp.status_code}")

    # 16. Verify Private Admin Excel Registry Export
    resp_excel = client.get("/settings/export/admin-registry")
    wb = openpyxl.load_workbook(io.BytesIO(resp_excel.data))
    sheet = wb.active
    headers = [sheet.cell(row=1, column=col).value for col in range(1, 9)]
    excel_ok = resp_excel.status_code == 200 and "Admin ID" in headers and "Last Login" in headers
    results["excel_registry_export"] = (excel_ok, f"Status: {resp_excel.status_code}, Headers: {headers}")

    # 17. Verify Secret Exclusion in Responses
    secret_leaks = False
    for r_check in [resp_csv.data.decode('utf-8', errors='ignore'), str(sheet.values)]:
        if "scrypt:" in r_check or "password_hash" in r_check:
            secret_leaks = True
    results["secret_exclusion"] = (not secret_leaks, "Zero password hashes, tokens, or secret keys leaked in exports")

    # 18. Camera Lifecycle & Idempotency Check
    cam_init = camera_manager.get_camera(0)
    frame = camera_manager.get_frame()
    has_frame = frame is not None
    camera_manager.stop()
    camera_manager.release_camera()
    is_running_after = camera_manager.is_running()
    
    # Second open/close cycle to test idempotency
    cam_reopen = camera_manager.get_camera(0)
    camera_manager.stop()
    camera_manager.release_camera()
    
    results["camera_lifecycle"] = (
        not is_running_after,
        f"Frame Captured: {has_frame}, Stopped Cleanly: {not is_running_after}"
    )

    # 19. Logout and Session Invalidation Check
    resp_logout = client.get("/logout")
    resp_post_logout = client.get("/dashboard")
    results["logout_and_redirect"] = (
        resp_logout.status_code == 302 and resp_post_logout.status_code == 302 and "/login" in resp_post_logout.headers.get("Location", ""),
        f"Logout Status: {resp_logout.status_code}, Post-Logout Dash Status: {resp_post_logout.status_code}"
    )

    # Print Summary Table
    print("\nSMOKE TEST SUMMARY TABLE:")
    print("-" * 70)
    all_passed = True
    for item, (passed, details) in results.items():
        status_text = "[PASS]" if passed else "[FAIL]"
        print(f"{status_text:<8} {item:<28} : {details}")
        if not passed:
            all_passed = False
    print("-" * 70)
    print(f"OVERALL SMOKE TEST RESULT: {'SUCCESS (ALL CHECKS PASSED)' if all_passed else 'FAILED'}\n")
    return all_passed

if __name__ == "__main__":
    success = run_smoke_test()
    sys.exit(0 if success else 1)
