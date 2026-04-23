"""
LINE Bot SDK v3 wrapper — handles all message building and API calls.
"""
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    Configuration,
    ReplyMessageRequest,
    TextMessage,
    QuickReply,
    QuickReplyItem,
    PostbackAction,
)
from app.config import settings

# Re-export so webhook router can use it
__all__ = ["LineBotService", "WebhookParser", "InvalidSignatureError"]

parser = WebhookParser(settings.LINE_CHANNEL_SECRET)
_configuration = Configuration(access_token=settings.LINE_CHANNEL_ACCESS_TOKEN)


class LineBotService:
    """Stateless helper — every method creates a short-lived API client."""

    # ------------------------------------------------------------------ #
    #  Low-level reply helper
    # ------------------------------------------------------------------ #
    @staticmethod
    async def _reply(reply_token: str, messages: list):
        async with AsyncApiClient(_configuration) as api_client:
            api = AsyncMessagingApi(api_client)
            await api.reply_message(
                ReplyMessageRequest(reply_token=reply_token, messages=messages)
            )

    # ------------------------------------------------------------------ #
    #  Profile
    # ------------------------------------------------------------------ #
    @staticmethod
    async def get_display_name(line_user_id: str) -> str:
        try:
            async with AsyncApiClient(_configuration) as api_client:
                api = AsyncMessagingApi(api_client)
                profile = await api.get_profile(line_user_id)
                return profile.display_name
        except Exception:
            return "使用者"

    # ------------------------------------------------------------------ #
    #  Simple text
    # ------------------------------------------------------------------ #
    @staticmethod
    async def reply_text(reply_token: str, text: str):
        await LineBotService._reply(reply_token, [TextMessage(text=text)])

    # ------------------------------------------------------------------ #
    #  Payer selection (Me / Partner)
    # ------------------------------------------------------------------ #
    @staticmethod
    async def reply_payer_prompt(reply_token: str, description: str, amount: float):
        text = (
            f"📝 {description}　NT$ {amount:,.0f}\n"
            "這筆錢是誰付的？ 👇"
        )
        quick_reply = QuickReply(
            items=[
                QuickReplyItem(
                    action=PostbackAction(
                        label="🙋 我付的",
                        data="action=payer_me",
                        display_text="我付的",
                    )
                ),
                QuickReplyItem(
                    action=PostbackAction(
                        label="👤 對方付的",
                        data="action=payer_partner",
                        display_text="對方付的",
                    )
                ),
            ]
        )
        await LineBotService._reply(
            reply_token, [TextMessage(text=text, quick_reply=quick_reply)]
        )

    # ------------------------------------------------------------------ #
    #  Split mode selection  (AA / 自訂)
    # ------------------------------------------------------------------ #
    @staticmethod
    async def reply_split_prompt(reply_token: str, description: str, amount: float):
        text = (
            f"📝 {description}　NT$ {amount:,.0f}\n"
            "請選擇分帳方式 👇"
        )
        quick_reply = QuickReply(
            items=[
                QuickReplyItem(
                    action=PostbackAction(
                        label="🔄 AA 平分",
                        data="action=split_aa",
                        display_text="AA 平分",
                    )
                ),
                QuickReplyItem(
                    action=PostbackAction(
                        label="✏️ 自訂分帳",
                        data="action=split_custom",
                        display_text="自訂分帳",
                    )
                ),
            ]
        )
        await LineBotService._reply(
            reply_token, [TextMessage(text=text, quick_reply=quick_reply)]
        )

    # ------------------------------------------------------------------ #
    #  Main menu
    # ------------------------------------------------------------------ #
    @staticmethod
    async def reply_main_menu(reply_token: str):
        text = "請選擇功能 👇\n\n💡 也可以直接輸入「品項 金額」來記帳\n例如：晚餐 320"
        quick_reply = QuickReply(
            items=[
                QuickReplyItem(
                    action=PostbackAction(
                        label="💰 查詢結算",
                        data="action=query",
                        display_text="查詢結算",
                    )
                ),
                QuickReplyItem(
                    action=PostbackAction(
                        label="📋 歷史紀錄",
                        data="action=history",
                        display_text="歷史紀錄",
                    )
                ),
                QuickReplyItem(
                    action=PostbackAction(
                        label="🧹 清帳",
                        data="action=clear",
                        display_text="清帳",
                    )
                ),
            ]
        )
        await LineBotService._reply(
            reply_token, [TextMessage(text=text, quick_reply=quick_reply)]
        )

    # ------------------------------------------------------------------ #
    #  Custom split prompt
    # ------------------------------------------------------------------ #
    @staticmethod
    async def reply_custom_split_prompt(reply_token: str, amount: float):
        text = (
            f"✏️ 請輸入你要負擔的金額（總額 NT$ {amount:,.0f}）\n\n"
            "格式範例：\n"
            "  我 200　　　→ 你付 200，對方付其餘\n"
            "  我 200 對方 120　→ 各自指定金額\n\n"
            "「我」代表你自己，對方自動為剩餘金額。"
        )
        await LineBotService._reply(reply_token, [TextMessage(text=text)])

    # ------------------------------------------------------------------ #
    #  Clear confirm
    # ------------------------------------------------------------------ #
    @staticmethod
    async def reply_clear_confirm(reply_token: str):
        text = "⚠️ 確定要清帳嗎？\n所有未結清的帳目將標記為已結清。"
        quick_reply = QuickReply(
            items=[
                QuickReplyItem(
                    action=PostbackAction(
                        label="✅ 確認清帳",
                        data="action=clear_confirm",
                        display_text="確認清帳",
                    )
                ),
                QuickReplyItem(
                    action=PostbackAction(
                        label="❌ 取消",
                        data="action=clear_cancel",
                        display_text="取消",
                    )
                ),
            ]
        )
        await LineBotService._reply(
            reply_token, [TextMessage(text=text, quick_reply=quick_reply)]
        )
