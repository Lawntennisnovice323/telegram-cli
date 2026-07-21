from __future__ import annotations

import os
import uuid

import pytest
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession


@pytest.mark.telegram_test_dc
@pytest.mark.asyncio
async def test_test_dc_saved_messages_lifecycle() -> None:
    """Exercise a disposable message lifecycle against Telegram Test DC."""

    required = ("CLITG_TEST_API_ID", "CLITG_TEST_API_HASH", "CLITG_TEST_PHONE")
    if any(not os.getenv(name) for name in required):
        pytest.skip("Telegram Test DC credentials are not configured")
    client = TelegramClient(
        StringSession(),
        int(os.environ["CLITG_TEST_API_ID"]),
        os.environ["CLITG_TEST_API_HASH"],
    )
    session = client.session
    assert session is not None
    session.set_dc(
        int(os.getenv("CLITG_TEST_DC_ID", "2")),
        os.getenv("CLITG_TEST_DC_ADDRESS", "149.154.167.40"),
        int(os.getenv("CLITG_TEST_DC_PORT", "80")),
    )
    sent = None
    try:
        await client.connect()
        if not await client.is_user_authorized():
            phone = os.environ["CLITG_TEST_PHONE"]
            code = os.getenv("CLITG_TEST_CODE", "22222")
            requested = await client.send_code_request(phone)
            try:
                await client.sign_in(
                    phone=phone,
                    code=code,
                    phone_code_hash=requested.phone_code_hash,
                )
            except SessionPasswordNeededError:
                password = os.getenv("CLITG_TEST_PASSWORD")
                if not password:
                    pytest.fail("CLITG_TEST_PASSWORD is required by the Test DC account")
                await client.sign_in(password=password)
        marker = f"clitg-test-dc-{uuid.uuid4()}"
        sent = await client.send_message("me", marker)
        edited = await client.edit_message("me", sent.id, f"{marker}-edited")
        assert edited.message.endswith("-edited")
    finally:
        if sent is not None:
            await client.delete_messages("me", [sent.id], revoke=True)
        await client.disconnect()
