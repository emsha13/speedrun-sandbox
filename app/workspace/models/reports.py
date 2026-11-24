"""What the organisation looks at to see how it is doing — and the record of who did what."""
import enum

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped

from app.db import Base
from app.workspace.base import Owned, col, loose, moment, ref
from app.workspace.models.calendar import Frequency
from app.workspace.models.projects import Health


class Subject(enum.StrEnum):
    TASKS = 'tasks'
    TICKETS = 'tickets'
    DEALS = 'deals'
    TIME = 'time'


class QuestionKind(enum.StrEnum):
    TEXT = 'text'
    SCALE = 'scale'
    CHOICE = 'choice'


class AuditRecord(Owned, Base):
    """Who changed what. Written by the doors of the tables that ask for it."""
    __tablename__ = 'audit_records'

    actor_id: Mapped[int | None] = loose('users')
    action: Mapped[str] = col(String(10))
    subject: Mapped[str] = col(String(40))
    subject_id: Mapped[int]


class Dashboard(Owned, Base):
    __tablename__ = 'dashboards'

    name: Mapped[str] = col(String(80))
    owner_id: Mapped[int | None] = loose('users', managed=True)
    is_shared: Mapped[bool] = col(default=False)


class Widget(Owned, Base):
    __tablename__ = 'widgets'

    dashboard_id: Mapped[int] = ref('dashboards', fixed=True)
    title: Mapped[str] = col(String(80))
    kind: Mapped[str] = col(String(30))
    options: Mapped[dict[str, Any]] = col(JSONB, default=dict)
    position: Mapped[int] = col(default=0, ge=0)


class Report(Owned, Base):
    __tablename__ = 'reports'

    name: Mapped[str] = col(String(80))
    subject: Mapped[Subject] = col(String(10), fixed=True)
    author_id: Mapped[int | None] = loose('users', managed=True)


class ReportRun(Owned, Base):
    """What a report said at the moment it was run."""
    __tablename__ = 'report_runs'

    report_id: Mapped[int] = ref('reports')
    run_by_id: Mapped[int | None] = loose('users')
    result: Mapped[dict[str, Any]] = col(JSONB, default=dict)


class ReportSchedule(Owned, Base):
    __tablename__ = 'report_schedules'

    report_id: Mapped[int] = ref('reports', fixed=True)
    frequency: Mapped[Frequency] = col(String(10))
    hour: Mapped[int] = col(default=8, ge=0, le=23)
    recipients: Mapped[list[str]] = col(JSONB, default=list)
    is_paused: Mapped[bool] = col(default=False)


class Goal(Owned, Base):
    __tablename__ = 'goals'

    title: Mapped[str] = col(String(200))
    owner_id: Mapped[int | None] = loose('users')
    team_id: Mapped[int | None] = loose('teams')
    starts_on: Mapped[date]
    ends_on: Mapped[date]
    health: Mapped[Health] = col(String(10), default=Health.ON_TRACK)


class KeyResult(Owned, Base):
    __tablename__ = 'key_results'

    goal_id: Mapped[int] = ref('goals', fixed=True)
    title: Mapped[str] = col(String(200))
    unit: Mapped[str | None] = col(String(20))
    target: Mapped[Decimal] = col(Numeric(12, 2))
    reached: Mapped[Decimal] = col(Numeric(12, 2), default=Decimal('0.00'))


class Metric(Owned, Base):
    __tablename__ = 'metrics'
    __table_args__ = (UniqueConstraint('organisation_id', 'name'),)

    name: Mapped[str] = col(String(60), pattern=r'^[a-z][a-z0-9_.]*$')
    title: Mapped[str] = col(String(120))
    unit: Mapped[str | None] = col(String(20))


class MetricPoint(Owned, Base):
    __tablename__ = 'metric_points'
    __table_args__ = (UniqueConstraint('metric_id', 'day'),)

    metric_id: Mapped[int] = ref('metrics', fixed=True)
    day: Mapped[date] = col(fixed=True)
    value: Mapped[Decimal] = col(Numeric(14, 4))


class Survey(Owned, Base):
    __tablename__ = 'surveys'

    title: Mapped[str] = col(String(200))
    is_anonymous: Mapped[bool] = col(default=True, fixed=True)
    closes_on: Mapped[date | None]
    author_id: Mapped[int | None] = loose('users', managed=True)


class SurveyQuestion(Owned, Base):
    __tablename__ = 'survey_questions'

    survey_id: Mapped[int] = ref('surveys', fixed=True)
    text: Mapped[str] = col(String(300))
    kind: Mapped[QuestionKind] = col(String(10), default=QuestionKind.TEXT)
    choices: Mapped[list[str]] = col(JSONB, default=list)
    position: Mapped[int] = col(default=0, ge=0)


class SurveyResponse(Owned, Base):
    __tablename__ = 'survey_responses'

    survey_id: Mapped[int] = ref('surveys')
    # Empty when the survey is anonymous.
    user_id: Mapped[int | None] = loose('users')
    submitted_at: Mapped[datetime | None] = moment()


class SurveyAnswer(Owned, Base):
    __tablename__ = 'survey_answers'
    __table_args__ = (UniqueConstraint('response_id', 'question_id'),)

    response_id: Mapped[int] = ref('survey_responses')
    question_id: Mapped[int] = ref('survey_questions')
    value: Mapped[str] = col(Text)


class CheckIn(Owned, Base):
    """A member's week in three answers."""
    __tablename__ = 'check_ins'
    __table_args__ = (UniqueConstraint('organisation_id', 'user_id', 'week_of'),)

    user_id: Mapped[int] = ref('users', managed=True)
    week_of: Mapped[date] = col(fixed=True)
    mood: Mapped[int] = col(ge=1, le=5)
    wins: Mapped[str | None] = col(Text)
    blockers: Mapped[str | None] = col(Text)
