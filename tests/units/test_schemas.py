"""The shapes the doors accept, checked without a door."""
import pytest

from pydantic import BaseModel, ValidationError

from app.schemas import (
    Code, Credentials, Email, EmailOrPhone, Name, Password, PasswordReset, Phone, ProfileUpdate, UserAdminUpdate,
    UserQuery,
)


class Shapes(BaseModel):
    password: Password = 'Passw0rd'
    email: Email = 'ann@example.com'
    phone: Phone = '+4915112345678'
    name: Name = 'Ann'
    code: Code = '123456'


def accepted(**value) -> Shapes:
    return Shapes(**value)


def refused(**value) -> str:
    with pytest.raises(ValidationError) as caught:
        Shapes(**value)
    return str(caught.value)


@pytest.mark.parametrize('password', [
    'Passw0rd', 'aB345678', 'Aa1' + 'x' * 69, 'Aa1' + 'é' * 34, 'ÄÖÜäöü12', 'Tr0ub4dor&3', 'correctHorse7', 'Zz9!@#$%',
    'P4ssword-with-dashes', 'Ab1' + '🙂' * 5,
])
def test_password_accepted(password):
    assert accepted(password=password).password == password


@pytest.mark.parametrize('password, why', [
    ('', 'at least 8'), ('Sh0rt', 'at least 8'), ('Seven7!', 'at least 8'),
    ('nouppercase1', 'uppercase'), ('NOLOWERCASE1', 'lowercase'), ('NoDigitsHere', 'digit'),
    ('12345678', 'lowercase'), ('abcdefgh', 'uppercase'), ('ABCDEFGH', 'lowercase'), ('!@#$%^&*', 'lowercase'),
    ('Passw0rd with space', 'space'), ('Passw0rd\t', 'space'), ('Passw0rd\n', 'space'), (' Passw0rd', 'space'),
    ('Aa1' + 'x' * 70, '72 bytes'), ('Aa1' + 'é' * 35, '72 bytes'), ('Aa1' + '🙂' * 18, '72 bytes'),
])
def test_password_refused(password, why):
    assert why in refused(password=password)


@pytest.mark.parametrize('password', [None, 12345678, ['Passw0rd'], {'password': 'Passw0rd'}, 1.5, True])
def test_password_is_text(password):
    refused(password=password)


@pytest.mark.parametrize('phone', [
    '+12025550123', '+442071234567', '+4915112345678', '+81312345678', '+35812345678', '+12345678', '+123456789012345',
    '+998901234567', '+61412345678', '+5511912345678',
])
def test_phone_accepted(phone):
    assert accepted(phone=phone).phone == phone


@pytest.mark.parametrize('phone', [
    '', '+', '4915112345678', '004915112345678', '+0915112345678', '+49 151 12345678', '+49-151-12345678',
    '+49(151)12345678', '+1234567', '+1234567890123456', '+49151123456ab', '++4915112345678', '+4915112345678 ',
    ' +4915112345678', '+４９１５１１２３４５６７８', '+49.151.12345678', 'phone', '+49151123#4567',
])
def test_phone_refused(phone):
    refused(phone=phone)


@pytest.mark.parametrize('given, kept', [
    ('ann@example.com', 'ann@example.com'), ('Ann@Example.com', 'ann@example.com'),
    ('ANN@EXAMPLE.COM', 'ann@example.com'), ('ann.lee@example.com', 'ann.lee@example.com'),
    ('ann+tag@example.com', 'ann+tag@example.com'), ('ann_lee@example.co.uk', 'ann_lee@example.co.uk'),
    ('a@example.org', 'a@example.org'), ('ann-lee@sub.example.com', 'ann-lee@sub.example.com'),
    ('1234@example.com', '1234@example.com'), ("o'neil@example.com", "o'neil@example.com"),
])
def test_email_accepted_and_lowercased(given, kept):
    assert accepted(email=given).email == kept


@pytest.mark.parametrize('email', [
    '', 'ann', 'ann@', '@example.com', 'ann@example', 'a b@example.com', 'ann@@example.com', 'ann@.com',
    'ann@example..com', '.ann@example.com', 'ann.@example.com', 'ann@example.com.', 'ann@-example.com',
    'ann@exa mple.com', 'x' * 250 + '@example.com', 'ann@localhost',
])
def test_email_refused(email):
    refused(email=email)


@pytest.mark.parametrize('name', [
    'Ann', 'A', 'Anne-Marie', "O'Neil", 'van der Berg', 'Élodie', 'Søren', 'Łukasz', 'Нина', '田中', 'x' * 50, 'J. R.',
    'Ann  Lee', '42',
])
def test_name_accepted(name):
    assert accepted(name=name).name == name


@pytest.mark.parametrize('name', ['', ' ', '  ', ' Ann', 'Ann ', '\tAnn', 'Ann\n', 'x' * 51, ' Ann', None, 42])
def test_name_refused(name):
    refused(name=name)


@pytest.mark.parametrize('code', ['000000', '123456', '999999', '000001'])
def test_code_accepted(code):
    assert accepted(code=code).code == code


@pytest.mark.parametrize('code', [
    '', '12345', '1234567', 'abcdef', '12 456', ' 123456', '123456 ', '12345a', '１２３４５６', '-12345', '+12345', '1e5000',
    123456, None,
])
def test_code_refused(code):
    refused(code=code)


@pytest.mark.parametrize('model, extra', [
    (EmailOrPhone, {}), (Credentials, {'password': 'x'}), (PasswordReset, {'code': '123456', 'new_password': 'Passw0rd'}),
])
@pytest.mark.parametrize('who, login', [
    ({'email': 'Ann@Example.com'}, 'ann@example.com'), ({'phone': '+4915112345678'}, '+4915112345678'),
    ({'email': 'ann@example.com', 'phone': None}, 'ann@example.com'),
    ({'email': None, 'phone': '+4915112345678'}, '+4915112345678'),
])
def test_an_address_or_a_number(model, extra, who, login):
    assert model(**who, **extra).login == login


@pytest.mark.parametrize('model, extra', [
    (EmailOrPhone, {}), (Credentials, {'password': 'x'}), (PasswordReset, {'code': '123456', 'new_password': 'Passw0rd'}),
])
@pytest.mark.parametrize('who', [
    {}, {'email': None}, {'phone': None}, {'email': None, 'phone': None},
    {'email': 'ann@example.com', 'phone': '+4915112345678'}, {'email': 'ann'}, {'phone': '12345'},
    {'email': '+4915112345678'}, {'phone': 'ann@example.com'},
])
def test_neither_or_both(model, extra, who):
    with pytest.raises(ValidationError):
        model(**who, **extra)


def test_user_query_defaults():
    query = UserQuery()

    assert (query.search, query.is_active, query.role) == (None, None, None)
    assert (query.sort, query.order, query.limit, query.offset) == ('id', 'asc', 20, 0)


@pytest.mark.parametrize('given', [
    {'limit': 1}, {'limit': 100}, {'limit': '50'}, {'offset': 0}, {'offset': 10 ** 6}, {'sort': 'email'},
    {'sort': 'created_at', 'order': 'desc'}, {'role': 'admin'}, {'role': 'user'}, {'is_active': 'true'},
    {'is_active': 'false'}, {'is_active': '1'}, {'search': 'a'}, {'search': 'x' * 100}, {'search': '%'},
])
def test_user_query_accepted(given):
    UserQuery(**given)


@pytest.mark.parametrize('given', [
    {'limit': 0}, {'limit': 101}, {'limit': -1}, {'limit': 'ten'}, {'limit': 1.5}, {'offset': -1}, {'offset': 'two'},
    {'sort': 'password_hash'}, {'sort': 'phone'}, {'sort': ''}, {'sort': 'ID'}, {'order': 'up'}, {'order': 'ASC'},
    {'role': 'king'}, {'role': ''}, {'is_active': 'maybe'}, {'search': ''}, {'search': 'x' * 101}, {'page': 2},
])
def test_user_query_refused(given):
    with pytest.raises(ValidationError):
        UserQuery(**given)


@pytest.mark.parametrize('given, kept', [
    ({}, {}), ({'first_name': 'Anna'}, {'first_name': 'Anna'}), ({'birth_date': '1990-05-17'}, {'birth_date'}),
    ({'birth_date': None}, {'birth_date': None}), ({'first_name': None}, {'first_name': None}),
    ({'email': 'x@example.com'}, {}),
])
def test_profile_update_keeps_what_was_sent(given, kept):
    sent = ProfileUpdate(**given).model_dump(exclude_unset=True)

    assert set(sent) == set(kept)


@pytest.mark.parametrize('day', ['', 'yesterday', '17.05.1990', '1990-13-01', '1990-02-30', '90-05-17', 19900517.5])
def test_profile_update_bad_day(day):
    with pytest.raises(ValidationError):
        ProfileUpdate(birth_date=day)


@pytest.mark.parametrize('given', [{'role': 'king'}, {'is_active': 'maybe'}, {'email': 'x@example.com'}, {'id': 2}])
def test_admin_update_refused(given):
    with pytest.raises(ValidationError):
        UserAdminUpdate(**given)


@pytest.mark.parametrize('given', [{}, {'role': 'admin'}, {'is_active': False}, {'role': 'user', 'is_active': True}])
def test_admin_update_accepted(given):
    assert UserAdminUpdate(**given).model_dump(exclude_none=True) == given
