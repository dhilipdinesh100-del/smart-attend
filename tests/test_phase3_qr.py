import unittest
import os
import cv2
import numpy as np
from pathlib import Path

import config
import database
import qr_engine
import security
from app import app

class Phase3QROperationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()
        cls.client = app.test_client()

        # Create a dedicated test student for Phase 3
        with database.db_session() as conn:
            conn.execute("DELETE FROM attendance WHERE student_id IN (SELECT id FROM students WHERE roll_no = 'CS-2026-P3-QR01');")
            conn.execute("DELETE FROM students WHERE roll_no = 'CS-2026-P3-QR01';")

        success, msg, sid = database.add_student("Nikola Tesla", "CS-2026-P3-QR01")
        assert success and sid is not None
        cls.student_id = sid

    def test_01_payload_generation_and_validation(self):
        """Test secure QR payload creation and cryptographic checksum validation."""
        payload = qr_engine.generate_payload(self.student_id)
        self.assertTrue(payload.startswith(f"SMARTATTEND:{self.student_id}:"))

        # Valid payload validation
        is_valid, sid, msg = qr_engine.validate_payload(payload)
        self.assertTrue(is_valid)
        self.assertEqual(sid, self.student_id)

        # Legacy numeric string validation
        is_valid_num, sid_num, _ = qr_engine.validate_payload(str(self.student_id))
        self.assertTrue(is_valid_num)
        self.assertEqual(sid_num, self.student_id)

        # Tampered / invalid checksum rejection
        tampered = f"SMARTATTEND:{self.student_id}:badchecksum"
        is_valid_tampered, _, err_tampered = qr_engine.validate_payload(tampered)
        self.assertFalse(is_valid_tampered)
        self.assertIn("checksum", err_tampered.lower())

        # Malformed format rejection
        is_valid_bad, _, _ = qr_engine.validate_payload("INVALID_RANDOM_TEXT")
        self.assertFalse(is_valid_bad)

        # Empty payload rejection
        is_valid_empty, _, _ = qr_engine.validate_payload("   ")
        self.assertFalse(is_valid_empty)

    def test_02_qr_code_file_generation_and_decoding(self):
        """Test QR code PNG generation, storage, and OpenCV decoding."""
        qr_path = qr_engine.generate_qr_code(self.student_id, force_regenerate=True)
        self.assertTrue(qr_path.exists())
        self.assertEqual(qr_path.name, f"student_{self.student_id}.png")
        self.assertGreater(qr_path.stat().st_size, 500)

        # Decode image using OpenCV QRCodeDetector
        img = cv2.imread(str(qr_path))
        self.assertIsNotNone(img)

        found, decoded_data, bbox = qr_engine.decode_qr_from_image(img)
        self.assertTrue(found)
        self.assertIsNotNone(decoded_data)
        
        # Verify decoded payload matches student
        is_valid, decoded_sid, _ = qr_engine.validate_payload(decoded_data)
        self.assertTrue(is_valid)
        self.assertEqual(decoded_sid, self.student_id)

    def test_03_qr_attendance_processing_and_duplicate_check(self):
        """Test processing valid QR scans, database recording, and duplicate prevention."""
        payload = qr_engine.generate_payload(self.student_id)

        # Clear any today's attendance for this student first
        with database.db_session() as conn:
            conn.execute("DELETE FROM attendance WHERE student_id = ?;", (self.student_id,))

        # 1. First scan -> MARKED
        res1 = qr_engine.process_qr_attendance(payload)
        self.assertTrue(res1["success"])
        self.assertEqual(res1["status"], "MARKED")
        self.assertEqual(res1["record"]["method"], "qr")

        # 2. Second scan on same day -> ALREADY_MARKED (No duplicate record)
        res2 = qr_engine.process_qr_attendance(payload)
        self.assertFalse(res2["success"])
        self.assertEqual(res2["status"], "ALREADY_MARKED")

        # Verify only 1 record exists in database
        with database.db_session() as conn:
            count = conn.execute("SELECT COUNT(*) FROM attendance WHERE student_id = ?;", (self.student_id,)).fetchone()[0]
            self.assertEqual(count, 1)

    def test_04_invalid_and_nonexistent_qr_rejection(self):
        """Test scanning invalid QR or non-existent student IDs."""
        # 1. Invalid payload
        res_inv = qr_engine.process_qr_attendance("GARBAGE_CODE_12345")
        self.assertFalse(res_inv["success"])
        self.assertEqual(res_inv["status"], "INVALID")

        # 2. Non-existent student ID
        fake_payload = qr_engine.generate_payload(999999)
        res_nf = qr_engine.process_qr_attendance(fake_payload)
        self.assertFalse(res_nf["success"])
        self.assertEqual(res_nf["status"], "NOT_FOUND")

    def test_05_unauthenticated_access_redirection(self):
        """Verify unauthenticated requests to QR endpoints redirect to /login."""
        endpoints = [
            "/qr-attendance",
            f"/qr/view/{self.student_id}",
            f"/qr/download/{self.student_id}"
        ]
        for ep in endpoints:
            resp = self.client.get(ep)
            self.assertEqual(resp.status_code, 302, f"Endpoint {ep} did not redirect")
            self.assertIn("/login", resp.headers.get("Location", ""))

    def test_06_authenticated_qr_web_routes(self):
        """Verify QR web display, raw image, download, and attendance scan endpoints."""
        csrf_tok = "test_csrf_token_p3"
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "admin"
            sess["role"] = "admin"
            sess["_csrf_token"] = csrf_tok

        # 1. GET /qr/view/<id> renders full HTML card
        resp_view = self.client.get(f"/qr/view/{self.student_id}")
        self.assertEqual(resp_view.status_code, 200)
        self.assertIn(b"Digital QR Attendance Pass", resp_view.data)
        self.assertIn(b"Nikola Tesla", resp_view.data)
        self.assertIn(b"Download QR", resp_view.data)

        # 2. GET /qr/view/<id>?raw=1 serves image/png
        resp_raw = self.client.get(f"/qr/view/{self.student_id}?raw=1")
        self.assertEqual(resp_raw.status_code, 200)
        self.assertEqual(resp_raw.mimetype, "image/png")

        # 3. GET /qr/download/<id> downloads PNG attachment
        resp_dl = self.client.get(f"/qr/download/{self.student_id}")
        self.assertEqual(resp_dl.status_code, 200)
        self.assertEqual(resp_dl.mimetype, "image/png")
        self.assertIn(f"student_{self.student_id}_qr.png", resp_dl.headers.get("Content-Disposition", ""))

        # 4. GET /qr-attendance opens live scanner portal
        resp_scanner = self.client.get("/qr-attendance")
        self.assertEqual(resp_scanner.status_code, 200)
        self.assertIn(b"QR Code Scanner", resp_scanner.data)
        self.assertIn(b"/video_feed/qr", resp_scanner.data)

        # 5. POST /api/attendance/scan-qr
        payload = qr_engine.generate_payload(self.student_id)
        resp_scan_api = self.client.post("/api/attendance/scan-qr", json={
            "payload": payload,
            "csrf_token": csrf_tok
        })
        self.assertEqual(resp_scan_api.status_code, 200)
        json_data = resp_scan_api.get_json()
        self.assertIn("status", json_data)

    @classmethod
    def tearDownClass(cls):
        # Cleanup test student
        database.delete_student(cls.student_id)

if __name__ == "__main__":
    unittest.main()
