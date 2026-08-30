import hashlib
import qrcode
from PIL import Image, ImageDraw, ImageFont
import cv2
import numpy as np
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from config import QR_DIR, SECRET_KEY, QR_SECRET_SALT, logger
import database

def get_qr_checksum(student_id: int) -> str:
    """Generate an 8-character deterministic checksum for a student QR code."""
    salt = f"{student_id}:{QR_SECRET_SALT}:smartattend_qr"
    return hashlib.sha256(salt.encode("utf-8")).hexdigest()[:8]

def generate_payload(student_id: int) -> str:
    """Generate the standard SmartAttend QR payload."""
    checksum = get_qr_checksum(student_id)
    return f"SMARTATTEND:{student_id}:{checksum}"

def validate_payload(raw_data: str) -> Tuple[bool, Optional[int], str]:
    """
    Validate and extract student_id from scanned QR payload.
    Accepts:
    1. Standard 'SMARTATTEND:<student_id>:<checksum>' format
    2. Legacy / numeric '<student_id>' format for backwards compatibility
    Returns (is_valid, student_id, error_reason).
    """
    raw_str = (raw_data or "").strip()
    if not raw_str:
        return False, None, "Empty QR payload."

    if raw_str.startswith("SMARTATTEND:"):
        parts = raw_str.split(":")
        if len(parts) != 3:
            return False, None, "Invalid SmartAttend QR structure."
        try:
            student_id = int(parts[1])
        except ValueError:
            return False, None, "Invalid student ID in QR payload."
        
        expected_checksum = get_qr_checksum(student_id)
        if parts[2] != expected_checksum:
            return False, None, "Invalid QR checksum signature."
        return True, student_id, "Valid"

    # Fallback to direct integer string if valid
    try:
        student_id = int(raw_str)
        return True, student_id, "Valid (Legacy numeric)"
    except ValueError:
        return False, None, "Invalid QR code format. Not a SmartAttend QR code."

def generate_qr_code(student_id: int, force_regenerate: bool = False) -> Path:
    """
    Generate and save a styled QR code for a given student_id.
    Saved to data/qr/student_<student_id>.png.
    """
    QR_DIR.mkdir(parents=True, exist_ok=True)
    qr_path = QR_DIR / f"student_{student_id}.png"
    
    if qr_path.exists() and not force_regenerate:
        return qr_path
        
    student = database.get_student_by_id(student_id)
    content = generate_payload(student_id)
    
    # Create QR code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(content)
    qr.make(fit=True)
    
    qr_img = qr.make_image(fill_color="#000000", back_color="#ffffff").convert("RGB")
    
    # Add styling: clean card with student metadata label at bottom
    width, height = qr_img.size
    card_width = width + 40
    card_height = height + 80
    card = Image.new("RGB", (card_width, card_height), "#ffffff")
    
    # Paste QR code centered
    card.paste(qr_img, (20, 20))
    
    # Draw student roll / ID text if student exists
    draw = ImageDraw.Draw(card)
    label_text = f"ID: #{student_id}"
    if student:
        label_text = f"{student['name']} • {student['roll_no']}"
        
    # Center text
    bbox = draw.textbbox((0, 0), label_text)
    text_w = bbox[2] - bbox[0]
    draw.text(((card_width - text_w) // 2, height + 30), label_text, fill="#334155")
    
    card.save(str(qr_path), format="PNG")
    logger.info(f"Generated QR pass for student #{student_id} at {qr_path}")
    return qr_path

def get_or_create_qr(student_id: int) -> Path:
    """Ensure the QR file exists, regenerating it if missing."""
    qr_path = QR_DIR / f"student_{student_id}.png"
    if not qr_path.exists():
        return generate_qr_code(student_id, force_regenerate=True)
    return qr_path

def decode_qr_from_image(image: np.ndarray) -> Tuple[bool, Optional[str], Optional[np.ndarray]]:
    """
    Decode QR code from an OpenCV BGR image using cv2.QRCodeDetector with fallback enhancements.
    Returns (found, decoded_text, bbox).
    """
    if image is None:
        return False, None, None
    detector = cv2.QRCodeDetector()
    try:
        data, bbox, _ = detector.detectAndDecode(image)
        if data:
            return True, data.strip(), bbox
    except Exception:
        pass

    # Fallback to grayscale
    try:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        data, bbox, _ = detector.detectAndDecode(gray)
        if data:
            return True, data.strip(), bbox
            
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        data, bbox, _ = detector.detectAndDecode(thresh)
        if data:
            return True, data.strip(), bbox
    except Exception:
        pass

    return False, None, None

import time
_qr_cooldowns: Dict[int, float] = {}

def process_qr_attendance(raw_data: str) -> Dict[str, Any]:
    """
    Parse scanned QR code data, validate signature and student existence,
    and atomically mark attendance with in-memory debouncing.
    """
    global _qr_cooldowns
    is_valid, student_id, err_msg = validate_payload(raw_data)
    if not is_valid or student_id is None:
        return {
            "success": False,
            "status": "INVALID",
            "message": f"Invalid QR Code: {err_msg}",
            "student": None,
            "record": None
        }

    now = time.time()
    if student_id in _qr_cooldowns and now - _qr_cooldowns[student_id] < 3.0:
        student = database.get_student_by_id(student_id)
        return {
            "success": False,
            "status": "ALREADY_MARKED",
            "message": f"Cooldown active: Attendance already processed for {student['name'] if student else student_id}",
            "student": student,
            "record": None
        }

    _qr_cooldowns[student_id] = now
    student = database.get_student_by_id(student_id)
    if not student:
        return {
            "success": False,
            "status": "NOT_FOUND",
            "message": f"Student Not Found for ID #{student_id}.",
            "student": None,
            "record": None
        }

    # Mark attendance with method = 'qr'
    success, msg, record = database.mark_attendance(student_id, method="qr")
    
    if success:
        return {
            "success": True,
            "status": "MARKED",
            "message": f"Attendance Marked: {student['name']} ({student['roll_no']}) via QR",
            "student": student,
            "record": record
        }
    else:
        return {
            "success": False,
            "status": "ALREADY_MARKED" if "Already marked" in msg else "ERROR",
            "message": msg,
            "student": student,
            "record": record
        }
