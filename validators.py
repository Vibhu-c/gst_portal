from __future__ import annotations

import re


GSTIN_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
GST_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_checksum(gstin_body: str):
    factor = 2
    total = 0
    for char in reversed(gstin_body):
        code_point = GST_CHARS.index(char)
        digit = factor * code_point
        factor = 1 if factor == 2 else 2
        total += (digit // 36) + (digit % 36)
    return GST_CHARS[(36 - (total % 36)) % 36]


def validate_gstin(gstin: str):
    gstin = (gstin or "").strip().upper()
    if not GSTIN_PATTERN.match(gstin):
        return False, "GSTIN format is invalid."
    if gstin[-1] != gstin_checksum(gstin[:-1]):
        return False, "GSTIN checksum is invalid."
    return True, ""
