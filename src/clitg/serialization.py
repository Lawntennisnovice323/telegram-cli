"""Safe JSON, cursor, hashing, and TL-object serialization."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

_JS_SAFE_INTEGER = 9_007_199_254_740_991
_SENSITIVE_KEYS = {
    "access_hash",
    "api_hash",
    "auth_key",
    "autologin_token",
    "login_code",
    "password",
    "phone_code_hash",
    "session",
    "session_string",
}


def redact(value: Any) -> Any:
    """Recursively redact credential-bearing fields."""

    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).lower() in _SENSITIVE_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(item) for item in value]
    return value


def to_jsonable(value: Any, *, raw: bool = False, field_name: str | None = None) -> Any:
    """Convert Pydantic, Telethon, and Python values to stable JSON values."""

    if isinstance(value, BaseModel):
        return to_jsonable(value.model_dump(mode="python"), raw=raw)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return to_jsonable(value.to_dict(), raw=True)
    if isinstance(value, dict):
        return {
            str(key): to_jsonable(item, raw=raw, field_name=str(key)) for key, item in value.items()
        }
    if isinstance(value, list | tuple | set):
        return [to_jsonable(item, raw=raw, field_name=field_name) for item in value]
    if isinstance(value, bytes):
        return {"$bytes": base64.b64encode(value).decode("ascii")}
    if isinstance(value, datetime):
        normalized = value if value.tzinfo else value.replace(tzinfo=UTC)
        return normalized.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, int) and not isinstance(value, bool):
        is_identifier = bool(
            field_name
            and field_name != "api_id"
            and (field_name == "id" or field_name.endswith("_id"))
        )
        if is_identifier or abs(value) > _JS_SAFE_INTEGER:
            return str(value)
    if value is not None and not isinstance(value, str | int | float | bool):
        return str(value)
    return value


def json_dumps(value: Any) -> str:
    """Serialize a value deterministically and without leaking secrets."""

    return json.dumps(redact(to_jsonable(value)), ensure_ascii=False, separators=(",", ":"))


def payload_hash(value: Any) -> str:
    """Return a stable SHA-256 hash for an operation payload."""

    canonical = json.dumps(to_jsonable(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def encode_cursor(value: dict[str, Any]) -> str:
    """Encode a versioned opaque pagination cursor."""

    raw = json.dumps({"v": 1, **value}, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(value: str | None) -> dict[str, Any]:
    """Decode and validate an opaque pagination cursor."""

    if value is None:
        return {}
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded).decode())
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid cursor") from exc
    if not isinstance(decoded, dict) or decoded.pop("v", None) != 1:
        raise ValueError("Unsupported cursor")
    return decoded
