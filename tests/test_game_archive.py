import base64
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from game_archive import encrypt, decrypt


class GameArchiveTests(unittest.TestCase):
    def setUp(self):
        self.key = base64.urlsafe_b64encode(bytes(range(32))).decode()

    def test_round_trip_and_unique_nonce(self):
        data = b"game archive bytes"
        encrypted = encrypt(data, self.key)
        self.assertEqual(decrypt(encrypted, self.key), data)
        self.assertNotEqual(encrypted, encrypt(data, self.key))

    def test_wrong_key_and_tampering_fail(self):
        encrypted = encrypt(b"game", self.key)
        wrong_key = base64.urlsafe_b64encode(b"x" * 32).decode()
        with self.assertRaisesRegex(ValueError, "authentication failed"):
            decrypt(encrypted, wrong_key)
        damaged = encrypted[:-1] + bytes([encrypted[-1] ^ 1])
        with self.assertRaisesRegex(ValueError, "authentication failed"):
            decrypt(damaged, self.key)

    def test_invalid_key_and_archive_fail(self):
        for key in ("invalid", "", base64.urlsafe_b64encode(b"short").decode()):
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, "32-byte key"):
                    encrypt(b"game", key)
        with self.assertRaisesRegex(ValueError, "Invalid encrypted"):
            decrypt(b"not encrypted", self.key)
