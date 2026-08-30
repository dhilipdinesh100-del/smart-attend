import os
import logging
from pathlib import Path

# Load environment variables from .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Base Paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
QR_DIR = DATA_DIR / "qr"
FACES_DIR = DATA_DIR / "faces"
MODEL_DIR = DATA_DIR / "model"
PRIVATE_DIR = DATA_DIR / "private"
BACKUP_DIR = BASE_DIR / "backups"
DB_PATH = DATA_DIR / "attendance.db"
MODEL_PATH = MODEL_DIR / "trainer.yml"
HAAR_CASCADE_PATH = BASE_DIR / "haarcascade_frontalface_default.xml"
LOG_FILE = DATA_DIR / "app.log"

# Ensure all critical directories exist
for directory in [DATA_DIR, QR_DIR, FACES_DIR, MODEL_DIR, PRIVATE_DIR, BACKUP_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# Security Configuration via Environment Variables
SECRET_KEY = os.environ.get("SECRET_KEY", "smartattend-prod-secret-984729487-key")
QR_SECRET_SALT = os.environ.get("QR_SECRET_SALT", SECRET_KEY)
SESSION_COOKIE_HTTPONLY = True
# SameSite=None + Secure=True enables seamless authentication when embedded in cross-origin iframes (e.g. GitHub Pages)
SESSION_COOKIE_SAMESITE = os.environ.get("SESSION_COOKIE_SAMESITE", "None")
SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "1").lower() in ("1", "true", "yes")
PERMANENT_SESSION_LIFETIME = 86400 # 24 hours


# Server Host and Debug Settings (Production debug is OFF by default)
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", 5000))
FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "0").lower() in ("1", "true", "yes")

# Default Application Settings
DEFAULT_SETTINGS = {
    "app_name": "SmartAttend",
    "face_confidence_threshold": "60",
    "camera_index": "0",
    "recognition_cooldown": "5",
    "samples_per_student": "30"
}

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(str(LOG_FILE), encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("smartattend")
