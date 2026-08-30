import os
import shutil
import cv2
from pathlib import Path
from database import init_db
from config import BASE_DIR, HAAR_CASCADE_PATH, DATA_DIR, QR_DIR, FACES_DIR, MODEL_DIR

def setup():
    # Initialize DB
    init_db()
    print("Database initialized successfully.")
    
    # Ensure directories
    for d in [DATA_DIR, QR_DIR, FACES_DIR, MODEL_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    print("Directories created.")
    
    # Copy Haar cascade if needed
    if not HAAR_CASCADE_PATH.exists():
        cv_cascade = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        if cv_cascade.exists():
            shutil.copyfile(str(cv_cascade), str(HAAR_CASCADE_PATH))
            print(f"Copied haarcascade to {HAAR_CASCADE_PATH} ({HAAR_CASCADE_PATH.stat().st_size} bytes)")
        else:
            print("Warning: cv2 haarcascade not found in cv2.data.haarcascades")
    else:
        print(f"Haar cascade already exists at {HAAR_CASCADE_PATH}")

if __name__ == "__main__":
    setup()
