from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import pytest
from telethon.errors import FloodWaitError, RPCError

from clitg.errors import ClitgError
from clitg.models import ErrorCode, Profile
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
    assert service.state_counts().data == {"logins": 0, "idempotency": 0, "confirmations": 0}
    with pytest.raises(ClitgError, match="Invalid state"):
        service.prune_state("bad", None, dry_run=False, confirmation=None)
    assert service.prune_state("all", None, dry_run=True, confirmation=None).data["dry_run"]
    with pytest.raises(ClitgError, match="--confirm"):
        service.prune_state("all", None, dry_run=False, confirmation=None)
    assert service.prune_state("all", None, dry_run=False, confirmation="state.prune").data[
        "deleted"
    ]
    assert ClitgService.version().data["schema_version"] == "0.1"
