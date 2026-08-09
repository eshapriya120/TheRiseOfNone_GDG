import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import evaluate_drive_eligibility, process_google_form_payload


class DriveEligibilityTests(unittest.TestCase):
    def test_first_time_student_is_eligible_by_default(self):
        student = {"username": "cse_student1", "status": "In Process"}
        result = evaluate_drive_eligibility(student, None)
        self.assertTrue(result["eligible"])
        self.assertEqual(result["decision"], "eligible_default")

    def test_feedback_missing_and_not_placed_requires_permission(self):
        student = {"username": "cse_student2", "status": "In Process"}
        previous = {
            "student_username": "cse_student2",
            "attendance": "no",
            "feedback_submitted": "no",
            "placement_status": "not_placed",
        }
        result = evaluate_drive_eligibility(student, previous)
        self.assertFalse(result["eligible"])
        self.assertTrue(result["requires_permission"])

    def test_feedback_complete_and_not_placed_is_eligible(self):
        student = {"username": "cse_student3", "status": "In Process"}
        previous = {
            "student_username": "cse_student3",
            "attendance": "yes",
            "feedback_submitted": "yes",
            "placement_status": "not_placed",
        }
        result = evaluate_drive_eligibility(student, previous)
        self.assertTrue(result["eligible"])
        self.assertEqual(result["decision"], "eligible")

    def test_google_form_payload_is_processed(self):
        result = process_google_form_payload({
            "student_username": "cse_student1",
            "drive_name": "Tech Drive 2026",
            "attendance": "yes",
            "feedback_submitted": "yes",
            "placement_status": "not_placed",
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["entry"]["student_username"], "cse_student1")


if __name__ == "__main__":
    unittest.main()
