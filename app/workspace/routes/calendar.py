"""Calendars, events and rooms."""
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import AwareDatetime, BaseModel, ConfigDict
from sqlalchemy import or_, select

from app.workspace.access import Context, Guest
from app.workspace.crud import RowId, find, out_of, resource
from app.workspace.models.calendar import Absence, Answer, Calendar, Event, EventAttendee, EventStatus, Room
from app.workspace.models.orgs import MemberRole

router = APIRouter(tags=['calendar'])
ADMIN = MemberRole.ADMIN
EventOut = out_of(Event)


class Reply(BaseModel):
    answer: Answer


class Window(BaseModel):
    model_config = ConfigDict(extra='forbid')

    starts_at: AwareDatetime
    ends_at: AwareDatetime


async def an_event_that_fits(context: Context, event: Event, old) -> None:
    if event.ends_at <= event.starts_at:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'it ends before it starts')
    if event.room_id is None or event.status == EventStatus.CANCELLED:
        return
    # Two stretches of time overlap when each starts before the other ends.
    others = select(Event.id).where(
        Event.room_id == event.room_id, Event.status != EventStatus.CANCELLED,
        Event.starts_at < event.ends_at, Event.ends_at > event.starts_at,
    )
    if old is not None:
        others = others.where(Event.id != event.id)
    if await context.session.scalar(others.limit(1)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, 'the room is taken')


async def dates_in_order(context: Context, row, old) -> None:
    if row.ends_on < row.starts_on:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'it ends before it starts')



@router.post('/events/{row_id}/answer', response_model=out_of(EventAttendee))
async def answer_invitation(row_id: RowId, data: Reply, context: Guest):
    await find(context, Event, row_id)
    attendee = await context.session.scalar(
        select(EventAttendee).where(EventAttendee.event_id == row_id, EventAttendee.user_id == context.user.id)
    )
    if attendee is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, 'not invited')
    if data.answer == Answer.PENDING:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'that is no answer')
    attendee.answer = data.answer
    await context.session.commit()
    return attendee


@router.get('/agenda', response_model=list[EventOut])
async def read_agenda(window: Annotated[Window, Query()], context: Guest):
    """What the caller has on in the window: the events they organise and the ones they are
    invited to and have not declined."""
    if window.ends_at <= window.starts_at:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'it ends before it starts')
    invited = select(EventAttendee.event_id).where(
        EventAttendee.user_id == context.user.id, EventAttendee.answer != Answer.NO
    )
    rows = await context.session.scalars(
        select(Event).where(
            Event.organisation_id == context.org_id, Event.status != EventStatus.CANCELLED,
            Event.starts_at < window.ends_at, Event.ends_at > window.starts_at,
            or_(Event.organiser_id == context.user.id, Event.id.in_(invited)),
        ).order_by(Event.starts_at, Event.id)
    )
    return rows.all()


resource(router, Calendar, search=('name',))
resource(router, Room, write=ADMIN, search=('name',))
resource(router, Event, search=('title', 'description', 'location'), author='organiser_id', check=an_event_that_fits)
resource(router, EventAttendee, methods='list read create delete')
resource(router, Absence, author='user_id', own=True, check=dates_in_order)
