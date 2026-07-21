from __future__ import annotations

from typing import Any

import pytest

from clitg.errors import ClitgError
from clitg.features import (
    FEATURE_BY_COMMAND,
    FeatureCommand,
    FeatureOption,
    build_feature_params,
    feature_catalog,
    normalize_feature_result,
)


def build(
    command: str,
    values: dict[str, Any],
    structured: dict[str, Any] | list[Any] | None = None,
) -> dict[str, Any]:
    return build_feature_params(FEATURE_BY_COMMAND[command], values, structured)


def artificial(builder: str, *options: FeatureOption) -> FeatureCommand:
    return FeatureCommand("test.command", "help.getConfig", "read", "Test.", options, builder)


def test_feature_metadata_and_default_resolution() -> None:
    read = artificial("default")
    critical = FeatureCommand("x.y", "help.getConfig", "critical", "Test.")
    assert read.mutation is False and read.critical is False
    assert critical.mutation is True and critical.critical is True
    assert FeatureOption("some_value").flag == "--some-value"

    resolvers = (
        FeatureOption("plain"),
        FeatureOption("peer", resolver="peer"),
        FeatureOption("channel", resolver="channel"),
        FeatureOption("user", resolver="user"),
        FeatureOption("peers", "str_list", resolver="peers"),
        FeatureOption("users", "str_list", resolver="users"),
        FeatureOption("bytes", resolver="bytes"),
        FeatureOption("date", resolver="datetime"),
        FeatureOption("reaction", resolver="reaction"),
        FeatureOption("tone", resolver="tone"),
        FeatureOption("folder", resolver="chatlist"),
        FeatureOption("set", resolver="stickerset"),
        FeatureOption("text", resolver="text"),
        FeatureOption("renamed", telegram_name="target"),
        FeatureOption("ignored"),
        FeatureOption("empty", "str_list"),
        FeatureOption("false", "bool", default=False),
        FeatureOption("explicit_false", "bool", default=False, emit_default=True),
    )
    params = build_feature_params(
        artificial("default", *resolvers),
        {
            "plain": "x",
            "peer": "me",
            "channel": "@channel",
            "user": "@user",
            "peers": ["a"],
            "users": ["b"],
            "bytes": "YQ==",
            "date": "2026-01-01T00:00:00Z",
            "reaction": "👍",
            "tone": "formal",
            "folder": 1,
            "set": "animals",
            "text": "hello",
            "renamed": "value",
            "ignored": None,
            "empty": [],
            "false": False,
            "explicit_false": False,
        },
    )
    assert params["plain"] == "x"
    assert params["peer"] == {"$peer": "me"}
    assert params["channel"] == {"$channel": "@channel"}
    assert params["user"] == {"$user": "@user"}
    assert params["peers"] == [{"$peer": "a"}]
    assert params["users"] == [{"$user": "b"}]
    assert params["bytes"] == {"$bytes": "YQ=="}
    assert params["date"] == {"$datetime": "2026-01-01T00:00:00Z"}
    assert params["reaction"]["emoticon"] == "👍"
    assert params["tone"]["slug"] == "formal"
    assert params["folder"]["filter_id"] == 1
    assert params["set"]["short_name"] == "animals"
    assert params["text"]["text"] == "hello"
    assert params["target"] == "value"
    assert "ignored" not in params and "empty" not in params and "false" not in params
    assert params["explicit_false"] is False


def test_structured_input_rules_and_simple_builders() -> None:
    option = FeatureOption("peer", resolver="peer")
    assert build_feature_params(artificial("default", option), {"peer": "me"}, {"x": 1}) == {
        "peer": {"$peer": "me"}
    }
    with pytest.raises(ClitgError, match="duplicates"):
        build_feature_params(artificial("default", option), {"peer": "me"}, {"peer": "x"})
    required = artificial("input-required", option)
    with pytest.raises(ClitgError, match="requires"):
        build_feature_params(required, {})
    assert build_feature_params(required, {}, {"value": 1}) == {"value": 1}
    assert build_feature_params(required, {}, [{"value": 1}]) == {}
    with pytest.raises(ClitgError, match="Unknown feature builder"):
        build_feature_params(artificial("missing"), {})

    assert build("messages.transcribe", {"peer": "me", "message_id": 1, "wait_seconds": 5}) == {
        "peer": {"$peer": "me"},
        "msg_id": 1,
    }
    assert build("inbox.mentions", {"peer": "me", "limit": 2})["offset_id"] == 0
    assert build("messages.views", {"peer": "me", "message_id": [1]})["increment"] is False
    assert build("todos.get", {"message_id": [1]})["id"][0]["id"] == 1
    assert build("folders.shared-links", {"folder_id": 3})["chatlist"]["filter_id"] == 3
    assert (
        build(
            "messages.search-calendar",
            {"peer": "me", "filter": "InputMessagesFilterPhotos", "offset_id": 0},
        )["offset_date"]
        is None
    )
    assert (
        build(
            "messages.search-counts",
            {"peer": "me", "filter": ["InputMessagesFilterPhotos"]},
        )["filters"][0]["_"]
        == "InputMessagesFilterPhotos"
    )
    assert build("stories.stop-live", {"call_id": 1, "access_hash": 2})["call"]["access_hash"] == 2
    assert build("account.set-photo", {"file": "/tmp/photo.png"})["file"]["$upload"]
    assert (
        build("account.set-birthday", {"day": 1, "month": 2, "year": 2000})["birthday"]["year"]
        == 2000
    )
    assert build("account.set-color", {"color": 1, "for_profile": True})["for_profile"]
    assert build("account.clear-emoji-status", {})["emoji_status"]["_"] == "EmojiStatusEmpty"
    assert build("account.clear-personal-channel", {})["channel"]["_"] == "InputChannelEmpty"
    assert build("contacts.note-clear", {"user": "me"})["note"]["text"] == ""
    assert build("account.music", {"user": "me", "cursor": 4, "limit": 2, "hash": 0})["offset"] == 4
    assert (
        build(
            "stats.message-forwards",
            {"channel": "@channel", "message_id": 1, "cursor": "next", "limit": 2},
        )["offset"]
        == "next"
    )
    assert (
        build(
            "stats.message-forwards",
            {"channel": "@channel", "message_id": 1, "limit": 2},
        )["offset"]
        == ""
    )
    sticker = build(
        "stickers.add",
        {"short_name": "set", "file": "x.webp", "emoji": "🙂"},
        {"extra": 1},
    )
    assert sticker["_feature_files"] == "x.webp" and sticker["_feature_input"] == {"extra": 1}


def test_translation_and_composition_builders() -> None:
    translated = build("messages.translate", {"to_lang": "en", "text": "hola"})
    assert translated["text"][0]["text"] == "hola" and "peer" not in translated
    translated_messages = build(
        "messages.translate",
        {"to_lang": "en", "peer": "me", "message_id": [1]},
    )
    assert translated_messages["id"] == [1]
    for values in (
        {"to_lang": "en"},
        {"to_lang": "en", "text": "x", "message_id": [1]},
        {"to_lang": "en", "message_id": [1]},
    ):
        with pytest.raises(ClitgError):
            build("messages.translate", values)
    with pytest.raises(ClitgError, match="composition mode"):
        build("messages.compose", {"text": "hello"})
    assert build("messages.compose", {"text": "hello", "proofread": True})["proofread"]


def test_todo_builders_and_validation() -> None:
    created = build(
        "todos.create",
        {
            "peer": "me",
            "title": "Plan",
            "item": ["First", {"id": 4, "title": "Fourth"}],
            "others_can_append": True,
        },
    )
    todo = created["media"]["todo"]
    assert [item["id"] for item in todo["list"]] == [1, 4]
    assert todo["others_can_append"] is True and todo["others_can_complete"] is False
    appended = build("todos.append", {"peer": "me", "message_id": 1, "item": [{"title": "Next"}]})
    assert appended["list"][0]["id"] == 1 and "item" not in appended
    assert (
        build("todos.complete", {"peer": "me", "message_id": 1, "item_id": [1]})["incompleted"]
        == []
    )
    assert build("todos.reopen", {"peer": "me", "message_id": 1, "item_id": [1]})["completed"] == []
    for items, match in (
        ([1], "title"),
        ([{"id": 0, "title": "bad"}], "positive"),
        ([{"id": 1, "title": "a"}, {"id": 1, "title": "b"}], "unique"),
    ):
        with pytest.raises(ClitgError, match=match):
            build("todos.append", {"peer": "me", "message_id": 1, "item": items})


def test_quick_reply_and_business_builders() -> None:
    assert (
        build("quick-replies.create", {"name": "hello", "text": "Hi"})["quick_reply_shortcut"][
            "shortcut"
        ]
        == "hello"
    )
    assert (
        build("quick-replies.add-message", {"shortcut_id": 2, "text": "Hi"})[
            "quick_reply_shortcut"
        ]["shortcut_id"]
        == 2
    )
    assert build("business.get", {})["id"]["_"] == "InputUserSelf"
    assert "slug" not in build("business.link-create", {"message": "Hello"})
    assert (
        build("business.link-edit", {"slug": "abc", "message": "Hello", "title": "Title"})["slug"]
        == "abc"
    )
    greeting = build(
        "business.greeting-set",
        {
            "shortcut_id": 1,
            "no_activity_days": 7,
            "recipient_scope": ["contacts"],
            "user": ["@a"],
        },
    )
    assert greeting["message"]["recipients"]["contacts"] is True
    with pytest.raises(ClitgError, match="Unknown Business recipient"):
        build(
            "business.greeting-set",
            {"shortcut_id": 1, "no_activity_days": 7, "recipient_scope": ["invalid"]},
        )
    for schedule in ("always", "outside-hours", "custom"):
        values: dict[str, Any] = {"shortcut_id": 1, "schedule": schedule}
        if schedule == "custom":
            values.update(start_at="2026-01-01T00:00:00Z", end_at="2026-01-02T00:00:00Z")
        assert build("business.away-set", values)["message"]["schedule"]["_"]
    with pytest.raises(ClitgError, match="Unknown Business away"):
        build("business.away-set", {"shortcut_id": 1, "schedule": "sometimes"})
    with pytest.raises(ClitgError, match="require dates"):
        build(
            "business.away-set",
            {"shortcut_id": 1, "schedule": "custom", "start_at": "2026-01-01T00:00:00Z"},
        )
    hours = build("business.hours-set", {"timezone": "UTC", "open": ["0:09:00-17:00"]})
    assert hours["business_work_hours"]["weekly_open"][0]["start_minute"] == 540
    assert (
        build(
            "business.location-set",
            {"latitude": 1.0, "longitude": 2.0, "accuracy_radius": 5, "address": "Here"},
        )["geo_point"]["accuracy_radius"]
        == 5
    )
    assert (
        build("business.intro-set", {"title": "Welcome", "description": "Hello"})["intro"]["title"]
        == "Welcome"
    )
    bot = build(
        "business.bot-connect",
        {"bot": "@bot", "recipient_scope": [], "right": ["reply"]},
    )
    assert bot["rights"]["reply"] is True and bot["recipients"]["users"] is None
    with pytest.raises(ClitgError, match="Unknown Business bot right"):
        build("business.bot-connect", {"bot": "@bot", "right": ["everything"]})


@pytest.mark.parametrize(
    "value,match",
    [
        ("bad", "must use"),
        ("7:09:00-10:00", "outside"),
        ("0:09:00-24:01", "outside"),
        ("0:09:60-10:00", "interval"),
        ("0:10:00-09:00", "interval"),
    ],
)
def test_business_hours_errors(value: str, match: str) -> None:
    with pytest.raises(ClitgError, match=match):
        build("business.hours-set", {"timezone": "UTC", "open": [value]})


def test_account_contacts_and_result_normalization() -> None:
    status = build(
        "account.set-emoji-status",
        {"document_id": 1, "until": "2026-01-01T00:00:00Z"},
    )["emoji_status"]
    assert status["until"]["$datetime"]
    assert build("account.set-emoji-status", {"document_id": 1})["emoji_status"]["until"] is None
    direct = build("contacts.import", {"phone": "+1", "first_name": "A", "last_name": "B"})
    assert direct["contacts"][0]["last_name"] == "B"
    batch = build(
        "contacts.import",
        {},
        [{"phone": "+2", "first_name": "C"}, {"phone": "+3", "first_name": "D"}],
    )
    assert [item["client_id"] for item in batch["contacts"]] == [1, 2]
    with pytest.raises(ClitgError, match="phone and first name"):
        build("contacts.import", {})

    catalog = feature_catalog()
    assert catalog["messages.translate"]["quota_consuming"] is True
    assert catalog["stories.viewers"]["paginated"] is True
    assert catalog["stories.viewers"]["cursor_param"] == "offset"
    business_options = {
        option["name"]: option for option in catalog["business.away-set"]["parameters"]
    }
    assert business_options["schedule"]["allowed_values"] == [
        "always",
        "outside-hours",
        "custom",
    ]
    assert business_options["schedule"]["help"]
    kind, value = normalize_feature_result(
        {"_": "Container", "items": [{"_": "Item", "id": 1}], "count": 1}
    )
    assert kind == "Container" and value == {"items": [{"id": 1}], "count": 1}
    assert normalize_feature_result([1, "x"]) == ("list", [1, "x"])
    assert normalize_feature_result(None) == ("NoneType", None)
