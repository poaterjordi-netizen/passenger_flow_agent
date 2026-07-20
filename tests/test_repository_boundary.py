import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_TRACKED_NAMES = {".env", "auth.json", "credentials.json"}


class RepositoryBoundaryTests(unittest.TestCase):
    def test_forbidden_sensitive_carrier_names_are_absent(self) -> None:
        found = {
            path.name
            for path in ROOT.rglob("*")
            if path.is_file() and ".git" not in path.parts and path.name in FORBIDDEN_TRACKED_NAMES
        }
        self.assertEqual(found, set())

    def test_synthetic_fixture_declares_synthetic_scope(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8").lower().replace("*", "")
        self.assertIn("synthetic", readme)
        self.assertIn("does not", readme)

    def test_example_environment_keeps_database_password_empty(self) -> None:
        lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        password_lines = [line for line in lines if line.startswith("METRO_DB_PASSWORD=")]
        self.assertEqual(password_lines, ["METRO_DB_PASSWORD="])


if __name__ == "__main__":
    unittest.main()
