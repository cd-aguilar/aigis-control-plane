from formatting import format_full_name, format_short_name


def test_format_full_name_strips_whitespace():
    assert format_full_name('  john ', ' smith ') == 'John Smith'


def test_format_short_name_strips_whitespace():
    assert format_short_name('  john ', ' smith ') == 'J. Smith'
