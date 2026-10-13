"""Encrypt the game ZIP for version control and authenticate it before use."""

import argparse
import base64
import binascii
import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"BALATRO-GAME\x01"


def decode_key(value):
    try:
        key = base64.b64decode(value.strip(), altchars=b"-_", validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("BALATRO_GAME_KEY must be a base64-encoded 32-byte key") from None
    if len(key) != 32:
        raise ValueError("BALATRO_GAME_KEY must be a base64-encoded 32-byte key")
    return key


def encrypt(data, key):
    nonce = os.urandom(12)
    return MAGIC + nonce + AESGCM(decode_key(key)).encrypt(nonce, data, MAGIC)


def decrypt(data, key):
    if not data.startswith(MAGIC) or len(data) < len(MAGIC) + 28:
        raise ValueError("Invalid encrypted game archive")
    nonce = data[len(MAGIC) : len(MAGIC) + 12]
    try:
        return AESGCM(decode_key(key)).decrypt(nonce, data[len(MAGIC) + 12 :], MAGIC)
    except InvalidTag:
        raise ValueError("Game archive authentication failed: wrong key or damaged archive") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    args = parser.parse_args()
    # Check the game before generating a key or replacing the encrypted file.
    from builder import game_files
    data = args.input.read_bytes()
    game_files(data)
    if args.key_file.exists():
        key = args.key_file.read_text().strip()
    else:
        key = base64.urlsafe_b64encode(AESGCM.generate_key(bit_length=256)).decode()
        args.key_file.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(args.key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as file:
            file.write(key + "\n")
    encrypted = encrypt(data, key)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encrypted)
    print("Encrypted game archive created; key saved separately (not printed).")


if __name__ == "__main__":
    main()
