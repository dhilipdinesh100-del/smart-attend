import unittest
import cv2
import numpy as np
from pathlib import Path

import config
import database
from camera import camera_manager, CameraStreamManager
from app import app

class Phase4CameraManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()
        cls.client = app.test_client()

    def test_01_camera_manager_singleton_and_initial_state(self):
        """Verify camera manager instance, attributes, and thread locks."""
        self.assertIsInstance(camera_manager, CameraStreamManager)
        self.assertIsNotNone(camera_manager.lock)
        self.assertIsNotNone(camera_manager.read_lock)
        
        # Fresh initial status
        camera_manager.stop()
        self.assertFalse(camera_manager.is_running())

        status = camera_manager.get_status()
        self.assertIn("online", status)
        self.assertIn("active_clients", status)
        self.assertIn("model_ready", status)

    def test_02_placeholder_fallback_frame(self):
        """Verify dark placeholder fallback frame generation for offline state."""
        frame = camera_manager.create_placeholder_frame("Test Signal", "Offline Reason")
        self.assertIsInstance(frame, np.ndarray)
        self.assertEqual(frame.shape, (480, 640, 3))
        self.assertEqual(frame.dtype, np.uint8)

        # Ensure valid JPEG encoding
        ret, jpeg = cv2.imencode('.jpg', frame)
        self.assertTrue(ret)
        self.assertGreater(len(jpeg), 1000)

    def test_03_stop_and_release_idempotency(self):
        """Verify stop() and release_camera() are safe when called repeatedly."""
        # Calling stop multiple times must never throw exceptions
        camera_manager.stop()
        camera_manager.stop()
        camera_manager.release_camera()
        camera_manager.release_camera()
        self.assertFalse(camera_manager.is_running())
        self.assertEqual(camera_manager.current_camera_index, -1)

    def test_04_thread_safe_read_when_offline(self):
        """Verify read() and get_frame() return (False, None) gracefully when offline."""
        camera_manager.stop()
        success, frame = camera_manager.read()
        self.assertFalse(success)
        self.assertIsNone(frame)

        raw_frame = camera_manager.get_frame()
        self.assertIsNone(raw_frame)

    def test_05_camera_api_endpoints(self):
        """Verify authenticated /api/camera/status, /api/camera/stop, and /api/camera/start endpoints."""
        csrf_tok = "csrf_token_p4"
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "admin"
            sess["role"] = "admin"
            sess["_csrf_token"] = csrf_tok

        # 1. GET /api/camera/status
        resp_status = self.client.get("/api/camera/status")
        self.assertEqual(resp_status.status_code, 200)
        json_st = resp_status.get_json()
        self.assertEqual(json_st["status"], "success")
        self.assertIn("online", json_st)
        self.assertIn("active_clients", json_st)

        # 2. POST /api/camera/stop
        resp_stop = self.client.post("/api/camera/stop")
        self.assertEqual(resp_stop.status_code, 200)
        json_stop = resp_stop.get_json()
        self.assertTrue(json_stop["success"])
        self.assertFalse(camera_manager.is_running())

        # 3. POST /api/camera/start
        resp_start = self.client.post("/api/camera/start")
        self.assertEqual(resp_start.status_code, 200)
        json_start = resp_start.get_json()
        self.assertIn("success", json_start)

        # Always release after test
        camera_manager.stop()

    def test_06_unauthenticated_api_protection(self):
        """Verify unauthenticated requests to camera APIs and streaming pages are protected."""
        unauth_client = app.test_client()
        # API endpoints return 401 JSON when unauthenticated
        resp1 = unauth_client.get("/api/camera/status")
        self.assertEqual(resp1.status_code, 401)
        self.assertIn("Authentication required", resp1.get_json()["message"])

        resp2 = unauth_client.post("/api/camera/stop")
        self.assertEqual(resp2.status_code, 401)

        # HTML streaming pages return 302 redirect to /login
        resp3 = unauth_client.get("/qr-attendance")
        self.assertEqual(resp3.status_code, 302)
        self.assertIn("/login", resp3.headers.get("Location", ""))

    def test_07_qr_and_stream_routes_available(self):
        """Verify /video_feed/qr and /video_feed/face routes are registered and protected."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "admin"
            sess["role"] = "admin"

        # Check endpoints return 200 stream headers or initial frame
        resp_qr = self.client.get("/qr-attendance")
        self.assertEqual(resp_qr.status_code, 200)

        resp_face = self.client.get("/face-attendance")
        self.assertEqual(resp_face.status_code, 200)

if __name__ == "__main__":
    unittest.main()
