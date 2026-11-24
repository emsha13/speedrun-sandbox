"""One table of an organisation behind the usual doors: list, read, create, update, delete.

    resource(router, Label, search=('name',))

What a request may send and what an answer shows are read off the model — its annotations, its
columns and their `info` (see `base.py`) — so a model is described once. A table whose rows have
rules of their own gives them as `check`, called before a row is saved, and `gone`, after one is
deleted; either refuses by raising.
"""
import enum
import inspect
import re
import types

from decimal import Decimal
from types import SimpleNamespace
from typing import Annotated, Any, Literal, Optional, get_args, get_type_hints

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import ConfigDict, Field, create_model
from sqlalchemy import JSON, Text, func, or_, select
from sqlalchemy.exc import IntegrityError

from app.models import now
from app.routers.users import escaped
from app.workspace.access import Context, at_least
from app.workspace.models.orgs import MemberRole, Membership
from app.workspace.models.reports import AuditRecord

EVERYTHING = 'list read create update delete'
# The largest number a Postgres `integer` holds. A request is refused for a number beyond it
# rather than passed on for the database to choke on.
INT4 = 2 ** 31 - 1
LONGEST_TEXT = 50_000
MANAGED = {'id', 'organisation_id', 'created_at'}
RowId = Annotated[int, Path(ge=1, le=INT4)]


def label_of(model) -> str:
    """`TaskComment` → `task comment`."""
    return re.sub(r'(?<!^)(?=[A-Z])', ' ', model.__name__).lower()


def kinds_of(model) -> dict[str, Any]:
    """What each column holds, as its annotation says it: `Mapped[str | None]` → `str | None`."""
    hints = get_type_hints(model)
    return {column.key: get_args(hints[column.key])[0] for column in model.__table__.columns}


def bare(kind):
    """The type without its `| None`."""
    if isinstance(kind, types.UnionType):
        return next(part for part in get_args(kind) if part is not type(None))
    return kind


def accepted(column, kind):
    """The type a request may give the column: the column's own, within what it can hold."""
    limits: dict[str, Any] = {}
    if kind is str:
        limits['max_length'] = getattr(column.type, 'length', None) or LONGEST_TEXT
        if not column.nullable and column.default is None:
            limits['min_length'] = 1
    elif kind is int:
        limits |= {'ge': 1 if column.foreign_keys else -INT4, 'le': INT4}
    elif kind is Decimal:
        limits |= {'max_digits': column.type.precision, 'decimal_places': column.type.scale}
    limits |= column.info.get('field', {})
    return Annotated[kind, Field(**limits)] if limits else kind


def is_choice(kind) -> bool:
    return isinstance(kind, type) and issubclass(kind, enum.Enum)


def shapes_of(model, search: tuple[str, ...]):
    """The four shapes of a table: a row shown, a row to make, the changes to one, and what a
    list of them may be asked for."""
    shown, made, changed, filters, sortable = {}, {}, {}, {}, []
    kinds = kinds_of(model)
    for column in model.__table__.columns:
        name, kind, info = column.key, kinds[column.key], column.info
        plain = bare(kind)
        if not info.get('hidden'):
            shown[name] = (kind, ...)
            if not isinstance(column.type, (JSON, Text)):
                sortable.append(name)
            if column.foreign_keys:
                filters[name] = (Optional[int], Query(None, ge=1, le=INT4))
            elif plain is bool or is_choice(plain):
                filters[name] = (Optional[plain], Query(None))
        if name in MANAGED or info.get('managed'):
            continue
        field = accepted(column, plain)
        if column.nullable:
            entry = (Optional[field], None)
        else:
            # Not required when the column has a default — and still never null: the default
            # here is only what an absent value looks like, and absent values are left out.
            entry = (field, ... if column.default is None else None)
        made[name] = entry
        if not info.get('fixed'):
            changed[name] = (entry[0], None)
    if search:
        filters['search'] = (Optional[str], Query(None, min_length=1, max_length=100))
    strict = ConfigDict(extra='forbid')
    name = model.__name__
    return (
        create_model(f'{name}Out', __config__=ConfigDict(from_attributes=True), **shown),
        create_model(f'{name}Create', __config__=strict, **made),
        create_model(f'{name}Update', __config__=strict, **changed),
        query_of(filters | {
            'sort': (Literal[*sortable], Query('id')), 'order': (Literal['asc', 'desc'], Query('asc')),
            'limit': (int, Query(20, ge=1, le=100)), 'offset': (int, Query(0, ge=0)),
        }),
    )


def query_of(parameters: dict):
    """A dependency that takes the parameters from the query string and hands them on together.

    Plain parameters and not a pydantic model under `Query()`: FastAPI keeps the fields of such
    models in an `lru_cache` of 128, and with more models than that the cache drops the fields
    the schema at `/openapi.json` was built from, and building it fails."""
    def query(**given):
        return SimpleNamespace(**given)
    query.__signature__ = inspect.Signature([
        inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, annotation=kind, default=default)
        for name, (kind, default) in parameters.items()
    ])
    return query


def out_of(model):
    """The shape a row is shown in, for the doors that are written by hand."""
    return shapes_of(model, ())[0]


def page_of(shape):
    return create_model(f'{shape.__name__.removesuffix("Out")}Page', total=(int, ...), items=(list[shape], ...))


def is_duplicate(error: IntegrityError) -> bool:
    return getattr(error.orig, 'sqlstate', None) == '23505'


async def check_references(context: Context, model, values: dict) -> None:
    """Every row a request points at is in the caller's organisation, and every user is a member
    of it. The foreign keys themselves would let any row of any organisation through."""
    for column in model.__table__.columns:
        value = values.get(column.key)
        if value is None or not column.foreign_keys:
            continue
        target = next(iter(column.foreign_keys)).column.table
        if target.name == 'users':
            found = select(Membership.id).where(
                Membership.organisation_id == context.org_id, Membership.user_id == value
            )
        else:
            found = select(target.c.id).where(target.c.id == value, target.c.organisation_id == context.org_id)
        if await context.session.scalar(found) is None:
            what = column.key.removesuffix('_id').replace('_', ' ')
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f'no such {what}')


async def find(context: Context, model, row_id: int):
    """The row of the caller's organisation with that id. Another organisation's row is as absent
    as one that never was."""
    row = await context.session.get(model, row_id)
    if row is None or row.organisation_id != context.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f'no such {label_of(model)}')
    return row


async def page(context: Context, model, shape, query, search: tuple[str, ...] = (), *where):
    """The rows of the organisation the query asks for, and how many there are in all."""
    found = select(model).where(model.organisation_id == context.org_id, *where)
    for name, value in vars(query).items():
        if value is not None and name not in ('search', 'sort', 'order', 'limit', 'offset'):
            found = found.where(getattr(model, name) == value)
    if getattr(query, 'search', None):
        pattern = f'%{escaped(query.search)}%'
        found = found.where(or_(*(getattr(model, name).ilike(pattern) for name in search)))
    total = await context.session.scalar(select(func.count()).select_from(found.subquery()))
    column = getattr(model, query.sort)
    # The id last: rows equal in what they are sorted by keep one order from page to page.
    ordered = found.order_by(column.desc() if query.order == 'desc' else column.asc(), model.id)
    rows = await context.session.scalars(ordered.limit(query.limit).offset(query.offset))
    return shape(total=total, items=rows.all())


def resource(
    router: APIRouter, model, *, methods: str = EVERYTHING, read: MemberRole = MemberRole.GUEST,
    write: MemberRole = MemberRole.MEMBER, search: tuple[str, ...] = (), author: str | None = None,
    own: bool = False, private: bool = False, check=None, gone=None, audited: bool = False,
):
    """The doors of one table.

    methods    which of the five there are
    read       the least a member must be to read; `write`, to change
    search     the columns `?search=` looks in
    author     the column that gets the id of whoever made the row
    own        only the author or an admin changes or deletes a row
    private    and nobody but the author sees it at all
    check      `async (context, row, old)` before a row is saved; `old` is None for a new row,
               and for a changed one what the changed columns held before
    gone       `async (context, row)` after a row is deleted and before that is committed
    audited    every change is written to the audit record
    """
    name, label = model.__tablename__, label_of(model)
    path = '/' + name.replace('_', '-')
    Out, Create, Update, ListQuery = shapes_of(model, search)
    Page = page_of(Out)
    Reader = Annotated[Context, Depends(at_least(read))]
    Writer = Annotated[Context, Depends(at_least(write))]
    methods = methods.split()

    async def the_row(context: Context, row_id: int):
        row = await find(context, model, row_id)
        if private and getattr(row, author) != context.user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f'no such {label}')
        return row

    def may_change(context: Context, row) -> None:
        if own and getattr(row, author) != context.user.id and not context.is_at_least(MemberRole.ADMIN):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f'not your {label}')

    async def settle(context: Context, row, action: str, old: dict | None = None) -> None:
        """Runs the table's own rule, writes, and commits — or refuses, and nothing is kept."""
        session = context.session
        try:
            if action == 'delete':
                await session.delete(row)
                await session.flush()
                if gone:
                    await gone(context, row)
            else:
                if check:
                    await check(context, row, old)
                session.add(row)
                await session.flush()
        except IntegrityError as error:
            if is_duplicate(error):
                raise HTTPException(status.HTTP_409_CONFLICT, f'such a {label} is there already') from None
            raise
        if audited:
            session.add(AuditRecord(
                organisation_id=context.org_id, actor_id=context.user.id, action=action, subject=name,
                subject_id=row.id,
            ))
        await session.commit()

    if 'list' in methods:
        @router.get(path, response_model=Page, name=f'list_{name}')
        async def list_rows(query: Annotated[SimpleNamespace, Depends(ListQuery)], context: Reader):
            mine = [getattr(model, author) == context.user.id] if private else []
            return await page(context, model, Page, query, search, *mine)

    if 'create' in methods:
        @router.post(path, response_model=Out, status_code=status.HTTP_201_CREATED, name=f'create_{name}')
        async def create_row(data: Create, context: Writer):
            values = data.model_dump(exclude_unset=True)
            await check_references(context, model, values)
            row = model(organisation_id=context.org_id, **values)
            if author:
                setattr(row, author, context.user.id)
            await settle(context, row, 'create')
            return row

    if 'read' in methods:
        @router.get(f'{path}/{{row_id}}', response_model=Out, name=f'read_{name}')
        async def read_row(row_id: RowId, context: Reader):
            return await the_row(context, row_id)

    if 'update' in methods:
        @router.patch(f'{path}/{{row_id}}', response_model=Out, name=f'update_{name}')
        async def update_row(row_id: RowId, data: Update, context: Writer):
            row = await the_row(context, row_id)
            may_change(context, row)
            changes = data.model_dump(exclude_unset=True)
            await check_references(context, model, changes)
            old = {key: getattr(row, key) for key in changes}
            for key, value in changes.items():
                setattr(row, key, value)
            if changes and hasattr(model, 'updated_at'):
                row.updated_at = now()
            await settle(context, row, 'update', old)
            return row

    if 'delete' in methods:
        @router.delete(f'{path}/{{row_id}}', status_code=status.HTTP_204_NO_CONTENT, name=f'delete_{name}')
        async def delete_row(row_id: RowId, context: Writer):
            row = await the_row(context, row_id)
            may_change(context, row)
            await settle(context, row, 'delete')


def mark(router: APIRouter, model, link, column: str, word: str):
    """A member's own mark on a row — a star, a vote, a watch: `PUT` puts it, `DELETE` takes it
    off, either as many times as one likes, and both say how many marks the row has now."""
    path = f'/{model.__tablename__.replace("_", "-")}/{{row_id}}/{word}'
    Anyone = Annotated[Context, Depends(at_least(MemberRole.GUEST))]

    async def answer(context: Context, row_id: int, wanted: bool) -> dict:
        await find(context, model, row_id)
        session = context.session
        mine = await session.scalar(
            select(link).where(getattr(link, column) == row_id, link.user_id == context.user.id)
        )
        if wanted and mine is None:
            session.add(link(organisation_id=context.org_id, user_id=context.user.id, **{column: row_id}))
        elif not wanted and mine is not None:
            await session.delete(mine)
        await session.commit()
        count = await session.scalar(select(func.count()).select_from(link).where(getattr(link, column) == row_id))
        return {'count': count}

    @router.put(path, name=f'put_{word}_on_{model.__tablename__}')
    async def put_mark(row_id: RowId, context: Anyone):
        return await answer(context, row_id, True)

    @router.delete(path, name=f'take_{word}_off_{model.__tablename__}')
    async def take_mark_off(row_id: RowId, context: Anyone):
        return await answer(context, row_id, False)
