import cv2
import numpy as np
import os
import time
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
from PIL import Image
from config import FACES_DIR, MODEL_DIR, MODEL_PATH, HAAR_CASCADE_PATH, BASE_DIR
import database

# Cache for loaded model and cascade
_face_cascade = None
_face_recognizer = None
_last_model_mtime = 0
_recognition_cooldowns: Dict[int, float] = {}

def get_face_cascade() -> cv2.CascadeClassifier:
    global _face_cascade
    if _face_cascade is None:
        cascade_path = str(HAAR_CASCADE_PATH)
        if not os.path.exists(cascade_path):
            raise FileNotFoundError(f"Haar cascade XML not found at {cascade_path}")
        _face_cascade = cv2.CascadeClassifier(cascade_path)
        if _face_cascade.empty():
            raise ValueError(f"Failed to load Haar cascade classifier from {cascade_path}")
    return _face_cascade

def detect_faces(image: np.ndarray, scale_factor: float = 1.15, min_neighbors: int = 4) -> List[Tuple[int, int, int, int]]:
    """
    Fast frontal face detection using scaled cascade.
    Returns list of (x, y, w, h) bounding boxes in original image coordinates.
    """
    cascade = get_face_cascade()
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
        
    h, w = gray.shape[:2]
    # Fast 0.5x downscaled detection for 3-4x speedup on CPU
    if w > 320:
        small_gray = cv2.resize(gray, (0, 0), fx=0.5, fy=0.5)
        small_gray = cv2.equalizeHist(small_gray)
        faces = cascade.detectMultiScale(
            small_gray,
            scaleFactor=scale_factor,
            minNeighbors=min_neighbors,
            minSize=(30, 30),
            flags=cv2.CASCADE_SCALE_IMAGE
        )
        return [(int(x * 2), int(y * 2), int(w_box * 2), int(h_box * 2)) for (x, y, w_box, h_box) in faces]
    else:
        gray = cv2.equalizeHist(gray)
        faces = cascade.detectMultiScale(
            gray,
            scaleFactor=scale_factor,
            minNeighbors=min_neighbors,
            minSize=(60, 60),
            flags=cv2.CASCADE_SCALE_IMAGE
        )
        return [(int(x), int(y), int(w_box), int(h_box)) for (x, y, w_box, h_box) in faces]

def extract_face_roi(image: np.ndarray, bbox: Tuple[int, int, int, int], target_size: Tuple[int, int] = (200, 200)) -> np.ndarray:
    """Crop and normalize face region for training or inference."""
    x, y, w, h = bbox
    # Add a slight 5% padding if within bounds
    img_h, img_w = image.shape[:2]
    pad_w = int(w * 0.05)
    pad_h = int(h * 0.05)
    
    x1 = max(0, x - pad_w)
    y1 = max(0, y - pad_h)
    x2 = min(img_w, x + w + pad_w)
    y2 = min(img_h, y + h + pad_h)
    
    face_roi = image[y1:y2, x1:x2]
    if len(face_roi.shape) == 3:
        face_roi = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY)
        
    face_roi = cv2.equalizeHist(face_roi)
    face_roi = cv2.resize(face_roi, target_size, interpolation=cv2.INTER_AREA)
    return face_roi

def save_face_sample(student_id: int, face_roi: np.ndarray) -> Tuple[bool, int, str]:
    """Save a normalized face sample image into data/faces/<student_id>/ as User.<student_id>.<idx>.jpg"""
    student_dir = FACES_DIR / str(student_id)
    student_dir.mkdir(parents=True, exist_ok=True)
    
    current_count = get_student_sample_count(student_id)
    next_idx = current_count + 1
    sample_path = student_dir / f"User.{student_id}.{next_idx:03d}.jpg"
    
    cv2.imwrite(str(sample_path), face_roi)
    return True, next_idx, str(sample_path)

def reset_student_dataset(student_id: int) -> bool:
    """Safely remove existing face samples for a given student."""
    student_dir = FACES_DIR / str(student_id)
    if student_dir.exists():
        for item in student_dir.glob("*.*"):
            try:
                item.unlink()
            except Exception:
                pass
    return True

def get_student_sample_count(student_id: int) -> int:
    student_dir = FACES_DIR / str(student_id)
    if not student_dir.exists():
        return 0
    try:
        with os.scandir(str(student_dir)) as it:
            return sum(1 for entry in it if entry.is_file() and entry.name.endswith(('.jpg', '.png', '.jpeg')))
    except Exception:
        return 0

def train_lbph_model() -> Dict[str, Any]:
    """
    Train the LBPH Face Recognizer using all datasets in data/faces/.
    Saves model safely via atomic temporary file to data/model/trainer.yml.
    """
    FACES_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    
    student_dirs = [d for d in FACES_DIR.iterdir() if d.is_dir() and d.name.isdigit()]
    
    if not student_dirs:
        return {
            "success": False,
            "message": "No face dataset directories found in data/faces/. Please capture faces for registered students first.",
            "students_count": 0,
            "images_count": 0
        }
        
    face_samples = []
    labels = []
    students_with_data = set()
    
    for s_dir in student_dirs:
        student_id = int(s_dir.name)
        # Verify student exists in SQLite DB
        student = database.get_student_by_id(student_id)
        if not student:
            continue
            
        img_files = list(s_dir.glob("*.jpg")) + list(s_dir.glob("*.jpeg")) + list(s_dir.glob("*.png"))
        for img_file in img_files:
            try:
                pil_img = Image.open(str(img_file)).convert("L")
                img_np = np.array(pil_img, "uint8")
                img_np = cv2.equalizeHist(img_np)
                img_np = cv2.resize(img_np, (200, 200), interpolation=cv2.INTER_AREA)
                
                face_samples.append(img_np)
                labels.append(student_id)
                students_with_data.add(student_id)
            except Exception as e:
                print(f"Warning: Corrupted or unreadable image skipped: {img_file} ({e})")
                
    if not face_samples:
        return {
            "success": False,
            "message": "No valid face sample images found in datasets. Please capture face images first.",
            "students_count": 0,
            "images_count": 0
        }
        
    temp_model_path = MODEL_DIR / f"trainer_temp_{int(time.time() * 1000)}.yml"
    try:
        recognizer = cv2.face.LBPHFaceRecognizer_create(radius=1, neighbors=8, grid_x=8, grid_y=8)
        recognizer.train(face_samples, np.array(labels, dtype=np.int32))
        recognizer.save(str(temp_model_path))
        
        # Verify temporary model file was created successfully before replacing active trainer.yml
        if not temp_model_path.exists() or temp_model_path.stat().st_size < 500:
            raise IOError("Trained temporary model file is missing or invalid.")
            
        # Atomically replace destination model file
        if MODEL_PATH.exists():
            try:
                os.remove(str(MODEL_PATH))
            except Exception:
                pass
        temp_model_path.rename(MODEL_PATH)
        
        # Reset cached recognizer instance so next call reloads new model
        global _face_recognizer, _last_model_mtime
        _face_recognizer = None
        _last_model_mtime = 0
        
        return {
            "success": True,
            "message": f"Training completed successfully. Students trained: {len(students_with_data)}, Samples used: {len(face_samples)}.",
            "students_count": len(students_with_data),
            "images_count": len(face_samples),
            "model_path": str(MODEL_PATH)
        }
    except Exception as e:
        if temp_model_path.exists():
            try:
                temp_model_path.unlink()
            except Exception:
                pass
        return {
            "success": False,
            "message": f"Model training failed: {str(e)}",
            "students_count": len(students_with_data),
            "images_count": len(face_samples)
        }

def get_face_recognizer() -> Optional[Any]:
    """Load and cache the trained LBPH model safely if available."""
    global _face_recognizer, _last_model_mtime
    
    if not MODEL_PATH.exists():
        return None
        
    try:
        mtime = MODEL_PATH.stat().st_mtime
        if _face_recognizer is None or mtime != _last_model_mtime:
            rec = cv2.face.LBPHFaceRecognizer_create()
            rec.read(str(MODEL_PATH))
            _face_recognizer = rec
            _last_model_mtime = mtime
        return _face_recognizer
    except Exception as e:
        print(f"Error loading trainer.yml model: {e}")
        return None

def recognize_face(face_roi: np.ndarray, confidence_threshold: Optional[float] = None) -> Tuple[Optional[int], float, bool]:
    """
    Recognize a face ROI using the LBPH model.
    Lower confidence number = better match.
    Returns (predicted_student_id, confidence, is_match).
    """
    recognizer = get_face_recognizer()
    if recognizer is None:
        return None, 999.0, False
        
    if confidence_threshold is None:
        conf_setting = database.get_setting("face_confidence_threshold", "60")
        try:
            confidence_threshold = float(conf_setting)
        except ValueError:
            confidence_threshold = 60.0
            
    try:
        predicted_id, confidence = recognizer.predict(face_roi)
        # LBPH confidence: lower is closer. Under threshold is a match.
        is_match = (confidence <= confidence_threshold)
        return (predicted_id if is_match else None), float(confidence), is_match
    except Exception as e:
        print(f"Prediction error: {e}")
        return None, 999.0, False

def process_face_attendance_event(student_id: int) -> Dict[str, Any]:
    """
    Handle attendance marking for a recognized student with cooldown prevention.
    """
    global _recognition_cooldowns
    now = time.time()
    
    try:
        cooldown_secs = float(database.get_setting("recognition_cooldown", "5"))
    except ValueError:
        cooldown_secs = 5.0
        
    # Check memory cooldown to avoid spamming
    if student_id in _recognition_cooldowns:
        if now - _recognition_cooldowns[student_id] < cooldown_secs:
            # Still in cooldown
            student = database.get_student_by_id(student_id)
            return {
                "success": False,
                "status": "COOLDOWN",
                "message": f"Processed recently for {student['name'] if student else student_id}",
                "student": student,
                "record": None
            }
            
    _recognition_cooldowns[student_id] = now
    
    student = database.get_student_by_id(student_id)
    if not student:
        return {
            "success": False,
            "status": "NOT_FOUND",
            "message": f"Student ID #{student_id} not found in database.",
            "student": None,
            "record": None
        }
        
    success, msg, record = database.mark_attendance(student_id, method="face")
    return {
        "success": success,
        "status": "MARKED" if success else ("ALREADY_MARKED" if "Already marked" in msg else "ERROR"),
        "message": msg,
        "student": student,
        "record": record
    }
