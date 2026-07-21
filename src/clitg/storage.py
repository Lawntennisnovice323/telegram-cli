"""Local profile and auxiliary state storage."""

from __future__ import annotations

import builtins
import json
import os
import re
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from filelock import FileLock
from platformdirs import user_config_path, user_data_path

from clitg.errors import ClitgError
from clitg.models import Confirmation, ErrorCode, LoginState, Profile, ProfileView
from clitg.serialization import payload_hash, to_jsonable

_PROFILE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def _secure_write(path: Path, content: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(content, encoding="utf-8")
    if os.name == "posix":
        temporary.chmod(0o600)
    temporary.replace(path)


class Paths:
    """Resolve platform-appropriate clitg paths."""

    def __init__(self, config_dir: Path | None = None, data_dir: Path | None = None) -> None:
        self.config_dir = config_dir or user_config_path("clitg", ensure_exists=True)
        self.data_dir = data_dir or user_data_path("clitg", ensure_exists=True)

    @property
    def profiles_file(self) -> Path:
        """Return the profile configuration path."""

        return self.config_dir / "profiles.json"

    @property
    def state_file(self) -> Path:
        """Return the auxiliary SQLite state path."""

        return self.data_dir / "state.sqlite3"

    def session_file(self, profile: str) -> Path:
        """Return a profile's Telethon session path."""

        path = self.data_dir / "profiles" / profile / "telegram"
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        return path

    def export_dir(self, profile: str) -> Path:
        """Return the default parent for resumable exports."""

        return self.data_dir / "profiles" / profile / "exports"

    def profile_lock(self, profile: str) -> FileLock:
        """Return a cross-platform session lock."""

        return FileLock(str(self.data_dir / "profiles" / profile / ".lock"), timeout=0)


class ProfileStore:
    """Persist profile metadata without exposing secrets."""

    def __init__(self, paths: Paths) -> None:
        self.paths = paths

    def _load(self) -> dict[str, Any]:
        if not self.paths.profiles_file.exists():
            return {"default": None, "profiles": {}}
        try:
            value = json.loads(self.paths.profiles_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ClitgError(ErrorCode.PROFILE_ERROR, "Profile configuration is invalid") from exc
        if not isinstance(value, dict) or not isinstance(value.get("profiles"), dict):
            raise ClitgError(ErrorCode.PROFILE_ERROR, "Profile configuration is invalid")
        return value

    def _save(self, value: dict[str, Any]) -> None:
        _secure_write(self.paths.profiles_file, json.dumps(to_jsonable(value), indent=2) + "\n")

    @staticmethod
    def validate_name(name: str) -> str:
        """Validate and normalize a profile name."""

        normalized = name.lower()
        if not _PROFILE_PATTERN.fullmatch(normalized):
            raise ClitgError(
                ErrorCode.INVALID_INPUT,
                "Profile names must be lowercase slugs of at most 63 characters",
            )
        return normalized

    def create(self, profile: Profile, *, make_default: bool = False) -> ProfileView:
        """Create a profile and optionally select it as default."""

        name = self.validate_name(profile.name)
        value = self._load()
        if name in value["profiles"]:
            raise ClitgError(ErrorCode.CONFLICT, f"Profile '{name}' already exists")
        profile.name = name
        value["profiles"][name] = profile.model_dump(mode="json")
        if make_default or value["default"] is None:
            value["default"] = name
        self._save(value)
        return self.view(profile, value["default"] == name)

    def resolve(self, requested: str | None = None) -> Profile:
        """Resolve an explicit, environment, or default profile."""

        value = self._load()
        name = requested or os.getenv("CLITG_PROFILE") or value["default"]
        if not name:
            raise ClitgError(ErrorCode.PROFILE_ERROR, "No profile was selected")
        raw = value["profiles"].get(name)
        if raw is None:
            raise ClitgError(ErrorCode.PROFILE_ERROR, f"Profile '{name}' does not exist")
        return Profile.model_validate(raw)

    def list(self) -> builtins.list[ProfileView]:
        """List profiles without credential material."""

        value = self._load()
        return [
            self.view(Profile.model_validate(raw), name == value["default"])
            for name, raw in sorted(value["profiles"].items())
        ]

    def get(self, name: str) -> ProfileView:
        """Get one safe profile view."""

        value = self._load()
        raw = value["profiles"].get(name)
        if raw is None:
            raise ClitgError(ErrorCode.NOT_FOUND, f"Profile '{name}' does not exist")
        return self.view(Profile.model_validate(raw), name == value["default"])

    def set_default(self, name: str) -> ProfileView:
        """Select the default profile."""

        value = self._load()
        raw = value["profiles"].get(name)
        if raw is None:
            raise ClitgError(ErrorCode.NOT_FOUND, f"Profile '{name}' does not exist")
        value["default"] = name
        self._save(value)
        return self.view(Profile.model_validate(raw), True)

    def set_secret_reference(self, name: str, reference: str) -> Profile:
        """Atomically replace a legacy API hash with a secret reference."""

        value = self._load()
        raw = value["profiles"].get(name)
        if raw is None:
            raise ClitgError(ErrorCode.NOT_FOUND, f"Profile '{name}' does not exist")
        raw["api_hash"] = None
        raw["api_hash_ref"] = reference
        self._save(value)
        return Profile.model_validate(raw)

    def set_policy_file(self, name: str, policy_file: str | None) -> ProfileView:
        """Attach or clear a versioned policy document."""

        value = self._load()
        raw = value["profiles"].get(name)
        if raw is None:
            raise ClitgError(ErrorCode.NOT_FOUND, f"Profile '{name}' does not exist")
        raw["policy_file"] = policy_file
        self._save(value)
        return self.view(Profile.model_validate(raw), name == value["default"])

    def remove(self, name: str) -> ProfileView:
        """Remove local profile configuration."""

        value = self._load()
        raw = value["profiles"].pop(name, None)
        if raw is None:
            raise ClitgError(ErrorCode.NOT_FOUND, f"Profile '{name}' does not exist")
        if value["default"] == name:
            value["default"] = None
        self._save(value)
        return self.view(Profile.model_validate(raw), False)

    @staticmethod
    def view(profile: Profile, is_default: bool) -> ProfileView:
        """Build a redacted public view."""

        from clitg.credentials import CredentialStore

        return ProfileView(
            name=profile.name,
            api_id=profile.api_id,
            phone=profile.phone,
            secret_storage=CredentialStore.kind(profile.api_hash_ref, profile.api_hash),
            policy_file=profile.policy_file,
            created_at=profile.created_at,
            is_default=is_default,
        )


class StateStore:
    """Persist resumable login, idempotency, and critical confirmations."""

    def __init__(self, paths: Paths) -> None:
        self.path = paths.state_file
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS logins (
                    login_id TEXT PRIMARY KEY,
                    profile TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    phone_code_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS idempotency (
                    profile TEXT NOT NULL,
                    action TEXT NOT NULL,
                    key TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (profile, action, key)
                );
                CREATE TABLE IF NOT EXISTS confirmations (
                    token TEXT PRIMARY KEY,
                    profile TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS checkpoints (
                    profile TEXT NOT NULL,
                    consumer_id TEXT NOT NULL,
                    cursor TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (profile, consumer_id)
                );
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurred_at TEXT NOT NULL,
                    profile TEXT,
                    command TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    target TEXT,
                    ok INTEGER NOT NULL,
                    error_code TEXT
                );
                """,
            )
        if os.name == "posix":
            self.path.chmod(0o600)

    def save_login(
        self,
        profile: str,
        phone: str,
        phone_code_hash: str,
        *,
        ttl_seconds: int = 600,
    ) -> LoginState:
        """Store a resumable login transaction."""

        now = datetime.now(UTC)
        login = LoginState(
            login_id=secrets.token_urlsafe(24),
            profile=profile,
            phone=phone,
            phone_code_hash=phone_code_hash,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO logins VALUES (?, ?, ?, ?, ?, ?)",
                (
                    login.login_id,
                    login.profile,
                    login.phone,
                    login.phone_code_hash,
                    login.created_at.isoformat(),
                    login.expires_at.isoformat(),
                ),
            )
        return login

    def get_login(self, login_id: str) -> LoginState:
        """Load a live login transaction."""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM logins WHERE login_id = ?", (login_id,)
            ).fetchone()
        if row is None:
            raise ClitgError(ErrorCode.NOT_FOUND, "Login transaction was not found")
        login = LoginState.model_validate(dict(row))
        if login.expires_at <= datetime.now(UTC):
            self.delete_login(login_id)
            raise ClitgError(ErrorCode.AUTH_REQUIRED, "Login transaction has expired")
        return login

    def delete_login(self, login_id: str) -> None:
        """Delete a login transaction."""

        with self._connect() as connection:
            connection.execute("DELETE FROM logins WHERE login_id = ?", (login_id,))

    def get_idempotent(self, profile: str, action: str, key: str, payload: Any) -> Any | None:
        """Return a cached result or reject a key reused with another payload."""

        digest = payload_hash(payload)
        cutoff = datetime.now(UTC) - timedelta(days=30)
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM idempotency WHERE created_at < ?", (cutoff.isoformat(),)
            )
            row = connection.execute(
                "SELECT payload_hash, result_json FROM idempotency "
                "WHERE profile=? AND action=? AND key=?",
                (profile, action, key),
            ).fetchone()
        if row is None:
            return None
        if row["payload_hash"] != digest:
            raise ClitgError(
                ErrorCode.CONFLICT, "Idempotency key was used with a different payload"
            )
        return json.loads(row["result_json"])

    def save_idempotent(
        self, profile: str, action: str, key: str, payload: Any, result: Any
    ) -> None:
        """Persist a successful idempotent result."""

        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO idempotency VALUES (?, ?, ?, ?, ?, ?)",
                (
                    profile,
                    action,
                    key,
                    payload_hash(payload),
                    json.dumps(to_jsonable(result), separators=(",", ":")),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def issue_confirmation(self, profile: str, action: str, payload: Any) -> Confirmation:
        """Issue a five-minute, single-use critical confirmation."""

        confirmation = Confirmation(
            token=secrets.token_urlsafe(32),
            profile=profile,
            action=action,
            payload_hash=payload_hash(payload),
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO confirmations VALUES (?, ?, ?, ?, ?, 0)",
                (
                    confirmation.token,
                    confirmation.profile,
                    confirmation.action,
                    confirmation.payload_hash,
                    confirmation.expires_at.isoformat(),
                ),
            )
        return confirmation

    def consume_confirmation(self, token: str, profile: str, action: str, payload: Any) -> None:
        """Validate and consume a critical confirmation."""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM confirmations WHERE token = ?", (token,)
            ).fetchone()
            if row is None:
                raise ClitgError(ErrorCode.CONFIRMATION_REQUIRED, "Confirmation token is invalid")
            confirmation = Confirmation.model_validate(dict(row))
            if confirmation.used or confirmation.expires_at <= datetime.now(UTC):
                raise ClitgError(ErrorCode.CONFIRMATION_REQUIRED, "Confirmation token has expired")
            if (
                confirmation.profile != profile
                or confirmation.action != action
                or confirmation.payload_hash != payload_hash(payload)
            ):
                raise ClitgError(
                    ErrorCode.CONFIRMATION_REQUIRED,
                    "Confirmation token does not match this operation",
                )
            connection.execute("UPDATE confirmations SET used = 1 WHERE token = ?", (token,))

    def counts(self) -> dict[str, int]:
        """Return safe auxiliary-state counts."""

        with self._connect() as connection:
            return {
                table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in ("logins", "idempotency", "confirmations", "checkpoints", "audit")
            }

    def save_checkpoint(self, profile: str, consumer_id: str, cursor: str) -> None:
        """Persist the last cursor acknowledged by one consumer."""

        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO checkpoints VALUES (?, ?, ?, ?)",
                (profile, consumer_id, cursor, datetime.now(UTC).isoformat()),
            )

    def get_checkpoint(self, profile: str, consumer_id: str) -> str | None:
        """Load a consumer cursor when present."""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT cursor FROM checkpoints WHERE profile=? AND consumer_id=?",
                (profile, consumer_id),
            ).fetchone()
        return None if row is None else str(row["cursor"])

    def record_audit(
        self,
        profile: str | None,
        command: str,
        request_id: str,
        *,
        target: str | None,
        ok: bool,
        error_code: str | None,
    ) -> None:
        """Record content-free command metadata and prune old entries."""

        cutoff = datetime.now(UTC) - timedelta(days=90)
        with self._connect() as connection:
            connection.execute("DELETE FROM audit WHERE occurred_at < ?", (cutoff.isoformat(),))
            connection.execute(
                "INSERT INTO audit "
                "(occurred_at, profile, command, request_id, target, ok, error_code) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    datetime.now(UTC).isoformat(),
                    profile,
                    command,
                    request_id,
                    target,
                    int(ok),
                    error_code,
                ),
            )

    def list_audit(self, limit: int | None = 100) -> list[dict[str, Any]]:
        """Return recent audit metadata."""

        with self._connect() as connection:
            if limit is None:
                rows = connection.execute("SELECT * FROM audit ORDER BY id DESC").fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
        return [dict(row) for row in rows]

    def prune(self, kind: str, before: datetime | None = None) -> dict[str, int]:
        """Delete auxiliary state by kind and optional age."""

        tables = {
            "login": ("logins", "created_at"),
            "idempotency": ("idempotency", "created_at"),
            "confirmation": ("confirmations", "expires_at"),
            "checkpoint": ("checkpoints", "updated_at"),
            "audit": ("audit", "occurred_at"),
        }
        selected = tables.values() if kind == "all" else (tables[kind],)
        result: dict[str, int] = {}
        with self._connect() as connection:
            for table, column in selected:
                if before is None:
                    cursor = connection.execute(f"DELETE FROM {table}")
                else:
                    cursor = connection.execute(
                        f"DELETE FROM {table} WHERE {column} < ?", (before.isoformat(),)
                    )
                result[table] = cursor.rowcount
        return result
