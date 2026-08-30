import unittest
import io
import csv
import shutil
from datetime import datetime

from app import app
import database
import qr_engine
import face_engine
from config import QR_DIR, FACES_DIR

class Phase12StudentIDHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()
        cls.client = app.test_client()

        # Clean existing test data from this test prefix
        with database.db_session() as conn:
            conn.execute("DELETE FROM attendance WHERE student_id IN (SELECT id FROM students WHERE roll_no LIKE 'P12-%');")
            conn.execute("DELETE FROM students WHERE roll_no LIKE 'P12-%';")
            conn.execute("DELETE FROM student_id_history WHERE roll_no LIKE 'P12-%';")

    def test_01_first_student_receives_random_numeric_id(self):
        """Verify first registered student gets a 6-digit random numeric student ID code."""
        ok, msg, sid = database.add_student("Alice Test", "P12-ROLL-A")
        self.assertTrue(ok)
        self.assertIsNotNone(sid)
        
        student = database.get_student_by_id(sid)
        self.assertIsNotNone(student)
        self.assertIn("student_id_code", student)
        code = student["student_id_code"]
        self.assertIsInstance(code, int)
        self.assertGreaterEqual(code, 100000)
        self.assertLessEqual(code, 999999)

    def test_02_active_student_keeps_same_id(self):
        """Verify active student retains their assigned ID across repeated queries."""
        student1 = database.get_student_by_roll("P12-ROLL-A")
        code1 = student1["student_id_code"]
        student2 = database.get_student_by_roll("P12-ROLL-A")
        self.assertEqual(code1, student2["student_id_code"])

    def test_03_registering_another_student_preserves_existing_ids(self):
        """Verify registering Bob and Charlie does not change Alice's ID."""
        alice_before = database.get_student_by_roll("P12-ROLL-A")["student_id_code"]
        
        ok_b, _, sid_b = database.add_student("Bob Test", "P12-ROLL-B")
        self.assertTrue(ok_b)
        ok_c, _, sid_c = database.add_student("Charlie Test", "P12-ROLL-C")
        self.assertTrue(ok_c)
        
        alice_after = database.get_student_by_roll("P12-ROLL-A")["student_id_code"]
        bob = database.get_student_by_roll("P12-ROLL-B")["student_id_code"]
        charlie = database.get_student_by_roll("P12-ROLL-C")["student_id_code"]
        
        self.assertEqual(alice_before, alice_after)
        self.assertNotEqual(alice_after, bob)
        self.assertNotEqual(bob, charlie)
        self.assertNotEqual(alice_after, charlie)

    def test_04_active_ids_cannot_be_reassigned(self):
        """Verify active student IDs are reserved and never assigned to new students."""
        active_codes = {s["student_id_code"] for s in database.get_all_students() if s.get("student_id_code")}
        ok_d, _, sid_d = database.add_student("Diana Test", "P12-ROLL-D")
        self.assertTrue(ok_d)
        diana_code = database.get_student_by_id(sid_d)["student_id_code"]
        self.assertNotIn(diana_code, active_codes)

    def test_05_delete_student_a_releases_id(self):
        """Verify deleting Student A marks their ID as RELEASED in student_id_history."""
        alice = database.get_student_by_roll("P12-ROLL-A")
        alice_id = alice["id"]
        alice_code = alice["student_id_code"]

        ok, msg = database.delete_student(alice_id)
        self.assertTrue(ok)

        # Alice should no longer be active
        self.assertIsNone(database.get_student_by_id(alice_id))

        # Check history has RELEASED status for Alice's code
        history = database.get_student_id_history()
        released_entry = [h for h in history if h["student_id_code"] == alice_code and h["status"] == "RELEASED"]
        self.assertEqual(len(released_entry), 1)
        self.assertEqual(released_entry[0]["previous_owner"], "Alice Test")

    def test_06_new_student_e_receives_alice_released_id(self):
        """Verify new student registration reuses the released ID code."""
        # Previous released ID belongs to Alice
        history = database.get_student_id_history()
        released_code = [h["student_id_code"] for h in history if h["status"] == "RELEASED"][0]

        ok, msg, sid_e = database.add_student("Edward Test", "P12-ROLL-E")
        self.assertTrue(ok)

        edward = database.get_student_by_id(sid_e)
        self.assertEqual(edward["student_id_code"], released_code)

    def test_07_multiple_released_ids_assigned_fifo(self):
        """Verify multiple released IDs are reassigned in FIFO order (oldest released first)."""
        # Delete Bob and Charlie
        bob = database.get_student_by_roll("P12-ROLL-B")
        bob_id = bob["id"]
        bob_code = bob["student_id_code"]
        database.delete_student(bob_id)

        charlie = database.get_student_by_roll("P12-ROLL-C")
        charlie_id = charlie["id"]
        charlie_code = charlie["student_id_code"]
        database.delete_student(charlie_id)

        # Register Fiona -> should get Bob's code (first released)
        ok_f, _, sid_f = database.add_student("Fiona Test", "P12-ROLL-F")
        self.assertTrue(ok_f)
        fiona = database.get_student_by_id(sid_f)
        self.assertEqual(fiona["student_id_code"], bob_code)

        # Register George -> should get Charlie's code (second released)
        ok_g, _, sid_g = database.add_student("George Test", "P12-ROLL-G")
        self.assertTrue(ok_g)
        george = database.get_student_by_id(sid_g)
        self.assertEqual(george["student_id_code"], charlie_code)

    def test_08_id_history_survives_deletion_with_provenance(self):
        """Verify ID history persists deletion with previous and current owners."""
        history = database.get_student_id_history()
        # Find entries for Bob's code
        bob_fiona_entries = [h for h in history if h["roll_no"] in ("P12-ROLL-B", "P12-ROLL-F")]
        self.assertGreaterEqual(len(bob_fiona_entries), 2)
        
        # Verify Fiona has previous_owner = Bob Test and current_owner = Fiona Test
        fiona_entry = [h for h in bob_fiona_entries if h["roll_no"] == "P12-ROLL-F"][0]
        self.assertEqual(fiona_entry["event"], "REASSIGNED")
        self.assertEqual(fiona_entry["previous_owner"], "Bob Test")
        self.assertEqual(fiona_entry["current_owner"], "Fiona Test")

    def test_09_attendance_safety_immutable_internal_binding(self):
        """Verify attendance records belong to internal student ID, never transferring across reuse."""
        # Create Student X, mark attendance
        ok_x, _, sid_x = database.add_student("User X", "P12-ROLL-X")
        x_code = database.get_student_by_id(sid_x)["student_id_code"]
        ok_att, _, _ = database.mark_attendance(sid_x, "face", "2026-08-01 10:00:00")
        self.assertTrue(ok_att)

        # Delete User X
        database.delete_student(sid_x)

        # User Y receives User X's student_id_code
        ok_y, _, sid_y = database.add_student("User Y", "P12-ROLL-Y")
        self.assertNotEqual(sid_x, sid_y) # Internal IDs are distinct
        user_y = database.get_student_by_id(sid_y)
        self.assertEqual(user_y["student_id_code"], x_code)

        # User Y should have 0 attendance records
        y_att = database.get_monthly_attendance(student_id=sid_y)
        self.assertEqual(y_att["student_data"]["present_days"], 0)

    def test_10_qr_safety_on_id_reuse(self):
        """Verify old QR credential cannot mark attendance for the new recipient of a recycled ID."""
        # User Z
        ok_z, _, sid_z = database.add_student("User Z", "P12-ROLL-Z")
        z_code = database.get_student_by_id(sid_z)["student_id_code"]
        qr_engine.generate_qr_code(sid_z)
        z_payload = qr_engine.generate_payload(sid_z)

        # Delete User Z
        database.delete_student(sid_z)

        # User W gets recycled ID code
        ok_w, _, sid_w = database.add_student("User W", "P12-ROLL-W")
        user_w = database.get_student_by_id(sid_w)
        self.assertEqual(user_w["student_id_code"], z_code)
        self.assertNotEqual(sid_z, sid_w)

        # User W gets distinct QR payload
        qr_engine.generate_qr_code(sid_w)
        w_payload = qr_engine.generate_payload(sid_w)
        self.assertNotEqual(z_payload, w_payload)

        # Validating old Z payload resolves to sid_z (which is deleted), so scanning Z's QR fails for W
        is_valid, extracted_id, _ = qr_engine.validate_payload(z_payload)
        self.assertTrue(is_valid)
        self.assertEqual(extracted_id, sid_z)
        self.assertIsNone(database.get_student_by_id(extracted_id)) # Deleted!

    def test_11_csv_export_includes_full_ownership_chain(self):
        """Verify GET /students/id-history/export/csv includes complete history with previous/current owners."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "admin"
            sess["role"] = "admin"

        resp = self.client.get("/students/id-history/export/csv")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, "text/csv")
        
        csv_text = resp.data.decode("utf-8")
        reader = csv.reader(io.StringIO(csv_text))
        rows = list(reader)
        header = rows[0]
        self.assertEqual(header, [
            "Student ID",
            "Student Name",
            "Event",
            "Assigned Date",
            "Released Date",
            "Status",
            "Previous Owner",
            "Current Owner"
        ])
        # Verify content exists
        self.assertGreater(len(rows), 1)

    def test_12_repeated_reuse_preserves_full_chain(self):
        """Verify chain: Owner 1 -> Deleted -> Owner 2 -> Deleted -> Owner 3 preserves history."""
        # 1. Owner 1
        ok_1, _, sid_1 = database.add_student("Chain Owner 1", "P12-CHAIN-1")
        code = database.get_student_by_id(sid_1)["student_id_code"]
        database.delete_student(sid_1)

        # 2. Owner 2
        ok_2, _, sid_2 = database.add_student("Chain Owner 2", "P12-CHAIN-2")
        self.assertEqual(database.get_student_by_id(sid_2)["student_id_code"], code)
        database.delete_student(sid_2)

        # 3. Owner 3
        ok_3, _, sid_3 = database.add_student("Chain Owner 3", "P12-CHAIN-3")
        self.assertEqual(database.get_student_by_id(sid_3)["student_id_code"], code)

        # Inspect history
        history = database.get_student_id_history()
        chain = [h for h in history if h["student_id_code"] == code]
        self.assertGreaterEqual(len(chain), 3)

    @classmethod
    def tearDownClass(cls):
        # Clean up test records
        with database.db_session() as conn:
            conn.execute("DELETE FROM attendance WHERE student_id IN (SELECT id FROM students WHERE roll_no LIKE 'P12-%');")
            conn.execute("DELETE FROM students WHERE roll_no LIKE 'P12-%';")
            conn.execute("DELETE FROM student_id_history WHERE roll_no LIKE 'P12-%';")

if __name__ == "__main__":
    unittest.main()
