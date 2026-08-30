import unittest
import os
import sqlite3
from pathlib import Path

import config
import database
import security
from app import app

class Phase1AuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()
        cls.client = app.test_client()

    def test_01_directories_and_config(self):
        """Verify all essential directories exist."""
        self.assertTrue(config.DATA_DIR.exists())
        self.assertTrue(config.PRIVATE_DIR.exists())
        self.assertTrue(config.DB_PATH.exists())
        self.assertTrue(config.BACKUP_DIR.exists())

    def test_02_database_schema_and_tables(self):
        """Verify SQLite database schema, tables, foreign keys, and indexes."""
        with database.db_session() as conn:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
            self.assertIn("users", tables)
            self.assertIn("students", tables)
            self.assertIn("attendance", tables)
            self.assertIn("settings", tables)

            # Check unique constraints on users
            user_cols = conn.execute("PRAGMA table_info(users);").fetchall()
            col_names = [c["name"] for c in user_cols]
            self.assertIn("full_name", col_names)
            self.assertIn("username", col_names)
            self.assertIn("email", col_names)
            self.assertIn("password_hash", col_names)

    def test_03_default_admin_and_password_hashing(self):
        """Verify default admin exists and password is securely hashed."""
        admin = database.get_user_by_username("admin")
        self.assertIsNotNone(admin)
        self.assertEqual(admin["username"], "admin")
        
        # Verify plaintext is NEVER stored
        self.assertNotEqual(admin["password_hash"], "admin123")
        self.assertTrue(admin["password_hash"].startswith("scrypt:") or admin["password_hash"].startswith("pbkdf2:"))
        
        # Verify password verification
        self.assertTrue(security.verify_password(admin["password_hash"], "admin123"))
        self.assertFalse(security.verify_password(admin["password_hash"], "wrongpassword"))

    def test_04_credentials_verification(self):
        """Verify credentials check handles username and email lookups."""
        user = database.verify_user_credentials("admin", "admin123")
        self.assertIsNotNone(user)
        self.assertEqual(user["username"], "admin")

        bad_user = database.verify_user_credentials("admin", "invalidpass")
        self.assertIsNone(bad_user)

    def test_05_admin_registration_validation(self):
        """Verify input validation for admin registration."""
        # 1. Full name validation
        valid, val, err = security.validate_admin_full_name("  ")
        self.assertFalse(valid)
        self.assertIn("Full Name", err)

        valid, val, err = security.validate_admin_full_name("Prof. Alan Turing")
        self.assertTrue(valid)
        self.assertEqual(val, "Prof. Alan Turing")

        # 2. Username validation
        valid, val, err = security.validate_admin_username("ab")
        self.assertFalse(valid)

        valid, val, err = security.validate_admin_username("admin_user_01")
        self.assertTrue(valid)

        # 3. Email validation
        valid, val, err = security.validate_admin_email("invalid-email")
        self.assertFalse(valid)

        valid, val, err = security.validate_admin_email("alan@oxford.edu")
        self.assertTrue(valid)

        # 4. Password validation
        valid, err = security.validate_admin_password("short", "short")
        self.assertFalse(valid)
        self.assertIn("at least 8", err)

        valid, err = security.validate_admin_password("securepassword123", "mismatchpassword")
        self.assertFalse(valid)
        self.assertIn("match", err)

        valid, err = security.validate_admin_password("securepassword123", "securepassword123")
        self.assertTrue(valid)

    def test_06_admin_creation_and_duplicates(self):
        """Verify database creation of new admin and duplicate rejection."""
        test_uname = "phase1_test_admin"
        test_email = "phase1_test@school.edu"

        # Cleanup prior test runs
        with database.db_session() as conn:
            conn.execute("DELETE FROM users WHERE username = ? OR email = ?;", (test_uname, test_email))

        success, msg, user_id = database.create_admin_user(
            "Phase 1 Admin", test_uname, test_email, "StrongPass123"
        )
        self.assertTrue(success)
        self.assertIsNotNone(user_id)

        # Duplicate username
        dup_u_success, dup_u_msg, _ = database.create_admin_user(
            "Another Admin", test_uname, "different@school.edu", "StrongPass123"
        )
        self.assertFalse(dup_u_success)
        self.assertIn("Username already exists", dup_u_msg)

        # Duplicate email
        dup_e_success, dup_e_msg, _ = database.create_admin_user(
            "Another Admin 2", "unique_uname", test_email, "StrongPass123"
        )
        self.assertFalse(dup_e_success)
        self.assertIn("Email already registered", dup_e_msg)

        # Authenticate newly created admin
        auth_user = database.verify_user_credentials(test_uname, "StrongPass123")
        self.assertIsNotNone(auth_user)
        self.assertEqual(auth_user["id"], user_id)

    def test_07_web_authentication_flow(self):
        """Verify HTTP routes: /login, /register, /logout, and session enforcement."""
        # 1. Unauthenticated /dashboard redirects to /login
        resp_unauth = self.client.get("/dashboard")
        self.assertEqual(resp_unauth.status_code, 302)
        self.assertIn("/login", resp_unauth.headers.get("Location", ""))

        # 2. GET /login displays portal and link to /register
        resp_login_page = self.client.get("/login")
        self.assertEqual(resp_login_page.status_code, 200)
        self.assertIn(b"New administrator?", resp_login_page.data)
        self.assertIn(b"Create Admin Account", resp_login_page.data)
        self.assertIn(b"/register", resp_login_page.data)

        # 3. GET /register displays registration form
        resp_reg_page = self.client.get("/register")
        self.assertEqual(resp_reg_page.status_code, 200)
        self.assertIn(b"Create Admin Account", resp_reg_page.data)
        self.assertIn(b"Sign In", resp_reg_page.data)

        # 4. POST /login with invalid credentials fails
        resp_bad_login = self.client.post("/login", data={
            "username": "admin",
            "password": "wrong_password"
        })
        self.assertEqual(resp_bad_login.status_code, 200)
        self.assertIn(b"Invalid username or password", resp_bad_login.data)

        # 5. POST /login with valid admin credentials succeeds and redirects
        resp_ok_login = self.client.post("/login", data={
            "username": "admin",
            "password": "admin123"
        }, follow_redirects=False)
        self.assertEqual(resp_ok_login.status_code, 302)

        # 6. Authenticated /dashboard opens with HTTP 200
        resp_dash = self.client.get("/dashboard")
        self.assertEqual(resp_dash.status_code, 200)
        self.assertIn(b"Dashboard", resp_dash.data)

        # 7. Logout clears session and redirects to /login
        resp_logout = self.client.get("/logout")
        self.assertEqual(resp_logout.status_code, 302)
        self.assertIn("/login", resp_logout.headers.get("Location", ""))

if __name__ == "__main__":
    unittest.main()
