from datetime import date, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field


def strong_enough(password: str) -> str:
    if len(password.encode()) > 72:
        raise ValueError('password is longer than 72 bytes')
    if not any(c.islower() for c in password):
        raise ValueError('password needs a lowercase letter')
    if not any(c.isupper() for c in password):
        raise ValueError('password needs an uppercase letter')
    if not any(c.isdigit() for c in password):
        raise ValueError('password needs a digit')
    return password


Password = Annotated[str, Field(min_length=8), AfterValidator(strong_enough)]
Email = Annotated[EmailStr, Field(max_length=254), AfterValidator(str.lower)]
Name = Annotated[str, Field(min_length=1, max_length=50, pattern=r'^\S(.*\S)?$')]
Code = Annotated[str, Field(pattern=r'^\d{6}$')]


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


class Credentials(BaseModel):
    email: Email
    password: str


class RefreshToken(BaseModel):
    refresh_token: str


class PasswordReset(BaseModel):
    email: Email
    code: Code
    new_password: Password


class PasswordChange(BaseModel):
    current_password: str
    new_password: Password


class EmailChange(BaseModel):
    new_email: Email
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
    first_name: str
    last_name: str
    birth_date: date | None
    is_active: bool
    created_at: datetime


class SessionOut(BaseModel):
    id: int
    user_agent: str
    created_at: datetime
    current: bool
