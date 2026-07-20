"""Telethon adapter for user-account operations."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from filelock import Timeout as FileLockTimeout
from telethon import TelegramClient, functions, types
from telethon.errors import SessionPasswordNeededError

from clitg.errors import ClitgError
from clitg.models import ErrorCode, Profile
from clitg.raw import RawCodec
from clitg.serialization import to_jsonable
from clitg.storage import Paths


def entity_view(entity: Any) -> dict[str, Any]:
    """Normalize a Telegram user, chat, or channel."""

    entity_id = getattr(entity, "id", None)
    first_name = getattr(entity, "first_name", None)
    last_name = getattr(entity, "last_name", None)
    title = getattr(entity, "title", None) or " ".join(
        part for part in (first_name, last_name) if part
    )
    if isinstance(entity, types.User):
        kind = "user"
    elif isinstance(entity, types.Channel):
        kind = "channel" if getattr(entity, "broadcast", False) else "group"
    elif isinstance(entity, types.Chat):
        kind = "group"
    else:
        kind = entity.__class__.__name__.lower()
    return {
        "id": entity_id,
        "kind": kind,
        "title": title or None,
        "username": getattr(entity, "username", None),
        "phone": getattr(entity, "phone", None),
        "is_bot": bool(getattr(entity, "bot", False)),
        "is_verified": bool(getattr(entity, "verified", False)),
    }


def message_view(message: Any, *, include_raw: bool = False) -> dict[str, Any]:
    """Normalize a Telegram message."""

    value: dict[str, Any] = {
        "id": getattr(message, "id", None),
        "peer_id": to_jsonable(getattr(message, "peer_id", None), raw=True),
        "sender_id": getattr(message, "sender_id", None),
        "date": getattr(message, "date", None),
        "text": getattr(message, "message", None),
        "outgoing": bool(getattr(message, "out", False)),
        "mentioned": bool(getattr(message, "mentioned", False)),
        "silent": bool(getattr(message, "silent", False)),
        "reply_to_message_id": getattr(message, "reply_to_msg_id", None),
        "grouped_id": getattr(message, "grouped_id", None),
        "has_media": getattr(message, "media", None) is not None,
        "views": getattr(message, "views", None),
        "forwards": getattr(message, "forwards", None),
        "edit_date": getattr(message, "edit_date", None),
    }
    if include_raw:
        value["raw"] = to_jsonable(message, raw=True)
    return to_jsonable(value)


def dialog_view(dialog: Any, *, include_raw: bool = False) -> dict[str, Any]:
    """Normalize a Telegram dialog."""

    value = {
        **entity_view(dialog.entity),
        "unread_count": dialog.unread_count,
        "unread_mentions_count": dialog.unread_mentions_count,
        "pinned": dialog.pinned,
        "archived": dialog.archived,
        "last_message": message_view(dialog.message) if dialog.message else None,
    }
    if include_raw:
        value["raw"] = to_jsonable(dialog.entity, raw=True)
    return value


class TelegramAdapter:
    """Perform Telegram operations using one locked profile session."""

    def __init__(self, paths: Paths, *, timeout_seconds: int = 30) -> None:
        self.paths = paths
        self.timeout_seconds = timeout_seconds
        self.codec = RawCodec()

    def _new_client(self, profile: Profile) -> TelegramClient:
        return TelegramClient(
            str(self.paths.session_file(profile.name)),
            profile.api_id,
            profile.api_hash,
            timeout=self.timeout_seconds,
            flood_sleep_threshold=0,
            request_retries=0,
            connection_retries=1,
        )

    @asynccontextmanager
    async def client(self, profile: Profile, *, require_auth: bool = True) -> AsyncIterator[Any]:
        """Open and reliably close a locked Telethon client."""

        lock = self.paths.profile_lock(profile.name)
        try:
            lock.acquire()
        except FileLockTimeout as exc:
            raise ClitgError(ErrorCode.CONFLICT, "The profile session is already in use") from exc
        client = self._new_client(profile)
        try:
            await client.connect()
            if require_auth and not await client.is_user_authorized():
                raise ClitgError(ErrorCode.AUTH_REQUIRED, "The profile is not authenticated")
            yield client
        finally:
            await client.disconnect()
            lock.release()

    async def request_code(self, profile: Profile, phone: str) -> str:
        """Request a Telegram login code and return its hash."""

        async with self.client(profile, require_auth=False) as client:
            result = await client.send_code_request(phone)
            return str(result.phone_code_hash)

    async def verify(
        self,
        profile: Profile,
        phone: str,
        code: str,
        phone_code_hash: str,
        password: str | None,
    ) -> dict[str, Any]:
        """Complete phone-code and optional 2FA login."""

        async with self.client(profile, require_auth=False) as client:
            try:
                user = await client.sign_in(
                    phone=phone,
                    code=code,
                    phone_code_hash=phone_code_hash,
                )
            except SessionPasswordNeededError:
                if not password:
                    raise ClitgError(
                        ErrorCode.AUTH_REQUIRED,
                        "A 2FA password is required",
                        details={"password_required": True},
                    ) from None
                user = await client.sign_in(password=password)
            return entity_view(user)

    async def auth_status(self, profile: Profile) -> dict[str, Any]:
        """Return authorization state without prompting."""

        async with self.client(profile, require_auth=False) as client:
            authorized = await client.is_user_authorized()
            me = await client.get_me() if authorized else None
            return {"authorized": authorized, "user": entity_view(me) if me else None}

    async def logout(self, profile: Profile) -> bool:
        """Revoke the current Telegram authorization."""

        async with self.client(profile) as client:
            return bool(await client.log_out())

    async def resolve_peer(self, client: Any, reference: str) -> Any:
        """Resolve a peer exactly or return structured ambiguity."""

        normalized: str | int = reference
        if reference.removeprefix("-").isdigit():
            normalized = int(reference)
        direct = reference == "me" or reference.startswith(("@", "+", "https://t.me/", "t.me/"))
        if direct or isinstance(normalized, int):
            try:
                return await client.get_entity(normalized)
            except (ValueError, TypeError) as exc:
                raise ClitgError(ErrorCode.NOT_FOUND, f"Peer '{reference}' was not found") from exc

        folded = reference.casefold()
        matches = []
        async for dialog in client.iter_dialogs():
            view = entity_view(dialog.entity)
            if folded in {
                str(view["title"] or "").casefold(),
                str(view["username"] or "").casefold(),
            }:
                matches.append(dialog.entity)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ClitgError(
                ErrorCode.AMBIGUOUS_PEER,
                f"Peer '{reference}' is ambiguous",
                details={"candidates": [entity_view(item) for item in matches]},
            )
        try:
            return await client.get_entity(reference)
        except (ValueError, TypeError) as exc:
            raise ClitgError(ErrorCode.NOT_FOUND, f"Peer '{reference}' was not found") from exc

    async def dialogs(
        self,
        profile: Profile,
        *,
        query: str | None,
        offset: int,
        limit: int,
        include_raw: bool,
    ) -> list[dict[str, Any]]:
        """List or search dialogs without changing read state."""

        async with self.client(profile) as client:
            found: list[dict[str, Any]] = []
            async for dialog in client.iter_dialogs(limit=offset + limit):
                view = dialog_view(dialog, include_raw=include_raw)
                if query and query.casefold() not in str(view.get("title") or "").casefold():
                    continue
                found.append(view)
            return found[offset : offset + limit]

    async def peer(self, profile: Profile, reference: str, *, include_raw: bool) -> dict[str, Any]:
        """Resolve and return one peer."""

        async with self.client(profile) as client:
            entity = await self.resolve_peer(client, reference)
            value = entity_view(entity)
            if include_raw:
                value["raw"] = to_jsonable(entity, raw=True)
            return value

    async def contacts(self, profile: Profile) -> list[dict[str, Any]]:
        """List Telegram contacts."""

        async with self.client(profile) as client:
            result = await client(functions.contacts.GetContactsRequest(hash=0))
            return [entity_view(user) for user in result.users]

    async def messages(
        self,
        profile: Profile,
        peer: str,
        *,
        limit: int,
        offset_id: int,
        query: str | None,
        topic_id: int | None,
        include_raw: bool,
    ) -> list[dict[str, Any]]:
        """List or search messages without sending read acknowledgements."""

        async with self.client(profile) as client:
            entity = await self.resolve_peer(client, peer)
            return [
                message_view(message, include_raw=include_raw)
                async for message in client.iter_messages(
                    entity,
                    limit=limit,
                    offset_id=offset_id,
                    search=query,
                    reply_to=topic_id,
                )
            ]

    async def get_message(
        self,
        profile: Profile,
        peer: str,
        message_id: int,
        *,
        include_raw: bool,
    ) -> dict[str, Any]:
        """Get one message without marking it read."""

        async with self.client(profile) as client:
            entity = await self.resolve_peer(client, peer)
            message = await client.get_messages(entity, ids=message_id)
            if message is None:
                raise ClitgError(ErrorCode.NOT_FOUND, f"Message '{message_id}' was not found")
            return message_view(message, include_raw=include_raw)

    async def send(
        self,
        profile: Profile,
        peer: str,
        *,
        text: str,
        files: list[Path],
        reply_to: int | None,
        topic_id: int | None,
        parse_mode: str,
        media_kind: str,
        schedule_at: datetime | None,
    ) -> list[dict[str, Any]]:
        """Send text or local media."""

        async with self.client(profile) as client:
            entity = await self.resolve_peer(client, peer)
            mode = None if parse_mode == "plain" else {"markdown": "md", "html": "html"}[parse_mode]
            reply = topic_id or reply_to
            if files:
                result = await client.send_file(
                    entity,
                    files if len(files) > 1 else files[0],
                    caption=text,
                    reply_to=reply,
                    parse_mode=mode,
                    voice_note=media_kind == "voice",
                    force_document=media_kind in {"document", "sticker"},
                    schedule=schedule_at,
                )
            else:
                result = await client.send_message(
                    entity,
                    text,
                    reply_to=reply,
                    parse_mode=mode,
                    schedule=schedule_at,
                )
            messages = result if isinstance(result, list) else [result]
            return [message_view(message) for message in messages]

    async def forward(
        self,
        profile: Profile,
        source_peer: str,
        target_peer: str,
        message_ids: list[int],
    ) -> list[dict[str, Any]]:
        """Forward messages between peers."""

        async with self.client(profile) as client:
            source = await self.resolve_peer(client, source_peer)
            target = await self.resolve_peer(client, target_peer)
            result = await client.forward_messages(target, message_ids, from_peer=source)
            messages = result if isinstance(result, list) else [result]
            return [message_view(message) for message in messages]

    async def edit(
        self,
        profile: Profile,
        peer: str,
        message_id: int,
        text: str,
        parse_mode: str,
    ) -> dict[str, Any]:
        """Edit a message."""

        async with self.client(profile) as client:
            entity = await self.resolve_peer(client, peer)
            mode = None if parse_mode == "plain" else {"markdown": "md", "html": "html"}[parse_mode]
            result = await client.edit_message(entity, message_id, text, parse_mode=mode)
            return message_view(result)

    async def delete(
        self,
        profile: Profile,
        peer: str,
        message_ids: list[int],
        *,
        everyone: bool,
    ) -> dict[str, Any]:
        """Delete messages with explicit revocation scope."""

        async with self.client(profile) as client:
            entity = await self.resolve_peer(client, peer)
            result = await client.delete_messages(entity, message_ids, revoke=everyone)
            return {"peer": entity_view(entity), "message_ids": message_ids, "updates": result}

    async def read(self, profile: Profile, peer: str, max_id: int | None) -> dict[str, Any]:
        """Explicitly send a read acknowledgement."""

        async with self.client(profile) as client:
            entity = await self.resolve_peer(client, peer)
            result = await client.send_read_acknowledge(entity, max_id=max_id)
            return {"peer": entity_view(entity), "max_id": max_id, "read": bool(result)}

    async def react(
        self,
        profile: Profile,
        peer: str,
        message_id: int,
        reaction: str | None,
    ) -> Any:
        """Set or clear a message reaction."""

        async with self.client(profile) as client:
            entity = await self.resolve_peer(client, peer)
            reactions: list[types.TypeReaction] = (
                [] if reaction is None else [types.ReactionEmoji(emoticon=reaction)]
            )
            result = await client(
                functions.messages.SendReactionRequest(
                    peer=entity,
                    msg_id=message_id,
                    reaction=reactions,
                )
            )
            return to_jsonable(result, raw=True)

    async def pin(
        self,
        profile: Profile,
        peer: str,
        message_id: int,
        *,
        unpin: bool,
    ) -> Any:
        """Pin or unpin one message."""

        async with self.client(profile) as client:
            entity = await self.resolve_peer(client, peer)
            result = await client(
                functions.messages.UpdatePinnedMessageRequest(
                    peer=entity,
                    id=message_id,
                    silent=True,
                    unpin=unpin,
                )
            )
            return to_jsonable(result, raw=True)

    async def scheduled(self, profile: Profile, peer: str) -> list[dict[str, Any]]:
        """List scheduled messages."""

        async with self.client(profile) as client:
            entity = await self.resolve_peer(client, peer)
            result = await client(
                functions.messages.GetScheduledHistoryRequest(peer=entity, hash=0)
            )
            return [message_view(message) for message in result.messages]

    async def cancel_scheduled(self, profile: Profile, peer: str, message_ids: list[int]) -> Any:
        """Cancel scheduled messages."""

        async with self.client(profile) as client:
            entity = await self.resolve_peer(client, peer)
            result = await client(
                functions.messages.DeleteScheduledMessagesRequest(peer=entity, id=message_ids)
            )
            return to_jsonable(result, raw=True)

    async def topics(self, profile: Profile, peer: str, *, limit: int) -> Any:
        """List forum topics for a group."""

        async with self.client(profile) as client:
            entity = await self.resolve_peer(client, peer)
            result = await client(
                functions.messages.GetForumTopicsRequest(
                    peer=entity,
                    offset_date=None,
                    offset_id=0,
                    offset_topic=0,
                    limit=limit,
                    q=None,
                )
            )
            return to_jsonable(result, raw=True)

    async def create_poll(
        self,
        profile: Profile,
        peer: str,
        question: str,
        answers: list[str],
        *,
        multiple_choice: bool,
        anonymous: bool,
        quiz: bool,
    ) -> list[dict[str, Any]]:
        """Create and send a poll."""

        answer_types: list[types.TypePollAnswer] = [
            types.PollAnswer(
                text=types.TextWithEntities(text=answer, entities=[]),
                option=bytes([index]),
            )
            for index, answer in enumerate(answers)
        ]
        poll = types.Poll(
            id=0,
            question=types.TextWithEntities(text=question, entities=[]),
            answers=answer_types,
            hash=0,
            public_voters=not anonymous,
            multiple_choice=multiple_choice,
            quiz=quiz,
        )
        async with self.client(profile) as client:
            entity = await self.resolve_peer(client, peer)
            result = await client.send_file(entity, types.InputMediaPoll(poll=poll))
            return [message_view(result)]

    async def vote_poll(
        self,
        profile: Profile,
        peer: str,
        message_id: int,
        options: list[int],
    ) -> Any:
        """Vote in a poll using zero-based option indexes."""

        async with self.client(profile) as client:
            entity = await self.resolve_peer(client, peer)
            result = await client(
                functions.messages.SendVoteRequest(
                    peer=entity,
                    msg_id=message_id,
                    options=[bytes([option]) for option in options],
                )
            )
            return to_jsonable(result, raw=True)

    async def close_poll(self, profile: Profile, peer: str, message_id: int) -> Any:
        """Close an existing poll."""

        async with self.client(profile) as client:
            entity = await self.resolve_peer(client, peer)
            message = await client.get_messages(entity, ids=message_id)
            if message is None or not isinstance(message.media, types.MessageMediaPoll):
                raise ClitgError(ErrorCode.NOT_FOUND, "Poll message was not found")
            poll = message.media.poll
            closed = types.Poll(
                id=poll.id,
                question=poll.question,
                answers=poll.answers,
                hash=poll.hash,
                closed=True,
                public_voters=poll.public_voters,
                multiple_choice=poll.multiple_choice,
                quiz=poll.quiz,
            )
            await client(
                functions.messages.EditMessageRequest(
                    peer=entity,
                    id=message_id,
                    media=types.InputMediaPoll(poll=closed),
                )
            )
            updated = await client.get_messages(entity, ids=message_id)
            if updated is None:
                raise ClitgError(ErrorCode.NOT_FOUND, "Closed poll message was not found")
            return message_view(updated)

    async def download(
        self,
        profile: Profile,
        peer: str,
        message_id: int,
        output: Path,
    ) -> Path:
        """Download message media to an explicit path."""

        async with self.client(profile) as client:
            entity = await self.resolve_peer(client, peer)
            message = await client.get_messages(entity, ids=message_id)
            if message is None or message.media is None:
                raise ClitgError(ErrorCode.NOT_FOUND, "Message media was not found")
            result = await client.download_media(message, file=output)
            if not result:
                raise ClitgError(ErrorCode.TELEGRAM_RPC, "Telegram did not return a media file")
            return Path(result)

    async def raw_invoke(
        self,
        profile: Profile,
        method: str,
        params: dict[str, Any],
    ) -> Any:
        """Build and invoke one raw TL request."""

        async with self.client(profile) as client:
            request = await self.codec.build(method, params, client, resolve=True)
            return self.codec.serialize(await client(request))
