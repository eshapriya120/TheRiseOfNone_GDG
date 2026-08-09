import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import app, CREDENTIALS_FILE


class LoginCredentialsTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_csv_credentials_allow_login(self):
        response = self.client.post(
            "/login",
            data={"username": "team01", "password": "team123"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/student")

    def test_invalid_credentials_return_error(self):
        response = self.client.post(
            "/login",
            data={"username": "doesnotexist", "password": "wrong"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Invalid Username or Password", response.data)


if __name__ == "__main__":
    unittest.main()
