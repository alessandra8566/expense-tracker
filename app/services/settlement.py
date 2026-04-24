"""
Settlement service — calculates who owes whom and how much.

Logic:
  For each unsettled expense:
    - The payer actually paid the full `amount`
    - The payer was only responsible for `payer_share`
    - So the partner owes the payer: `partner_share`

  net = Σ partner_share (where I am payer) − Σ partner_share (where partner is payer)

  net > 0  →  partner owes me `net`
  net < 0  →  I owe partner `|net|`
  net == 0 →  balanced
"""
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.expense import Expense
from app.models.user import User


class SettlementService:

    @staticmethod
    async def calculate(
        db: AsyncSession, me: User, partner: User
    ) -> tuple[Decimal, str]:
        """
        Returns (net_amount, human_readable_message).
        net_amount > 0  → partner owes me
        net_amount < 0  → I owe partner
        """
        result = await db.execute(
            select(Expense).where(
                or_(
                    Expense.payer_id == me.id,
                    Expense.payer_id == partner.id,
                ),
                Expense.is_settled == False,
            )
        )
        expenses = result.scalars().all()

        owed_to_me = Decimal("0")       # partner owes me (I paid, partner's share)
        owed_to_partner = Decimal("0")  # I owe partner (partner paid, my share)

        for exp in expenses:
            if exp.payer_id == me.id:
                owed_to_me += exp.partner_share
            else:
                owed_to_partner += exp.partner_share

        net = owed_to_me - owed_to_partner
        msg = SettlementService._format(net, partner.display_name)
        return net, msg

    @staticmethod
    def _format(net: Decimal, partner_name: str) -> str:
        if net > 0:
            return (
                f"💸 結算結果\n"
                f"──────────\n"
                f"🎯 {partner_name} 共欠你\n"
                f"NT$ {net:,.0f}"
            )
        elif net < 0:
            return (
                f"💸 結算結果\n"
                f"──────────\n"
                f"🎯 你共欠 {partner_name}\n"
                f"NT$ {abs(net):,.0f}"
            )
        else:
            return "🎉 目前帳務已平衡，互不相欠！"

    @staticmethod
    def format_history(expenses: list, me_id) -> str:
        if not expenses:
            return "📋 目前沒有未結清的記錄。"
            
        header = "📋 最近未結清紀錄\n──────────"
        items = []
        for exp in expenses:
            who = "你先付" if str(exp.payer_id) == str(me_id) else "對方付"
            mode = "AA" if exp.split_mode.value == "AA" else "自訂"
            ts = exp.created_at.strftime("%m/%d %H:%M")
            my_share = exp.payer_share if str(exp.payer_id)==str(me_id) else exp.partner_share
            
            items.append(
                f"🔹 {ts} {exp.description}\n"
                f"   總額 ${exp.amount:,.0f} ({who}/{mode})\n"
                f"   👉 你負擔 ${my_share:,.0f}"
            )
            
        return header + "\n" + "\n\n".join(items)

    @staticmethod
    def format_expense_result(
        description: str,
        amount: Decimal,
        payer_share: Decimal,
        partner_share: Decimal,
        payer_name: str,
        partner_name: str,
    ) -> str:
        return (
            f"✅ 已記帳：{description}\n"
            f"──────────\n"
            f"💰 總額：NT$ {amount:,.0f}\n"
            f"👤 {payer_name}：NT$ {payer_share:,.0f}\n"
            f"👤 {partner_name}：NT$ {partner_share:,.0f}"
        )
