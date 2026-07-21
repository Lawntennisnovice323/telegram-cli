from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from telethon.errors import FloodWaitError, RPCError

from clitg.errors import ClitgError
from clitg.models import BatchOperation, ErrorCode, Profile
from clitg.serialization import encode_cursor
from clitg.service import ClitgService
from clitg.storage import Paths


class FakeCodec:
    def __init__(self) -> None:
        self.selected_risk = "read"
        self.built: list[tuple[str, dict[str, Any], bool]] = []

    async def build(
        self,
        method: str,
        params: dict[str, Any],
        client: Any = None,
        *,
        resolve: bool,
    ) -> object:
        self.built.append((method, params, resolve))
        return object()

    def risk(self, method: str) -> str:
        return self.selected_risk


class FakeTelegram:
    def __init__(self) -> None:
        self.codec = FakeCodec()
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def _call(self, name: str, *args: Any, result: Any = None, **kwargs: Any) -> Any:
        self.calls.append((name, args, kwargs))
        return result

    async def request_code(self, *args: Any) -> str:
        await self._call("request_code", *args)
        return "code-hash"

    async def verify(self, *args: Any) -> dict[str, Any]:
        return await self._call("verify", *args, result={"id": 1})

    async def auth_status(self, *args: Any) -> dict[str, Any]:
        return await self._call("auth_status", *args, result={"authorized": True})

    async def qr_login(self, *args: Any) -> dict[str, Any]:
        return await self._call("qr_login", *args, result={"authorized": True})

    async def logout(self, *args: Any) -> bool:
        return await self._call("logout", *args, result=True)

    async def dialogs(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        limit = kwargs["limit"]
        return await self._call(
            "dialogs",
            *args,
            result=[{"id": index} for index in range(limit)],
            **kwargs,
        )

    async def peer(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await self._call("peer", *args, result={"id": 1, "title": "peer"}, **kwargs)

    async def contacts(self, *args: Any) -> list[dict[str, Any]]:
        return await self._call(
            "contacts",
            *args,
            result=[
                {"title": "Alice", "username": "alice", "phone": "+1"},
                {"title": "Bob", "username": "bob", "phone": "+2"},
            ],
        )

    async def messages(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        limit = kwargs["limit"]
        return await self._call(
            "messages",
            *args,
            result=[{"id": index + 1} for index in range(limit)],
            **kwargs,
        )

    async def global_search(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        limit = kwargs["limit"]
        return await self._call(
            "global_search",
            *args,
            result=[{"id": index + 1} for index in range(limit)],
            **kwargs,
        )

    async def inbox(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        limit = kwargs["limit"]
        return await self._call(
            "inbox",
            *args,
            result=[{"id": index + 1} for index in range(limit)],
            **kwargs,
        )

    async def message_context(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return await self._call("message_context", *args, result=[{"id": 1}], **kwargs)

    async def message_replies(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        limit = kwargs["limit"]
        return await self._call(
            "message_replies",
            *args,
            result=[{"id": index + 1} for index in range(limit)],
            **kwargs,
        )

    async def watch_updates(self, *args: Any, **kwargs: Any) -> Any:
        await self._call("watch_updates", *args, **kwargs)
        yield {
            "event_id": "event",
            "event_type": "message.new",
            "occurred_at": "2026-01-01T00:00:00Z",
            "peer_id": "1",
            "data": {},
            "raw_type": None,
        }

    async def get_message(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await self._call("get_message", *args, result={"id": 1}, **kwargs)

    async def send(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return await self._call("send", *args, result=[{"id": 10}], **kwargs)

    async def forward(self, *args: Any) -> list[dict[str, Any]]:
        return await self._call("forward", *args, result=[{"id": 11}])

    async def edit(self, *args: Any) -> dict[str, Any]:
        return await self._call("edit", *args, result={"id": 1, "text": "edited"})

    async def delete(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await self._call("delete", *args, result={"deleted": True}, **kwargs)

    async def read(self, *args: Any) -> dict[str, Any]:
        return await self._call("read", *args, result={"read": True})

    async def react(self, *args: Any) -> dict[str, Any]:
        return await self._call("react", *args, result={"reacted": True})

    async def pin(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await self._call("pin", *args, result={"pinned": not kwargs["unpin"]}, **kwargs)

    async def scheduled(self, *args: Any) -> list[dict[str, Any]]:
        return await self._call("scheduled", *args, result=[{"id": 2}])

    async def cancel_scheduled(self, *args: Any) -> dict[str, Any]:
        return await self._call("cancel_scheduled", *args, result={"cancelled": True})

    async def topics(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await self._call("topics", *args, result={"topics": [{"id": 1}]}, **kwargs)

    async def create_poll(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return await self._call("create_poll", *args, result=[{"id": 3}], **kwargs)

    async def vote_poll(self, *args: Any) -> dict[str, Any]:
        return await self._call("vote_poll", *args, result={"voted": True})

    async def close_poll(self, *args: Any) -> dict[str, Any]:
        return await self._call("close_poll", *args, result={"closed": True})

    async def download(self, *args: Any) -> Path:
        output = args[-1]
        output.write_bytes(b"content")
        return await self._call("download", *args, result=output)

    async def raw_invoke(self, *args: Any) -> dict[str, Any]:
        return await self._call("raw_invoke", *args, result={"_": "Config"})


@pytest.fixture
def service(paths: Paths) -> ClitgService:
    value = ClitgService(paths)
    value.profiles.create(Profile(name="personal", api_id=1, api_hash="secret"))
    value.telegram = cast(Any, FakeTelegram())
    return value


def test_profile_resolution_and_crud(
    service: ClitgService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLITG_API_ID", "2")
    monkeypatch.setenv("CLITG_API_HASH", "override")
    monkeypatch.setenv("CLITG_PHONE", "+2")
    selected = service.profile(None)
    assert (selected.api_id, selected.api_hash, selected.phone) == (2, "override", "+2")
    monkeypatch.setenv("CLITG_API_ID", "bad")
    with pytest.raises(ClitgError, match="must be an integer"):
        service.profile(None)
    monkeypatch.delenv("CLITG_API_ID")
    created = service.create_profile("other", 2, "hash", None, make_default=False)
    assert created.data.name == "other"
    listed_profiles = service.list_profiles().items
    assert listed_profiles is not None and len(listed_profiles) == 2
    assert service.get_profile("other").data.name == "other"
    assert service.set_default_profile("other").data.is_default
    assert service.remove_profile("other", dry_run=True, confirmation=None).data["dry_run"]
    with pytest.raises(ClitgError, match="--confirm"):
        service.remove_profile("other", dry_run=False, confirmation=None)
    assert (
        service.remove_profile("other", dry_run=False, confirmation="profiles.remove")
        .data["removed"]
        .name
        == "other"
    )


@pytest.mark.asyncio
async def test_telegram_error_translation(service: ClitgService) -> None:
    async def domain() -> None:
        raise ClitgError(ErrorCode.NOT_FOUND, "x")

    async def flood() -> None:
        raise FloodWaitError(request=None, capture=3)

    async def permission() -> None:
        raise RPCError(request=None, message="CHAT_ADMIN_REQUIRED")

    async def rpc() -> None:
        raise RPCError(request=None, message="SOMETHING")

    async def network() -> None:
        raise TimeoutError("timeout")

    for coroutine, code in (
        (domain, ErrorCode.NOT_FOUND),
        (flood, ErrorCode.RATE_LIMITED),
        (permission, ErrorCode.PERMISSION_DENIED),
        (rpc, ErrorCode.TELEGRAM_RPC),
        (network, ErrorCode.NETWORK),
    ):
        with pytest.raises(ClitgError) as error:
            await service.telegram_call(coroutine())
        assert error.value.info.code == code
    assert (await service.telegram_call(asyncio.sleep(0, result=4))) == 4


@pytest.mark.asyncio
async def test_auth_flow(service: ClitgService) -> None:
    service.profiles.resolve().phone = None
    with pytest.raises(ClitgError, match="phone"):
        await service.request_code(None, None)
    requested = await service.request_code(None, "+1")
    login_id = requested.data["login_id"]
    with pytest.raises(ClitgError, match="another profile"):
        service.profiles.create(Profile(name="other", api_id=2, api_hash="x"))
        await service.verify_login("other", login_id, "123", None)
    verified = await service.verify_login(None, login_id, "123", None)
    assert verified.data["authorized"] is True
    assert (await service.auth_status(None)).data["authorized"] is True
    assert (await service.logout(None, dry_run=True, confirmation=None)).data["dry_run"]
    with pytest.raises(ClitgError, match="--confirm"):
        await service.logout(None, dry_run=False, confirmation=None)
    assert (await service.logout(None, dry_run=False, confirmation="auth.logout")).data["revoked"]


@pytest.mark.asyncio
async def test_dialog_contacts_and_messages(service: ClitgService) -> None:
    dialogs = await service.dialogs(None, query=None, cursor=None, limit=2, include_raw=False)
    assert dialogs.items is not None and len(dialogs.items) == 2 and dialogs.next_cursor
    page = await service.dialogs(
        None, query="x", cursor=dialogs.next_cursor, limit=1, include_raw=True
    )
    assert page.next_cursor
    assert (await service.peer(None, "me", include_raw=True)).data["id"] == 1
    contacts = (await service.contacts(None, None)).items
    assert contacts is not None and len(contacts) == 2
    filtered_contacts = (await service.contacts(None, "ali")).items
    assert filtered_contacts is not None
    assert [item["title"] for item in filtered_contacts] == ["Alice"]
    messages = await service.messages(
        None,
        "me",
        query=None,
        cursor=None,
        limit=2,
        topic_id=None,
        include_raw=False,
    )
    assert messages.next_cursor
    assert (
        await service.messages(
            None,
            "me",
            query="x",
            cursor=messages.next_cursor,
            limit=1,
            topic_id=1,
            include_raw=True,
        )
    ).items
    assert (await service.get_message(None, "me", 1, include_raw=True)).data["id"] == 1
    for bad_limit in (0, 501):
        with pytest.raises(ClitgError, match="Limit"):
            await service.dialogs(None, query=None, cursor=None, limit=bad_limit, include_raw=False)
    with pytest.raises(ClitgError, match="cursor"):
        await service.dialogs(None, query=None, cursor="bad", limit=1, include_raw=False)


@pytest.mark.asyncio
async def test_send_and_idempotency(service: ClitgService, tmp_path: Path) -> None:
    with pytest.raises(ClitgError, match="Text"):
        await service.send(
            None,
            "me",
            text="",
            files=[],
            reply_to=None,
            topic_id=None,
            parse_mode="plain",
            media_kind="auto",
            schedule_at=None,
            idempotency_key=None,
            dry_run=False,
        )
    with pytest.raises(ClitgError, match="do not exist"):
        await service.send(
            None,
            "me",
            text="x",
            files=[tmp_path / "missing"],
            reply_to=None,
            topic_id=None,
            parse_mode="plain",
            media_kind="auto",
            schedule_at=None,
            idempotency_key=None,
            dry_run=False,
        )
    preview = await service.send(
        None,
        "me",
        text="hello",
        files=[],
        reply_to=None,
        topic_id=None,
        parse_mode="plain",
        media_kind="auto",
        schedule_at=None,
        idempotency_key="key",
        dry_run=True,
    )
    assert preview.data["dry_run"]
    sent = await service.send(
        None,
        "me",
        text="hello",
        files=[],
        reply_to=None,
        topic_id=None,
        parse_mode="plain",
        media_kind="auto",
        schedule_at=None,
        idempotency_key="key",
        dry_run=False,
    )
    assert sent.data["idempotent_replay"] is False
    replay = await service.send(
        None,
        "me",
        text="hello",
        files=[],
        reply_to=None,
        topic_id=None,
        parse_mode="plain",
        media_kind="auto",
        schedule_at=None,
        idempotency_key="key",
        dry_run=False,
    )
    assert replay.data["idempotent_replay"] is True
    sent_without_key = await service.send(
        None,
        "me",
        text="other",
        files=[],
        reply_to=None,
        topic_id=None,
        parse_mode="plain",
        media_kind="auto",
        schedule_at=None,
        idempotency_key=None,
        dry_run=False,
    )
    assert sent_without_key.data["messages"]


@pytest.mark.asyncio
async def test_forward_and_message_mutations(service: ClitgService) -> None:
    with pytest.raises(ClitgError, match="At least"):
        await service.forward(None, "a", "b", [], idempotency_key=None, dry_run=False)
    assert (await service.forward(None, "a", "b", [1], idempotency_key="f", dry_run=True)).data[
        "dry_run"
    ]
    first = await service.forward(None, "a", "b", [1], idempotency_key="f", dry_run=False)
    assert first.data["idempotent_replay"] is False
    assert (await service.forward(None, "a", "b", [1], idempotency_key="f", dry_run=False)).data[
        "idempotent_replay"
    ]
    assert (await service.forward(None, "a", "b", [2], idempotency_key=None, dry_run=False)).data[
        "messages"
    ]
    assert (await service.edit_message(None, "me", 1, "x", "plain", dry_run=True)).data["dry_run"]
    assert (await service.edit_message(None, "me", 1, "x", "plain", dry_run=False)).data
    first_edit = await service.edit_message(
        None,
        "me",
        1,
        "x",
        "plain",
        dry_run=False,
        idempotency_key="edit",
    )
    replay_edit = await service.edit_message(
        None,
        "me",
        1,
        "x",
        "plain",
        dry_run=False,
        idempotency_key="edit",
    )
    assert not first_edit.data["idempotent_replay"] and replay_edit.data["idempotent_replay"]
    assert service._mutation_data([1], False) == {"result": [1], "idempotent_replay": False}
    for ids, scope, match in (([], "self", "At least"), ([1], "bad", "Scope")):
        with pytest.raises(ClitgError, match=match):
            await service.delete_messages(None, "me", ids, scope, dry_run=False, confirmation=None)
    assert (
        await service.delete_messages(None, "me", [1], "self", dry_run=True, confirmation=None)
    ).data["dry_run"]
    with pytest.raises(ClitgError, match="--confirm"):
        await service.delete_messages(None, "me", [1], "everyone", dry_run=False, confirmation=None)
    assert (
        await service.delete_messages(
            None,
            "me",
            [1],
            "everyone",
            dry_run=False,
            confirmation="messages.delete",
        )
    ).data["deleted"]
    assert (await service.read_messages(None, "me", 1, dry_run=True)).data["dry_run"]
    assert (await service.read_messages(None, "me", 1, dry_run=False)).data["read"]
    assert (await service.react_message(None, "me", 1, "👍", dry_run=True)).data["dry_run"]
    assert (await service.react_message(None, "me", 1, None, dry_run=False)).data["reacted"]
    for unpin in (False, True):
        assert (await service.pin_message(None, "me", 1, unpin=unpin, dry_run=True)).data["dry_run"]
        assert (
            "pinned" in (await service.pin_message(None, "me", 1, unpin=unpin, dry_run=False)).data
        )


@pytest.mark.asyncio
async def test_scheduled_topics_and_polls(service: ClitgService) -> None:
    assert (await service.scheduled_messages(None, "me")).items
    with pytest.raises(ClitgError, match="At least"):
        await service.cancel_scheduled(None, "me", [], dry_run=False, confirmation=None)
    assert (await service.cancel_scheduled(None, "me", [1], dry_run=True, confirmation=None)).data[
        "dry_run"
    ]
    with pytest.raises(ClitgError, match="--confirm"):
        await service.cancel_scheduled(None, "me", [1], dry_run=False, confirmation=None)
    assert (
        await service.cancel_scheduled(
            None,
            "me",
            [1],
            dry_run=False,
            confirmation="scheduled.cancel",
        )
    ).data["cancelled"]
    assert (await service.topics(None, "me", 5)).items
    for answers, match in ((["one"], "at least"), ([str(i) for i in range(11)], "at most")):
        with pytest.raises(ClitgError, match=match):
            await service.create_poll(
                None,
                "me",
                "q",
                answers,
                multiple_choice=False,
                anonymous=True,
                quiz=False,
                dry_run=False,
            )
    assert (
        await service.create_poll(
            None,
            "me",
            "q",
            ["a", "b"],
            multiple_choice=True,
            anonymous=False,
            quiz=True,
            dry_run=True,
        )
    ).data["dry_run"]
    assert (
        await service.create_poll(
            None,
            "me",
            "q",
            ["a", "b"],
            multiple_choice=False,
            anonymous=True,
            quiz=False,
            dry_run=False,
        )
    ).data["messages"]
    first_poll = await service.create_poll(
        None,
        "me",
        "q",
        ["a", "b"],
        multiple_choice=False,
        anonymous=True,
        quiz=False,
        dry_run=False,
        idempotency_key="poll",
    )
    replay_poll = await service.create_poll(
        None,
        "me",
        "q",
        ["a", "b"],
        multiple_choice=False,
        anonymous=True,
        quiz=False,
        dry_run=False,
        idempotency_key="poll",
    )
    assert not first_poll.data["idempotent_replay"] and replay_poll.data["idempotent_replay"]
    for options in ([], [-1], [10]):
        with pytest.raises(ClitgError, match="indexes"):
            await service.vote_poll(None, "me", 1, options, dry_run=False)
    assert (await service.vote_poll(None, "me", 1, [0], dry_run=True)).data["dry_run"]
    assert (await service.vote_poll(None, "me", 1, [0], dry_run=False)).data["voted"]
    assert (await service.close_poll(None, "me", 1, dry_run=True, confirmation=None)).data[
        "dry_run"
    ]
    with pytest.raises(ClitgError, match="--confirm"):
        await service.close_poll(None, "me", 1, dry_run=False, confirmation=None)
    assert (
        await service.close_poll(None, "me", 1, dry_run=False, confirmation="polls.close")
    ).data["closed"]


@pytest.mark.asyncio
async def test_raw_safety(service: ClitgService) -> None:
    fake = service.telegram
    assert isinstance(fake, FakeTelegram)
    with pytest.raises(ClitgError, match="--allow-raw"):
        await service.raw(
            None,
            "help.getConfig",
            {},
            allow_raw=False,
            dry_run=False,
            confirmation=None,
            confirmation_token=None,
        )
    preview = await service.raw(
        None,
        "help.getConfig",
        {},
        allow_raw=True,
        dry_run=True,
        confirmation=None,
        confirmation_token=None,
    )
    assert preview.data["risk"] == "read"
    assert (
        await service.raw(
            None,
            "help.getConfig",
            {},
            allow_raw=True,
            dry_run=False,
            confirmation=None,
            confirmation_token=None,
        )
    ).data["result"]
    fake.codec.selected_risk = "destructive"
    with pytest.raises(ClitgError, match="--confirm"):
        await service.raw(
            None,
            "messages.deleteMessages",
            {},
            allow_raw=True,
            dry_run=False,
            confirmation=None,
            confirmation_token=None,
        )
    assert (
        await service.raw(
            None,
            "messages.deleteMessages",
            {},
            allow_raw=True,
            dry_run=False,
            confirmation="messages.deleteMessages",
            confirmation_token=None,
        )
    ).data["result"]
    for critical_risk in ("critical", "unknown"):
        fake.codec.selected_risk = critical_risk
        critical = await service.raw(
            None,
            "account.deleteAccount",
            {"reason": "x"},
            allow_raw=True,
            dry_run=True,
            confirmation=None,
            confirmation_token=None,
        )
        token = critical.data["confirmation_token"]
        with pytest.raises(ClitgError, match="token is required"):
            await service.raw(
                None,
                "account.deleteAccount",
                {"reason": "x"},
                allow_raw=True,
                dry_run=False,
                confirmation=None,
                confirmation_token=None,
            )
        assert (
            await service.raw(
                None,
                "account.deleteAccount",
                {"reason": "x"},
                allow_raw=True,
                dry_run=False,
                confirmation=None,
                confirmation_token=token,
            )
        ).data["result"]


@pytest.mark.asyncio
async def test_download(service: ClitgService, tmp_path: Path) -> None:
    output = tmp_path / "missing" / "file.txt"
    with pytest.raises(ClitgError, match="parent"):
        await service.download(
            None,
            "me",
            1,
            output,
            create_dirs=False,
            overwrite=False,
            dry_run=False,
        )
    preview = await service.download(
        None, "me", 1, output, create_dirs=True, overwrite=False, dry_run=True
    )
    assert preview.data["dry_run"] and not output.parent.exists()
    result = await service.download(
        None, "me", 1, output, create_dirs=True, overwrite=False, dry_run=False
    )
    assert result.data["size"] == 7
    with pytest.raises(ClitgError, match="exists"):
        await service.download(
            None,
            "me",
            1,
            output,
            create_dirs=False,
            overwrite=False,
            dry_run=False,
        )
    assert (
        await service.download(
            None,
            "me",
            1,
            output,
            create_dirs=False,
            overwrite=True,
            dry_run=False,
        )
    ).data["sha256"]


def test_catalog_schema_state_and_version(service: ClitgService, tmp_path: Path) -> None:
    listed = service.capabilities()
    assert listed.items
    assert service.capabilities(status="high-level").items
    assert service.capabilities(method="help.getConfig").data.method == "help.getConfig"
    with pytest.raises(ClitgError, match="not found"):
        service.capabilities(method="none.missing")
    assert "Envelope" in service.schemas().data["models"]
    assert service.schemas("Envelope").data["name"] == "Envelope"
    with pytest.raises(ClitgError, match="not found"):
        service.schemas("Missing")
    output = tmp_path / "schema" / "catalog.json"
    assert service.export_schemas(output, overwrite=False).data["path"]
    with pytest.raises(ClitgError, match="exists"):
        service.export_schemas(output, overwrite=False)
    assert service.export_schemas(output, overwrite=True).data["path"]
    assert service.state_counts().data == {
        "logins": 0,
        "idempotency": 0,
        "confirmations": 0,
        "checkpoints": 0,
        "audit": 0,
    }
    with pytest.raises(ClitgError, match="Invalid state"):
        service.prune_state("bad", None, dry_run=False, confirmation=None)
    assert service.prune_state("all", None, dry_run=True, confirmation=None).data["dry_run"]
    with pytest.raises(ClitgError, match="--confirm"):
        service.prune_state("all", None, dry_run=False, confirmation=None)
    assert service.prune_state("all", None, dry_run=False, confirmation="state.prune").data[
        "deleted"
    ]
    assert (
        service.prune_state(
            "audit",
            None,
            dry_run=True,
            confirmation=None,
            action="audit.prune",
        ).data["action"]
        == "audit.prune"
    )
    assert service.prune_state(
        "audit",
        None,
        dry_run=False,
        confirmation="audit.prune",
        action="audit.prune",
    ).data["deleted"] == {"audit": 0}
    assert ClitgService.version().data["schema_version"] == "0.2"


def test_profile_secret_migration_and_missing(service: ClitgService, paths: Paths) -> None:
    migrated = service.profile(None)
    assert migrated.api_hash == "secret"
    stored = service.profiles.resolve("personal")
    assert stored.api_hash is None and stored.api_hash_ref
    missing = ClitgService(Paths(paths.config_dir / "missing", paths.data_dir / "missing"))
    missing.profiles.create(Profile(name="empty", api_id=1))
    with pytest.raises(ClitgError, match="unavailable"):
        missing.profile("empty")


@pytest.mark.asyncio
async def test_qr_inbox_global_context_and_replies(service: ClitgService, tmp_path: Path) -> None:
    output = tmp_path / "qr.png"
    assert (await service.qr_login(None, output, 10)).data["authorized"]
    output.write_text("exists")
    with pytest.raises(ClitgError, match="exists"):
        await service.qr_login(None, output, 10)
    with pytest.raises(ClitgError, match="positive"):
        await service.qr_login(None, tmp_path / "other.png", 0)

    global_result = await service.messages(
        None,
        None,
        query="needle",
        cursor=None,
        limit=2,
        topic_id=None,
        include_raw=True,
    )
    assert global_result.next_cursor
    invalid_after = datetime(2026, 1, 2, tzinfo=UTC)
    with pytest.raises(ClitgError, match="earlier"):
        await service.messages(
            None,
            None,
            query="needle",
            cursor=None,
            limit=2,
            topic_id=None,
            include_raw=False,
            after=invalid_after,
            before=invalid_after,
        )
    with pytest.raises(ClitgError, match="requires a query"):
        await service.messages(
            None,
            None,
            query=None,
            cursor=None,
            limit=1,
            topic_id=None,
            include_raw=False,
        )
    with pytest.raises(ClitgError, match="does not support topics"):
        await service.messages(
            None,
            None,
            query="x",
            cursor=None,
            limit=1,
            topic_id=1,
            include_raw=False,
        )
    inbox = await service.inbox(
        None,
        view="messages",
        include_archived=False,
        cursor=None,
        limit=2,
    )
    assert inbox.next_cursor and inbox.items
    with pytest.raises(ClitgError, match="view"):
        await service.inbox(
            None,
            view="bad",
            include_archived=False,
            cursor=None,
            limit=1,
        )
    with pytest.raises(ClitgError, match="negative"):
        await service.inbox(
            None,
            view="messages",
            include_archived=False,
            cursor=None,
            limit=1,
            folder_id=-1,
        )
    with pytest.raises(ClitgError, match="earlier"):
        await service.inbox(
            None,
            view="messages",
            include_archived=False,
            cursor=None,
            limit=1,
            after=invalid_after,
            before=invalid_after,
        )
    context = await service.message_context(
        None,
        "me",
        1,
        before=1,
        after=1,
        include_raw=False,
    )
    assert context.items
    for before, after in ((-1, 0), (0, 101)):
        with pytest.raises(ClitgError, match="Context"):
            await service.message_context(
                None,
                "me",
                1,
                before=before,
                after=after,
                include_raw=False,
            )
    replies = await service.message_replies(
        None,
        "me",
        1,
        cursor=None,
        limit=2,
        include_raw=True,
    )
    assert replies.next_cursor


@pytest.mark.asyncio
async def test_export_conversation(service: ClitgService, tmp_path: Path) -> None:
    output = tmp_path / "export"
    result = await service.export_conversation(
        None,
        "me",
        output,
        limit=2,
        resume=False,
        download_media=False,
    )
    assert result.data["next_cursor"] and (output / "messages.jsonl").is_file()
    no_media_output = tmp_path / "no-media-export"
    assert (
        await service.export_conversation(
            None,
            "me",
            no_media_output,
            limit=1,
            resume=False,
            download_media=True,
        )
    ).data["count"] == 1
    resumed = await service.export_conversation(
        None,
        "me",
        output,
        limit=1,
        resume=True,
        download_media=False,
    )
    assert resumed.data["count"] == 1
    with pytest.raises(ClitgError, match="already exists"):
        await service.export_conversation(
            None,
            "me",
            output,
            limit=1,
            resume=False,
            download_media=False,
        )
    missing = tmp_path / "missing"
    missing.mkdir()
    with pytest.raises(ClitgError, match="manifest"):
        await service.export_conversation(
            None,
            "me",
            missing,
            limit=1,
            resume=True,
            download_media=False,
        )
    (missing / "manifest.json").write_text("{")
    with pytest.raises(ClitgError, match="manifest"):
        await service.export_conversation(
            None,
            "me",
            missing,
            limit=1,
            resume=True,
            download_media=False,
        )

    fake = cast(FakeTelegram, service.telegram)

    async def media_messages(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"id": 9, "has_media": True}]

    fake.messages = media_messages  # ty: ignore[invalid-assignment]
    media_output = tmp_path / "media-export"
    exported = await service.export_conversation(
        None,
        "me",
        media_output,
        limit=2,
        resume=False,
        download_media=True,
    )
    assert exported.items and exported.items[0]["exported_media"]

    async def failed_download(*args: Any) -> Path:
        raise ClitgError(ErrorCode.NETWORK, "failed")

    fake.download = failed_download  # ty: ignore[invalid-assignment]
    failed_output = tmp_path / "failed-media-export"
    failed = await service.export_conversation(
        None,
        "me",
        failed_output,
        limit=2,
        resume=False,
        download_media=True,
    )
    assert failed.items and failed.items[0]["media_error"].code == ErrorCode.NETWORK


@pytest.mark.asyncio
async def test_update_stream_and_checkpoints(service: ClitgService) -> None:
    for kwargs in (
        {"max_events": 0},
        {"idle_timeout": 0.0},
        {"total_timeout": 0.0},
        {"heartbeat": 0.0},
    ):
        values = {
            "max_events": 1,
            "idle_timeout": 1.0,
            "total_timeout": 1.0,
            "heartbeat": 1.0,
            **kwargs,
        }
        with pytest.raises(ClitgError, match="positive"):
            async for _ in service.watch_updates(
                None,
                event_types=set(),
                peers=set(),
                cursor=None,
                consumer_id=None,
                **values,
            ):
                pass
    records = [
        item
        async for item in service.watch_updates(
            None,
            event_types={"message.new"},
            peers={"me"},
            cursor=encode_cursor({"sequence": 3}),
            consumer_id="agent",
            max_events=1,
            idle_timeout=1,
            total_timeout=1,
            heartbeat=1,
        )
    ]
    assert len(records) == 1
    assert service.state.get_checkpoint("personal", "agent") == records[0]["cursor"]
    records = [
        item
        async for item in service.watch_updates(
            None,
            event_types=set(),
            peers=set(),
            cursor=None,
            consumer_id="agent",
            max_events=1,
            idle_timeout=1,
            total_timeout=1,
            heartbeat=1,
        )
    ]
    assert records
    records = [
        item
        async for item in service.watch_updates(
            None,
            event_types=set(),
            peers=set(),
            cursor=None,
            consumer_id=None,
            max_events=1,
            idle_timeout=1,
            total_timeout=1,
            heartbeat=1,
        )
    ]
    assert records and "cursor" in records[0]


@pytest.mark.asyncio
async def test_registered_operations_and_safety(service: ClitgService, tmp_path: Path) -> None:
    read = await service.execute_operation(
        None,
        "account.get",
        {"id": {"_": "InputUserSelf"}},
        dry_run=False,
        confirmation=None,
        confirmation_token=None,
        idempotency_key=None,
    )
    assert read.data["result"]
    with pytest.raises(ClitgError, match="not found"):
        await service.execute_operation(
            None,
            "missing.command",
            {},
            dry_run=False,
            confirmation=None,
            confirmation_token=None,
            idempotency_key=None,
        )
    with pytest.raises(ClitgError, match="do not use"):
        await service.execute_operation(
            None,
            "account.get",
            {"id": {"_": "InputUserSelf"}},
            dry_run=False,
            confirmation=None,
            confirmation_token=None,
            idempotency_key="read",
        )
    preview = await service.execute_operation(
        None,
        "contacts.add",
        {"id": "@user", "first_name": "User", "last_name": "", "phone": ""},
        dry_run=True,
        confirmation=None,
        confirmation_token=None,
        idempotency_key="write",
    )
    assert preview.data["dry_run"]
    written = await service.execute_operation(
        None,
        "contacts.add",
        {"id": "@user", "first_name": "User", "last_name": "", "phone": ""},
        dry_run=False,
        confirmation=None,
        confirmation_token=None,
        idempotency_key="write",
    )
    assert written.data["idempotent_replay"] is False
    replay = await service.execute_operation(
        None,
        "contacts.add",
        {"id": "@user", "first_name": "User", "last_name": "", "phone": ""},
        dry_run=False,
        confirmation=None,
        confirmation_token=None,
        idempotency_key="write",
    )
    assert replay.data["idempotent_replay"] is True
    with pytest.raises(ClitgError, match="--confirm"):
        await service.execute_operation(
            None,
            "contacts.delete",
            {"id": [{"_": "InputUserSelf"}]},
            dry_run=False,
            confirmation=None,
            confirmation_token=None,
            idempotency_key=None,
        )
    assert (
        await service.execute_operation(
            None,
            "contacts.delete",
            {"id": [{"_": "InputUserSelf"}]},
            dry_run=False,
            confirmation="contacts.delete",
            confirmation_token=None,
            idempotency_key=None,
        )
    ).data["result"]

    critical = await service.execute_operation(
        None,
        "chats.delete-channel",
        {"channel": "@repeat"},
        dry_run=True,
        confirmation=None,
        confirmation_token=None,
        idempotency_key="critical",
    )
    executed = await service.execute_operation(
        None,
        "chats.delete-channel",
        {"channel": "@repeat"},
        dry_run=False,
        confirmation="chats.delete-channel",
        confirmation_token=critical.data["confirmation_token"],
        idempotency_key="critical",
    )
    repeated = await service.execute_operation(
        None,
        "chats.delete-channel",
        {"channel": "@repeat"},
        dry_run=False,
        confirmation=None,
        confirmation_token=None,
        idempotency_key="critical",
    )
    assert not executed.data["idempotent_replay"] and repeated.data["idempotent_replay"]
    critical = await service.execute_operation(
        None,
        "chats.delete-channel",
        {"channel": "@group"},
        dry_run=True,
        confirmation=None,
        confirmation_token=None,
        idempotency_key=None,
    )
    token = critical.data["confirmation_token"]
    with pytest.raises(ClitgError, match="--confirm"):
        await service.execute_operation(
            None,
            "chats.delete-channel",
            {"channel": "@group"},
            dry_run=False,
            confirmation=None,
            confirmation_token=token,
            idempotency_key=None,
        )
    with pytest.raises(ClitgError, match="token"):
        await service.execute_operation(
            None,
            "chats.delete-channel",
            {"channel": "@group"},
            dry_run=False,
            confirmation="chats.delete-channel",
            confirmation_token=None,
            idempotency_key=None,
        )
    critical = await service.execute_operation(
        None,
        "chats.delete-channel",
        {"channel": "@group"},
        dry_run=True,
        confirmation=None,
        confirmation_token=None,
        idempotency_key=None,
    )
    assert (
        await service.execute_operation(
            None,
            "chats.delete-channel",
            {"channel": "@group"},
            dry_run=False,
            confirmation="chats.delete-channel",
            confirmation_token=critical.data["confirmation_token"],
            idempotency_key=None,
        )
    ).data["result"]

    promoted = await service.execute_operation(
        None,
        "chats.promote-channel",
        {"channel": "@group", "user_id": "@user", "role": "moderator"},
        dry_run=True,
        confirmation=None,
        confirmation_token=None,
        idempotency_key=None,
    )
    assert promoted.data["payload"]["params"]["admin_rights"]
    restricted = await service.execute_operation(
        None,
        "chats.restrict",
        {
            "channel": "@group",
            "participant": {"_": "InputPeerSelf"},
            "role": "restricted",
            "rights_overrides": {"send_media": True},
        },
        dry_run=True,
        confirmation=None,
        confirmation_token=None,
        idempotency_key=None,
    )
    assert restricted.data["payload"]["params"]["banned_rights"]["send_media"]
    group_admin = await service.execute_operation(
        None,
        "chats.promote-group",
        {"chat_id": 1, "user_id": "@user", "role": "admin", "rights_overrides": {}},
        dry_run=True,
        confirmation=None,
        confirmation_token=None,
        idempotency_key=None,
    )
    assert group_admin.data["payload"]["params"]["is_admin"]
    group_moderator = await service.execute_operation(
        None,
        "chats.promote-group",
        {"chat_id": 1, "user_id": "@user", "role": "moderator"},
        dry_run=True,
        confirmation=None,
        confirmation_token=None,
        idempotency_key=None,
    )
    assert group_moderator.data["payload"]["params"]["is_admin"]
    for command, role, overrides, match in (
        ("contacts.add", "admin", None, "not supported"),
        ("chats.promote-channel", "owner", None, "Unknown"),
        ("chats.promote-channel", "admin", "bad", "must be an object"),
        ("chats.promote-group", "admin", "bad", "must be an object"),
    ):
        params: dict[str, Any] = {"role": role}
        if overrides is not None:
            params["rights_overrides"] = overrides
        with pytest.raises(ClitgError, match=match):
            await service.execute_operation(
                None,
                command,
                params,
                dry_run=True,
                confirmation=None,
                confirmation_token=None,
                idempotency_key=None,
            )

    policy = tmp_path / "deny.json"
    policy.write_text('{"deny_commands":["account.get"]}')
    service.set_policy("personal", policy)
    with pytest.raises(ClitgError, match="policy"):
        await service.execute_operation(
            None,
            "account.get",
            {"id": {"_": "InputUserSelf"}},
            dry_run=False,
            confirmation=None,
            confirmation_token=None,
            idempotency_key=None,
        )
    service.set_policy("personal", None)
    policy.write_text('{"deny_commands":["messages.list"]}')
    service.set_policy("personal", policy)
    with pytest.raises(ClitgError, match="policy"):
        await service.messages(
            None,
            "me",
            query=None,
            cursor=None,
            limit=1,
            topic_id=None,
            include_raw=False,
        )
    service.set_policy("personal", None)


@pytest.mark.asyncio
async def test_batch_policy_and_audit(service: ClitgService, tmp_path: Path) -> None:
    operations = [
        BatchOperation(id="one", command="account.get", params={"id": {"_": "InputUserSelf"}}),
        BatchOperation(id="two", command="auth.sessions"),
    ]
    result = await service.batch(None, operations, concurrency=2, fail_fast=False)
    assert result.data["succeeded"] == 2
    assert (await service.batch(None, operations, concurrency=1, fail_fast=True)).data[
        "succeeded"
    ] == 2
    assert (await service.batch(None, [], concurrency=1, fail_fast=True)).data["count"] == 0
    with pytest.raises(ClitgError, match="Concurrency"):
        await service.batch(None, operations, concurrency=0, fail_fast=False)
    with pytest.raises(ClitgError, match="registered read"):
        await service.batch(
            None,
            [BatchOperation(id="write", command="contacts.add")],
            concurrency=1,
            fail_fast=False,
        )
    policy = tmp_path / "limited.json"
    policy.write_text('{"max_operations":1}')
    assert service.validate_policy(policy).data["valid"]
    assert service.set_policy("personal", policy).data.policy_file
    assert service.inspect_policy(None).data["policy"].max_operations == 1
    with pytest.raises(ClitgError, match="max_operations"):
        await service.batch(None, operations, concurrency=1, fail_fast=False)
    explained = service.explain_policy(None, "account.get", "read", None, None)
    assert explained.data["decision"]["allowed"]
    service.set_policy("personal", None)

    targets_policy = tmp_path / "targets.json"
    targets_policy.write_text('{"max_targets":1}')
    service.set_policy("personal", targets_policy)
    with pytest.raises(ClitgError, match="max_targets"):
        await service.batch(
            None,
            [
                BatchOperation(id="a", command="bots.inline", params={"peer": "one"}),
                BatchOperation(id="b", command="bots.inline", params={"peer": "two"}),
            ],
            concurrency=1,
            fail_fast=False,
        )
    service.set_policy("personal", None)

    original = service.execute_operation

    async def sometimes_fail(*args: Any, **kwargs: Any) -> Any:
        if args[1] == "auth.sessions":
            raise ClitgError(ErrorCode.NETWORK, "failed")
        return await original(*args, **kwargs)

    service.execute_operation = sometimes_fail  # ty: ignore[invalid-assignment]
    failed = await service.batch(None, operations, concurrency=1, fail_fast=True)
    assert failed.data["failed"] == 1

    service.record_audit("personal", "account.get", "r", ok=True, target="1")
    assert service.audit_records(10).items
    output = tmp_path / "audit" / "events.jsonl"
    assert service.export_audit(output, overwrite=False).data["count"] == 1
    with pytest.raises(ClitgError, match="exists"):
        service.export_audit(output, overwrite=False)
    assert service.export_audit(output, overwrite=True).data["path"]
