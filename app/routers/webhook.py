"""
LINE Webhook router — the single entry point for all LINE events.

State transitions:
  WAITING_INPUT      →  text "品項 金額"  →  WAITING_SPLIT_MODE
  WAITING_SPLIT_MODE →  postback AA       →  WAITING_INPUT  (save expense)
  WAITING_SPLIT_MODE →  postback custom   →  WAITING_CUSTOM_SPLIT
  WAITING_CUSTOM_SPLIT → text "我 200"   →  WAITING_INPUT  (save expense)
"""
import re
import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import (
    MessageEvent,
    PostbackEvent,
    TextMessageContent,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user_state import StateEnum
from app.services.line_service import LineBotService, parser
from app.services.state_machine import StateMachineService
from app.services.expense_service import ExpenseService, parse_expense_input, parse_custom_split
from app.services.settlement import SettlementService

router = APIRouter()
log = logging.getLogger(__name__)

# Keywords that trigger the main menu
MENU_KEYWORDS = {"選單", "menu", "Menu", "幫助", "help", "Help"}
# Keywords that trigger invite-code generation
PAIR_TRIGGER = re.compile(r"^配對$", re.IGNORECASE)
# Keywords that trigger pairing with a code
PAIR_CODE = re.compile(r"^配對\s+([A-Z0-9]{6})$", re.IGNORECASE)


# ──────────────────────────────────────────────────────────────────────────────
#  Webhook endpoint
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/webhook")
async def webhook(
    request: Request,
    x_line_signature: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    body = await request.body()
    try:
        events = parser.parse(body.decode("utf-8"), x_line_signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    for event in events:
        try:
            if isinstance(event, MessageEvent) and isinstance(
                event.message, TextMessageContent
            ):
                await _handle_text(event, db)
            elif isinstance(event, PostbackEvent):
                await _handle_postback(event, db)
        except Exception as exc:
            log.exception("Error handling event: %s", exc)

    await db.commit()
    return {"status": "ok"}


# ──────────────────────────────────────────────────────────────────────────────
#  Text message handler
# ──────────────────────────────────────────────────────────────────────────────

async def _handle_text(event: MessageEvent, db: AsyncSession):
    line_user_id = event.source.user_id
    text = event.message.text.strip()
    reply_token = event.reply_token

    # Resolve display name & ensure user exists
    display_name = await LineBotService.get_display_name(line_user_id)
    user = await ExpenseService.get_or_create_user(db, line_user_id, display_name)
    user_state = await StateMachineService.get_state(db, line_user_id)

    # ── State: WAITING_CUSTOM_SPLIT ─────────────────────────────────────────
    if user_state.state == StateEnum.WAITING_CUSTOM_SPLIT:
        await _handle_custom_split_input(event, db, user, user_state, text)
        return

    # ── State: WAITING_SPLIT_MODE — user typed instead of tapping button ───
    if user_state.state == StateEnum.WAITING_SPLIT_MODE:
        await LineBotService.reply_text(reply_token, "請點選上方按鈕選擇分帳方式 👆")
        return

    # ── Menu keywords ───────────────────────────────────────────────────────
    if text in MENU_KEYWORDS:
        await LineBotService.reply_main_menu(reply_token)
        return

    # ── Pairing: "配對" (generate code) ────────────────────────────────────
    if PAIR_TRIGGER.match(text):
        await _handle_generate_invite(event, db, user)
        return

    # ── Pairing: "配對 XXXXXX" (use code) ──────────────────────────────────
    m = PAIR_CODE.match(text)
    if m:
        await _handle_use_invite(event, db, user, m.group(1))
        return

    # ── Expense input: "品項 金額" ──────────────────────────────────────────
    parsed = parse_expense_input(text)
    if parsed:
        description, amount = parsed
        if not user.partner_id:
            await LineBotService.reply_text(
                reply_token,
                "⚠️ 你還沒有配對夥伴！\n\n請輸入「配對」來產生邀請碼。",
            )
            return
        # Save pending and transition
        await StateMachineService.transition(
            db,
            line_user_id,
            StateEnum.WAITING_SPLIT_MODE,
            {"description": description, "amount": str(amount)},
        )
        await LineBotService.reply_split_prompt(reply_token, description, float(amount))
        return

    # ── Fallback: show menu ─────────────────────────────────────────────────
    await LineBotService.reply_main_menu(reply_token)


# ──────────────────────────────────────────────────────────────────────────────
#  Postback handler
# ──────────────────────────────────────────────────────────────────────────────

async def _handle_postback(event: PostbackEvent, db: AsyncSession):
    line_user_id = event.source.user_id
    data = event.postback.data  # e.g. "action=split_aa"
    reply_token = event.reply_token

    params = dict(kv.split("=", 1) for kv in data.split("&") if "=" in kv)
    action = params.get("action", "")

    display_name = await LineBotService.get_display_name(line_user_id)
    user = await ExpenseService.get_or_create_user(db, line_user_id, display_name)
    user_state = await StateMachineService.get_state(db, line_user_id)

    if action == "split_aa":
        await _handle_split_aa(event, db, user, user_state)
    elif action == "split_custom":
        await _handle_split_custom_init(event, db, user, user_state)
    elif action == "query":
        await _handle_query(event, db, user)
    elif action == "history":
        await _handle_history(event, db, user)
    elif action == "clear":
        await LineBotService.reply_clear_confirm(reply_token)
    elif action == "clear_confirm":
        await _handle_clear(event, db, user)
    elif action == "clear_cancel":
        await LineBotService.reply_text(reply_token, "已取消清帳。")
    else:
        await LineBotService.reply_main_menu(reply_token)


# ──────────────────────────────────────────────────────────────────────────────
#  Action handlers
# ──────────────────────────────────────────────────────────────────────────────

async def _handle_split_aa(event, db, user, user_state):
    reply_token = event.reply_token
    if user_state.state != StateEnum.WAITING_SPLIT_MODE or not user_state.pending_data:
        await LineBotService.reply_text(reply_token, "⚠️ 請先輸入品項和金額。")
        return

    partner = await ExpenseService.get_partner(db, user)
    if not partner:
        await LineBotService.reply_text(reply_token, "⚠️ 找不到配對夥伴，請重新配對。")
        return

    description = user_state.pending_data["description"]
    amount = Decimal(user_state.pending_data["amount"])

    expense = await ExpenseService.add_expense_aa(db, user, partner, description, amount)
    await StateMachineService.reset(db, user.line_user_id)

    msg = SettlementService.format_expense_result(
        description, amount,
        expense.payer_share, expense.partner_share,
        "你", partner.display_name,
    )
    await LineBotService.reply_text(reply_token, msg)


async def _handle_split_custom_init(event, db, user, user_state):
    reply_token = event.reply_token
    if user_state.state != StateEnum.WAITING_SPLIT_MODE or not user_state.pending_data:
        await LineBotService.reply_text(reply_token, "⚠️ 請先輸入品項和金額。")
        return

    amount = Decimal(user_state.pending_data["amount"])
    await StateMachineService.transition(
        db, user.line_user_id, StateEnum.WAITING_CUSTOM_SPLIT, user_state.pending_data
    )
    await LineBotService.reply_custom_split_prompt(reply_token, float(amount))


async def _handle_custom_split_input(event, db, user, user_state, text):
    reply_token = event.reply_token
    if not user_state.pending_data:
        await StateMachineService.reset(db, user.line_user_id)
        await LineBotService.reply_text(reply_token, "⚠️ 資料遺失，請重新輸入品項和金額。")
        return

    description = user_state.pending_data["description"]
    amount = Decimal(user_state.pending_data["amount"])

    result = parse_custom_split(text, amount)
    if result is None:
        await LineBotService.reply_text(
            reply_token,
            f"❌ 格式錯誤或金額不符（總額 NT$ {float(amount):,.0f}）\n\n"
            "請重新輸入，例如：\n  我 200\n  我 200 對方 120",
        )
        return

    payer_share, partner_share = result
    partner = await ExpenseService.get_partner(db, user)
    if not partner:
        await LineBotService.reply_text(reply_token, "⚠️ 找不到配對夥伴，請重新配對。")
        return

    expense = await ExpenseService.add_expense_custom(
        db, user, partner, description, amount, payer_share, partner_share
    )
    await StateMachineService.reset(db, user.line_user_id)

    msg = SettlementService.format_expense_result(
        description, amount,
        expense.payer_share, expense.partner_share,
        "你", partner.display_name,
    )
    await LineBotService.reply_text(reply_token, msg)


async def _handle_query(event, db, user):
    reply_token = event.reply_token
    partner = await ExpenseService.get_partner(db, user)
    if not partner:
        await LineBotService.reply_text(reply_token, "⚠️ 你還沒有配對夥伴，請先輸入「配對」。")
        return
    _, msg = await SettlementService.calculate(db, user, partner)
    await LineBotService.reply_text(reply_token, msg)


async def _handle_history(event, db, user):
    reply_token = event.reply_token
    expenses = await ExpenseService.get_history(db, user)
    msg = SettlementService.format_history(expenses, user.id)
    await LineBotService.reply_text(reply_token, msg)


async def _handle_clear(event, db, user):
    reply_token = event.reply_token
    count = await ExpenseService.settle_all(db, user)
    await LineBotService.reply_text(
        reply_token,
        f"✅ 已清帳！共結清 {count} 筆記錄。\n帳務歸零，重新開始 🎉",
    )


async def _handle_generate_invite(event, db, user):
    reply_token = event.reply_token
    if user.partner_id:
        await LineBotService.reply_text(reply_token, "⚠️ 你已經有配對夥伴了！")
        return
    code = await ExpenseService.generate_invite_code(db, user)
    await LineBotService.reply_text(
        reply_token,
        f"🔗 你的邀請碼：{code}\n\n"
        f"有效期限：24 小時\n\n"
        f"請對方輸入：配對 {code}",
    )


async def _handle_use_invite(event, db, user, code):
    reply_token = event.reply_token
    success, msg = await ExpenseService.pair_with_code(db, user, code)
    await LineBotService.reply_text(reply_token, msg)
