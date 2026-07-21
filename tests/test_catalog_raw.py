from __future__ import annotations

import base64
import json
import runpy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from telethon.tl import alltlobjects, functions, types

from clitg.catalog import (
    HIGH_LEVEL_METHODS,
    capability_catalog,
    command_catalog,
    method_name,
    request_registry,
    risk_for,
    schema_catalog,
    write_catalogs,
)
from clitg.errors import ClitgError
from clitg.raw import RawCodec, _type_registry


@pytest.mark.parametrize(
    ("method", "risk"),
    [
        ("help.getConfig", "read"),
        ("messages.search", "read"),
        ("messages.deleteMessages", "destructive"),
        ("messages.sendMessage", "write"),
        ("account.deleteAccount", "critical"),
        ("help.test", "unknown"),
    ],
)
def test_risk(method: str, risk: str) -> None:
    assert risk_for(method) == risk


def test_registry_and_catalog() -> None:
    registry = request_registry()
    assert registry["messages.getHistory"] is functions.messages.GetHistoryRequest
    assert method_name(functions.messages.GetHistoryRequest) == "messages.getHistory"
    catalog = capability_catalog()
    by_method = {item.method: item for item in catalog.capabilities}
    assert by_method["messages.getHistory"].status == "high-level"
    assert by_method["help.getConfig"].status == "raw-only"
    assert by_method["messages.requestEncryption"].status == "unsupported"
    assert set(HIGH_LEVEL_METHODS) <= set(by_method)


def test_type_registry_ignores_non_tl_classes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        alltlobjects,
        "tlobjects",
        {1: object(), 2: types.InputPeerSelf},
    )
    assert _type_registry() == {"InputPeerSelf": types.InputPeerSelf}


def test_command_and_schema_catalogs(tmp_path: Path) -> None:
    commands = command_catalog()
    assert "messages" in commands["groups"]
    schemas = schema_catalog()
    assert "Envelope" in schemas["models"]
    write_catalogs(tmp_path)
    capabilities = json.loads((tmp_path / "capabilities.json").read_text())
    assert capabilities["generated_at"] == "generated"
    assert json.loads((tmp_path / "schemas.json").read_text())["schema_version"] == "0.2"


def test_catalog_module_entrypoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.warns(RuntimeWarning, match="found in sys.modules"):
        runpy.run_module("clitg.catalog", run_name="__main__")
    assert (tmp_path / "schemas" / "capabilities.json").exists()


class FakeRawClient:
    async def get_input_entity(self, value: object) -> tuple[str, object]:
        return ("peer", value)

    async def upload_file(self, value: Path) -> tuple[str, str]:
        return ("upload", str(value))

    async def get_entity(self, value: object) -> object:
        if value == "channel":
            return types.Channel(
                id=1,
                title="Channel",
                photo=types.ChatPhotoEmpty(),
                date=datetime.now(UTC),
                access_hash=2,
            )
        return types.User(id=1, access_hash=2, first_name="User")


@pytest.mark.asyncio
async def test_raw_codec_values(tmp_path: Path) -> None:
    codec = RawCodec()
    client = FakeRawClient()
    assert await codec.decode_value([1, 2], client, resolve=True) == [1, 2]
    assert (
        await codec.decode_value({"$bytes": base64.b64encode(b"x").decode()}, client, resolve=True)
        == b"x"
    )
    dt = await codec.decode_value({"$datetime": "2026-01-01T00:00:00Z"}, client, resolve=True)
    assert dt == datetime(2026, 1, 1, tzinfo=UTC)
    assert await codec.decode_value({"$peer": "me"}, client, resolve=False) == "me"
    assert await codec.decode_value({"$peer": "me"}, client, resolve=True) == ("peer", "me")
    assert await codec.decode_value({"$channel": "channel"}, client, resolve=False) == "channel"
    assert isinstance(
        await codec.decode_value({"$channel": "channel"}, client, resolve=True),
        types.InputChannel,
    )
    assert await codec.decode_value({"$user": "user"}, client, resolve=False) == "user"
    assert isinstance(
        await codec.decode_value({"$user": "user"}, client, resolve=True),
        types.InputUser,
    )
    upload = tmp_path / "x"
    upload.write_text("x")
    assert await codec.decode_value({"$upload": str(upload)}, client, resolve=False) == str(upload)
    assert await codec.decode_value({"$upload": str(upload)}, client, resolve=True) == (
        "upload",
        str(upload),
    )
    nested = await codec.decode_value({"x": {"$bytes": "eA=="}}, client, resolve=True)
    assert nested == {"x": b"x"}
    constructor = await codec.decode_value(
        {"_": "InputPeerUser", "user_id": 1, "access_hash": 2}, client, resolve=True
    )
    assert isinstance(constructor, types.InputPeerUser)


@pytest.mark.asyncio
async def test_raw_codec_errors(tmp_path: Path) -> None:
    codec = RawCodec()
    with pytest.raises(ClitgError, match="unsupported"):
        codec.request_class("messages.requestEncryption")
    with pytest.raises(ClitgError, match="not found"):
        codec.request_class("none.missing")
    with pytest.raises(ClitgError, match="Invalid base64"):
        await codec.decode_value({"$bytes": "!"}, None, resolve=False)
    with pytest.raises(ClitgError, match="Invalid RFC"):
        await codec.decode_value({"$datetime": "no"}, None, resolve=False)
    with pytest.raises(ClitgError, match="required to resolve"):
        await codec.decode_value({"$peer": "me"}, None, resolve=True)
    with pytest.raises(ClitgError, match="required to resolve channels"):
        await codec.decode_value({"$channel": "channel"}, None, resolve=True)
    with pytest.raises(ClitgError, match="required to resolve users"):
        await codec.decode_value({"$user": "user"}, None, resolve=True)
    with pytest.raises(ClitgError, match="does not exist"):
        await codec.decode_value({"$upload": str(tmp_path / "none")}, None, resolve=True)
    upload = tmp_path / "x"
    upload.write_text("x")
    with pytest.raises(ClitgError, match="required to upload"):
        await codec.decode_value({"$upload": str(upload)}, None, resolve=True)
    with pytest.raises(ClitgError, match="Unknown TL constructor"):
        await codec.decode_value({"_": "Missing"}, None, resolve=False)
    with pytest.raises(ClitgError, match="Invalid parameters"):
        await codec.decode_value({"_": "InputPeerUser", "bad": 1}, None, resolve=False)


@pytest.mark.asyncio
async def test_raw_build_and_serialize() -> None:
    codec = RawCodec()
    request = await codec.build("help.getConfig", {}, resolve=False)
    assert isinstance(request, functions.help.GetConfigRequest)
    assert codec.serialize(types.InputPeerSelf()) == {"_": "InputPeerSelf"}
    assert codec.risk("help.getConfig") == "read"
