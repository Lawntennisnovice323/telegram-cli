"""Stable high-level feature catalog for Telegram capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from clitg.errors import ClitgError
from clitg.models import ErrorCode
from clitg.operations import Risk

OptionKind = Literal["str", "int", "float", "bool", "str_list", "int_list"]
Resolver = Literal[
    "peer",
    "channel",
    "user",
    "peers",
    "users",
    "bytes",
    "datetime",
    "reaction",
    "tone",
    "chatlist",
    "stickerset",
    "text",
]


@dataclass(frozen=True)
class FeatureOption:
    """One explicit CLI option mapped to a Telegram request parameter."""

    name: str
    kind: OptionKind = "str"
    required: bool = False
    default: Any = None
    telegram_name: str | None = None
    resolver: Resolver | None = None
    help: str = ""
    emit_default: bool = False
    choices: tuple[str, ...] = ()

    @property
    def flag(self) -> str:
        return f"--{self.name.replace('_', '-')}"


@dataclass(frozen=True)
class FeatureCommand:
    """One stable agent-facing command backed by a generated MTProto method."""

    command: str
    method: str
    risk: Risk
    summary: str
    options: tuple[FeatureOption, ...] = ()
    builder: str = "default"
    requirements: tuple[str, ...] = ()
    quota_consuming: bool = False
    paginated: bool = False
    cursor_param: str | None = None
    result_model: str = "FeatureResult"

    @property
    def mutation(self) -> bool:
        return self.risk != "read"

    @property
    def critical(self) -> bool:
        return self.risk == "critical"


def s(
    name: str,
    *,
    required: bool = False,
    default: Any = None,
    telegram_name: str | None = None,
    resolver: Resolver | None = None,
    help: str = "",
    choices: tuple[str, ...] = (),
) -> FeatureOption:
    return FeatureOption(
        name, "str", required, default, telegram_name, resolver, help, False, choices
    )


def i(
    name: str,
    *,
    required: bool = False,
    default: Any = None,
    telegram_name: str | None = None,
    resolver: Resolver | None = None,
    help: str = "",
) -> FeatureOption:
    return FeatureOption(name, "int", required, default, telegram_name, resolver, help)


def f(
    name: str,
    *,
    required: bool = False,
    default: Any = None,
    telegram_name: str | None = None,
    help: str = "",
) -> FeatureOption:
    return FeatureOption(name, "float", required, default, telegram_name, None, help)


def b(
    name: str,
    *,
    default: bool = False,
    telegram_name: str | None = None,
    help: str = "",
    emit_default: bool = False,
) -> FeatureOption:
    return FeatureOption(name, "bool", False, default, telegram_name, None, help, emit_default)


def ss(
    name: str,
    *,
    required: bool = False,
    telegram_name: str | None = None,
    resolver: Resolver | None = None,
    help: str = "",
    choices: tuple[str, ...] = (),
) -> FeatureOption:
    return FeatureOption(
        name,
        "str_list",
        required,
        None,
        telegram_name,
        resolver,
        help,
        False,
        choices,
    )


def ii(
    name: str,
    *,
    required: bool = False,
    telegram_name: str | None = None,
    help: str = "",
) -> FeatureOption:
    return FeatureOption(name, "int_list", required, None, telegram_name, None, help)


PEER = s("peer", required=True, resolver="peer")
CHANNEL = s("channel", required=True, resolver="channel")
MESSAGE_ID = i("message_id", required=True, telegram_name="msg_id")
STORY_ID = i("story_id", required=True, telegram_name="id")
LIMIT = i("limit", default=100)
OFFSET = s("cursor", default="", telegram_name="offset")
CURSOR = s("cursor")
BUSINESS_BOT_RIGHTS = {
    "reply",
    "read_messages",
    "delete_sent_messages",
    "delete_received_messages",
    "edit_name",
    "edit_bio",
    "edit_profile_photo",
    "edit_username",
    "view_gifts",
    "sell_gifts",
    "change_gift_settings",
    "transfer_and_upgrade_gifts",
    "transfer_stars",
    "manage_stories",
}
BUSINESS_RECIPIENT_SCOPES = (
    "existing_chats",
    "new_chats",
    "contacts",
    "non_contacts",
    "exclude_selected",
)
BUSINESS_AWAY_SCHEDULES = ("always", "outside-hours", "custom")


def cmd(
    command: str,
    method: str,
    risk: Risk,
    summary: str,
    *options: FeatureOption,
    builder: str = "default",
    requirements: tuple[str, ...] = (),
    quota: bool = False,
    paginated: bool = False,
    cursor_param: str | None = None,
) -> FeatureCommand:
    return FeatureCommand(
        command,
        method,
        risk,
        summary,
        options,
        builder,
        requirements,
        quota,
        paginated,
        cursor_param,
    )


FEATURE_COMMANDS = (
    # Telegram AI and transcription.
    cmd(
        "messages.translate",
        "messages.translateText",
        "read",
        "Translate messages or supplied text.",
        s("to_lang", required=True),
        s("peer", resolver="peer"),
        ii(
            "message_id",
            telegram_name="id",
            help="Repeat for each message ID; requires --peer and excludes --text.",
        ),
        s("text", help="Supplied text to translate; excludes --peer and --message-id."),
        s("tone"),
        builder="translate",
        quota=True,
    ),
    cmd(
        "messages.transcribe",
        "messages.transcribeAudio",
        "read",
        "Transcribe one voice or video message.",
        PEER,
        MESSAGE_ID,
        i("wait_seconds", default=0, help="Bounded wait for a matching completion update."),
        builder="transcribe",
        quota=True,
    ),
    cmd(
        "messages.rate-transcription",
        "messages.rateTranscribedAudio",
        "write",
        "Rate one Telegram transcription.",
        PEER,
        MESSAGE_ID,
        i("transcription_id", required=True),
        b("good", emit_default=True),
    ),
    cmd(
        "messages.summarize",
        "messages.summarizeText",
        "read",
        "Summarize one Telegram message.",
        PEER,
        i("message_id", required=True, telegram_name="id"),
        s("to_lang"),
        s("tone"),
        quota=True,
    ),
    cmd(
        "messages.compose",
        "messages.composeMessageWithAI",
        "read",
        "Transform supplied text with Telegram AI.",
        s("text", required=True, resolver="text"),
        b("proofread"),
        b("emojify"),
        s("translate_to_lang"),
        s("tone", resolver="tone"),
        builder="compose",
        quota=True,
    ),
    cmd(
        "ai-tones.list", "aicompose.getTones", "read", "List saved AI tones.", i("hash", default=0)
    ),
    cmd(
        "ai-tones.get",
        "aicompose.getTone",
        "read",
        "Get one AI tone.",
        s("tone", required=True, resolver="tone"),
    ),
    cmd(
        "ai-tones.create",
        "aicompose.createTone",
        "write",
        "Create a custom AI tone.",
        i("emoji_id", required=True),
        s("title", required=True),
        s("prompt", required=True),
        b("display_author"),
        requirements=("premium",),
    ),
    cmd(
        "ai-tones.edit",
        "aicompose.updateTone",
        "write",
        "Edit a custom AI tone.",
        s("tone", required=True, resolver="tone"),
        i("emoji_id"),
        s("title"),
        s("prompt"),
        b("display_author"),
        requirements=("premium",),
    ),
    cmd(
        "ai-tones.save",
        "aicompose.saveTone",
        "write",
        "Save an AI tone.",
        s("tone", required=True, resolver="tone"),
        b("unsave", emit_default=True),
    ),
    cmd(
        "ai-tones.unsave",
        "aicompose.saveTone",
        "destructive",
        "Remove a saved AI tone.",
        s("tone", required=True, resolver="tone"),
        b("unsave", default=True, emit_default=True),
    ),
    cmd(
        "ai-tones.delete",
        "aicompose.deleteTone",
        "destructive",
        "Delete a custom AI tone.",
        s("tone", required=True, resolver="tone"),
    ),
    # Collaborative todo lists.
    cmd(
        "todos.create",
        "messages.sendMedia",
        "write",
        "Create a collaborative checklist.",
        PEER,
        s("title", required=True),
        ss("item", required=True),
        b("others_can_append"),
        b("others_can_complete"),
        builder="todo-create",
        requirements=("premium",),
    ),
    cmd(
        "todos.get",
        "messages.getMessages",
        "read",
        "Get one checklist message.",
        ii("message_id", required=True, telegram_name="id"),
        builder="message-ids",
    ),
    cmd(
        "todos.append",
        "messages.appendTodoList",
        "write",
        "Append checklist items.",
        PEER,
        MESSAGE_ID,
        ss("item", required=True),
        builder="todo-append",
    ),
    cmd(
        "todos.complete",
        "messages.toggleTodoCompleted",
        "write",
        "Complete checklist items.",
        PEER,
        MESSAGE_ID,
        ii("item_id", required=True, telegram_name="completed"),
        builder="todo-complete",
    ),
    cmd(
        "todos.reopen",
        "messages.toggleTodoCompleted",
        "write",
        "Reopen checklist items.",
        PEER,
        MESSAGE_ID,
        ii("item_id", required=True, telegram_name="incompleted"),
        builder="todo-reopen",
    ),
    # Quick replies and Telegram Business.
    cmd(
        "quick-replies.list",
        "messages.getQuickReplies",
        "read",
        "List quick reply shortcuts.",
        i("hash", default=0),
        requirements=("business",),
    ),
    cmd(
        "quick-replies.get",
        "messages.getQuickReplyMessages",
        "read",
        "Get quick reply messages.",
        i("shortcut_id", required=True),
        ii("message_id", telegram_name="id"),
        i("hash", default=0),
        requirements=("business",),
    ),
    cmd(
        "quick-replies.check",
        "messages.checkQuickReplyShortcut",
        "read",
        "Check a quick reply name.",
        s("name", required=True, telegram_name="shortcut"),
        requirements=("business",),
    ),
    cmd(
        "quick-replies.create",
        "messages.sendMessage",
        "write",
        "Create a text quick reply.",
        s("name", required=True),
        s("text", required=True),
        builder="quick-create",
        requirements=("business",),
    ),
    cmd(
        "quick-replies.add-message",
        "messages.sendMessage",
        "write",
        "Add text to a quick reply.",
        i("shortcut_id", required=True),
        s("text", required=True),
        builder="quick-add",
        requirements=("business",),
    ),
    cmd(
        "quick-replies.delete-message",
        "messages.deleteQuickReplyMessages",
        "destructive",
        "Delete quick reply messages.",
        i("shortcut_id", required=True),
        ii("message_id", required=True, telegram_name="id"),
        requirements=("business",),
    ),
    cmd(
        "quick-replies.rename",
        "messages.editQuickReplyShortcut",
        "write",
        "Rename a quick reply.",
        i("shortcut_id", required=True),
        s("name", required=True, telegram_name="shortcut"),
        requirements=("business",),
    ),
    cmd(
        "quick-replies.reorder",
        "messages.reorderQuickReplies",
        "write",
        "Reorder quick replies.",
        ii("shortcut_id", required=True, telegram_name="order"),
        requirements=("business",),
    ),
    cmd(
        "quick-replies.send",
        "messages.sendQuickReplyMessages",
        "write",
        "Send a quick reply.",
        PEER,
        i("shortcut_id", required=True),
        ii("message_id", required=True, telegram_name="id"),
        requirements=("business",),
    ),
    cmd(
        "quick-replies.delete",
        "messages.deleteQuickReplyShortcut",
        "destructive",
        "Delete a quick reply.",
        i("shortcut_id", required=True),
        requirements=("business",),
    ),
    cmd(
        "business.get",
        "users.getFullUser",
        "read",
        "Inspect current Business settings.",
        builder="self-user",
        requirements=("business",),
    ),
    cmd(
        "business.links",
        "account.getBusinessChatLinks",
        "read",
        "List Business chat links.",
        requirements=("business",),
    ),
    cmd(
        "business.link-create",
        "account.createBusinessChatLink",
        "write",
        "Create a Business chat link.",
        s("message", required=True),
        s("title"),
        builder="business-link",
        requirements=("business",),
    ),
    cmd(
        "business.link-edit",
        "account.editBusinessChatLink",
        "write",
        "Edit a Business chat link.",
        s("slug", required=True),
        s("message", required=True),
        s("title"),
        builder="business-link",
        requirements=("business",),
    ),
    cmd(
        "business.link-delete",
        "account.deleteBusinessChatLink",
        "destructive",
        "Delete a Business chat link.",
        s("slug", required=True),
        requirements=("business",),
    ),
    cmd(
        "business.greeting-set",
        "account.updateBusinessGreetingMessage",
        "write",
        "Set the Business greeting.",
        i("shortcut_id", required=True),
        i("no_activity_days", default=7),
        ss(
            "recipient_scope",
            help="Repeat: existing_chats, new_chats, contacts, non_contacts, exclude_selected.",
            choices=BUSINESS_RECIPIENT_SCOPES,
        ),
        ss("user", resolver="users"),
        builder="business-greeting",
        requirements=("business",),
    ),
    cmd(
        "business.greeting-disable",
        "account.updateBusinessGreetingMessage",
        "destructive",
        "Disable the Business greeting.",
        requirements=("business",),
    ),
    cmd(
        "business.away-set",
        "account.updateBusinessAwayMessage",
        "write",
        "Set the Business away message.",
        i("shortcut_id", required=True),
        s(
            "schedule",
            default="always",
            help="always, outside-hours, or custom.",
            choices=BUSINESS_AWAY_SCHEDULES,
        ),
        s("start_at", resolver="datetime"),
        s("end_at", resolver="datetime"),
        ss(
            "recipient_scope",
            help="Repeat: existing_chats, new_chats, contacts, non_contacts, exclude_selected.",
            choices=BUSINESS_RECIPIENT_SCOPES,
        ),
        ss("user", resolver="users"),
        b("offline_only"),
        builder="business-away",
        requirements=("business",),
    ),
    cmd(
        "business.away-disable",
        "account.updateBusinessAwayMessage",
        "destructive",
        "Disable the Business away message.",
        requirements=("business",),
    ),
    cmd(
        "business.hours-set",
        "account.updateBusinessWorkHours",
        "write",
        "Set Business opening hours.",
        s("timezone", required=True),
        ss(
            "open",
            required=True,
            help="Repeat DAY:HH:MM-HH:MM; DAY 0 is Monday and DAY 6 is Sunday.",
        ),
        builder="business-hours",
        requirements=("business",),
    ),
    cmd(
        "business.hours-clear",
        "account.updateBusinessWorkHours",
        "destructive",
        "Clear Business opening hours.",
        requirements=("business",),
    ),
    cmd(
        "business.location-set",
        "account.updateBusinessLocation",
        "write",
        "Set a Business location.",
        f("latitude", required=True),
        f("longitude", required=True),
        s("address", required=True),
        i("accuracy_radius"),
        builder="business-location",
        requirements=("business",),
    ),
    cmd(
        "business.location-clear",
        "account.updateBusinessLocation",
        "destructive",
        "Clear the Business location.",
        requirements=("business",),
    ),
    cmd(
        "business.intro-set",
        "account.updateBusinessIntro",
        "write",
        "Set a Business introduction.",
        s("title", required=True),
        s("description", required=True),
        builder="business-intro",
        requirements=("business",),
    ),
    cmd(
        "business.intro-clear",
        "account.updateBusinessIntro",
        "destructive",
        "Clear the Business introduction.",
        requirements=("business",),
    ),
    cmd(
        "business.bots",
        "account.getConnectedBots",
        "read",
        "List connected Business bots.",
        requirements=("business",),
    ),
    cmd(
        "business.bot-connect",
        "account.updateConnectedBot",
        "critical",
        "Connect or update a Business bot.",
        s("bot", required=True, resolver="user"),
        ss(
            "recipient_scope",
            help="Repeat: existing_chats, new_chats, contacts, non_contacts, exclude_selected.",
            choices=BUSINESS_RECIPIENT_SCOPES,
        ),
        ss("user", resolver="users"),
        ss(
            "right",
            help="Repeat a BusinessBotRights field; inspect commands get for allowed values.",
            choices=tuple(sorted(BUSINESS_BOT_RIGHTS)),
        ),
        builder="business-bot",
        requirements=("business",),
    ),
    cmd(
        "business.bot-pause",
        "account.toggleConnectedBotPaused",
        "write",
        "Pause a Business bot for a peer.",
        PEER,
        b("paused", default=True, emit_default=True),
        requirements=("business",),
    ),
    cmd(
        "business.bot-resume",
        "account.toggleConnectedBotPaused",
        "write",
        "Resume a Business bot for a peer.",
        PEER,
        b("paused", emit_default=True),
        requirements=("business",),
    ),
    cmd(
        "business.bot-disconnect-peer",
        "account.disablePeerConnectedBot",
        "destructive",
        "Disconnect a peer from Business bots.",
        PEER,
        requirements=("business",),
    ),
    # Focused unread feeds and message insights.
    cmd(
        "inbox.mentions",
        "messages.getUnreadMentions",
        "read",
        "List unread mentions.",
        PEER,
        LIMIT,
        i("top_msg_id"),
        CURSOR,
        builder="unread-feed",
        paginated=True,
        cursor_param="offset_id",
    ),
    cmd(
        "inbox.reactions",
        "messages.getUnreadReactions",
        "read",
        "List unread reactions.",
        PEER,
        LIMIT,
        i("top_msg_id"),
        CURSOR,
        builder="unread-feed",
        paginated=True,
        cursor_param="offset_id",
    ),
    cmd(
        "inbox.poll-votes",
        "messages.getUnreadPollVotes",
        "read",
        "List polls with unread votes.",
        PEER,
        LIMIT,
        i("top_msg_id"),
        CURSOR,
        builder="unread-feed",
        paginated=True,
        cursor_param="offset_id",
    ),
    cmd(
        "messages.search-calendar",
        "messages.getSearchResultsCalendar",
        "read",
        "Get a search results calendar.",
        PEER,
        s("filter", default="InputMessagesFilterEmpty"),
        i("offset_id", default=0),
        s("offset_date", resolver="datetime"),
        builder="message-filter",
    ),
    cmd(
        "messages.search-counts",
        "messages.getSearchCounters",
        "read",
        "Count search result media types.",
        PEER,
        ss("filter", required=True),
        i("top_msg_id"),
        builder="message-filters",
    ),
    cmd(
        "messages.read-participants",
        "messages.getMessageReadParticipants",
        "read",
        "List message readers.",
        PEER,
        MESSAGE_ID,
    ),
    cmd(
        "messages.read-date",
        "messages.getOutboxReadDate",
        "read",
        "Get an outgoing message read date.",
        PEER,
        MESSAGE_ID,
    ),
    cmd(
        "messages.recent-locations",
        "messages.getRecentLocations",
        "read",
        "List recent live locations.",
        PEER,
        LIMIT,
        i("hash", default=0),
    ),
    cmd(
        "messages.views",
        "messages.getMessagesViews",
        "read",
        "Get message view counters without incrementing them.",
        PEER,
        ii("message_id", required=True, telegram_name="id"),
        builder="views",
    ),
    cmd(
        "messages.link",
        "channels.exportMessageLink",
        "read",
        "Export a permanent message link.",
        CHANNEL,
        i("message_id", required=True, telegram_name="id"),
        b("grouped"),
        b("thread"),
    ),
    # Shared folders.
    cmd(
        "folders.share",
        "chatlists.exportChatlistInvite",
        "write",
        "Share a chat folder.",
        i("folder_id", required=True),
        s("title", default=""),
        ss("peer", required=True, telegram_name="peers", resolver="peers"),
        builder="chatlist",
    ),
    cmd(
        "folders.shared-links",
        "chatlists.getExportedInvites",
        "read",
        "List shared folder links.",
        i("folder_id", required=True),
        builder="chatlist",
    ),
    cmd(
        "folders.edit-shared-link",
        "chatlists.editExportedInvite",
        "write",
        "Edit a shared folder link.",
        i("folder_id", required=True),
        s("slug", required=True),
        s("title"),
        ss("peer", telegram_name="peers", resolver="peers"),
        builder="chatlist",
    ),
    cmd(
        "folders.revoke-shared-link",
        "chatlists.deleteExportedInvite",
        "destructive",
        "Revoke a shared folder link.",
        i("folder_id", required=True),
        s("slug", required=True),
        builder="chatlist",
    ),
    cmd(
        "folders.inspect-shared-link",
        "chatlists.checkChatlistInvite",
        "read",
        "Inspect a shared folder link.",
        s("slug", required=True),
    ),
    cmd(
        "folders.join-shared",
        "chatlists.joinChatlistInvite",
        "write",
        "Join a shared folder.",
        s("slug", required=True),
        ss("peer", required=True, telegram_name="peers", resolver="peers"),
    ),
    cmd(
        "folders.shared-updates",
        "chatlists.getChatlistUpdates",
        "read",
        "Inspect shared folder updates.",
        i("folder_id", required=True),
        builder="chatlist",
    ),
    cmd(
        "folders.accept-shared-updates",
        "chatlists.joinChatlistUpdates",
        "write",
        "Accept shared folder updates.",
        i("folder_id", required=True),
        ss("peer", required=True, telegram_name="peers", resolver="peers"),
        builder="chatlist",
    ),
    cmd(
        "folders.dismiss-shared-updates",
        "chatlists.hideChatlistUpdates",
        "write",
        "Dismiss shared folder updates.",
        i("folder_id", required=True),
        builder="chatlist",
    ),
    cmd(
        "folders.leave-shared",
        "chatlists.leaveChatlist",
        "destructive",
        "Leave a shared folder.",
        i("folder_id", required=True),
        ss("peer", required=True, telegram_name="peers", resolver="peers"),
        builder="chatlist",
    ),
    # Statistics and moderation.
    cmd(
        "stats.channel",
        "stats.getBroadcastStats",
        "read",
        "Get channel statistics.",
        CHANNEL,
        b("dark"),
        requirements=("admin",),
    ),
    cmd(
        "stats.group",
        "stats.getMegagroupStats",
        "read",
        "Get supergroup statistics.",
        CHANNEL,
        b("dark"),
        requirements=("admin",),
    ),
    cmd(
        "stats.message",
        "stats.getMessageStats",
        "read",
        "Get message statistics.",
        CHANNEL,
        MESSAGE_ID,
        b("dark"),
        requirements=("admin",),
    ),
    cmd(
        "stats.message-forwards",
        "stats.getMessagePublicForwards",
        "read",
        "List public message forwards.",
        CHANNEL,
        MESSAGE_ID,
        OFFSET,
        LIMIT,
        requirements=("admin",),
        paginated=True,
        cursor_param="offset",
    ),
    cmd(
        "stats.story",
        "stats.getStoryStats",
        "read",
        "Get story statistics.",
        PEER,
        STORY_ID,
        b("dark"),
        requirements=("admin",),
    ),
    cmd(
        "stats.story-forwards",
        "stats.getStoryPublicForwards",
        "read",
        "List public story forwards.",
        PEER,
        STORY_ID,
        OFFSET,
        LIMIT,
        requirements=("admin",),
        paginated=True,
        cursor_param="offset",
    ),
    cmd(
        "stats.poll",
        "stats.getPollStats",
        "read",
        "Get poll statistics.",
        PEER,
        MESSAGE_ID,
        b("dark"),
        requirements=("admin",),
    ),
    cmd(
        "stats.graph",
        "stats.loadAsyncGraph",
        "read",
        "Load an asynchronous statistics graph.",
        s("token", required=True),
        i("x"),
    ),
    cmd(
        "messages.report",
        "messages.report",
        "critical",
        "Report messages.",
        PEER,
        ii("message_id", required=True, telegram_name="id"),
        s("option", required=True, resolver="bytes"),
        s("message", default=""),
    ),
    cmd("dialogs.report-spam", "messages.reportSpam", "critical", "Report a peer for spam.", PEER),
    cmd(
        "stories.report",
        "stories.report",
        "critical",
        "Report stories.",
        PEER,
        ii("story_id", required=True, telegram_name="id"),
        s("option", required=True, resolver="bytes"),
        s("message", default=""),
    ),
    cmd(
        "messages.report-reaction",
        "messages.reportReaction",
        "critical",
        "Report a message reaction.",
        PEER,
        i("message_id", required=True, telegram_name="id"),
        s("reaction_peer", required=True, resolver="peer"),
    ),
    cmd(
        "messages.remove-participant-reaction",
        "messages.deleteParticipantReaction",
        "destructive",
        "Remove one participant reaction.",
        PEER,
        MESSAGE_ID,
        s("participant", required=True, resolver="peer"),
    ),
    cmd(
        "messages.clear-participant-reactions",
        "messages.deleteParticipantReactions",
        "destructive",
        "Remove all participant reactions.",
        PEER,
        s("participant", required=True, resolver="peer"),
    ),
    cmd(
        "join-requests.approve-all",
        "messages.hideAllChatJoinRequests",
        "write",
        "Approve all pending join requests.",
        PEER,
        s("link"),
        b("approved", default=True),
    ),
    cmd(
        "join-requests.reject-all",
        "messages.hideAllChatJoinRequests",
        "destructive",
        "Reject all pending join requests.",
        PEER,
        s("link"),
        b("approved"),
    ),
    cmd(
        "chats.set-anti-spam",
        "channels.toggleAntiSpam",
        "critical",
        "Change channel anti-spam.",
        CHANNEL,
        b("enabled", emit_default=True),
    ),
    cmd(
        "chats.set-slow-mode",
        "channels.toggleSlowMode",
        "critical",
        "Change channel slow mode.",
        CHANNEL,
        i("seconds", required=True),
    ),
    cmd(
        "chats.set-default-permissions",
        "messages.editChatDefaultBannedRights",
        "critical",
        "Change default chat permissions.",
        PEER,
        builder="input-required",
    ),
    cmd(
        "chats.set-member-rank",
        "messages.editChatParticipantRank",
        "critical",
        "Set a participant rank.",
        PEER,
        s("participant", required=True, resolver="peer"),
        s("rank", required=True),
    ),
    # Complete story lifecycle, excluding media transport.
    cmd(
        "stories.archive",
        "stories.getStoriesArchive",
        "read",
        "List archived stories.",
        PEER,
        CURSOR,
        LIMIT,
        paginated=True,
        cursor_param="offset_id",
    ),
    cmd(
        "stories.pinned",
        "stories.getPinnedStories",
        "read",
        "List pinned stories.",
        PEER,
        CURSOR,
        LIMIT,
        paginated=True,
        cursor_param="offset_id",
    ),
    cmd(
        "stories.views",
        "stories.getStoriesViews",
        "read",
        "Get story view summaries.",
        PEER,
        ii("story_id", required=True, telegram_name="id"),
    ),
    cmd(
        "stories.viewers",
        "stories.getStoryViewsList",
        "read",
        "List story viewers.",
        PEER,
        STORY_ID,
        OFFSET,
        LIMIT,
        b("just_contacts"),
        b("reactions_first"),
        b("forwards_first"),
        s("query", telegram_name="q"),
        paginated=True,
        cursor_param="offset",
    ),
    cmd(
        "stories.reactions",
        "stories.getStoryReactionsList",
        "read",
        "List story reactions.",
        PEER,
        STORY_ID,
        OFFSET,
        LIMIT,
        b("forwards_first"),
        s("reaction", resolver="reaction"),
        paginated=True,
        cursor_param="offset",
    ),
    cmd(
        "stories.react",
        "stories.sendReaction",
        "write",
        "React to a story.",
        PEER,
        i("story_id", required=True),
        s("reaction", required=True, resolver="reaction"),
        b("add_to_recent"),
    ),
    cmd("stories.link", "stories.exportStoryLink", "read", "Export a story link.", PEER, STORY_ID),
    cmd(
        "stories.hide-peer",
        "stories.togglePeerStoriesHidden",
        "write",
        "Hide a peer's stories.",
        PEER,
        b("hidden", default=True, emit_default=True),
    ),
    cmd(
        "stories.show-peer",
        "stories.togglePeerStoriesHidden",
        "write",
        "Show a peer's stories.",
        PEER,
        b("hidden", emit_default=True),
    ),
    cmd(
        "stories.pin-many",
        "stories.togglePinned",
        "write",
        "Pin stories.",
        PEER,
        ii("story_id", required=True, telegram_name="id"),
        b("pinned", default=True, emit_default=True),
    ),
    cmd(
        "stories.unpin-many",
        "stories.togglePinned",
        "write",
        "Unpin stories.",
        PEER,
        ii("story_id", required=True, telegram_name="id"),
        b("pinned", emit_default=True),
    ),
    cmd(
        "stories.stealth",
        "stories.activateStealthMode",
        "write",
        "Activate story stealth mode.",
        b("past"),
        b("future"),
        requirements=("premium",),
    ),
    cmd(
        "stories.albums",
        "stories.getAlbums",
        "read",
        "List story albums.",
        PEER,
        i("hash", default=0),
    ),
    cmd(
        "stories.album",
        "stories.getAlbumStories",
        "read",
        "Get stories in an album.",
        PEER,
        i("album_id", required=True),
        CURSOR,
        LIMIT,
        paginated=True,
        cursor_param="offset",
    ),
    cmd(
        "stories.album-create",
        "stories.createAlbum",
        "write",
        "Create a story album.",
        PEER,
        s("title", required=True),
        ii("story_id", required=True, telegram_name="stories"),
    ),
    cmd(
        "stories.album-edit",
        "stories.updateAlbum",
        "write",
        "Edit a story album.",
        PEER,
        i("album_id", required=True),
        s("title"),
        ii("add_story", telegram_name="add_stories"),
        ii("delete_story", telegram_name="delete_stories"),
        ii("order"),
    ),
    cmd(
        "stories.album-delete",
        "stories.deleteAlbum",
        "destructive",
        "Delete a story album.",
        PEER,
        i("album_id", required=True),
    ),
    cmd(
        "stories.albums-reorder",
        "stories.reorderAlbums",
        "write",
        "Reorder story albums.",
        PEER,
        ii("album_id", required=True, telegram_name="order"),
    ),
    cmd(
        "stories.mark-read",
        "stories.readStories",
        "write",
        "Mark stories read explicitly.",
        PEER,
        i("max_id", required=True),
    ),
    cmd("stories.live-status", "stories.getPeerStories", "read", "Inspect live story state.", PEER),
    cmd(
        "stories.start-live",
        "stories.startLive",
        "write",
        "Start a live story session without media transport.",
        PEER,
        s("caption"),
        b("pinned"),
        b("noforwards"),
        b("messages_enabled"),
        builder="input-required",
    ),
    cmd(
        "stories.stop-live",
        "phone.discardGroupCall",
        "destructive",
        "Stop a live story session.",
        i("call_id", required=True),
        i("access_hash", required=True),
        builder="group-call",
    ),
    # Profile and contacts. Nearby contacts are intentionally absent.
    cmd(
        "account.edit-profile",
        "account.updateProfile",
        "write",
        "Edit account profile fields.",
        s("first_name"),
        s("last_name"),
        s("about"),
    ),
    cmd(
        "account.set-photo",
        "photos.uploadProfilePhoto",
        "write",
        "Set a profile photo from a local upload.",
        s("file", required=True),
        builder="upload-photo",
    ),
    cmd(
        "account.delete-photo",
        "photos.deletePhotos",
        "destructive",
        "Delete selected profile photos.",
        builder="input-required",
    ),
    cmd(
        "account.set-birthday",
        "account.updateBirthday",
        "write",
        "Set the account birthday.",
        i("day", required=True),
        i("month", required=True),
        i("year"),
        builder="birthday",
    ),
    cmd(
        "account.clear-birthday",
        "account.updateBirthday",
        "destructive",
        "Clear the account birthday.",
    ),
    cmd(
        "account.set-color",
        "account.updateColor",
        "write",
        "Set the account color.",
        i("color"),
        i("background_emoji_id"),
        b("for_profile"),
        builder="peer-color",
    ),
    cmd(
        "account.clear-color",
        "account.updateColor",
        "destructive",
        "Clear the account color.",
        b("for_profile"),
    ),
    cmd(
        "account.set-emoji-status",
        "account.updateEmojiStatus",
        "write",
        "Set an emoji status.",
        i("document_id", required=True),
        s("until", resolver="datetime"),
        builder="emoji-status",
    ),
    cmd(
        "account.clear-emoji-status",
        "account.updateEmojiStatus",
        "destructive",
        "Clear the emoji status.",
        builder="emoji-status-empty",
    ),
    cmd(
        "account.set-personal-channel",
        "account.updatePersonalChannel",
        "write",
        "Set the personal profile channel.",
        CHANNEL,
    ),
    cmd(
        "account.clear-personal-channel",
        "account.updatePersonalChannel",
        "destructive",
        "Clear the personal profile channel.",
        builder="empty-channel",
    ),
    cmd(
        "account.music",
        "users.getSavedMusic",
        "read",
        "List profile music.",
        s("user", default="me", telegram_name="id", resolver="user"),
        CURSOR,
        LIMIT,
        i("hash", default=0),
        paginated=True,
        cursor_param="offset",
    ),
    cmd(
        "account.music-add",
        "account.saveMusic",
        "write",
        "Add or move profile music.",
        builder="input-required",
    ),
    cmd(
        "account.music-remove",
        "account.saveMusic",
        "destructive",
        "Remove profile music.",
        builder="input-required",
    ),
    cmd(
        "contacts.import",
        "contacts.importContacts",
        "write",
        "Import one or more contacts.",
        s("phone"),
        s("first_name"),
        s("last_name"),
        builder="contacts-import",
    ),
    cmd("contacts.birthdays", "contacts.getBirthdays", "read", "List contact birthdays."),
    cmd(
        "contacts.top",
        "contacts.getTopPeers",
        "read",
        "List frequently used contacts.",
        CURSOR,
        LIMIT,
        i("hash", default=0),
        b("correspondents", default=True),
        b("groups"),
        b("channels"),
        b("bots_pm"),
        paginated=True,
        cursor_param="offset",
    ),
    cmd(
        "contacts.note-set",
        "contacts.updateContactNote",
        "write",
        "Set a private contact note.",
        s("user", required=True, resolver="user", telegram_name="id"),
        s("note", required=True, resolver="text"),
    ),
    cmd(
        "contacts.note-clear",
        "contacts.updateContactNote",
        "destructive",
        "Clear a private contact note.",
        s("user", required=True, resolver="user", telegram_name="id"),
        builder="empty-note",
    ),
    cmd(
        "contacts.resolve-username",
        "contacts.resolveUsername",
        "read",
        "Resolve a username.",
        s("username", required=True),
        s("referer"),
    ),
    cmd(
        "contacts.resolve-phone",
        "contacts.resolvePhone",
        "read",
        "Resolve a phone number.",
        s("phone", required=True),
    ),
    # Sticker sets, custom emoji, GIF state, and schedule queue.
    cmd(
        "stickers.sets",
        "messages.getAllStickers",
        "read",
        "List installed sticker sets.",
        i("hash", default=0),
    ),
    cmd(
        "stickers.mine",
        "messages.getMyStickers",
        "read",
        "List sticker sets created by the account.",
        CURSOR,
        LIMIT,
        paginated=True,
        cursor_param="offset_id",
    ),
    cmd(
        "stickers.set",
        "messages.getStickerSet",
        "read",
        "Get one sticker set.",
        s("short_name", required=True, resolver="stickerset", telegram_name="stickerset"),
        i("hash", default=0),
    ),
    cmd(
        "stickers.archived",
        "messages.getArchivedStickers",
        "read",
        "List archived sticker sets.",
        CURSOR,
        LIMIT,
        b("masks"),
        b("emojis"),
        paginated=True,
        cursor_param="offset_id",
    ),
    cmd(
        "stickers.install",
        "messages.installStickerSet",
        "write",
        "Install a sticker set.",
        s("short_name", required=True, resolver="stickerset", telegram_name="stickerset"),
        b("archived", emit_default=True),
    ),
    cmd(
        "stickers.uninstall",
        "messages.uninstallStickerSet",
        "destructive",
        "Uninstall a sticker set.",
        s("short_name", required=True, resolver="stickerset", telegram_name="stickerset"),
    ),
    cmd(
        "stickers.favorite",
        "messages.faveSticker",
        "write",
        "Favorite a sticker.",
        builder="input-required",
    ),
    cmd(
        "stickers.unfavorite",
        "messages.faveSticker",
        "destructive",
        "Remove a favorite sticker.",
        builder="input-required",
    ),
    cmd(
        "stickers.create-set",
        "stickers.createStickerSet",
        "write",
        "Create a sticker set from validated files.",
        s("title", required=True),
        s("short_name", required=True),
        ss("file", required=True, help="Repeat for each Telegram-ready sticker file."),
        ss(
            "emoji",
            required=True,
            help="Provide one emoji for all files or one emoji per file.",
        ),
        b("masks"),
        b("emojis"),
        b("text_color"),
        builder="sticker-create",
    ),
    cmd(
        "stickers.add",
        "stickers.addStickerToSet",
        "write",
        "Add a sticker to an owned set.",
        s("short_name", required=True),
        s("file", required=True, help="Exactly one Telegram-ready sticker file."),
        s("emoji", required=True),
        s("keywords"),
        builder="sticker-item",
    ),
    cmd(
        "stickers.edit",
        "stickers.changeSticker",
        "write",
        "Edit sticker metadata.",
        s("emoji"),
        s("keywords"),
        builder="input-required",
    ),
    cmd(
        "stickers.move",
        "stickers.changeStickerPosition",
        "write",
        "Move a sticker in its set.",
        i("position", required=True),
        builder="input-required",
    ),
    cmd(
        "stickers.replace",
        "stickers.replaceSticker",
        "destructive",
        "Replace a sticker in its set.",
        s("file"),
        s("emoji", required=True),
        s("keywords"),
        builder="input-required",
    ),
    cmd(
        "stickers.remove",
        "stickers.removeStickerFromSet",
        "destructive",
        "Remove a sticker from its set.",
        builder="input-required",
    ),
    cmd(
        "stickers.rename-set",
        "stickers.renameStickerSet",
        "write",
        "Rename an owned sticker set.",
        s("short_name", required=True, resolver="stickerset", telegram_name="stickerset"),
        s("title", required=True),
    ),
    cmd(
        "stickers.set-thumbnail",
        "stickers.setStickerSetThumb",
        "write",
        "Set an owned sticker set thumbnail.",
        s("short_name", required=True, resolver="stickerset", telegram_name="stickerset"),
        builder="input-required",
    ),
    cmd(
        "stickers.delete-set",
        "stickers.deleteStickerSet",
        "critical",
        "Delete an owned sticker set.",
        s("short_name", required=True, resolver="stickerset", telegram_name="stickerset"),
    ),
    cmd(
        "stickers.search-emoji",
        "messages.searchCustomEmoji",
        "read",
        "Search custom emoji.",
        s("emoji", required=True, telegram_name="emoticon"),
        i("hash", default=0),
    ),
    cmd(
        "stickers.available-reactions",
        "messages.getAvailableReactions",
        "read",
        "List available reactions.",
        i("hash", default=0),
    ),
    cmd("gifs.save", "messages.saveGif", "write", "Save a GIF.", builder="input-required"),
    cmd(
        "gifs.unsave",
        "messages.saveGif",
        "destructive",
        "Remove a saved GIF.",
        builder="input-required",
    ),
    cmd(
        "scheduled.get",
        "messages.getScheduledMessages",
        "read",
        "Get selected scheduled messages.",
        PEER,
        ii("message_id", required=True, telegram_name="id"),
    ),
    cmd(
        "scheduled.send-now",
        "messages.sendScheduledMessages",
        "write",
        "Send scheduled messages immediately.",
        PEER,
        ii("message_id", required=True, telegram_name="id"),
    ),
)

FEATURE_BY_COMMAND = {feature.command: feature for feature in FEATURE_COMMANDS}


def _resolved(value: Any, resolver: Resolver | None) -> Any:
    if resolver is None:
        return value
    if resolver == "peer":
        return {"$peer": value}
    if resolver == "channel":
        return {"$channel": value}
    if resolver == "user":
        return {"$user": value}
    if resolver == "peers":
        return [{"$peer": item} for item in value]
    if resolver == "users":
        return [{"$user": item} for item in value]
    if resolver == "bytes":
        return {"$bytes": value}
    if resolver == "datetime":
        return {"$datetime": value}
    if resolver == "reaction":
        return {"_": "ReactionEmoji", "emoticon": value}
    if resolver == "tone":
        return {"_": "InputAiComposeToneSlug", "slug": value}
    if resolver == "chatlist":
        return {"_": "InputChatlistDialogFilter", "filter_id": value}
    if resolver == "stickerset":
        return {"_": "InputStickerSetShortName", "short_name": value}
    return {"_": "TextWithEntities", "text": value, "entities": []}


def _default_params(feature: FeatureCommand, values: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for option in feature.options:
        value = values.get(option.name)
        if value is None or value == []:
            continue
        if (
            option.kind == "bool"
            and value is False
            and option.default is False
            and not option.emit_default
        ):
            continue
        params[option.telegram_name or option.name] = _resolved(value, option.resolver)
    return params


def _recipients(values: dict[str, Any]) -> dict[str, Any]:
    scopes = set(values.get("recipient_scope") or [])
    valid = set(BUSINESS_RECIPIENT_SCOPES)
    if unknown := scopes - valid:
        raise ClitgError(
            ErrorCode.INVALID_INPUT,
            "Unknown Business recipient scope",
            details={"unknown": sorted(unknown), "allowed": sorted(valid)},
        )
    return {
        "_": "InputBusinessRecipients",
        **{scope: True for scope in sorted(scopes)},
        "users": [{"$user": item} for item in values.get("user") or []] or None,
    }


def _todo_items(items: list[Any], *, start: int = 1) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=start):
        if isinstance(item, str):
            item_id, title = index, item
        elif isinstance(item, dict) and isinstance(item.get("title"), str):
            item_id, title = int(item.get("id", index)), item["title"]
        else:
            raise ClitgError(ErrorCode.INVALID_INPUT, "Todo items require a title")
        if item_id <= 0:
            raise ClitgError(ErrorCode.INVALID_INPUT, "Todo item IDs must be positive")
        result.append(
            {
                "_": "TodoItem",
                "id": item_id,
                "title": {"_": "TextWithEntities", "text": title, "entities": []},
            }
        )
    if len({item["id"] for item in result}) != len(result):
        raise ClitgError(ErrorCode.INVALID_INPUT, "Todo item IDs must be unique")
    return result


def _weekly_open(values: list[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in values:
        try:
            day_text, hours = item.split(":", maxsplit=1)
            start_text, end_text = hours.split("-", maxsplit=1)
            start_hour, start_minute = (int(part) for part in start_text.split(":"))
            end_hour, end_minute = (int(part) for part in end_text.split(":"))
            day = int(day_text)
        except (ValueError, TypeError) as exc:
            raise ClitgError(
                ErrorCode.INVALID_INPUT,
                "Business hours must use DAY:HH:MM-HH:MM",
            ) from exc
        if (
            not 0 <= day <= 6
            or not 0 <= start_hour <= 23
            or not 0 <= end_hour <= 24
            or (end_hour == 24 and end_minute != 0)
        ):
            raise ClitgError(ErrorCode.INVALID_INPUT, "Business hours are outside valid ranges")
        start = day * 1440 + start_hour * 60 + start_minute
        end = day * 1440 + end_hour * 60 + end_minute
        if not 0 <= start_minute <= 59 or not 0 <= end_minute <= 59 or end <= start:
            raise ClitgError(ErrorCode.INVALID_INPUT, "Business hour interval is invalid")
        result.append({"_": "BusinessWeeklyOpen", "start_minute": start, "end_minute": end})
    return result


def build_feature_params(
    feature: FeatureCommand,
    values: dict[str, Any],
    structured: dict[str, Any] | list[Any] | None = None,
) -> dict[str, Any]:
    """Build reviewed TL parameters from stable feature inputs."""

    merged = dict(values)
    if isinstance(structured, dict):
        duplicates = set(merged) & set(structured)
        if duplicates:
            raise ClitgError(
                ErrorCode.INVALID_INPUT,
                "Structured input duplicates explicit options",
                details={"fields": sorted(duplicates)},
            )
        merged.update(structured)
    elif structured is not None:
        merged["items"] = structured

    builder = feature.builder
    if builder == "input-required" and structured is None:
        raise ClitgError(ErrorCode.INVALID_INPUT, "This command requires --input or --stdin")
    params = _default_params(feature, merged)
    if feature.cursor_param:
        params.pop("cursor", None)
        params.pop("offset", None)
        cursor = merged.get("cursor")
        if cursor in {None, ""}:
            cursor = "" if feature.cursor_param == "offset" and feature.options.count(OFFSET) else 0
        params[feature.cursor_param] = cursor
    if builder == "input-required" and isinstance(structured, dict):
        params.update(structured)
    if builder == "default" or builder == "input-required":
        return params
    if builder == "translate":
        text = merged.get("text")
        if bool(text) == bool(merged.get("message_id")):
            raise ClitgError(
                ErrorCode.INVALID_INPUT,
                "Provide either text or peer with message IDs",
            )
        if text:
            params["text"] = [{"_": "TextWithEntities", "text": text, "entities": []}]
            params.pop("peer", None)
        elif "peer" not in params:
            raise ClitgError(ErrorCode.INVALID_INPUT, "A peer is required for message translation")
        return params
    if builder == "compose":
        if not any(
            merged.get(name) for name in ("proofread", "emojify", "translate_to_lang", "tone")
        ):
            raise ClitgError(ErrorCode.INVALID_INPUT, "Select at least one AI composition mode")
        return params
    if builder == "transcribe":
        params.pop("wait_seconds", None)
        return params
    if builder == "unread-feed":
        return {
            **params,
            "offset_id": params.get("offset_id", 0),
            "add_offset": 0,
            "max_id": 0,
            "min_id": 0,
        }
    if builder == "todo-create":
        return {
            "peer": params["peer"],
            "media": {
                "_": "InputMediaTodo",
                "todo": {
                    "_": "TodoList",
                    "title": {"_": "TextWithEntities", "text": merged["title"], "entities": []},
                    "list": _todo_items(merged["item"]),
                    "others_can_append": bool(merged.get("others_can_append")),
                    "others_can_complete": bool(merged.get("others_can_complete")),
                },
            },
            "message": "",
        }
    if builder == "todo-append":
        params.pop("item", None)
        params["list"] = _todo_items(merged["item"])
        return params
    if builder == "todo-complete":
        params["incompleted"] = []
        return params
    if builder == "todo-reopen":
        params["completed"] = []
        return params
    if builder in {"quick-create", "quick-add"}:
        shortcut: dict[str, Any]
        if builder == "quick-create":
            shortcut = {"_": "InputQuickReplyShortcut", "shortcut": merged["name"]}
        else:
            shortcut = {"_": "InputQuickReplyShortcutId", "shortcut_id": merged["shortcut_id"]}
        return {
            "peer": {"_": "InputPeerSelf"},
            "message": merged["text"],
            "quick_reply_shortcut": shortcut,
        }
    if builder == "self-user":
        return {"id": {"_": "InputUserSelf"}}
    if builder == "business-link":
        result = {
            "link": {
                "_": "InputBusinessChatLink",
                "message": merged["message"],
                "entities": [],
                "title": merged.get("title"),
            }
        }
        if merged.get("slug"):
            result["slug"] = merged["slug"]
        return result
    if builder == "business-greeting":
        return {
            "message": {
                "_": "InputBusinessGreetingMessage",
                "shortcut_id": merged["shortcut_id"],
                "recipients": _recipients(merged),
                "no_activity_days": merged["no_activity_days"],
            }
        }
    if builder == "business-away":
        schedule = merged.get("schedule", "always")
        schedules: dict[str, dict[str, Any]] = {
            "always": {"_": "BusinessAwayMessageScheduleAlways"},
            "outside-hours": {"_": "BusinessAwayMessageScheduleOutsideWorkHours"},
            "custom": {
                "_": "BusinessAwayMessageScheduleCustom",
                "start_date": _resolved(merged.get("start_at"), "datetime"),
                "end_date": _resolved(merged.get("end_at"), "datetime"),
            },
        }
        if schedule not in schedules:
            raise ClitgError(ErrorCode.INVALID_INPUT, "Unknown Business away schedule")
        if schedule == "custom" and not all(merged.get(name) for name in ("start_at", "end_at")):
            raise ClitgError(ErrorCode.INVALID_INPUT, "Custom away schedules require dates")
        return {
            "message": {
                "_": "InputBusinessAwayMessage",
                "shortcut_id": merged["shortcut_id"],
                "schedule": schedules[schedule],
                "recipients": _recipients(merged),
                "offline_only": bool(merged.get("offline_only")),
            }
        }
    if builder == "business-hours":
        return {
            "business_work_hours": {
                "_": "BusinessWorkHours",
                "timezone_id": merged["timezone"],
                "weekly_open": _weekly_open(merged["open"]),
            }
        }
    if builder == "business-location":
        return {
            "geo_point": {
                "_": "InputGeoPoint",
                "lat": merged["latitude"],
                "long": merged["longitude"],
                "accuracy_radius": merged.get("accuracy_radius"),
            },
            "address": merged["address"],
        }
    if builder == "business-intro":
        return {
            "intro": {
                "_": "InputBusinessIntro",
                "title": merged["title"],
                "description": merged["description"],
            }
        }
    if builder == "business-bot":
        rights = set(merged.get("right") or [])
        if unknown := rights - BUSINESS_BOT_RIGHTS:
            raise ClitgError(
                ErrorCode.INVALID_INPUT,
                "Unknown Business bot right",
                details={"unknown": sorted(unknown), "allowed": sorted(BUSINESS_BOT_RIGHTS)},
            )
        return {
            "bot": params["bot"],
            "recipients": {
                "_": "InputBusinessBotRecipients",
                **{key: value for key, value in _recipients(merged).items() if key != "_"},
            },
            "rights": {"_": "BusinessBotRights", **{right: True for right in sorted(rights)}},
        }
    if builder == "views":
        params["increment"] = False
        return params
    if builder == "message-ids":
        return {"id": [{"_": "InputMessageID", "id": item} for item in merged["message_id"]]}
    if builder == "chatlist":
        params["chatlist"] = {"_": "InputChatlistDialogFilter", "filter_id": merged["folder_id"]}
        params.pop("folder_id", None)
        return params
    if builder == "message-filter":
        params["filter"] = {"_": str(merged["filter"])}
        params.setdefault("offset_date", None)
        return params
    if builder == "message-filters":
        params["filters"] = [{"_": str(item)} for item in merged["filter"]]
        params.pop("filter", None)
        return params
    if builder == "group-call":
        return {
            "call": {
                "_": "InputGroupCall",
                "id": merged["call_id"],
                "access_hash": merged["access_hash"],
            }
        }
    if builder == "upload-photo":
        return {"file": {"$upload": merged["file"]}}
    if builder == "birthday":
        return {
            "birthday": {
                "_": "Birthday",
                "day": merged["day"],
                "month": merged["month"],
                "year": merged.get("year"),
            }
        }
    if builder == "peer-color":
        return {
            "for_profile": bool(merged.get("for_profile")),
            "color": {
                "_": "PeerColor",
                "color": merged.get("color"),
                "background_emoji_id": merged.get("background_emoji_id"),
            },
        }
    if builder == "emoji-status":
        return {
            "emoji_status": {
                "_": "EmojiStatus",
                "document_id": merged["document_id"],
                "until": _resolved(merged.get("until"), "datetime")
                if merged.get("until")
                else None,
            }
        }
    if builder == "emoji-status-empty":
        return {"emoji_status": {"_": "EmojiStatusEmpty"}}
    if builder == "empty-channel":
        return {"channel": {"_": "InputChannelEmpty"}}
    if builder == "contacts-import":
        items = merged.get("items")
        if items is None:
            if not merged.get("phone") or not merged.get("first_name"):
                raise ClitgError(ErrorCode.INVALID_INPUT, "A phone and first name are required")
            items = [
                {
                    "phone": merged["phone"],
                    "first_name": merged["first_name"],
                    "last_name": merged.get("last_name") or "",
                }
            ]
        return {
            "contacts": [
                {
                    "_": "InputPhoneContact",
                    "client_id": index,
                    "phone": item["phone"],
                    "first_name": item["first_name"],
                    "last_name": item.get("last_name", ""),
                }
                for index, item in enumerate(items, start=1)
            ]
        }
    if builder == "empty-note":
        return {
            "id": params["id"],
            "note": {"_": "TextWithEntities", "text": "", "entities": []},
        }
    if builder in {"sticker-create", "sticker-item"}:
        return {**params, "_feature_files": merged.get("file") or [], "_feature_input": structured}
    raise ClitgError(ErrorCode.INTERNAL, f"Unknown feature builder '{builder}'")


def feature_catalog() -> dict[str, dict[str, Any]]:
    """Return machine-readable metadata for every stable feature command."""

    return {
        feature.command: {
            "method": feature.method,
            "risk": feature.risk,
            "mutation": feature.mutation,
            "summary": feature.summary,
            "requirements": list(feature.requirements),
            "quota_consuming": feature.quota_consuming,
            "paginated": feature.paginated,
            "cursor_param": feature.cursor_param,
            "result_schema": feature.result_model,
            "parameters": [
                {
                    "name": option.name,
                    "flag": option.flag,
                    "type": option.kind,
                    "required": option.required,
                    "default": option.default,
                    "help": option.help,
                    "allowed_values": list(option.choices),
                }
                for option in feature.options
            ],
        }
        for feature in FEATURE_COMMANDS
    }


def normalize_feature_result(value: Any) -> tuple[str, Any]:
    """Normalize a generated result behind a stable type and value pair."""

    if isinstance(value, dict):
        result_type = str(value.get("_") or "object")
        return result_type, {
            str(key): normalize_feature_result(item)[1] for key, item in value.items() if key != "_"
        }
    if isinstance(value, list):
        return "list", [normalize_feature_result(item)[1] for item in value]
    return type(value).__name__, value
