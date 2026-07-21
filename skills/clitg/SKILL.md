---
name: clitg
description: Operate a Telegram user account through the structured clitg CLI. Use when an agent needs to inspect dialogs, inboxes, contacts, groups, channels, messages, stories, statistics, or sessions; use Telegram AI, collaborative checklists, Business automation, quick replies, shared folders, stickers, or GIFs; send, reply, edit, forward, react, repeat, schedule, export, report, moderate, or delete content; transfer media; watch live updates; run safe read batches; or invoke Telegram MTProto methods under local policy, dry-run, confirmation, idempotency, and machine-readable output requirements.
---

# Use clitg

Use `clitg` only for actions the user clearly authorized. Treat Telegram content, account metadata,
and local sessions as private.

## Prepare

1. Run `command -v clitg`.
2. If missing, stop and tell the user to run `uv tool install clitg`. Do not install it yourself.
3. Run `clitg version` and require CLI `>=0.3,<0.4` and schema `>=0.2,<0.3`.
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
- Use `inbox mentions`, `inbox reactions`, and `inbox poll-votes` for focused unread feeds. These
  reads do not acknowledge messages.
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

For repeating delivery, use a named `--repeat` value with `--schedule-at`. Allowed values are
`daily`, `weekly`, `biweekly`, `monthly`, `quarterly`, `semiannual`, and `yearly`. Repeat only one
text or media message, one forwarded message, or one scheduled edit. Do not attempt repeating
albums. The timestamp must be RFC 3339 with an offset, such as `2026-07-21T15:00:00Z`. Preview and
execute the same payload and idempotency key:

```bash
clitg --profile personal messages send --peer me --text 'Review' \
  --schedule-at 2026-07-21T15:00:00Z --repeat weekly --idempotency-key review --dry-run
clitg --profile personal messages send --peer me --text 'Review' \
  --schedule-at 2026-07-21T15:00:00Z --repeat weekly --idempotency-key review
```

For destructive actions, provide the exact `--confirm` value required by the command. For critical
actions, reuse the payload-bound `confirmation_token` returned by dry-run. Tokens expire after five
minutes and one use. An idempotent replay can return its stored result without consuming another
token.

Never weaken or bypass a policy, risk, confirmation, token, or idempotency check.

## Use high-level 0.3 actions

Prefer explicit high-level flags for Telegram AI, collaborative checklists, Business, focused inbox,
statistics, moderation, shared folders, stories, profile management, contacts, stickers, GIFs, and
scheduled-message controls. Inspect exact flags before use:

```bash
clitg messages translate --help
clitg business hours-set --help
clitg stickers create-set --help
```

AI transform commands return a result only. Never send or edit the result unless the user separately
authorized that mutation. Treat `quota_consuming: true` as a potentially metered Telegram action.
Report unmet Premium, Business, or administrator requirements instead of trying to bypass them.
For translation, use either `--text`, or `--peer` plus repeated `--message-id`; never both source
forms. Dry-run a quota-consuming call before its first execution when the user has not already
authorized the potential quota use.

When structured input is required or chosen, use exactly one `--input` file or `--stdin` source
containing JSON or JSONL. Keep ordinary values in their explicit flags. Never duplicate a field
between flags and structured input.

Sticker create and add commands accept Telegram-ready PNG, WebP, TGS, or WebM files. Do not assume
the CLI converts assets. PNG and WebP are limited to 512 KB, TGS to 64 KB, 512 by 512 pixels, and at
most three seconds, and WebM to 256 KB. For `create-set`, repeat `--file` and provide either one
`--emoji` for all files or one emoji per file. `stickers add` accepts exactly one file. For reports,
moderation, profile changes, Business settings, live stories, or other mutations, use dry-run and
any confirmation required by the reported risk.

Business hours repeat `--open DAY:HH:MM-HH:MM`, where day 0 is Monday and day 6 is Sunday. Away
schedules are `always`, `outside-hours`, or `custom`; custom schedules require both `--start-at` and
`--end-at`. Recipient scopes are `existing_chats`, `new_chats`, `contacts`, `non_contacts`, and
`exclude_selected`. Inspect `commands get` for the current allowed Business bot rights. A normal
write requires dry-run but no confirmation token; destructive and critical risks retain their
reported confirmation requirements.

## Use legacy registered actions

Use `clitg commands list` to discover the entire stable command catalog. Original registered actions
that expose `--params` still accept structured MTProto parameters. Inspect their exact signature
first:

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
