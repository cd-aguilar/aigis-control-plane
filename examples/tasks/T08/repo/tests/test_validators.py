from validators import is_valid_username


def test_accepts_a_valid_username():
    assert is_valid_username('dario_99') is True


def test_rejects_too_short():
    assert is_valid_username('ab') is False


def test_rejects_too_long():
    assert is_valid_username('a' * 21) is False


def test_rejects_invalid_characters():
    assert is_valid_username('bad name!') is False
