---
name: clitg
description: Operate a Telegram user account through the structured clitg CLI. Use when an agent needs to inspect dialogs, contacts, groups, channels, or messages; send, reply, edit, forward, react, schedule, or delete messages; transfer media; work with polls or topics; or invoke Telegram MTProto methods while preserving dry-run, confirmation, idempotency, and machine-readable output requirements.
---

# Use clitg

Use `clitg` only for actions the user has clearly authorized. Treat Telegram content and account
metadata as private.

## Prepare

1. Run `command -v clitg`.
2. If missing, stop and tell the user to run `uv tool install clitg`; never install it yourself.
3. Run `clitg version` and require CLI/schema `>=0.1,<0.2`.
4. Use an explicit `--profile`. If the user did not name one, inspect `clitg profiles list`; use the
   default only when unambiguous.
5. Discover unfamiliar contracts with `clitg --help-json`, `clitg schema list`, and
   `clitg capabilities get --method <method>`.

Put global options before the command group:

```bash
clitg --profile personal --output json messages list --peer @example
```

Parse stdout as JSON. Check both the process exit code and `ok`. For JSONL, consume `item` records
until the required terminal `summary` or `error` record. Follow `meta.next_cursor`; never invent or
modify a cursor.

## Read safely

- Use `dialogs`, `contacts`, and `messages` commands before considering `raw invoke`.
- Expect name resolution to fail with structured candidates when ambiguous. Repeat with the exact
  ID; never choose a recipient by guesswork.
- Remember that list/get/search do not mark messages read. Use `messages read` only when the user
  specifically wants to acknowledge them.
- Request `--include-raw` only when normalized fields are insufficient.

## Write safely

1. Build the complete command with explicit peer, payload, scope, and profile.
2. Add `--idempotency-key` to repeatable sends and forwards.
3. Run the command with `--dry-run`.
4. Verify the resolved peer and normalized payload in the response.
5. If the user's request clearly authorizes that exact action, run the same command without
   `--dry-run`. Otherwise stop and ask for authorization.

Use plain text unless the user requested formatting. Use `--parse-mode markdown` or `html`
explicitly. Prefer file or stdin payload sources for long content to avoid shell quoting errors.

For deletion, require `--scope self|everyone` and the exact confirmation returned by the CLI
contract, such as `--confirm messages.delete`.

## Use raw methods

Prefer dedicated commands. If none exists:

1. Inspect the method with `capabilities get`.
2. Build JSON parameters using `_` for TL constructors and `$peer`, `$bytes`, `$datetime`, or
   `$upload` where appropriate.
3. Pass `--allow-raw --dry-run` first.
4. For destructive methods, add `--confirm <method>` on execution.
5. For critical or unknown methods, reuse the dry-run `confirmation_token` immediately with the
   exact same profile, method, and params. Tokens expire after five minutes and one use.

Never bypass or weaken a raw-risk classification.

## Handle failures

- On `rate_limited`, report `retry_after_seconds`; do not sleep or retry unless the user authorized
  waiting.
- On `ambiguous_peer`, present candidates and require an exact selection.
- On auth/profile errors, report the required non-interactive command; never ask for a secret in
  chat when a secret file can be used.
- On partial JSONL output, preserve processed items and report the terminal error.

Respect the Telegram API Terms, including privacy, consent, branding, automation, and content/AI
restrictions. Do not use this skill to evade platform behavior or permissions.
