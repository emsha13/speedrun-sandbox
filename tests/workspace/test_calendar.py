"""Events: a room is booked once at a time, invitations are answered, and everybody has an agenda."""
import pytest

from datetime import UTC, datetime

from app.workspace.models.calendar import Answer, Calendar, Event, EventAttendee, EventStatus, Room


@pytest.fixture
async def calendar(new):
    return await new(Calendar)


@pytest.fixture
async def room(new):
    return await new(Room)


def at_hours(start: int, end: int, day: int = 1) -> dict:
    return {'starts_at': f'2026-03-{day:02d}T{start:02d}:00:00Z', 'ends_at': f'2026-03-{day:02d}T{end:02d}:00:00Z'}


async def booked(client, as_, at, calendar, room=None, start=10, end=11, by='member', **fields):
    body = {'calendar_id': calendar.id, 'title': 'Talk'} | at_hours(start, end) | fields
    if room is not None:
        body['room_id'] = room.id
    return await client.post(at('/events'), json=body, headers=await as_(by))


async def test_an_event(client, as_, at, calendar, room, people):
    response = await booked(client, as_, at, calendar, room)

    assert response.status_code == 201
    assert (response.json()['organiser_id'], response.json()['status']) == (people['member'].id, 'confirmed')


@pytest.mark.parametrize('start, end', [(11, 10), (10, 10)])
async def test_an_event_that_ends_before_it_starts(client, as_, at, calendar, start, end):
    response = await booked(client, as_, at, calendar, start=start, end=end)

    assert (response.status_code, response.json()) == (400, {'detail': 'it ends before it starts'})


@pytest.mark.parametrize('start, end, expected', [
    (10, 11, 409), (9, 11, 409), (10, 12, 409), (9, 12, 409), (11, 12, 409),
    (8, 10, 201), (12, 13, 201), (7, 8, 201),
])
async def test_a_room_is_booked_once_at_a_time(client, as_, at, calendar, room, start, end, expected):
    await booked(client, as_, at, calendar, room, start=10, end=12)
    response = await booked(client, as_, at, calendar, room, start=start, end=end)

    assert response.status_code == expected
    if expected == 409:
        assert response.json() == {'detail': 'the room is taken'}


async def test_two_rooms_at_one_time(client, as_, at, calendar, room, new):
    await booked(client, as_, at, calendar, room)

    assert (await booked(client, as_, at, calendar, await new(Room))).status_code == 201


async def test_a_room_on_another_day(client, as_, at, calendar, room):
    await booked(client, as_, at, calendar, room)

    assert (await booked(client, as_, at, calendar, room, starts_at='2026-03-02T10:00:00Z',
                         ends_at='2026-03-02T11:00:00Z')).status_code == 201


async def test_a_cancelled_event_keeps_no_room(client, as_, at, calendar, room):
    first = (await booked(client, as_, at, calendar, room)).json()
    await client.patch(at(f'/events/{first["id"]}'), json={'status': 'cancelled'}, headers=await as_('member'))

    assert (await booked(client, as_, at, calendar, room)).status_code == 201


async def test_a_cancelled_event_takes_no_room(client, as_, at, calendar, room):
    await booked(client, as_, at, calendar, room)

    assert (await booked(client, as_, at, calendar, room, status='cancelled')).status_code == 201


async def test_an_event_moved_into_another(client, as_, at, calendar, room):
    await booked(client, as_, at, calendar, room, start=10, end=11)
    later = (await booked(client, as_, at, calendar, room, start=14, end=15)).json()
    response = await client.patch(at(f'/events/{later["id"]}'), json=at_hours(10, 11), headers=await as_('member'))

    assert response.status_code == 409


async def test_an_event_moved_within_its_own_time(client, as_, at, calendar, room):
    event = (await booked(client, as_, at, calendar, room, start=10, end=12)).json()
    response = await client.patch(at(f'/events/{event["id"]}'), json=at_hours(10, 11), headers=await as_('member'))

    assert response.status_code == 200


async def test_an_event_moved_to_end_before_it_starts(client, as_, at, calendar):
    event = (await booked(client, as_, at, calendar)).json()
    response = await client.patch(at(f'/events/{event["id"]}'), json={'ends_at': '2026-03-01T09:00:00Z'},
                                  headers=await as_('member'))

    assert response.status_code == 400


async def test_the_room_of_another_organisation(client, as_, at, calendar, new, other_org):
    theirs = await new(Room, by='outsider', organisation=other_org)

    assert (await booked(client, as_, at, calendar, theirs)).status_code == 400


@pytest.mark.parametrize('moment', ['2026-03-01T10:00:00', '2026-03-01', 'soon', '2026-03-01T25:00:00Z'])
async def test_an_event_at_a_malformed_moment(client, as_, at, calendar, moment):
    response = await booked(client, as_, at, calendar, starts_at=moment)

    assert response.status_code == 422


@pytest.fixture
async def invitation(new, people):
    event = await new(Event)
    await new(EventAttendee, event_id=event.id, user_id=people['peer'].id)
    return event


async def answer(client, as_, at, event, value, by='peer'):
    return await client.post(at(f'/events/{event.id}/answer'), json={'answer': value}, headers=await as_(by))


@pytest.mark.parametrize('value', ['yes', 'no', 'maybe'])
async def test_an_invitation_answered(client, as_, at, invitation, value):
    response = await answer(client, as_, at, invitation, value)

    assert (response.status_code, response.json()['answer']) == (200, value)


async def test_an_answer_changed(client, as_, at, invitation):
    await answer(client, as_, at, invitation, 'yes')

    assert (await answer(client, as_, at, invitation, 'no')).json()['answer'] == 'no'


async def test_pending_is_no_answer(client, as_, at, invitation):
    assert (await answer(client, as_, at, invitation, 'pending')).status_code == 400


async def test_an_answer_from_somebody_not_invited(client, as_, at, invitation):
    response = await answer(client, as_, at, invitation, 'yes', by='member')

    assert (response.status_code, response.json()) == (403, {'detail': 'not invited'})


async def test_a_guest_answers_their_own(client, as_, at, new, people):
    event = await new(Event)
    await new(EventAttendee, event_id=event.id, user_id=people['guest'].id)

    assert (await answer(client, as_, at, event, 'yes', by='guest')).status_code == 200


async def test_an_answer_is_not_set_by_hand(client, as_, at, invitation, people):
    body = {'event_id': invitation.id, 'user_id': people['member'].id, 'answer': 'yes'}

    assert (await client.post(at('/event-attendees'), json=body, headers=await as_('member'))).status_code == 422


async def test_somebody_invited_twice(client, as_, at, invitation, people):
    body = {'event_id': invitation.id, 'user_id': people['peer'].id}
    response = await client.post(at('/event-attendees'), json=body, headers=await as_('member'))

    assert response.status_code == 409


WINDOW = {'starts_at': '2026-03-01T00:00:00Z', 'ends_at': '2026-03-02T00:00:00Z'}


async def agenda(client, as_, at, by='peer', **window):
    response = await client.get(at('/agenda'), params=WINDOW | window, headers=await as_(by))
    assert response.status_code == 200, response.text
    return [row['title'] for row in response.json()]


def moment(hour: int, day: int = 1) -> datetime:
    return datetime(2026, 3, day, hour, tzinfo=UTC)


@pytest.fixture
async def week(new, people):
    """The peer's events and other people's, on the first and second of March."""
    peer = people['peer'].id
    for title, organiser, start, day, status in (
        ('mine', peer, 9, 1, EventStatus.CONFIRMED), ('theirs', people['member'].id, 11, 1, EventStatus.CONFIRMED),
        ('mine, cancelled', peer, 13, 1, EventStatus.CANCELLED), ('mine, tomorrow', peer, 9, 2, EventStatus.CONFIRMED),
    ):
        await new(Event, title=title, organiser_id=organiser, starts_at=moment(start, day),
                  ends_at=moment(start + 1, day), status=status)
    for title, answered in (('invited', Answer.PENDING), ('accepted', Answer.YES), ('declined', Answer.NO),
                            ('maybe', Answer.MAYBE)):
        event = await new(Event, title=title, starts_at=moment(15), ends_at=moment(16))
        await new(EventAttendee, event_id=event.id, user_id=peer, answer=answered)


async def test_an_agenda(client, as_, at, week):
    assert await agenda(client, as_, at) == ['mine', 'invited', 'accepted', 'maybe']


async def test_the_agenda_of_somebody_else(client, as_, at, week):
    assert await agenda(client, as_, at, by='member') == ['theirs']


async def test_an_agenda_of_two_days(client, as_, at, week):
    titles = await agenda(client, as_, at, ends_at='2026-03-03T00:00:00Z')

    assert titles == ['mine', 'invited', 'accepted', 'maybe', 'mine, tomorrow']


@pytest.mark.parametrize('window, expected', [
    ({'starts_at': '2026-03-01T09:30:00Z', 'ends_at': '2026-03-01T09:45:00Z'}, ['mine']),
    ({'starts_at': '2026-03-01T10:00:00Z', 'ends_at': '2026-03-01T15:00:00Z'}, []),
    ({'starts_at': '2026-03-01T08:00:00Z', 'ends_at': '2026-03-01T09:00:00Z'}, []),
    ({'starts_at': '2026-03-01T08:00:00+01:00', 'ends_at': '2026-03-01T09:00:01Z'}, ['mine']),
])
async def test_an_agenda_holds_what_overlaps_the_window(client, as_, at, week, window, expected):
    assert await agenda(client, as_, at, **window) == expected


async def test_an_agenda_with_a_window_back_to_front(client, as_, at):
    response = await client.get(at('/agenda'), params={'starts_at': WINDOW['ends_at'], 'ends_at': WINDOW['starts_at']},
                                headers=await as_('peer'))

    assert response.status_code == 400


@pytest.mark.parametrize('params', [{}, {'starts_at': WINDOW['starts_at']},
                                    {'starts_at': '2026-03-01T00:00:00', 'ends_at': WINDOW['ends_at']}])
async def test_an_agenda_malformed(client, as_, at, params):
    assert (await client.get(at('/agenda'), params=params, headers=await as_('peer'))).status_code == 422


async def test_an_agenda_holds_this_organisation_only(client, as_, at, new, other_org, people):
    await new(Event, by='outsider', organisation=other_org, organiser_id=people['peer'].id,
              starts_at=moment(9), ends_at=moment(10))

    assert await agenda(client, as_, at) == []


@pytest.mark.parametrize('starts, ends, expected', [
    ('2026-07-01', '2026-07-10', 201), ('2026-07-01', '2026-07-01', 201), ('2026-07-10', '2026-07-01', 400),
])
async def test_an_absence(client, as_, at, starts, ends, expected):
    response = await client.post(at('/absences'), json={'starts_on': starts, 'ends_on': ends},
                                 headers=await as_('member'))

    assert response.status_code == expected


async def test_an_absence_with_somebody_to_answer_meanwhile(client, as_, at, people):
    body = {'starts_on': '2026-07-01', 'ends_on': '2026-07-10', 'delegate_id': people['outsider'].id}

    assert (await client.post(at('/absences'), json=body, headers=await as_('member'))).status_code == 400
