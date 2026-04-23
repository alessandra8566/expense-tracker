from decimal import Decimal
from app.services.settlement import SettlementService


class TestSettlementFormat:
    def test_partner_owes_me(self):
        msg = SettlementService._format(Decimal("430"), "小明")
        assert "小明 共欠你" in msg
        assert "430" in msg

    def test_i_owe_partner(self):
        msg = SettlementService._format(Decimal("-200"), "小明")
        assert "你共欠 小明" in msg
        assert "200" in msg

    def test_balanced(self):
        msg = SettlementService._format(Decimal("0"), "小明")
        assert "平衡" in msg

    def test_format_history_empty(self):
        msg = SettlementService.format_history([], "some-id")
        assert "沒有" in msg

    def test_format_expense_result(self):
        msg = SettlementService.format_expense_result(
            "晚餐", Decimal("320"), Decimal("160"), Decimal("160"), "你", "小明"
        )
        assert "晚餐" in msg
        assert "320" in msg
        assert "160" in msg
