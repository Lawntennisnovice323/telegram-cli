from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from filelock import Timeout as FileLockTimeout
from telethon import functions, types
from telethon.errors import SessionPasswordNeededError

from clitg.errors import ClitgError
from clitg.models import Profile
from clitg.storage import Paths
from clitg.telegram import TelegramAdapter, dialog_view, entity_view, message_view


def user(user_id: int = 1, name: str = "Alice") -> types.User:
    return types.User(
        id=user_id,
        first_name=name,
        last_name="User",
        username=name.lower(),
        phone="1555",
        bot=False,
        verified=True,
    )


def message(message_id: int = 1, *, media: Any = None) -> types.Message:
    return types.Message(
        id=message_id,
        peer_id=types.PeerUser(1),
        from_id=types.PeerUser(2),
        date=datetime(2026, 1, 1, tzinfo=UTC),
        message="hello",
        out=True,
        mentioned=True,
        silent=True,
        reply_to=types.MessageReplyHeader(reply_to_msg_id=7),
        grouped_id=8,
        media=media,
        views=9,
        forwards=10,
        edit_date=datetime(2026, 1, 2, tzinfo=UTC),
    )


def test_entity_message_and_dialog_views() -> None:
    assert entity_view(user())["kind"] == "user"
    photo = types.ChatPhotoEmpty()
    channel = types.Channel(
        id=2,
        title="Group",
        photo=photo,
        date=datetime.now(UTC),
        broadcast=False,
    )
    broadcast = types.Channel(
        id=3,
        title="News",
        photo=photo,
        date=datetime.now(UTC),
        broadcast=True,
    )
    chat = types.Chat(
        id=4,
        title="Chat",
        photo=photo,
        participants_count=2,
        date=datetime.now(UTC),
        version=1,
    )
    assert entity_view(channel)["kind"] == "group"
    assert entity_view(broadcast)["kind"] == "channel"
    assert entity_view(chat)["kind"] == "group"
    assert entity_view(SimpleNamespace(id=5, __class__=SimpleNamespace))["kind"]
    normalized = message_view(message(), include_raw=True)
    assert normalized["id"] == "1"
    assert normalized["reply_to_message_id"] == "7"
    assert normalized["raw"]["_"] == "Message"
    assert "raw" not in message_view(message(), include_raw=False)
    dialog = SimpleNamespace(
        entity=user(),
        unread_count=2,
        unread_mentions_count=1,
        pinned=True,
        archived=False,
        message=message(),
    )
    assert dialog_view(dialog, include_raw=True)["last_message"]["id"] == "1"
    dialog.message = None
    assert dialog_view(dialog)["last_message"] is None


class FakeLock:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.released = False

    def acquire(self) -> None:
        if self.fail:
            raise FileLockTimeout("busy")

    def release(self) -> None:
        self.released = True


class FakeClient:
    def __init__(self) -> None:
        self.connected = False
        self.disconnected = False
        self.authorized = True
        self.password_needed = False
        self.dialog_entities: list[Any] = [user()]
        self.entity_error = False
        self.message_result: Any = message()
        self.download_result: str | None = None
        self.calls: list[Any] = []

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnected = True

    async def is_user_authorized(self) -> bool:
        return self.authorized

    async def send_code_request(self, phone: str) -> Any:
        return SimpleNamespace(phone_code_hash=f"hash-{phone}")

    async def sign_in(self, **kwargs: Any) -> types.User:
        self.calls.append(("sign_in", kwargs))
        if self.password_needed and "password" not in kwargs:
            raise SessionPasswordNeededError(request=None)
        return user()

    async def get_me(self) -> types.User:
        return user()

    async def log_out(self) -> bool:
        return True

    async def get_entity(self, reference: Any) -> Any:
        self.calls.append(("get_entity", reference))
        if self.entity_error:
            raise ValueError("missing")
        return user()

    async def get_input_entity(self, reference: Any) -> Any:
        return types.InputPeerSelf()

    async def upload_file(self, path: Path) -> Any:
        return ("upload", str(path))

    async def iter_dialogs(self, limit: int | None = None) -> AsyncIterator[Any]:
        for entity in self.dialog_entities[:limit]:
            yield SimpleNamespace(
                entity=entity,
                unread_count=0,
                unread_mentions_count=0,
                pinned=False,
                archived=False,
                message=message(),
            )

    async def iter_messages(self, *args: Any, **kwargs: Any) -> AsyncIterator[types.Message]:
        self.calls.append(("iter_messages", args, kwargs))
        yield message()

    async def get_messages(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(("get_messages", args, kwargs))
        return self.message_result

    async def send_file(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(("send_file", args, kwargs))
        return self.message_result

    async def send_message(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(("send_message", args, kwargs))
        return self.message_result

    async def forward_messages(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(("forward_messages", args, kwargs))
        return [message(2)]

    async def edit_message(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(("edit_message", args, kwargs))
        return self.message_result

    async def delete_messages(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(("delete_messages", args, kwargs))
        return [types.messages.AffectedMessages(pts=1, pts_count=1)]

    async def send_read_acknowledge(self, *args: Any, **kwargs: Any) -> bool:
        self.calls.append(("read", args, kwargs))
        return True

    async def pin_message(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(("pin", args, kwargs))
        return types.UpdatesTooLong()

    async def unpin_message(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(("unpin", args, kwargs))
        return types.UpdatesTooLong()

    async def download_media(self, *args: Any, **kwargs: Any) -> str | None:
        self.calls.append(("download", args, kwargs))
        return self.download_result

    async def __call__(self, request: Any) -> Any:
        self.calls.append(("request", request))
        if isinstance(request, functions.contacts.GetContactsRequest):
            return SimpleNamespace(users=[user()])
        if isinstance(request, functions.messages.GetScheduledHistoryRequest):
            return SimpleNamespace(messages=[message()])
        if isinstance(request, functions.messages.GetForumTopicsRequest):
            return types.messages.ForumTopics(
                count=0, topics=[], messages=[], chats=[], users=[], pts=1
            )
        if isinstance(request, functions.messages.SendReactionRequest):
            return types.UpdatesTooLong()
        if isinstance(
            request,
            (functions.messages.EditMessageRequest, functions.messages.UpdatePinnedMessageRequest),
        ):
            return types.UpdatesTooLong()
        if isinstance(request, functions.messages.DeleteScheduledMessagesRequest):
            return types.UpdatesTooLong()
        if isinstance(request, functions.messages.SendVoteRequest):
            return types.UpdatesTooLong()
        return types.InputPeerSelf()


class StubAdapter(TelegramAdapter):
    def __init__(self, paths: Paths, fake: FakeClient) -> None:
        super().__init__(paths)
        self.fake = fake

    @asynccontextmanager
    async def client(self, profile: Profile, *, require_auth: bool = True) -> AsyncIterator[Any]:
        if require_auth and not self.fake.authorized:
            raise ClitgError
        yield self.fake


@pytest.fixture
def fake_client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def adapter(paths: Paths, fake_client: FakeClient) -> StubAdapter:
    return StubAdapter(paths, fake_client)


@pytest.mark.asyncio
async def test_real_client_context(
    paths: Paths, profile: Profile, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeClient()
    lock = FakeLock()
    adapter = TelegramAdapter(paths)
    monkeypatch.setattr(adapter, "_new_client", lambda _: fake)
    monkeypatch.setattr(paths, "profile_lock", lambda _: lock)
    async with adapter.client(profile) as received:
        assert received is fake
    assert fake.connected and fake.disconnected and lock.released
    fake.authorized = False
    with pytest.raises(ClitgError, match="not authenticated"):
        async with adapter.client(profile):
            pass
    failing = FakeLock(fail=True)
    monkeypatch.setattr(paths, "profile_lock", lambda _: failing)
    with pytest.raises(ClitgError, match="already in use"):
        async with adapter.client(profile):
            pass
    client = TelegramAdapter._new_client(adapter, profile)
    assert client.flood_sleep_threshold == 0
    assert client.session is not None
    client.session.close()


@pytest.mark.asyncio
async def test_auth(adapter: StubAdapter, profile: Profile, fake_client: FakeClient) -> None:
    assert await adapter.request_code(profile, "+1") == "hash-+1"
    assert (await adapter.verify(profile, "+1", "123", "h", None))["id"] == 1
    fake_client.password_needed = True
    with pytest.raises(ClitgError, match="2FA"):
        await adapter.verify(profile, "+1", "123", "h", None)
    assert (await adapter.verify(profile, "+1", "123", "h", "pw"))["id"] == 1
    assert (await adapter.auth_status(profile))["authorized"] is True
    fake_client.authorized = False
    assert (await adapter.auth_status(profile)) == {"authorized": False, "user": None}
    fake_client.authorized = True
    assert await adapter.logout(profile) is True


@pytest.mark.asyncio
async def test_resolve_peer(
    adapter: StubAdapter, profile: Profile, fake_client: FakeClient
) -> None:
    for reference in ("me", "@alice", "+1", "https://t.me/a", "t.me/a", "123", "-123"):
        assert await adapter.resolve_peer(fake_client, reference)
    fake_client.entity_error = True
    with pytest.raises(ClitgError, match="not found"):
        await adapter.resolve_peer(fake_client, "@missing")
    fake_client.entity_error = False
    assert (await adapter.resolve_peer(fake_client, "Alice User")).id == 1
    fake_client.dialog_entities = [user(1, "Bob"), user(2)]
    assert (await adapter.resolve_peer(fake_client, "Alice User")).id == 2
    fake_client.dialog_entities = [user(1), user(2)]
    with pytest.raises(ClitgError, match="ambiguous"):
        await adapter.resolve_peer(fake_client, "Alice User")
    fake_client.dialog_entities = []
    assert await adapter.resolve_peer(fake_client, "fallback")
    fake_client.entity_error = True
    with pytest.raises(ClitgError, match="not found"):
        await adapter.resolve_peer(fake_client, "missing")


@pytest.mark.asyncio
async def test_read_operations(
    adapter: StubAdapter, profile: Profile, fake_client: FakeClient
) -> None:
    assert await adapter.dialogs(profile, query=None, offset=0, limit=1, include_raw=False)
    assert not await adapter.dialogs(profile, query="missing", offset=0, limit=1, include_raw=True)
    assert (await adapter.peer(profile, "me", include_raw=True))["raw"]
    assert "raw" not in await adapter.peer(profile, "me", include_raw=False)
    assert await adapter.contacts(profile)
    assert await adapter.messages(
        profile,
        "me",
        limit=1,
        offset_id=0,
        query=None,
        topic_id=None,
        include_raw=True,
    )
    assert (await adapter.get_message(profile, "me", 1, include_raw=False))["id"] == "1"
    fake_client.message_result = None
    with pytest.raises(ClitgError, match="not found"):
        await adapter.get_message(profile, "me", 1, include_raw=False)


@pytest.mark.asyncio
async def test_send_and_mutations(
    adapter: StubAdapter, profile: Profile, fake_client: FakeClient, tmp_path: Path
) -> None:
    fake_client.message_result = message()
    assert await adapter.send(
        profile,
        "me",
        text="hello",
        files=[],
        reply_to=None,
        topic_id=None,
        parse_mode="plain",
        media_kind="auto",
        schedule_at=None,
    )
    file = tmp_path / "x"
    file.write_text("x")
    fake_client.message_result = [message(), message(2)]
    assert (
        len(
            await adapter.send(
                profile,
                "me",
                text="caption",
                files=[file, file],
                reply_to=1,
                topic_id=2,
                parse_mode="markdown",
                media_kind="voice",
                schedule_at=datetime.now(UTC),
            )
        )
        == 2
    )
    fake_client.message_result = message()
    assert await adapter.send(
        profile,
        "me",
        text="caption",
        files=[file],
        reply_to=None,
        topic_id=None,
        parse_mode="html",
        media_kind="document",
        schedule_at=None,
    )
    assert await adapter.forward(profile, "me", "@alice", [1])
    assert (await adapter.edit(profile, "me", 1, "x", "plain"))["id"] == "1"
    assert (await adapter.edit(profile, "me", 1, "x", "html"))["id"] == "1"
    assert (await adapter.delete(profile, "me", [1], everyone=True))["message_ids"] == [1]
    assert (await adapter.read(profile, "me", 1))["read"] is True
    assert await adapter.react(profile, "me", 1, "👍")
    assert await adapter.react(profile, "me", 1, None)
    assert await adapter.pin(profile, "me", 1, unpin=False)
    assert await adapter.pin(profile, "me", 1, unpin=True)


@pytest.mark.asyncio
async def test_scheduled_topics_polls_raw_and_download(
    adapter: StubAdapter,
    profile: Profile,
    fake_client: FakeClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert await adapter.scheduled(profile, "me")
    assert await adapter.cancel_scheduled(profile, "me", [1])
    assert await adapter.topics(profile, "me", limit=3)
    assert await adapter.create_poll(
        profile,
        "me",
        "question",
        ["a", "b"],
        multiple_choice=True,
        anonymous=False,
        quiz=True,
    )
    assert await adapter.vote_poll(profile, "me", 1, [0, 1])
    poll = types.Poll(
        id=1,
        question=types.TextWithEntities(text="q", entities=[]),
        answers=[types.PollAnswer(text=types.TextWithEntities(text="a", entities=[]), option=b"0")],
        hash=0,
    )
    fake_client.message_result = message(
        media=types.MessageMediaPoll(poll=poll, results=types.PollResults())
    )
    assert await adapter.close_poll(profile, "me", 1)
    original_get_messages = fake_client.get_messages
    calls = 0

    async def disappearing_message(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return await original_get_messages(*args, **kwargs) if calls == 1 else None

    with monkeypatch.context() as context:
        context.setattr(fake_client, "get_messages", disappearing_message)
        with pytest.raises(ClitgError, match="Closed poll"):
            await adapter.close_poll(profile, "me", 1)
    fake_client.message_result = None
    with pytest.raises(ClitgError, match="not found"):
        await adapter.close_poll(profile, "me", 1)
    fake_client.message_result = message()
    with pytest.raises(ClitgError, match="not found"):
        await adapter.close_poll(profile, "me", 1)
    fake_client.message_result = message(
        media=types.MessageMediaDocument(document=types.DocumentEmpty(id=1))
    )
    output = tmp_path / "file"
    fake_client.download_result = str(output)
    assert await adapter.download(profile, "me", 1, output) == output
    fake_client.download_result = None
    with pytest.raises(ClitgError, match="did not return"):
        await adapter.download(profile, "me", 1, output)
    fake_client.message_result = None
    with pytest.raises(ClitgError, match="not found"):
        await adapter.download(profile, "me", 1, output)
    assert (await adapter.raw_invoke(profile, "help.getConfig", {}))["_"] == "InputPeerSelf"
