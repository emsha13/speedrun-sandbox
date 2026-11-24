"""Organisations and the people in them."""
import enum

from datetime import date, datetime

from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models import now
from app.workspace.base import COLOR, COUNTRY, Owned, col, loose, moment, ref


class Plan(enum.StrEnum):
    FREE = 'free'
    TEAM = 'team'
    BUSINESS = 'business'


class MemberRole(enum.StrEnum):
    GUEST = 'guest'
    MEMBER = 'member'
    ADMIN = 'admin'
    OWNER = 'owner'


class TimeOffKind(enum.StrEnum):
    VACATION = 'vacation'
    SICK = 'sick'
    UNPAID = 'unpaid'


class Decision(enum.StrEnum):
    PENDING = 'pending'
    APPROVED = 'approved'
    REJECTED = 'rejected'


class Organisation(Base):
    __tablename__ = 'organisations'

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    plan: Mapped[Plan] = mapped_column(String(10), default=Plan.FREE)
    timezone: Mapped[str] = mapped_column(String(40), default='UTC')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Membership(Owned, Base):
    """Who is in the organisation, and as what. Whoever owns it is a member like the rest: there
    is no owner written on the organisation to fall out of step with this table."""
    __tablename__ = 'memberships'
    __table_args__ = (UniqueConstraint('organisation_id', 'user_id'),)

    user_id: Mapped[int] = ref('users')
    role: Mapped[MemberRole] = col(String(10), default=MemberRole.MEMBER)
    title: Mapped[str | None] = col(String(80))


class Invitation(Owned, Base):
    __tablename__ = 'invitations'

    email: Mapped[str] = col(String(254))
    role: Mapped[MemberRole] = col(String(10), default=MemberRole.MEMBER)
    # The token goes out in the letter and is not kept, only its digest.
    token_digest: Mapped[str] = col(String(64), unique=True, hidden=True)
    invited_by_id: Mapped[int | None] = loose('users')
    expires_at: Mapped[datetime] = moment()
    accepted_at: Mapped[datetime | None] = moment()


class Team(Owned, Base):
    __tablename__ = 'teams'
    __table_args__ = (UniqueConstraint('organisation_id', 'name'),)

    name: Mapped[str] = col(String(60))
    description: Mapped[str | None] = col(Text)
    lead_id: Mapped[int | None] = loose('users')
    color: Mapped[str] = col(String(7), default='#888888', pattern=COLOR)


class TeamMember(Owned, Base):
    __tablename__ = 'team_members'
    __table_args__ = (UniqueConstraint('team_id', 'user_id'),)

    team_id: Mapped[int] = ref('teams')
    user_id: Mapped[int] = ref('users')


class Department(Owned, Base):
    __tablename__ = 'departments'

    name: Mapped[str] = col(String(80))
    parent_id: Mapped[int | None] = loose('departments')
    head_id: Mapped[int | None] = loose('users')


class Office(Owned, Base):
    __tablename__ = 'offices'

    name: Mapped[str] = col(String(80))
    city: Mapped[str] = col(String(80))
    country: Mapped[str] = col(String(2), pattern=COUNTRY)
    address: Mapped[str | None] = col(String(200))
    timezone: Mapped[str] = col(String(40), default='UTC')
    capacity: Mapped[int | None] = col(ge=0)


class JobTitle(Owned, Base):
    __tablename__ = 'job_titles'
    __table_args__ = (UniqueConstraint('organisation_id', 'name'),)

    name: Mapped[str] = col(String(80))
    level: Mapped[int] = col(default=1, ge=1, le=10)


class OrgSettings(Owned, Base):
    """One row an organisation, made with it."""
    __tablename__ = 'org_settings'
    __table_args__ = (UniqueConstraint('organisation_id'),)

    week_starts_on: Mapped[int] = col(default=1, ge=0, le=6)
    date_format: Mapped[str] = col(String(12), default='YYYY-MM-DD')
    allow_guests: Mapped[bool] = col(default=True)
    session_hours: Mapped[int] = col(default=720, ge=1, le=8760)
    updated_at: Mapped[datetime | None] = moment()


class Domain(Owned, Base):
    """A mail domain the organisation says is its own. One organisation at a time may say so."""
    __tablename__ = 'domains'

    name: Mapped[str] = col(String(253), unique=True, fixed=True, pattern=r'^[a-z0-9-]+(\.[a-z0-9-]+)+$')
    verified_at: Mapped[datetime | None] = moment(managed=True)


class MemberProfile(Owned, Base):
    __tablename__ = 'member_profiles'
    __table_args__ = (UniqueConstraint('organisation_id', 'user_id'),)

    user_id: Mapped[int] = ref('users', fixed=True)
    department_id: Mapped[int | None] = loose('departments')
    office_id: Mapped[int | None] = loose('offices')
    job_title_id: Mapped[int | None] = loose('job_titles')
    manager_id: Mapped[int | None] = loose('users')
    started_on: Mapped[date | None]
    bio: Mapped[str | None] = col(Text)


class Announcement(Owned, Base):
    __tablename__ = 'announcements'

    title: Mapped[str] = col(String(120))
    body: Mapped[str] = col(Text)
    is_pinned: Mapped[bool] = col(default=False)
    author_id: Mapped[int | None] = loose('users', managed=True)


class AnnouncementRead(Owned, Base):
    __tablename__ = 'announcement_reads'
    __table_args__ = (UniqueConstraint('announcement_id', 'user_id'),)

    announcement_id: Mapped[int] = ref('announcements')
    user_id: Mapped[int] = ref('users')


class Holiday(Owned, Base):
    __tablename__ = 'holidays'

    name: Mapped[str] = col(String(80))
    day: Mapped[date]
    office_id: Mapped[int | None] = loose('offices')
    is_recurring: Mapped[bool] = col(default=False)


class TimeOffRequest(Owned, Base):
    __tablename__ = 'time_off_requests'

    user_id: Mapped[int | None] = loose('users', managed=True)
    kind: Mapped[TimeOffKind] = col(String(10))
    starts_on: Mapped[date]
    ends_on: Mapped[date]
    note: Mapped[str | None] = col(String(500))
    status: Mapped[Decision] = col(String(10), default=Decision.PENDING, managed=True)
    decided_by_id: Mapped[int | None] = loose('users', managed=True)


class TimeOffBalance(Owned, Base):
    __tablename__ = 'time_off_balances'
    __table_args__ = (UniqueConstraint('organisation_id', 'user_id', 'kind', 'year'),)

    user_id: Mapped[int] = ref('users', fixed=True)
    kind: Mapped[TimeOffKind] = col(String(10), fixed=True)
    year: Mapped[int] = col(fixed=True, ge=2000, le=2100)
    days_allowed: Mapped[int] = col(ge=0, le=366)
    days_used: Mapped[int] = col(default=0, ge=0, le=366)
