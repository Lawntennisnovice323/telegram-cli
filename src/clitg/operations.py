"""Dedicated command registry backed by Telegram's generated MTProto layer."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Literal

Risk = Literal["read", "write", "destructive", "critical"]


@dataclass(frozen=True)
class Operation:
    """One stable high-level command mapped to a generated request."""

    command: str
    method: str
    risk: Risk
    summary: str

    @property
    def mutation(self) -> bool:
        return self.risk != "read"

    @property
    def critical(self) -> bool:
        return self.risk == "critical"


def _op(command: str, method: str, risk: Risk, summary: str) -> Operation:
    return Operation(command, method, risk, summary)


OPERATIONS = (
    _op("account.get", "users.getFullUser", "read", "Inspect the current account profile."),
    _op("account.privacy", "account.getPrivacy", "read", "Inspect one privacy rule category."),
    _op("auth.sessions", "account.getAuthorizations", "read", "List active authorizations."),
    _op("bots.click", "messages.getBotCallbackAnswer", "write", "Activate a bot callback button."),
    _op("bots.inline", "messages.getInlineBotResults", "read", "Query an inline bot."),
    _op("bots.start", "messages.startBot", "write", "Start a bot with an optional parameter."),
    _op("chats.admin-log", "channels.getAdminLog", "read", "List channel administration events."),
    _op(
        "chats.create-channel", "channels.createChannel", "write", "Create a channel or megagroup."
    ),
    _op("chats.create-group", "messages.createChat", "write", "Create a basic group."),
    _op(
        "chats.delete-channel",
        "channels.deleteChannel",
        "critical",
        "Delete a channel or megagroup.",
    ),
    _op("chats.delete-group", "messages.deleteChat", "critical", "Delete a basic group."),
    _op("chats.edit-channel", "channels.editTitle", "write", "Edit a channel title."),
    _op("chats.edit-channel-photo", "channels.editPhoto", "write", "Edit a channel photo."),
    _op("chats.edit-group", "messages.editChatTitle", "write", "Edit a basic group title."),
    _op("chats.edit-group-photo", "messages.editChatPhoto", "write", "Edit a group photo."),
    _op("chats.edit-about", "messages.editChatAbout", "write", "Edit a chat description."),
    _op("chats.update-username", "channels.updateUsername", "write", "Update a public username."),
    _op("chats.invite-channel", "channels.inviteToChannel", "write", "Invite one channel member."),
    _op("chats.invite-group", "messages.addChatUser", "write", "Invite one basic-group member."),
    _op("chats.join", "channels.joinChannel", "write", "Join a public channel."),
    _op("chats.join-invite", "messages.importChatInvite", "write", "Join using an invite hash."),
    _op("chats.leave-channel", "channels.leaveChannel", "destructive", "Leave a channel."),
    _op("chats.leave-group", "messages.deleteChatUser", "destructive", "Leave a basic group."),
    _op("chats.participants", "channels.getParticipants", "read", "List channel participants."),
    _op(
        "chats.promote-channel",
        "channels.editAdmin",
        "critical",
        "Change channel administrator rights.",
    ),
    _op(
        "chats.promote-group",
        "messages.editChatAdmin",
        "critical",
        "Change basic-group administrator rights.",
    ),
    _op(
        "chats.remove-channel-member",
        "channels.editBanned",
        "destructive",
        "Remove a channel member.",
    ),
    _op(
        "chats.remove-group-member",
        "messages.deleteChatUser",
        "destructive",
        "Remove a group member.",
    ),
    _op("chats.restrict", "channels.editBanned", "critical", "Change participant restrictions."),
    _op("contacts.add", "contacts.addContact", "write", "Add or update one Telegram contact."),
    _op("contacts.block", "contacts.block", "destructive", "Block one peer."),
    _op("contacts.blocked", "contacts.getBlocked", "read", "List blocked peers."),
    _op("contacts.delete", "contacts.deleteContacts", "destructive", "Delete one contact."),
    _op("contacts.unblock", "contacts.unblock", "write", "Unblock one peer."),
    _op("dialogs.archive", "folders.editPeerFolders", "write", "Move a dialog to Archive."),
    _op("dialogs.mark-unread", "messages.markDialogUnread", "write", "Mark a dialog unread."),
    _op("dialogs.mute", "account.updateNotifySettings", "write", "Mute dialog notifications."),
    _op("dialogs.pin-dialog", "messages.toggleDialogPin", "write", "Pin a dialog."),
    _op("dialogs.unarchive", "folders.editPeerFolders", "write", "Move a dialog out of Archive."),
    _op("dialogs.unmute", "account.updateNotifySettings", "write", "Restore dialog notifications."),
    _op("dialogs.unpin-dialog", "messages.toggleDialogPin", "write", "Unpin a dialog."),
    _op("drafts.list", "messages.getAllDrafts", "read", "List all cloud drafts."),
    _op("drafts.set", "messages.saveDraft", "write", "Create or update a cloud draft."),
    _op("drafts.delete", "messages.saveDraft", "destructive", "Delete a cloud draft."),
    _op("folders.list", "messages.getDialogFilters", "read", "List Telegram chat folders."),
    _op("folders.create", "messages.updateDialogFilter", "write", "Create a chat folder."),
    _op("folders.edit", "messages.updateDialogFilter", "write", "Edit a chat folder."),
    _op("folders.reorder", "messages.updateDialogFiltersOrder", "write", "Reorder chat folders."),
    _op("folders.delete", "messages.updateDialogFilter", "destructive", "Delete a chat folder."),
    _op("gifs.recent", "messages.getSavedGifs", "read", "List saved GIFs."),
    _op("gifs.search", "messages.search", "read", "Search GIF messages."),
    _op("gifs.send", "messages.sendMedia", "write", "Send a GIF."),
    _op("invite-links.create", "messages.exportChatInvite", "write", "Create an invite link."),
    _op("invite-links.list", "messages.getExportedChatInvites", "read", "List invite links."),
    _op("invite-links.edit", "messages.editExportedChatInvite", "write", "Edit an invite link."),
    _op(
        "invite-links.revoke",
        "messages.deleteExportedChatInvite",
        "destructive",
        "Revoke an invite link.",
    ),
    _op(
        "join-requests.list",
        "messages.getChatInviteImporters",
        "read",
        "List pending join requests.",
    ),
    _op(
        "join-requests.approve",
        "messages.hideChatJoinRequest",
        "write",
        "Approve one join request.",
    ),
    _op(
        "join-requests.reject",
        "messages.hideChatJoinRequest",
        "destructive",
        "Reject one join request.",
    ),
    _op(
        "messages.reactions", "messages.getMessageReactionsList", "read", "List message reactions."
    ),
    _op("messages.send-contact", "messages.sendMedia", "write", "Send a contact card."),
    _op("messages.send-location", "messages.sendMedia", "write", "Send a location."),
    _op("messages.send-venue", "messages.sendMedia", "write", "Send a venue."),
    _op("messages.stop-live-location", "messages.editMessage", "write", "Stop a live location."),
    _op(
        "messages.update-live-location", "messages.editMessage", "write", "Update a live location."
    ),
    _op("polls.results", "messages.getPollResults", "read", "Get poll results."),
    _op("polls.voters", "messages.getPollVotes", "read", "List poll voters."),
    _op("saved.dialogs", "messages.getSavedDialogs", "read", "List Saved Messages conversations."),
    _op("saved.list", "messages.getHistory", "read", "List Saved Messages."),
    _op("saved.search", "messages.search", "read", "Search Saved Messages."),
    _op("saved.tags", "messages.getSavedReactionTags", "read", "List Saved Messages tags."),
    _op("saved.tag", "messages.updateSavedReactionTag", "write", "Add or rename a saved tag."),
    _op("saved.untag", "messages.updateSavedReactionTag", "destructive", "Remove a saved tag."),
    _op("scheduled.edit", "messages.editMessage", "write", "Edit a scheduled message."),
    _op("stickers.favorites", "messages.getFavedStickers", "read", "List favorite stickers."),
    _op("stickers.recent", "messages.getRecentStickers", "read", "List recent stickers."),
    _op("stickers.search", "messages.searchStickers", "read", "Search available stickers."),
    _op("stickers.send", "messages.sendMedia", "write", "Send a sticker."),
    _op("stories.delete", "stories.deleteStories", "destructive", "Delete stories."),
    _op("stories.edit", "stories.editStory", "write", "Edit a story."),
    _op("stories.list", "stories.getAllStories", "read", "List available stories."),
    _op("stories.get", "stories.getStoriesByID", "read", "Get selected stories."),
    _op("stories.publish", "stories.sendStory", "write", "Publish a story."),
    _op("topics.close", "messages.editForumTopic", "write", "Close a forum topic."),
    _op("topics.create", "messages.createForumTopic", "write", "Create a forum topic."),
    _op(
        "topics.delete", "messages.deleteTopicHistory", "critical", "Delete a forum topic history."
    ),
    _op("topics.edit", "messages.editForumTopic", "write", "Edit a forum topic."),
    _op("topics.pin", "messages.updatePinnedMessage", "write", "Pin a forum topic message."),
    _op("topics.reopen", "messages.editForumTopic", "write", "Reopen a forum topic."),
)

OPERATION_BY_COMMAND = {operation.command: operation for operation in OPERATIONS}


def operation_catalog() -> dict[str, dict[str, Any]]:
    """Describe all dedicated generated operations for agents."""

    from clitg.catalog import request_registry

    registry = request_registry()
    result: dict[str, dict[str, Any]] = {}
    for operation in OPERATIONS:
        request_class = registry[operation.method]
        result[operation.command] = {
            "method": operation.method,
            "risk": operation.risk,
            "mutation": operation.mutation,
            "summary": operation.summary,
            "parameters": str(inspect.signature(request_class)),
        }
    return result


def normalize_params(value: Any, field: str | None = None) -> Any:
    """Translate friendly peer references into RawCodec special values."""

    if isinstance(value, dict):
        return {key: normalize_params(item, key) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_params(item, field) for item in value]
    if not isinstance(value, str):
        return value
    if field in {"peer", "to_peer", "from_peer"}:
        return {"$peer": value}
    if field in {"channel"}:
        return {"$channel": value}
    if field in {"user", "user_id", "bot", "bot_id"}:
        return {"$user": value}
    if field in {"users"}:
        return {"$user": value}
    return value
