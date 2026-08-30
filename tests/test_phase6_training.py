import unittest
import os
import cv2
import numpy as np
from pathlib import Path

import config
import database
import face_engine
from config import FACES_DIR, MODEL_DIR, MODEL_PATH
from app import app

class Phase6FaceModelTrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()
        cls.client = app.test_client()

        # Create two dedicated test students for Phase 6
        with database.db_session() as conn:
            conn.execute("DELETE FROM attendance WHERE student_id IN (SELECT id FROM students WHERE roll_no IN ('CS-2026-P6-A', 'CS-2026-P6-B'));")
            conn.execute("DELETE FROM students WHERE roll_no IN ('CS-2026-P6-A', 'CS-2026-P6-B');")

        _, _, s1 = database.add_student("Claude Shannon", "CS-2026-P6-A")
        _, _, s2 = database.add_student("Ada Lovelace", "CS-2026-P6-B")
        cls.student_1 = s1
        cls.student_2 = s2

    def test_01_training_page_auth_and_redirection(self):
        """Verify unauthenticated requests to /train and /api/train are guarded."""
        unauth_client = app.test_client()

        resp_get = unauth_client.get("/train")
        self.assertEqual(resp_get.status_code, 302)
        self.assertIn("/login", resp_get.headers.get("Location", ""))

        resp_post = unauth_client.post("/train")
        self.assertEqual(resp_post.status_code, 302)

        resp_api = unauth_client.post("/api/train")
        self.assertEqual(resp_api.status_code, 401)

    def test_02_authenticated_training_page_rendering(self):
        """Verify training page displays KPI metrics, student table, and compiler form."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "admin"
            sess["role"] = "admin"

        resp = self.client.get("/train")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Train Recognition Model", resp.data)
        self.assertIn(b"LBPH Face Recognition Compiler", resp.data)

    def test_03_lbph_model_training_and_atomic_file_creation(self):
        """Verify LBPH training on captured datasets and atomic trainer.yml generation."""
        # Clean any old test datasets
        face_engine.reset_student_dataset(self.student_1)
        face_engine.reset_student_dataset(self.student_2)

        # Generate distinct texture face samples for student 1 & 2
        for i in range(1, 11):
            # Student 1: Horizontal gradient stripes
            img1 = np.zeros((200, 200), dtype=np.uint8)
            for r in range(200):
                img1[r, :] = (r * 4 + i) % 256
            face_engine.save_face_sample(self.student_1, img1)

            # Student 2: Vertical gradient stripes
            img2 = np.zeros((200, 200), dtype=np.uint8)
            for c in range(200):
                img2[:, c] = (c * 4 + i) % 256
            face_engine.save_face_sample(self.student_2, img2)

        self.assertEqual(face_engine.get_student_sample_count(self.student_1), 10)
        self.assertEqual(face_engine.get_student_sample_count(self.student_2), 10)

        # Run LBPH Training
        result = face_engine.train_lbph_model()
        self.assertTrue(result["success"])
        self.assertGreaterEqual(result["students_count"], 2)
        self.assertGreaterEqual(result["images_count"], 20)
        self.assertTrue(MODEL_PATH.exists())
        self.assertGreater(MODEL_PATH.stat().st_size, 1000)

    def test_04_model_loading_and_face_recognition_prediction(self):
        """Verify get_face_recognizer loads model and accurately predicts student ID."""
        recognizer = face_engine.get_face_recognizer()
        self.assertIsNotNone(recognizer)

        # Test prediction for Student 1 pattern
        test_img1 = np.zeros((200, 200), dtype=np.uint8)
        for r in range(200):
            test_img1[r, :] = (r * 4 + 2) % 256

        pred_id1, conf1, is_match1 = face_engine.recognize_face(test_img1, confidence_threshold=80.0)
        self.assertEqual(pred_id1, self.student_1)
        self.assertTrue(is_match1)

        # Test prediction for Student 2 pattern
        test_img2 = np.zeros((200, 200), dtype=np.uint8)
        for c in range(200):
            test_img2[:, c] = (c * 4 + 2) % 256

        pred_id2, conf2, is_match2 = face_engine.recognize_face(test_img2, confidence_threshold=80.0)
        self.assertEqual(pred_id2, self.student_2)
        self.assertTrue(is_match2)

    def test_05_face_attendance_recording_and_duplicate_check(self):
        """Verify process_face_attendance_event marks method='face' and prevents duplicate logging."""
        # Clear today's attendance for student 1
        with database.db_session() as conn:
            conn.execute("DELETE FROM attendance WHERE student_id = ?;", (self.student_1,))

        # 1. First event -> MARKED with method='face'
        ev1 = face_engine.process_face_attendance_event(self.student_1)
        self.assertTrue(ev1["success"])
        self.assertEqual(ev1["status"], "MARKED")
        self.assertEqual(ev1["record"]["method"], "face")

        # 2. Second event on same day -> ALREADY_MARKED or COOLDOWN
        # Clear memory cooldown to test database duplicate rejection
        face_engine._recognition_cooldowns.clear()
        ev2 = face_engine.process_face_attendance_event(self.student_1)
        self.assertFalse(ev2["success"])
        self.assertEqual(ev2["status"], "ALREADY_MARKED")

        # Confirm only 1 database row exists
        with database.db_session() as conn:
            count = conn.execute("SELECT COUNT(*) FROM attendance WHERE student_id = ?;", (self.student_1,)).fetchone()[0]
            self.assertEqual(count, 1)

    def test_06_corrupt_and_missing_model_resilience(self):
        """Verify safe handling when trainer.yml is missing or corrupted."""
        from unittest.mock import patch
        with patch("face_engine.get_face_recognizer", return_value=None):
            pred_id, conf, is_match = face_engine.recognize_face(np.zeros((200, 200), dtype=np.uint8))
            self.assertIsNone(pred_id)
            self.assertFalse(is_match)
            self.assertEqual(conf, 999.0)

    @classmethod
    def tearDownClass(cls):
        # Cleanup test students
        face_engine.reset_student_dataset(cls.student_1)
        face_engine.reset_student_dataset(cls.student_2)
        database.delete_student(cls.student_1)
        database.delete_student(cls.student_2)

if __name__ == "__main__":
    unittest.main()
