"""
Expense service — user management, parsing, and expense CRUD.
"""
import re
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Tuple, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.expense import Expense, SplitMode


# ──────────────────────────────────────────────────────────────────────────────
#  Input parsing helpers
# ──────────────────────────────────────────────────────────────────────────────

# Matches: "晚餐 320" / "Costco 3,000" / "咖啡 50.5"
_EXPENSE_RE = re.compile(
    r"^(?P<desc>.+?)\s+(?P<amount>[\d,]+(?:\.\d+)?)$",
    re.UNICODE,
)

# Matches custom split input:
#   "200"             → mine=200
#   "我 200"          → mine=200
#   "我200對方120"    → mine=200, theirs=120
_CUSTOM_RE = re.compile(
    r"^(?:我\s*)?(?P<mine>[\d,]+(?:\.\d+)?)"
    r"(?:\s*對方\s*(?P<theirs>[\d,]+(?:\.\d+)?))?$",
    re.UNICODE,
)


def parse_expense_input(text: str) -> Optional[Tuple[str, Decimal]]:
    """Return (description, amount) or None if text doesn't match."""
    m = _EXPENSE_RE.match(text.strip())
    if not m:
        return None
    try:
        amount = Decimal(m.group("amount").replace(",", ""))
        if amount <= 0:
            return None
        return m.group("desc").strip(), amount
    except Exception:
        return None


def parse_custom_split(text: str, total: Decimal) -> Optional[Tuple[Decimal, Decimal]]:
    """
    Return (payer_share, partner_share) from custom split text, or None on error.
    Ensures payer_share + partner_share == total.
    """
    m = _CUSTOM_RE.match(text.strip())
    if not m:
        return None
    try:
        mine = Decimal(m.group("mine").replace(",", ""))
        if m.group("theirs"):
            theirs = Decimal(m.group("theirs").replace(",", ""))
            # Validate sum
            if (mine + theirs).quantize(Decimal("0.01")) != total.quantize(Decimal("0.01")):
                return None
        else:
            theirs = total - mine
        if mine < 0 or theirs < 0:
            return None
        return mine, theirs
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────────────
#  User management
# ──────────────────────────────────────────────────────────────────────────────

class ExpenseService:

    @staticmethod
    async def get_or_create_user(
        db: AsyncSession, line_user_id: str, display_name: str = "使用者"
    ) -> User:
        result = await db.execute(
            select(User).where(User.line_user_id == line_user_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            user = User(line_user_id=line_user_id, display_name=display_name)
            db.add(user)
            await db.flush()
        return user

    @staticmethod
    async def get_partner(db: AsyncSession, user: User) -> Optional[User]:
        if not user.partner_id:
            return None
        result = await db.execute(
            select(User).where(User.id == user.partner_id)
        )
        return result.scalar_one_or_none()

    # ── Invite code ──────────────────────────────────────────────────────────

    @staticmethod
    def _gen_code(length: int = 6) -> str:
        return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))

    @staticmethod
    async def generate_invite_code(db: AsyncSession, user: User) -> str:
        code = ExpenseService._gen_code()
        # Ensure uniqueness
        while True:
            result = await db.execute(
                select(User).where(User.invite_code == code)
            )
            if result.scalar_one_or_none() is None:
                break
            code = ExpenseService._gen_code()
        user.invite_code = code
        user.invite_code_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
        await db.flush()
        return code

    @staticmethod
    async def pair_with_code(
        db: AsyncSession, requester: User, code: str
    ) -> Tuple[bool, str]:
        """
        Try to pair requester with the user who owns `code`.
        Returns (success, message).
        """
        if requester.partner_id:
            return False, "❌ 你已經有配對夥伴了！"

        result = await db.execute(
            select(User).where(User.invite_code == code.upper().strip())
        )
        target: Optional[User] = result.scalar_one_or_none()

        if target is None:
            return False, "❌ 找不到這個邀請碼，請確認是否正確。"
        if target.id == requester.id:
            return False, "❌ 不能和自己配對喔！"
        if target.partner_id:
            return False, "❌ 對方已與他人配對。"
        if target.invite_code_expires_at and target.invite_code_expires_at < datetime.now(timezone.utc):
            return False, "❌ 邀請碼已過期，請對方重新產生。"

        # Link both users
        requester.partner_id = target.id
        target.partner_id = requester.id
        # Clear invite code
        target.invite_code = None
        target.invite_code_expires_at = None
        await db.flush()
        return True, f"✅ 已成功與 {target.display_name} 配對！可以開始記帳了 🎉"

    # ── Expense CRUD ─────────────────────────────────────────────────────────

    @staticmethod
    async def add_expense_aa(
        db: AsyncSession,
        payer: User,
        partner: User,
        description: str,
        amount: Decimal,
    ) -> Expense:
        half = (amount / 2).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        partner_share = amount - half  # handles odd cents
        expense = Expense(
            payer_id=payer.id,
            partner_id=partner.id,
            description=description,
            amount=amount,
            split_mode=SplitMode.AA,
            payer_share=half,
            partner_share=partner_share,
        )
        db.add(expense)
        await db.flush()
        return expense

    @staticmethod
    async def add_expense_custom(
        db: AsyncSession,
        payer: User,
        partner: User,
        description: str,
        amount: Decimal,
        payer_share: Decimal,
        partner_share: Decimal,
    ) -> Expense:
        expense = Expense(
            payer_id=payer.id,
            partner_id=partner.id,
            description=description,
            amount=amount,
            split_mode=SplitMode.CUSTOM,
            payer_share=payer_share,
            partner_share=partner_share,
        )
        db.add(expense)
        await db.flush()
        return expense

    @staticmethod
    async def get_history(
        db: AsyncSession, user: User, limit: int = 10
    ) -> List[Expense]:
        """Return last `limit` unsettled expenses involving this user."""
        from sqlalchemy import or_, desc
        result = await db.execute(
            select(Expense)
            .where(
                or_(Expense.payer_id == user.id, Expense.partner_id == user.id),
                Expense.is_settled == False,
            )
            .order_by(desc(Expense.created_at))
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def settle_all(db: AsyncSession, user: User) -> int:
        """Mark all unsettled expenses for this pair as settled. Returns count."""
        from sqlalchemy import or_, update
        result = await db.execute(
            select(Expense).where(
                or_(Expense.payer_id == user.id, Expense.partner_id == user.id),
                Expense.is_settled == False,
            )
        )
        expenses = result.scalars().all()
        for exp in expenses:
            exp.is_settled = True
        await db.flush()
        return len(expenses)
