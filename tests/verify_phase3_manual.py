import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np
import database
import qr_engine
from app import app

def run_manual_phase3_check():
    print("==================================================")
    print(" PHASE 3: QR WORKFLOW MANUAL/FUNCTIONAL VERIFICATION")
    print("==================================================")

    # 1. Ensure DB & default admin
    database.init_db()
    client = app.test_client()

    # 2. Authenticate admin
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["username"] = "admin"
        sess["role"] = "admin"
        sess["_csrf_token"] = "csrf_phase3_verify"

    # 3. Create test student
    success, msg, sid = database.add_student("Marie Curie", "CS-2026-QR-MANUAL")
    assert success and sid is not None, f"Failed to create student: {msg}"
    print(f" [OK] A & B: Student registered: Marie Curie (ID: #{sid})")

    # 4. Open student QR page
    resp_view = client.get(f"/qr/view/{sid}")
    assert resp_view.status_code == 200
    assert b"Marie Curie" in resp_view.data
    print(f" [OK] C & D: QR view page accessible at /qr/view/{sid}")

    # 5. Download QR
    resp_dl = client.get(f"/qr/download/{sid}")
    assert resp_dl.status_code == 200
    assert resp_dl.mimetype == "image/png"
    assert len(resp_dl.data) > 500
    print(f" [OK] E: Download QR returned valid PNG ({len(resp_dl.data)} bytes)")

    # 6. Open QR Attendance page
    resp_scanner = client.get("/qr-attendance")
    assert resp_scanner.status_code == 200
    assert b"QR Code Scanner" in resp_scanner.data
    print(f" [OK] F & G: QR Attendance scanner portal loads at /qr-attendance")

    # 7. Scan student QR and mark attendance
    payload = qr_engine.generate_payload(sid)
    scan_resp = client.post("/api/attendance/scan-qr", json={
        "payload": payload,
        "csrf_token": "csrf_phase3_verify"
    })
    assert scan_resp.status_code == 200
    scan_json = scan_resp.get_json()
    assert scan_json["success"] is True
    assert scan_json["status"] == "MARKED"
    assert scan_json["record"]["method"] == "qr"
    print(f" [OK] H, I, J: QR scanned successfully -> {scan_json['message']}")

    # 8. Duplicate Scan on same day
    dup_resp = client.post("/api/attendance/scan-qr", json={
        "payload": payload,
        "csrf_token": "csrf_phase3_verify"
    })
    assert dup_resp.status_code == 200
    dup_json = dup_resp.get_json()
    assert dup_json["success"] is False
    assert dup_json["status"] == "ALREADY_MARKED"
    print(f" [OK] K & L: Duplicate QR scan rejected -> {dup_json['message']}")

    # 9. Invalid QR Scan
    inv_resp = client.post("/api/attendance/scan-qr", json={
        "payload": "TAMPERED_OR_INVALID_CODE",
        "csrf_token": "csrf_phase3_verify"
    })
    assert inv_resp.status_code == 200
    inv_json = inv_resp.get_json()
    assert inv_json["success"] is False
    assert inv_json["status"] == "INVALID"
    print(f" [OK] M: Invalid QR correctly rejected -> {inv_json['message']}")

    # 10. Stop Camera Endpoint
    stop_resp = client.post("/api/camera/stop")
    assert stop_resp.status_code == 200
    print(f" [OK] N & O: Stop camera API confirmed released")

    # Cleanup
    database.delete_student(sid)
    print("==================================================")
    print(" ALL 15 PHASE 3 FUNCTIONAL CHECKS PASSED (100%)")
    print("==================================================")

if __name__ == "__main__":
    run_manual_phase3_check()
