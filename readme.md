# clitg: Telegram CLI for AI agents

Give an AI agent a deterministic interface to a real Telegram user account. `clitg` reads inboxes,
searches conversations, sends and manages messages, works with groups, channels, contacts, stories,
polls, topics, folders, bots, and media, and exposes the wider MTProto API through structured JSON.

`clitg` is designed for workflows powered by **Claude Code**, **OpenAI Codex**, **Google
Antigravity**, **GitHub Copilot**, **xAI Grok**, **Cursor**, **Amp**, and every other AI agent that can
run a command and consume JSON or JSONL. It is an unofficial Telegram client for user accounts,
powered by Telethon. It is not a Bot API wrapper and does not use a BotFather token.

## Why agents use clitg

- **No prompts:** every value comes from an option, environment variable, file, or explicitly
  selected stdin.
- **Structured contracts:** successes and failures use versioned JSON envelopes. Lists and live
  updates support JSONL.
- **Broad Telegram coverage:** dedicated commands cover common user actions, while the generated
  MTProto gateway provides a conservative escape hatch.
- **Safety for real accounts:** dry-run previews, exact destructive confirmations, one-use critical
  tokens, local policies, idempotency keys, and content-free audit metadata.
- **Automation primitives:** filtered inboxes, account-wide search, resumable exports, update
  checkpoints, and bounded read-only batches.
- **Agent discovery:** machine-readable command, schema, capability, error, cursor, risk, and skill
  metadata are part of the product.

Build inbox assistants, Telegram research agents, personal knowledge capture, follow-up workflows,
scheduled delivery, moderation tools, media pipelines, or your own account automation without
inventing another protocol.

> [!IMPORTANT]
> A Telethon session grants access to its Telegram account. Never commit, upload, or share session
> files. `clitg` stores sessions and credentials outside the repository with restrictive
> permissions.

## Install

Install [uv](https://docs.astral.sh/uv/) and then install the published CLI:

```bash
uv tool install clitg
clitg version
```

`clitg` 0.2 requires Python 3.14. uv can install the compatible interpreter automatically.

For local development:

```bash
git clone https://github.com/leynier/telegram-cli.git
cd telegram-cli
uv sync --all-groups
uv run clitg version
```

The project metadata and lockfile are managed with `uv init`, `uv add`, `uv remove`, and `uv lock`.

## Install the Agent Skill

The repository ships an Agent Skill that teaches compatible agents how to operate `clitg` safely.
Install it with the npm or Bun runner:

```bash
npx skills add leynier/telegram-cli --skill clitg
bunx skills add leynier/telegram-cli --skill clitg
```

Target an agent and install globally without prompts when desired:

```bash
npx skills add leynier/telegram-cli --skill clitg --agent claude-code -g -y
bunx skills add leynier/telegram-cli --skill clitg --agent codex -g -y
```

The open [`skills` CLI](https://github.com/vercel-labs/skills) supports Claude Code, Codex,
Antigravity, GitHub Copilot, Cursor, Amp, and other agents. Grok and any shell-capable agent can use
the same CLI contract even if it loads skills through another mechanism. The skill does not install
the executable. If `clitg` is missing, it tells the operator to run `uv tool install clitg`.

## Get a Telegram App ID and API hash

Telegram user-account clients need an application identity. This is different from a Telegram bot
token.

1. Open Telegram's official portal at [my.telegram.org/apps](https://my.telegram.org/apps).
2. Enter the account phone number in international format.
3. Enter the confirmation code delivered inside the Telegram app.
4. Open **API development tools**.
5. Create an application with a title, short name, and platform.
6. Copy **App api_id** and **App api_hash** into local environment variables.

```bash
export CLITG_API_ID='12345678'
export CLITG_API_HASH='your-private-api-hash'
export CLITG_PHONE='+15551234567'
```

Treat the API hash as a secret. Never paste it into an issue, log it, or commit it. Create a profile
without placing the hash in the process arguments:

```bash
clitg profiles create --name personal --default
```

The API hash is stored in the operating-system keyring when a usable non-interactive backend is
available. Otherwise, `clitg` uses a private file with mode `0600`. Existing 0.1 profiles containing
an inline API hash are migrated automatically and atomically the next time they are used.
`profiles list` and `profiles get` expose only the storage classification, never the secret.

Values can come from explicit options, secret files, or `CLITG_API_ID`, `CLITG_API_HASH`,
`CLITG_PHONE`, `CLITG_CODE`, and `CLITG_PASSWORD`. Explicit options take precedence. Login codes and
2FA passwords are never persisted.

## Authenticate without prompts

Use the resumable phone-code flow:

```bash
clitg --profile personal auth request-code --phone +15551234567
clitg --profile personal auth verify \
  --login-id '<login-id>' \
  --code-file ./telegram-code.txt \
  --password-file ./telegram-2fa.txt
clitg --profile personal auth status
```

Telegram normally delivers the code inside its app. The password file is needed only when the
account has two-step verification enabled. Delete temporary secret files after use.

Alternatively, create a QR image and wait for the Telegram mobile app to scan it:

```bash
clitg --profile personal auth qr-login \
  --qr-output ./telegram-login.png \
  --timeout 120
```

Open Telegram on the phone, go to **Settings**, **Devices**, **Link Desktop Device**, then scan the
generated image before the timeout. The command remains non-interactive.

## Structured output contract

Every normal operation writes one envelope to stdout:

```json
{
  "schema_version": "0.2",
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
ends with `summary` or `error`. Operational errors stay on stdout. Redacted diagnostics use stderr
only when `--verbose` is explicit.

`clitg help` and `clitg --help` are equivalent. `clitg version` and `clitg --version` are also
equivalent. Agents can discover contracts with:

```bash
clitg --help-json
clitg commands list
clitg commands get --command stories.publish
clitg schema list
clitg capabilities get --method stories.sendStory
```

Global options precede the command group:

```bash
clitg --profile personal --output jsonl messages list --peer @example --limit 25
```

Opaque cursors can be returned in `meta.next_cursor`. Pass them back unchanged with `--cursor`.
Listing, searching, exporting, and inspecting context never mark messages read.

Exit codes are stable within schema 0.2:

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

## Inbox, search, context, and export

Read a filtered unread inbox as messages or dialog summaries:

```bash
clitg --profile personal inbox list \
  --view messages \
  --peer @example \
  --from @alice \
  --folder-id 0 \
  --after 2026-07-01T00:00:00Z \
  --before 2026-08-01T00:00:00Z \
  --media-only
```

Search one conversation or the entire account. Omit `--peer` for global search:

```bash
clitg --profile personal messages search --peer @example --query invoice
clitg --profile personal messages search \
  --query invoice \
  --from @alice \
  --after 2026-01-01T00:00:00Z \
  --media-only
```

Recover surrounding context, replies, or a resumable export:

```bash
clitg --profile personal messages context --peer @example --message-id 123 --before 10 --after 10
clitg --profile personal messages replies --peer @example --message-id 123
clitg --profile personal messages export --peer @example --output ./exports/example
clitg --profile personal messages export --peer @example --output ./exports/example --resume
```

Add `--download-media` to export media into the export directory. Existing exports require
`--resume`; an accidental overwrite is rejected.

## Send and mutate safely

Plain text is the default. Markdown or HTML must be explicit:

```bash
clitg --profile personal messages send \
  --peer me \
  --text '**Status:** complete' \
  --parse-mode markdown \
  --idempotency-key job-42 \
  --dry-run

clitg --profile personal messages send \
  --peer me \
  --text '**Status:** complete' \
  --parse-mode markdown \
  --idempotency-key job-42
```

Text and JSON accept a literal value, a file, or explicitly selected stdin as mutually exclusive
sources. Repeat `--file` for albums. Use `--media-kind voice`, `sticker`, or `document` when needed.
`--schedule-at` requires RFC 3339 with an offset.

Every compatible mutation accepts `--idempotency-key`. Reusing the same key and payload returns the
stored result with `idempotent_replay: true`. Changing the payload under an existing key is a
conflict. Records expire after 30 days.

Destructive operations require the exact confirmation:

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
  --confirm messages.delete \
  --idempotency-key delete-123
```

Critical operations also require the payload-bound token returned by dry-run. Tokens are single
use and expire after five minutes.

## Dedicated Telegram actions

The 0.2 command registry adds stable actions for:

- account details, privacy rules, and active authorization sessions;
- bot starts, callbacks, and inline queries;
- group and channel creation, editing, descriptions, photos, usernames, membership, administration,
  restrictions, invites, joins, leaves, participants, and admin logs;
- contact creation, deletion, blocking, and unblocking;
- dialog archive, pin, mute, unread, draft, and folder organization;
- GIFs, stickers, contact cards, locations, venues, and live locations;
- invite links and join request moderation;
- reactions, polls, Saved Messages, scheduled messages, stories, and forum topics.

Registered actions use a stable command name and structured MTProto parameters. Inspect the exact
signature, risk, and method before constructing a payload:

```bash
clitg commands get --command chats.create-channel
clitg --profile personal chats create-channel \
  --params '{"title":"Agent Updates","about":"Generated by clitg","broadcast":true,"megagroup":false}' \
  --dry-run
```

Friendly strings in peer, channel, and user fields are resolved safely. TL constructors still use
the `_` discriminator when a nested generated type is required.

Calls, secret chats, payments, account-security mutations, session revocation, and mutation batches
are intentionally excluded from dedicated 0.2 commands.

## Live updates with JSONL

Stream normalized message events and preserve a checkpoint by consumer ID:

```bash
clitg --profile personal --output jsonl updates watch \
  --event message.new \
  --event message.edited \
  --peer @example \
  --consumer-id inbox-agent \
  --max-events 100 \
  --idle-timeout 30 \
  --timeout 300 \
  --heartbeat 15
```

Known updates use stable event types. Other Telegram updates are retained as
`telegram.raw_update`. Each item carries an opaque cursor. A consumer checkpoint is updated only
after an item is emitted.

## Local authorization policy

Attach a versioned JSON policy to a profile to constrain agents locally. Deny rules always take
precedence over allow rules.

```json
{
  "policy_version": "0.1",
  "allow_commands": ["dialogs.*", "inbox.*", "messages.*", "account.get"],
  "deny_commands": ["messages.delete"],
  "allow_peers": ["me", "@trusted_*"],
  "deny_peers": ["@blocked"],
  "allow_mutation_risks": ["write"],
  "allow_raw_methods": ["help.*"],
  "deny_raw_methods": [],
  "allow_raw_risks": ["read"],
  "max_operations": 100,
  "max_targets": 25
}
```

```bash
clitg policy validate --file examples/policy.json
clitg policy set --name personal --file examples/policy.json
clitg --profile personal policy get
clitg --profile personal policy explain --command messages.send --risk write --peer me
```

Clear the attached policy with `clitg policy set --name personal`.

## Read-only batch execution

Batch input is JSONL. Only registered read operations are accepted, concurrency is bounded from 1
to 10, and output order matches input order.

```jsonl
{"id":"account","command":"account.get","params":{"id":{"_":"InputUserSelf"}}}
{"id":"sessions","command":"auth.sessions","params":{}}
```

```bash
clitg --profile personal batch run --input examples/read-batch.jsonl --concurrency 2
```

Use `--fail-fast` for sequential stop-on-error behavior. Policies can cap operation and target
counts. Mutation batches are rejected.

## Content-free audit metadata

Operational commands record timestamp, profile name, command, request ID, optional target, success,
and error code. Message text, raw parameters, API hashes, codes, passwords, auth keys, and session
material are never recorded.

```bash
clitg audit list --limit 100
clitg audit export --output ./audit.jsonl
clitg audit prune --before 2026-07-01T00:00:00Z --dry-run
clitg audit prune --before 2026-07-01T00:00:00Z --confirm audit.prune
```

## Raw MTProto gateway

Prefer a dedicated command. When one does not exist, inspect the method first:

```bash
clitg capabilities get --method help.getConfig
clitg --profile personal raw invoke \
  --method help.getConfig \
  --params '{}' \
  --allow-raw \
  --dry-run
```

Special JSON values include `$peer`, `$channel`, `$user`, `$bytes`, `$datetime`, and `$upload`:

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

All raw calls require `--allow-raw`. Destructive calls also require `--confirm <method>`. Critical
or unclassified calls require a dry-run token bound to the profile, method, and payload. Unknown raw
methods remain critical until reviewed.

The generated `schemas/capabilities.json` classifies every request in the installed Telethon layer.
`schemas/schemas.json` contains public JSON Schemas and the command manifest.

## Development quality gates

```bash
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest --cov=clitg --cov-branch --cov-fail-under=100
uv run python scripts/check_skill.py
uv run python -m clitg.catalog
uv build --no-sources
```

`make check` runs Ruff formatting, Ruff lint, and ty. `make tests` runs those checks plus the full
coverage gate. The normal suite is offline and deterministic. A separate protected workflow runs a
minimal send, edit, and delete lifecycle against Telegram Test DC when its credentials are present.

## Terms and privacy

`clitg` is an unofficial third-party client and is not affiliated with Telegram. Operators are
responsible for the [Telegram API Terms of Service](https://core.telegram.org/api/terms), including
privacy, consent, branding, automation, and content or AI restrictions. The CLI does not bypass
read receipts, rate limits, permissions, or Telegram behavior.

## License

MIT. See [LICENSE](LICENSE).
