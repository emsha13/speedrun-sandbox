"""Files and folders."""
import secrets

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.models import now
from app.settings import settings
from app.workspace import outside
from app.workspace.access import Context, Member
from app.workspace.crud import RowId, find, mark, out_of, resource
from app.workspace.models.files import A_TERABYTE, File, FileEvent, FileLock, FileStar, FileVersion, Folder, ShareLink
from app.workspace.models.orgs import MemberRole

router = APIRouter(tags=['files'])
FileOut = out_of(File)


class NewContents(BaseModel):
    size: int = Field(ge=0, le=A_TERABYTE)
    checksum: str = Field(pattern=r'^[0-9a-f]{64}$')


async def lock_of(context: Context, file_id: int) -> FileLock | None:
    return await context.session.scalar(select(FileLock).where(FileLock.file_id == file_id))


async def not_locked_by_another(context: Context, file: File) -> None:
    lock = await lock_of(context, file.id)
    if lock is not None and lock.user_id != context.user.id:
        raise HTTPException(status.HTTP_423_LOCKED, 'somebody else is editing the file')


def logged(context: Context, file: File, kind: str) -> None:
    context.session.add(FileEvent(organisation_id=context.org_id, file_id=file.id, kind=kind, actor_id=context.user.id))


async def a_file_in_its_place(context: Context, file: File, old) -> None:
    if old is None:
        file.storage_key = secrets.token_hex(32)
        return
    await not_locked_by_another(context, file)
    if file.trashed_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, 'the file is in the trash')


async def a_folder_not_in_itself(context: Context, folder: Folder, old) -> None:
    if old is None or folder.parent_id is None:
        return
    # Up from the new parent to the top: the folder must not be met on the way.
    at = folder.parent_id
    while at is not None:
        if at == folder.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, 'a folder is not put inside itself')
        at = await context.session.scalar(select(Folder.parent_id).where(Folder.id == at))



async def a_link_with_a_token(context: Context, link: ShareLink, old) -> None:
    if old is None:
        link.token = secrets.token_urlsafe(32)
    if link.expires_at is not None and link.expires_at <= now():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'the link would be expired already')


async def a_file_out_of_the_bucket(context: Context, file: File) -> None:
    if settings.S3_BUCKET:
        await outside.delete_object(file.storage_key)


@router.post('/files/{row_id}/contents', response_model=FileOut)
async def replace_contents(row_id: RowId, data: NewContents, context: Member):
    """New contents for a file: the ones it had are kept as a version."""
    file = await find(context, File, row_id)
    await not_locked_by_another(context, file)
    if file.trashed_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, 'the file is in the trash')
    context.session.add(FileVersion(
        organisation_id=context.org_id, file_id=file.id, number=file.version, size=file.size,
        checksum=file.checksum, storage_key=file.storage_key, uploaded_by_id=file.uploaded_by_id,
    ))
    file.size, file.checksum, file.storage_key = data.size, data.checksum, secrets.token_hex(32)
    file.uploaded_by_id, file.version, file.updated_at = context.user.id, file.version + 1, now()
    logged(context, file, 'replaced')
    await context.session.commit()
    return file


@router.post('/files/{row_id}/trash', response_model=FileOut)
async def trash_file(row_id: RowId, context: Member):
    file = await find(context, File, row_id)
    await not_locked_by_another(context, file)
    if file.trashed_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, 'the file is in the trash')
    file.trashed_at = now()
    logged(context, file, 'trashed')
    await context.session.commit()
    return file


@router.post('/files/{row_id}/restore', response_model=FileOut)
async def restore_file(row_id: RowId, context: Member):
    file = await find(context, File, row_id)
    if file.trashed_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, 'the file is not in the trash')
    file.trashed_at = None
    logged(context, file, 'restored')
    await context.session.commit()
    return file


@router.post('/files/{row_id}/lock', status_code=status.HTTP_204_NO_CONTENT)
async def lock_file(row_id: RowId, context: Member):
    file = await find(context, File, row_id)
    lock = await lock_of(context, file.id)
    if lock is not None:
        if lock.user_id != context.user.id:
            raise HTTPException(status.HTTP_423_LOCKED, 'somebody else is editing the file')
        return
    context.session.add(FileLock(organisation_id=context.org_id, file_id=file.id, user_id=context.user.id))
    await context.session.commit()


@router.post('/files/{row_id}/unlock', status_code=status.HTTP_204_NO_CONTENT)
async def unlock_file(row_id: RowId, context: Member):
    """Whoever locked it unlocks it — or an admin, for somebody who went on holiday."""
    file = await find(context, File, row_id)
    lock = await lock_of(context, file.id)
    if lock is None:
        return
    if lock.user_id != context.user.id and not context.is_at_least(MemberRole.ADMIN):
        raise HTTPException(status.HTTP_423_LOCKED, 'somebody else is editing the file')
    await context.session.delete(lock)
    await context.session.commit()


mark(router, File, FileStar, 'file_id', 'star')

resource(router, Folder, author='created_by_id', search=('name',), check=a_folder_not_in_itself)
resource(router, File, author='uploaded_by_id', search=('name',), check=a_file_in_its_place,
         gone=a_file_out_of_the_bucket)
resource(router, FileVersion, methods='list read')
resource(router, ShareLink, methods='list read create update delete', author='created_by_id', own=True,
         check=a_link_with_a_token)
