import unittest
import os
import shutil
import cv2
import numpy as np
from pathlib import Path
from datetime import datetime

import database
import qr_engine
import face_engine
import security
import config
from app import app

class SmartAttendComprehensiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()
        with database.db_session() as conn:
            conn.execute("DELETE FROM attendance;")
            conn.execute("DELETE FROM students WHERE roll_no LIKE 'TEST-%';")
        cls.client = app.test_client()

    def test_01_database_tables_and_admin(self):
        with database.db_session() as conn:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
            self.assertIn("users", tables)
            self.assertIn("students", tables)
            self.assertIn("attendance", tables)
            self.assertIn("settings", tables)

        admin = database.get_user_by_username("admin")
        self.assertIsNotNone(admin)
        self.assertTrue(security.verify_password(admin["password_hash"], "admin123"))

    def test_02_authentication_and_unauthorized_redirect(self):
        # Unauthenticated request to /dashboard must redirect to /login
        unauth_resp = self.client.get("/dashboard")
        self.assertEqual(unauth_resp.status_code, 302)
        self.assertIn("/login", unauth_resp.headers["Location"])

        # Health endpoint should be public
        health_resp = self.client.get("/health")
        self.assertEqual(health_resp.status_code, 200)
        self.assertEqual(health_resp.get_json()["status"], "ok")

        # Invalid login attempt
        bad_login = self.client.post("/login", data={"username": "admin", "password": "wrongpassword"})
        self.assertEqual(bad_login.status_code, 200)

        # Successful login
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "admin"
            sess["role"] = "admin"

        auth_resp = self.client.get("/dashboard")
        self.assertEqual(auth_resp.status_code, 200)

    def test_02b_admin_registration(self):
        # Clear authenticated session so /register can be accessed as guest
        self.client.get("/logout")

        # 1. Open admin registration page
        resp = self.client.get("/register")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Create Admin Account", resp.data)

        # 2. Validation: Empty fields
        resp = self.client.post("/register", data={
            "full_name": "",
            "username": "",
            "email": "",
            "password": "",
            "confirm_password": ""
        })
        self.assertEqual(resp.status_code, 200)

        # 3. Validation: Password mismatch
        resp = self.client.post("/register", data={
            "full_name": "Test Admin",
            "username": "testadmin",
            "email": "testadmin@school.edu",
            "password": "password123",
            "confirm_password": "differentpassword"
        })
        self.assertEqual(resp.status_code, 200)

        # 4. Successful Admin Registration
        resp = self.client.post("/register", data={
            "full_name": "Test Admin",
            "username": "testadmin",
            "email": "testadmin@school.edu",
            "password": "SecurePassword123",
            "confirm_password": "SecurePassword123"
        }, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers["Location"])

        # 5. Duplicate username rejection
        resp = self.client.post("/register", data={
            "full_name": "Test Admin 2",
            "username": "testadmin",
            "email": "another@school.edu",
            "password": "SecurePassword123",
            "confirm_password": "SecurePassword123"
        })
        self.assertEqual(resp.status_code, 200)

        # 6. Duplicate email rejection
        resp = self.client.post("/register", data={
            "full_name": "Test Admin 3",
            "username": "differentuser",
            "email": "testadmin@school.edu",
            "password": "SecurePassword123",
            "confirm_password": "SecurePassword123"
        })
        self.assertEqual(resp.status_code, 200)

        # 7. Authenticate with newly registered admin
        user = database.verify_user_credentials("testadmin", "SecurePassword123")
        self.assertIsNotNone(user)
        self.assertEqual(user["username"], "testadmin")

    def test_02c_admin_audit_excel(self):
        import admin_audit
        import openpyxl

        # 1. Verify Excel file exists in data/private/
        self.assertTrue(admin_audit.EXCEL_REGISTRY_PATH.exists())

        # 2. Inspect Excel content
        wb = openpyxl.load_workbook(str(admin_audit.EXCEL_REGISTRY_PATH))
        sheet = wb.active

        # Check headers
        headers = [cell.value for cell in sheet[1]]
        self.assertIn("Admin ID", headers)
        self.assertIn("Full Name", headers)
        self.assertIn("Username", headers)
        self.assertIn("Email", headers)
        self.assertIn("Registration Date", headers)
        self.assertIn("Last Login", headers)
        self.assertIn("Account Status", headers)

        # 3. Verify passwords or hashes are NOT stored in Excel
        for row in sheet.iter_rows(values_only=True):
            for cell_val in row:
                val_str = str(cell_val or '')
                self.assertNotIn("admin123", val_str)
                self.assertNotIn("SecurePassword123", val_str)
                self.assertNotIn("scrypt:", val_str)
                self.assertNotIn("pbkdf2:", val_str)

        # 4. Verify login update in Excel
        admin_audit.record_admin_login("testadmin")
        records = admin_audit.get_all_audit_records()
        matching = [r for r in records if r["username"] == "testadmin"]
        self.assertEqual(len(matching), 1)
        self.assertNotEqual(matching[0]["last_login"], "Never")

        # 5. Authenticated export of admin registry Excel
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "admin"
            sess["role"] = "admin"

        export_resp = self.client.get("/settings/export/admin-registry")
        self.assertEqual(export_resp.status_code, 200)
        self.assertEqual(
            export_resp.mimetype,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    def test_03_student_registration_and_qr_generation(self):
        success, msg, student_id = database.add_student("John Doe", "TEST-ROLL-001")
        self.assertTrue(success, f"Failed to add student: {msg}")
        self.assertIsNotNone(student_id)
        
        dup_success, dup_msg, _ = database.add_student("Another John", "TEST-ROLL-001")
        self.assertFalse(dup_success, "Duplicate roll number should have been rejected.")

        qr_path = qr_engine.generate_qr_code(student_id)
        self.assertTrue(qr_path.exists(), f"QR file not created at {qr_path}")

        qr_path.unlink()
        self.assertFalse(qr_path.exists())
        regen_path = qr_engine.get_or_create_qr(student_id)
        self.assertTrue(regen_path.exists(), "QR was not auto-regenerated.")

    def test_04_qr_attendance_and_duplicate_prevention(self):
        student = database.get_student_by_roll("TEST-ROLL-001")
        self.assertIsNotNone(student)
        student_id = student["id"]

        res1 = qr_engine.process_qr_attendance(str(student_id))
        self.assertTrue(res1["success"], f"First QR attendance should succeed: {res1}")
        self.assertEqual(res1["status"], "MARKED")

        res2 = qr_engine.process_qr_attendance(str(student_id))
        self.assertFalse(res2["success"], "Second QR scan on same day must not create duplicate.")
        self.assertEqual(res2["status"], "ALREADY_MARKED")

        res_invalid = qr_engine.process_qr_attendance("9999999")
        self.assertFalse(res_invalid["success"])
        self.assertEqual(res_invalid["status"], "NOT_FOUND")

    def test_05_face_dataset_and_training(self):
        success, _, s2_id = database.add_student("Jane Smith", "TEST-ROLL-002")
        self.assertTrue(success)

        dummy_face = np.ones((200, 200), dtype=np.uint8) * 128
        for i in range(5):
            face_engine.save_face_sample(s2_id, dummy_face)

        count = face_engine.get_student_sample_count(s2_id)
        self.assertEqual(count, 5)

        train_res = face_engine.train_lbph_model()
        self.assertTrue(train_res["success"], f"Training failed: {train_res}")
        self.assertTrue(config.MODEL_PATH.exists(), "Model file trainer.yml should exist.")

    def test_06_face_attendance_and_duplicate_prevention(self):
        student = database.get_student_by_roll("TEST-ROLL-002")
        s2_id = student["id"]

        event1 = face_engine.process_face_attendance_event(s2_id)
        self.assertTrue(event1["success"], f"Face attendance should succeed: {event1}")
        self.assertEqual(event1["status"], "MARKED")

        event2 = face_engine.process_face_attendance_event(s2_id)
        self.assertFalse(event2["success"])
        self.assertIn(event2["status"], ["COOLDOWN", "ALREADY_MARKED"])

    def test_07_daily_and_monthly_attendance_calculations(self):
        daily = database.get_daily_attendance()
        self.assertEqual(daily["present_count"], 2)
        self.assertEqual(daily["face_count"], 1)
        self.assertEqual(daily["qr_count"], 1)
        self.assertGreaterEqual(daily["attendance_rate"], 0.0)

        student = database.get_student_by_roll("TEST-ROLL-001")
        monthly = database.get_monthly_attendance(student_id=student["id"])
        self.assertIsNotNone(monthly["student_data"])
        sd = monthly["student_data"]
        self.assertEqual(sd["present_days"], 1)
        self.assertEqual(sd["elapsed_days"], sd["present_days"] + sd["absent_days"])
        self.assertEqual(sd["total_days"], sd["elapsed_days"] + sd["upcoming_days"])
        
        # Verify calendar day status according to date
        today_date = datetime.now().date()
        for day_rec in sd["calendar_days"]:
            d_obj = datetime.strptime(day_rec["date"], "%Y-%m-%d").date()
            if d_obj > today_date:
                self.assertEqual(day_rec["status"], "UPCOMING", f"Future date {day_rec['date']} must be UPCOMING")
                self.assertEqual(day_rec["method"], "-")
                self.assertEqual(day_rec["time"], "-")
            elif d_obj == today_date:
                self.assertIn(day_rec["status"], ["PRESENT", "ABSENT"])
            else:
                self.assertIn(day_rec["status"], ["PRESENT", "ABSENT"])

        # Test future month (all upcoming)
        future_month_str = (datetime.now().replace(year=datetime.now().year + 1)).strftime("%Y-%m")
        future_monthly = database.get_monthly_attendance(student_id=student["id"], year_month=future_month_str)
        self.assertEqual(future_monthly["student_data"]["upcoming_days"], future_monthly["days_in_month"])
        self.assertEqual(future_monthly["student_data"]["present_days"], 0)
        self.assertEqual(future_monthly["student_data"]["absent_days"], 0)
        self.assertEqual(future_monthly["student_data"]["attendance_percentage"], 0.0)

    def test_08_database_backup(self):
        success, msg, backup_path = database.backup_database()
        self.assertTrue(success, f"Database backup failed: {msg}")
        self.assertIsNotNone(backup_path)
        self.assertTrue(backup_path.exists())
        self.assertGreater(backup_path.stat().st_size, 0)
        backup_path.unlink()

    def test_09_attendance_deletion(self):
        daily = database.get_daily_attendance()
        record_to_delete = None
        for r in daily["records"]:
            if r["status"] == "PRESENT" and r["attendance_id"]:
                record_to_delete = r
                break

        self.assertIsNotNone(record_to_delete)
        att_id = record_to_delete["attendance_id"]
        
        del_success, _ = database.delete_attendance(att_id)
        self.assertTrue(del_success)

        daily_after = database.get_daily_attendance()
        self.assertEqual(daily_after["present_count"], daily["present_count"] - 1)

    def test_10_student_deletion_cascade(self):
        student = database.get_student_by_roll("TEST-ROLL-002")
        s_id = student["id"]

        del_success, _ = database.delete_student(s_id)
        self.assertTrue(del_success)

        self.assertIsNone(database.get_student_by_id(s_id))

        qr_file = config.QR_DIR / f"student_{s_id}.png"
        face_dir = config.FACES_DIR / str(s_id)
        self.assertFalse(qr_file.exists(), "QR file should be deleted on student deletion.")
        self.assertFalse(face_dir.exists(), "Face folder should be deleted on student deletion.")

    def test_11_authenticated_flask_routes(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "admin"
            sess["role"] = "admin"

        routes = [
            ("/", 200),
            ("/dashboard", 200),
            ("/students", 200),
            ("/students/register", 200),
            ("/train", 200),
            ("/face-attendance", 200),
            ("/qr-attendance", 200),
            ("/daily-attendance", 200),
            ("/monthly-attendance", 200),
            ("/attendance-history", 200),
            ("/settings", 200),
            ("/health", 200),
            ("/api/dashboard", 200),
            ("/api/students", 200),
            ("/api/attendance/today", 200),
        ]

        for route, expected_status in routes:
            resp = self.client.get(route)
            self.assertEqual(resp.status_code, expected_status, f"Route {route} returned {resp.status_code}")

    def test_12_camera_status_and_control(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "admin"
            sess["role"] = "admin"

        # 1. Check camera status JSON API
        status_resp = self.client.get("/api/camera/status")
        self.assertEqual(status_resp.status_code, 200)
        st_json = status_resp.get_json()
        self.assertEqual(st_json["status"], "success")
        self.assertIn("online", st_json)
        self.assertIn("model_ready", st_json)

        # 2. Stop camera API
        stop_resp = self.client.post("/api/camera/stop")
        self.assertEqual(stop_resp.status_code, 200)
        self.assertTrue(stop_resp.get_json()["success"])

        # 3. Check Face Attendance page indicators
        face_page_resp = self.client.get("/face-attendance")
        self.assertEqual(face_page_resp.status_code, 200)
        self.assertIn(b"Live Optical Feed", face_page_resp.data)
        self.assertIn(b"Stop Camera", face_page_resp.data)

    @classmethod
    def tearDownClass(cls):
        with database.db_session() as conn:
            conn.execute("DELETE FROM attendance;")
            conn.execute("DELETE FROM students;")
            conn.execute("DELETE FROM users WHERE username != 'admin';")
        if config.QR_DIR.exists():
            for f in config.QR_DIR.glob("student_*.png"):
                try: f.unlink()
                except: pass
        if config.FACES_DIR.exists():
            shutil.rmtree(config.FACES_DIR, ignore_errors=True)
            config.FACES_DIR.mkdir(exist_ok=True)
        if config.MODEL_PATH.exists():
            try: config.MODEL_PATH.unlink()
            except: pass

if __name__ == "__main__":
    unittest.main()
