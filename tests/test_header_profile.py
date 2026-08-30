import unittest
import re
from app import app
import database

class DashboardTopHeaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()
        cls.client = app.test_client()

        # Clean old test user
        with database.db_session() as conn:
            conn.execute("DELETE FROM users WHERE username = 'header_test_user';")

        # Create a test admin user with distinct Full Name, Username, and Email
        ok, msg, uid = database.create_admin_user(
            full_name="Professor Charles Xavier",
            username="header_test_user",
            email="charles.xavier@mutants.edu",
            password="XavierPassword123"
        )
        cls.test_user_id = uid

    def test_01_unauthenticated_dashboard_redirects_to_login(self):
        """Verify dashboard is protected and redirects unauthenticated users to /login."""
        unauth_client = app.test_client()
        resp = unauth_client.get("/dashboard")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers.get("Location", ""))

    def test_02_authenticated_user_full_name_appears_in_top_header(self):
        """Verify authenticated user's Full Name appears in the top-right header."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.test_user_id
            sess["username"] = "header_test_user"
            sess["role"] = "admin"

        resp = self.client.get("/dashboard")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")

        # 1. Full name is present in header
        self.assertIn("Professor Charles Xavier", html)
        self.assertIn("headerProfile", html)
        self.assertIn("headerProfileName", html)
        self.assertIn("👤", html)

    def test_03_email_does_not_appear_in_top_header(self):
        """Verify user email is NOT exposed in the top-right header."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.test_user_id
            sess["username"] = "header_test_user"
            sess["role"] = "admin"

        resp = self.client.get("/dashboard")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")

        # Extract top-header container HTML
        header_match = re.search(r'<header class="top-header">(.*?)</header>', html, re.DOTALL)
        self.assertIsNotNone(header_match, "top-header not found in rendered HTML")
        header_html = header_match.group(1)

        # Email must NOT appear in header
        self.assertNotIn("charles.xavier@mutants.edu", header_html)
        self.assertNotIn("@", header_html)

    def test_04_username_does_not_appear_in_top_header(self):
        """Verify username is NOT exposed in the top-right header."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.test_user_id
            sess["username"] = "header_test_user"
            sess["role"] = "admin"

        resp = self.client.get("/dashboard")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")

        # Extract top-header container HTML
        header_match = re.search(r'<header class="top-header">(.*?)</header>', html, re.DOTALL)
        self.assertIsNotNone(header_match)
        header_html = header_match.group(1)

        # Username must NOT appear in header
        self.assertNotIn("header_test_user", header_html)

    def test_05_live_time_and_logout_present_in_top_header(self):
        """Verify live time clock and logout button are present in the top-right header."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.test_user_id
            sess["username"] = "header_test_user"
            sess["role"] = "admin"

        resp = self.client.get("/dashboard")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")

        # Extract top-header container HTML
        header_match = re.search(r'<header class="top-header">(.*?)</header>', html, re.DOTALL)
        self.assertIsNotNone(header_match)
        header_html = header_match.group(1)

        # Live time element present
        self.assertIn('id="live-clock-time"', header_html)
        self.assertIn("live-clock", header_html)

        # Logout button present
        self.assertIn('href="/logout"', header_html)
        self.assertIn("Logout", header_html)
        self.assertIn("headerLogoutBtn", header_html)

    def test_06_three_items_in_header_actions(self):
        """Verify header-actions contains the three horizontal components: logged-user, server-clock, header-logout."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.test_user_id
            sess["username"] = "header_test_user"
            sess["role"] = "admin"

        resp = self.client.get("/dashboard")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")

        # Verify classes are present
        self.assertIn("dashboard-header-right", html)
        self.assertIn("logged-user", html)
        self.assertIn("user-icon", html)
        self.assertIn("user-name", html)
        self.assertIn("server-clock", html)
        self.assertIn("header-logout", html)
        self.assertIn("Professor Charles Xavier", html)
        self.assertIn("Logout", html)

    @classmethod
    def tearDownClass(cls):
        with database.db_session() as conn:
            conn.execute("DELETE FROM users WHERE username = 'header_test_user';")

if __name__ == "__main__":
    unittest.main()
