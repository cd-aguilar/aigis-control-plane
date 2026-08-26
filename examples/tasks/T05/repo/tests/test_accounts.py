import pytest

from accounts import Account


def test_withdraw_reduces_balance():
    account = Account(100)
    account.withdraw(30)
    assert account.balance == 70


def test_withdraw_rejects_negative_amount():
    account = Account(100)
    with pytest.raises(ValueError):
        account.withdraw(-10)


def test_withdraw_rejects_insufficient_balance():
    account = Account(50)
    with pytest.raises(ValueError):
        account.withdraw(100)
