import pytest
from decimal import Decimal
from app.services.expense_service import parse_expense_input, parse_custom_split


class TestParseExpenseInput:
    def test_basic_chinese(self):
        assert parse_expense_input("晚餐 320") == ("晚餐", Decimal("320"))

    def test_english_item(self):
        assert parse_expense_input("Costco 3000") == ("Costco", Decimal("3000"))

    def test_decimal_amount(self):
        assert parse_expense_input("咖啡 50.5") == ("咖啡", Decimal("50.5"))

    def test_comma_amount(self):
        assert parse_expense_input("超市 1,200") == ("超市", Decimal("1200"))

    def test_no_amount(self):
        assert parse_expense_input("晚餐") is None

    def test_zero_amount(self):
        assert parse_expense_input("晚餐 0") is None

    def test_negative_amount(self):
        assert parse_expense_input("晚餐 -100") is None

    def test_empty(self):
        assert parse_expense_input("") is None

    def test_menu_keyword(self):
        assert parse_expense_input("選單") is None


class TestParseCustomSplit:
    def test_mine_only(self):
        total = Decimal("320")
        result = parse_custom_split("我 200", total)
        assert result == (Decimal("200"), Decimal("120"))

    def test_mine_only_no_space(self):
        result = parse_custom_split("我200", Decimal("300"))
        assert result == (Decimal("200"), Decimal("100"))

    def test_both_specified_valid(self):
        result = parse_custom_split("我 200 對方 120", Decimal("320"))
        assert result == (Decimal("200"), Decimal("120"))

    def test_both_specified_mismatch(self):
        # 200 + 200 != 320
        result = parse_custom_split("我 200 對方 200", Decimal("320"))
        assert result is None

    def test_negative_mine(self):
        result = parse_custom_split("我 -50", Decimal("320"))
        assert result is None

    def test_invalid_format(self):
        assert parse_custom_split("隨便文字", Decimal("320")) is None
