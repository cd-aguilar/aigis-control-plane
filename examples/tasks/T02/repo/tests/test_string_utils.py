from string_utils import reverse_words


def test_reverse_words():
    assert reverse_words('the quick brown fox') == 'fox brown quick the'
