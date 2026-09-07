from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.user_state import StateEnum
from app.routers import webhook


def _text_event(text: str):
    return SimpleNamespace(
        source=SimpleNamespace(user_id="U-test"),
        message=SimpleNamespace(text=text),
        reply_token="reply-token",
    )


def _patch_text_dependencies(monkeypatch, state):
    user = SimpleNamespace(line_user_id="U-test", partner_id="partner")
    monkeypatch.setattr(
        webhook.LineBotService,
        "get_display_name",
        AsyncMock(return_value="測試"),
    )
    monkeypatch.setattr(
        webhook.ExpenseService,
        "get_or_create_user",
        AsyncMock(return_value=user),
    )
    monkeypatch.setattr(
        webhook.StateMachineService,
        "get_state",
        AsyncMock(return_value=state),
    )
    return user


@pytest.mark.asyncio
async def test_missing_payer_buttons_are_replied_again(monkeypatch):
    state = SimpleNamespace(
        state=StateEnum.WAITING_PAYER,
        pending_data={"description": "牛排", "amount": "890"},
    )
    _patch_text_dependencies(monkeypatch, state)
    reply_payer_prompt = AsyncMock()
    reply_text = AsyncMock()
    monkeypatch.setattr(
        webhook.LineBotService, "reply_payer_prompt", reply_payer_prompt
    )
    monkeypatch.setattr(webhook.LineBotService, "reply_text", reply_text)

    await webhook._handle_text(_text_event("按鈕不見了"), object())

    reply_payer_prompt.assert_awaited_once_with("reply-token", "牛排", 890.0)
    reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_split_buttons_are_replied_again(monkeypatch):
    state = SimpleNamespace(
        state=StateEnum.WAITING_SPLIT_MODE,
        pending_data={
            "description": "牛排",
            "amount": "890",
            "payer_type": "me",
        },
    )
    _patch_text_dependencies(monkeypatch, state)
    reply_split_prompt = AsyncMock()
    reply_text = AsyncMock()
    monkeypatch.setattr(
        webhook.LineBotService, "reply_split_prompt", reply_split_prompt
    )
    monkeypatch.setattr(webhook.LineBotService, "reply_text", reply_text)

    await webhook._handle_text(_text_event("按鈕不見了"), object())

    reply_split_prompt.assert_awaited_once_with("reply-token", "牛排", 890.0)
    reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_resets_a_stuck_flow_and_shows_menu(monkeypatch):
    state = SimpleNamespace(
        state=StateEnum.WAITING_PAYER,
        pending_data={"description": "牛排", "amount": "890"},
    )
    user = _patch_text_dependencies(monkeypatch, state)
    reset = AsyncMock()
    reply_main_menu = AsyncMock()
    reply_text = AsyncMock()
    monkeypatch.setattr(webhook.StateMachineService, "reset", reset)
    monkeypatch.setattr(webhook.LineBotService, "reply_main_menu", reply_main_menu)
    monkeypatch.setattr(webhook.LineBotService, "reply_text", reply_text)

    db = object()

    await webhook._handle_text(_text_event("取消"), db)

    reset.assert_awaited_once_with(db, user.line_user_id)
    reply_main_menu.assert_awaited_once_with("reply-token")
    reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_payer_prompt_does_not_persist_waiting_state(monkeypatch):
    state = SimpleNamespace(state=StateEnum.WAITING_INPUT, pending_data=None)
    _patch_text_dependencies(monkeypatch, state)
    transition = AsyncMock()
    monkeypatch.setattr(webhook.StateMachineService, "transition", transition)
    monkeypatch.setattr(
        webhook.LineBotService,
        "reply_payer_prompt",
        AsyncMock(side_effect=RuntimeError("LINE reply failed")),
    )

    with pytest.raises(RuntimeError, match="LINE reply failed"):
        await webhook._handle_text(_text_event("牛排 890"), object())

    transition.assert_not_awaited()
