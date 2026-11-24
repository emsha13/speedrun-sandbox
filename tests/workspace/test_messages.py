"""Notifications, broadcasts, and chat channels."""
import pytest

from sqlalchemy import select

from app.models import now
from app.workspace.models.messages import (
    Broadcast, ChannelMember, ChatChannel, Message, Notification, NotificationPreference,
)
from app.workspace.models.orgs import Team, TeamMember


@pytest.fixture
async def inbox(new, people):
    """Three notifications for the member, the last of them read, and one for the peer."""
    rows = [await new(Notification, user_id=people['member'].id, title=f'N{number}') for number in range(3)]
    rows[2].read_at = now()
    await new(Notification, user_id=people['peer'].id, title='Not yours')
    return rows


async def notifications(client, as_, at, by='member', **params):
    response = await client.get(at('/notifications'), params=params, headers=await as_(by))
    assert response.status_code == 200
    return [row['title'] for row in response.json()]


async def test_my_notifications_newest_first(client, as_, at, inbox):
    assert await notifications(client, as_, at) == ['N2', 'N1', 'N0']


async def test_my_unread_notifications(client, as_, at, inbox, db_session):
    await db_session.commit()

    assert await notifications(client, as_, at, unread=True) == ['N1', 'N0']
    assert (await client.get(at('/notifications/unread-count'), headers=await as_('member'))).json() == {'count': 2}


async def test_some_of_my_notifications(client, as_, at, inbox):
    assert await notifications(client, as_, at, limit=1) == ['N2']


async def test_nobody_elses_notifications(client, as_, at, inbox):
    assert await notifications(client, as_, at, by='guest') == []


@pytest.mark.parametrize('params', [{'limit': 0}, {'limit': 101}, {'unread': 'perhaps'}])
async def test_my_notifications_malformed(client, as_, at, params):
    assert (await client.get(at('/notifications'), params=params, headers=await as_('member'))).status_code == 422


async def test_a_notification_read(client, as_, at, inbox):
    response = await client.post(at(f'/notifications/{inbox[0].id}/read'), headers=await as_('member'))

    assert response.json()['read_at'] is not None
    assert await notifications(client, as_, at, unread=True) == ['N1']


async def test_a_notification_read_twice_keeps_the_first_time(client, as_, at, inbox):
    first = await client.post(at(f'/notifications/{inbox[0].id}/read'), headers=await as_('member'))
    second = await client.post(at(f'/notifications/{inbox[0].id}/read'), headers=await as_('member'))

    assert first.json()['read_at'] == second.json()['read_at']


async def test_somebody_elses_notification_is_not_there(client, as_, at, inbox):
    response = await client.post(at(f'/notifications/{inbox[0].id}/read'), headers=await as_('peer'))

    assert (response.status_code, response.json()) == (404, {'detail': 'no such notification'})


async def test_all_read(client, as_, at, inbox, db_session):
    await db_session.commit()
    response = await client.post(at('/notifications/read-all'), headers=await as_('member'))

    assert response.json() == {'count': 2}
    assert await notifications(client, as_, at, unread=True) == []
    assert await notifications(client, as_, at, by='peer', unread=True) == ['Not yours']


async def test_my_preferences(client, as_, at):
    for wanted in (False, True, False):
        response = await client.put(at('/notification-preferences'), json={
            'kind': 'mention', 'channel': 'email', 'is_wanted': wanted,
        }, headers=await as_('member'))
    listed = (await client.get(at('/notification-preferences'), headers=await as_('member'))).json()

    assert response.json()['is_wanted'] is False
    assert [(row['kind'], row['channel'], row['is_wanted']) for row in listed] == [('mention', 'email', False)]
    assert (await client.get(at('/notification-preferences'), headers=await as_('peer'))).json() == []


@pytest.mark.parametrize('body', [
    {'kind': '', 'channel': 'email', 'is_wanted': True}, {'kind': 'x', 'channel': 'pigeon', 'is_wanted': True},
    {'kind': 'x', 'channel': 'email'},
])
async def test_a_preference_malformed(client, as_, at, body):
    assert (await client.put(at('/notification-preferences'), json=body,
                             headers=await as_('member'))).status_code == 422


async def send(client, as_, at, broadcast, by='admin'):
    return await client.post(at(f'/broadcasts/{broadcast.id}/send'), headers=await as_(by))


async def recipients(db_session, people) -> list[str]:
    names = {user.id: name for name, user in people.items()}
    rows = await db_session.scalars(select(Notification).order_by(Notification.id))
    return [names[row.user_id] for row in rows]


async def test_a_broadcast_to_everyone(client, as_, at, new, db_session, people):
    broadcast = await new(Broadcast, title='Hello')
    response = await send(client, as_, at, broadcast)

    assert response.json()['sent_at'] is not None
    assert await recipients(db_session, people) == ['owner', 'admin', 'member', 'peer', 'guest']


async def test_a_broadcast_to_the_admins(client, as_, at, new, db_session, people):
    await send(client, as_, at, await new(Broadcast, audience='admins'))

    assert await recipients(db_session, people) == ['owner', 'admin']


async def test_a_broadcast_to_a_team(client, as_, at, new, db_session, people):
    team = await new(Team)
    for name in ('peer', 'guest'):
        await new(TeamMember, team_id=team.id, user_id=people[name].id)
    await send(client, as_, at, await new(Broadcast, audience='team', team_id=team.id))

    assert await recipients(db_session, people) == ['peer', 'guest']


async def test_a_broadcast_skips_whoever_wants_none(client, as_, at, new, db_session, people):
    await new(NotificationPreference, user_id=people['member'].id, kind='broadcast', channel='in_app', is_wanted=False)
    await new(NotificationPreference, user_id=people['peer'].id, kind='broadcast', channel='email', is_wanted=False)
    await send(client, as_, at, await new(Broadcast))

    assert await recipients(db_session, people) == ['owner', 'admin', 'peer', 'guest']


async def test_a_broadcast_goes_out_once(client, as_, at, new):
    broadcast = await new(Broadcast)
    await send(client, as_, at, broadcast)

    assert (await send(client, as_, at, broadcast)).status_code == 409


async def test_a_sent_broadcast_is_kept_as_it_is(client, as_, at, new):
    broadcast = await new(Broadcast)
    await send(client, as_, at, broadcast)
    response = await client.patch(at(f'/broadcasts/{broadcast.id}'), json={'title': 'X'}, headers=await as_('admin'))

    assert (response.status_code, response.json()) == (409, {'detail': 'the broadcast is sent'})


@pytest.mark.parametrize('audience, team', [('team', False), ('everyone', True), ('admins', True)])
async def test_a_team_named_when_the_audience_is_a_team_only(client, as_, at, new, audience, team):
    body = {'title': 'Hi', 'body': 'There', 'audience': audience}
    if team:
        body['team_id'] = (await new(Team)).id

    assert (await client.post(at('/broadcasts'), json=body, headers=await as_('admin'))).status_code == 400


async def test_broadcasts_are_for_admins(client, as_, at, new):
    assert (await send(client, as_, at, await new(Broadcast), by='member')).status_code == 403


async def opened(client, as_, at, by='member', **fields):
    response = await client.post(at('/chat-channels'), json={'name': 'general'} | fields, headers=await as_(by))
    assert response.status_code == 201, response.text
    return response.json()


async def members_of(db_session, people, channel) -> list[str]:
    names = {user.id: name for name, user in people.items()}
    rows = await db_session.scalars(
        select(ChannelMember).where(ChannelMember.channel_id == channel['id']).order_by(ChannelMember.id)
    )
    return [names[row.user_id] for row in rows]


async def test_whoever_opens_a_channel_is_in_it(client, as_, at, db_session, people):
    channel = await opened(client, as_, at)

    assert await members_of(db_session, people, channel) == ['member']


@pytest.mark.parametrize('name', ['General', 'two words', '-dash', '', 'x' * 61])
async def test_a_channel_of_a_malformed_name(client, as_, at, name):
    assert (await client.post(at('/chat-channels'), json={'name': name},
                              headers=await as_('member'))).status_code == 422


async def test_a_channel_name_once(client, as_, at):
    await opened(client, as_, at)

    assert (await client.post(at('/chat-channels'), json={'name': 'general'},
                              headers=await as_('peer'))).status_code == 409


async def join(client, as_, at, channel, by):
    return await client.post(at(f'/chat-channels/{channel["id"]}/join'), headers=await as_(by))


async def test_join_and_leave(client, as_, at, db_session, people):
    channel = await opened(client, as_, at)
    for name in ('peer', 'guest', 'peer'):
        assert (await join(client, as_, at, channel, name)).status_code == 204
    await client.post(at(f'/chat-channels/{channel["id"]}/leave'), headers=await as_('guest'))
    await client.post(at(f'/chat-channels/{channel["id"]}/leave'), headers=await as_('guest'))

    assert await members_of(db_session, people, channel) == ['member', 'peer']


@pytest.mark.parametrize('name, expected', [('peer', 403), ('guest', 403), ('admin', 204), ('owner', 204)])
async def test_a_private_channel_is_entered_by_invitation(client, as_, at, name, expected):
    channel = await opened(client, as_, at, is_private=True)

    assert (await join(client, as_, at, channel, name)).status_code == expected


async def said(client, as_, at, channel, by='member', **fields):
    return await client.post(at('/messages'), json={'channel_id': channel['id'], 'body': 'Hi'} | fields,
                             headers=await as_(by))


async def test_a_message(client, as_, at, people):
    channel = await opened(client, as_, at)
    response = await said(client, as_, at, channel, by='peer')

    assert (response.status_code, response.json()['author_id']) == (201, people['peer'].id)


async def test_a_private_channel_hears_its_members_only(client, as_, at):
    channel = await opened(client, as_, at, is_private=True)

    assert (await said(client, as_, at, channel)).status_code == 201
    assert (await said(client, as_, at, channel, by='peer')).status_code == 403


async def test_an_archived_channel_is_silent(client, as_, at, db_session):
    channel = await opened(client, as_, at)
    row = await db_session.get(ChatChannel, channel['id'])
    row.archived_at = now()
    await db_session.commit()

    assert (await said(client, as_, at, channel)).json() == {'detail': 'the channel is archived'}


async def test_a_thread(client, as_, at):
    channel = await opened(client, as_, at)
    first = (await said(client, as_, at, channel)).json()
    answer = await said(client, as_, at, channel, by='peer', parent_id=first['id'])

    assert answer.json()['parent_id'] == first['id']
    page = (await client.get(at('/messages'), params={'parent_id': first['id']}, headers=await as_('guest'))).json()
    assert [row['id'] for row in page['items']] == [answer.json()['id']]


async def test_a_thread_keeps_to_its_channel(client, as_, at):
    here = await opened(client, as_, at)
    there = await opened(client, as_, at, name='random')
    first = (await said(client, as_, at, here)).json()

    response = await said(client, as_, at, there, parent_id=first['id'])
    assert (response.status_code, response.json()) == (400, {'detail': 'the thread is in another channel'})


async def test_a_thread_goes_with_its_first_message(client, as_, at, db_session):
    channel = await opened(client, as_, at)
    first = (await said(client, as_, at, channel)).json()
    await said(client, as_, at, channel, parent_id=first['id'])
    await client.delete(at(f'/messages/{first["id"]}'), headers=await as_('member'))

    assert (await db_session.scalars(select(Message))).all() == []


async def test_a_message_edited(client, as_, at):
    channel = await opened(client, as_, at)
    message = (await said(client, as_, at, channel)).json()
    response = await client.patch(at(f'/messages/{message["id"]}'), json={'body': 'Hello'},
                                  headers=await as_('member'))

    assert (response.json()['body'], response.json()['updated_at'] is not None) == ('Hello', True)


async def test_a_message_moves_to_no_other_channel(client, as_, at):
    channel = await opened(client, as_, at)
    message = (await said(client, as_, at, channel)).json()
    response = await client.patch(at(f'/messages/{message["id"]}'), json={'channel_id': channel['id']},
                                  headers=await as_('member'))

    assert response.status_code == 422


async def test_messages_searched(client, as_, at):
    channel = await opened(client, as_, at)
    for body in ('Lunch at noon?', 'Deploy is done', 'lunch: yes'):
        await said(client, as_, at, channel, body=body)
    page = (await client.get(at('/messages'), params={'search': 'LUNCH'}, headers=await as_('guest'))).json()

    assert [row['body'] for row in page['items']] == ['Lunch at noon?', 'lunch: yes']
