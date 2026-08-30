import os
import unittest
from pathlib import Path
from flask import Flask
from config import (
    BASE_DIR, SECRET_KEY, FLASK_DEBUG, HOST, PORT,
    SESSION_COOKIE_HTTPONLY, SESSION_COOKIE_SAMESITE
)
import app as app_module

class ProductionDeploymentTests(unittest.TestCase):
    def test_01_app_exposes_flask_instance(self):
        """Verify app.py exposes app = Flask(__name__)."""
        self.assertIsInstance(app_module.app, Flask)
        self.assertEqual(app_module.app.name, "app")

    def test_02_production_debug_mode_default_off(self):
        """Verify production debug mode defaults to False."""
        self.assertFalse(FLASK_DEBUG)

    def test_03_cookie_security_and_session_settings(self):
        """Verify secure cookie settings for production sessions."""
        self.assertTrue(app_module.app.config["SESSION_COOKIE_HTTPONLY"])
        self.assertEqual(app_module.app.config["SESSION_COOKIE_SAMESITE"], "Lax")
        self.assertIsNotNone(app_module.app.secret_key)
        self.assertGreaterEqual(len(app_module.app.secret_key), 16)

    def test_04_requirements_txt_contains_production_deps(self):
        """Verify requirements.txt contains gunicorn and all core production dependencies."""
        req_path = BASE_DIR / "requirements.txt"
        self.assertTrue(req_path.exists())
        req_text = req_path.read_text(encoding="utf-8").lower()
        
        required_packages = [
            "flask",
            "gunicorn",
            "opencv-contrib-python",
            "qrcode",
            "pillow",
            "numpy",
            "openpyxl",
            "python-dotenv"
        ]
        for pkg in required_packages:
            self.assertIn(pkg, req_text, f"Missing {pkg} in requirements.txt")

    def test_05_gitignore_excludes_secrets_cache_and_backups(self):
        """Verify .gitignore contains all necessary production exclusion patterns."""
        gitignore_path = BASE_DIR / ".gitignore"
        self.assertTrue(gitignore_path.exists())
        gi_text = gitignore_path.read_text(encoding="utf-8")

        patterns = [
            ".env",
            "__pycache__/",
            "*.pyc",
            "backups/",
            "*.db-wal",
            "*.db-shm"
        ]
        for pat in patterns:
            self.assertIn(pat, gi_text, f"Missing '{pat}' pattern in .gitignore")

    def test_06_no_env_files_tracked_in_repo_root(self):
        """Verify no sensitive .env files are in the project root."""
        env_path = BASE_DIR / ".env"
        self.assertFalse(env_path.exists(), ".env file must not be committed to repository")

    def test_07_critical_templates_exist(self):
        """Verify all critical Jinja2 HTML templates exist."""
        templates_dir = BASE_DIR / "templates"
        critical_templates = [
            "base.html",
            "dashboard.html",
            "login.html",
            "register.html",
            "students.html",
            "student_detail.html",
            "register_student.html",
            "qr_attendance.html",
            "face_attendance.html",
            "daily_attendance.html",
            "monthly_attendance.html",
            "attendance.html",
            "train.html",
            "settings.html",
            "users.html",
            "create_user.html",
            "error.html"
        ]
        for tmpl in critical_templates:
            self.assertTrue((templates_dir / tmpl).is_file(), f"Missing template: {tmpl}")

    def test_08_critical_static_assets_exist(self):
        """Verify all critical CSS and JavaScript static assets exist."""
        static_dir = BASE_DIR / "static"
        critical_assets = [
            static_dir / "css" / "style.css",
            static_dir / "js" / "app.js",
            static_dir / "js" / "dashboard.js",
            static_dir / "js" / "attendance.js",
            static_dir / "js" / "qr.js"
        ]
        for asset in critical_assets:
            self.assertTrue(asset.is_file(), f"Missing static asset: {asset}")

if __name__ == "__main__":
    unittest.main()
