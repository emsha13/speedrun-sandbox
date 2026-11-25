"""Dashboards, reports, goals, surveys — and the audit record."""
from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.models import now
from app.settings import settings
from app.workspace import outside
from app.workspace.access import Context, Guest, Member
from app.workspace.crud import RowId, find, out_of, resource
from app.workspace.models.crm import Deal
from app.workspace.models.helpdesk import Ticket
from app.workspace.models.orgs import MemberRole
from app.workspace.models.reports import AuditRecord, CheckIn, Dashboard, Goal, KeyResult, Report, ReportRun, Subject
from app.workspace.models.tasks import Task, TimeEntry

router = APIRouter(tags=['reports'])
ADMIN = MemberRole.ADMIN


class Progress(BaseModel):
    goal_id: int
    key_results: int
    percent: int


async def figures(context: Context, subject: Subject) -> dict:
    """What a report of the subject says now."""
    session, org = context.session, context.org_id
    if subject == Subject.TASKS:
        total, done = (await session.execute(
            select(func.count(), func.count(Task.completed_at)).where(Task.organisation_id == org)
        )).one()
        return {'total': total, 'done': done}
    if subject == Subject.TICKETS:
        rows = await session.execute(
            select(Ticket.status, func.count()).where(Ticket.organisation_id == org).group_by(Ticket.status)
        )
        return {status_: count for status_, count in rows}
    if subject == Subject.DEALS:
        count, amount = (await session.execute(
            select(func.count(), func.coalesce(func.sum(Deal.amount), 0)).where(Deal.organisation_id == org)
        )).one()
        return {'count': count, 'amount': str(amount)}
    minutes = await session.scalar(
        select(func.coalesce(func.sum(TimeEntry.minutes), 0)).where(TimeEntry.organisation_id == org)
    )
    return {'minutes': minutes}


@router.post('/reports/{row_id}/run', response_model=out_of(ReportRun), status_code=status.HTTP_201_CREATED)
async def run_report(row_id: RowId, context: Member):
    report = await find(context, Report, row_id)
    result = await figures(context, report.subject)
    if settings.ANTHROPIC_API_KEY:
        result['summary'] = await outside.summarise(result)
    run = ReportRun(organisation_id=context.org_id, report_id=report.id, run_by_id=context.user.id, result=result)
    context.session.add(run)
    await context.session.commit()
    return run


@router.get('/goals/{row_id}/progress', response_model=Progress)
async def goal_progress(row_id: RowId, context: Guest):
    """How far the goal is: the mean of how far each key result is, each counted to its target
    and no further."""
    goal = await find(context, Goal, row_id)
    results = (await context.session.scalars(select(KeyResult).where(KeyResult.goal_id == goal.id))).all()
    shares = [min(result.reached / result.target, Decimal(1)) if result.target else Decimal(1) for result in results]
    percent = int(sum(shares) * 100 / len(shares)) if shares else 0
    return Progress(goal_id=goal.id, key_results=len(results), percent=percent)


async def dates_in_order(context: Context, row, old) -> None:
    if row.ends_on < row.starts_on:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'it ends before it starts')





async def a_check_in_on_a_monday(context: Context, check_in: CheckIn, old) -> None:
    if check_in.week_of.weekday() != 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'a week starts on a Monday')
    if check_in.week_of > now().date():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'that week has not come')


resource(router, AuditRecord, methods='list', read=ADMIN)
resource(router, Dashboard, author='owner_id', own=True, search=('name',))
resource(router, Report, author='author_id', own=True, search=('name',))
resource(router, Goal, search=('title',), check=dates_in_order)
resource(router, KeyResult, methods='list create update delete')
resource(router, CheckIn, author='user_id', own=True, check=a_check_in_on_a_monday)
