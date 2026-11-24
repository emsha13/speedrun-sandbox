"""The help desk: tickets, what is promised about them, and the articles that save writing one."""
import enum

from datetime import datetime, time
from typing import Any

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped

from app.db import Base
from app.workspace.base import EMAIL, Owned, col, loose, moment, ref
from app.workspace.models.docs import DocumentStatus
from app.workspace.models.tasks import Priority


class TicketStatus(enum.StrEnum):
    OPEN = 'open'
    PENDING = 'pending'
    SOLVED = 'solved'
    CLOSED = 'closed'


class Source(enum.StrEnum):
    EMAIL = 'email'
    WEB = 'web'
    PHONE = 'phone'
    CHAT = 'chat'


class Queue(Owned, Base):
    __tablename__ = 'queues'
    __table_args__ = (UniqueConstraint('organisation_id', 'name'),)

    name: Mapped[str] = col(String(60))
    email: Mapped[str | None] = col(String(254), pattern=EMAIL)
    description: Mapped[str | None] = col(Text)
    default_assignee_id: Mapped[int | None] = loose('users')
    is_active: Mapped[bool] = col(default=True)


class SlaPolicy(Owned, Base):
    """How soon a ticket of a priority is answered and how soon it is solved."""
    __tablename__ = 'sla_policies'
    __table_args__ = (UniqueConstraint('organisation_id', 'priority'),)

    name: Mapped[str] = col(String(60))
    priority: Mapped[Priority] = col(String(10))
    first_response_minutes: Mapped[int] = col(ge=1, le=100000)
    resolution_minutes: Mapped[int] = col(ge=1, le=1000000)


class Ticket(Owned, Base):
    __tablename__ = 'tickets'
    __table_args__ = (UniqueConstraint('organisation_id', 'number'),)

    queue_id: Mapped[int] = ref('queues')
    number: Mapped[int] = col(managed=True)
    subject: Mapped[str] = col(String(200))
    description: Mapped[str | None] = col(Text)
    requester_email: Mapped[str] = col(String(254), pattern=EMAIL)
    contact_id: Mapped[int | None] = loose('contacts')
    priority: Mapped[Priority] = col(String(10), default=Priority.NORMAL)
    source: Mapped[Source] = col(String(10), default=Source.WEB, fixed=True)
    assignee_id: Mapped[int | None] = loose('users')
    status: Mapped[TicketStatus] = col(String(10), default=TicketStatus.OPEN, managed=True)
    # Both come from the policy for the ticket's priority, counted from when it was opened.
    respond_by: Mapped[datetime | None] = moment(managed=True)
    solve_by: Mapped[datetime | None] = moment(managed=True)
    first_response_at: Mapped[datetime | None] = moment(managed=True)
    solved_at: Mapped[datetime | None] = moment(managed=True)
    updated_at: Mapped[datetime | None] = moment(managed=True)


class TicketMessage(Owned, Base):
    __tablename__ = 'ticket_messages'

    ticket_id: Mapped[int] = ref('tickets', fixed=True)
    author_id: Mapped[int | None] = loose('users', managed=True)
    body: Mapped[str] = col(Text)
    # A note among the staff: the requester does not see it, and it is no answer to them.
    is_internal: Mapped[bool] = col(default=False, fixed=True)


class TicketTag(Owned, Base):
    __tablename__ = 'ticket_tags'
    __table_args__ = (UniqueConstraint('organisation_id', 'name'),)

    name: Mapped[str] = col(String(40))


class TicketTagLink(Owned, Base):
    __tablename__ = 'ticket_tag_links'
    __table_args__ = (UniqueConstraint('ticket_id', 'tag_id'),)

    ticket_id: Mapped[int] = ref('tickets')
    tag_id: Mapped[int] = ref('ticket_tags')


class TicketWatcher(Owned, Base):
    __tablename__ = 'ticket_watchers'
    __table_args__ = (UniqueConstraint('ticket_id', 'user_id'),)

    ticket_id: Mapped[int] = ref('tickets')
    user_id: Mapped[int] = ref('users')


class TicketEvent(Owned, Base):
    """What happened to a ticket, in order."""
    __tablename__ = 'ticket_events'

    ticket_id: Mapped[int] = ref('tickets')
    kind: Mapped[str] = col(String(30))
    actor_id: Mapped[int | None] = loose('users')


class TicketLink(Owned, Base):
    """The task somebody has to do before the ticket can be solved."""
    __tablename__ = 'ticket_links'
    __table_args__ = (UniqueConstraint('ticket_id', 'task_id'),)

    ticket_id: Mapped[int] = ref('tickets')
    task_id: Mapped[int] = ref('tasks')


class Rating(Owned, Base):
    __tablename__ = 'ratings'
    __table_args__ = (UniqueConstraint('ticket_id'),)

    ticket_id: Mapped[int] = ref('tickets', fixed=True)
    score: Mapped[int] = col(ge=1, le=5)
    comment: Mapped[str | None] = col(String(1000))


class CannedResponse(Owned, Base):
    __tablename__ = 'canned_responses'

    title: Mapped[str] = col(String(80))
    shortcut: Mapped[str | None] = col(String(30))
    body: Mapped[str] = col(Text)
    queue_id: Mapped[int | None] = loose('queues')


class Macro(Owned, Base):
    __tablename__ = 'macros'

    name: Mapped[str] = col(String(80))
    author_id: Mapped[int | None] = loose('users', managed=True)
    actions: Mapped[list[dict[str, Any]]] = col(JSONB, default=list)
    is_shared: Mapped[bool] = col(default=True)


class TicketForm(Owned, Base):
    __tablename__ = 'ticket_forms'

    name: Mapped[str] = col(String(80))
    queue_id: Mapped[int] = ref('queues')
    layout: Mapped[list[dict[str, Any]]] = col(JSONB, default=list)
    is_active: Mapped[bool] = col(default=True)


class BusinessHours(Owned, Base):
    __tablename__ = 'business_hours'
    __table_args__ = (UniqueConstraint('queue_id', 'weekday'),)

    queue_id: Mapped[int] = ref('queues', fixed=True)
    weekday: Mapped[int] = col(ge=0, le=6)
    opens: Mapped[time]
    closes: Mapped[time]


class EscalationRule(Owned, Base):
    __tablename__ = 'escalation_rules'

    queue_id: Mapped[int] = ref('queues')
    name: Mapped[str] = col(String(80))
    after_minutes: Mapped[int] = col(ge=1, le=100000)
    notify_team_id: Mapped[int | None] = loose('teams')
    is_active: Mapped[bool] = col(default=True)


class ArticleCategory(Owned, Base):
    __tablename__ = 'article_categories'

    name: Mapped[str] = col(String(80))
    parent_id: Mapped[int | None] = loose('article_categories')
    position: Mapped[int] = col(default=0, ge=0)


class Article(Owned, Base):
    __tablename__ = 'articles'

    category_id: Mapped[int | None] = loose('article_categories')
    title: Mapped[str] = col(String(200))
    body: Mapped[str] = col(Text)
    status: Mapped[DocumentStatus] = col(String(10), default=DocumentStatus.DRAFT)
    author_id: Mapped[int | None] = loose('users', managed=True)
    helped: Mapped[int] = col(default=0, managed=True)
    did_not_help: Mapped[int] = col(default=0, managed=True)


class ArticleFeedback(Owned, Base):
    __tablename__ = 'article_feedback'
    __table_args__ = (UniqueConstraint('article_id', 'user_id'),)

    article_id: Mapped[int] = ref('articles')
    user_id: Mapped[int] = ref('users')
    did_help: Mapped[bool]
