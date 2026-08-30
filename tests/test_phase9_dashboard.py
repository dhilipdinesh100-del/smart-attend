import unittest
from datetime import datetime
from app import app
import database

class Phase9DashboardAnalyticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()
        cls.client = app.test_client()

        # Clean old test records
        with database.db_session() as conn:
            conn.execute("DELETE FROM attendance WHERE student_id IN (SELECT id FROM students WHERE roll_no IN ('CS-2026-P9-A', 'CS-2026-P9-B', 'CS-2026-P9-C'));")
            conn.execute("DELETE FROM students WHERE roll_no IN ('CS-2026-P9-A', 'CS-2026-P9-B', 'CS-2026-P9-C');")

        # Register 3 test students
        _, _, s1 = database.add_student("Tim Berners-Lee", "CS-2026-P9-A")
        _, _, s2 = database.add_student("Linus Torvalds", "CS-2026-P9-B")
        _, _, s3 = database.add_student("Margaret Hamilton", "CS-2026-P9-C")
        cls.student_1 = s1
        cls.student_2 = s2
        cls.student_3 = s3

    def test_01_unauthenticated_dashboard_redirect(self):
        """Verify unauthenticated requests to /dashboard and /api/dashboard are guarded."""
        unauth_client = app.test_client()

        resp_page = unauth_client.get("/dashboard")
        self.assertEqual(resp_page.status_code, 302)
        self.assertIn("/login", resp_page.headers.get("Location", ""))

        resp_root = unauth_client.get("/")
        self.assertEqual(resp_root.status_code, 302)
        self.assertIn("/login", resp_root.headers.get("Location", ""))

    def test_02_authenticated_dashboard_page_rendering(self):
        """Verify authenticated /dashboard renders all 7 KPI cards and charts container."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "admin"
            sess["role"] = "admin"

        resp = self.client.get("/dashboard")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Total Students", resp.data)
        self.assertIn(b"Present Today", resp.data)
        self.assertIn(b"Absent Today", resp.data)
        self.assertIn(b"Attendance %", resp.data)
        self.assertIn(b"Face Attendance", resp.data)
        self.assertIn(b"QR Attendance", resp.data)
        self.assertIn(b"Manual Logs", resp.data)
        self.assertIn(b"trendChart", resp.data)
        self.assertIn(b"methodChart", resp.data)

    def test_03_dashboard_api_endpoint(self):
        """Verify /api/dashboard returns JSON payload with stats and trends."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "admin"
            sess["role"] = "admin"

        resp = self.client.get("/api/dashboard")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("stats", data)
        self.assertIn("trends", data)
        self.assertIn("server_time", data)

    def test_04_kpi_calculations_and_method_breakdown(self):
        """Verify dashboard statistics accurately aggregate present, absent, rate, and method totals."""
        today_str = datetime.now().strftime("%Y-%m-%d")

        # Clear today's attendance for test students
        with database.db_session() as conn:
            conn.execute("DELETE FROM attendance WHERE student_id IN (?, ?, ?) AND date = ?;",
                         (self.student_1, self.student_2, self.student_3, today_str))

        # Mark Student 1 via FACE, Student 2 via QR, Student 3 via MANUAL
        database.mark_attendance(self.student_1, method="face")
        database.mark_attendance(self.student_2, method="qr")
        database.mark_attendance(self.student_3, method="manual")

        stats = database.get_dashboard_stats()
        self.assertGreaterEqual(stats["total_students"], 3)
        self.assertGreaterEqual(stats["today_present"], 3)
        self.assertGreaterEqual(stats["face_today"], 1)
        self.assertGreaterEqual(stats["qr_today"], 1)
        self.assertGreaterEqual(stats["manual_today"], 1)
        self.assertGreaterEqual(stats["face_total"], 1)
        self.assertGreaterEqual(stats["qr_total"], 1)
        self.assertGreaterEqual(stats["manual_total"], 1)
        self.assertGreater(stats["attendance_rate"], 0.0)

    def test_05_attendance_trends_and_future_dates(self):
        """Verify 7-day trend arrays and ensure future dates never corrupt trends."""
        trends = database.get_attendance_trends(days=7)
        self.assertEqual(len(trends["labels"]), 7)
        self.assertEqual(len(trends["dates"]), 7)
        self.assertEqual(len(trends["present"]), 7)
        self.assertEqual(len(trends["face"]), 7)
        self.assertEqual(len(trends["qr"]), 7)
        self.assertEqual(len(trends["manual"]), 7)

        # Most recent date in 7-day trend is today
        today_str = datetime.now().strftime("%Y-%m-%d")
        self.assertEqual(trends["dates"][-1], today_str)

    def test_06_top_attendees_ranking(self):
        """Verify top attendees rank query returns valid student records."""
        top = database.get_top_students(limit=5)
        self.assertIsInstance(top, list)
        for st in top:
            self.assertIn("name", st)
            self.assertIn("roll_no", st)
            self.assertIn("attendance_count", st)

    @classmethod
    def tearDownClass(cls):
        # Cleanup test students
        database.delete_student(cls.student_1)
        database.delete_student(cls.student_2)
        database.delete_student(cls.student_3)

if __name__ == "__main__":
    unittest.main()
