"""Notifications and chat."""
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update

from app.models import now
from app.workspace.access import Admin, Context, Guest
from app.workspace.crud import RowId, find, out_of, resource
from app.workspace.models.calendar import Channel
from app.workspace.models.messages import (
    Audience, Broadcast, ChannelMember, ChatChannel, Message, Notification, NotificationPreference,
)
from app.workspace.models.orgs import MemberRole, Membership, TeamMember

router = APIRouter(tags=['messages'])
ADMIN = MemberRole.ADMIN
NotificationOut = out_of(Notification)
PreferenceOut = out_of(NotificationPreference)


class Unread(BaseModel):
    model_config = ConfigDict(extra='forbid')

    unread: bool = False
    limit: int = Field(20, ge=1, le=100)


class Preference(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    channel: Channel
    is_wanted: bool


def mine(context: Context):
    return (Notification.organisation_id == context.org_id, Notification.user_id == context.user.id)


@router.get('/notifications', response_model=list[NotificationOut])
async def list_my_notifications(query: Annotated[Unread, Query()], context: Guest):
    found = select(Notification).where(*mine(context))
    if query.unread:
        found = found.where(Notification.read_at.is_(None))
    rows = await context.session.scalars(found.order_by(Notification.id.desc()).limit(query.limit))
    return rows.all()


@router.get('/notifications/unread-count')
async def count_my_unread(context: Guest):
    count = await context.session.scalar(
        select(func.count()).select_from(Notification).where(*mine(context), Notification.read_at.is_(None))
    )
    return {'count': count}


@router.post('/notifications/read-all')
async def read_all_my_notifications(context: Guest):
    done = await context.session.execute(
        update(Notification).where(*mine(context), Notification.read_at.is_(None)).values(read_at=now())
    )
    await context.session.commit()
    return {'count': done.rowcount}


@router.post('/notifications/{row_id}/read', response_model=NotificationOut)
async def read_notification(row_id: RowId, context: Guest):
    notification = await find(context, Notification, row_id)
    # Somebody else's notification is not there, as far as the caller can tell.
    if notification.user_id != context.user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'no such notification')
    if notification.read_at is None:
        notification.read_at = now()
        await context.session.commit()
    return notification


@router.get('/notification-preferences', response_model=list[PreferenceOut])
async def list_my_preferences(context: Guest):
    rows = await context.session.scalars(
        select(NotificationPreference).where(
            NotificationPreference.organisation_id == context.org_id,
            NotificationPreference.user_id == context.user.id,
        ).order_by(NotificationPreference.id)
    )
    return rows.all()


@router.put('/notification-preferences', response_model=PreferenceOut)
async def set_my_preference(data: Preference, context: Guest):
    preference = await context.session.scalar(
        select(NotificationPreference).where(
            NotificationPreference.organisation_id == context.org_id,
            NotificationPreference.user_id == context.user.id, NotificationPreference.kind == data.kind,
            NotificationPreference.channel == data.channel,
        )
    )
    if preference is None:
        preference = NotificationPreference(
            organisation_id=context.org_id, user_id=context.user.id, kind=data.kind, channel=data.channel,
        )
        context.session.add(preference)
    preference.is_wanted = data.is_wanted
    await context.session.commit()
    return preference


async def a_broadcast_for_somebody(context: Context, broadcast: Broadcast, old) -> None:
    if old is not None and broadcast.sent_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, 'the broadcast is sent')
    if (broadcast.audience == Audience.TEAM) != (broadcast.team_id is not None):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'a team is named when the audience is a team, and only then')


@router.post('/broadcasts/{row_id}/send', response_model=out_of(Broadcast))
async def send_broadcast(row_id: RowId, context: Admin):
    """Everybody in the audience gets a notification, except those who have said they want no
    broadcasts in the application."""
    session = context.session
    broadcast = await find(context, Broadcast, row_id)
    if broadcast.sent_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, 'the broadcast is sent')
    audience = select(Membership.user_id).where(Membership.organisation_id == context.org_id)
    if broadcast.audience == Audience.ADMINS:
        audience = audience.where(Membership.role.in_([MemberRole.ADMIN, MemberRole.OWNER]))
    elif broadcast.audience == Audience.TEAM:
        audience = audience.where(
            Membership.user_id.in_(select(TeamMember.user_id).where(TeamMember.team_id == broadcast.team_id))
        )
    unwilling = select(NotificationPreference.user_id).where(
        NotificationPreference.organisation_id == context.org_id, NotificationPreference.kind == 'broadcast',
        NotificationPreference.channel == Channel.IN_APP, NotificationPreference.is_wanted.is_(False),
    )
    users = await session.scalars(audience.where(Membership.user_id.not_in(unwilling)).order_by(Membership.id))
    session.add_all([
        Notification(organisation_id=context.org_id, user_id=user_id, kind='broadcast', title=broadcast.title)
        for user_id in users
    ])
    broadcast.sent_at = now()
    await session.commit()
    return broadcast


async def channel_member(context: Context, channel_id: int) -> ChannelMember | None:
    return await context.session.scalar(
        select(ChannelMember).where(ChannelMember.channel_id == channel_id, ChannelMember.user_id == context.user.id)
    )


@router.post('/chat-channels/{row_id}/join', status_code=status.HTTP_204_NO_CONTENT)
async def join_channel(row_id: RowId, context: Guest):
    channel = await find(context, ChatChannel, row_id)
    if await channel_member(context, row_id) is not None:
        return
    # A private channel is entered by invitation: whoever made it adds people, and admins do.
    if channel.is_private and not context.is_at_least(MemberRole.ADMIN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, 'the channel is private')
    context.session.add(ChannelMember(organisation_id=context.org_id, channel_id=row_id, user_id=context.user.id))
    await context.session.commit()


@router.post('/chat-channels/{row_id}/leave', status_code=status.HTTP_204_NO_CONTENT)
async def leave_channel(row_id: RowId, context: Guest):
    await find(context, ChatChannel, row_id)
    membership = await channel_member(context, row_id)
    if membership is not None:
        await context.session.delete(membership)
        await context.session.commit()


async def a_channel_with_its_maker_in_it(context: Context, channel: ChatChannel, old) -> None:
    if old is None:
        context.session.add(channel)
        await context.session.flush()
        context.session.add(
            ChannelMember(organisation_id=context.org_id, channel_id=channel.id, user_id=context.user.id)
        )


async def a_message_from_inside(context: Context, message: Message, old) -> None:
    if old is not None:
        return
    channel = await context.session.get(ChatChannel, message.channel_id)
    if channel.archived_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, 'the channel is archived')
    if channel.is_private and await channel_member(context, channel.id) is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, 'the channel is private')
    if message.parent_id is not None:
        parent = await context.session.get(Message, message.parent_id)
        if parent.channel_id != message.channel_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, 'the thread is in another channel')


resource(router, Broadcast, read=ADMIN, write=ADMIN, check=a_broadcast_for_somebody)
resource(
    router, ChatChannel, author='created_by_id', own=True, search=('name', 'topic'),
    check=a_channel_with_its_maker_in_it,
)
resource(router, Message, author='author_id', own=True, search=('body',), check=a_message_from_inside)
