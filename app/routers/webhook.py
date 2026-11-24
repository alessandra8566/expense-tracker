"""
LINE Webhook router — the single entry point for all LINE events.

State transitions:
  WAITING_INPUT      →  text "品項 金額"  →  WAITING_PAYER
  WAITING_PAYER      →  postback Me/Partner →  WAITING_SPLIT_MODE
  WAITING_SPLIT_MODE →  postback AA       →  WAITING_INPUT  (save expense)
  WAITING_SPLIT_MODE →  postback custom   →  WAITING_CUSTOM_SPLIT
  WAITING_CUSTOM_SPLIT → text "我 200"   →  WAITING_INPUT  (save expense)
"""
import re
import logging
from decimal import Decimal
from uuid import UUID

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
# Keywords for direct commands
QUERY_KEYWORDS = {"查詢", "查詢結算", "結算", "query"}
HISTORY_KEYWORDS = {"歷史", "歷史紀錄", "紀錄", "history"}
CLEAR_KEYWORDS = {"清帳", "清除", "clear"}
DELETE_ITEMS_KEYWORD = "刪除品項"
# Keywords that cancel an unfinished expense flow
CANCEL_KEYWORDS = {"取消", "重來", "重新開始", "cancel", "reset"}

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

    # Always provide an escape hatch, even if the quick reply disappeared.
    if text in CANCEL_KEYWORDS:
        await StateMachineService.reset(db, line_user_id)
        await LineBotService.reply_main_menu(reply_token)
        return

    if text == DELETE_ITEMS_KEYWORD:
        await StateMachineService.reset(db, line_user_id)
        await _handle_delete_items(reply_token, db, user)
        return

    # ── State: WAITING_CUSTOM_SPLIT ─────────────────────────────────────────
    if user_state.state == StateEnum.WAITING_CUSTOM_SPLIT:
        await _handle_custom_split_input(event, db, user, user_state, text)
        return

    # ── State: WAITING_PAYER / WAITING_SPLIT_MODE ─────────────────────────
    # Quick replies are temporary in the LINE client. Re-send the relevant
    # prompt when the user sends a message after the buttons have disappeared.
    if user_state.state == StateEnum.WAITING_PAYER and user_state.pending_data:
        await LineBotService.reply_payer_prompt(
            reply_token,
            user_state.pending_data["description"],
            float(user_state.pending_data["amount"]),
        )
        return
    if user_state.state == StateEnum.WAITING_SPLIT_MODE and user_state.pending_data:
        await LineBotService.reply_split_prompt(
            reply_token,
            user_state.pending_data["description"],
            float(user_state.pending_data["amount"]),
        )
        return

    # ── Menu keywords ───────────────────────────────────────────────────────
    if text in MENU_KEYWORDS:
        await LineBotService.reply_main_menu(reply_token)
        return

    # ── Direct commands ─────────────────────────────────────────────────────
    if text in QUERY_KEYWORDS:
        await _handle_query(event, db, user)
        return
    if text in HISTORY_KEYWORDS:
        await _handle_history(event, db, user)
        return
    if text in CLEAR_KEYWORDS:
        await LineBotService.reply_clear_confirm(reply_token)
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
        # Send the prompt first. If LINE rejects the reply, do not persist a
        # state that requires buttons the user never received.
        await LineBotService.reply_payer_prompt(reply_token, description, float(amount))
        await StateMachineService.transition(
            db,
            line_user_id,
            StateEnum.WAITING_PAYER,
            {"description": description, "amount": str(amount)},
        )
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

    if action == "payer_me":
        await _handle_payer_select(event, db, user, user_state, "me")
    elif action == "payer_partner":
        await _handle_payer_select(event, db, user, user_state, "partner")
    elif action == "split_aa":
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
    elif action == "delete_items":
        await StateMachineService.reset(db, line_user_id)
        await _handle_delete_items(reply_token, db, user)
    elif action == "delete_expense":
        await _handle_delete_expense(reply_token, db, user, params.get("id", ""))
    elif action == "delete_cancel":
        await LineBotService.reply_main_menu(reply_token, "已取消刪除，回到功能選單 👇")
    else:
        await LineBotService.reply_main_menu(reply_token)


# ──────────────────────────────────────────────────────────────────────────────
#  Action handlers
# ──────────────────────────────────────────────────────────────────────────────

async def _handle_payer_select(event, db, user, user_state, payer_type):
    reply_token = event.reply_token
    if user_state.state != StateEnum.WAITING_PAYER or not user_state.pending_data:
        await LineBotService.reply_text(reply_token, "⚠️ 請先輸入品項和金額。")
        return

    # Update pending data with payer info
    pending_data = user_state.pending_data.copy()
    pending_data["payer_type"] = payer_type

    await LineBotService.reply_split_prompt(
        reply_token, pending_data["description"], float(pending_data["amount"])
    )
    await StateMachineService.transition(
        db, user.line_user_id, StateEnum.WAITING_SPLIT_MODE, pending_data
    )


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
    payer_type = user_state.pending_data.get("payer_type", "me")

    # Determine actual payer and partner
    if payer_type == "me":
        actual_payer, actual_partner = user, partner
        payer_name = "你"
        partner_name = partner.display_name
    else:
        actual_payer, actual_partner = partner, user
        payer_name = partner.display_name
        partner_name = "你"

    expense = await ExpenseService.add_expense_aa(db, actual_payer, actual_partner, description, amount)
    await StateMachineService.reset(db, user.line_user_id)

    msg = SettlementService.format_expense_result(
        description, amount,
        expense.payer_share, expense.partner_share,
        payer_name, partner_name,
    )
    await LineBotService.reply_text(reply_token, msg)


async def _handle_split_custom_init(event, db, user, user_state):
    reply_token = event.reply_token
    if user_state.state != StateEnum.WAITING_SPLIT_MODE or not user_state.pending_data:
        await LineBotService.reply_text(reply_token, "⚠️ 請先輸入品項和金額。")
        return

    amount = Decimal(user_state.pending_data["amount"])
    await LineBotService.reply_custom_split_prompt(reply_token, float(amount))
    await StateMachineService.transition(
        db, user.line_user_id, StateEnum.WAITING_CUSTOM_SPLIT, user_state.pending_data
    )


async def _handle_custom_split_input(event, db, user, user_state, text):
    reply_token = event.reply_token
    if not user_state.pending_data:
        await StateMachineService.reset(db, user.line_user_id)
        await LineBotService.reply_text(reply_token, "⚠️ 資料遺失，請重新輸入品項和金額。")
        return

    description = user_state.pending_data["description"]
    amount = Decimal(user_state.pending_data["amount"])
    payer_type = user_state.pending_data.get("payer_type", "me")

    result = parse_custom_split(text, amount)
    if result is None:
        await LineBotService.reply_text(
            reply_token,
            f"❌ 格式錯誤或金額不符（總額 NT$ {float(amount):,.0f}）\n\n"
            "請重新輸入，例如：\n  我 200\n  我 200 對方 120",
        )
        return

    mine_share, theirs_share = result
    partner = await ExpenseService.get_partner(db, user)
    if not partner:
        await LineBotService.reply_text(reply_token, "⚠️ 找不到配對夥伴，請重新配對。")
        return

    # Determine actual shares and names based on who paid
    if payer_type == "me":
        # Current user is payer
        actual_payer, actual_partner = user, partner
        payer_share, partner_share = mine_share, theirs_share
        payer_name, partner_name = "你", partner.display_name
    else:
        # Partner is payer
        actual_payer, actual_partner = partner, user
        # 'mine_share' is still what the current user (me) owes, so it's partner_share for the actual payer
        payer_share, partner_share = theirs_share, mine_share
        payer_name, partner_name = partner.display_name, "你"

    expense = await ExpenseService.add_expense_custom(
        db, actual_payer, actual_partner, description, amount, payer_share, partner_share
    )
    await StateMachineService.reset(db, user.line_user_id)

    msg = SettlementService.format_expense_result(
        description, amount,
        expense.payer_share, expense.partner_share,
        payer_name, partner_name,
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


async def _handle_delete_items(reply_token, db, user):
    expenses = await ExpenseService.get_recent_expenses(db, user, limit=10)
    await LineBotService.reply_delete_expense_prompt(reply_token, expenses, user.id)


async def _handle_delete_expense(reply_token, db, user, expense_id_value):
    try:
        expense_id = UUID(expense_id_value)
    except (TypeError, ValueError):
        await LineBotService.reply_main_menu(
            reply_token, "⚠️ 無法辨識這筆記錄，回到功能選單 👇"
        )
        return

    async with db.begin_nested():
        expense = await ExpenseService.delete_expense(db, user, expense_id)
        if expense is None:
            await LineBotService.reply_main_menu(
                reply_token, "這筆記錄不存在、已結清或不屬於你的帳本，請重新操作。"
            )
            return

        await LineBotService.reply_main_menu(
            reply_token,
            f"✅ 已刪除：{expense.description}　NT$ {expense.amount:,.2f}\n\n"
            "回到功能選單 👇",
        )


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
