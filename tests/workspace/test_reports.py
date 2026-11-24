"""Reports say what is there; goals say how far they are; a week is checked into once."""
import pytest

from decimal import Decimal

from sqlalchemy import select

from app.models import now
from app.workspace.models.crm import Deal
from app.workspace.models.helpdesk import Ticket, TicketStatus
from app.workspace.models.reports import CheckIn, Goal, KeyResult, Report, ReportRun
from app.workspace.models.tasks import Task, TimeEntry


async def run(client, as_, at, report, by='member'):
    return await client.post(at(f'/reports/{report.id}/run'), headers=await as_(by))


async def test_a_report_of_tasks(client, as_, at, new, other_org):
    for done in (True, False, False):
        await new(Task, completed_at=now() if done else None)
    await new(Task, by='outsider', organisation=other_org)
    response = await run(client, as_, at, await new(Report, subject='tasks'))

    assert response.status_code == 201
    assert response.json()['result'] == {'total': 3, 'done': 1}


async def test_a_report_of_tickets(client, as_, at, new):
    for status in (TicketStatus.OPEN, TicketStatus.OPEN, TicketStatus.SOLVED):
        await new(Ticket, status=status)

    assert (await run(client, as_, at, await new(Report, subject='tickets'))).json()['result'] == {
        'open': 2, 'solved': 1,
    }


async def test_a_report_of_deals(client, as_, at, new):
    for amount in ('100.00', '250.50'):
        await new(Deal, amount=Decimal(amount))

    assert (await run(client, as_, at, await new(Report, subject='deals'))).json()['result'] == {
        'count': 2, 'amount': '350.50',
    }


async def test_a_report_of_time(client, as_, at, new):
    for minutes in (30, 45):
        await new(TimeEntry, minutes=minutes)

    assert (await run(client, as_, at, await new(Report, subject='time'))).json()['result'] == {'minutes': 75}


@pytest.mark.parametrize('subject, empty', [
    ('tasks', {'total': 0, 'done': 0}), ('tickets', {}), ('deals', {'count': 0, 'amount': '0'}),
    ('time', {'minutes': 0}),
])
async def test_a_report_of_nothing(client, as_, at, new, subject, empty):
    assert (await run(client, as_, at, await new(Report, subject=subject))).json()['result'] == empty


async def test_every_run_is_kept(client, as_, at, new, db_session, people):
    report = await new(Report, subject='time')
    await run(client, as_, at, report)
    await new(TimeEntry, minutes=10)
    await run(client, as_, at, report, by='peer')

    runs = (await db_session.scalars(select(ReportRun).order_by(ReportRun.id))).all()
    assert [(r.result, r.run_by_id) for r in runs] == [
        ({'minutes': 0}, people['member'].id), ({'minutes': 10}, people['peer'].id),
    ]


async def test_a_guest_runs_no_report(client, as_, at, new):
    assert (await run(client, as_, at, await new(Report), by='guest')).status_code == 403


async def test_the_subject_of_a_report_is_set_once(client, as_, at, new):
    report = await new(Report, subject='time')
    response = await client.patch(at(f'/reports/{report.id}'), json={'subject': 'tasks'}, headers=await as_('member'))

    assert response.status_code == 422


async def progress(client, as_, at, goal):
    response = await client.get(at(f'/goals/{goal.id}/progress'), headers=await as_('guest'))
    assert response.status_code == 200
    return response.json()


@pytest.mark.parametrize('results, percent', [
    ([], 0),
    ([('10', '5')], 50),
    ([('10', '5'), ('4', '4')], 75),
    ([('10', '20')], 100),
    ([('10', '20'), ('10', '0')], 50),
    ([('3', '1')], 33),
    ([('0', '0')], 100),
])
async def test_how_far_a_goal_is(client, as_, at, new, results, percent):
    goal = await new(Goal)
    for target, reached in results:
        await new(KeyResult, goal_id=goal.id, target=Decimal(target), reached=Decimal(reached))

    expected = {'goal_id': goal.id, 'key_results': len(results), 'percent': percent}
    assert await progress(client, as_, at, goal) == expected


async def test_a_goal_moves_with_its_results(client, as_, at, new):
    goal = await new(Goal)
    result = await new(KeyResult, goal_id=goal.id, target=Decimal('8'), reached=Decimal('2'))
    await client.patch(at(f'/key-results/{result.id}'), json={'reached': '6.00'}, headers=await as_('member'))

    assert (await progress(client, as_, at, goal))['percent'] == 75


async def test_the_progress_of_a_goal_of_another_organisation(client, as_, at, new, other_org):
    theirs = await new(Goal, by='outsider', organisation=other_org)

    assert (await client.get(at(f'/goals/{theirs.id}/progress'), headers=await as_('guest'))).status_code == 404


@pytest.mark.parametrize('starts, ends, expected', [
    ('2026-01-01', '2026-03-31', 201), ('2026-01-01', '2026-01-01', 201), ('2026-03-31', '2026-01-01', 400),
])
async def test_a_goal_of_a_quarter(client, as_, at, starts, ends, expected):
    body = {'title': 'Ship it', 'starts_on': starts, 'ends_on': ends}

    assert (await client.post(at('/goals'), json=body, headers=await as_('member'))).status_code == expected


async def check_in(client, as_, at, week_of, by='member', mood=4):
    return await client.post(at('/check-ins'), json={'week_of': week_of, 'mood': mood}, headers=await as_(by))


@pytest.mark.freeze_time('2026-03-04 12:00:00')
async def test_a_week_checked_into(client, as_, at, people):
    response = await check_in(client, as_, at, '2026-03-02')

    assert response.status_code == 201
    assert response.json()['user_id'] == people['member'].id


@pytest.mark.freeze_time('2026-03-04 12:00:00')
@pytest.mark.parametrize('week_of, detail', [
    ('2026-03-03', 'a week starts on a Monday'), ('2026-03-08', 'a week starts on a Monday'),
    ('2026-03-09', 'that week has not come'),
])
async def test_a_week_that_is_not(client, as_, at, week_of, detail):
    response = await check_in(client, as_, at, week_of)

    assert (response.status_code, response.json()) == (400, {'detail': detail})


@pytest.mark.freeze_time('2026-03-04 12:00:00')
async def test_a_week_checked_into_once(client, as_, at):
    await check_in(client, as_, at, '2026-03-02')

    assert (await check_in(client, as_, at, '2026-03-02')).status_code == 409


@pytest.mark.freeze_time('2026-03-04 12:00:00')
async def test_one_week_by_two(client, as_, at, db_session):
    await check_in(client, as_, at, '2026-03-02')
    await check_in(client, as_, at, '2026-03-02', by='peer')

    assert len((await db_session.scalars(select(CheckIn))).all()) == 2


@pytest.mark.freeze_time('2026-03-04 12:00:00')
@pytest.mark.parametrize('mood', [0, 6])
async def test_a_mood_out_of_five(client, as_, at, mood):
    assert (await check_in(client, as_, at, '2026-03-02', mood=mood)).status_code == 422


@pytest.mark.freeze_time('2026-03-04 12:00:00')
async def test_the_week_is_set_once(client, as_, at):
    made = (await check_in(client, as_, at, '2026-03-02')).json()
    response = await client.patch(at(f'/check-ins/{made["id"]}'), json={'week_of': '2026-02-23'},
                                  headers=await as_('member'))

    assert response.status_code == 422


async def test_the_record_is_for_admins(client, as_, at, new):
    await client.post(at('/projects'), json={'name': 'Web', 'key': 'WEB'}, headers=await as_('member'))

    page = (await client.get(at('/audit-records'), headers=await as_('admin'))).json()
    assert [(row['action'], row['subject']) for row in page['items']] == [('create', 'projects')]
    assert (await client.get(at('/audit-records'), headers=await as_('member'))).status_code == 403
