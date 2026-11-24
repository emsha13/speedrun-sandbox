"""Projects: the numbers of their tasks, sprints that start and end, releases that go out, and the
marks members put on things."""
import pytest

from sqlalchemy import select

from app.workspace.models.projects import Project, Release, Sprint, StatusCategory, TaskStatus
from app.workspace.models.tasks import Task, TaskStatusChange


@pytest.fixture
async def project(new):
    return await new(Project, key='WEB')


@pytest.fixture
async def statuses(new):
    return {
        category: await new(TaskStatus, name=category.value, category=category) for category in StatusCategory
    }


async def made_task(client, as_, at, project, **fields):
    response = await client.post(at('/tasks'), json={'project_id': project.id, 'title': 'Do it'} | fields,
                                 headers=await as_('member'))
    assert response.status_code == 201, response.text
    return response.json()


async def test_tasks_are_numbered_in_their_project(client, as_, at, project, new):
    other = await new(Project, key='APP')
    numbers = [(await made_task(client, as_, at, project))['number'] for _ in range(3)]

    assert numbers == [1, 2, 3]
    assert (await made_task(client, as_, at, other))['number'] == 1


async def test_a_deleted_task_leaves_its_number_unused(client, as_, at, project):
    first = await made_task(client, as_, at, project)
    await client.delete(at(f'/tasks/{first["id"]}'), headers=await as_('member'))

    assert (await made_task(client, as_, at, project))['number'] == 2


async def test_the_reporter_is_whoever_made_it(client, as_, at, project, people):
    assert (await made_task(client, as_, at, project))['reporter_id'] == people['member'].id


async def test_the_number_is_not_given(client, as_, at, project):
    body = {'project_id': project.id, 'title': 'Do it', 'number': 7}

    assert (await client.post(at('/tasks'), json=body, headers=await as_('member'))).status_code == 422


async def test_a_task_moves_to_no_other_project(client, as_, at, project, new):
    task = await made_task(client, as_, at, project)
    other = await new(Project, key='APP')
    response = await client.patch(at(f'/tasks/{task["id"]}'), json={'project_id': other.id},
                                  headers=await as_('member'))

    assert response.status_code == 422


async def test_a_task_made_done(client, as_, at, project, statuses):
    task = await made_task(client, as_, at, project, status_id=statuses[StatusCategory.DONE].id)

    assert task['completed_at'] is not None


async def test_a_task_finished_and_reopened(client, as_, at, project, statuses, db_session, people):
    task = await made_task(client, as_, at, project, status_id=statuses[StatusCategory.TODO].id)
    path = at(f'/tasks/{task["id"]}')

    done = await client.patch(path, json={'status_id': statuses[StatusCategory.DONE].id}, headers=await as_('peer'))
    reopened = await client.patch(path, json={'status_id': statuses[StatusCategory.DOING].id},
                                  headers=await as_('peer'))

    assert done.json()['completed_at'] is not None
    assert reopened.json()['completed_at'] is None
    changes = (await db_session.scalars(select(TaskStatusChange).order_by(TaskStatusChange.id))).all()
    assert [(c.from_status_id, c.to_status_id, c.changed_by_id) for c in changes] == [
        (statuses[StatusCategory.TODO].id, statuses[StatusCategory.DONE].id, people['peer'].id),
        (statuses[StatusCategory.DONE].id, statuses[StatusCategory.DOING].id, people['peer'].id),
    ]


async def test_a_change_of_no_status_is_not_recorded(client, as_, at, project, statuses, db_session):
    task = await made_task(client, as_, at, project, status_id=statuses[StatusCategory.TODO].id)
    await client.patch(at(f'/tasks/{task["id"]}'), json={'title': 'Do it now'}, headers=await as_('member'))
    await client.patch(at(f'/tasks/{task["id"]}'), json={'status_id': statuses[StatusCategory.TODO].id},
                       headers=await as_('member'))

    assert (await db_session.scalars(select(TaskStatusChange))).all() == []


async def test_a_task_is_not_its_own_parent(client, as_, at, project):
    task = await made_task(client, as_, at, project)
    response = await client.patch(at(f'/tasks/{task["id"]}'), json={'parent_id': task['id']},
                                  headers=await as_('member'))

    assert (response.status_code, response.json()) == (400, {'detail': 'a task is not its own parent'})


async def test_a_subtask(client, as_, at, project):
    parent = await made_task(client, as_, at, project)
    child = await made_task(client, as_, at, project, parent_id=parent['id'])

    page = (await client.get(at('/tasks'), params={'parent_id': parent['id']}, headers=await as_('guest'))).json()
    assert [row['id'] for row in page['items']] == [child['id']]


async def test_a_task_assigned_to_a_member_only(client, as_, at, project, people):
    body = {'project_id': project.id, 'title': 'Do it', 'assignee_id': people['outsider'].id}
    response = await client.post(at('/tasks'), json=body, headers=await as_('member'))

    assert (response.status_code, response.json()) == (400, {'detail': 'no such assignee'})


@pytest.mark.parametrize('params, titles', [
    ({'priority': 'high'}, ['B']),
    ({'sort': 'title', 'order': 'desc'}, ['C', 'B', 'A']),
    ({'search': 'b'}, ['B']),
    ({'priority': 'low', 'sort': 'title'}, ['A', 'C']),
])
async def test_tasks_filtered(client, as_, at, project, params, titles):
    for title, priority in (('A', 'low'), ('B', 'high'), ('C', 'low')):
        await made_task(client, as_, at, project, title=title, priority=priority)

    page = (await client.get(at('/tasks'), params=params, headers=await as_('guest'))).json()
    assert [row['title'] for row in page['items']] == titles


@pytest.fixture
async def sprint(new, project):
    return await new(Sprint, project_id=project.id)


async def step(client, as_, at, sprint, name, by='member'):
    return await client.post(at(f'/sprints/{sprint.id}/{name}'), headers=await as_(by))


async def test_a_sprint_starts(client, as_, at, sprint):
    response = await step(client, as_, at, sprint, 'start')

    assert response.status_code == 200
    assert response.json()['status'] == 'active'
    assert response.json()['started_at'] is not None


async def test_one_sprint_at_a_time(client, as_, at, sprint, new, project):
    other = await new(Sprint, project_id=project.id)
    await step(client, as_, at, sprint, 'start')
    response = await step(client, as_, at, other, 'start')

    assert (response.status_code, response.json()) == (409, {'detail': 'the project has a sprint running'})


async def test_sprints_of_two_projects_run_together(client, as_, at, sprint, new):
    other = await new(Sprint)
    await step(client, as_, at, sprint, 'start')

    assert (await step(client, as_, at, other, 'start')).status_code == 200


@pytest.mark.parametrize('steps, expected', [
    (['complete'], 'the sprint is planned'),
    (['start', 'start'], 'the sprint is active'),
    (['start', 'complete', 'start'], 'the sprint is completed'),
    (['start', 'complete', 'complete'], 'the sprint is completed'),
])
async def test_sprint_steps_out_of_turn(client, as_, at, sprint, steps, expected):
    for name in steps:
        response = await step(client, as_, at, sprint, name)

    assert (response.status_code, response.json()) == (409, {'detail': expected})


async def test_what_a_sprint_leaves_unfinished_goes_back(client, as_, at, sprint, project, statuses, db_session):
    done = await made_task(client, as_, at, project, sprint_id=sprint.id, status_id=statuses[StatusCategory.DONE].id)
    open_ = await made_task(client, as_, at, project, sprint_id=sprint.id)
    await step(client, as_, at, sprint, 'start')
    response = await step(client, as_, at, sprint, 'complete')

    assert response.json()['status'] == 'completed'
    tasks = {task.id: task for task in (await db_session.scalars(select(Task))).all()}
    for task in tasks.values():
        await db_session.refresh(task)
    assert (tasks[done['id']].sprint_id, tasks[open_['id']].sprint_id) == (sprint.id, None)


async def test_a_guest_runs_no_sprint(client, as_, at, sprint):
    assert (await step(client, as_, at, sprint, 'start', by='guest')).status_code == 403


async def test_a_sprint_of_another_organisation(client, as_, at, new, other_org):
    theirs = await new(Sprint, by='outsider', organisation=other_org)

    assert (await step(client, as_, at, theirs, 'start')).status_code == 404


async def test_a_sprint_that_ends_before_it_starts(client, as_, at, project):
    body = {'project_id': project.id, 'name': 'S1', 'starts_on': '2026-03-10', 'ends_on': '2026-03-09'}

    assert (await client.post(at('/sprints'), json=body, headers=await as_('member'))).status_code == 400


async def test_the_status_of_a_sprint_is_not_set_by_hand(client, as_, at, sprint):
    response = await client.patch(at(f'/sprints/{sprint.id}'), json={'status': 'active'}, headers=await as_('member'))

    assert response.status_code == 422


@pytest.fixture
async def release(new, project):
    return await new(Release, project_id=project.id)


async def test_a_release_goes_out(client, as_, at, release, project, statuses):
    await made_task(client, as_, at, project, release_id=release.id, status_id=statuses[StatusCategory.DONE].id)
    response = await client.post(at(f'/releases/{release.id}/publish'), headers=await as_('member'))

    assert response.status_code == 200
    assert response.json()['released_at'] is not None


async def test_an_empty_release_goes_out(client, as_, at, release):
    assert (await client.post(at(f'/releases/{release.id}/publish'), headers=await as_('member'))).status_code == 200


async def test_a_release_waits_for_its_tasks(client, as_, at, release, project):
    await made_task(client, as_, at, project, release_id=release.id)
    response = await client.post(at(f'/releases/{release.id}/publish'), headers=await as_('member'))

    assert (response.status_code, response.json()) == (409, {'detail': 'the release has unfinished tasks'})


async def test_a_release_goes_out_once(client, as_, at, release):
    await client.post(at(f'/releases/{release.id}/publish'), headers=await as_('member'))

    assert (await client.post(at(f'/releases/{release.id}/publish'), headers=await as_('member'))).status_code == 409


async def test_a_release_name_once_a_project(client, as_, at, project):
    body = {'project_id': project.id, 'name': '1.0'}
    for expected in (201, 409):
        assert (await client.post(at('/releases'), json=body, headers=await as_('member'))).status_code == expected


async def test_a_project_key_once_an_organisation(client, as_, at, project):
    response = await client.post(at('/projects'), json={'name': 'Web again', 'key': 'WEB'}, headers=await as_('member'))

    assert (response.status_code, response.json()) == (409, {'detail': 'such a project is there already'})


async def test_a_project_key_in_two_organisations(client, as_, project, other_org):
    response = await client.post(f'/orgs/{other_org.id}/projects', json={'name': 'Web', 'key': 'WEB'},
                                 headers=await as_('outsider'))

    assert response.status_code == 201


@pytest.mark.parametrize('key', ['W', 'web', '1WEB', 'WEB-1', 'ABCDEFGHI', ''])
async def test_a_malformed_project_key(client, as_, at, key):
    response = await client.post(at('/projects'), json={'name': 'Web', 'key': key}, headers=await as_('member'))

    assert response.status_code == 422


async def test_a_project_goes_with_its_tasks(client, as_, at, project, db_session):
    await made_task(client, as_, at, project)
    await client.delete(at(f'/projects/{project.id}'), headers=await as_('member'))

    assert (await db_session.scalars(select(Task))).all() == []


MARKS = [('projects', 'favourite'), ('tasks', 'watch'), ('tasks', 'vote')]


@pytest.fixture
async def task(new, project):
    return await new(Task, project_id=project.id)


def marked(at, table, word, project, task):
    row = project if table == 'projects' else task
    return at(f'/{table}/{row.id}/{word}')


@pytest.mark.parametrize('table, word', MARKS)
async def test_a_mark_is_put_once(client, as_, at, project, task, table, word):
    path = marked(at, table, word, project, task)
    counts = [(await client.put(path, headers=await as_('member'))).json()['count'] for _ in range(2)]

    assert counts == [1, 1]


@pytest.mark.parametrize('table, word', MARKS)
async def test_marks_are_counted(client, as_, at, project, task, table, word):
    path = marked(at, table, word, project, task)
    for name in ('member', 'peer', 'guest'):
        response = await client.put(path, headers=await as_(name))

    assert response.json() == {'count': 3}


@pytest.mark.parametrize('table, word', MARKS)
async def test_a_mark_taken_off(client, as_, at, project, task, table, word):
    path = marked(at, table, word, project, task)
    await client.put(path, headers=await as_('member'))
    await client.put(path, headers=await as_('peer'))
    counts = [(await client.delete(path, headers=await as_('member'))).json()['count'] for _ in range(2)]

    assert counts == [1, 1]


@pytest.mark.parametrize('table, word', MARKS)
async def test_a_mark_on_nothing(client, as_, at, table, word):
    assert (await client.put(at(f'/{table}/999999/{word}'), headers=await as_('member'))).status_code == 404


@pytest.mark.parametrize('table, word', MARKS)
async def test_a_mark_is_for_members(client, as_, at, org, project, task, table, word):
    path = marked(at, table, word, project, task)

    assert (await client.put(path, headers=await as_('outsider'))).status_code == 404
    assert (await client.put(path)).status_code == 401
