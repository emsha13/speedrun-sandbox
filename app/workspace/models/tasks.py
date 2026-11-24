"""Tasks and everything that hangs on one."""
import enum

from datetime import date, datetime
from typing import Any

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped

from app.db import Base
from app.workspace.base import Owned, col, loose, moment, ref


class Priority(enum.StrEnum):
    LOW = 'low'
    NORMAL = 'normal'
    HIGH = 'high'
    URGENT = 'urgent'


class LinkKind(enum.StrEnum):
    BLOCKS = 'blocks'
    RELATES = 'relates'
    DUPLICATES = 'duplicates'


class Every(enum.StrEnum):
    DAY = 'day'
    WEEK = 'week'
    MONTH = 'month'


class FieldKind(enum.StrEnum):
    TEXT = 'text'
    NUMBER = 'number'
    DATE = 'date'
    CHOICE = 'choice'


class Task(Owned, Base):
    __tablename__ = 'tasks'
    __table_args__ = (UniqueConstraint('project_id', 'number'),)

    project_id: Mapped[int] = ref('projects', fixed=True)
    number: Mapped[int] = col(managed=True)
    title: Mapped[str] = col(String(200))
    description: Mapped[str | None] = col(Text)
    priority: Mapped[Priority] = col(String(10), default=Priority.NORMAL)
    status_id: Mapped[int | None] = loose('task_statuses')
    type_id: Mapped[int | None] = loose('task_types')
    assignee_id: Mapped[int | None] = loose('users')
    reporter_id: Mapped[int | None] = loose('users', managed=True)
    parent_id: Mapped[int | None] = loose('tasks')
    milestone_id: Mapped[int | None] = loose('milestones')
    sprint_id: Mapped[int | None] = loose('sprints')
    component_id: Mapped[int | None] = loose('components')
    release_id: Mapped[int | None] = loose('releases')
    estimate_minutes: Mapped[int | None] = col(ge=0)
    due_on: Mapped[date | None]
    position: Mapped[int] = col(default=0, ge=0)
    completed_at: Mapped[datetime | None] = moment(managed=True)
    updated_at: Mapped[datetime | None] = moment(managed=True)


class TaskWatcher(Owned, Base):
    __tablename__ = 'task_watchers'
    __table_args__ = (UniqueConstraint('task_id', 'user_id'),)

    task_id: Mapped[int] = ref('tasks')
    user_id: Mapped[int] = ref('users')


class TaskLabel(Owned, Base):
    __tablename__ = 'task_labels'
    __table_args__ = (UniqueConstraint('task_id', 'label_id'),)

    task_id: Mapped[int] = ref('tasks')
    label_id: Mapped[int] = ref('labels')


class TaskComment(Owned, Base):
    __tablename__ = 'task_comments'

    task_id: Mapped[int] = ref('tasks', fixed=True)
    author_id: Mapped[int | None] = loose('users', managed=True)
    body: Mapped[str] = col(Text)
    updated_at: Mapped[datetime | None] = moment(managed=True)


class TaskAttachment(Owned, Base):
    __tablename__ = 'task_attachments'
    __table_args__ = (UniqueConstraint('task_id', 'file_id'),)

    task_id: Mapped[int] = ref('tasks')
    file_id: Mapped[int] = ref('files')


class TaskLink(Owned, Base):
    __tablename__ = 'task_links'
    __table_args__ = (UniqueConstraint('source_id', 'target_id', 'kind'),)

    source_id: Mapped[int] = ref('tasks')
    target_id: Mapped[int] = ref('tasks')
    kind: Mapped[LinkKind] = col(String(12), default=LinkKind.RELATES)


class TaskChecklist(Owned, Base):
    __tablename__ = 'task_checklists'

    task_id: Mapped[int] = ref('tasks', fixed=True)
    title: Mapped[str] = col(String(120))
    position: Mapped[int] = col(default=0, ge=0)


class TaskChecklistItem(Owned, Base):
    __tablename__ = 'task_checklist_items'

    checklist_id: Mapped[int] = ref('task_checklists', fixed=True)
    text: Mapped[str] = col(String(300))
    is_done: Mapped[bool] = col(default=False)
    position: Mapped[int] = col(default=0, ge=0)


class TimeEntry(Owned, Base):
    __tablename__ = 'time_entries'

    task_id: Mapped[int] = ref('tasks', fixed=True)
    user_id: Mapped[int | None] = loose('users', managed=True)
    minutes: Mapped[int] = col(ge=1, le=1440)
    spent_on: Mapped[date]
    note: Mapped[str | None] = col(String(300))
    is_billable: Mapped[bool] = col(default=False)


class TaskStatusChange(Owned, Base):
    """Written when a task's status changes; read by whoever wants to know how long it sat."""
    __tablename__ = 'task_status_changes'

    task_id: Mapped[int] = ref('tasks')
    from_status_id: Mapped[int | None] = loose('task_statuses')
    to_status_id: Mapped[int | None] = loose('task_statuses')
    changed_by_id: Mapped[int | None] = loose('users')


class TaskReminder(Owned, Base):
    __tablename__ = 'task_reminders'

    task_id: Mapped[int] = ref('tasks', fixed=True)
    user_id: Mapped[int | None] = loose('users', managed=True)
    remind_at: Mapped[datetime] = moment()
    sent_at: Mapped[datetime | None] = moment(managed=True)


class TaskTemplate(Owned, Base):
    __tablename__ = 'task_templates'

    name: Mapped[str] = col(String(80))
    title: Mapped[str] = col(String(200))
    description: Mapped[str | None] = col(Text)
    type_id: Mapped[int | None] = loose('task_types')
    priority: Mapped[Priority] = col(String(10), default=Priority.NORMAL)
    checklist: Mapped[list[str]] = col(JSONB, default=list)


class SavedFilter(Owned, Base):
    __tablename__ = 'saved_filters'

    name: Mapped[str] = col(String(80))
    owner_id: Mapped[int | None] = loose('users', managed=True)
    criteria: Mapped[dict[str, Any]] = col(JSONB, default=dict)
    is_shared: Mapped[bool] = col(default=False)


class RecurringTask(Owned, Base):
    __tablename__ = 'recurring_tasks'

    project_id: Mapped[int] = ref('projects', fixed=True)
    title: Mapped[str] = col(String(200))
    every: Mapped[Every] = col(String(10))
    next_on: Mapped[date]
    assignee_id: Mapped[int | None] = loose('users')
    is_paused: Mapped[bool] = col(default=False)


class TaskVote(Owned, Base):
    __tablename__ = 'task_votes'
    __table_args__ = (UniqueConstraint('task_id', 'user_id'),)

    task_id: Mapped[int] = ref('tasks')
    user_id: Mapped[int] = ref('users')


class CustomField(Owned, Base):
    __tablename__ = 'custom_fields'
    __table_args__ = (UniqueConstraint('organisation_id', 'name'),)

    name: Mapped[str] = col(String(60))
    kind: Mapped[FieldKind] = col(String(10), fixed=True)
    choices: Mapped[list[str]] = col(JSONB, default=list)
    is_required: Mapped[bool] = col(default=False)


class CustomFieldValue(Owned, Base):
    __tablename__ = 'custom_field_values'
    __table_args__ = (UniqueConstraint('task_id', 'field_id'),)

    task_id: Mapped[int] = ref('tasks', fixed=True)
    field_id: Mapped[int] = ref('custom_fields', fixed=True)
    value: Mapped[str] = col(String(500))
