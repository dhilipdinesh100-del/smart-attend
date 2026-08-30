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

class Phase5FaceCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()
        cls.client = app.test_client()

        # Create a dedicated test student for Phase 5
        with database.db_session() as conn:
            conn.execute("DELETE FROM attendance WHERE student_id IN (SELECT id FROM students WHERE roll_no = 'CS-2026-P5-FACE');")
            conn.execute("DELETE FROM students WHERE roll_no = 'CS-2026-P5-FACE';")

        success, msg, sid = database.add_student("Alan Turing", "CS-2026-P5-FACE")
        assert success and sid is not None
        cls.student_id = sid

    def test_01_unauthenticated_capture_protection(self):
        """Verify unauthenticated requests to capture pages and APIs are guarded."""
        unauth_client = app.test_client()

        # HTML page redirects
        resp_page = unauth_client.get(f"/capture/{self.student_id}")
        self.assertEqual(resp_page.status_code, 302)
        self.assertIn("/login", resp_page.headers.get("Location", ""))

        # API endpoints return 401
        resp_start = unauth_client.post(f"/api/capture/start/{self.student_id}")
        self.assertEqual(resp_start.status_code, 401)

        resp_status = unauth_client.get(f"/api/capture/status/{self.student_id}")
        self.assertEqual(resp_status.status_code, 401)

        resp_reset = unauth_client.post(f"/api/capture/reset/{self.student_id}")
        self.assertEqual(resp_reset.status_code, 401)

    def test_02_authenticated_capture_page_rendering(self):
        """Verify capture UI displays student credentials and live viewport."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "admin"
            sess["role"] = "admin"

        resp = self.client.get(f"/capture/{self.student_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Face Dataset Capture", resp.data)
        self.assertIn(b"Alan Turing", resp.data)
        self.assertIn(b"CS-2026-P5-FACE", resp.data)
        self.assertIn(b"/video_feed/capture/", resp.data)

    def test_03_invalid_student_handling(self):
        """Verify accessing capture page with nonexistent student ID redirects."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "admin"
            sess["role"] = "admin"

        resp = self.client.get("/capture/9999999")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/students", resp.headers.get("Location", ""))

    def test_04_dataset_directory_and_sample_storage(self):
        """Verify face sample storage structure and User.<id>.<idx>.jpg naming convention."""
        # Reset any existing test samples
        face_engine.reset_student_dataset(self.student_id)
        self.assertEqual(face_engine.get_student_sample_count(self.student_id), 0)

        # Create synthetic 200x200 grayscale face ROI
        mock_face_roi = np.full((200, 200), 128, dtype=np.uint8)
        cv2.circle(mock_face_roi, (100, 100), 50, 200, -1)

        # Save 3 test samples
        for i in range(1, 4):
            success, idx, path_str = face_engine.save_face_sample(self.student_id, mock_face_roi)
            self.assertTrue(success)
            self.assertEqual(idx, i)
            self.assertTrue(os.path.exists(path_str))
            self.assertIn(f"User.{self.student_id}.{i:03d}.jpg", path_str)

        # Verify count
        self.assertEqual(face_engine.get_student_sample_count(self.student_id), 3)

        # Test reset
        face_engine.reset_student_dataset(self.student_id)
        self.assertEqual(face_engine.get_student_sample_count(self.student_id), 0)

    def test_05_face_roi_extraction_and_normalization(self):
        """Verify extract_face_roi resizes and equalizes face to 200x200."""
        dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.rectangle(dummy_frame, (200, 140), (360, 300), (200, 200, 200), -1)

        bbox = (200, 140, 160, 160)
        roi = face_engine.extract_face_roi(dummy_frame, bbox, target_size=(200, 200))

        self.assertIsInstance(roi, np.ndarray)
        self.assertEqual(roi.shape, (200, 200))
        self.assertEqual(roi.dtype, np.uint8)

    def test_06_capture_api_lifecycle(self):
        """Verify /api/capture/start, /api/capture/status, and /api/capture/reset endpoints."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "admin"
            sess["role"] = "admin"

        # 1. Start Capture
        resp_start = self.client.post(f"/api/capture/start/{self.student_id}")
        self.assertEqual(resp_start.status_code, 200)
        json_start = resp_start.get_json()
        self.assertTrue(json_start["success"])
        self.assertTrue(camera_manager.is_capturing)
        self.assertEqual(camera_manager.capture_student_id, self.student_id)

        # 2. Status Poll
        resp_status = self.client.get(f"/api/capture/status/{self.student_id}")
        self.assertEqual(resp_status.status_code, 200)
        json_status = resp_status.get_json()
        self.assertEqual(json_status["student_id"], self.student_id)
        self.assertIn("sample_count", json_status)
        self.assertIn("target_samples", json_status)

        # 3. Reset
        resp_reset = self.client.post(f"/api/capture/reset/{self.student_id}")
        self.assertEqual(resp_reset.status_code, 200)
        json_reset = resp_reset.get_json()
        self.assertTrue(json_reset["success"])
        self.assertEqual(json_reset["sample_count"], 0)

        # Clean session
        camera_manager.stop_capture_session()

    @classmethod
    def tearDownClass(cls):
        # Cleanup test student & dataset
        face_engine.reset_student_dataset(cls.student_id)
        database.delete_student(cls.student_id)
        camera_manager.stop()

if __name__ == "__main__":
    unittest.main()
