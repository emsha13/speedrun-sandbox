"""What every table of the workspace is made of.

A row belongs to one organisation and says so itself, in `organisation_id` — also the rows that
could find it through a parent. One column answers "whose is this" for every table alike, and the
doors in `crud.py` need nothing else to keep one organisation out of another's rows.

A column carries, in `info`, what the doors need to know of it and the database does not:

    managed    the application sets it; no request does
    fixed      set when the row is made and not changed after
    hidden     never shown
    field      what a value must satisfy, in pydantic's words: `ge`, `le`, `pattern`
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.models import now

COLOR = r'^#[0-9a-f]{6}$'
COUNTRY = r'^[A-Z]{2}$'
CURRENCY = r'^[A-Z]{3}$'
KEY = r'^[A-Z][A-Z0-9]{1,7}$'
SLUG = r'^[a-z0-9]+(-[a-z0-9]+)*$'
EMAIL = r'^[^@\s]+@[^@\s]+\.[^@\s]+$'
URL = r'^https?://\S+$'


def col(*args, managed: bool = False, fixed: bool = False, hidden: bool = False, **rest):
    field = {name: rest.pop(name) for name in ('ge', 'le', 'gt', 'lt', 'pattern') if name in rest}
    info = {'managed': managed, 'fixed': fixed, 'hidden': hidden, 'field': field}
    return mapped_column(*args, info=info, **rest)


def ref(table: str, **rest):
    """A row of another table that this one cannot be without: it goes when that one goes."""
    return col(ForeignKey(f'{table}.id', ondelete='CASCADE'), index=True, **rest)


def loose(table: str, **rest):
    """A row of another table that this one outlives. The column is nullable."""
    return col(ForeignKey(f'{table}.id', ondelete='SET NULL'), index=True, **rest)


def moment(**rest):
    return col(DateTime(timezone=True), **rest)


def money(**rest):
    return col(Numeric(12, 2), **rest)


class Owned:
    id: Mapped[int] = mapped_column(primary_key=True, sort_order=-3)
    organisation_id: Mapped[int] = mapped_column(
        ForeignKey('organisations.id', ondelete='CASCADE'), index=True, sort_order=-2,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, sort_order=-1)
