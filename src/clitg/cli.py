"""Typer command-line interface with JSON-first output."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import typer
from typer import _click as click

from clitg.catalog import command_catalog
from clitg.errors import ClitgError
from clitg.models import (
    CommandResult,
    Envelope,
    ErrorCode,
    ErrorInfo,
    JsonlRecord,
    Meta,
    OutputFormat,
)
from clitg.serialization import json_dumps
from clitg.service import ClitgService

app = typer.Typer(
    name="clitg",
    help="Structured Telegram user-account CLI for agents.",
    invoke_without_command=True,
    no_args_is_help=False,
    rich_markup_mode=None,
    add_completion=False,
)

profiles_app = typer.Typer(help="Manage isolated account profiles.")
auth_app = typer.Typer(help="Authenticate an existing Telegram user account.")
dialogs_app = typer.Typer(help="Inspect chats, groups, and channels.")
contacts_app = typer.Typer(help="Inspect and resolve contacts.")
messages_app = typer.Typer(help="Read and write rich messages.")
media_app = typer.Typer(help="Transfer message media.")
polls_app = typer.Typer(help="Create and interact with polls.")
scheduled_app = typer.Typer(help="Inspect and cancel scheduled messages.")
topics_app = typer.Typer(help="Inspect forum topics.")
raw_app = typer.Typer(help="Invoke generated MTProto requests.")
capabilities_app = typer.Typer(help="Inspect MTProto support and risk.")
schema_app = typer.Typer(help="Inspect public JSON Schemas.")
state_app = typer.Typer(help="Inspect and prune auxiliary local state.")

for name, subapp in (
    ("profiles", profiles_app),
    ("auth", auth_app),
    ("dialogs", dialogs_app),
    ("contacts", contacts_app),
    ("messages", messages_app),
    ("media", media_app),
    ("polls", polls_app),
    ("scheduled", scheduled_app),
    ("topics", topics_app),
    ("raw", raw_app),
    ("capabilities", capabilities_app),
    ("schema", schema_app),
    ("state", state_app),
):
    app.add_typer(subapp, name=name)


@dataclass
class CliContext:
    """Global options shared by command handlers."""

    profile: str | None
    output: OutputFormat
    timeout_seconds: int
    verbose: bool
    service: ClitgService | None = None


SERVICE_FACTORY: Callable[..., ClitgService] = ClitgService


@app.callback()
def root(
    ctx: typer.Context,
    profile: str | None = typer.Option(None, "--profile", help="Profile slug."),
    output: OutputFormat = typer.Option(OutputFormat.JSON, "--output", help="json or jsonl."),
    timeout_seconds: int = typer.Option(30, "--timeout-seconds", min=1),
    verbose: bool = typer.Option(False, "--verbose", help="Emit redacted diagnostics to stderr."),
    show_version: bool = typer.Option(
        False,
        "--version",
        is_eager=True,
        help="Emit CLI, schema, Telethon, and Telegram layer versions.",
    ),
    help_json: bool = typer.Option(
        False,
        "--help-json",
        is_eager=True,
        help="Emit the machine-readable command catalog.",
    ),
) -> None:
    """Configure one non-interactive clitg invocation."""

    context = CliContext(profile, output, timeout_seconds, verbose)
    ctx.obj = context
    if show_version:
        _emit_success(context, "version", ClitgService.version(), str(uuid.uuid4()))
        raise typer.Exit()
    if help_json:
        _emit_success(context, "help", CommandResult(data=command_catalog()), str(uuid.uuid4()))
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


def _context(ctx: typer.Context) -> CliContext:
    value = ctx.find_root().obj
    if not isinstance(value, CliContext):
        raise RuntimeError("CLI context is unavailable")
    return value


def _service(context: CliContext) -> ClitgService:
    if context.service is None:
        context.service = SERVICE_FACTORY(timeout_seconds=context.timeout_seconds)
    return context.service


def _meta(context: CliContext, command: str, request_id: str, cursor: str | None = None) -> Meta:
    return Meta(
        command=command,
        profile=context.profile or os.getenv("CLITG_PROFILE"),
        request_id=request_id,
        next_cursor=cursor,
    )


def _emit_success(
    context: CliContext,
    command: str,
    result: CommandResult,
    request_id: str,
) -> None:
    meta = _meta(context, command, request_id, result.next_cursor)
    if context.output == OutputFormat.JSON:
        typer.echo(json_dumps(Envelope(ok=True, data=result.data, meta=meta)))
        return
    for item in result.items or []:
        typer.echo(json_dumps(JsonlRecord(record_type="item", data=item, meta=meta.model_copy())))
    typer.echo(
        json_dumps(
            JsonlRecord(
                record_type="summary",
                data={"count": len(result.items or []), "next_cursor": result.next_cursor},
                meta=meta,
            )
        )
    )


def _emit_error(
    context: CliContext,
    command: str,
    error: ErrorInfo,
    request_id: str,
) -> None:
    meta = _meta(context, command, request_id)
    if context.output == OutputFormat.JSON:
        typer.echo(json_dumps(Envelope(ok=False, error=error, meta=meta)))
    else:
        typer.echo(json_dumps(JsonlRecord(record_type="error", error=error, meta=meta)))


def _execute(ctx: typer.Context, command: str, factory: Callable[[], Any]) -> None:
    context = _context(ctx)
    request_id = str(uuid.uuid4())
    try:
        result = factory()
        if inspect.isawaitable(result):
            result = asyncio.run(result)
        if not isinstance(result, CommandResult):
            raise TypeError("Command did not return CommandResult")
        _emit_success(context, command, result, request_id)
    except ClitgError as exc:
        _emit_error(context, command, exc.info, request_id)
        raise typer.Exit(exc.exit_code) from exc
    except Exception as exc:
        error = ErrorInfo(
            code=ErrorCode.INTERNAL,
            message="Unexpected internal error",
            details={"exception": exc.__class__.__name__},
        )
        _emit_error(context, command, error, request_id)
        if context.verbose:
            typer.echo(json_dumps({"event": "exception", "type": exc.__class__.__name__}), err=True)
        raise typer.Exit(1) from exc


def _read_text(
    literal: str | None,
    file: Path | None,
    stdin: bool,
    *,
    label: str,
    environment: str | None = None,
    required: bool = False,
) -> str:
    sources = int(literal is not None) + int(file is not None) + int(stdin)
    if sources > 1:
        raise ClitgError(ErrorCode.INVALID_INPUT, f"Only one {label} source may be used")
    value = literal
    if file is not None:
        try:
            value = file.read_text(encoding="utf-8")
        except OSError as exc:
            raise ClitgError(ErrorCode.INVALID_INPUT, f"Unable to read {label} file") from exc
    elif stdin:
        value = sys.stdin.read()
    elif value is None and environment:
        value = os.getenv(environment)
    if required and not value:
        raise ClitgError(ErrorCode.INVALID_INPUT, f"{label.capitalize()} is required")
    return value or ""


def _read_json(literal: str | None, file: Path | None, stdin: bool) -> dict[str, Any]:
    raw = _read_text(literal, file, stdin, label="JSON", required=True)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ClitgError(ErrorCode.INVALID_INPUT, "JSON input is invalid") from exc
    if not isinstance(value, dict):
        raise ClitgError(ErrorCode.INVALID_INPUT, "JSON input must be an object")
    return value


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ClitgError(ErrorCode.INVALID_INPUT, "Datetime must be RFC 3339") from exc
    if parsed.tzinfo is None:
        raise ClitgError(ErrorCode.INVALID_INPUT, "Datetime must include a UTC offset")
    return parsed


def _validate_parse_mode(value: str) -> str:
    if value not in {"plain", "markdown", "html"}:
        raise ClitgError(ErrorCode.INVALID_INPUT, "Parse mode must be plain, markdown, or html")
    return value


@profiles_app.command("create")
def profiles_create(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name"),
    api_id: int | None = typer.Option(None, "--api-id"),
    api_hash: str | None = typer.Option(None, "--api-hash"),
    api_hash_file: Path | None = typer.Option(None, "--api-hash-file"),
    phone: str | None = typer.Option(None, "--phone"),
    make_default: bool = typer.Option(False, "--default"),
) -> None:
    """Create an isolated user-account profile."""

    def invoke() -> CommandResult:
        selected_api_id = api_id or int(os.getenv("CLITG_API_ID", "0"))
        if selected_api_id <= 0:
            raise ClitgError(ErrorCode.INVALID_INPUT, "A positive API ID is required")
        selected_hash = _read_text(
            api_hash,
            api_hash_file,
            False,
            label="API hash",
            environment="CLITG_API_HASH",
            required=True,
        )
        return _service(_context(ctx)).create_profile(
            name,
            selected_api_id,
            selected_hash,
            phone or os.getenv("CLITG_PHONE"),
            make_default=make_default,
        )

    _execute(ctx, "profiles.create", invoke)


@profiles_app.command("list")
def profiles_list(ctx: typer.Context) -> None:
    """List safe profile metadata."""

    _execute(ctx, "profiles.list", lambda: _service(_context(ctx)).list_profiles())


@profiles_app.command("get")
def profiles_get(ctx: typer.Context, name: str = typer.Option(..., "--name")) -> None:
    """Get one profile without secrets."""

    _execute(ctx, "profiles.get", lambda: _service(_context(ctx)).get_profile(name))


@profiles_app.command("set-default")
def profiles_set_default(ctx: typer.Context, name: str = typer.Option(..., "--name")) -> None:
    """Select the default profile."""

    _execute(
        ctx,
        "profiles.set-default",
        lambda: _service(_context(ctx)).set_default_profile(name),
    )


@profiles_app.command("remove")
def profiles_remove(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    confirm: str | None = typer.Option(None, "--confirm"),
) -> None:
    """Remove only local profile metadata."""

    _execute(
        ctx,
        "profiles.remove",
        lambda: _service(_context(ctx)).remove_profile(
            name,
            dry_run=dry_run,
            confirmation=confirm,
        ),
    )


@auth_app.command("request-code")
def auth_request_code(
    ctx: typer.Context,
    phone: str | None = typer.Option(None, "--phone"),
) -> None:
    """Request a login code and return an opaque login ID."""

    _execute(
        ctx,
        "auth.request-code",
        lambda: _service(_context(ctx)).request_code(_context(ctx).profile, phone),
    )


@auth_app.command("verify")
def auth_verify(
    ctx: typer.Context,
    login_id: str = typer.Option(..., "--login-id"),
    code: str | None = typer.Option(None, "--code"),
    code_file: Path | None = typer.Option(None, "--code-file"),
    password: str | None = typer.Option(None, "--password"),
    password_file: Path | None = typer.Option(None, "--password-file"),
) -> None:
    """Complete code and optional 2FA authorization."""

    def invoke() -> Any:
        selected_code = _read_text(
            code,
            code_file,
            False,
            label="login code",
            environment="CLITG_CODE",
            required=True,
        ).strip()
        selected_password = (
            _read_text(
                password,
                password_file,
                False,
                label="2FA password",
                environment="CLITG_PASSWORD",
            ).strip()
            or None
        )
        return _service(_context(ctx)).verify_login(
            _context(ctx).profile,
            login_id,
            selected_code,
            selected_password,
        )

    _execute(ctx, "auth.verify", invoke)


@auth_app.command("status")
def auth_status(ctx: typer.Context) -> None:
    """Report whether the selected profile is authorized."""

    _execute(
        ctx,
        "auth.status",
        lambda: _service(_context(ctx)).auth_status(_context(ctx).profile),
    )


@auth_app.command("logout")
def auth_logout(
    ctx: typer.Context,
    dry_run: bool = typer.Option(False, "--dry-run"),
    confirm: str | None = typer.Option(None, "--confirm"),
) -> None:
    """Revoke the current Telegram authorization."""

    _execute(
        ctx,
        "auth.logout",
        lambda: _service(_context(ctx)).logout(
            _context(ctx).profile,
            dry_run=dry_run,
            confirmation=confirm,
        ),
    )


@dialogs_app.command("list")
def dialogs_list(
    ctx: typer.Context,
    cursor: str | None = typer.Option(None, "--cursor"),
    limit: int = typer.Option(50, "--limit"),
    include_raw: bool = typer.Option(False, "--include-raw"),
) -> None:
    """List joined dialogs."""

    _execute(
        ctx,
        "dialogs.list",
        lambda: _service(_context(ctx)).dialogs(
            _context(ctx).profile,
            query=None,
            cursor=cursor,
            limit=limit,
            include_raw=include_raw,
        ),
    )


@dialogs_app.command("search")
def dialogs_search(
    ctx: typer.Context,
    query: str = typer.Option(..., "--query"),
    cursor: str | None = typer.Option(None, "--cursor"),
    limit: int = typer.Option(50, "--limit"),
    include_raw: bool = typer.Option(False, "--include-raw"),
) -> None:
    """Search joined dialogs by title."""

    _execute(
        ctx,
        "dialogs.search",
        lambda: _service(_context(ctx)).dialogs(
            _context(ctx).profile,
            query=query,
            cursor=cursor,
            limit=limit,
            include_raw=include_raw,
        ),
    )


@dialogs_app.command("get")
def dialogs_get(
    ctx: typer.Context,
    peer: str = typer.Option(..., "--peer"),
    include_raw: bool = typer.Option(False, "--include-raw"),
) -> None:
    """Resolve one dialog or peer."""

    _execute(
        ctx,
        "dialogs.get",
        lambda: _service(_context(ctx)).peer(
            _context(ctx).profile,
            peer,
            include_raw=include_raw,
        ),
    )


@contacts_app.command("list")
def contacts_list(ctx: typer.Context) -> None:
    """List Telegram contacts."""

    _execute(
        ctx,
        "contacts.list",
        lambda: _service(_context(ctx)).contacts(_context(ctx).profile, None),
    )


@contacts_app.command("search")
def contacts_search(ctx: typer.Context, query: str = typer.Option(..., "--query")) -> None:
    """Search Telegram contacts locally."""

    _execute(
        ctx,
        "contacts.search",
        lambda: _service(_context(ctx)).contacts(_context(ctx).profile, query),
    )


@contacts_app.command("resolve")
def contacts_resolve(ctx: typer.Context, peer: str = typer.Option(..., "--peer")) -> None:
    """Resolve a stable peer reference."""

    _execute(
        ctx,
        "contacts.resolve",
        lambda: _service(_context(ctx)).peer(_context(ctx).profile, peer, include_raw=False),
    )


def _message_page(
    ctx: typer.Context,
    command: str,
    peer: str,
    query: str | None,
    cursor: str | None,
    limit: int,
    topic_id: int | None,
    include_raw: bool,
) -> None:
    _execute(
        ctx,
        command,
        lambda: _service(_context(ctx)).messages(
            _context(ctx).profile,
            peer,
            query=query,
            cursor=cursor,
            limit=limit,
            topic_id=topic_id,
            include_raw=include_raw,
        ),
    )


@messages_app.command("list")
def messages_list(
    ctx: typer.Context,
    peer: str = typer.Option(..., "--peer"),
    cursor: str | None = typer.Option(None, "--cursor"),
    limit: int = typer.Option(50, "--limit"),
    topic_id: int | None = typer.Option(None, "--topic-id"),
    include_raw: bool = typer.Option(False, "--include-raw"),
) -> None:
    """List messages without marking them read."""

    _message_page(ctx, "messages.list", peer, None, cursor, limit, topic_id, include_raw)


@messages_app.command("search")
def messages_search(
    ctx: typer.Context,
    peer: str = typer.Option(..., "--peer"),
    query: str = typer.Option(..., "--query"),
    cursor: str | None = typer.Option(None, "--cursor"),
    limit: int = typer.Option(50, "--limit"),
    topic_id: int | None = typer.Option(None, "--topic-id"),
    include_raw: bool = typer.Option(False, "--include-raw"),
) -> None:
    """Search a peer's message history."""

    _message_page(ctx, "messages.search", peer, query, cursor, limit, topic_id, include_raw)


@messages_app.command("get")
def messages_get(
    ctx: typer.Context,
    peer: str = typer.Option(..., "--peer"),
    message_id: int = typer.Option(..., "--message-id"),
    include_raw: bool = typer.Option(False, "--include-raw"),
) -> None:
    """Get one message without marking it read."""

    _execute(
        ctx,
        "messages.get",
        lambda: _service(_context(ctx)).get_message(
            _context(ctx).profile,
            peer,
            message_id,
            include_raw=include_raw,
        ),
    )


def _send_command(
    ctx: typer.Context,
    command: str,
    peer: str,
    text: str | None,
    text_file: Path | None,
    text_stdin: bool,
    files: list[Path],
    reply_to: int | None,
    topic_id: int | None,
    parse_mode: str,
    media_kind: str,
    schedule_at: str | None,
    idempotency_key: str | None,
    dry_run: bool,
) -> None:
    def invoke() -> Any:
        selected_text = _read_text(text, text_file, text_stdin, label="message text")
        return _service(_context(ctx)).send(
            _context(ctx).profile,
            peer,
            text=selected_text,
            files=files,
            reply_to=reply_to,
            topic_id=topic_id,
            parse_mode=_validate_parse_mode(parse_mode),
            media_kind=media_kind,
            schedule_at=_parse_datetime(schedule_at),
            idempotency_key=idempotency_key,
            dry_run=dry_run,
        )

    _execute(ctx, command, invoke)


@messages_app.command("send")
def messages_send(
    ctx: typer.Context,
    peer: str = typer.Option(..., "--peer"),
    text: str | None = typer.Option(None, "--text"),
    text_file: Path | None = typer.Option(None, "--text-file"),
    text_stdin: bool = typer.Option(False, "--text-stdin"),
    file: list[Path] | None = typer.Option(None, "--file"),
    topic_id: int | None = typer.Option(None, "--topic-id"),
    parse_mode: str = typer.Option("plain", "--parse-mode"),
    media_kind: str = typer.Option("auto", "--media-kind"),
    schedule_at: str | None = typer.Option(None, "--schedule-at"),
    idempotency_key: str | None = typer.Option(None, "--idempotency-key"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Send text, files, albums, voice, or stickers."""

    _send_command(
        ctx,
        "messages.send",
        peer,
        text,
        text_file,
        text_stdin,
        file or [],
        None,
        topic_id,
        parse_mode,
        media_kind,
        schedule_at,
        idempotency_key,
        dry_run,
    )


@messages_app.command("reply")
def messages_reply(
    ctx: typer.Context,
    peer: str = typer.Option(..., "--peer"),
    message_id: int = typer.Option(..., "--message-id"),
    text: str | None = typer.Option(None, "--text"),
    text_file: Path | None = typer.Option(None, "--text-file"),
    text_stdin: bool = typer.Option(False, "--text-stdin"),
    file: list[Path] | None = typer.Option(None, "--file"),
    parse_mode: str = typer.Option("plain", "--parse-mode"),
    media_kind: str = typer.Option("auto", "--media-kind"),
    idempotency_key: str | None = typer.Option(None, "--idempotency-key"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Reply to one message."""

    _send_command(
        ctx,
        "messages.reply",
        peer,
        text,
        text_file,
        text_stdin,
        file or [],
        message_id,
        None,
        parse_mode,
        media_kind,
        None,
        idempotency_key,
        dry_run,
    )


@messages_app.command("forward")
def messages_forward(
    ctx: typer.Context,
    source_peer: str = typer.Option(..., "--source-peer"),
    target_peer: str = typer.Option(..., "--target-peer"),
    message_id: list[int] | None = typer.Option(None, "--message-id"),
    idempotency_key: str | None = typer.Option(None, "--idempotency-key"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Forward an exact message set."""

    _execute(
        ctx,
        "messages.forward",
        lambda: _service(_context(ctx)).forward(
            _context(ctx).profile,
            source_peer,
            target_peer,
            message_id or [],
            idempotency_key=idempotency_key,
            dry_run=dry_run,
        ),
    )


@messages_app.command("edit")
def messages_edit(
    ctx: typer.Context,
    peer: str = typer.Option(..., "--peer"),
    message_id: int = typer.Option(..., "--message-id"),
    text: str | None = typer.Option(None, "--text"),
    text_file: Path | None = typer.Option(None, "--text-file"),
    text_stdin: bool = typer.Option(False, "--text-stdin"),
    parse_mode: str = typer.Option("plain", "--parse-mode"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Edit an existing message."""

    def invoke() -> Any:
        selected = _read_text(text, text_file, text_stdin, label="message text", required=True)
        return _service(_context(ctx)).edit_message(
            _context(ctx).profile,
            peer,
            message_id,
            selected,
            _validate_parse_mode(parse_mode),
            dry_run=dry_run,
        )

    _execute(ctx, "messages.edit", invoke)


@messages_app.command("delete")
def messages_delete(
    ctx: typer.Context,
    peer: str = typer.Option(..., "--peer"),
    message_id: list[int] | None = typer.Option(None, "--message-id"),
    scope: str = typer.Option(..., "--scope"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    confirm: str | None = typer.Option(None, "--confirm"),
) -> None:
    """Delete messages with an explicit self/everyone scope."""

    _execute(
        ctx,
        "messages.delete",
        lambda: _service(_context(ctx)).delete_messages(
            _context(ctx).profile,
            peer,
            message_id or [],
            scope,
            dry_run=dry_run,
            confirmation=confirm,
        ),
    )


@messages_app.command("read")
def messages_read(
    ctx: typer.Context,
    peer: str = typer.Option(..., "--peer"),
    max_id: int | None = typer.Option(None, "--max-id"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Explicitly mark messages read."""

    _execute(
        ctx,
        "messages.read",
        lambda: _service(_context(ctx)).read_messages(
            _context(ctx).profile,
            peer,
            max_id,
            dry_run=dry_run,
        ),
    )


@messages_app.command("react")
def messages_react(
    ctx: typer.Context,
    peer: str = typer.Option(..., "--peer"),
    message_id: int = typer.Option(..., "--message-id"),
    reaction: str | None = typer.Option(None, "--reaction"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Set or clear one reaction."""

    _execute(
        ctx,
        "messages.react",
        lambda: _service(_context(ctx)).react_message(
            _context(ctx).profile,
            peer,
            message_id,
            reaction,
            dry_run=dry_run,
        ),
    )


def _pin_command(
    ctx: typer.Context,
    peer: str,
    message_id: int,
    dry_run: bool,
    *,
    unpin: bool,
) -> None:
    command = "messages.unpin" if unpin else "messages.pin"
    _execute(
        ctx,
        command,
        lambda: _service(_context(ctx)).pin_message(
            _context(ctx).profile,
            peer,
            message_id,
            unpin=unpin,
            dry_run=dry_run,
        ),
    )


@messages_app.command("pin")
def messages_pin(
    ctx: typer.Context,
    peer: str = typer.Option(..., "--peer"),
    message_id: int = typer.Option(..., "--message-id"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Pin a message."""

    _pin_command(ctx, peer, message_id, dry_run, unpin=False)


@messages_app.command("unpin")
def messages_unpin(
    ctx: typer.Context,
    peer: str = typer.Option(..., "--peer"),
    message_id: int = typer.Option(..., "--message-id"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Unpin a message."""

    _pin_command(ctx, peer, message_id, dry_run, unpin=True)


@media_app.command("download")
def media_download(
    ctx: typer.Context,
    peer: str = typer.Option(..., "--peer"),
    message_id: int = typer.Option(..., "--message-id"),
    output: Path = typer.Option(..., "--output"),
    create_dirs: bool = typer.Option(False, "--create-dirs"),
    overwrite: bool = typer.Option(False, "--overwrite"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Download media to an explicit path."""

    _execute(
        ctx,
        "media.download",
        lambda: _service(_context(ctx)).download(
            _context(ctx).profile,
            peer,
            message_id,
            output,
            create_dirs=create_dirs,
            overwrite=overwrite,
            dry_run=dry_run,
        ),
    )


@polls_app.command("create")
def polls_create(
    ctx: typer.Context,
    peer: str = typer.Option(..., "--peer"),
    question: str = typer.Option(..., "--question"),
    answer: list[str] | None = typer.Option(None, "--answer"),
    multiple_choice: bool = typer.Option(False, "--multiple-choice"),
    anonymous: bool = typer.Option(True, "--anonymous/--public-voters"),
    quiz: bool = typer.Option(False, "--quiz"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Create and send a poll."""

    _execute(
        ctx,
        "polls.create",
        lambda: _service(_context(ctx)).create_poll(
            _context(ctx).profile,
            peer,
            question,
            answer or [],
            multiple_choice=multiple_choice,
            anonymous=anonymous,
            quiz=quiz,
            dry_run=dry_run,
        ),
    )


@polls_app.command("vote")
def polls_vote(
    ctx: typer.Context,
    peer: str = typer.Option(..., "--peer"),
    message_id: int = typer.Option(..., "--message-id"),
    option: list[int] | None = typer.Option(None, "--option"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Vote by zero-based answer index."""

    _execute(
        ctx,
        "polls.vote",
        lambda: _service(_context(ctx)).vote_poll(
            _context(ctx).profile,
            peer,
            message_id,
            option or [],
            dry_run=dry_run,
        ),
    )


@polls_app.command("close")
def polls_close(
    ctx: typer.Context,
    peer: str = typer.Option(..., "--peer"),
    message_id: int = typer.Option(..., "--message-id"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    confirm: str | None = typer.Option(None, "--confirm"),
) -> None:
    """Close an existing poll."""

    _execute(
        ctx,
        "polls.close",
        lambda: _service(_context(ctx)).close_poll(
            _context(ctx).profile,
            peer,
            message_id,
            dry_run=dry_run,
            confirmation=confirm,
        ),
    )


@scheduled_app.command("list")
def scheduled_list(ctx: typer.Context, peer: str = typer.Option(..., "--peer")) -> None:
    """List scheduled messages."""

    _execute(
        ctx,
        "scheduled.list",
        lambda: _service(_context(ctx)).scheduled_messages(_context(ctx).profile, peer),
    )


@scheduled_app.command("cancel")
def scheduled_cancel(
    ctx: typer.Context,
    peer: str = typer.Option(..., "--peer"),
    message_id: list[int] | None = typer.Option(None, "--message-id"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    confirm: str | None = typer.Option(None, "--confirm"),
) -> None:
    """Cancel scheduled messages."""

    _execute(
        ctx,
        "scheduled.cancel",
        lambda: _service(_context(ctx)).cancel_scheduled(
            _context(ctx).profile,
            peer,
            message_id or [],
            dry_run=dry_run,
            confirmation=confirm,
        ),
    )


@topics_app.command("list")
def topics_list(
    ctx: typer.Context,
    peer: str = typer.Option(..., "--peer"),
    limit: int = typer.Option(50, "--limit"),
) -> None:
    """List forum topics."""

    _execute(
        ctx,
        "topics.list",
        lambda: _service(_context(ctx)).topics(_context(ctx).profile, peer, limit),
    )


@raw_app.command("invoke")
def raw_invoke(
    ctx: typer.Context,
    method: str = typer.Option(..., "--method"),
    params: str | None = typer.Option(None, "--params"),
    params_file: Path | None = typer.Option(None, "--params-file"),
    params_stdin: bool = typer.Option(False, "--params-stdin"),
    allow_raw: bool = typer.Option(False, "--allow-raw"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    confirm: str | None = typer.Option(None, "--confirm"),
    confirmation_token: str | None = typer.Option(None, "--confirmation-token"),
) -> None:
    """Invoke any supported generated TL request."""

    def invoke() -> Any:
        parsed = _read_json(params, params_file, params_stdin)
        return _service(_context(ctx)).raw(
            _context(ctx).profile,
            method,
            parsed,
            allow_raw=allow_raw,
            dry_run=dry_run,
            confirmation=confirm,
            confirmation_token=confirmation_token,
        )

    _execute(ctx, "raw.invoke", invoke)


@capabilities_app.command("list")
def capabilities_list(
    ctx: typer.Context,
    status: str | None = typer.Option(None, "--status"),
) -> None:
    """List MTProto support classifications."""

    _execute(
        ctx,
        "capabilities.list",
        lambda: _service(_context(ctx)).capabilities(status=status),
    )


@capabilities_app.command("get")
def capabilities_get(ctx: typer.Context, method: str = typer.Option(..., "--method")) -> None:
    """Get one MTProto capability."""

    _execute(
        ctx,
        "capabilities.get",
        lambda: _service(_context(ctx)).capabilities(method=method),
    )


@schema_app.command("list")
def schema_list(ctx: typer.Context) -> None:
    """List public schemas and command metadata."""

    _execute(ctx, "schema.list", lambda: _service(_context(ctx)).schemas())


@schema_app.command("get")
def schema_get(ctx: typer.Context, name: str = typer.Option(..., "--name")) -> None:
    """Get one JSON Schema."""

    _execute(ctx, "schema.get", lambda: _service(_context(ctx)).schemas(name))


@schema_app.command("export")
def schema_export(
    ctx: typer.Context,
    output: Path = typer.Option(..., "--output"),
    overwrite: bool = typer.Option(False, "--overwrite"),
) -> None:
    """Export schema and command catalogs."""

    _execute(
        ctx,
        "schema.export",
        lambda: _service(_context(ctx)).export_schemas(output, overwrite=overwrite),
    )


@state_app.command("get")
def state_get(ctx: typer.Context) -> None:
    """Return safe auxiliary-state counts."""

    _execute(ctx, "state.get", lambda: _service(_context(ctx)).state_counts())


@state_app.command("prune")
def state_prune(
    ctx: typer.Context,
    kind: str = typer.Option(..., "--kind"),
    before: str | None = typer.Option(None, "--before"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    confirm: str | None = typer.Option(None, "--confirm"),
) -> None:
    """Prune auxiliary state by kind and age."""

    _execute(
        ctx,
        "state.prune",
        lambda: _service(_context(ctx)).prune_state(
            kind,
            _parse_datetime(before),
            dry_run=dry_run,
            confirmation=confirm,
        ),
    )


@app.command("help")
def help_command(ctx: typer.Context) -> None:
    """Show the same human-readable help as --help."""

    typer.echo(ctx.find_root().get_help())


@app.command("version")
def version(ctx: typer.Context) -> None:
    """Return CLI, schema, Telethon, and layer versions."""

    _execute(ctx, "version", ClitgService.version)


def main() -> int:
    """Run Typer while converting usage failures to structured JSON."""

    try:
        result = app(standalone_mode=False)
    except click.exceptions.Exit as exc:
        return int(exc.exit_code)
    except click.ClickException as exc:
        request_id = str(uuid.uuid4())
        context = CliContext(None, OutputFormat.JSON, 30, False)
        _emit_error(
            context,
            "cli",
            ErrorInfo(code=ErrorCode.INVALID_INPUT, message=exc.format_message()),
            request_id,
        )
        return 2
    return int(result) if isinstance(result, int) else 0
