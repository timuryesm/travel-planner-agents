"""
Password hashing — the only file that knows about bcrypt.

Two functions, no project imports, no database. Kept separate from jwt.py
so password logic can be tested and swapped independently of token logic.

Uses the `bcrypt` package directly rather than passlib. passlib[bcrypt]
has a known incompatibility with bcrypt >= 4.0 (passlib is unmaintained);
this avoids the version-pinning problem entirely.

Requires: bcrypt
    pip install bcrypt
"""
from __future__ import annotations

import bcrypt


def hash_password(plain: str) -> str:
    """
    Return a bcrypt hash of `plain`.

    The hash is safe to store in the database. Each call produces a
    different value (bcrypt embeds a random salt) even for the same input.
    """
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """
    Return True if `plain` matches the stored `hashed` value.

    Timing-safe: bcrypt.checkpw uses a constant-time comparison internally
    so the return value does not leak information through response time.
    """
    return bcrypt.checkpw(plain.encode(), hashed.encode())