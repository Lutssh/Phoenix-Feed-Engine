import os
from pathlib import Path

# SEC-04: Prevent path traversal by validating media paths
# Allow /tmp and everything inside the current working directory /app
ALLOWED_MEDIA_DIRS = ["/tmp", "/app", "/data/media", "/teamspace"]

def validate_media_path(path: str) -> str:
    """Raise ValueError if path is outside allowed directories."""
    resolved = str(Path(path).resolve())
    if not any(resolved.startswith(d) for d in ALLOWED_MEDIA_DIRS):
        raise ValueError(f"Path {path!r} is outside allowed media directories")
    if not os.path.exists(resolved):
        raise FileNotFoundError(f"Media file not found: {resolved}")
    return resolved
