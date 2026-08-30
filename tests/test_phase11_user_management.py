import unittest
import openpyxl
import io
from datetime import datetime

from app import app
import database
import security
import admin_audit
from admin_audit import EXCEL_REGISTRY_PATH

class Phase11UserManagementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()
        admin_audit.init_admin_registry()
        cls.client = app.test_client()

        # Clean old test users
        with database.db_session() as conn:
            conn.execute("DELETE FROM users WHERE username LIKE 'p11_%';")

        # Create base test admin
        database.create_admin_user("Phase 11 Primary Admin", "p11_primary_admin", "p11_primary@school.edu", "Password123")

    def test_01_login_page_loads(self):
        """Verify GET /login returns HTTP 200 and has login form elements."""
        resp = self.client.get("/login")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Sign In", resp.data)
        self.assertIn(b"username", resp.data)
        self.assertIn(b"password", resp.data)

    def test_02_invalid_login_rejected(self):
        """Verify invalid credentials return error message without leaking user existence."""
        resp = self.client.post("/login", data={"username": "p11_primary_admin", "password": "WrongPassword999"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Invalid username or password", resp.data)

    def test_03_valid_admin_login_succeeds(self):
        """Verify valid admin credentials create session and redirect to dashboard."""
        resp = self.client.post("/login", data={"username": "p11_primary_admin", "password": "Password123"})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/dashboard", resp.headers.get("Location", ""))

    def test_04_logout_invalidates_session(self):
        """Verify /logout clears session and redirects to /login."""
        # Login first
        self.client.post("/login", data={"username": "p11_primary_admin", "password": "Password123"})

        # Logout
        resp_logout = self.client.get("/logout")
        self.assertEqual(resp_logout.status_code, 302)
        self.assertIn("/login", resp_logout.headers.get("Location", ""))

        # Verify /dashboard is guarded
        resp_dash = self.client.get("/dashboard")
        self.assertEqual(resp_dash.status_code, 302)
        self.assertIn("/login", resp_dash.headers.get("Location", ""))

    def test_05_protected_dashboard_requires_authentication(self):
        """Verify unauthenticated requests to /dashboard redirect to /login."""
        unauth_client = app.test_client()
        resp = unauth_client.get("/dashboard")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers.get("Location", ""))

    def test_06_users_page_requires_authentication(self):
        """Verify unauthenticated requests to /users redirect to /login."""
        unauth_client = app.test_client()
        resp = unauth_client.get("/users")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers.get("Location", ""))

    def test_07_new_user_page_requires_authentication(self):
        """Verify unauthenticated requests to /users/new redirect to /login."""
        unauth_client = app.test_client()
        resp = unauth_client.get("/users/new")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers.get("Location", ""))

    def test_08_new_admin_creation_succeeds(self):
        """Verify authenticated admin can create a new user via POST /users/new with CSRF token."""
        token = "test_csrf_user_creation_token"
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "admin"
            sess["role"] = "admin"
            sess["_csrf_token"] = token

        resp = self.client.post("/users/new", data={
            "csrf_token": token,
            "full_name": "Dr. Sarah Connor",
            "username": "p11_sconnor",
            "email": "p11_sconnor@school.edu",
            "password": "SecurePassword456",
            "confirm_password": "SecurePassword456"
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/users", resp.headers.get("Location", ""))

        # Verify user exists in database
        user = database.get_user_by_username("p11_sconnor")
        self.assertIsNotNone(user)
        self.assertEqual(user["full_name"], "Dr. Sarah Connor")
        self.assertEqual(user["email"], "p11_sconnor@school.edu")

    def test_09_duplicate_username_rejected(self):
        """Verify attempting to create a user with an existing username is rejected."""
        token = "test_csrf_token_dup_user"
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "admin"
            sess["role"] = "admin"
            sess["_csrf_token"] = token

        resp = self.client.post("/users/new", data={
            "csrf_token": token,
            "full_name": "Duplicate User",
            "username": "p11_primary_admin",
            "email": "different_email@school.edu",
            "password": "Password123",
            "confirm_password": "Password123"
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Username already exists", resp.data)

    def test_10_duplicate_email_rejected(self):
        """Verify attempting to create a user with an existing email is rejected."""
        token = "test_csrf_token_dup_email"
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "admin"
            sess["role"] = "admin"
            sess["_csrf_token"] = token

        resp = self.client.post("/users/new", data={
            "csrf_token": token,
            "full_name": "Duplicate Email User",
            "username": "p11_unique_name_123",
            "email": "p11_primary@school.edu",
            "password": "Password123",
            "confirm_password": "Password123"
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Email already registered", resp.data)

    def test_11_password_mismatch_rejected(self):
        """Verify password and confirm_password mismatch is rejected."""
        token = "test_csrf_token_mismatch"
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "admin"
            sess["role"] = "admin"
            sess["_csrf_token"] = token

        resp = self.client.post("/users/new", data={
            "csrf_token": token,
            "full_name": "Mismatch User",
            "username": "p11_mismatch_user",
            "email": "mismatch@school.edu",
            "password": "Password123",
            "confirm_password": "DifferentPassword123"
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Passwords do not match", resp.data)

    def test_12_password_stored_hashed_never_plaintext(self):
        """Verify database stores only scrypt/werkzeug password hashes."""
        user = database.get_user_by_username("p11_sconnor")
        self.assertIsNotNone(user)
        self.assertNotIn("SecurePassword456", user["password_hash"])
        self.assertTrue(user["password_hash"].startswith("scrypt:") or user["password_hash"].startswith("pbkdf2:"))

    def test_13_new_user_can_login(self):
        """Verify newly created admin user can authenticate successfully."""
        new_client = app.test_client()
        resp = new_client.post("/login", data={"username": "p11_sconnor", "password": "SecurePassword456"})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/dashboard", resp.headers.get("Location", ""))

        # Verify access to /users
        resp_users = new_client.get("/users")
        self.assertEqual(resp_users.status_code, 200)
        self.assertIn(b"Dr. Sarah Connor", resp_users.data)
        self.assertIn(b"p11_sconnor", resp_users.data)

    def test_14_admin_registry_receives_new_user_info(self):
        """Verify Excel registry audit contains the newly registered admin."""
        records = admin_audit.get_all_audit_records()
        matching = [r for r in records if r["username"] == "p11_sconnor"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["full_name"], "Dr. Sarah Connor")
        self.assertEqual(matching[0]["email"], "p11_sconnor@school.edu")

    def test_15_excel_registry_contains_no_secrets(self):
        """Verify Excel file contains zero passwords or password hashes."""
        wb = openpyxl.load_workbook(str(EXCEL_REGISTRY_PATH))
        sheet = wb.active
        for row in sheet.iter_rows(values_only=True):
            for cell_val in row:
                val_str = str(cell_val or '').lower()
                self.assertNotIn("securepassword456", val_str)
                self.assertNotIn("scrypt:", val_str)
                self.assertNotIn("pbkdf2:", val_str)
                self.assertNotIn("password", val_str)

    def test_16_csrf_protection_on_user_creation(self):
        """Verify POST /users/new without CSRF token is blocked."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "admin"
            sess["role"] = "admin"

        resp = self.client.post("/users/new", data={
            "full_name": "No CSRF User",
            "username": "p11_nocsrf",
            "email": "nocsrf@school.edu",
            "password": "Password123",
            "confirm_password": "Password123"
        })
        self.assertIn(resp.status_code, [400, 403])

    def test_17_existing_admin_remains_functional(self):
        """Verify primary admin can still log in and access system."""
        user = database.verify_user_credentials("p11_primary_admin", "Password123")
        self.assertIsNotNone(user)
        self.assertEqual(user["username"], "p11_primary_admin")

    def test_18_existing_data_remains_intact(self):
        """Verify students, attendance, and settings tables remain unharmed."""
        students = database.get_all_students()
        self.assertIsInstance(students, list)
        settings = database.get_all_settings()
        self.assertIn("app_name", settings)

    @classmethod
    def tearDownClass(cls):
        # Clean test admins
        with database.db_session() as conn:
            conn.execute("DELETE FROM users WHERE username IN ('p11_primary_admin', 'p11_sconnor', 'p11_unique_name_123', 'p11_mismatch_user', 'p11_nocsrf');")

if __name__ == "__main__":
    unittest.main()
