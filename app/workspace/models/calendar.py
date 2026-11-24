"""Calendars, events, rooms, and who is away."""
import enum

from datetime import date, datetime, time

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped

from app.db import Base
from app.workspace.base import COLOR, EMAIL, SLUG, Owned, col, loose, moment, ref


class EventStatus(enum.StrEnum):
    CONFIRMED = 'confirmed'
    TENTATIVE = 'tentative'
    CANCELLED = 'cancelled'


class Answer(enum.StrEnum):
    PENDING = 'pending'
    YES = 'yes'
    NO = 'no'
    MAYBE = 'maybe'


class Frequency(enum.StrEnum):
    DAILY = 'daily'
    WEEKLY = 'weekly'
    MONTHLY = 'monthly'
    YEARLY = 'yearly'


class Channel(enum.StrEnum):
    EMAIL = 'email'
    PUSH = 'push'
    IN_APP = 'in_app'


class Calendar(Owned, Base):
    __tablename__ = 'calendars'

    name: Mapped[str] = col(String(80))
    color: Mapped[str] = col(String(7), default='#3366cc', pattern=COLOR)
    owner_id: Mapped[int | None] = loose('users')
    is_shared: Mapped[bool] = col(default=True)
    timezone: Mapped[str] = col(String(40), default='UTC')


class CalendarSubscription(Owned, Base):
    __tablename__ = 'calendar_subscriptions'
    __table_args__ = (UniqueConstraint('calendar_id', 'user_id'),)

    calendar_id: Mapped[int] = ref('calendars', fixed=True)
    user_id: Mapped[int] = ref('users', managed=True)
    color: Mapped[str | None] = col(String(7), pattern=COLOR)
    is_hidden: Mapped[bool] = col(default=False)


class Recurrence(Owned, Base):
    __tablename__ = 'recurrences'

    frequency: Mapped[Frequency] = col(String(10))
    interval: Mapped[int] = col(default=1, ge=1, le=365)
    count: Mapped[int | None] = col(ge=1, le=1000)
    until: Mapped[date | None]


class Room(Owned, Base):
    __tablename__ = 'rooms'
    __table_args__ = (UniqueConstraint('organisation_id', 'name'),)

    name: Mapped[str] = col(String(60))
    office_id: Mapped[int | None] = loose('offices')
    floor: Mapped[int | None] = col(ge=-10, le=200)
    capacity: Mapped[int] = col(default=4, ge=1, le=1000)
    has_video: Mapped[bool] = col(default=False)


class RoomEquipment(Owned, Base):
    __tablename__ = 'room_equipment'

    room_id: Mapped[int] = ref('rooms', fixed=True)
    name: Mapped[str] = col(String(60))
    quantity: Mapped[int] = col(default=1, ge=1, le=1000)


class Event(Owned, Base):
    __tablename__ = 'events'

    calendar_id: Mapped[int] = ref('calendars')
    title: Mapped[str] = col(String(200))
    description: Mapped[str | None] = col(Text)
    starts_at: Mapped[datetime] = moment()
    ends_at: Mapped[datetime] = moment()
    is_all_day: Mapped[bool] = col(default=False)
    location: Mapped[str | None] = col(String(200))
    room_id: Mapped[int | None] = loose('rooms')
    recurrence_id: Mapped[int | None] = loose('recurrences')
    organiser_id: Mapped[int | None] = loose('users', managed=True)
    status: Mapped[EventStatus] = col(String(10), default=EventStatus.CONFIRMED)


class EventAttendee(Owned, Base):
    __tablename__ = 'event_attendees'
    __table_args__ = (UniqueConstraint('event_id', 'user_id'),)

    event_id: Mapped[int] = ref('events', fixed=True)
    user_id: Mapped[int] = ref('users', fixed=True)
    is_optional: Mapped[bool] = col(default=False)
    answer: Mapped[Answer] = col(String(10), default=Answer.PENDING, managed=True)


class EventReminder(Owned, Base):
    __tablename__ = 'event_reminders'

    event_id: Mapped[int] = ref('events', fixed=True)
    user_id: Mapped[int | None] = loose('users', managed=True)
    minutes_before: Mapped[int] = col(ge=0, le=40320)
    channel: Mapped[Channel] = col(String(10), default=Channel.IN_APP)


class EventCategory(Owned, Base):
    __tablename__ = 'event_categories'
    __table_args__ = (UniqueConstraint('organisation_id', 'name'),)

    name: Mapped[str] = col(String(40))
    color: Mapped[str] = col(String(7), default='#888888', pattern=COLOR)


class EventCategoryLink(Owned, Base):
    __tablename__ = 'event_category_links'
    __table_args__ = (UniqueConstraint('event_id', 'category_id'),)

    event_id: Mapped[int] = ref('events')
    category_id: Mapped[int] = ref('event_categories')


class MeetingNote(Owned, Base):
    __tablename__ = 'meeting_notes'

    event_id: Mapped[int] = ref('events', fixed=True)
    author_id: Mapped[int | None] = loose('users', managed=True)
    body: Mapped[str] = col(Text)
    decisions: Mapped[str | None] = col(Text)


class ActionItem(Owned, Base):
    """What somebody said at a meeting they would do."""
    __tablename__ = 'action_items'

    note_id: Mapped[int] = ref('meeting_notes', fixed=True)
    text: Mapped[str] = col(String(300))
    assignee_id: Mapped[int | None] = loose('users')
    due_on: Mapped[date | None]
    is_done: Mapped[bool] = col(default=False)


class WorkingHours(Owned, Base):
    __tablename__ = 'working_hours'
    __table_args__ = (UniqueConstraint('organisation_id', 'user_id', 'weekday'),)

    user_id: Mapped[int] = ref('users', managed=True)
    weekday: Mapped[int] = col(ge=0, le=6)
    opens: Mapped[time]
    closes: Mapped[time]


class Absence(Owned, Base):
    """Out of the office: the dates, what a sender is told, and who answers meanwhile."""
    __tablename__ = 'absences'

    user_id: Mapped[int | None] = loose('users', managed=True)
    starts_on: Mapped[date]
    ends_on: Mapped[date]
    message: Mapped[str | None] = col(String(500))
    delegate_id: Mapped[int | None] = loose('users')


class BookingPage(Owned, Base):
    """A page where somebody outside picks a time with somebody inside."""
    __tablename__ = 'booking_pages'

    slug: Mapped[str] = col(String(40), unique=True, pattern=SLUG)
    title: Mapped[str] = col(String(120))
    owner_id: Mapped[int | None] = loose('users', managed=True)
    minutes: Mapped[int] = col(default=30, ge=5, le=480)
    is_active: Mapped[bool] = col(default=True)


class Booking(Owned, Base):
    __tablename__ = 'bookings'

    page_id: Mapped[int] = ref('booking_pages', fixed=True)
    guest_name: Mapped[str] = col(String(100))
    guest_email: Mapped[str] = col(String(254), pattern=EMAIL)
    starts_at: Mapped[datetime] = moment()
    is_cancelled: Mapped[bool] = col(default=False)
