import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import argparse
import time
from config import MODEL_PATH
import database
import face_engine

def main():
    parser = argparse.ArgumentParser(description="SmartAttend - Real-Time Face Recognition Attendance Scanner")
    parser.add_argument("--camera", type=int, default=0, help="Camera index (default: 0)")
    parser.add_argument("--threshold", type=float, default=None, help="Confidence threshold (default: from settings)")
    args = parser.parse_args()

    database.init_db()

    if not MODEL_PATH.exists():
        print(f"[ERROR] Trained model file not found at '{MODEL_PATH}'.")
        print("[INFO] Please capture face datasets and run 'python scripts/train_model.py' first.")
        return

    conf_thresh = args.threshold
    if conf_thresh is None:
        try:
            conf_thresh = float(database.get_setting("face_confidence_threshold", "60"))
        except ValueError:
            conf_thresh = 60.0

    print("=" * 60)
    print(" SmartAttend — Real-Time Face Recognition Attendance")
    print(f" Confidence Threshold: {conf_thresh} (Lower = stricter match)")
    print(" Press 'q' or ESC in video window to exit.")
    print("=" * 60)

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f"[ERROR] Could not open camera #{args.camera}.")
        return

    last_event_msg = "Ready. Point camera at student face."
    last_event_time = time.time()

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("[ERROR] Failed to read frame.")
                break

            frame = cv2.flip(frame, 1)
            bboxes = face_engine.detect_faces(frame)

            for bbox in bboxes:
                x, y, w, h = bbox
                face_roi = face_engine.extract_face_roi(frame, bbox)
                pred_id, conf, is_match = face_engine.recognize_face(face_roi, conf_thresh)

                if is_match and pred_id is not None:
                    student = database.get_student_by_id(pred_id)
                    name = student["name"] if student else f"Student #{pred_id}"
                    roll = student["roll_no"] if student else ""

                    event = face_engine.process_face_attendance_event(pred_id)
                    if event.get("status") in ["MARKED", "ALREADY_MARKED"]:
                        last_event_msg = f"{name} ({roll}): {event['message']}"
                        last_event_time = time.time()
                        print(f"[{event['status']}] {last_event_msg}")

                    # Draw green box
                    cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                    cv2.putText(frame, f"{name} [{int(conf)}]", (x, y - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                else:
                    # Unknown / low confidence
                    cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 0, 255), 1)
                    cv2.putText(frame, f"Unknown [{int(conf) if conf < 990 else '?'}]", (x, y - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

            # Status banner at top
            cv2.rectangle(frame, (0, 0), (frame.shape[1], 40), (20, 20, 20), -1)
            cv2.putText(frame, last_event_msg[:70], (10, 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

            cv2.imshow("SmartAttend - Face Recognition Attendance", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or key == 27:
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
    print("[INFO] Face attendance scanner closed.")

if __name__ == "__main__":
    main()
