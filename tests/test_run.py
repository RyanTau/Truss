import tempfile
import unittest
from pathlib import Path

from run import engine_token


class TokenTests(unittest.TestCase):
    def test_generated_token_is_persisted_and_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "truss_engine_token"
            first, created = engine_token({}, path)
            second, reused = engine_token({}, path)
        self.assertTrue(created)
        self.assertFalse(reused)
        self.assertGreaterEqual(len(first), 24)
        self.assertEqual(first, second)

    def test_explicit_token_is_not_written_or_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "truss_engine_token"
            token, created = engine_token({"api_token": "configured-token-at-least-24-long"}, path)
            self.assertFalse(path.exists())
        self.assertEqual(token, "configured-token-at-least-24-long")
        self.assertFalse(created)
