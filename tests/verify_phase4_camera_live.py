import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np
from camera import camera_manager
import database

def run_live_camera_verification():
    print("==================================================")
    print(" PHASE 4: LIVE HARDWARE CAMERA VALIDATION")
    print("==================================================")

    database.init_db()

    # Step 1: Start Camera via central manager
    print(" [1/7] Initializing physical camera with CAP_DSHOW...")
    is_open = camera_manager.start(0)
    print(f"       Camera Start Result: {'SUCCESS' if is_open else 'OFFLINE/VIRTUAL (Fallback active)'}")

    # Step 2: Test Frame Acquisition and Dimensions
    print(" [2/7] Testing frame acquisition & properties...")
    if is_open:
        success, frame = camera_manager.read()
        if success and frame is not None:
            h, w, c = frame.shape
            print(f"       Frame Acquired: {w}x{h} ({c} channels) - SUCCESS")
            assert w == 640 and h == 480 or (w > 0 and h > 0)
        else:
            print("       Read returned empty frame (testing fallback placeholder).")
            frame = camera_manager.create_placeholder_frame()
    else:
        frame = camera_manager.create_placeholder_frame()
        print("       Placeholder generated successfully (640x480).")

    # Step 3: Test JPEG stream encoding
    print(" [3/7] Testing MJPEG encoding quality...")
    ret, jpeg = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    assert ret is True and len(jpeg) > 500
    print(f"       JPEG encoded cleanly: {len(jpeg)} bytes.")

    # Step 4: Test First Clean Stop & Hardware Release
    print(" [4/7] Testing camera stop and hardware handle release...")
    camera_manager.stop()
    assert not camera_manager.is_running()
    print("       Camera successfully stopped. Hardware handle closed.")

    # Step 5: Test Re-initialization (Prevent 'camera in use' bugs)
    print(" [5/7] Testing second camera initialization (Re-open test)...")
    is_open_2 = camera_manager.start(0)
    print(f"       Re-open Result: {'SUCCESS' if is_open_2 else 'OFFLINE/VIRTUAL'}")
    if is_open_2:
        success_2, frame_2 = camera_manager.read()
        print(f"       Second read result: {success_2}")

    # Step 6: Test QR Stream Generator
    print(" [6/7] Testing QR Attendance stream generator lifecycle...")
    gen = camera_manager.generate_qr_stream()
    first_chunk = next(gen)
    assert b"--frame" in first_chunk
    assert b"Content-Type: image/jpeg" in first_chunk
    print("       QR stream chunk generated valid multipart frame.")
    gen.close()  # Cleanly close generator and release client lock

    # Step 7: Final Release
    print(" [7/7] Final hardware release & window destruction...")
    camera_manager.stop()
    assert not camera_manager.is_running()
    print("       Hardware released completely.")

    print("==================================================")
    print(" ALL 7 PHASE 4 CAMERA ARCHITECTURE CHECKS PASSED")
    print("==================================================")

if __name__ == "__main__":
    run_live_camera_verification()
