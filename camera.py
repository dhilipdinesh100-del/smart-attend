import cv2
import numpy as np
import time
import os
import threading
import logging
from typing import Generator, Optional, Dict, Any
from config import BASE_DIR, HAAR_CASCADE_PATH, MODEL_PATH
import database
import face_engine
import qr_engine

logger = logging.getLogger("smartattend")

class CameraStreamManager:
    """
    Thread-safe camera stream manager with frame generator for MJPEG streaming.
    Guarantees strict hardware camera release and OpenCV cleanup on stream termination.
    """
    def __init__(self):
        self.lock = threading.RLock()
        self.read_lock = threading.RLock()
        self.active_camera: Optional[cv2.VideoCapture] = None
        self.current_camera_index: int = -1
        self.last_detection_event: Dict[str, Any] = {}
        self.capture_count = 0
        self.is_capturing = False
        self.capture_student_id = None
        self.target_samples = 30
        self._active_clients = 0
        self._last_frame_time = 0

    def get_camera(self, camera_index: int = 0) -> Optional[cv2.VideoCapture]:
        with self.lock:
            # Reuse active camera if already opened at requested index
            if self.active_camera is not None and self.current_camera_index == camera_index:
                if self.active_camera.isOpened():
                    return self.active_camera
                else:
                    try:
                        self.active_camera.release()
                    except Exception:
                        pass
                    self.active_camera = None

            if self.active_camera is not None:
                try:
                    self.active_camera.release()
                except Exception:
                    pass
                self.active_camera = None

            cap = None
            # On Windows, try CAP_DSHOW first for instant capture and fast release
            if os.name == 'nt':
                try:
                    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
                    if not cap.isOpened():
                        cap.release()
                        cap = cv2.VideoCapture(camera_index)
                except Exception as e:
                    logger.warning(f"DSHOW camera open failed, trying default backend: {e}")
                    cap = cv2.VideoCapture(camera_index)
            else:
                cap = cv2.VideoCapture(camera_index)

            if cap is not None and cap.isOpened():
                try:
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                    cap.set(cv2.CAP_PROP_FPS, 30)
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                except Exception:
                    pass

                self.active_camera = cap
                self.current_camera_index = camera_index
                logger.info(f"OpenCV Camera #{camera_index} initialized successfully.")
                return cap
            else:
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass
                logger.warning(f"Could not open camera #{camera_index}")
                return None

    def start(self, camera_index: Optional[int] = None) -> bool:
        """Explicitly start/initialize physical webcam. Returns True if opened."""
        if camera_index is None:
            try:
                camera_index = int(database.get_setting("camera_index", "0"))
            except (ValueError, TypeError):
                camera_index = 0
        cap = self.get_camera(camera_index)
        return cap is not None and cap.isOpened()

    def is_running(self) -> bool:
        """Check if physical camera is currently open and active."""
        with self.lock:
            return self.active_camera is not None and self.active_camera.isOpened()

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Thread-safe frame acquisition."""
        with self.read_lock:
            if self.active_camera is None or not self.active_camera.isOpened():
                return False, None
            try:
                success, frame = self.active_camera.read()
                if success and frame is not None:
                    self._last_frame_time = time.time()
                return success, frame
            except Exception as e:
                logger.error(f"Camera read exception: {e}")
                return False, None

    def get_frame(self) -> Optional[np.ndarray]:
        """Convenience method returning the raw BGR frame or None."""
        success, frame = self.read()
        return frame if success else None

    def stop(self):
        """Explicitly stop and release the physical webcam."""
        self.release_camera()

    def release_camera(self):
        """Completely release OpenCV VideoCapture hardware handle and destroy windows."""
        with self.lock:
            if self.active_camera is not None:
                try:
                    self.active_camera.release()
                except Exception as e:
                    logger.error(f"Error releasing camera: {e}")
                self.active_camera = None
                self.current_camera_index = -1
                self._active_clients = 0
                logger.info("OpenCV camera released and hardware handle closed.")
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass

    def stop_capture_session(self):
        """Stop dataset capture session and release camera."""
        with self.lock:
            self.is_capturing = False
            self.capture_student_id = None
        self.release_camera()

    def get_status(self) -> Dict[str, Any]:
        """Return real-time camera and model health status."""
        with self.lock:
            is_online = (
                self.active_camera is not None
                and self.active_camera.isOpened()
                and (time.time() - self._last_frame_time < 3.0 or self._active_clients > 0)
            )
            return {
                "online": is_online,
                "camera_index": self.current_camera_index,
                "active_clients": self._active_clients,
                "model_ready": MODEL_PATH.exists()
            }

    def create_placeholder_frame(
        self,
        message: str = "Optical Sensor Offline",
        subtext: str = "Check camera settings or permissions"
    ) -> np.ndarray:
        """Create a modern dark frame for fallback."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        for y in range(480):
            val = int(18 + (y / 480.0) * 16)
            frame[y, :] = (val + 6, val + 2, val)

        cv2.rectangle(frame, (10, 10), (630, 470), (45, 55, 72), 2)
        font = cv2.FONT_HERSHEY_SIMPLEX
        text_size = cv2.getTextSize(message, font, 0.75, 2)[0]
        text_x = (640 - text_size[0]) // 2
        cv2.putText(frame, message, (text_x, 220), font, 0.75, (241, 245, 249), 2, cv2.LINE_AA)

        sub_size = cv2.getTextSize(subtext, font, 0.45, 1)[0]
        sub_x = (640 - sub_size[0]) // 2
        cv2.putText(frame, subtext, (sub_x, 260), font, 0.45, (148, 163, 184), 1, cv2.LINE_AA)

        return frame

    def generate_face_stream(self) -> Generator[bytes, None, None]:
        """Stream video with real-time face detection, recognition, and attendance marking."""
        with self.lock:
            self._active_clients += 1
        try:
            try:
                cam_idx = int(database.get_setting("camera_index", "0"))
            except ValueError:
                cam_idx = 0

            cap = self.get_camera(cam_idx)
            conf_threshold = float(database.get_setting("face_confidence_threshold", "60"))
            consecutive_failures = 0

            while True:
                if cap is None or not cap.isOpened():
                    frame = self.create_placeholder_frame("Connecting to Optical Sensor...", f"Camera #{cam_idx} initializing")
                    ret, jpeg = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                    if ret:
                        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
                    time.sleep(0.5)
                    cap = self.get_camera(cam_idx)
                    continue

                with self.read_lock:
                    success, frame = cap.read()

                if not success or frame is None:
                    consecutive_failures += 1
                    if consecutive_failures > 5:
                        frame = self.create_placeholder_frame("Video Signal Interrupted", f"Reconnecting to Camera #{cam_idx}...")
                        ret, jpeg = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                        if ret:
                            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
                        time.sleep(0.3)
                        cap = self.get_camera(cam_idx)
                        consecutive_failures = 0
                    else:
                        time.sleep(0.02)
                    continue

                consecutive_failures = 0
                self._last_frame_time = time.time()
                frame = cv2.flip(frame, 1)

                try:
                    bboxes = face_engine.detect_faces(frame)
                    model_exists = MODEL_PATH.exists()

                    for bbox in bboxes:
                        x, y, w, h = bbox
                        if model_exists:
                            face_roi = face_engine.extract_face_roi(frame, bbox)
                            pred_id, conf, is_match = face_engine.recognize_face(face_roi, conf_threshold)

                            if is_match and pred_id is not None:
                                student = database.get_student_by_id(pred_id)
                                name = student["name"] if student else f"Student #{pred_id}"
                                roll = student["roll_no"] if student else ""

                                event = face_engine.process_face_attendance_event(pred_id)
                                self.last_detection_event = event

                                box_color = (74, 222, 128)  # Emerald green
                                label = f"{name} ({roll}) [{int(conf)}]"

                                cv2.rectangle(frame, (x, y), (x + w, y + h), box_color, 2)
                                cv2.rectangle(frame, (x, max(0, y - 28)), (x + w, y), box_color, -1)
                                cv2.putText(frame, label, (x + 6, max(18, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (15, 23, 42), 1, cv2.LINE_AA)
                            else:
                                box_color = (148, 163, 184)  # Slate
                                cv2.rectangle(frame, (x, y), (x + w, y + h), box_color, 1)
                                cv2.putText(frame, "Scanning / Unrecognized", (x, max(15, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (203, 213, 225), 1, cv2.LINE_AA)
                        else:
                            # Model not trained yet
                            box_color = (11, 158, 245)  # Amber
                            cv2.rectangle(frame, (x, y), (x + w, y + h), box_color, 2)
                            cv2.putText(frame, "Face Detected (Train Model First)", (x, max(15, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.42, box_color, 1, cv2.LINE_AA)
                except Exception as e:
                    logger.debug(f"Face recognition loop exception: {e}")

                ret, jpeg = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if ret:
                    yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
                time.sleep(0.015)
        finally:
            with self.lock:
                self._active_clients = max(0, self._active_clients - 1)
                if self._active_clients == 0:
                    self.release_camera()
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass

    def generate_qr_stream(self) -> Generator[bytes, None, None]:
        """Stream video with real-time QR code detection and attendance marking."""
        with self.lock:
            self._active_clients += 1
        try:
            try:
                cam_idx = int(database.get_setting("camera_index", "0"))
            except ValueError:
                cam_idx = 0

            cap = self.get_camera(cam_idx)
            detector = cv2.QRCodeDetector()
            last_scan_time = 0
            consecutive_failures = 0

            while True:
                if cap is None or not cap.isOpened():
                    frame = self.create_placeholder_frame("Connecting to Optical Sensor...", f"Camera #{cam_idx} initializing")
                    ret, jpeg = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                    if ret:
                        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
                    time.sleep(0.5)
                    cap = self.get_camera(cam_idx)
                    continue

                with self.read_lock:
                    success, frame = cap.read()

                if not success or frame is None:
                    consecutive_failures += 1
                    if consecutive_failures > 5:
                        frame = self.create_placeholder_frame("Video Signal Interrupted", f"Reconnecting to Camera #{cam_idx}...")
                        ret, jpeg = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                        if ret:
                            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
                        time.sleep(0.3)
                        cap = self.get_camera(cam_idx)
                        consecutive_failures = 0
                    else:
                        time.sleep(0.02)
                    continue

                consecutive_failures = 0
                self._last_frame_time = time.time()
                frame = cv2.flip(frame, 1)
                h_img, w_img = frame.shape[:2]

                target_box_size = 240
                cx, cy = w_img // 2, h_img // 2
                tx1, ty1 = cx - target_box_size // 2, cy - target_box_size // 2
                tx2, ty2 = cx + target_box_size // 2, cy + target_box_size // 2

                cv2.rectangle(frame, (tx1, ty1), (tx2, ty2), (99, 102, 241), 1)

                try:
                    data, bbox, _ = detector.detectAndDecode(frame)
                    if data and bbox is not None:
                        points = bbox.astype(int).reshape(-1, 2)
                        for i in range(len(points)):
                            pt1 = tuple(points[i])
                            pt2 = tuple(points[(i + 1) % len(points)])
                            cv2.line(frame, pt1, pt2, (34, 197, 94), 3)

                        now = time.time()
                        if now - last_scan_time > 1.0:
                            last_scan_time = now
                            res = qr_engine.process_qr_attendance(data)
                            self.last_detection_event = res
                except Exception as e:
                    logger.debug(f"QR stream decode exception: {e}")

                ret, jpeg = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if ret:
                    yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
                time.sleep(0.015)
        finally:
            with self.lock:
                self._active_clients = max(0, self._active_clients - 1)
                if self._active_clients == 0:
                    self.release_camera()
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass

    def generate_capture_stream(self, student_id: int) -> Generator[bytes, None, None]:
        """Stream video for capturing face datasets for a student."""
        with self.lock:
            self._active_clients += 1
        try:
            try:
                cam_idx = int(database.get_setting("camera_index", "0"))
            except ValueError:
                cam_idx = 0

            cap = self.get_camera(cam_idx)
            consecutive_failures = 0

            while True:
                if cap is None or not cap.isOpened():
                    frame = self.create_placeholder_frame("Connecting to Optical Sensor...", f"Camera #{cam_idx} initializing")
                    ret, jpeg = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                    if ret:
                        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
                    time.sleep(0.5)
                    cap = self.get_camera(cam_idx)
                    continue

                with self.read_lock:
                    success, frame = cap.read()

                if not success or frame is None:
                    consecutive_failures += 1
                    if consecutive_failures > 5:
                        frame = self.create_placeholder_frame("Video Signal Interrupted", f"Reconnecting to Camera #{cam_idx}...")
                        ret, jpeg = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                        if ret:
                            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
                        time.sleep(0.3)
                        cap = self.get_camera(cam_idx)
                        consecutive_failures = 0
                    else:
                        time.sleep(0.02)
                    continue

                consecutive_failures = 0
                self._last_frame_time = time.time()
                frame = cv2.flip(frame, 1)

                try:
                    bboxes = face_engine.detect_faces(frame)
                    current_count = face_engine.get_student_sample_count(student_id)

                    for bbox in bboxes:
                        x, y, w, h = bbox
                        cv2.rectangle(frame, (x, y), (x + w, y + h), (99, 102, 241), 2)

                        if self.is_capturing and self.capture_student_id == student_id:
                            if current_count < self.target_samples:
                                face_roi = face_engine.extract_face_roi(frame, bbox)
                                face_engine.save_face_sample(student_id, face_roi)
                                time.sleep(0.05)
                            else:
                                self.is_capturing = False

                    total_samples = face_engine.get_student_sample_count(student_id)
                    info_text = f"Samples: {total_samples} / {self.target_samples}"
                    cv2.putText(frame, info_text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
                except Exception as e:
                    logger.debug(f"Capture stream exception: {e}")

                ret, jpeg = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if ret:
                    yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
                time.sleep(0.015)
        finally:
            with self.lock:
                self._active_clients = max(0, self._active_clients - 1)
                if self._active_clients == 0:
                    self.release_camera()
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass

# Global camera manager instance
camera_manager = CameraStreamManager()
