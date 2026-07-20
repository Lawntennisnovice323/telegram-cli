# Architecture

`clitg` separates the public command contract from Telegram's dynamic API:

1. Typer parses explicit options and serializes every operational result.
2. `ClitgService` owns profile selection, safety, idempotency, pagination, and error translation.
3. `ProfileStore` and `StateStore` persist local configuration and functional metadata.
4. `TelegramAdapter` contains Telethon-specific behavior.
5. `RawCodec` reflects Telethon's generated TL classes for methods without dedicated commands.

The normal test suite replaces the adapter and never opens a network connection. Telethon objects
are normalized before they cross the service boundary unless the caller explicitly requests raw
data.

## State

Profiles hold `api_id`, `api_hash`, optional phone, and a per-profile Telethon SQLite session.
Auxiliary SQLite tables hold pending logins, idempotency records, and critical confirmations. There
is no content audit table.

## Generated contracts

`python -m clitg.catalog` regenerates the checked-in capability and JSON Schema artifacts. The
capability generator enumerates every `TLRequest` in Telethon's installed layer, applies dedicated
command mappings and explicit unsupported overrides, then assigns a conservative risk. Unknown
methods are operationally critical.
