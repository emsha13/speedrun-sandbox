"""Projects and what work in them is sorted by."""
import enum

from datetime import date, datetime
from typing import Any

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped

from app.db import Base
from app.workspace.base import COLOR, KEY, URL, Owned, col, loose, moment, ref


class ProjectStatus(enum.StrEnum):
    ACTIVE = 'active'
    PAUSED = 'paused'
    ARCHIVED = 'archived'


class ProjectRole(enum.StrEnum):
    VIEWER = 'viewer'
    CONTRIBUTOR = 'contributor'
    MANAGER = 'manager'


class SprintStatus(enum.StrEnum):
    PLANNED = 'planned'
    ACTIVE = 'active'
    COMPLETED = 'completed'


class BoardKind(enum.StrEnum):
    KANBAN = 'kanban'
    SCRUM = 'scrum'


class StatusCategory(enum.StrEnum):
    TODO = 'todo'
    DOING = 'doing'
    DONE = 'done'


class Health(enum.StrEnum):
    ON_TRACK = 'on_track'
    AT_RISK = 'at_risk'
    OFF_TRACK = 'off_track'


class Project(Owned, Base):
    __tablename__ = 'projects'
    __table_args__ = (UniqueConstraint('organisation_id', 'key'),)

    name: Mapped[str] = col(String(80))
    # What a task's name starts with: WEB-12.
    key: Mapped[str] = col(String(8), pattern=KEY)
    description: Mapped[str | None] = col(Text)
    status: Mapped[ProjectStatus] = col(String(10), default=ProjectStatus.ACTIVE)
    lead_id: Mapped[int | None] = loose('users')
    team_id: Mapped[int | None] = loose('teams')
    starts_on: Mapped[date | None]
    due_on: Mapped[date | None]
    color: Mapped[str] = col(String(7), default='#3366cc', pattern=COLOR)
    is_private: Mapped[bool] = col(default=False)
    # The number the project's next task gets.
    next_number: Mapped[int] = col(default=1, managed=True)


class ProjectMember(Owned, Base):
    __tablename__ = 'project_members'
    __table_args__ = (UniqueConstraint('project_id', 'user_id'),)

    project_id: Mapped[int] = ref('projects', fixed=True)
    user_id: Mapped[int] = ref('users', fixed=True)
    role: Mapped[ProjectRole] = col(String(12), default=ProjectRole.CONTRIBUTOR)


class Milestone(Owned, Base):
    __tablename__ = 'milestones'

    project_id: Mapped[int] = ref('projects', fixed=True)
    name: Mapped[str] = col(String(80))
    description: Mapped[str | None] = col(Text)
    due_on: Mapped[date | None]
    is_closed: Mapped[bool] = col(default=False)


class Sprint(Owned, Base):
    __tablename__ = 'sprints'

    project_id: Mapped[int] = ref('projects', fixed=True)
    name: Mapped[str] = col(String(80))
    goal: Mapped[str | None] = col(String(300))
    starts_on: Mapped[date | None]
    ends_on: Mapped[date | None]
    status: Mapped[SprintStatus] = col(String(10), default=SprintStatus.PLANNED, managed=True)
    started_at: Mapped[datetime | None] = moment(managed=True)
    completed_at: Mapped[datetime | None] = moment(managed=True)


class Board(Owned, Base):
    __tablename__ = 'boards'

    project_id: Mapped[int] = ref('projects', fixed=True)
    name: Mapped[str] = col(String(80))
    kind: Mapped[BoardKind] = col(String(10), default=BoardKind.KANBAN)


class TaskStatus(Owned, Base):
    __tablename__ = 'task_statuses'
    __table_args__ = (UniqueConstraint('organisation_id', 'name'),)

    name: Mapped[str] = col(String(40))
    category: Mapped[StatusCategory] = col(String(10), default=StatusCategory.TODO)
    position: Mapped[int] = col(default=0, ge=0)
    color: Mapped[str] = col(String(7), default='#888888', pattern=COLOR)


class BoardColumn(Owned, Base):
    __tablename__ = 'board_columns'

    board_id: Mapped[int] = ref('boards', fixed=True)
    name: Mapped[str] = col(String(40))
    position: Mapped[int] = col(default=0, ge=0)
    wip_limit: Mapped[int | None] = col(ge=1)
    status_id: Mapped[int | None] = loose('task_statuses')


class TaskType(Owned, Base):
    __tablename__ = 'task_types'
    __table_args__ = (UniqueConstraint('organisation_id', 'name'),)

    name: Mapped[str] = col(String(40))
    icon: Mapped[str | None] = col(String(40))
    color: Mapped[str] = col(String(7), default='#888888', pattern=COLOR)
    is_subtask: Mapped[bool] = col(default=False)


class Label(Owned, Base):
    __tablename__ = 'labels'
    __table_args__ = (UniqueConstraint('organisation_id', 'name'),)

    name: Mapped[str] = col(String(40))
    color: Mapped[str] = col(String(7), default='#888888', pattern=COLOR)


class Component(Owned, Base):
    __tablename__ = 'components'

    project_id: Mapped[int] = ref('projects', fixed=True)
    name: Mapped[str] = col(String(80))
    lead_id: Mapped[int | None] = loose('users')


class Release(Owned, Base):
    __tablename__ = 'releases'
    __table_args__ = (UniqueConstraint('project_id', 'name'),)

    project_id: Mapped[int] = ref('projects', fixed=True)
    name: Mapped[str] = col(String(40))
    notes: Mapped[str | None] = col(Text)
    planned_on: Mapped[date | None]
    released_at: Mapped[datetime | None] = moment(managed=True)


class ProjectLink(Owned, Base):
    __tablename__ = 'project_links'

    project_id: Mapped[int] = ref('projects', fixed=True)
    title: Mapped[str] = col(String(80))
    url: Mapped[str] = col(String(500), pattern=URL)


class ProjectUpdate(Owned, Base):
    """How the project is doing, as its lead put it that week."""
    __tablename__ = 'project_updates'

    project_id: Mapped[int] = ref('projects', fixed=True)
    author_id: Mapped[int | None] = loose('users', managed=True)
    health: Mapped[Health] = col(String(10))
    body: Mapped[str] = col(Text)


class ProjectTemplate(Owned, Base):
    __tablename__ = 'project_templates'

    name: Mapped[str] = col(String(80))
    description: Mapped[str | None] = col(Text)
    layout: Mapped[dict[str, Any]] = col(JSONB, default=dict)


class ProjectFavourite(Owned, Base):
    __tablename__ = 'project_favourites'
    __table_args__ = (UniqueConstraint('project_id', 'user_id'),)

    project_id: Mapped[int] = ref('projects')
    user_id: Mapped[int] = ref('users')
