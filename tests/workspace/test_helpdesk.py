"""Tickets: numbered, promised an answer by a deadline, answered, solved, rated — and the articles
that save writing one."""
import pytest

from datetime import timedelta

from sqlalchemy import select

from app.workspace.models.helpdesk import Article, Queue, SlaPolicy, Ticket, TicketEvent, TicketStatus


@pytest.fixture
async def queue(new):
    return await new(Queue)


async def opened(client, as_, at, queue, by='member', **fields):
    body = {'queue_id': queue.id, 'subject': 'It broke', 'requester_email': 'client@example.com'} | fields
    response = await client.post(at('/tickets'), json=body, headers=await as_(by))
    assert response.status_code == 201, response.text
    return response.json()


async def test_tickets_are_numbered_in_their_organisation(client, as_, at, queue, new, other_org):
    other_queue = await new(Queue)
    numbers = [(await opened(client, as_, at, q))['number'] for q in (queue, other_queue, queue)]
    theirs = await client.post(f'/orgs/{other_org.id}/tickets', json={
        'queue_id': (await new(Queue, by='outsider', organisation=other_org)).id, 'subject': 'X',
        'requester_email': 'x@example.com',
    }, headers=await as_('outsider'))

    assert numbers == [1, 2, 3]
    assert theirs.json()['number'] == 1


async def test_a_ticket_goes_to_whoever_the_queue_names(client, as_, at, new, people):
    queue = await new(Queue, default_assignee_id=people['peer'].id)

    assert (await opened(client, as_, at, queue))['assignee_id'] == people['peer'].id


async def test_a_ticket_assigned_by_hand_stays_so(client, as_, at, new, people):
    queue = await new(Queue, default_assignee_id=people['peer'].id)

    assert (await opened(client, as_, at, queue, assignee_id=people['admin'].id))['assignee_id'] == people['admin'].id


async def test_a_ticket_with_no_promise(client, as_, at, queue):
    ticket = await opened(client, as_, at, queue)

    assert (ticket['respond_by'], ticket['solve_by']) == (None, None)


@pytest.fixture
async def policies(new):
    """An hour to answer and a day to solve a normal ticket; ten minutes and two hours an urgent one."""
    await new(SlaPolicy, priority='normal', first_response_minutes=60, resolution_minutes=1440)
    await new(SlaPolicy, priority='urgent', first_response_minutes=10, resolution_minutes=120)


@pytest.mark.freeze_time('2026-03-02 09:00:00')
async def test_a_ticket_is_promised_by_its_priority(client, as_, at, queue, policies):
    normal = await opened(client, as_, at, queue)
    urgent = await opened(client, as_, at, queue, priority='urgent')

    assert (normal['respond_by'], normal['solve_by']) == ('2026-03-02T10:00:00Z', '2026-03-03T09:00:00Z')
    assert (urgent['respond_by'], urgent['solve_by']) == ('2026-03-02T09:10:00Z', '2026-03-02T11:00:00Z')


@pytest.mark.freeze_time('2026-03-02 09:00:00')
async def test_a_new_priority_makes_a_new_promise_from_the_start(client, as_, at, queue, policies, freezer):
    ticket = await opened(client, as_, at, queue)
    # Less than an access token lives.
    freezer.tick(timedelta(minutes=10))
    response = await client.patch(at(f'/tickets/{ticket["id"]}'), json={'priority': 'urgent'},
                                  headers=await as_('member'))

    assert response.json()['respond_by'] == '2026-03-02T09:10:00Z'


@pytest.mark.freeze_time('2026-03-02 09:00:00')
async def test_a_priority_with_no_policy_promises_nothing(client, as_, at, queue, policies):
    ticket = await opened(client, as_, at, queue)
    response = await client.patch(at(f'/tickets/{ticket["id"]}'), json={'priority': 'low'},
                                  headers=await as_('member'))

    assert (response.json()['respond_by'], response.json()['solve_by']) == (None, None)


async def test_a_change_of_subject_keeps_the_promise(client, as_, at, queue, policies):
    ticket = await opened(client, as_, at, queue)
    response = await client.patch(at(f'/tickets/{ticket["id"]}'), json={'subject': 'It broke again'},
                                  headers=await as_('member'))

    assert response.json()['respond_by'] == ticket['respond_by']


async def test_one_policy_a_priority(client, as_, at, policies):
    body = {'name': 'Again', 'priority': 'normal', 'first_response_minutes': 5, 'resolution_minutes': 50}

    assert (await client.post(at('/sla-policies'), json=body, headers=await as_('admin'))).status_code == 409


@pytest.fixture
async def ticket(client, as_, at, queue):
    return await opened(client, as_, at, queue)


async def said(client, as_, at, ticket, internal=False, by='member'):
    return await client.post(at('/ticket-messages'), json={
        'ticket_id': ticket['id'], 'body': 'Looking', 'is_internal': internal,
    }, headers=await as_(by))


async def read(client, as_, at, ticket):
    return (await client.get(at(f'/tickets/{ticket["id"]}'), headers=await as_('guest'))).json()


@pytest.mark.freeze_time('2026-03-02 09:00:00')
async def test_the_first_answer(client, as_, at, ticket):
    response = await said(client, as_, at, ticket)

    assert response.status_code == 201
    now = await read(client, as_, at, ticket)
    assert (now['status'], now['first_response_at']) == ('pending', '2026-03-02T09:00:00Z')


async def test_the_first_answer_is_counted_once(client, as_, at, ticket, freezer):
    await said(client, as_, at, ticket)
    first = (await read(client, as_, at, ticket))['first_response_at']
    freezer.tick(timedelta(minutes=10))
    await said(client, as_, at, ticket)

    assert (await read(client, as_, at, ticket))['first_response_at'] == first


async def test_a_note_among_the_staff_is_no_answer(client, as_, at, ticket):
    await said(client, as_, at, ticket, internal=True)
    now = await read(client, as_, at, ticket)

    assert (now['status'], now['first_response_at']) == ('open', None)


async def test_a_message_has_its_author(client, as_, at, ticket, people):
    assert (await said(client, as_, at, ticket, by='peer')).json()['author_id'] == people['peer'].id


async def test_a_message_is_not_taken_back(client, as_, at, ticket):
    message = (await said(client, as_, at, ticket)).json()

    assert (await client.delete(at(f'/ticket-messages/{message["id"]}'),
                                headers=await as_('member'))).status_code == 405


async def step(client, as_, at, ticket, name, by='member'):
    return await client.post(at(f'/tickets/{ticket["id"]}/{name}'), headers=await as_(by))


async def test_solve(client, as_, at, ticket):
    response = await step(client, as_, at, ticket, 'solve')

    assert response.json()['status'] == 'solved'
    assert response.json()['solved_at'] is not None


async def test_solve_what_waits_for_an_answer(client, as_, at, ticket):
    await said(client, as_, at, ticket)

    assert (await step(client, as_, at, ticket, 'solve')).json()['status'] == 'solved'


async def test_reopen(client, as_, at, ticket):
    await step(client, as_, at, ticket, 'solve')
    response = await step(client, as_, at, ticket, 'reopen')

    assert (response.json()['status'], response.json()['solved_at']) == ('open', None)


async def test_close(client, as_, at, ticket):
    await step(client, as_, at, ticket, 'solve')
    response = await step(client, as_, at, ticket, 'close')

    assert response.json()['status'] == 'closed'
    assert response.json()['solved_at'] is not None


@pytest.mark.parametrize('steps, expected', [
    (['reopen'], 'the ticket is open'),
    (['close'], 'the ticket is open'),
    (['solve', 'solve'], 'the ticket is solved'),
    (['solve', 'close', 'reopen'], 'the ticket is closed'),
    (['solve', 'close', 'solve'], 'the ticket is closed'),
])
async def test_steps_out_of_turn(client, as_, at, ticket, steps, expected):
    for name in steps:
        response = await step(client, as_, at, ticket, name)

    assert (response.status_code, response.json()) == (409, {'detail': expected})


async def test_every_step_is_recorded(client, as_, at, ticket, people, db_session):
    for name in ('solve', 'reopen', 'solve', 'close'):
        await step(client, as_, at, ticket, name)

    events = (await db_session.scalars(select(TicketEvent).order_by(TicketEvent.id))).all()
    assert [(event.kind, event.actor_id) for event in events] == [
        ('solve', people['member'].id), ('reopen', people['member'].id), ('solve', people['member'].id),
        ('close', people['member'].id),
    ]


async def test_a_closed_ticket_is_kept_as_it_is(client, as_, at, ticket):
    await step(client, as_, at, ticket, 'solve')
    await step(client, as_, at, ticket, 'close')

    changed = await client.patch(at(f'/tickets/{ticket["id"]}'), json={'subject': 'X'}, headers=await as_('member'))
    answered = await said(client, as_, at, ticket)
    assert (changed.status_code, answered.status_code) == (409, 409)


@pytest.mark.parametrize('name', ['solve', 'reopen', 'close'])
async def test_a_guest_takes_no_step(client, as_, at, ticket, name):
    assert (await step(client, as_, at, ticket, name, by='guest')).status_code == 403


async def test_the_status_is_not_set_by_hand(client, as_, at, ticket):
    response = await client.patch(at(f'/tickets/{ticket["id"]}'), json={'status': 'closed'},
                                  headers=await as_('member'))

    assert response.status_code == 422


async def test_the_source_is_set_once(client, as_, at, queue):
    ticket = await opened(client, as_, at, queue, source='phone')
    response = await client.patch(at(f'/tickets/{ticket["id"]}'), json={'source': 'email'},
                                  headers=await as_('member'))

    assert (ticket['source'], response.status_code) == ('phone', 422)


async def rated(client, as_, at, ticket, score=5):
    return await client.post(at('/ratings'), json={'ticket_id': ticket['id'], 'score': score},
                             headers=await as_('member'))


@pytest.mark.parametrize('steps', [['solve'], ['solve', 'close']])
async def test_a_solved_ticket_is_rated(client, as_, at, ticket, steps):
    for name in steps:
        await step(client, as_, at, ticket, name)

    assert (await rated(client, as_, at, ticket)).status_code == 201


async def test_an_open_ticket_is_not_rated(client, as_, at, ticket):
    response = await rated(client, as_, at, ticket)

    assert (response.status_code, response.json()) == (409, {'detail': 'the ticket is not solved'})


async def test_a_ticket_is_rated_once(client, as_, at, ticket):
    await step(client, as_, at, ticket, 'solve')
    await rated(client, as_, at, ticket)

    assert (await rated(client, as_, at, ticket)).status_code == 409


@pytest.mark.parametrize('score', [0, 6, -1, 'five'])
async def test_a_score_out_of_five(client, as_, at, ticket, score):
    await step(client, as_, at, ticket, 'solve')

    assert (await rated(client, as_, at, ticket, score)).status_code == 422


@pytest.fixture
async def article(new):
    return await new(Article)


async def feedback(client, as_, at, article, did_help, by='member'):
    response = await client.post(at(f'/articles/{article.id}/feedback'), json={'did_help': did_help},
                                 headers=await as_(by))
    assert response.status_code == 200
    body = response.json()
    return body['helped'], body['did_not_help']


async def test_an_article_helped(client, as_, at, article):
    assert await feedback(client, as_, at, article, True) == (1, 0)


async def test_an_article_helped_some(client, as_, at, article):
    await feedback(client, as_, at, article, True)
    await feedback(client, as_, at, article, False, by='peer')

    assert await feedback(client, as_, at, article, True, by='admin') == (2, 1)


async def test_an_opinion_given_twice_counts_once(client, as_, at, article):
    await feedback(client, as_, at, article, True)

    assert await feedback(client, as_, at, article, True) == (1, 0)


async def test_an_opinion_changed(client, as_, at, article):
    await feedback(client, as_, at, article, True)

    assert await feedback(client, as_, at, article, False) == (0, 1)
    assert await feedback(client, as_, at, article, True) == (1, 0)


async def test_the_counts_are_not_set_by_hand(client, as_, at, article):
    response = await client.patch(at(f'/articles/{article.id}'), json={'helped': 100}, headers=await as_('member'))

    assert response.status_code == 422


async def test_a_ticket_watched(client, as_, at, ticket):
    for name in ('member', 'guest'):
        response = await client.put(at(f'/tickets/{ticket["id"]}/watch'), headers=await as_(name))

    assert response.json() == {'count': 2}


async def test_tickets_by_status(client, as_, at, queue):
    first = await opened(client, as_, at, queue)
    await opened(client, as_, at, queue)
    await step(client, as_, at, first, 'solve')

    page = (await client.get(at('/tickets'), params={'status': TicketStatus.SOLVED.value},
                             headers=await as_('guest'))).json()
    assert [row['id'] for row in page['items']] == [first['id']]


async def test_a_ticket_goes_with_its_queue(client, as_, at, queue, ticket, db_session):
    await client.delete(at(f'/queues/{queue.id}'), headers=await as_('admin'))

    assert (await db_session.scalars(select(Ticket))).all() == []
