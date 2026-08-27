from inventory import apply_discount


def test_apply_discount_round_percent():
    assert apply_discount(200, 10) == 20.0


def test_apply_discount_non_round_result():
    assert apply_discount(250, 33) == 82.5
