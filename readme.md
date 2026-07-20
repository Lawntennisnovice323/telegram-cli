# clitg: Telegram CLI for AI agents

Give your AI agent a real, scriptable interface to your Telegram user account. `clitg` can read
conversations, find contacts, send and edit messages, transfer files, manage polls and scheduled
messages, inspect forum topics, and reach the wider MTProto API, all through deterministic commands
and structured JSON.

`clitg` is built for agent workflows powered by **Claude Code**, **OpenAI Codex**, **Google
Antigravity**, **GitHub Copilot**, **xAI Grok**, **Cursor**, **Amp**, and any other AI agent that can
execute shell commands and consume JSON or JSONL. It is an unofficial Telegram client for user
accounts, powered by Telethon; it is not a Bot API wrapper and does not require a BotFather token.

## Turn Telegram into an agent tool

- **Agent-native I/O:** explicit arguments in, versioned JSON or streaming JSONL out, with no interactive
  prompts to block an automation.
- **Your full user account:** work with private chats, Saved Messages, groups, channels, contacts,
  media, reactions, polls, scheduled messages, and forum topics wherever Telegram permits it.
- **A large escape hatch:** use the schema-aware raw MTProto gateway when a dedicated command does
  not exist, backed by a generated capability catalog.
- **Guardrails for real accounts:** preview mutations with dry-run, require explicit confirmation
  for destructive actions, protect critical raw calls with short-lived tokens, and avoid duplicate
  sends with idempotency keys.
- **Discoverable by agents:** ship `clitg` together with an installable Agent Skill and
  machine-readable help, schemas, errors, cursors, and capability metadata.

Use it to build inbox assistants, Telegram research agents, notification and follow-up workflows,
message triage, personal knowledge capture, scheduled delivery, media pipelines, or your own
Telegram automation layer without designing another integration protocol.

> [!IMPORTANT]
> A Telethon session grants access to the associated Telegram account. Never commit, upload, or
> share session files. `clitg` stores them outside the repository using platform-specific user data
> directories and restrictive permissions.

## What you get

- Multiple isolated user-account profiles.
- Phone, login-code, and optional 2FA authentication without prompts.
- Dialog, contact, group, channel, and message discovery.
- Text, replies, forwarding, editing, deletion, read acknowledgements, reactions, pins, files,
  albums, voice notes, stickers, polls, scheduled messages, and forum topics.
- A schema-aware raw MTProto gateway for methods without dedicated commands.
- JSON Schema and capability catalogs designed for AI agents.
- Dry-run, explicit destructive confirmation, critical one-use tokens, and local idempotency.

Bots, QR/passkey login, live update streaming, calls, and secret-chat encryption are not supported
in v0.1.

## Quick start

Install [uv](https://docs.astral.sh/uv/) and then install the published tool:

```bash
uv tool install clitg
clitg --version
```

`clitg` requires Python 3.14. uv downloads a compatible interpreter automatically unless managed
Python downloads have been disabled.

For development:

```bash
git clone https://github.com/leynier/telegram-cli.git
cd telegram-cli
uv sync --all-groups
uv run clitg --version
```

The project itself, dependencies, and lockfile are managed with `uv init`, `uv add`, `uv remove`,
and `uv lock`. Do not edit dependency arrays manually.

## Install the Agent Skill

The repository includes a `clitg` skill for the open Agent Skills ecosystem. Install it with either
the npm or Bun runner:

```bash
# npm / Node.js
npx skills add leynier/telegram-cli --skill clitg

# Bun
bunx skills add leynier/telegram-cli --skill clitg
```

You can also target a specific supported agent and install globally without prompts:

```bash
npx skills add leynier/telegram-cli --skill clitg --agent claude-code -g -y
bunx skills add leynier/telegram-cli --skill clitg --agent codex -g -y
```

The open [`skills` CLI](https://github.com/vercel-labs/skills) supports Claude Code, Codex,
Antigravity, GitHub Copilot, Cursor, Amp, and many other agents. `clitg` itself remains
agent-agnostic, so Grok and other shell-capable agents can call the same structured CLI even when
they use a different skill-loading mechanism.

The skill teaches an agent the command contract and safety rules, but deliberately does not install
the executable. If `clitg` is missing, it reports `uv tool install clitg` and stops.

## Get your Telegram App ID and API hash

Telegram user-account clients need an application identity. This is different from a Telegram bot
token. Obtain it from Telegram's official developer portal:

1. Open [my.telegram.org/apps](https://my.telegram.org/apps).
2. Enter your phone number in international format and select **Next**.
3. Enter the confirmation code Telegram sends inside the Telegram app, not by SMS.
4. Open **API development tools**.
5. Complete the application form with an app title, short name, and platform.
6. Copy **App api_id** into `CLITG_API_ID` and **App api_hash** into `CLITG_API_HASH`.

Treat the API hash like a password: never publish it, paste it into an issue, or commit it to Git.
Set the credentials locally:

```bash
export CLITG_API_ID='12345678'
export CLITG_API_HASH='your-private-api-hash'
export CLITG_PHONE='+15551234567'
```

Create a local profile without exposing the hash in shell arguments:

```bash
clitg profiles create \
  --name personal \
  --default
```

Credential values can come from explicit options, secret files, or `CLITG_API_ID`,
`CLITG_API_HASH`, `CLITG_PHONE`, `CLITG_CODE`, and `CLITG_PASSWORD`. Direct options take
precedence. Login codes and 2FA passwords are never persisted.

Request the login code and finish the resumable login flow. Telegram delivers the code inside your
Telegram app. Accounts with two-step verification also need `--password-file`:

```bash
clitg --profile personal auth request-code --phone +15551234567
clitg --profile personal auth verify \
  --login-id '<login-id-from-the-first-command>' \
  --code-file ./telegram-code.txt \
  --password-file ./telegram-2fa.txt
clitg --profile personal auth status
```

After authentication, try a read-only command or send a controlled message to Saved Messages:

```bash
clitg --profile personal dialogs list --limit 10
clitg --profile personal messages send --peer me --text 'Hello from my AI agent' --dry-run
```

## Structured output

Every operational command writes one envelope to stdout:

```json
{
  "schema_version": "0.1",
  "ok": true,
  "data": {},
  "error": null,
  "meta": {
    "command": "messages.list",
    "profile": "personal",
    "request_id": "...",
    "next_cursor": null
  }
}
```

Failures use the same envelope and a nonzero exit code. `--output jsonl` emits `item` records and
always ends with `summary` or `error`. Human help remains available with `--help`; agents can use
`--help-json`, `schema`, and `capabilities`.

`clitg help` is equivalent to `clitg --help`, and `clitg version` is equivalent to
`clitg --version`.

Global options must precede the command group:

```bash
clitg --profile personal --output jsonl messages list --peer @example --limit 25
```

Opaque cursors are returned in `meta.next_cursor` and can be passed back with `--cursor`. Listing or
searching messages never marks them read; use `messages read` explicitly.

Exit codes are stable within schema `0.1`:

| Code | Meaning |
| ---: | --- |
| 0 | Success |
| 1 | Internal error |
| 2 | Invalid input or CLI usage |
| 3 | Profile or authentication error |
| 4 | Missing or ambiguous entity |
| 5 | Conflict or missing confirmation |
| 6 | Telegram permission failure |
| 7 | Telegram rate limit |
| 8 | Telegram RPC or network failure |

## Messaging

Read and search without changing read state:

```bash
clitg --profile personal dialogs list --limit 50
clitg --profile personal messages list --peer @example --limit 50
clitg --profile personal messages search --peer @example --query invoice
clitg --profile personal messages get --peer @example --message-id 123
```

Plain text is the default. Markdown or HTML must be explicit:

```bash
clitg --profile personal messages send \
  --peer @example \
  --text '**Status:** complete' \
  --parse-mode markdown \
  --idempotency-key job-42 \
  --dry-run

clitg --profile personal messages send \
  --peer @example \
  --text '**Status:** complete' \
  --parse-mode markdown \
  --idempotency-key job-42
```

Text and raw JSON accept a literal option, a file, or stdin as mutually exclusive sources. Repeat
`--file` to send an album. Use `--media-kind voice`, `sticker`, or `document` when inference is not
appropriate. `--schedule-at` requires RFC 3339 with an offset.

Destructive operations require an exact intention:

```bash
clitg --profile personal messages delete \
  --peer @example \
  --message-id 123 \
  --scope everyone \
  --dry-run

clitg --profile personal messages delete \
  --peer @example \
  --message-id 123 \
  --scope everyone \
  --confirm messages.delete
```

Downloads require an explicit destination and never overwrite implicitly:

```bash
clitg --profile personal media download \
  --peer @example \
  --message-id 123 \
  --output ./downloads/document.pdf \
  --create-dirs
```

## Raw MTProto gateway

Inspect support first:

```bash
clitg capabilities get --method messages.getHistory
clitg --profile personal raw invoke \
  --method help.getConfig \
  --params '{}' \
  --allow-raw \
  --dry-run
```

Nested TL constructors use an `_` discriminator. Special values include `$peer`, `$bytes`,
`$datetime`, and `$upload`:

```json
{
  "peer": {"$peer": "@example"},
  "offset_id": 0,
  "offset_date": null,
  "add_offset": 0,
  "limit": 10,
  "max_id": 0,
  "min_id": 0,
  "hash": 0
}
```

All raw calls require `--allow-raw`. Destructive calls additionally require
`--confirm <method>`. Critical or unclassified methods require a dry-run-generated
`--confirmation-token`; the token is payload-bound, single-use, and valid for five minutes.

The checked-in `schemas/capabilities.json` classifies every request in the installed Telethon
layer. `schemas/schemas.json` contains the public Pydantic schemas. CI rejects drift after a
Telethon or model update.

## Local state

`clitg state get` reports counts only. No message-content audit log is created. Idempotency state is
retained until explicitly pruned:

```bash
clitg state prune --kind idempotency --dry-run
clitg state prune --kind idempotency --confirm state.prune
```

Pending logins expire with Telegram. Critical confirmation tokens expire after five minutes.

## Development quality gates

```bash
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest --cov=clitg --cov-branch --cov-fail-under=100
uv run python -m clitg.catalog
git diff --exit-code -- schemas
uv build --no-sources
```

The normal suite uses fakes and never needs personal Telegram credentials. A separate manual,
secret-gated workflow targets Telegram Test DC.

## Terms and privacy

`clitg` is an unofficial third-party client and is not affiliated with Telegram. Operators are
responsible for complying with the [Telegram API Terms of Service](https://core.telegram.org/api/terms),
including privacy, consent, branding, automation, and content/AI restrictions. The CLI does not
attempt to bypass read receipts, rate limits, permissions, or other platform behavior.

## License

MIT. See [LICENSE](LICENSE).
