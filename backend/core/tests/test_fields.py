from core.fields import MoneyField, QuantityField


def test_money_and_quantity_precision() -> None:
    money, quantity = MoneyField(), QuantityField()

    assert (money.max_digits, money.decimal_places) == (12, 2)
    assert (quantity.max_digits, quantity.decimal_places) == (14, 3)


def test_precision_can_be_overridden() -> None:
    assert MoneyField(max_digits=14).max_digits == 14
