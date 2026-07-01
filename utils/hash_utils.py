"""File hashing utilities for book versioning."""

import hashlib


def compute_file_hash(path: str, chunk_size: int = 65536) -> str:
    """Compute SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()
