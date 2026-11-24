"""An organisation: who makes it, who is in it and as what, how somebody new gets in."""
import pytest

from datetime import date, timedelta

from sqlalchemy import select

from app import security
from app.models import now
from app.workspace.models.orgs import (
    Announcement, Decision, Invitation, Membership, OrgSettings, Plan, Team, TimeOffBalance, TimeOffRequest,
)
from tests.utils import bearer, mailed_code, sign_in


async def test_create_organisation(client, as_, people, db_session):
    response = await client.post('/orgs', json={'name': 'Initech', 'slug': 'initech'}, headers=await as_('member'))

    assert response.status_code == 201
    created = response.json()
    assert (created['name'], created['slug'], created['plan']) == ('Initech', 'initech', 'free')
    membership = await db_session.scalar(select(Membership).where(Membership.organisation_id == created['id']))
    assert (membership.user_id, membership.role) == (people['member'].id, 'owner')
    assert await db_session.scalar(select(OrgSettings).where(OrgSettings.organisation_id == created['id']))


async def test_a_slug_is_taken_once(client, as_, org):
    response = await client.post('/orgs', json={'name': 'Acme Two', 'slug': 'acme'}, headers=await as_('member'))

    assert (response.status_code, response.json()) == (409, {'detail': 'slug is taken'})


@pytest.mark.parametrize('slug', ['', 'a', 'Acme', 'acme corp', '-acme', 'acme-', 'a--b', 'x' * 41])
async def test_a_malformed_slug(client, as_, people, slug):
    response = await client.post('/orgs', json={'name': 'X', 'slug': slug}, headers=await as_('member'))

    assert response.status_code == 422


async def test_my_organisations(client, as_, org, other_org):
    mine = (await client.get('/orgs', headers=await as_('guest'))).json()
    theirs = (await client.get('/orgs', headers=await as_('outsider'))).json()

    assert [row['slug'] for row in mine] == ['acme']
    assert [row['slug'] for row in theirs] == ['globex']


async def test_organisations_want_a_sign_in(client):
    assert (await client.get('/orgs')).status_code == 401
    assert (await client.post('/orgs', json={'name': 'X', 'slug': 'xx'})).status_code == 401


@pytest.mark.parametrize('role', ['owner', 'admin', 'member', 'peer', 'guest'])
async def test_everybody_inside_reads_the_organisation(client, as_, at, role):
    response = await client.get(at(''), headers=await as_(role))

    assert (response.status_code, response.json()['slug']) == (200, 'acme')


@pytest.mark.parametrize('role, expected', [('owner', 200), ('admin', 200), ('member', 403), ('guest', 403)])
async def test_who_renames_the_organisation(client, as_, at, role, expected):
    response = await client.patch(at(''), json={'name': 'Acme Ltd'}, headers=await as_(role))

    assert response.status_code == expected


@pytest.mark.parametrize('role, expected', [('owner', 200), ('admin', 403)])
async def test_the_plan_is_for_owners(client, as_, at, role, expected):
    response = await client.patch(at(''), json={'plan': 'business'}, headers=await as_(role))

    assert response.status_code == expected


@pytest.mark.parametrize('body', [{'name': ''}, {'plan': 'gold'}, {'slug': 'other'}, {'name': 'x' * 81}])
async def test_update_organisation_malformed(client, as_, at, body):
    assert (await client.patch(at(''), json=body, headers=await as_('owner'))).status_code == 422


@pytest.mark.parametrize('role, expected', [('owner', 204), ('admin', 403), ('member', 403)])
async def test_who_deletes_the_organisation(client, as_, at, role, expected):
    assert (await client.delete(at(''), headers=await as_(role))).status_code == expected


async def test_an_organisation_goes_with_everything_in_it(client, as_, at, org, new, db_session):
    await new(Team)
    await client.delete(at(''), headers=await as_('owner'))

    assert (await db_session.scalars(select(Team))).all() == []
    assert (await db_session.scalars(select(Membership))).all() == []
    assert (await client.get(at(''), headers=await as_('owner'))).status_code == 404


async def test_settings(client, as_, at):
    changed = await client.patch(at('/settings'), json={'week_starts_on': 0}, headers=await as_('admin'))
    read = await client.get(at('/settings'), headers=await as_('guest'))

    assert changed.status_code == 200
    assert read.json()['week_starts_on'] == 0
    assert read.json()['updated_at'] is not None


@pytest.mark.parametrize('body', [{'week_starts_on': 7}, {'session_hours': 0}, {'nonsense': 1}, {'id': 3}])
async def test_settings_malformed(client, as_, at, body):
    assert (await client.patch(at('/settings'), json=body, headers=await as_('admin'))).status_code == 422


async def test_settings_are_for_admins(client, as_, at):
    assert (await client.patch(at('/settings'), json={}, headers=await as_('member'))).status_code == 403


async def test_members(client, as_, at, people):
    members = (await client.get(at('/members'), headers=await as_('guest'))).json()

    assert [(row['email'], row['role']) for row in members] == [
        ('owner@example.com', 'owner'), ('admin@example.com', 'admin'), ('member@example.com', 'member'),
        ('peer@example.com', 'member'), ('guest@example.com', 'guest'),
    ]


async def test_an_admin_promotes_a_member(client, as_, at, people):
    response = await client.patch(
        at(f'/members/{people["member"].id}'), json={'role': 'admin', 'title': 'Lead'}, headers=await as_('admin'),
    )

    assert response.status_code == 200
    assert (response.json()['role'], response.json()['title']) == ('admin', 'Lead')


@pytest.mark.parametrize('target, role', [('member', 'owner'), ('owner', 'admin')])
async def test_an_admin_neither_makes_nor_unmakes_an_owner(client, as_, at, people, target, role):
    response = await client.patch(at(f'/members/{people[target].id}'), json={'role': role}, headers=await as_('admin'))

    assert (response.status_code, response.json()) == (403, {'detail': 'owners only'})


async def test_an_owner_makes_another(client, as_, at, people):
    response = await client.patch(
        at(f'/members/{people["admin"].id}'), json={'role': 'owner'}, headers=await as_('owner'),
    )

    assert response.json()['role'] == 'owner'


async def test_the_last_owner_stays(client, as_, at, people):
    response = await client.patch(
        at(f'/members/{people["owner"].id}'), json={'role': 'admin'}, headers=await as_('owner'),
    )

    assert (response.status_code, response.json()) == (409, {'detail': 'an organisation keeps an owner'})


async def test_one_of_two_owners_steps_down(client, as_, at, people):
    await client.patch(at(f'/members/{people["admin"].id}'), json={'role': 'owner'}, headers=await as_('owner'))
    response = await client.patch(
        at(f'/members/{people["owner"].id}'), json={'role': 'member'}, headers=await as_('owner'),
    )

    assert response.status_code == 200


@pytest.mark.parametrize('role', ['member', 'guest'])
async def test_roles_are_for_admins(client, as_, at, people, role):
    response = await client.patch(at(f'/members/{people["peer"].id}'), json={'role': 'admin'}, headers=await as_(role))

    assert response.status_code == 403


async def test_a_member_that_is_not(client, as_, at, people):
    for user in (people['outsider'].id, 999999):
        assert (await client.patch(at(f'/members/{user}'), json={}, headers=await as_('admin'))).status_code == 404


@pytest.mark.parametrize('role', ['member', 'guest', 'admin'])
async def test_anybody_leaves(client, as_, at, people, role):
    assert (await client.delete(at(f'/members/{people[role].id}'), headers=await as_(role))).status_code == 204
    assert (await client.get(at(''), headers=await as_(role))).status_code == 404


async def test_the_last_owner_does_not_leave(client, as_, at, people):
    response = await client.delete(at(f'/members/{people["owner"].id}'), headers=await as_('owner'))

    assert response.status_code == 409


@pytest.mark.parametrize('remover, removed, expected', [
    ('admin', 'member', 204), ('admin', 'owner', 403), ('owner', 'admin', 204), ('member', 'peer', 403),
    ('guest', 'member', 403),
])
async def test_who_removes_whom(client, as_, at, people, remover, removed, expected):
    response = await client.delete(at(f'/members/{people[removed].id}'), headers=await as_(remover))

    assert response.status_code == expected


async def test_invite(client, as_, at, org, outbox, db_session):
    response = await client.post(
        at('/invitations'), json={'email': 'New@Example.com', 'role': 'guest'}, headers=await as_('admin'),
    )

    assert response.status_code == 201
    assert (response.json()['email'], response.json()['role']) == ('new@example.com', 'guest')
    assert 'token_digest' not in response.json()
    assert outbox.call_args.args[:2] == ('new@example.com', 'Join Acme')
    invitation = await db_session.get(Invitation, response.json()['id'])
    assert invitation.token_digest == security.digest(mailed_code(outbox))


async def test_nobody_is_invited_as_an_owner(client, as_, at):
    response = await client.post(at('/invitations'), json={'email': 'x@example.com', 'role': 'owner'},
                                 headers=await as_('owner'))

    assert response.status_code == 400


async def test_a_member_is_not_invited(client, as_, at):
    response = await client.post(at('/invitations'), json={'email': 'peer@example.com'}, headers=await as_('admin'))

    assert (response.status_code, response.json()) == (409, {'detail': 'already a member'})


async def test_invited_once(client, as_, at):
    for expected in (201, 409):
        response = await client.post(at('/invitations'), json={'email': 'x@example.com'}, headers=await as_('admin'))
        assert response.status_code == expected


async def test_invited_again_once_the_first_has_expired(client, as_, at, db_session):
    first = (await client.post(at('/invitations'), json={'email': 'x@example.com'}, headers=await as_('admin'))).json()
    invitation = await db_session.get(Invitation, first['id'])
    invitation.expires_at = now() - timedelta(seconds=1)
    await db_session.commit()

    response = await client.post(at('/invitations'), json={'email': 'x@example.com'}, headers=await as_('admin'))
    assert response.status_code == 201


async def test_no_seats_no_invitation(client, as_, at, org, db_session):
    org.plan = Plan.FREE
    await db_session.commit()
    response = await client.post(at('/invitations'), json={'email': 'x@example.com'}, headers=await as_('admin'))

    assert (response.status_code, response.json()) == (409, {'detail': 'the plan has no seats left'})


@pytest.mark.parametrize('role', ['member', 'guest'])
async def test_invitations_are_for_admins(client, as_, at, role):
    response = await client.post(at('/invitations'), json={'email': 'x@example.com'}, headers=await as_(role))

    assert response.status_code == 403


async def invited(client, as_, at, outbox, email, role='member') -> str:
    await client.post(at('/invitations'), json={'email': email, 'role': role}, headers=await as_('admin'))
    return mailed_code(outbox)


@pytest.fixture
async def newcomer(create_user, password):
    return await create_user('newcomer@example.com', password)


@pytest.fixture
async def newcomer_auth(client, newcomer, password):
    return bearer((await sign_in(client, newcomer.email, password))['access_token'])


async def test_accept(client, as_, at, org, outbox, newcomer, newcomer_auth):
    token = await invited(client, as_, at, outbox, newcomer.email, role='guest')
    response = await client.post('/invitations/accept', json={'token': token}, headers=newcomer_auth)

    assert (response.status_code, response.json()['slug']) == (200, 'acme')
    members = (await client.get(at('/members'), headers=newcomer_auth)).json()
    assert members[-1]['email'] == newcomer.email
    assert members[-1]['role'] == 'guest'


async def test_accept_once(client, as_, at, outbox, newcomer, newcomer_auth):
    token = await invited(client, as_, at, outbox, newcomer.email)
    for expected in (200, 400):
        response = await client.post('/invitations/accept', json={'token': token}, headers=newcomer_auth)
        assert response.status_code == expected


async def test_accept_a_token_that_is_not(client, newcomer_auth):
    response = await client.post('/invitations/accept', json={'token': 'nonsense'}, headers=newcomer_auth)

    assert (response.status_code, response.json()) == (400, {'detail': 'invalid invitation'})


async def test_accept_too_late(client, as_, at, outbox, newcomer, newcomer_auth, db_session):
    token = await invited(client, as_, at, outbox, newcomer.email)
    invitation = await db_session.scalar(select(Invitation))
    invitation.expires_at = now() - timedelta(seconds=1)
    await db_session.commit()
    response = await client.post('/invitations/accept', json={'token': token}, headers=newcomer_auth)

    assert (response.status_code, response.json()) == (400, {'detail': 'invitation expired'})


async def test_accept_somebody_elses(client, as_, at, outbox, newcomer_auth):
    token = await invited(client, as_, at, outbox, 'somebody@example.com')
    response = await client.post('/invitations/accept', json={'token': token}, headers=newcomer_auth)

    assert response.status_code == 403


async def test_accept_when_the_seats_have_gone(client, as_, at, org, outbox, newcomer, newcomer_auth, db_session):
    token = await invited(client, as_, at, outbox, newcomer.email)
    org.plan = Plan.FREE
    await db_session.commit()
    response = await client.post('/invitations/accept', json={'token': token}, headers=newcomer_auth)

    assert response.status_code == 409


async def test_accept_signed_out(client):
    assert (await client.post('/invitations/accept', json={'token': 'x'})).status_code == 401


async def test_an_announcement_read(client, as_, at, new, people):
    announcement = await new(Announcement)
    for name in ('member', 'member', 'guest'):
        response = await client.post(at(f'/announcements/{announcement.id}/read'), headers=await as_(name))
        assert response.status_code == 204
    readers = await client.get(at(f'/announcements/{announcement.id}/readers'), headers=await as_('admin'))

    assert readers.json() == [people['member'].id, people['guest'].id]


async def test_who_read_it_is_for_admins(client, as_, at, new):
    announcement = await new(Announcement)

    assert (await client.get(at(f'/announcements/{announcement.id}/readers'),
                             headers=await as_('member'))).status_code == 403


async def test_an_announcement_of_another_organisation(client, as_, at, new, other_org):
    theirs = await new(Announcement, by='outsider', organisation=other_org)

    assert (await client.post(at(f'/announcements/{theirs.id}/read'), headers=await as_('member'))).status_code == 404


@pytest.fixture
async def time_off(new, people):
    """Member asks for five days of vacation, and has twenty this year."""
    await new(TimeOffBalance, user_id=people['member'].id, kind='vacation', year=2026, days_allowed=20)
    return await new(
        TimeOffRequest, user_id=people['member'].id, kind='vacation', starts_on=date(2026, 7, 6),
        ends_on=date(2026, 7, 10),
    )


async def decide(client, as_, at, request, approve, by='admin'):
    return await client.post(at(f'/time-off-requests/{request.id}/decide'), json={'approve': approve},
                             headers=await as_(by))


async def test_time_off_approved(client, as_, at, time_off, people, db_session):
    response = await decide(client, as_, at, time_off, True)

    assert response.status_code == 200
    assert (response.json()['status'], response.json()['decided_by_id']) == ('approved', people['admin'].id)
    balance = await db_session.scalar(select(TimeOffBalance))
    await db_session.refresh(balance)
    assert balance.days_used == 5


async def test_time_off_rejected_costs_nothing(client, as_, at, time_off, db_session):
    response = await decide(client, as_, at, time_off, False)

    assert response.json()['status'] == 'rejected'
    balance = await db_session.scalar(select(TimeOffBalance))
    await db_session.refresh(balance)
    assert balance.days_used == 0


async def test_time_off_decided_once(client, as_, at, time_off):
    await decide(client, as_, at, time_off, True)

    assert (await decide(client, as_, at, time_off, False)).status_code == 409


async def test_time_off_beyond_the_balance(client, as_, at, time_off, db_session):
    balance = await db_session.scalar(select(TimeOffBalance))
    balance.days_used = 16
    await db_session.commit()

    response = await decide(client, as_, at, time_off, True)
    assert (response.status_code, response.json()) == (409, {'detail': 'not enough days left'})
    await db_session.refresh(time_off)
    assert time_off.status == Decision.PENDING


async def test_time_off_with_no_balance_kept(client, as_, at, new, people):
    request = await new(TimeOffRequest, user_id=people['member'].id, kind='sick', starts_on=date(2026, 7, 6),
                        ends_on=date(2026, 7, 6))

    assert (await decide(client, as_, at, request, True)).status_code == 200


async def test_nobody_decides_their_own_time_off(client, as_, at, new, people):
    request = await new(TimeOffRequest, by='admin', user_id=people['admin'].id)

    assert (await decide(client, as_, at, request, True)).status_code == 403


@pytest.mark.parametrize('role', ['member', 'peer', 'guest'])
async def test_time_off_is_decided_by_admins(client, as_, at, time_off, role):
    assert (await decide(client, as_, at, time_off, True, by=role)).status_code == 403


async def test_a_decided_request_is_not_changed(client, as_, at, time_off):
    await decide(client, as_, at, time_off, True)
    response = await client.patch(at(f'/time-off-requests/{time_off.id}'), json={'note': 'more'},
                                  headers=await as_('member'))

    assert (response.status_code, response.json()) == (409, {'detail': 'the request is decided'})


async def test_time_off_that_ends_before_it_starts(client, as_, at):
    body = {'kind': 'vacation', 'starts_on': '2026-07-10', 'ends_on': '2026-07-09'}
    response = await client.post(at('/time-off-requests'), json=body, headers=await as_('member'))

    assert (response.status_code, response.json()) == (400, {'detail': 'it ends before it starts'})


async def test_time_off_of_one_day(client, as_, at, people):
    body = {'kind': 'vacation', 'starts_on': '2026-07-10', 'ends_on': '2026-07-10'}
    response = await client.post(at('/time-off-requests'), json=body, headers=await as_('member'))

    assert response.status_code == 201
    assert (response.json()['user_id'], response.json()['status']) == (people['member'].id, 'pending')
