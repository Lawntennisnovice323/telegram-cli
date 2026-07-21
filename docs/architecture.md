# Architecture

`clitg` separates the stable agent contract from Telegram's dynamic MTProto layer:

1. Typer parses explicit options and serializes operational results as JSON or JSONL.
2. `ClitgService` owns profile selection, policies, audit metadata, safety, idempotency, pagination,
   batches, checkpoints, and error translation.
3. `ProfileStore`, `CredentialStore`, and `StateStore` persist configuration, secret references,
   and content-free functional metadata.
4. `TelegramAdapter` owns Telethon clients, peer resolution, normalization, friendly operations,
   exports, and live updates.
5. `Operation` maps stable dedicated commands to generated Telegram requests.
6. `RawCodec` reflects Telethon's generated TL registry for methods without dedicated commands.

The offline test suite replaces the adapter and never opens a Telegram connection. Telethon values
are normalized before they cross the service boundary unless `--include-raw` or `raw invoke` is
explicit.

## Profiles, credentials, and sessions

Profiles contain an API ID, optional phone, optional policy path, and an opaque API-hash reference.
`CredentialStore` prefers a usable non-interactive operating-system keyring and falls back to a
private `0600` file. Legacy inline API hashes are migrated automatically and the profile is updated
atomically. Public profile views expose only a storage classification.

Each profile has its own Telethon SQLite session. Sessions, API hashes, login codes, passwords,
auth keys, and Telegram content are outside audit storage and structured diagnostics.

## Policies and mutation safety

A profile can reference one versioned JSON policy. Command, peer, mutation-risk, raw-method, and
raw-risk allow and deny rules are evaluated before Telegram access. Deny rules take precedence.
Batch operation and target limits are also policy controlled.

Mutations have a reviewed risk: write, destructive, or critical. All support dry-run. Destructive
operations require an exact confirmation. Critical operations additionally require a short-lived,
one-use, payload-bound token. Compatible mutations use the same 30-day idempotency contract.

## State

The auxiliary SQLite database stores pending logins, idempotency results, critical confirmations,
update checkpoints, and content-free audit records. Audit records contain only command metadata,
never request payloads or message content. State pruning is explicit and confirmed.

## Streaming and exports

`updates watch` emits JSONL items followed by a terminal summary or error. Known Telegram updates
use stable event types, while other updates retain a normalized raw fallback. Optional consumer IDs
persist opaque cursors after successful emission.

Conversation export appends normalized JSONL messages and writes a manifest containing the next
cursor. Optional media downloads live below the export directory. Resume is explicit and an
existing export is never overwritten implicitly.

## Generated contracts

`uv run python -m clitg.catalog` regenerates the checked-in capability and JSON Schema artifacts.
The generator enumerates every `TLRequest` in Telethon's installed layer, applies dedicated command
mappings and unsupported overrides, and assigns a conservative risk. Unknown methods remain
critical in execution.
