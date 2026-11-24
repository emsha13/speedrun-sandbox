"""Projects, their sprints and releases, and the tasks in them."""
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, update

from app.models import now
from app.workspace.access import Context, Member
from app.workspace.crud import RowId, find, mark, out_of, resource
from app.workspace.models.orgs import MemberRole
from app.workspace.models.projects import (
    Label, Milestone, Project, ProjectFavourite, Release, Sprint, SprintStatus, StatusCategory, TaskStatus,
)
from app.workspace.models.tasks import Task, TaskComment, TaskStatusChange, TaskVote, TaskWatcher, TimeEntry

router = APIRouter(tags=['projects'])
ADMIN = MemberRole.ADMIN


async def a_task_in_its_place(context: Context, task: Task, old) -> None:
    session = context.session
    if old is None:
        # The project's row is locked while its counter is read and moved on, so two tasks made
        # at once do not get one number.
        project = await session.get(Project, task.project_id, with_for_update=True)
        task.number = project.next_number
        project.next_number += 1
    elif task.parent_id == task.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'a task is not its own parent')
    if old is None or 'status_id' in old and old['status_id'] != task.status_id:
        to = await session.get(TaskStatus, task.status_id) if task.status_id else None
        task.completed_at = now() if to is not None and to.category == StatusCategory.DONE else None
        if old is not None:
            session.add(TaskStatusChange(
                organisation_id=context.org_id, task_id=task.id, from_status_id=old['status_id'],
                to_status_id=task.status_id, changed_by_id=context.user.id,
            ))



async def dates_in_order(context: Context, row, old) -> None:
    if row.starts_on and row.ends_on and row.ends_on < row.starts_on:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'it ends before it starts')


@router.post('/sprints/{row_id}/start', response_model=out_of(Sprint))
async def start_sprint(row_id: RowId, context: Member):
    sprint = await find(context, Sprint, row_id)
    if sprint.status != SprintStatus.PLANNED:
        raise HTTPException(status.HTTP_409_CONFLICT, f'the sprint is {sprint.status}')
    running = await context.session.scalar(
        select(Sprint.id).where(Sprint.project_id == sprint.project_id, Sprint.status == SprintStatus.ACTIVE)
    )
    if running is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, 'the project has a sprint running')
    sprint.status, sprint.started_at = SprintStatus.ACTIVE, now()
    await context.session.commit()
    return sprint


@router.post('/sprints/{row_id}/complete', response_model=out_of(Sprint))
async def complete_sprint(row_id: RowId, context: Member):
    sprint = await find(context, Sprint, row_id)
    if sprint.status != SprintStatus.ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, f'the sprint is {sprint.status}')
    sprint.status, sprint.completed_at = SprintStatus.COMPLETED, now()
    # What was not finished goes back to the backlog; what was stays, as the sprint's record.
    await context.session.execute(
        update(Task).where(Task.sprint_id == sprint.id, Task.completed_at.is_(None)).values(sprint_id=None)
    )
    await context.session.commit()
    return sprint


@router.post('/releases/{row_id}/publish', response_model=out_of(Release))
async def publish_release(row_id: RowId, context: Member):
    release = await find(context, Release, row_id)
    if release.released_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, 'the release is out')
    unfinished = await context.session.scalar(
        select(Task.id).where(Task.release_id == release.id, Task.completed_at.is_(None)).limit(1)
    )
    if unfinished is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, 'the release has unfinished tasks')
    release.released_at = now()
    await context.session.commit()
    return release


mark(router, Project, ProjectFavourite, 'project_id', 'favourite')
mark(router, Task, TaskWatcher, 'task_id', 'watch')
mark(router, Task, TaskVote, 'task_id', 'vote')

resource(router, Project, search=('name', 'key', 'description'), audited=True)
resource(router, Milestone, search=('name',))
resource(router, Sprint, search=('name',), check=dates_in_order)
resource(router, TaskStatus, methods='list create delete', write=ADMIN)
resource(router, Label, search=('name',))
resource(router, Release, search=('name',))

resource(router, Task, search=('title', 'description'), author='reporter_id', check=a_task_in_its_place)
resource(router, TaskComment, author='author_id', own=True, search=('body',))
resource(router, TimeEntry, author='user_id', own=True)
