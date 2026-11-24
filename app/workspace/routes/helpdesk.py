"""The help desk."""
from datetime import timedelta

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.models import now
from app.workspace.access import Context, Member
from app.workspace.crud import RowId, find, mark, out_of, resource
from app.workspace.models.helpdesk import (
    Article, ArticleFeedback, Queue, Rating, SlaPolicy, Ticket, TicketEvent, TicketMessage, TicketStatus, TicketWatcher,
)
from app.workspace.models.orgs import MemberRole

router = APIRouter(tags=['helpdesk'])
ADMIN = MemberRole.ADMIN
TicketOut = out_of(Ticket)
# The step, the statuses it may be taken from, and the status it leads to.
STEPS = {
    'solve': ((TicketStatus.OPEN, TicketStatus.PENDING), TicketStatus.SOLVED),
    'reopen': ((TicketStatus.SOLVED,), TicketStatus.OPEN),
    'close': ((TicketStatus.SOLVED,), TicketStatus.CLOSED),
}


class Feedback(BaseModel):
    did_help: bool


async def a_ticket_with_its_deadlines(context: Context, ticket: Ticket, old) -> None:
    session = context.session
    if old is None:
        last = await session.scalar(
            select(func.max(Ticket.number)).where(Ticket.organisation_id == context.org_id)
        )
        ticket.number = (last or 0) + 1
        if ticket.assignee_id is None:
            ticket.assignee_id = (await session.get(Queue, ticket.queue_id)).default_assignee_id
    elif ticket.status == TicketStatus.CLOSED:
        raise HTTPException(status.HTTP_409_CONFLICT, 'the ticket is closed')
    if old is None or 'priority' in old:
        policy = await session.scalar(
            select(SlaPolicy).where(
                SlaPolicy.organisation_id == context.org_id, SlaPolicy.priority == (ticket.priority or 'normal')
            )
        )
        opened = ticket.created_at or now()
        ticket.respond_by = opened + timedelta(minutes=policy.first_response_minutes) if policy else None
        ticket.solve_by = opened + timedelta(minutes=policy.resolution_minutes) if policy else None


async def a_message_on_an_open_ticket(context: Context, message: TicketMessage, old) -> None:
    ticket = await context.session.get(Ticket, message.ticket_id)
    if ticket.status == TicketStatus.CLOSED:
        raise HTTPException(status.HTTP_409_CONFLICT, 'the ticket is closed')
    if message.is_internal:
        return
    # The first answer the requester can read is what the promise of a first response is about.
    if ticket.first_response_at is None:
        ticket.first_response_at = now()
    if ticket.status == TicketStatus.OPEN:
        ticket.status = TicketStatus.PENDING


async def a_rating_of_a_solved_ticket(context: Context, rating: Rating, old) -> None:
    ticket = await context.session.get(Ticket, rating.ticket_id)
    if ticket.status not in (TicketStatus.SOLVED, TicketStatus.CLOSED):
        raise HTTPException(status.HTTP_409_CONFLICT, 'the ticket is not solved')


def step(name: str) -> None:
    allowed, leads_to = STEPS[name]

    @router.post(f'/tickets/{{row_id}}/{name}', response_model=TicketOut, name=f'{name}_ticket')
    async def take_step(row_id: RowId, context: Member):
        ticket = await find(context, Ticket, row_id)
        if ticket.status not in allowed:
            raise HTTPException(status.HTTP_409_CONFLICT, f'the ticket is {ticket.status}')
        ticket.status = leads_to
        ticket.solved_at = now() if name == 'solve' else None if name == 'reopen' else ticket.solved_at
        ticket.updated_at = now()
        context.session.add(TicketEvent(
            organisation_id=context.org_id, ticket_id=ticket.id, kind=name, actor_id=context.user.id,
        ))
        await context.session.commit()
        return ticket


for name in STEPS:
    step(name)


@router.post('/articles/{row_id}/feedback', response_model=out_of(Article))
async def rate_article(row_id: RowId, data: Feedback, context: Member):
    """One opinion a member: a second one replaces the first."""
    article = await find(context, Article, row_id)
    mine = await context.session.scalar(
        select(ArticleFeedback).where(
            ArticleFeedback.article_id == row_id, ArticleFeedback.user_id == context.user.id
        )
    )
    if mine is None:
        context.session.add(ArticleFeedback(
            organisation_id=context.org_id, article_id=row_id, user_id=context.user.id, did_help=data.did_help,
        ))
    elif mine.did_help != data.did_help:
        if mine.did_help:
            article.helped -= 1
        else:
            article.did_not_help -= 1
        mine.did_help = data.did_help
    else:
        return article
    if data.did_help:
        article.helped += 1
    else:
        article.did_not_help += 1
    await context.session.commit()
    return article


mark(router, Ticket, TicketWatcher, 'ticket_id', 'watch')

resource(router, Queue, write=ADMIN, search=('name',))
resource(router, SlaPolicy, methods='list create delete', write=ADMIN, audited=True)
resource(router, Ticket, search=('subject', 'requester_email'), check=a_ticket_with_its_deadlines)
resource(
    router, TicketMessage, methods='list read create', author='author_id', check=a_message_on_an_open_ticket,
)
resource(router, Rating, methods='list read create', check=a_rating_of_a_solved_ticket)
resource(router, Article, author='author_id', search=('title', 'body'))
