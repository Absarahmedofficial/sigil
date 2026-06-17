"""SHA-256 hashing utilities used for cache keys and integrity checks.

The stripper pipeline writes per-target state to
`.pyglimmer_cache/<sha256-of-target>/state.json` so a crash at stage 3 doesn't
waste stages 1 and 2. This module is the source of truth for those cache keys.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_of_file(path: Path, chunk_size: int = 65536) -> str:
    """Compute the SHA-256 hex digest of a file's contents.

    Args:
        path: File to hash. Must exist and be readable.
        chunk_size: Read buffer size in bytes. 64 KiB is a good default that
            balances syscall overhead vs memory usage.

    Returns:
        Lowercase hex digest, 64 characters.

    Raises:
        FileNotFoundError: If `path` doesn't exist.
        OSError: If `path` is not readable.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_of_bytes(data: bytes) -> str:
    """Compute the SHA-256 hex digest of an in-memory bytes blob."""
    return hashlib.sha256(data).hexdigest()
