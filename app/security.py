"""Security primitives: tokens, hashing, filename sanitising, upload rules."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import unicodedata
import uuid
from pathlib import Path

#: Extensions accepted for uploaded snapshots. Deliberately an allowlist.
#: Anything that a browser could be talked into executing (html, htm, xhtml,
#: svg, js, mjs, xml, swf, ...) is absent on purpose.
ALLOWED_EXTENSIONS: dict[str, str] = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".json": "application/json",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

#: Media types we are willing to render inline in the browser. Never text/html,
#: never image/svg+xml — both can carry script.
INLINE_MEDIA_TYPES: frozenset[str] = frozenset(
    {"image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf"}
)

_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_DOT_RUN = re.compile(r"\.{2,}")

MAX_FILENAME_LENGTH = 120


def new_id() -> str:
    """Random, non-sequential primary key."""
    return uuid.uuid4().hex


def generate_review_token(n_bytes: int = 32) -> str:
    """Return a URL-safe token backed by ``n_bytes`` of CSPRNG entropy.

    ``secrets.token_urlsafe`` reads from the OS CSPRNG. 32 bytes == 256 bits,
    which is not enumerable by any practical attacker.
    """
    if n_bytes < 16:
        raise ValueError("review tokens need at least 16 bytes of entropy")
    return secrets.token_urlsafe(n_bytes)


def tokens_equal(a: str, b: str) -> bool:
    """Constant-time token comparison."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_text(text: str) -> str:
    """Hash text exactly as it is stored: UTF-8, no re-encoding surprises."""
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sanitize_filename(raw: str | None, *, fallback: str = "snapshot") -> str:
    """Reduce an arbitrary client-supplied name to a safe display name.

    Strips directory components (POSIX *and* Windows separators), NFKD-folds
    unicode, keeps only ``[A-Za-z0-9._-]``, collapses dot runs so ``..`` can
    never survive, and refuses leading dots. The result is used for display and
    for the download ``Content-Disposition`` only — never to build a path.
    """
    if not raw:
        return fallback

    name = raw.replace("\\", "/").split("/")[-1]
    name = name.replace("\x00", "")
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    name = _SAFE_CHARS.sub("_", name)
    name = _DOT_RUN.sub(".", name).strip("._-")

    if not name:
        return fallback

    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    stem = stem[: MAX_FILENAME_LENGTH - len(ext) - 1] or fallback
    return f"{stem}.{ext}" if ext else stem


def extension_of(filename: str) -> str:
    _, dot, ext = filename.rpartition(".")
    return f".{ext.lower()}" if dot else ""


def is_allowed_extension(filename: str) -> bool:
    return extension_of(filename) in ALLOWED_EXTENSIONS


def media_type_for(filename: str) -> str:
    """Media type we will serve the file with — derived from our allowlist.

    The client-supplied ``Content-Type`` is ignored entirely, so a file cannot
    talk us into serving it as ``text/html``.
    """
    return ALLOWED_EXTENSIONS.get(extension_of(filename), "application/octet-stream")


def resolve_within(base: Path, candidate: Path) -> Path:
    """Return ``candidate`` resolved, or raise if it escapes ``base``.

    A belt-and-braces check: stored names are generated from the approval id, so
    traversal is already impossible by construction.
    """
    base_resolved = base.resolve()
    if candidate.is_absolute():
        target = candidate.resolve()
    else:
        target = (base_resolved / candidate).resolve()
    if base_resolved != target and base_resolved not in target.parents:
        raise ValueError(f"path escapes storage directory: {candidate}")
    return target


def sign_session_value(secret: str, value: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256)
    return f"{value}.{mac.hexdigest()}"


def verify_session_value(secret: str, signed: str) -> str | None:
    value, _, mac = signed.rpartition(".")
    if not value or not mac:
        return None
    expected = hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256)
    if hmac.compare_digest(expected.hexdigest(), mac):
        return value
    return None


def random_suffix(n: int = 8) -> str:
    return os.urandom(n).hex()
