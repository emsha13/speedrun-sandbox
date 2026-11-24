"""Rows of any table of the workspace, made up: valid, and different from each other.

`make` puts a row straight into the database, with whatever rows it needs above it made first;
`body` is what a request to make one would send. Both fill in what a row cannot be without and
leave the rest to the table's defaults.
"""
import enum
import itertools

from collections import defaultdict

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import get_origin

from sqlalchemy import JSON

from app.db import Base
from app.workspace import base
from app.workspace.crud import bare, kinds_of

_numbers = itertools.count(1)
_turns = defaultdict(itertools.count)
A_MONDAY = date(2026, 1, 5)

PATTERNS = {
    base.COLOR: lambda n: f'#{n % 0xffffff:06x}',
    base.COUNTRY: lambda n: 'DE',
    base.CURRENCY: lambda n: 'EUR',
    base.KEY: lambda n: f'K{n}',
    base.SLUG: lambda n: f'slug-{n}',
    base.EMAIL: lambda n: f'person{n}@example.com',
    base.URL: lambda n: f'https://example.com/{n}',
    r'^[a-z0-9-]+(\.[a-z0-9-]+)+$': lambda n: f'd{n}.example.com',
    r'^[0-9a-f]{64}$': lambda n: f'{n:064x}',
    r'^[0-9a-f:.]+/[0-9]{1,3}$': lambda n: f'10.{n % 256}.0.0/16',
    r'^[a-z][a-z0-9_.]*$': lambda n: f'name_{n}',
    r'^[a-z0-9][a-z0-9-]*$': lambda n: f'room-{n}',
}


def model_of(table):
    return next(mapper.class_ for mapper in Base.registry.mappers if mapper.local_table is table)


def lowest(column) -> int:
    field = column.info.get('field', {})
    if 'ge' in field:
        return field['ge']
    return field['gt'] + 1 if 'gt' in field else 1


def a_date(key: str, n: int) -> date:
    # Whatever ends ends after whatever starts starts; a week is said by its Monday; and every
    # day here is in the past.
    if key in ('ends_on', 'until', 'valid_until'):
        return date(2026, 6, 1)
    return A_MONDAY + timedelta(weeks=n % 20)


def a_moment(key: str, n: int) -> datetime:
    if key == 'expires_at':
        return datetime(2030, 1, 1, tzinfo=UTC)
    if key == 'ends_at':
        return datetime(2026, 3, 1, 11, tzinfo=UTC)
    return datetime(2026, 3, 1, 10, tzinfo=UTC)


def sample(model, column):
    """A value the column takes."""
    n, key = next(_numbers), column.key
    kind = bare(kinds_of(model)[key])
    pattern = column.info.get('field', {}).get('pattern')
    if pattern:
        return PATTERNS[pattern](n)
    if isinstance(column.type, JSON):
        return [] if get_origin(kind) is list else {}
    if isinstance(kind, type) and issubclass(kind, enum.Enum):
        # Each in turn: a choice is often part of what makes a row unique.
        members = list(kind)
        return members[next(_turns[kind]) % len(members)]
    if kind is str:
        return f'{key.replace("_", " ")} {n}'[:getattr(column.type, 'length', None) or 200]
    if kind is bool:
        return False
    if kind is int:
        # A number with no bounds is often one of a series — a task's, an invoice's — and two
        # rows of one series do not share it.
        return lowest(column) if column.info.get('field') else n
    if kind is Decimal:
        return Decimal('10.00')
    # By name: freezegun puts classes of its own in place of `date` and `datetime` in every module
    # loaded, this one too, and the class the annotation names is the real one.
    named = getattr(kind, '__name__', None) if getattr(kind, '__module__', None) == 'datetime' else None
    if named == 'date':
        return a_date(key, n)
    if named == 'datetime':
        return a_moment(key, n)
    if named == 'time':
        return time(17) if key == 'closes' else time(9)
    raise TypeError(f'no sample for {model.__name__}.{key}')


def needed(column) -> bool:
    return not (column.nullable or column.default is not None or column.primary_key or column.key == 'created_at')


async def make(session, model, org_id: int, user_id: int, /, **given):
    """A row of the table in the organisation, in the database. Every user it names is
    `user_id`, and every row above it it needs is made too."""
    values = {'organisation_id': org_id} if 'organisation_id' in model.__table__.columns else {}
    for column in model.__table__.columns:
        if column.key in given or column.key in values or not needed(column):
            continue
        if column.foreign_keys:
            target = next(iter(column.foreign_keys)).column.table
            if target.name == 'users':
                values[column.key] = user_id
            else:
                options = PARENTS.get(model.__tablename__, {}).get(target.name, {})
                above = await make(session, model_of(target), org_id, user_id, **options)
                values[column.key] = above.id
        else:
            values[column.key] = sample(model, column)
    row = model(**values | given)
    session.add(row)
    await session.commit()
    return row


# What a row above must be for a row below it to be made through the door at all: a payment is
# of an invoice that has gone out, a rating of a ticket that is solved.
PARENTS = {
    'payments': {'invoices': {'status': 'sent', 'total': Decimal('100.00')}},
    'ratings': {'tickets': {'status': 'solved'}},
}


def as_json(value):
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, enum.Enum):
        return value.value
    return value


async def body(session, made, org_id: int, user_id: int) -> dict:
    """What a request to make a row of the table sends: what it cannot do without. A row it
    points at is made in the organisation first; a user it names is `user_id`."""
    model, sent = made.model, {}
    parents = PARENTS.get(model.__tablename__, {})
    for name, field in made.create.model_fields.items():
        if not field.is_required():
            continue
        column = model.__table__.columns[name]
        if column.foreign_keys:
            target = next(iter(column.foreign_keys)).column.table
            if target.name == 'users':
                sent[name] = user_id
            else:
                sent[name] = (await make(session, model_of(target), org_id, user_id, **parents.get(target.name, {}))).id
        else:
            sent[name] = as_json(sample(model, column))
    return sent
