import jwt
import pytest

from datetime import UTC, datetime, timedelta

from app import security
from app.settings import settings


def test_a_hash_is_not_the_password():
    assert security.hash_password('Passw0rd') != 'Passw0rd'


def test_a_hash_verifies_its_password():
    assert security.verify_password('Passw0rd', security.hash_password('Passw0rd'))


def test_a_hash_verifies_no_other_password():
    assert not security.verify_password('Passw0rD', security.hash_password('Passw0rd'))


def test_two_hashes_of_one_password_differ():
    assert security.hash_password('Passw0rd') != security.hash_password('Passw0rd')


def test_nobodys_hash_verifies_nothing_one_could_type():
    assert not security.verify_password('', security.NOBODYS_HASH)
    assert not security.verify_password('Passw0rd', security.NOBODYS_HASH)


@pytest.mark.parametrize('value', ['', 'a', '123456', 'x' * 1000, 'Ünïcödé', 'token-with-dashes_and_underscores'])
def test_digest_is_sixty_four_hex_digits(value):
    digest = security.digest(value)

    assert len(digest) == 64 and set(digest) <= set('0123456789abcdef')


@pytest.mark.parametrize('value', ['123456', 'a refresh token', ''])
def test_digest_is_the_same_every_time(value):
    assert security.digest(value) == security.digest(value)


@pytest.mark.parametrize('one, another', [('123456', '123457'), ('a', 'A'), ('', ' '), ('abc', 'abc ')])
def test_digests_differ(one, another):
    assert security.digest(one) != security.digest(another)


def test_digest_depends_on_the_key(monkeypatch):
    before = security.digest('123456')
    monkeypatch.setattr(settings, 'SECRET_KEY', 'another-key-another-key-another-key')

    assert security.digest('123456') != before


def test_codes_are_six_digits():
    codes = {security.random_code() for _ in range(200)}

    assert all(len(code) == 6 and code.isdigit() for code in codes)
    assert len(codes) > 190


def test_small_codes_keep_their_zeros(mocker):
    mocker.patch('secrets.randbelow', return_value=42)

    assert security.random_code() == '000042'


def test_tokens_are_long_and_differ():
    tokens = {security.random_token() for _ in range(50)}

    assert len(tokens) == 50 and all(len(token) >= 43 for token in tokens)


def test_access_token_names_the_user_and_the_session():
    payload = security.read_access_token(security.create_access_token(7, 42))

    assert (payload['sub'], payload['sid']) == ('7', 42)


@pytest.mark.freeze_time('2026-03-01 10:00:00')
def test_access_token_is_dated():
    payload = security.read_access_token(security.create_access_token(7, 42))

    assert payload['iat'] == int(datetime(2026, 3, 1, 10, tzinfo=UTC).timestamp())
    assert payload['exp'] - payload['iat'] == 15 * 60


@pytest.mark.freeze_time
@pytest.mark.parametrize('seconds, alive', [(0, True), (60, True), (15 * 60 - 1, True), (15 * 60 + 1, False), (3600, False)])
def test_access_token_lives_fifteen_minutes(freezer, seconds, alive):
    token = security.create_access_token(7, 42)
    freezer.tick(seconds)

    assert (security.read_access_token(token) is not None) is alive


@pytest.mark.parametrize('token', ['', 'nonsense', 'a.b.c', 'a.b', '....', 'eyJhbGciOiJub25lIn0.eyJzdWIiOiI3In0.'])
def test_what_is_not_a_token(token):
    assert security.read_access_token(token) is None


def test_token_signed_with_another_key():
    forged = jwt.encode(
        {'sub': '7', 'sid': 42, 'exp': datetime.now(UTC) + timedelta(minutes=5)}, 'k' * 40, algorithm='HS256'
    )

    assert security.read_access_token(forged) is None


def test_token_with_another_algorithm(monkeypatch):
    monkeypatch.setattr(settings, 'SECRET_KEY', 'k' * 64)
    forged = jwt.encode(
        {'sub': '7', 'sid': 42, 'exp': datetime.now(UTC) + timedelta(minutes=5)}, settings.SECRET_KEY,
        algorithm='HS512',
    )

    assert security.read_access_token(forged) is None


def test_tampered_token():
    header, payload, signature = security.create_access_token(7, 42).split('.')

    assert security.read_access_token('.'.join([header, payload, signature[::-1]])) is None
