"""Schema-aware JSON codec for Telethon's generated TL API."""

from __future__ import annotations

import base64
import inspect
from datetime import datetime
from pathlib import Path
from typing import Any

from telethon import utils
from telethon.tl import alltlobjects
from telethon.tl.tlobject import TLObject, TLRequest

from clitg.catalog import UNSUPPORTED_METHODS, request_registry, risk_for
from clitg.errors import ClitgError
from clitg.models import ErrorCode
from clitg.serialization import to_jsonable


def _type_registry() -> dict[str, type[TLObject]]:
    registry: dict[str, type[TLObject]] = {}
    for candidate in alltlobjects.tlobjects.values():
        if inspect.isclass(candidate) and issubclass(candidate, TLObject):
            registry[candidate.__name__] = candidate
    return registry


class RawCodec:
    """Build requests from JSON and serialize generated TL objects."""

    def __init__(self) -> None:
        self.requests = request_registry()
        self.types = _type_registry()

    def request_class(self, method: str) -> type[TLRequest]:
        """Resolve a supported canonical method name."""

        if method in UNSUPPORTED_METHODS:
            raise ClitgError(
                ErrorCode.INVALID_INPUT,
                f"Method '{method}' is unsupported",
                details={"reason": UNSUPPORTED_METHODS[method]},
            )
        request_class = self.requests.get(method)
        if request_class is None:
            raise ClitgError(ErrorCode.NOT_FOUND, f"Raw method '{method}' was not found")
        return request_class

    async def decode_value(self, value: Any, client: Any | None, *, resolve: bool) -> Any:
        """Decode one JSON-compatible TL value."""

        if isinstance(value, list):
            return [await self.decode_value(item, client, resolve=resolve) for item in value]
        if not isinstance(value, dict):
            return value
        if "$bytes" in value:
            try:
                return base64.b64decode(value["$bytes"], validate=True)
            except (ValueError, TypeError) as exc:
                raise ClitgError(ErrorCode.INVALID_INPUT, "Invalid base64 byte value") from exc
        if "$datetime" in value:
            try:
                return datetime.fromisoformat(str(value["$datetime"]).replace("Z", "+00:00"))
            except ValueError as exc:
                raise ClitgError(ErrorCode.INVALID_INPUT, "Invalid RFC 3339 datetime") from exc
        if "$peer" in value:
            if not resolve:
                return value["$peer"]
            if client is None:
                raise ClitgError(
                    ErrorCode.INTERNAL, "A Telegram client is required to resolve peers"
                )
            return await client.get_input_entity(value["$peer"])
        if "$channel" in value:
            if not resolve:
                return value["$channel"]
            if client is None:
                raise ClitgError(
                    ErrorCode.INTERNAL, "A Telegram client is required to resolve channels"
                )
            return utils.get_input_channel(await client.get_entity(value["$channel"]))
        if "$user" in value:
            if not resolve:
                return value["$user"]
            if client is None:
                raise ClitgError(
                    ErrorCode.INTERNAL, "A Telegram client is required to resolve users"
                )
            return utils.get_input_user(await client.get_entity(value["$user"]))
        if "$upload" in value:
            path = Path(value["$upload"])
            if not path.is_file():
                raise ClitgError(ErrorCode.INVALID_INPUT, f"Upload file does not exist: {path}")
            if not resolve:
                return str(path)
            if client is None:
                raise ClitgError(
                    ErrorCode.INTERNAL, "A Telegram client is required to upload files"
                )
            return await client.upload_file(path)
        type_name = value.get("_")
        if type_name is None:
            return {
                key: await self.decode_value(item, client, resolve=resolve)
                for key, item in value.items()
            }
        constructor = self.types.get(str(type_name))
        if constructor is None:
            raise ClitgError(ErrorCode.INVALID_INPUT, f"Unknown TL constructor '{type_name}'")
        kwargs = {
            key: await self.decode_value(item, client, resolve=resolve)
            for key, item in value.items()
            if key != "_"
        }
        return self._construct(constructor, kwargs)

    async def build(
        self,
        method: str,
        params: dict[str, Any],
        client: Any | None = None,
        *,
        resolve: bool = True,
    ) -> TLRequest:
        """Validate and construct a request."""

        request_class = self.request_class(method)
        kwargs = {
            key: await self.decode_value(value, client, resolve=resolve)
            for key, value in params.items()
        }
        return self._construct(request_class, kwargs)

    @staticmethod
    def _construct(constructor: type[TLObject], kwargs: dict[str, Any]) -> Any:
        try:
            return constructor(**kwargs)
        except TypeError as exc:
            raise ClitgError(
                ErrorCode.INVALID_INPUT,
                f"Invalid parameters for {constructor.__name__}",
                details={"signature": str(inspect.signature(constructor))},
            ) from exc

    @staticmethod
    def serialize(value: Any) -> Any:
        """Serialize a raw result using stable JSON primitives."""

        return to_jsonable(value, raw=True)

    @staticmethod
    def risk(method: str) -> str:
        """Return the conservative risk classification."""

        return risk_for(method)
