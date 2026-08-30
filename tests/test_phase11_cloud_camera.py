import io
import os
import cv2
import numpy as np
import unittest
from datetime import datetime
from PIL import Image

from app import app
import database
import face_engine
import security
from config import DATA_DIR, FACES_DIR, MODEL_PATH, MODEL_DIR

class Phase11CloudCameraTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()
        cls.client = app.test_client()

        # Create test admin session credentials
        cls.admin_username = "cloud_cam_admin"
        with database.db_session() as conn:
            conn.execute("DELETE FROM users WHERE username = ?;", (cls.admin_username,))
        
        ok, msg, uid = database.create_admin_user(
            full_name="Cloud Camera Admin",
            username=cls.admin_username,
            email="cloud.admin@smartattend.test",
            password="CloudAdminPass123"
        )
        cls.admin_id = uid

        # Create a test student
        cls.test_roll = "CLOUD-CAM-001"
        with database.db_session() as conn:
            conn.execute("DELETE FROM attendance WHERE student_id IN (SELECT id FROM students WHERE roll_no = ?);", (cls.test_roll,))
            conn.execute("DELETE FROM students WHERE roll_no = ?;", (cls.test_roll,))
        
        _, _, sid = database.add_student("Cloud Student", cls.test_roll)
        cls.student_id = sid

        # Generate a synthetic face image for testing
        cls.synth_face_img = cls._create_synthetic_face_image()
        cls.synth_face_bytes = cls._image_to_jpeg_bytes(cls.synth_face_img)

        # Generate a synthetic non-face image
        cls.blank_img = np.zeros((200, 200, 3), dtype=np.uint8)
        cls.blank_bytes = cls._image_to_jpeg_bytes(cls.blank_img)

    @classmethod
    def _create_synthetic_face_image(cls) -> np.ndarray:
        """Draw an image with basic contrast features for testing."""
        img = np.full((300, 300, 3), 180, dtype=np.uint8)
        # Head oval
        cv2.ellipse(img, (150, 150), (80, 110), 0, 0, 360, (120, 120, 120), -1)
        # Eyes
        cv2.circle(img, (120, 125), 14, (30, 30, 30), -1)
        cv2.circle(img, (180, 125), 14, (30, 30, 30), -1)
        # Nose
        cv2.line(img, (150, 135), (150, 165), (50, 50, 50), 3)
        # Mouth
        cv2.ellipse(img, (150, 190), (30, 12), 0, 0, 180, (40, 40, 40), 3)
        return img

    @classmethod
    def _image_to_jpeg_bytes(cls, img_np: np.ndarray) -> bytes:
        success, encoded = cv2.imencode(".jpg", img_np)
        return encoded.tobytes() if success else b""

    def login_client(self):
        """Set up authenticated test session with valid CSRF token."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.admin_id
            sess["username"] = self.admin_username
            sess["role"] = "admin"
            sess["full_name"] = "Cloud Camera Admin"
            sess["_csrf_token"] = "test_csrf_token_phase11"
        return "test_csrf_token_phase11"

    # =========================================================================
    # 1. PAGE ACCESS & AUTHENTICATION GUARD TESTS
    # =========================================================================

    def test_01_unauthenticated_page_access_redirects(self):
        """Verify unauthenticated requests to camera pages redirect to /login."""
        unauth = app.test_client()
        for path in ["/face-attendance", f"/capture/{self.student_id}", "/qr-attendance"]:
            resp = unauth.get(path)
            self.assertEqual(resp.status_code, 302, f"Failed for {path}")
            self.assertIn("/login", resp.headers.get("Location", ""))

    def test_02_authenticated_camera_pages_render_browser_webrtc_elements(self):
        """Verify authenticated camera pages load with WebRTC video and canvas elements."""
        self.login_client()
        
        # Face attendance
        resp = self.client.get("/face-attendance")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"browserVideo", resp.data)
        self.assertIn(b"frameCanvas", resp.data)
        self.assertIn(b"Browser Webcam", resp.data)

        # Face capture
        resp = self.client.get(f"/capture/{self.student_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"browserCaptureVideo", resp.data)
        self.assertIn(b"captureCanvas", resp.data)
        self.assertIn(b"Cloud Student", resp.data)

        # QR attendance
        resp = self.client.get("/qr-attendance")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"browserQrVideo", resp.data)

    # =========================================================================
    # 2. FRAME API AUTHENTICATION & CSRF TESTS
    # =========================================================================

    def test_03_unauthenticated_api_rejection(self):
        """Verify cloud frame endpoints reject unauthenticated requests with 401 or 302."""
        unauth = app.test_client()
        for path in ["/api/face/scan-frame", "/api/capture/frame", "/api/attendance/scan-qr-frame"]:
            resp = unauth.post(path, data={"frame": "empty"})
            self.assertIn(resp.status_code, [401, 302])

    def test_04_csrf_protection_on_frame_apis(self):
        """Verify invalid or missing CSRF tokens are rejected with 400 Bad Request."""
        # Set session without providing matching token in request
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.admin_id
            sess["_csrf_token"] = "valid_csrf_token_secret"

        resp = self.client.post("/api/face/scan-frame", data={
            "csrf_token": "wrong_token",
            "frame": (io.BytesIO(self.blank_bytes), "frame.jpg")
        })
        self.assertEqual(resp.status_code, 400)

    # =========================================================================
    # 3. INPUT VALIDATION, PAYLOAD SANITIZATION & SIZE LIMITS
    # =========================================================================

    def test_05_invalid_and_empty_image_rejection(self):
        """Verify invalid, empty, or corrupted frame payloads are rejected with 400."""
        token = self.login_client()

        # No frame payload
        resp = self.client.post("/api/face/scan-frame", data={"csrf_token": token})
        self.assertEqual(resp.status_code, 400)

        # Corrupted non-image bytes
        resp = self.client.post("/api/face/scan-frame", data={
            "csrf_token": token,
            "frame": (io.BytesIO(b"not-a-valid-image-file-contents"), "corrupt.jpg")
        })
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data["success"])

    def test_06_oversized_image_upload_rejection(self):
        """Verify image uploads exceeding size limit are rejected."""
        token = self.login_client()
        oversized_bytes = b"X" * (6 * 1024 * 1024) # 6MB
        resp = self.client.post("/api/face/scan-frame", data={
            "csrf_token": token,
            "frame": (io.BytesIO(oversized_bytes), "large.jpg")
        })
        self.assertEqual(resp.status_code, 400)

    def test_07_invalid_student_id_rejection_on_capture(self):
        """Verify non-integer or non-existent student IDs are rejected."""
        token = self.login_client()

        # Non-integer ID
        resp = self.client.post("/api/capture/frame", data={
            "csrf_token": token,
            "student_id": "abc_invalid",
            "frame": (io.BytesIO(self.blank_bytes), "frame.jpg")
        })
        self.assertEqual(resp.status_code, 400)

        # Non-existent ID
        resp = self.client.post("/api/capture/frame", data={
            "csrf_token": token,
            "student_id": 99999999,
            "frame": (io.BytesIO(self.blank_bytes), "frame.jpg")
        })
        self.assertEqual(resp.status_code, 404)

    # =========================================================================
    # 4. DATASET CAPTURE VIA BROWSER FRAMES
    # =========================================================================

    def test_08_capture_face_samples_via_frame_api(self):
        """Verify browser frames save normalized face samples in data/faces/<student_id>/."""
        token = self.login_client()

        # Reset dataset first
        face_engine.reset_student_dataset(self.student_id)
        self.assertEqual(face_engine.get_student_sample_count(self.student_id), 0)

        # Create a test ROI image
        test_face_roi = np.full((200, 200), 128, dtype=np.uint8)
        _, sample_idx, path = face_engine.save_face_sample(self.student_id, test_face_roi)
        self.assertEqual(sample_idx, 1)
        self.assertTrue(os.path.exists(path))

        # Check sample count via API
        resp = self.client.get(f"/api/capture/status/{self.student_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["sample_count"], 1)

    # =========================================================================
    # 5. FACE RECOGNITION & ATTENDANCE RECORDING
    # =========================================================================

    def test_09_cloud_face_attendance_marking_and_duplicate_prevention(self):
        """Verify face attendance marks attendance with method='face' and blocks duplicates."""
        token = self.login_client()
        today_str = datetime.now().strftime("%Y-%m-%d")

        # Clear today's attendance for test student
        with database.db_session() as conn:
            conn.execute("DELETE FROM attendance WHERE student_id = ? AND date = ?;", (self.student_id, today_str))

        # 1. Mark attendance via face event
        event1 = face_engine.process_face_attendance_event(self.student_id)
        self.assertTrue(event1["success"])
        self.assertEqual(event1["status"], "MARKED")
        self.assertEqual(event1["record"]["method"].lower(), "face")

        # 2. Attempt duplicate attendance on same day
        # Clear in-memory cooldown so duplicate check reaches database rule
        if self.student_id in face_engine._recognition_cooldowns:
            del face_engine._recognition_cooldowns[self.student_id]

        event2 = face_engine.process_face_attendance_event(self.student_id)
        self.assertFalse(event2["success"])
        self.assertEqual(event2["status"], "ALREADY_MARKED")

    def test_10_scan_qr_frame_api(self):
        """Verify cloud QR frame scanning endpoint handles valid QR images."""
        token = self.login_client()

        # Test with non-QR image returns NO_QR
        resp = self.client.post("/api/attendance/scan-qr-frame", data={
            "csrf_token": token,
            "frame": (io.BytesIO(self.blank_bytes), "frame.jpg")
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "NO_QR")

    @classmethod
    def tearDownClass(cls):
        # Clean test student & user
        database.delete_student(cls.student_id)
        with database.db_session() as conn:
            conn.execute("DELETE FROM users WHERE username = ?;", (cls.admin_username,))

if __name__ == "__main__":
    unittest.main()
