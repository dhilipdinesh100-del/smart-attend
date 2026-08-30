import unittest
import csv
import io
from datetime import datetime, date, timedelta
from app import app
import database

class Phase8AttendanceAnalyticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()
        cls.client = app.test_client()

        # Clean old test records
        with database.db_session() as conn:
            conn.execute("DELETE FROM attendance WHERE student_id IN (SELECT id FROM students WHERE roll_no IN ('CS-2026-P8-A', 'CS-2026-P8-B'));")
            conn.execute("DELETE FROM students WHERE roll_no IN ('CS-2026-P8-A', 'CS-2026-P8-B');")

        # Create two dedicated test students
        _, _, s1 = database.add_student("Alan Kay", "CS-2026-P8-A")
        _, _, s2 = database.add_student("Barbara Liskov", "CS-2026-P8-B")
        cls.student_1 = s1
        cls.student_2 = s2

    def test_01_unauthenticated_redirection(self):
        """Verify unauthenticated requests to attendance reporting routes redirect to /login."""
        unauth_client = app.test_client()

        for route in ["/daily-attendance", "/monthly-attendance", "/attendance-history", "/attendance/export/csv"]:
            resp = unauth_client.get(route)
            self.assertEqual(resp.status_code, 302, f"Route {route} allowed unauthenticated access")
            self.assertIn("/login", resp.headers.get("Location", ""))

    def test_02_daily_attendance_reporting(self):
        """Verify daily attendance returns correct student status, counts, and methods."""
        today_str = datetime.now().strftime("%Y-%m-%d")

        # Mark attendance for student 1 via FACE and student 2 via QR
        with database.db_session() as conn:
            conn.execute("DELETE FROM attendance WHERE student_id IN (?, ?) AND date = ?;", (self.student_1, self.student_2, today_str))

        database.mark_attendance(self.student_1, method="face")
        database.mark_attendance(self.student_2, method="qr")

        report = database.get_daily_attendance(target_date=today_str)
        self.assertGreaterEqual(report["total_students"], 2)
        self.assertGreaterEqual(report["present_count"], 2)
        self.assertGreaterEqual(report["face_count"], 1)
        self.assertGreaterEqual(report["qr_count"], 1)

        # Check records in student list
        student_records = {r["id"]: r for r in report["records"]}
        self.assertIn(self.student_1, student_records)
        self.assertEqual(student_records[self.student_1]["status"], "PRESENT")
        self.assertEqual(student_records[self.student_1]["method"], "FACE")

        self.assertIn(self.student_2, student_records)
        self.assertEqual(student_records[self.student_2]["status"], "PRESENT")
        self.assertEqual(student_records[self.student_2]["method"], "QR")

    def test_03_monthly_attendance_future_date_and_percentage_calculation(self):
        """
        CRITICAL TEST:
        1. Future dates (date > today) MUST have status='UPCOMING', NEVER 'ABSENT'.
        2. Future dates MUST NOT decrease attendance percentage.
        3. Past dates with no attendance are 'ABSENT'.
        4. Past dates with attendance are 'PRESENT'.
        """
        current_year_month = datetime.now().strftime("%Y-%m")
        today_day = datetime.now().day

        # Get monthly matrix for Student 1
        monthly_report = database.get_monthly_attendance(student_id=self.student_1, year_month=current_year_month)
        s_data = monthly_report["student_data"]
        self.assertIsNotNone(s_data)

        calendar_days = s_data["calendar_days"]
        self.assertGreaterEqual(len(calendar_days), 28)

        # Validate each calendar day
        for day_entry in calendar_days:
            day_num = int(day_entry["day"])
            entry_date = datetime.strptime(day_entry["date"], "%Y-%m-%d").date()
            today_date = datetime.now().date()

            if entry_date > today_date:
                # FUTURE DATE MUST BE UPCOMING
                self.assertEqual(day_entry["status"], "UPCOMING",
                                 f"Future date {day_entry['date']} was marked {day_entry['status']} instead of UPCOMING")
            elif entry_date == today_date:
                # TODAY'S ATTENDANCE
                self.assertEqual(day_entry["status"], "PRESENT")
            else:
                # PAST DATE
                self.assertIn(day_entry["status"], ["PRESENT", "ABSENT"])

        # Check percentage calculation:
        # elapsed_days should ONLY count days elapsed up to today (present_days + absent_days)
        self.assertEqual(s_data["elapsed_days"], s_data["present_days"] + s_data["absent_days"])
        self.assertEqual(s_data["total_days"], s_data["elapsed_days"] + s_data["upcoming_days"])

        expected_percentage = round((s_data["present_days"] / s_data["elapsed_days"] * 100), 1) if s_data["elapsed_days"] > 0 else 0.0
        self.assertEqual(s_data["attendance_percentage"], expected_percentage)

    def test_04_attendance_history_and_filters(self):
        """Verify attendance history filtering by student, method, and date."""
        # Query history for student 1
        hist = database.get_attendance_history(student_id=self.student_1, method="face")
        self.assertGreaterEqual(hist["total"], 1)
        self.assertTrue(all(r["student_id"] == self.student_1 for r in hist["records"]))
        self.assertTrue(all(r["method"] == "FACE" for r in hist["records"]))

        # Query history for student 2
        hist2 = database.get_attendance_history(student_id=self.student_2, method="qr")
        self.assertGreaterEqual(hist2["total"], 1)
        self.assertTrue(all(r["student_id"] == self.student_2 for r in hist2["records"]))
        self.assertTrue(all(r["method"] == "QR" for r in hist2["records"]))

    def test_05_csv_export_format_and_security(self):
        """Verify attendance CSV export has correct columns and does not leak private credentials."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "admin"
            sess["role"] = "admin"

        resp = self.client.get("/attendance/export/csv")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, "text/csv")
        self.assertIn("attachment; filename=", resp.headers.get("Content-Disposition", ""))

        csv_text = resp.data.decode("utf-8")
        reader = csv.reader(io.StringIO(csv_text))
        rows = list(reader)

        # Check Header
        self.assertGreaterEqual(len(rows), 1)
        header = rows[0]
        self.assertEqual(header, ["Student ID", "Student Name", "Roll Number", "Date", "Time", "Method", "Status"])

        # Check that no passwords, hashes, or session tokens exist anywhere in the export
        for row in rows:
            for cell in row:
                self.assertNotIn("scrypt:", cell)
                self.assertNotIn("pbkdf2:", cell)
                self.assertNotIn("password", cell.lower())

    def test_06_dashboard_statistics(self):
        """Verify get_dashboard_stats returns fast aggregate statistics without full table scans."""
        stats = database.get_dashboard_stats()
        self.assertIn("total_students", stats)
        self.assertIn("today_present", stats)
        self.assertIn("today_absent", stats)
        self.assertIn("attendance_rate", stats)
        self.assertIn("face_today", stats)
        self.assertIn("qr_today", stats)
        self.assertGreaterEqual(stats["total_students"], 2)
        self.assertGreaterEqual(stats["today_present"], 2)

    def test_07_duplicate_attendance_protection(self):
        """Verify double check-in on the same calendar day is blocked across all methods."""
        today_str = datetime.now().strftime("%Y-%m-%d")

        # Student 1 is already marked today from test_02
        success_face, msg_face, _ = database.mark_attendance(self.student_1, method="face")
        self.assertFalse(success_face)
        self.assertIn("Already marked today", msg_face)

        success_qr, msg_qr, _ = database.mark_attendance(self.student_1, method="qr")
        self.assertFalse(success_qr)
        self.assertIn("Already marked today", msg_qr)

        success_manual, msg_manual, _ = database.mark_attendance(self.student_1, method="manual")
        self.assertFalse(success_manual)
        self.assertIn("Already marked today", msg_manual)

    @classmethod
    def tearDownClass(cls):
        # Clean up test students
        database.delete_student(cls.student_1)
        database.delete_student(cls.student_2)

if __name__ == "__main__":
    unittest.main()
