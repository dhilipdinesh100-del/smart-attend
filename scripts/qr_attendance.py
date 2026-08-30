import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import argparse
import time
import database
import qr_engine

def main():
    parser = argparse.ArgumentParser(description="SmartAttend - Real-Time QR Code Attendance Scanner")
    parser.add_argument("--camera", type=int, default=0, help="Camera index (default: 0)")
    args = parser.parse_args()

    database.init_db()

    print("=" * 60)
    print(" SmartAttend — Real-Time QR Attendance Scanner")
    print(" Show student QR card to camera. Press 'q' or ESC to exit.")
    print("=" * 60)

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f"[ERROR] Could not open camera #{args.camera}.")
        return

    detector = cv2.QRCodeDetector()
    last_event_msg = "Ready. Hold student QR code in front of camera."
    last_scan_time = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("[ERROR] Failed to read frame.")
                break

            frame = cv2.flip(frame, 1)
            h, w = frame.shape[:2]

            # Draw targeting reticle
            cx, cy = w // 2, h // 2
            box_size = 240
            cv2.rectangle(frame, (cx - box_size//2, cy - box_size//2),
                                 (cx + box_size//2, cy + box_size//2), (255, 255, 0), 1)

            try:
                data, bbox, _ = detector.detectAndDecode(frame)
                if data and bbox is not None:
                    # Draw polygon
                    points = bbox.astype(int).reshape(-1, 2)
                    for i in range(len(points)):
                        pt1 = tuple(points[i])
                        pt2 = tuple(points[(i + 1) % len(points)])
                        cv2.line(frame, pt1, pt2, (0, 255, 0), 3)

                    now = time.time()
                    if now - last_scan_time > 1.5:
                        last_scan_time = now
                        res = qr_engine.process_qr_attendance(data)
                        last_event_msg = res["message"]
                        print(f"[{res.get('status', 'SCANNED')}] {res['message']}")
            except Exception as e:
                print(f"QR decode error: {e}")

            # Status banner at top
            cv2.rectangle(frame, (0, 0), (frame.shape[1], 40), (20, 20, 20), -1)
            cv2.putText(frame, last_event_msg[:70], (10, 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

            cv2.imshow("SmartAttend - QR Attendance Scanner", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or key == 27:
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
    print("[INFO] QR attendance scanner closed.")

if __name__ == "__main__":
    main()
