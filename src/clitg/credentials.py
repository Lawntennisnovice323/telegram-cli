"""Non-interactive API hash storage and legacy profile migration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import keyring
from keyring.errors import KeyringError

from clitg.errors import ClitgError
from clitg.models import ErrorCode
from clitg.storage import Paths, _secure_write

_SERVICE = "clitg"


class CredentialStore:
    """Store API hashes in a system keyring or private fallback file."""

    def __init__(self, paths: Paths) -> None:
        self.paths = paths

    def save(self, profile: str, api_hash: str) -> str:
        """Persist a secret without requiring user interaction."""

        try:
            backend = keyring.get_keyring()
            if backend.priority > 0:
                keyring.set_password(_SERVICE, profile, api_hash)
                if keyring.get_password(_SERVICE, profile) == api_hash:
                    return f"keyring:{profile}"
        except KeyringError, RuntimeError, OSError:
            pass
        path = self.paths.data_dir / "profiles" / profile / "api_hash"
        _secure_write(path, api_hash)
        return f"file:{path.resolve()}"

    @staticmethod
    def load(reference: str) -> str:
        """Resolve a keyring or file reference."""

        if reference.startswith("keyring:"):
            profile = reference.removeprefix("keyring:")
            try:
                value = keyring.get_password(_SERVICE, profile)
            except (KeyringError, RuntimeError, OSError) as exc:
                raise ClitgError(
                    ErrorCode.PROFILE_ERROR, "Unable to access the system keyring"
                ) from exc
            if value:
                return value
        elif reference.startswith("file:"):
            path = Path(reference.removeprefix("file:"))
            try:
                value = path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise ClitgError(
                    ErrorCode.PROFILE_ERROR, "Unable to read the API hash file"
                ) from exc
            if value:
                return value
        raise ClitgError(ErrorCode.PROFILE_ERROR, "The profile API hash is unavailable")

    @staticmethod
    def kind(
        reference: str | None, legacy: str | None
    ) -> Literal["environment", "keyring", "file", "legacy", "missing"]:
        """Return a safe public storage classification."""

        if os.getenv("CLITG_API_HASH"):
            return "environment"
        if reference and reference.startswith("keyring:"):
            return "keyring"
        if reference and reference.startswith("file:"):
            return "file"
        if legacy:
            return "legacy"
        return "missing"
