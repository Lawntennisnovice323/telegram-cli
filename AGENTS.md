# AGENTS.md

## Purpose

Build and maintain `clitg` as a deterministic, non-interactive Telegram CLI for AI agents. Treat
its stdout JSON, schemas, exit codes, safety checks, and capability manifest as public APIs.

## Tooling

- Use uv for all Python and dependency operations.
- Create project metadata with `uv init`; add or remove dependencies with `uv add` and `uv remove`.
- Commit `uv.lock` and `.python-version`. Do not hand-edit dependency arrays.
- Run Python commands through `uv run`.
- Use Ruff for formatting and linting, and ty for type checking.
- Write code, comments, documentation, tests, and commit messages in English.

## Product invariants

- Never add interactive prompts. All values must arrive through options, environment variables,
  files, or explicitly selected stdin.
- Emit operational successes and failures as schema-versioned JSON or JSONL on stdout.
- Keep stderr empty unless redacted verbose diagnostics were explicitly requested.
- Never print or log API hashes, login codes, passwords, auth keys, or session material.
- Do not mark messages read during list, get, search, resolve, schema, or capability operations.
- Resolve ambiguous peers by returning candidates; never guess a mutation target.
- Support `--dry-run` for every mutation. Preserve exact confirmation and critical-token checks.
- Treat unknown raw methods as critical until their risk has been reviewed.
- Keep personal sessions, credentials, Telegram data, and real account identifiers out of tests.

## Architecture

- Keep Typer presentation, application services, storage, and Telethon integration separated.
- Keep Telethon and dynamic TL values at adapter boundaries; use typed Pydantic models internally.
- Prefer the friendly Telethon API for dedicated commands and the generated TL registry for raw
  coverage.
- Update generated schemas and capabilities whenever public models or Telethon change.
- Preserve schema `0.2` across patch releases. A breaking contract requires a new minor schema and
  a coordinated skill update.

## Testing and completion

- Add or update tests with every behavior change.
- Maintain 100% statement and branch coverage for `src/clitg`.
- Default tests must be offline and deterministic; Test DC coverage belongs to the protected manual
  workflow.
- Before finishing, run every command documented in the quality-gate section of `readme.md`.
- Validate the skill and install the built wheel in an isolated smoke environment.
- Do not claim completion while generated artifacts, the lockfile, formatting, lint, typing,
  coverage, or build checks are stale.
