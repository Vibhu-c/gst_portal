from __future__ import annotations

import hashlib
import hmac
import os
from typing import Optional


def hash_password(password: str, salt: Optional[bytes] = None):
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120000)
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored_hash: str):
    salt_hex, digest_hex = stored_hash.split(":", 1)
    fresh_hash = hash_password(password, bytes.fromhex(salt_hex))
    return hmac.compare_digest(fresh_hash, stored_hash)
