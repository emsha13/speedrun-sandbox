from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app import limits, security, services
from app.deps import Db, Me
from app.models import CodePurpose, RefreshSession, now
from app.schemas import (
    CodeOnly, EmailChange, PasswordChange, PasswordOnly, PhoneChange, ProfileUpdate, SessionOut, UserOut,
)

router = APIRouter(prefix='/me', tags=['account'])
WRONG_PASSWORD = HTTPException(status.HTTP_400_BAD_REQUEST, 'wrong password')


@router.get('', response_model=UserOut)
async def read_profile(me: Me):
    return me.user


@router.patch('', response_model=UserOut)
async def update_profile(data: ProfileUpdate, me: Me, session: Db):
    changes = data.model_dump(exclude_unset=True)
    if changes.get('birth_date') and changes['birth_date'] > now().date():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'birth date is in the future')
    for name in ('first_name', 'last_name'):
        if name in changes and changes[name] is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f'{name} cannot be empty')
    for name, value in changes.items():
        setattr(me.user, name, value)
    await session.commit()
    return me.user


@router.post('/change-password', status_code=status.HTTP_204_NO_CONTENT)
async def change_password(data: PasswordChange, me: Me, session: Db):
    if not security.verify_password(data.current_password, me.user.password_hash):
        raise WRONG_PASSWORD
    if data.new_password == data.current_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'new password is the old one')
    me.user.password_hash = security.hash_password(data.new_password)
    # Whoever else holds the old password is out; the device that changed it stays in.
    await services.close_sessions(session, me.user, keep=me.session_id)
    services.record(session, me.user, 'password_changed')
    await session.commit()


@router.post('/change-email', status_code=status.HTTP_204_NO_CONTENT)
async def change_email(data: EmailChange, me: Me, session: Db):
    if not security.verify_password(data.password, me.user.password_hash):
        raise WRONG_PASSWORD
    if data.new_email == me.user.email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'new email is the old one')
    if await services.user_by_email(session, data.new_email):
        raise HTTPException(status.HTTP_409_CONFLICT, 'email is taken')
    await limits.spend_send(data.new_email)
    await services.send_code(session, me.user, CodePurpose.CHANGE_EMAIL, data.new_email)


@router.post('/change-email/confirm', response_model=UserOut)
async def confirm_email_change(data: CodeOnly, me: Me, session: Db):
    row = await services.use_code(session, me.user, CodePurpose.CHANGE_EMAIL, data.code)
    # Between the request and the code somebody else may have registered the address.
    if await services.user_by_email(session, row.target):
        await session.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, 'email is taken')
    me.user.email = row.target
    services.record(session, me.user, 'email_changed')
    await session.commit()
    return me.user


@router.post('/change-phone', status_code=status.HTTP_204_NO_CONTENT)
async def change_phone(data: PhoneChange, me: Me, session: Db):
    """The first number is set the same way a number is changed: by a code sent to it."""
    if not security.verify_password(data.password, me.user.password_hash):
        raise WRONG_PASSWORD
    if data.new_phone == me.user.phone:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'new phone is the old one')
    if await services.user_by_phone(session, data.new_phone):
        raise HTTPException(status.HTTP_409_CONFLICT, 'phone is taken')
    await limits.spend_send(data.new_phone)
    await services.send_code(session, me.user, CodePurpose.CHANGE_PHONE, data.new_phone)


@router.post('/change-phone/confirm', response_model=UserOut)
async def confirm_phone_change(data: CodeOnly, me: Me, session: Db):
    row = await services.use_code(session, me.user, CodePurpose.CHANGE_PHONE, data.code)
    if await services.user_by_phone(session, row.target):
        await session.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, 'phone is taken')
    me.user.phone = row.target
    services.record(session, me.user, 'phone_changed')
    await session.commit()
    return me.user


@router.post('/remove-phone', response_model=UserOut)
async def remove_phone(data: PasswordOnly, me: Me, session: Db):
    if not security.verify_password(data.password, me.user.password_hash):
        raise WRONG_PASSWORD
    if me.user.phone is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'there is no phone to remove')
    me.user.phone = None
    services.record(session, me.user, 'phone_removed')
    await session.commit()
    return me.user


@router.get('/sessions', response_model=list[SessionOut])
async def list_sessions(me: Me, session: Db):
    rows = await session.scalars(
        select(RefreshSession).where(
            RefreshSession.user_id == me.user.id, RefreshSession.revoked_at.is_(None),
            RefreshSession.expires_at > now(),
        ).order_by(RefreshSession.id)
    )
    return [
        SessionOut(id=row.id, user_agent=row.user_agent, created_at=row.created_at, current=row.id == me.session_id)
        for row in rows
    ]


@router.delete('/sessions/{session_id}', status_code=status.HTTP_204_NO_CONTENT)
async def end_session(session_id: int, me: Me, session: Db):
    row = await session.get(RefreshSession, session_id)
    if row is None or row.user_id != me.user.id or row.revoked_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'no such session')
    row.revoked_at = now()
    await session.commit()


@router.delete('', status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(data: PasswordOnly, me: Me, session: Db):
    if not security.verify_password(data.password, me.user.password_hash):
        raise WRONG_PASSWORD
    await session.delete(me.user)
    await session.commit()
