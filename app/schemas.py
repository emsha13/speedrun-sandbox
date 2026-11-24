from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.models import Role


def strong_enough(password: str) -> str:
    if len(password.encode()) > 72:
        raise ValueError('password is longer than 72 bytes')
    if not any(c.islower() for c in password):
        raise ValueError('password needs a lowercase letter')
    if not any(c.isupper() for c in password):
        raise ValueError('password needs an uppercase letter')
    if not any(c.isdigit() for c in password):
        raise ValueError('password needs a digit')
    if any(c.isspace() for c in password):
        raise ValueError('password cannot hold a space')
    return password


Password = Annotated[str, Field(min_length=8), AfterValidator(strong_enough)]
Email = Annotated[EmailStr, Field(max_length=254), AfterValidator(str.lower)]
# E.164: a plus, a country code that does not start with zero, eight to fifteen digits in all.
Phone = Annotated[str, Field(pattern=r'^\+[1-9][0-9]{7,14}$')]
Name = Annotated[str, Field(min_length=1, max_length=50, pattern=r'^\S(.*\S)?$')]
Code = Annotated[str, Field(pattern=r'^[0-9]{6}$')]


class EmailOrPhone(BaseModel):
    """Who is asking, by address or by number — one of the two, never both."""
    email: Email | None = None
    phone: Phone | None = None

    @model_validator(mode='after')
    def exactly_one(self) -> Self:
        if (self.email is None) == (self.phone is None):
            raise ValueError('give an email or a phone, one of the two')
        return self

    @property
    def login(self) -> str:
        return self.email or self.phone


class Registration(BaseModel):
    email: Email
    password: Password
    first_name: Name
    last_name: Name


class EmailOnly(BaseModel):
    email: Email


class EmailAndCode(BaseModel):
    email: Email
    code: Code


class Credentials(EmailOrPhone):
    password: str


class RefreshToken(BaseModel):
    refresh_token: str


class PasswordReset(EmailOrPhone):
    code: Code
    new_password: Password


class PasswordChange(BaseModel):
    current_password: str
    new_password: Password


class EmailChange(BaseModel):
    new_email: Email
    password: str


class PhoneChange(BaseModel):
    new_phone: Phone
    password: str


class CodeOnly(BaseModel):
    code: Code


class PasswordOnly(BaseModel):
    password: str


class ProfileUpdate(BaseModel):
    first_name: Name | None = None
    last_name: Name | None = None
    birth_date: date | None = None


class Tokens(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = 'bearer'


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    phone: str | None
    first_name: str
    last_name: str
    birth_date: date | None
    role: Role
    is_active: bool
    created_at: datetime


class SessionOut(BaseModel):
    id: int
    user_agent: str
    created_at: datetime
    current: bool


class UserQuery(BaseModel):
    """What the list of users is asked for."""
    model_config = ConfigDict(extra='forbid')

    search: str | None = Field(None, min_length=1, max_length=100)
    is_active: bool | None = None
    role: Role | None = None
    sort: Literal['id', 'email', 'first_name', 'last_name', 'created_at'] = 'id'
    order: Literal['asc', 'desc'] = 'asc'
    limit: int = Field(20, ge=1, le=100)
    offset: int = Field(0, ge=0)


class UserPage(BaseModel):
    total: int
    items: list[UserOut]


class UserAdminUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    is_active: bool | None = None
    role: Role | None = None
