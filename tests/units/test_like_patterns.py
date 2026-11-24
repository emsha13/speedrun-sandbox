import pytest

from app.routers.users import escaped


@pytest.mark.parametrize('text, pattern', [
    ('ann', 'ann'), ('', ''), ('100%', '100\\%'), ('a_b', 'a\\_b'), ('%', '\\%'), ('_', '\\_'), ('\\', '\\\\'),
    ('\\%', '\\\\\\%'), ('%%', '\\%\\%'), ('a%b_c\\d', 'a\\%b\\_c\\\\d'), ("o'neil", "o'neil"), ('+4915', '+4915'),
    ('ann@example.com', 'ann@example.com'), ('Нина', 'Нина'),
])
def test_escaped(text, pattern):
    assert escaped(text) == pattern
