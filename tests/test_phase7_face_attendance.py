import unittest
import os
import cv2
import numpy as np
from pathlib import Path

import config
import database
import face_engine
from camera import camera_manager
from app import app

class Phase7FaceAttendanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()
        cls.client = app.test_client()

        # Create two dedicated test students for Phase 7
        with database.db_session() as conn:
            conn.execute("DELETE FROM attendance WHERE student_id IN (SELECT id FROM students WHERE roll_no IN ('CS-2026-P7-A', 'CS-2026-P7-B'));")
            conn.execute("DELETE FROM students WHERE roll_no IN ('CS-2026-P7-A', 'CS-2026-P7-B');")

        _, _, s1 = database.add_student("Grace Hopper", "CS-2026-P7-A")
        _, _, s2 = database.add_student("Katherine Johnson", "CS-2026-P7-B")
        cls.student_1 = s1
        cls.student_2 = s2

    def test_01_unauthenticated_access_protection(self):
        """Verify unauthenticated requests to face attendance pages and streams redirect to /login."""
        unauth_client = app.test_client()

        resp_page = unauth_client.get("/face-attendance")
        self.assertEqual(resp_page.status_code, 302)
        self.assertIn("/login", resp_page.headers.get("Location", ""))

        resp_feed = unauth_client.get("/video_feed/face")
        self.assertEqual(resp_feed.status_code, 302)

    def test_02_authenticated_face_attendance_page(self):
        """Verify authenticated /face-attendance loads live scanner interface."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "admin"
            sess["role"] = "admin"

        resp = self.client.get("/face-attendance")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Face Recognition Scanner", resp.data)
        self.assertIn(b"/video_feed/face", resp.data)
        self.assertIn(b"Live Verified Check-ins", resp.data)

    def test_03_per_student_cooldown_independence(self):
        """Verify cooldown on Student 1 never blocks Student 2 from check-in."""
        # Clear today's attendance for both test students
        with database.db_session() as conn:
            conn.execute("DELETE FROM attendance WHERE student_id IN (?, ?);", (self.student_1, self.student_2))

        # 1. Process Student 1 -> MARKED
        ev1 = face_engine.process_face_attendance_event(self.student_1)
        self.assertTrue(ev1["success"])
        self.assertEqual(ev1["status"], "MARKED")

        # 2. Immediate second call for Student 1 -> COOLDOWN
        ev1_repeat = face_engine.process_face_attendance_event(self.student_1)
        self.assertFalse(ev1_repeat["success"])
        self.assertIn(ev1_repeat["status"], ["COOLDOWN", "ALREADY_MARKED"])

        # 3. Call for Student 2 immediately -> Must SUCCEED (not blocked by Student 1's cooldown)
        ev2 = face_engine.process_face_attendance_event(self.student_2)
        self.assertTrue(ev2["success"])
        self.assertEqual(ev2["status"], "MARKED")
        self.assertEqual(ev2["record"]["method"], "face")

    def test_04_database_unique_constraint_duplicate_prevention(self):
        """Verify UNIQUE(student_id, date) constraint enforces single check-in per day."""
        # Clear in-memory cooldown to specifically test DB rejection
        face_engine._recognition_cooldowns.clear()

        # Student 1 was already marked today in test_03
        ev_dup = face_engine.process_face_attendance_event(self.student_1)
        self.assertFalse(ev_dup["success"])
        self.assertEqual(ev_dup["status"], "ALREADY_MARKED")
        self.assertIn("Already marked today", ev_dup["message"])

        # Confirm exactly 1 record in database
        with database.db_session() as conn:
            count = conn.execute("SELECT COUNT(*) FROM attendance WHERE student_id = ?;", (self.student_1,)).fetchone()[0]
            self.assertEqual(count, 1)

    def test_05_unknown_face_and_missing_student_handling(self):
        """Verify non-existent student IDs and unknown predictions do not mark attendance."""
        ev_nf = face_engine.process_face_attendance_event(999999)
        self.assertFalse(ev_nf["success"])
        self.assertEqual(ev_nf["status"], "NOT_FOUND")

    def test_06_camera_api_lifecycle(self):
        """Verify camera start, status, and stop during face scanner sessions."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "admin"
            sess["role"] = "admin"

        # Check status
        resp_st = self.client.get("/api/camera/status")
        self.assertEqual(resp_st.status_code, 200)

        # Stop camera explicitly
        resp_stop = self.client.post("/api/camera/stop")
        self.assertEqual(resp_stop.status_code, 200)
        self.assertFalse(camera_manager.is_running())

    @classmethod
    def tearDownClass(cls):
        # Cleanup test students
        database.delete_student(cls.student_1)
        database.delete_student(cls.student_2)
        camera_manager.stop()

if __name__ == "__main__":
    unittest.main()
