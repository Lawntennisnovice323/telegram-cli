---
name: clitg
description: Operate a Telegram user account through the structured clitg CLI. Use when an agent needs to inspect dialogs, inboxes, contacts, groups, channels, messages, stories, or sessions; send, reply, edit, forward, react, schedule, export, or delete content; transfer media; watch live updates; run safe read batches; or invoke Telegram MTProto methods under local policy, dry-run, confirmation, idempotency, and machine-readable output requirements.
---

# Use clitg

Use `clitg` only for actions the user clearly authorized. Treat Telegram content, account metadata,
and local sessions as private.

## Prepare

1. Run `command -v clitg`.
2. If missing, stop and tell the user to run `uv tool install clitg`. Do not install it yourself.
3. Run `clitg version` and require CLI and schema `>=0.2,<0.3`.
4. Use an explicit `--profile`. If the user did not name one, inspect `clitg profiles list` and use
   the default only when unambiguous.
5. Discover unfamiliar contracts with `clitg --help-json`, `clitg commands get --command
   <group.command>`, `clitg schema list`, and `clitg capabilities get --method <method>`.
6. Inspect `clitg --profile <profile> policy get` before planning mutations or batches.

Put global options before the command group:

```bash
clitg --profile personal --output json messages list --peer @example
```

Parse stdout as JSON and check both the process exit code and `ok`. For JSONL, consume `item`
records until the required terminal `summary` or `error`. Follow `meta.next_cursor` exactly. Never
invent or modify a cursor.

## Read safely

- Prefer `inbox`, `dialogs`, `contacts`, `messages`, `account`, and other dedicated commands over
  `raw invoke`.
- Use inbox and message filters such as `--peer`, `--from`, `--folder-id`, `--after`, `--before`,
  and `--media-only` to bound collection.
- Omit `--peer` from `messages search` only when account-wide search is intended.
- Expect ambiguous peer resolution to return candidates. Require an exact ID or reference and never
  guess the target.
- Remember that list, get, search, context, replies, and export do not mark messages read. Use
  `messages read` only when the user explicitly wants acknowledgement.
- Request `--include-raw` only when normalized fields are insufficient.
- Use `messages export --resume` only for an existing export manifest. Do not replace export data.

## Write safely

1. Build the complete command with an explicit profile, target, payload, and scope.
2. Add a stable `--idempotency-key` to compatible mutations.
3. Run the exact command with `--dry-run`.
4. Verify the resolved target, risk, and normalized payload.
5. If the user's request authorizes that exact action, execute it without `--dry-run`. Otherwise,
   stop and request authorization.

Use plain text unless formatting was requested. Select `--parse-mode markdown` or `html`
explicitly. Prefer file or stdin payload sources for long content and sensitive login values.

For destructive actions, provide the exact `--confirm` value required by the command. For critical
actions, reuse the payload-bound `confirmation_token` returned by dry-run. Tokens expire after five
minutes and one use. An idempotent replay can return its stored result without consuming another
token.

Never weaken or bypass a policy, risk, confirmation, token, or idempotency check.

## Use registered actions

Use `clitg commands list` to discover stable account, bot, chat, contact, dialog, draft, folder, GIF,
invite, join-request, message, poll, Saved Messages, scheduled, sticker, story, and topic actions.
Inspect the exact generated parameter signature first:

```bash
clitg commands get --command chats.create-channel
clitg --profile personal chats create-channel \
  --params '{"title":"Updates","about":"Agent managed","broadcast":true,"megagroup":false}' \
  --dry-run
```

Pass parameters through exactly one of `--params`, `--params-file`, or `--params-stdin`. Friendly
peer, channel, and user strings are resolved by the CLI. Use `_` for nested TL constructors when the
command signature requires a generated Telegram type.

## Watch updates

Use JSONL and bound the stream whenever possible:

```bash
clitg --profile personal --output jsonl updates watch \
  --event message.new \
  --consumer-id inbox-agent \
  --max-events 100 \
  --idle-timeout 30 \
  --timeout 300
```

Use `--peer` to restrict sources. Save and reuse the opaque cursor, or use a stable consumer ID for
automatic checkpoints. Treat `telegram.raw_update` as unreviewed input and inspect its `raw_type`.
Do not assume every update is a message.

## Run read-only batches

Use JSONL with one `id`, registered read `command`, and `params` object per line. Validate unfamiliar
commands with `commands get`. Keep `--concurrency` between 1 and 10. Use `--fail-fast` only when
sequential stop-on-error behavior is desired.

Do not place mutations in a batch. The CLI rejects them. Respect policy limits for operation and
target counts.

## Use raw methods

Use raw methods only when no dedicated command exists:

1. Inspect the method with `capabilities get`.
2. Build JSON parameters using `_` for TL constructors and `$peer`, `$channel`, `$user`, `$bytes`,
   `$datetime`, or `$upload` as appropriate.
3. Pass `--allow-raw --dry-run` first.
4. Add `--confirm <method>` for destructive execution.
5. Reuse the dry-run token for critical or unknown execution with the exact same profile, method,
   and parameters.

Unknown raw methods are critical. Do not reinterpret their classification.

## Handle failures

- On `rate_limited`, report `retry_after_seconds`. Do not sleep or retry unless waiting was
  authorized.
- On `ambiguous_peer`, present candidates and require an exact selection.
- On `permission_denied`, report `policy_reason` when present. Do not change the attached policy
  unless the user explicitly asks.
- On authentication errors, report the required non-interactive command. Prefer secret files over
  requesting secrets in chat.
- On partial JSONL output, preserve processed items and report the terminal error.
- On idempotent replay, treat the stored result as the completed operation.

Respect Telegram API terms, including privacy, consent, branding, automation, and content or AI
restrictions. Do not use this skill to evade platform behavior or permissions.
