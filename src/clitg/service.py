"""Application services coordinating storage, safety, and Telegram."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
from collections.abc import Awaitable
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

from telethon.errors import FloodWaitError, RPCError

from clitg import SCHEMA_VERSION, __version__
from clitg.catalog import capability_catalog, command_catalog, schema_catalog
from clitg.errors import ClitgError
from clitg.models import CommandResult, ErrorCode, Profile
from clitg.serialization import decode_cursor, encode_cursor
from clitg.storage import Paths, ProfileStore, StateStore
from clitg.telegram import TelegramAdapter

T = TypeVar("T")


class ClitgService:
    """Implement every CLI use case behind a testable API."""

    def __init__(self, paths: Paths | None = None, *, timeout_seconds: int = 30) -> None:
        self.paths = paths or Paths()
        self.profiles = ProfileStore(self.paths)
        self.state = StateStore(self.paths)
        self.telegram = TelegramAdapter(self.paths, timeout_seconds=timeout_seconds)

    def profile(self, requested: str | None) -> Profile:
        """Resolve a profile and apply explicit environment credential overrides."""

        profile = self.profiles.resolve(requested)
        changes: dict[str, Any] = {}
        if api_id := os.getenv("CLITG_API_ID"):
            try:
                changes["api_id"] = int(api_id)
            except ValueError as exc:
                raise ClitgError(
                    ErrorCode.INVALID_INPUT, "CLITG_API_ID must be an integer"
                ) from exc
        if api_hash := os.getenv("CLITG_API_HASH"):
            changes["api_hash"] = api_hash
        if phone := os.getenv("CLITG_PHONE"):
            changes["phone"] = phone
        return profile.model_copy(update=changes)

    async def telegram_call(self, operation: Awaitable[T]) -> T:
        """Translate Telethon and network failures into the public error contract."""

        try:
            return await operation
        except ClitgError:
            raise
        except FloodWaitError as exc:
            raise ClitgError(
                ErrorCode.RATE_LIMITED,
                "Telegram rate limit reached",
                retryable=True,
                retry_after_seconds=int(exc.seconds),
            ) from exc
        except RPCError as exc:
            message = str(exc)
            lowered = message.lower()
            code = (
                ErrorCode.PERMISSION_DENIED
                if "admin" in lowered or "forbidden" in lowered
                else ErrorCode.TELEGRAM_RPC
            )
            raise ClitgError(code, message, details={"rpc_error": exc.__class__.__name__}) from exc
        except (TimeoutError, ConnectionError, OSError) as exc:
            raise ClitgError(ErrorCode.NETWORK, str(exc), retryable=True) from exc

    def create_profile(
        self,
        name: str,
        api_id: int,
        api_hash: str,
        phone: str | None,
        *,
        make_default: bool,
    ) -> CommandResult:
        """Create a profile."""

        return CommandResult(
            data=self.profiles.create(
                Profile(name=name, api_id=api_id, api_hash=api_hash, phone=phone),
                make_default=make_default,
            )
        )

    def list_profiles(self) -> CommandResult:
        """List profiles."""

        return CommandResult(data=self.profiles.list(), items=self.profiles.list())

    def get_profile(self, name: str) -> CommandResult:
        """Get a safe profile."""

        return CommandResult(data=self.profiles.get(name))

    def set_default_profile(self, name: str) -> CommandResult:
        """Set the default profile."""

        return CommandResult(data=self.profiles.set_default(name))

    def remove_profile(
        self, name: str, *, dry_run: bool, confirmation: str | None
    ) -> CommandResult:
        """Remove local profile metadata with explicit intent."""

        preview = {"action": "profiles.remove", "profile": name, "server_session_revoked": False}
        if dry_run:
            return CommandResult(data={**preview, "dry_run": True})
        self._require_confirmation("profiles.remove", confirmation)
        removed = self.profiles.remove(name)
        return CommandResult(data={**preview, "removed": removed})

    async def request_code(self, requested: str | None, phone: str | None) -> CommandResult:
        """Begin login and persist an opaque transaction."""

        profile = self.profile(requested)
        selected_phone = phone or profile.phone
        if not selected_phone:
            raise ClitgError(ErrorCode.INVALID_INPUT, "A phone number is required")
        code_hash = await self.telegram_call(self.telegram.request_code(profile, selected_phone))
        login = self.state.save_login(profile.name, selected_phone, code_hash)
        return CommandResult(
            data={
                "login_id": login.login_id,
                "profile": login.profile,
                "phone": login.phone,
                "expires_at": login.expires_at,
            }
        )

    async def verify_login(
        self,
        requested: str | None,
        login_id: str,
        code: str,
        password: str | None,
    ) -> CommandResult:
        """Finish a pending Telegram login."""

        login = self.state.get_login(login_id)
        profile = self.profile(requested or login.profile)
        if profile.name != login.profile:
            raise ClitgError(ErrorCode.CONFLICT, "Login transaction belongs to another profile")
        user = await self.telegram_call(
            self.telegram.verify(
                profile,
                login.phone,
                code,
                login.phone_code_hash,
                password,
            )
        )
        self.state.delete_login(login_id)
        return CommandResult(data={"authorized": True, "user": user})

    async def auth_status(self, requested: str | None) -> CommandResult:
        """Return profile authorization state."""

        profile = self.profile(requested)
        return CommandResult(data=await self.telegram_call(self.telegram.auth_status(profile)))

    async def logout(
        self, requested: str | None, *, dry_run: bool, confirmation: str | None
    ) -> CommandResult:
        """Revoke the current session."""

        profile = self.profile(requested)
        preview = {"action": "auth.logout", "profile": profile.name}
        if dry_run:
            return CommandResult(data={**preview, "dry_run": True})
        self._require_confirmation("auth.logout", confirmation)
        revoked = await self.telegram_call(self.telegram.logout(profile))
        return CommandResult(data={**preview, "revoked": revoked})

    async def dialogs(
        self,
        requested: str | None,
        *,
        query: str | None,
        cursor: str | None,
        limit: int,
        include_raw: bool,
    ) -> CommandResult:
        """List or search dialogs."""

        self._limit(limit)
        profile = self.profile(requested)
        offset = int(self._cursor(cursor).get("offset", 0))
        items = await self.telegram_call(
            self.telegram.dialogs(
                profile,
                query=query,
                offset=offset,
                limit=limit,
                include_raw=include_raw,
            )
        )
        next_cursor = (
            encode_cursor({"offset": offset + len(items)}) if len(items) == limit else None
        )
        return CommandResult(data={"items": items}, items=items, next_cursor=next_cursor)

    async def peer(
        self, requested: str | None, reference: str, *, include_raw: bool
    ) -> CommandResult:
        """Resolve a peer."""

        profile = self.profile(requested)
        return CommandResult(
            data=await self.telegram_call(
                self.telegram.peer(profile, reference, include_raw=include_raw)
            )
        )

    async def contacts(self, requested: str | None, query: str | None) -> CommandResult:
        """List or search contacts locally."""

        profile = self.profile(requested)
        items = await self.telegram_call(self.telegram.contacts(profile))
        if query:
            folded = query.casefold()
            items = [
                item
                for item in items
                if folded in str(item.get("title") or "").casefold()
                or folded in str(item.get("username") or "").casefold()
                or folded in str(item.get("phone") or "").casefold()
            ]
        return CommandResult(data={"items": items}, items=items)

    async def messages(
        self,
        requested: str | None,
        peer: str,
        *,
        query: str | None,
        cursor: str | None,
        limit: int,
        topic_id: int | None,
        include_raw: bool,
    ) -> CommandResult:
        """List or search a peer's messages."""

        self._limit(limit)
        profile = self.profile(requested)
        offset_id = int(self._cursor(cursor).get("offset_id", 0))
        items = await self.telegram_call(
            self.telegram.messages(
                profile,
                peer,
                limit=limit,
                offset_id=offset_id,
                query=query,
                topic_id=topic_id,
                include_raw=include_raw,
            )
        )
        next_cursor = (
            encode_cursor({"offset_id": int(items[-1]["id"])}) if len(items) == limit else None
        )
        return CommandResult(data={"items": items}, items=items, next_cursor=next_cursor)

    async def get_message(
        self,
        requested: str | None,
        peer: str,
        message_id: int,
        *,
        include_raw: bool,
    ) -> CommandResult:
        """Get one message."""

        profile = self.profile(requested)
        return CommandResult(
            data=await self.telegram_call(
                self.telegram.get_message(
                    profile,
                    peer,
                    message_id,
                    include_raw=include_raw,
                )
            )
        )

    async def send(
        self,
        requested: str | None,
        peer: str,
        *,
        text: str,
        files: list[Path],
        reply_to: int | None,
        topic_id: int | None,
        parse_mode: str,
        media_kind: str,
        schedule_at: datetime | None,
        idempotency_key: str | None,
        dry_run: bool,
    ) -> CommandResult:
        """Send, reply, schedule, or upload messages safely."""

        if not text and not files:
            raise ClitgError(ErrorCode.INVALID_INPUT, "Text or at least one file is required")
        missing = [str(path) for path in files if not path.is_file()]
        if missing:
            raise ClitgError(
                ErrorCode.INVALID_INPUT, "Upload files do not exist", details={"files": missing}
            )
        profile = self.profile(requested)
        payload = {
            "peer": peer,
            "text": text,
            "files": [str(path.resolve()) for path in files],
            "reply_to": reply_to,
            "topic_id": topic_id,
            "parse_mode": parse_mode,
            "media_kind": media_kind,
            "schedule_at": schedule_at,
        }
        if dry_run:
            resolved = await self.telegram_call(
                self.telegram.peer(profile, peer, include_raw=False)
            )
            return CommandResult(
                data={
                    "action": "messages.send",
                    "payload": payload,
                    "peer": resolved,
                    "dry_run": True,
                }
            )
        if idempotency_key:
            existing = self.state.get_idempotent(
                profile.name, "messages.send", idempotency_key, payload
            )
            if existing is not None:
                return CommandResult(data={"messages": existing, "idempotent_replay": True})
        result = await self.telegram_call(
            self.telegram.send(
                profile,
                peer,
                text=text,
                files=files,
                reply_to=reply_to,
                topic_id=topic_id,
                parse_mode=parse_mode,
                media_kind=media_kind,
                schedule_at=schedule_at,
            )
        )
        if idempotency_key:
            self.state.save_idempotent(
                profile.name,
                "messages.send",
                idempotency_key,
                payload,
                result,
            )
        return CommandResult(data={"messages": result, "idempotent_replay": False})

    async def forward(
        self,
        requested: str | None,
        source_peer: str,
        target_peer: str,
        message_ids: list[int],
        *,
        idempotency_key: str | None,
        dry_run: bool,
    ) -> CommandResult:
        """Forward messages with optional idempotency."""

        if not message_ids:
            raise ClitgError(ErrorCode.INVALID_INPUT, "At least one message ID is required")
        profile = self.profile(requested)
        payload = {
            "source_peer": source_peer,
            "target_peer": target_peer,
            "message_ids": message_ids,
        }
        if dry_run:
            source = await self.telegram_call(
                self.telegram.peer(profile, source_peer, include_raw=False)
            )
            target = await self.telegram_call(
                self.telegram.peer(profile, target_peer, include_raw=False)
            )
            return CommandResult(
                data={
                    "action": "messages.forward",
                    "payload": payload,
                    "source": source,
                    "target": target,
                    "dry_run": True,
                }
            )
        if idempotency_key:
            existing = self.state.get_idempotent(
                profile.name, "messages.forward", idempotency_key, payload
            )
            if existing is not None:
                return CommandResult(data={"messages": existing, "idempotent_replay": True})
        result = await self.telegram_call(
            self.telegram.forward(profile, source_peer, target_peer, message_ids)
        )
        if idempotency_key:
            self.state.save_idempotent(
                profile.name, "messages.forward", idempotency_key, payload, result
            )
        return CommandResult(data={"messages": result, "idempotent_replay": False})

    async def edit_message(
        self,
        requested: str | None,
        peer: str,
        message_id: int,
        text: str,
        parse_mode: str,
        *,
        dry_run: bool,
    ) -> CommandResult:
        """Preview or edit one message."""

        profile = self.profile(requested)
        payload = {
            "peer": peer,
            "message_id": message_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if dry_run:
            resolved = await self.telegram_call(
                self.telegram.peer(profile, peer, include_raw=False)
            )
            return CommandResult(
                data={
                    "action": "messages.edit",
                    "payload": payload,
                    "peer": resolved,
                    "dry_run": True,
                }
            )
        return CommandResult(
            data=await self.telegram_call(
                self.telegram.edit(profile, peer, message_id, text, parse_mode)
            )
        )

    async def delete_messages(
        self,
        requested: str | None,
        peer: str,
        message_ids: list[int],
        scope: str,
        *,
        dry_run: bool,
        confirmation: str | None,
    ) -> CommandResult:
        """Preview or delete an exact message set."""

        if not message_ids:
            raise ClitgError(ErrorCode.INVALID_INPUT, "At least one message ID is required")
        if scope not in {"self", "everyone"}:
            raise ClitgError(ErrorCode.INVALID_INPUT, "Scope must be 'self' or 'everyone'")
        profile = self.profile(requested)
        action = "messages.delete"
        payload = {"peer": peer, "message_ids": message_ids, "scope": scope}
        if dry_run:
            resolved = await self.telegram_call(
                self.telegram.peer(profile, peer, include_raw=False)
            )
            return CommandResult(
                data={"action": action, "payload": payload, "peer": resolved, "dry_run": True}
            )
        self._require_confirmation(action, confirmation)
        return CommandResult(
            data=await self.telegram_call(
                self.telegram.delete(
                    profile,
                    peer,
                    message_ids,
                    everyone=scope == "everyone",
                )
            )
        )

    async def read_messages(
        self,
        requested: str | None,
        peer: str,
        max_id: int | None,
        *,
        dry_run: bool,
    ) -> CommandResult:
        """Preview or explicitly acknowledge messages as read."""

        profile = self.profile(requested)
        payload = {"peer": peer, "max_id": max_id}
        if dry_run:
            return CommandResult(
                data={"action": "messages.read", "payload": payload, "dry_run": True}
            )
        return CommandResult(
            data=await self.telegram_call(self.telegram.read(profile, peer, max_id))
        )

    async def react_message(
        self,
        requested: str | None,
        peer: str,
        message_id: int,
        reaction: str | None,
        *,
        dry_run: bool,
    ) -> CommandResult:
        """Preview or update a message reaction."""

        profile = self.profile(requested)
        payload = {"peer": peer, "message_id": message_id, "reaction": reaction}
        if dry_run:
            return CommandResult(
                data={"action": "messages.react", "payload": payload, "dry_run": True}
            )
        return CommandResult(
            data=await self.telegram_call(self.telegram.react(profile, peer, message_id, reaction))
        )

    async def pin_message(
        self,
        requested: str | None,
        peer: str,
        message_id: int,
        *,
        unpin: bool,
        dry_run: bool,
    ) -> CommandResult:
        """Preview or update a pinned message."""

        profile = self.profile(requested)
        action = "messages.unpin" if unpin else "messages.pin"
        payload = {"peer": peer, "message_id": message_id}
        if dry_run:
            return CommandResult(data={"action": action, "payload": payload, "dry_run": True})
        return CommandResult(
            data=await self.telegram_call(self.telegram.pin(profile, peer, message_id, unpin=unpin))
        )

    async def scheduled_messages(self, requested: str | None, peer: str) -> CommandResult:
        """List scheduled messages."""

        profile = self.profile(requested)
        items = await self.telegram_call(self.telegram.scheduled(profile, peer))
        return CommandResult(data={"items": items}, items=items)

    async def cancel_scheduled(
        self,
        requested: str | None,
        peer: str,
        message_ids: list[int],
        *,
        dry_run: bool,
        confirmation: str | None,
    ) -> CommandResult:
        """Preview or cancel scheduled messages."""

        if not message_ids:
            raise ClitgError(ErrorCode.INVALID_INPUT, "At least one message ID is required")
        profile = self.profile(requested)
        payload = {"peer": peer, "message_ids": message_ids}
        if dry_run:
            return CommandResult(
                data={"action": "scheduled.cancel", "payload": payload, "dry_run": True}
            )
        self._require_confirmation("scheduled.cancel", confirmation)
        return CommandResult(
            data=await self.telegram_call(
                self.telegram.cancel_scheduled(profile, peer, message_ids)
            )
        )

    async def topics(self, requested: str | None, peer: str, limit: int) -> CommandResult:
        """List forum topics."""

        self._limit(limit)
        profile = self.profile(requested)
        result = await self.telegram_call(self.telegram.topics(profile, peer, limit=limit))
        items = result.get("topics", []) if isinstance(result, dict) else []
        return CommandResult(data=result, items=items)

    async def create_poll(
        self,
        requested: str | None,
        peer: str,
        question: str,
        answers: list[str],
        *,
        multiple_choice: bool,
        anonymous: bool,
        quiz: bool,
        dry_run: bool,
    ) -> CommandResult:
        """Preview or create a poll."""

        if len(answers) < 2:
            raise ClitgError(ErrorCode.INVALID_INPUT, "A poll requires at least two answers")
        if len(answers) > 10:
            raise ClitgError(ErrorCode.INVALID_INPUT, "A poll supports at most ten answers")
        profile = self.profile(requested)
        payload = {
            "peer": peer,
            "question": question,
            "answers": answers,
            "multiple_choice": multiple_choice,
            "anonymous": anonymous,
            "quiz": quiz,
        }
        if dry_run:
            return CommandResult(
                data={"action": "polls.create", "payload": payload, "dry_run": True}
            )
        result = await self.telegram_call(
            self.telegram.create_poll(
                profile,
                peer,
                question,
                answers,
                multiple_choice=multiple_choice,
                anonymous=anonymous,
                quiz=quiz,
            )
        )
        return CommandResult(data={"messages": result})

    async def vote_poll(
        self,
        requested: str | None,
        peer: str,
        message_id: int,
        options: list[int],
        *,
        dry_run: bool,
    ) -> CommandResult:
        """Preview or vote in a poll."""

        if not options or any(option < 0 or option > 9 for option in options):
            raise ClitgError(ErrorCode.INVALID_INPUT, "Poll options must be indexes from 0 to 9")
        profile = self.profile(requested)
        payload = {"peer": peer, "message_id": message_id, "options": options}
        if dry_run:
            return CommandResult(data={"action": "polls.vote", "payload": payload, "dry_run": True})
        return CommandResult(
            data=await self.telegram_call(
                self.telegram.vote_poll(profile, peer, message_id, options)
            )
        )

    async def close_poll(
        self,
        requested: str | None,
        peer: str,
        message_id: int,
        *,
        dry_run: bool,
        confirmation: str | None,
    ) -> CommandResult:
        """Preview or close a poll."""

        profile = self.profile(requested)
        payload = {"peer": peer, "message_id": message_id}
        if dry_run:
            return CommandResult(
                data={"action": "polls.close", "payload": payload, "dry_run": True}
            )
        self._require_confirmation("polls.close", confirmation)
        return CommandResult(
            data=await self.telegram_call(self.telegram.close_poll(profile, peer, message_id))
        )

    async def raw(
        self,
        requested: str | None,
        method: str,
        params: dict[str, Any],
        *,
        allow_raw: bool,
        dry_run: bool,
        confirmation: str | None,
        confirmation_token: str | None,
    ) -> CommandResult:
        """Validate, preview, authorize, and invoke a raw TL method."""

        if not allow_raw:
            raise ClitgError(ErrorCode.CONFIRMATION_REQUIRED, "Raw invocation requires --allow-raw")
        profile = self.profile(requested)
        await self.telegram.codec.build(method, params, resolve=False)
        risk = self.telegram.codec.risk(method)
        payload = {"method": method, "params": params}
        critical = risk in {"critical", "unknown"}
        if dry_run:
            data: dict[str, Any] = {
                "action": "raw.invoke",
                "risk": risk,
                "payload": payload,
                "dry_run": True,
            }
            if critical:
                issued = self.state.issue_confirmation(profile.name, method, params)
                data["confirmation_token"] = issued.token
                data["confirmation_expires_at"] = issued.expires_at
            return CommandResult(data=data)
        if critical:
            if not confirmation_token:
                raise ClitgError(
                    ErrorCode.CONFIRMATION_REQUIRED, "A critical confirmation token is required"
                )
            self.state.consume_confirmation(confirmation_token, profile.name, method, params)
        elif risk == "destructive":
            self._require_confirmation(method, confirmation)
        return CommandResult(
            data={
                "method": method,
                "risk": risk,
                "result": await self.telegram_call(
                    self.telegram.raw_invoke(profile, method, params)
                ),
            }
        )

    async def download(
        self,
        requested: str | None,
        peer: str,
        message_id: int,
        output: Path,
        *,
        create_dirs: bool,
        overwrite: bool,
        dry_run: bool,
    ) -> CommandResult:
        """Download media without implicit path creation or overwrite."""

        if output.exists() and not overwrite:
            raise ClitgError(ErrorCode.CONFLICT, f"Output already exists: {output}")
        if not output.parent.exists():
            if not create_dirs:
                raise ClitgError(ErrorCode.INVALID_INPUT, "Output parent does not exist")
            if not dry_run:
                output.parent.mkdir(parents=True)
        profile = self.profile(requested)
        payload = {"peer": peer, "message_id": message_id, "output": str(output)}
        if dry_run:
            return CommandResult(
                data={"action": "media.download", "payload": payload, "dry_run": True}
            )
        path = await self.telegram_call(self.telegram.download(profile, peer, message_id, output))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        mime, _ = mimetypes.guess_type(path.name)
        return CommandResult(
            data={
                "path": str(path.resolve()),
                "size": path.stat().st_size,
                "mime_type": mime,
                "sha256": digest,
            }
        )

    def capabilities(self, method: str | None = None, status: str | None = None) -> CommandResult:
        """Query the generated MTProto capability catalog."""

        catalog = capability_catalog()
        values = catalog.capabilities
        if method:
            match = next((item for item in values if item.method == method), None)
            if match is None:
                raise ClitgError(ErrorCode.NOT_FOUND, f"Capability '{method}' was not found")
            return CommandResult(data=match)
        if status:
            values = [item for item in values if item.status == status]
        return CommandResult(
            data={
                "telethon_version": catalog.telethon_version,
                "telegram_layer": catalog.telegram_layer,
                "items": values,
            },
            items=values,
        )

    def schemas(self, name: str | None = None) -> CommandResult:
        """Query public JSON Schemas and the command catalog."""

        schemas = schema_catalog()
        if name is None:
            names = sorted(schemas["models"])
            return CommandResult(data={"models": names, "commands": command_catalog()})
        schema = schemas["models"].get(name)
        if schema is None:
            raise ClitgError(ErrorCode.NOT_FOUND, f"Schema '{name}' was not found")
        return CommandResult(data={"name": name, "schema": schema})

    def export_schemas(self, output: Path, *, overwrite: bool) -> CommandResult:
        """Export public schema and command catalogs."""

        if output.exists() and not overwrite:
            raise ClitgError(ErrorCode.CONFLICT, f"Output already exists: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {"commands": command_catalog(), **schema_catalog()}, indent=2, sort_keys=True
            )
            + "\n",
            encoding="utf-8",
        )
        return CommandResult(data={"path": str(output.resolve())})

    def state_counts(self) -> CommandResult:
        """Return safe auxiliary state counts."""

        return CommandResult(data=self.state.counts())

    def prune_state(
        self,
        kind: str,
        before: datetime | None,
        *,
        dry_run: bool,
        confirmation: str | None,
    ) -> CommandResult:
        """Preview or delete auxiliary state."""

        if kind not in {"login", "idempotency", "confirmation", "all"}:
            raise ClitgError(ErrorCode.INVALID_INPUT, "Invalid state kind")
        if dry_run:
            return CommandResult(
                data={
                    "action": "state.prune",
                    "kind": kind,
                    "before": before,
                    "current": self.state.counts(),
                    "dry_run": True,
                }
            )
        self._require_confirmation("state.prune", confirmation)
        return CommandResult(data={"deleted": self.state.prune(kind, before)})

    @staticmethod
    def version() -> CommandResult:
        """Return runtime and protocol versions."""

        catalog = capability_catalog()
        return CommandResult(
            data={
                "cli_version": __version__,
                "schema_version": SCHEMA_VERSION,
                "telethon_version": catalog.telethon_version,
                "telegram_layer": catalog.telegram_layer,
            }
        )

    @staticmethod
    def _require_confirmation(action: str, supplied: str | None) -> None:
        if supplied != action:
            raise ClitgError(
                ErrorCode.CONFIRMATION_REQUIRED,
                f"Operation requires --confirm {action}",
                details={"expected": action},
            )

    @staticmethod
    def _limit(limit: int) -> None:
        if not 1 <= limit <= 500:
            raise ClitgError(ErrorCode.INVALID_INPUT, "Limit must be between 1 and 500")

    @staticmethod
    def _cursor(cursor: str | None) -> dict[str, Any]:
        try:
            return decode_cursor(cursor)
        except ValueError as exc:
            raise ClitgError(ErrorCode.INVALID_INPUT, str(exc)) from exc
