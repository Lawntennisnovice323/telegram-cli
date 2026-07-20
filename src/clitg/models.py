"""Stable public models used by every clitg command."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from clitg import SCHEMA_VERSION


class OutputFormat(StrEnum):
    """Supported machine-readable output formats."""

    JSON = "json"
    JSONL = "jsonl"


class ErrorCode(StrEnum):
    """Stable error codes paired with process exit codes."""

    INVALID_INPUT = "invalid_input"
    AUTH_REQUIRED = "auth_required"
    PROFILE_ERROR = "profile_error"
    NOT_FOUND = "not_found"
    AMBIGUOUS_PEER = "ambiguous_peer"
    CONFLICT = "conflict"
    CONFIRMATION_REQUIRED = "confirmation_required"
    PERMISSION_DENIED = "permission_denied"
    RATE_LIMITED = "rate_limited"
    TELEGRAM_RPC = "telegram_rpc"
    NETWORK = "network"
    INTERNAL = "internal"


class ErrorInfo(BaseModel):
    """Structured command failure."""

    code: ErrorCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False
    retry_after_seconds: int | None = None


class Meta(BaseModel):
    """Metadata shared by success and error responses."""

    command: str
    profile: str | None = None
    request_id: str
    next_cursor: str | None = None


class Envelope(BaseModel):
    """The JSON response envelope."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    ok: bool
    data: Any = None
    error: ErrorInfo | None = None
    meta: Meta


class JsonlRecord(BaseModel):
    """One JSONL item, summary, or terminal error record."""

    schema_version: str = SCHEMA_VERSION
    record_type: Literal["item", "summary", "error"]
    data: Any = None
    error: ErrorInfo | None = None
    meta: Meta


class Profile(BaseModel):
    """Persisted non-session profile configuration."""

    name: str
    api_id: int
    api_hash: str = Field(repr=False)
    phone: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ProfileView(BaseModel):
    """Safe profile representation."""

    name: str
    api_id: int
    phone: str | None
    created_at: datetime
    is_default: bool


class LoginState(BaseModel):
    """State needed to finish a non-interactive Telegram login."""

    login_id: str
    profile: str
    phone: str
    phone_code_hash: str = Field(repr=False)
    created_at: datetime
    expires_at: datetime


class Confirmation(BaseModel):
    """One-use authorization for a critical raw request."""

    token: str = Field(repr=False)
    profile: str
    action: str
    payload_hash: str
    expires_at: datetime
    used: bool = False


class CommandResult(BaseModel):
    """Internal result returned by services."""

    data: Any
    next_cursor: str | None = None
    items: list[Any] | None = None


class Capability(BaseModel):
    """Support and risk classification for one MTProto method."""

    method: str
    python_class: str
    status: Literal["high-level", "raw-only", "inapplicable-user", "unsupported"]
    risk: Literal["read", "write", "destructive", "critical", "unknown"]
    command: str | None = None
    reason: str | None = None


class CapabilityCatalog(BaseModel):
    """Versioned MTProto capability manifest."""

    schema_version: str = SCHEMA_VERSION
    telethon_version: str
    telegram_layer: int
    generated_at: datetime
    capabilities: list[Capability]
