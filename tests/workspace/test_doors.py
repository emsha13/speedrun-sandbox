"""What is true of every table behind the usual doors, whatever the table: the same tests, run
over each table `resource` made doors for."""
import pytest

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select

from app.workspace.crud import INT4, MADE, bare, kinds_of, shapes_of
from app.workspace.models.orgs import MemberRole
from app.workspace.models.reports import AuditRecord
from tests.workspace.conftest import ROLES, WHO
from tests.workspace.factory import as_json, body, make, model_of

RANK = list(MemberRole)


def tables(*methods, where=bool):
    """The tables with all those doors, each as a parameter named by its path."""
    return pytest.mark.parametrize('made', [
        pytest.param(made, id=made.path.lstrip('/'))
        for made in MADE if set(methods) <= set(made.methods) and where(made)
    ])


def update_of(made):
    """One change a request may make to a row, and the value it leaves there."""
    model = made.model
    changeable = shapes_of(model, ())[2].model_fields
    update = [name for name in model.__table__.columns.keys() if name in changeable]
    by_kind = {}
    for name in update:
        column = model.__table__.columns[name]
        if column.foreign_keys:
            continue
        kind = bare(kinds_of(model)[name])
        if kind is str and not column.info.get('field', {}).get('pattern'):
            by_kind.setdefault('str', (name, 'Changed'))
        elif kind is int:
            field = column.info.get('field', {})
            by_kind.setdefault('int', (name, min(field.get('ge', 1) + 2, field.get('le', INT4))))
        elif kind is bool:
            by_kind.setdefault('bool', (name, True))
        elif kind is datetime:
            by_kind.setdefault('datetime', (name, '2031-01-01T00:00:00Z'))
    for kind in ('str', 'int', 'bool', 'datetime'):
        if kind in by_kind:
            return by_kind[kind]
    return None


def required(made) -> list[str]:
    return [name for name, field in made.create.model_fields.items() if field.is_required()]


def references(made, *, users: bool) -> list[str]:
    columns = made.model.__table__.columns
    return [
        name for name in made.create.model_fields
        if columns[name].foreign_keys
        and (next(iter(columns[name].foreign_keys)).column.table.name == 'users') == users
    ]


def writer(made) -> str:
    return WHO[made.write]


def reader(made) -> str:
    return WHO[made.read]


@pytest.fixture
def row_in(db_session, people):
    """`await row_in(org, made)`: a row of the table, made in the database — by `by`, whose name
    is on it as its author."""
    async def _row_in(organisation, made, by='member', **given):
        if made.author:
            given.setdefault(made.author, people[by].id)
        return await make(db_session, made.model, organisation.id, people[by].id, **given)
    return _row_in


@pytest.fixture
def new_body(db_session, people, org):
    async def _new_body(made, by=None):
        return await body(db_session, made, org.id, people[by or writer(made)].id)
    return _new_body


async def listed(client, as_, at, made, by=None, **params):
    response = await client.get(at(made.path), params=params, headers=await as_(by or reader(made)))
    assert response.status_code == 200, response.text
    return response.json()


@tables('create')
async def test_create(client, as_, at, org, people, made, new_body):
    sent = await new_body(made)
    response = await client.post(at(made.path), json=sent, headers=await as_(writer(made)))

    assert response.status_code == 201, response.text
    row = response.json()
    assert row | sent == row
    assert row['organisation_id'] == org.id
    if made.author:
        assert row[made.author] == people[writer(made)].id


@tables('create', 'read')
async def test_what_is_made_is_read(client, as_, at, made, new_body):
    made_row = (await client.post(at(made.path), json=await new_body(made), headers=await as_(writer(made)))).json()
    response = await client.get(at(f'{made.path}/{made_row["id"]}'), headers=await as_(reader(made)))

    assert response.status_code == 200
    assert response.json() == made_row


@tables('create', 'list')
async def test_what_is_made_is_listed(client, as_, at, made, new_body):
    made_row = (await client.post(at(made.path), json=await new_body(made), headers=await as_(writer(made)))).json()

    assert await listed(client, as_, at, made) == {'total': 1, 'items': [made_row]}


@tables('create', where=lambda made: required(made))
async def test_create_wants_what_is_required(client, as_, at, made):
    response = await client.post(at(made.path), json={}, headers=await as_(writer(made)))

    assert response.status_code == 422
    missing = {error['loc'][-1] for error in response.json()['detail'] if error['type'] == 'missing'}
    assert missing == set(required(made))


@tables('create')
async def test_create_takes_nothing_it_sets_itself(client, as_, at, made, new_body):
    sent = await new_body(made)
    for name, value in (('id', 7), ('organisation_id', 7), ('created_at', '2026-01-01T00:00:00Z'), ('nonsense', 1)):
        response = await client.post(at(made.path), json=sent | {name: value}, headers=await as_(writer(made)))
        assert response.status_code == 422, name


@tables('create', where=lambda made: references(made, users=False))
async def test_create_points_at_nothing_in_another_organisation(
    client, as_, at, made, new_body, db_session, people, other_org,
):
    name = references(made, users=False)[0]
    column = made.model.__table__.columns[name]
    elsewhere = await make(
        db_session, model_of(next(iter(column.foreign_keys)).column.table), other_org.id, people['outsider'].id,
    )
    sent = await new_body(made) | {name: elsewhere.id}
    response = await client.post(at(made.path), json=sent, headers=await as_(writer(made)))

    assert response.status_code == 400
    assert response.json()['detail'].startswith('no such ')


@tables('create', where=lambda made: references(made, users=True))
async def test_create_names_nobody_from_outside(client, as_, at, made, new_body, people):
    sent = await new_body(made) | {references(made, users=True)[0]: people['outsider'].id}
    response = await client.post(at(made.path), json=sent, headers=await as_(writer(made)))

    assert response.status_code == 400


@tables('create', where=lambda made: references(made, users=False) or references(made, users=True))
async def test_create_points_at_nothing_that_is_not(client, as_, at, made, new_body):
    names = references(made, users=False) or references(made, users=True)
    sent = await new_body(made) | {names[0]: INT4}
    response = await client.post(at(made.path), json=sent, headers=await as_(writer(made)))

    assert response.status_code == 400


def may(role: str, least: MemberRole) -> bool:
    return RANK.index(ROLES[role]) >= RANK.index(least)


@tables('create')
async def test_who_makes_a_row(client, as_, at, made, new_body):
    for role in ROLES:
        sent = await new_body(made, by=role)
        response = await client.post(at(made.path), json=sent, headers=await as_(role))

        if may(role, made.write):
            assert response.status_code == 201, (role, response.text)
        else:
            assert response.status_code == 403, role
            assert response.json() == {'detail': f'{made.write}s only'}


@tables('list')
async def test_who_reads_the_list(client, as_, at, made):
    for role in ROLES:
        response = await client.get(at(made.path), headers=await as_(role))
        assert response.status_code == (200 if may(role, made.read) else 403), role


@tables('list')
async def test_the_list_is_for_members_only(client, as_, at, org, made):
    outsider = await client.get(at(made.path), headers=await as_('outsider'))
    stranger = await client.get(at(made.path))

    assert (outsider.status_code, outsider.json()) == (404, {'detail': 'no such organisation'})
    assert stranger.status_code == 401


@tables('list')
async def test_an_organisation_that_is_not(client, as_, made, org):
    for org_id in (org.id + 1000, INT4, INT4 + 1):
        response = await client.get(f'/orgs/{org_id}{made.path}', headers=await as_('owner'))
        assert response.status_code == 404


@tables('list')
async def test_the_list_holds_this_organisation_only(client, as_, at, org, other_org, made, row_in):
    ours = await row_in(org, made)
    await row_in(other_org, made, by='outsider')

    page = await listed(client, as_, at, made)
    assert [item['id'] for item in page['items']] == [ours.id]


@tables('list')
async def test_the_list_in_pages(client, as_, at, org, made, row_in):
    rows = [await row_in(org, made, by=name) for name in ('member', 'peer', 'admin')]

    first = await listed(client, as_, at, made, limit=2)
    rest = await listed(client, as_, at, made, limit=2, offset=2)
    assert (first['total'], rest['total']) == (3, 3)
    assert [item['id'] for item in first['items'] + rest['items']] == [row.id for row in rows]


@tables('list')
async def test_the_list_backwards(client, as_, at, org, made, row_in):
    rows = [await row_in(org, made, by=name) for name in ('member', 'peer', 'admin')]

    page = await listed(client, as_, at, made, sort='id', order='desc')
    assert [item['id'] for item in page['items']] == [row.id for row in reversed(rows)]


@tables('list')
async def test_the_list_malformed(client, as_, at, org, made):
    malformed = [{'sort': 'nonsense'}, {'order': 'up'}, {'limit': 0}, {'limit': 101}, {'offset': -1}, {'limit': 'ten'}]
    if made.search:
        malformed += [{'search': ''}, {'search': 'x' * 101}]
    for params in malformed:
        response = await client.get(at(made.path), params=params, headers=await as_(reader(made)))
        assert response.status_code == 422, params


@tables('list', where=lambda made: made.search)
async def test_the_list_searched(client, as_, at, org, made, row_in):
    column = made.search[0]
    wanted = await row_in(org, made, **{column: 'Zebra 100% sure'})
    await row_in(org, made, by='peer', **{column: 'Zebu'})

    for term, expected in (('zebra', [wanted.id]), ('ZEBRA', [wanted.id]), ('100%', [wanted.id]), ('0%s', []),
                           ('ze', None), ('quagga', [])):
        page = await listed(client, as_, at, made, search=term)
        found = [item['id'] for item in page['items']]
        assert found == expected if expected is not None else len(found) == 2, term


@tables('read')
async def test_read_a_row_that_is_not(client, as_, at, org, made):
    for row_id, expected in (('999999', 404), ('0', 422), ('-1', 422), (str(INT4 + 1), 422), ('one', 422)):
        response = await client.get(at(f'{made.path}/{row_id}'), headers=await as_(reader(made)))
        assert response.status_code == expected, row_id


def doors_to_a_row(made) -> list[str]:
    return [method for method, door in (('GET', 'read'), ('PATCH', 'update'), ('DELETE', 'delete'))
            if door in made.methods]


@tables(where=doors_to_a_row)
async def test_another_organisations_row_is_not_there(client, as_, at, org, other_org, made, row_in):
    theirs = await row_in(other_org, made, by='outsider')
    for method in doors_to_a_row(made):
        response = await client.request(method, at(f'{made.path}/{theirs.id}'), json={}, headers=await as_('owner'))
        assert response.status_code == 404, method


@tables('update', where=update_of)
async def test_update(client, as_, at, org, made, row_in, db_session):
    row = await row_in(org, made)
    name, value = update_of(made)
    response = await client.patch(
        at(f'{made.path}/{row.id}'), json={name: value}, headers=await as_(writer(made)),
    )

    assert response.status_code == 200, response.text
    assert response.json()[name] == value
    await db_session.refresh(row)
    assert as_json(getattr(row, name)) == value


@tables('update')
async def test_update_with_nothing(client, as_, at, org, made, row_in):
    row = await row_in(org, made)
    response = await client.patch(at(f'{made.path}/{row.id}'), json={}, headers=await as_(writer(made)))

    assert response.status_code == 200
    assert response.json()['id'] == row.id


@tables('update')
async def test_update_changes_nothing_it_sets_itself(client, as_, at, org, made, row_in):
    row = await row_in(org, made)
    for name in ('id', 'organisation_id', 'created_at', 'nonsense'):
        response = await client.patch(at(f'{made.path}/{row.id}'), json={name: 1}, headers=await as_(writer(made)))
        assert response.status_code == 422, name


@tables('update')
async def test_who_changes_a_row(client, as_, at, org, made, row_in):
    """Whoever may write changes a row — of a table of one's own rows, their own or as an admin."""
    for role in ROLES:
        row = await row_in(org, made, by=role)
        response = await client.patch(at(f'{made.path}/{row.id}'), json={}, headers=await as_(role))
        assert response.status_code == (200 if may(role, made.write) else 403), role


@tables('delete')
async def test_delete(client, as_, at, org, made, row_in):
    row = await row_in(org, made)
    response = await client.delete(at(f'{made.path}/{row.id}'), headers=await as_(writer(made)))

    assert response.status_code == 204
    if 'list' in made.methods:
        assert (await listed(client, as_, at, made))['total'] == 0
    again = await client.delete(at(f'{made.path}/{row.id}'), headers=await as_(writer(made)))
    assert again.status_code == 404


@tables('delete')
async def test_delete_leaves_the_rest(client, as_, at, org, made, row_in):
    gone, kept = await row_in(org, made), await row_in(org, made, by='peer')
    await client.delete(at(f'{made.path}/{gone.id}'), headers=await as_(writer(made)))

    if 'list' in made.methods:
        assert [item['id'] for item in (await listed(client, as_, at, made))['items']] == [kept.id]


@tables('delete')
async def test_who_deletes_a_row(client, as_, at, org, made, row_in):
    for role in ROLES:
        row = await row_in(org, made, by=role)
        response = await client.delete(at(f'{made.path}/{row.id}'), headers=await as_(role))
        assert response.status_code == (204 if may(role, made.write) else 403), role


def owned_doors(made):
    return [method for method, door in (('PATCH', 'update'), ('DELETE', 'delete')) if door in made.methods]


@pytest.mark.parametrize('made, method', [
    pytest.param(made, method, id=f'{made.path.lstrip("/")}-{method}')
    for made in MADE if made.own for method in owned_doors(made)
])
async def test_a_row_of_ones_own(client, as_, at, org, made, method, row_in):
    """Its author changes it, and so do admins; another member does not."""
    for who, allowed in (('peer', False), ('member', True), ('admin', True), ('owner', True)):
        row = await row_in(org, made, by='member')
        response = await client.request(method, at(f'{made.path}/{row.id}'), json={}, headers=await as_(who))
        if allowed:
            assert response.status_code in (200, 204), who
        else:
            assert response.status_code == 403, who
            assert response.json()['detail'].startswith('not your ')


@tables('create', where=lambda made: made.audited)
async def test_a_new_row_is_on_the_record(client, as_, at, org, people, made, new_body, db_session):
    row = (await client.post(at(made.path), json=await new_body(made), headers=await as_(writer(made)))).json()

    records = (await db_session.scalars(select(AuditRecord))).all()
    assert [(r.actor_id, r.action, r.subject, r.subject_id) for r in records] == [
        (people[writer(made)].id, 'create', made.model.__tablename__, row['id']),
    ]


@tables('delete', where=lambda made: made.audited)
async def test_a_deleted_row_is_on_the_record(client, as_, at, org, made, row_in, db_session):
    row = await row_in(org, made)
    await client.delete(at(f'{made.path}/{row.id}'), headers=await as_(writer(made)))

    records = (await db_session.scalars(select(AuditRecord))).all()
    assert [(r.action, r.subject_id) for r in records] == [('delete', row.id)]


@tables('read', where=lambda made: any(column.info.get('hidden') for column in made.model.__table__.columns))
async def test_a_row_shows_no_secret(client, as_, at, org, made, row_in):
    row = await row_in(org, made)
    shown = (await client.get(at(f'{made.path}/{row.id}'), headers=await as_(reader(made)))).json()

    hidden = {column.key for column in made.model.__table__.columns if column.info.get('hidden')}
    assert not hidden & set(shown)


@tables('read', where=lambda made: any(
    bare(kinds_of(made.model)[name]) is Decimal for name in made.model.__table__.columns.keys()
))
async def test_money_comes_as_text(client, as_, at, org, made, row_in):
    row = await row_in(org, made)
    shown = (await client.get(at(f'{made.path}/{row.id}'), headers=await as_(reader(made)))).json()

    amounts = [name for name in made.model.__table__.columns.keys() if bare(kinds_of(made.model)[name]) is Decimal]
    assert all(isinstance(shown[name], str) or shown[name] is None for name in amounts)
