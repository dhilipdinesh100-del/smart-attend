import unittest
import os
import sqlite3
from pathlib import Path

import config
import database
import security
from app import app

class Phase2StudentManagementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()
        cls.client = app.test_client()

    def test_01_student_registration_validation(self):
        """Test input validation for student registration."""
        # 1. Empty name validation
        valid_name, _, err_name = security.validate_student_name("   ")
        self.assertFalse(valid_name)
        self.assertIn("name is required", err_name.lower())

        # 2. Valid name
        valid_name, clean_name, _ = security.validate_student_name("  Ada Lovelace  ")
        self.assertTrue(valid_name)
        self.assertEqual(clean_name, "Ada Lovelace")

        # 3. Empty roll number validation
        valid_roll, _, err_roll = security.validate_roll_no("   ")
        self.assertFalse(valid_roll)
        self.assertIn("roll number is required", err_roll.lower())

        # 4. Valid roll number
        valid_roll, clean_roll, _ = security.validate_roll_no("  CS-2026-P2-001  ")
        self.assertTrue(valid_roll)
        self.assertEqual(clean_roll, "CS-2026-P2-001")

    def test_02_student_creation_and_duplicate_rejection(self):
        """Test database insertion and unique roll number constraint."""
        roll = "CS-2026-P2-TEST1"
        name = "Charles Babbage"

        # Cleanup in case of previous run
        existing = database.get_student_by_roll(roll)
        if existing:
            database.delete_student(existing["id"])

        success, msg, student_id = database.add_student(name, roll)
        self.assertTrue(success, f"Failed to add student: {msg}")
        self.assertIsNotNone(student_id)

        # Duplicate roll number insertion must fail
        dup_success, dup_msg, _ = database.add_student("Duplicate Student", roll)
        self.assertFalse(dup_success)
        self.assertIn("already exists", dup_msg.lower())

        # Cleanup
        database.delete_student(student_id)

    def test_03_student_retrieval_and_listing(self):
        """Test retrieving student by ID, roll number, and search query."""
        success, _, s_id = database.add_student("Grace Hopper", "CS-2026-P2-GRACE")
        self.assertTrue(success)

        # By ID
        s_by_id = database.get_student_by_id(s_id)
        self.assertIsNotNone(s_by_id)
        self.assertEqual(s_by_id["name"], "Grace Hopper")
        self.assertEqual(s_by_id["roll_no"], "CS-2026-P2-GRACE")

        # By Roll Number
        s_by_roll = database.get_student_by_roll("CS-2026-P2-GRACE")
        self.assertIsNotNone(s_by_roll)
        self.assertEqual(s_by_roll["id"], s_id)

        # Search Query
        results = database.get_all_students(search_query="Grace")
        self.assertTrue(any(st["id"] == s_id for st in results))

        results_roll = database.get_all_students(search_query="P2-GRACE")
        self.assertTrue(any(st["id"] == s_id for st in results_roll))

        # Cleanup
        database.delete_student(s_id)

    def test_04_student_update_and_preservation(self):
        """Test updating student name and roll number while preserving ID and relationships."""
        success, _, s_id = database.add_student("Original Name", "CS-2026-P2-ORIG")
        self.assertTrue(success)

        # Update student name and roll
        up_success, up_msg = database.update_student(s_id, "Updated Name", "CS-2026-P2-UPDT")
        self.assertTrue(up_success, f"Update failed: {up_msg}")

        updated_student = database.get_student_by_id(s_id)
        self.assertEqual(updated_student["id"], s_id)
        self.assertEqual(updated_student["name"], "Updated Name")
        self.assertEqual(updated_student["roll_no"], "CS-2026-P2-UPDT")

        # Cleanup
        database.delete_student(s_id)

    def test_05_student_deletion_and_cascade(self):
        """Test student deletion and verify cascading cleanup."""
        success, _, s_id = database.add_student("Delete Test", "CS-2026-P2-DEL")
        self.assertTrue(success)

        # Insert dummy attendance record for foreign key check
        with database.db_session() as conn:
            conn.execute(
                "INSERT INTO attendance (student_id, method, date, date_time) VALUES (?, 'manual', '2026-08-29', '2026-08-29 10:00:00');",
                (s_id,)
            )
            att_row = conn.execute("SELECT id FROM attendance WHERE student_id = ?;", (s_id,)).fetchone()
            self.assertIsNotNone(att_row)

        # Delete student
        del_success, del_msg = database.delete_student(s_id)
        self.assertTrue(del_success, f"Delete failed: {del_msg}")

        # Verify student is removed
        self.assertIsNone(database.get_student_by_id(s_id))

        # Verify attendance record was CASCADE deleted
        with database.db_session() as conn:
            att_after = conn.execute("SELECT id FROM attendance WHERE student_id = ?;", (s_id,)).fetchone()
            self.assertIsNone(att_after)

    def test_06_unauthenticated_access_redirection(self):
        """Verify unauthenticated requests to student endpoints redirect to /login."""
        endpoints = [
            "/students",
            "/students/register",
            "/students/1"
        ]
        for ep in endpoints:
            resp = self.client.get(ep)
            self.assertEqual(resp.status_code, 302, f"Endpoint {ep} did not redirect")
            self.assertIn("/login", resp.headers.get("Location", ""))

        post_endpoints = [
            "/students/register",
            "/students/edit/1",
            "/students/delete/1"
        ]
        for ep in post_endpoints:
            resp = self.client.post(ep, data={"name": "Test", "roll_no": "TEST"})
            self.assertEqual(resp.status_code, 302, f"POST Endpoint {ep} did not redirect")
            self.assertIn("/login", resp.headers.get("Location", ""))

    def test_07_authenticated_student_web_flow(self):
        """Verify full web flow: add student, view list, view details, edit student, delete student."""
        csrf_tok = "test_csrf_token_p2"
        # Set authenticated session
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "admin"
            sess["role"] = "admin"
            sess["_csrf_token"] = csrf_tok

        # 1. GET /students/register opens
        resp_form = self.client.get("/students/register")
        self.assertEqual(resp_form.status_code, 200)
        self.assertIn(b"New Student Enrollment", resp_form.data)

        # 2. POST /students/register creates student and redirects to profile
        resp_post = self.client.post("/students/register", data={
            "name": "E2E Web Student",
            "roll_no": "CS-2026-P2-WEB",
            "csrf_token": csrf_tok
        }, follow_redirects=False)
        self.assertEqual(resp_post.status_code, 302)
        redirect_url = resp_post.headers.get("Location", "")
        self.assertIn("/students/", redirect_url)

        # Extract student id from redirect URL
        created_sid = int(redirect_url.split("/")[-1])

        # 3. GET /students/<id> profile view
        resp_profile = self.client.get(f"/students/{created_sid}")
        self.assertEqual(resp_profile.status_code, 200)
        self.assertIn(b"E2E Web Student", resp_profile.data)
        self.assertIn(b"CS-2026-P2-WEB", resp_profile.data)

        # 4. GET /students list contains newly created student
        resp_list = self.client.get("/students")
        self.assertEqual(resp_list.status_code, 200)
        self.assertIn(b"E2E Web Student", resp_list.data)
        self.assertIn(b"CS-2026-P2-WEB", resp_list.data)

        # 5. POST /students/edit/<id> updates details
        resp_edit = self.client.post(f"/students/edit/{created_sid}", data={
            "name": "E2E Web Student (Renamed)",
            "roll_no": "CS-2026-P2-WEB-RENAMED",
            "csrf_token": csrf_tok
        }, follow_redirects=False)
        self.assertEqual(resp_edit.status_code, 302)

        # Verify update in profile
        resp_profile_updated = self.client.get(f"/students/{created_sid}")
        self.assertEqual(resp_profile_updated.status_code, 200)
        self.assertIn(b"E2E Web Student (Renamed)", resp_profile_updated.data)
        self.assertIn(b"CS-2026-P2-WEB-RENAMED", resp_profile_updated.data)

        # 6. POST /students/delete/<id> deletes student
        resp_del = self.client.post(
            f"/students/delete/{created_sid}",
            data={"csrf_token": csrf_tok},
            follow_redirects=False
        )
        self.assertEqual(resp_del.status_code, 302)

        # Verify profile is now redirect
        resp_profile_gone = self.client.get(f"/students/{created_sid}", follow_redirects=False)
        self.assertEqual(resp_profile_gone.status_code, 302)

if __name__ == "__main__":
    unittest.main()
