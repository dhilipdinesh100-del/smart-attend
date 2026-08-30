import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import time
import argparse
from config import HAAR_CASCADE_PATH, FACES_DIR
import database
import face_engine

def main():
    parser = argparse.ArgumentParser(description="SmartAttend - Capture Face Dataset for a Student")
    parser.add_argument("--id", type=int, help="Student ID")
    parser.add_argument("--roll", type=str, help="Student Roll Number")
    parser.add_argument("--samples", type=int, default=30, help="Number of face samples to capture (default: 30)")
    parser.add_argument("--camera", type=int, default=0, help="Camera index (default: 0)")
    args = parser.parse_args()

    database.init_db()

    student = None
    if args.id:
        student = database.get_student_by_id(args.id)
    elif args.roll:
        student = database.get_student_by_roll(args.roll)
    else:
        # Prompt user
        all_students = database.get_all_students()
        if not all_students:
            print("[ERROR] No students registered in database. Register a student first.")
            return
        print("\nRegistered Students:")
        for s in all_students:
            print(f"  ID: {s['id']} | Roll: {s['roll_no']} | Name: {s['name']} | Current Samples: {s['face_samples']}")
        
        val = input("\nEnter Student ID or Roll Number to capture: ").strip()
        if val.isdigit():
            student = database.get_student_by_id(int(val))
        if not student:
            student = database.get_student_by_roll(val)

    if not student:
        print("[ERROR] Student not found. Exiting.")
        return

    student_id = student["id"]
    target_samples = args.samples
    print(f"\n[INFO] Starting face capture for: {student['name']} (Roll: {student['roll_no']}, ID: {student_id})")
    print(f"[INFO] Target samples: {target_samples}")
    print("[INFO] Press 'q' or ESC in the video window to quit early.")

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f"[ERROR] Could not open camera #{args.camera}. Check permissions/connection.")
        return

    count = face_engine.get_student_sample_count(student_id)
    print(f"[INFO] Existing samples: {count}")

    try:
        while count < target_samples:
            ret, frame = cap.read()
            if not ret:
                print("[ERROR] Failed to read frame from camera.")
                break

            frame = cv2.flip(frame, 1)
            bboxes = face_engine.detect_faces(frame)

            for bbox in bboxes:
                x, y, w, h = bbox
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                
                # Extract and save
                face_roi = face_engine.extract_face_roi(frame, bbox)
                _, count, _ = face_engine.save_face_sample(student_id, face_roi)
                time.sleep(0.08)

            # Overlay text
            cv2.putText(frame, f"Student: {student['name']} ({student['roll_no']})", (20, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(frame, f"Captured: {count} / {target_samples}", (20, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            cv2.imshow("SmartAttend - Face Capture", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or key == 27:
                print("[INFO] Capture cancelled by user.")
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
    print(f"\n[SUCCESS] Face dataset capture complete. Total samples for student {student_id}: {face_engine.get_student_sample_count(student_id)}")
    print("[INFO] You can now run 'python scripts/train_model.py' to train the recognizer.")

if __name__ == "__main__":
    main()
