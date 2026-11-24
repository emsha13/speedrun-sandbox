"""What people are told: notifications, and the channels they talk in."""
import enum

from datetime import datetime

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped

from app.db import Base
from app.workspace.base import Owned, col, loose, moment, ref
from app.workspace.models.calendar import Channel, Frequency


class Audience(enum.StrEnum):
    EVERYONE = 'everyone'
    ADMINS = 'admins'
    TEAM = 'team'


class Platform(enum.StrEnum):
    IOS = 'ios'
    ANDROID = 'android'
    WEB = 'web'


class Delivery(enum.StrEnum):
    QUEUED = 'queued'
    SENT = 'sent'
    FAILED = 'failed'


class Notification(Owned, Base):
    __tablename__ = 'notifications'

    user_id: Mapped[int] = ref('users')
    kind: Mapped[str] = col(String(40))
    title: Mapped[str] = col(String(200))
    link: Mapped[str | None] = col(String(300))
    read_at: Mapped[datetime | None] = moment()


class NotificationPreference(Owned, Base):
    """Whether a member wants a kind of notification by a channel. No row means yes."""
    __tablename__ = 'notification_preferences'
    __table_args__ = (UniqueConstraint('organisation_id', 'user_id', 'kind', 'channel'),)

    user_id: Mapped[int] = ref('users')
    kind: Mapped[str] = col(String(40))
    channel: Mapped[Channel] = col(String(10))
    is_wanted: Mapped[bool]


class NotificationTemplate(Owned, Base):
    __tablename__ = 'notification_templates'
    __table_args__ = (UniqueConstraint('organisation_id', 'kind', 'channel'),)

    kind: Mapped[str] = col(String(40), fixed=True)
    channel: Mapped[Channel] = col(String(10), fixed=True)
    subject: Mapped[str] = col(String(200))
    body: Mapped[str] = col(Text)


class DigestSchedule(Owned, Base):
    __tablename__ = 'digest_schedules'
    __table_args__ = (UniqueConstraint('organisation_id', 'user_id'),)

    user_id: Mapped[int] = ref('users', managed=True)
    frequency: Mapped[Frequency] = col(String(10))
    hour: Mapped[int] = col(default=8, ge=0, le=23)
    is_paused: Mapped[bool] = col(default=False)


class PushDevice(Owned, Base):
    __tablename__ = 'push_devices'

    user_id: Mapped[int] = ref('users', managed=True)
    platform: Mapped[Platform] = col(String(10), fixed=True)
    name: Mapped[str] = col(String(80))
    token: Mapped[str] = col(String(200), unique=True, fixed=True, hidden=True)
    last_seen_at: Mapped[datetime | None] = moment(managed=True)


class Mention(Owned, Base):
    __tablename__ = 'mentions'

    user_id: Mapped[int] = ref('users')
    author_id: Mapped[int | None] = loose('users')
    message_id: Mapped[int] = ref('messages')


class Follow(Owned, Base):
    """A member wants to hear about a thing: `subject` says which kind, `subject_id` which one."""
    __tablename__ = 'follows'
    __table_args__ = (UniqueConstraint('user_id', 'subject', 'subject_id'),)

    user_id: Mapped[int] = ref('users', managed=True)
    subject: Mapped[str] = col(String(30), fixed=True)
    subject_id: Mapped[int] = col(fixed=True, ge=1)


class Mute(Owned, Base):
    __tablename__ = 'mutes'
    __table_args__ = (UniqueConstraint('user_id', 'subject', 'subject_id'),)

    user_id: Mapped[int] = ref('users', managed=True)
    subject: Mapped[str] = col(String(30), fixed=True)
    subject_id: Mapped[int] = col(fixed=True, ge=1)
    until: Mapped[datetime | None] = moment()


class EmailLog(Owned, Base):
    __tablename__ = 'email_log'

    recipient: Mapped[str] = col(String(254))
    subject: Mapped[str] = col(String(200))
    status: Mapped[Delivery] = col(String(10), default=Delivery.QUEUED)
    error: Mapped[str | None] = col(String(300))


class SmsLog(Owned, Base):
    __tablename__ = 'sms_log'

    recipient: Mapped[str] = col(String(16))
    status: Mapped[Delivery] = col(String(10), default=Delivery.QUEUED)
    error: Mapped[str | None] = col(String(300))


class Broadcast(Owned, Base):
    __tablename__ = 'broadcasts'

    title: Mapped[str] = col(String(120))
    body: Mapped[str] = col(Text)
    audience: Mapped[Audience] = col(String(10), default=Audience.EVERYONE)
    team_id: Mapped[int | None] = loose('teams')
    send_at: Mapped[datetime | None] = moment()
    sent_at: Mapped[datetime | None] = moment(managed=True)


class ChatChannel(Owned, Base):
    __tablename__ = 'chat_channels'
    __table_args__ = (UniqueConstraint('organisation_id', 'name'),)

    name: Mapped[str] = col(String(60), pattern=r'^[a-z0-9][a-z0-9-]*$')
    topic: Mapped[str | None] = col(String(200))
    is_private: Mapped[bool] = col(default=False)
    created_by_id: Mapped[int | None] = loose('users', managed=True)
    archived_at: Mapped[datetime | None] = moment(managed=True)


class ChannelMember(Owned, Base):
    __tablename__ = 'channel_members'
    __table_args__ = (UniqueConstraint('channel_id', 'user_id'),)

    channel_id: Mapped[int] = ref('chat_channels')
    user_id: Mapped[int] = ref('users')
    # The last message of the channel the member has seen.
    seen_id: Mapped[int | None] = col()


class Message(Owned, Base):
    __tablename__ = 'messages'

    channel_id: Mapped[int] = ref('chat_channels', fixed=True)
    author_id: Mapped[int | None] = loose('users', managed=True)
    # The message this one answers, when it is part of a thread.
    parent_id: Mapped[int | None] = ref('messages', fixed=True)
    body: Mapped[str] = col(Text)
    updated_at: Mapped[datetime | None] = moment(managed=True)


class Reaction(Owned, Base):
    __tablename__ = 'reactions'
    __table_args__ = (UniqueConstraint('message_id', 'user_id', 'emoji'),)

    message_id: Mapped[int] = ref('messages', fixed=True)
    user_id: Mapped[int] = ref('users', managed=True)
    emoji: Mapped[str] = col(String(30), fixed=True)


class Pin(Owned, Base):
    __tablename__ = 'pins'
    __table_args__ = (UniqueConstraint('message_id'),)

    message_id: Mapped[int] = ref('messages', fixed=True)
    pinned_by_id: Mapped[int | None] = loose('users', managed=True)


class Draft(Owned, Base):
    """What a member had typed into a channel and not sent."""
    __tablename__ = 'drafts'
    __table_args__ = (UniqueConstraint('channel_id', 'user_id'),)

    channel_id: Mapped[int] = ref('chat_channels', fixed=True)
    user_id: Mapped[int] = ref('users', managed=True)
    body: Mapped[str] = col(Text)
