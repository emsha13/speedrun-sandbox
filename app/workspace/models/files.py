"""Files: where they are kept, who may see them, and who is editing one now."""
import enum

from datetime import datetime

from sqlalchemy import BigInteger, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped

from app.db import Base
from app.workspace.base import Owned, col, loose, moment, ref
from app.workspace.models.docs import Access

A_TERABYTE = 2 ** 40


class RetentionAction(enum.StrEnum):
    DELETE = 'delete'
    ARCHIVE = 'archive'


class Folder(Owned, Base):
    __tablename__ = 'folders'

    name: Mapped[str] = col(String(120))
    parent_id: Mapped[int | None] = ref('folders')
    created_by_id: Mapped[int | None] = loose('users', managed=True)


class File(Owned, Base):
    """What is known of a file. The bytes are elsewhere, under `storage_key`."""
    __tablename__ = 'files'

    folder_id: Mapped[int | None] = loose('folders')
    name: Mapped[str] = col(String(200))
    content_type: Mapped[str] = col(String(100), default='application/octet-stream')
    size: Mapped[int] = col(BigInteger, ge=0, le=A_TERABYTE)
    checksum: Mapped[str] = col(String(64), pattern=r'^[0-9a-f]{64}$')
    storage_key: Mapped[str] = col(String(64), unique=True, managed=True, hidden=True)
    uploaded_by_id: Mapped[int | None] = loose('users', managed=True)
    # Counts the contents, not the row: renaming a file leaves it as it is.
    version: Mapped[int] = col(default=1, managed=True)
    trashed_at: Mapped[datetime | None] = moment(managed=True)
    updated_at: Mapped[datetime | None] = moment(managed=True)


class FileVersion(Owned, Base):
    """The contents a file had before new ones replaced them."""
    __tablename__ = 'file_versions'
    __table_args__ = (UniqueConstraint('file_id', 'number'),)

    file_id: Mapped[int] = ref('files')
    number: Mapped[int]
    size: Mapped[int] = col(BigInteger)
    checksum: Mapped[str] = col(String(64))
    storage_key: Mapped[str] = col(String(64), hidden=True)
    uploaded_by_id: Mapped[int | None] = loose('users')


class FileShare(Owned, Base):
    __tablename__ = 'file_shares'

    file_id: Mapped[int] = ref('files', fixed=True)
    user_id: Mapped[int | None] = loose('users')
    team_id: Mapped[int | None] = loose('teams')
    access: Mapped[Access] = col(String(10), default=Access.VIEW)


class ShareLink(Owned, Base):
    """A file for whoever holds the link — no account, no membership."""
    __tablename__ = 'share_links'

    file_id: Mapped[int] = ref('files', fixed=True)
    token: Mapped[str] = col(String(43), unique=True, managed=True)
    created_by_id: Mapped[int | None] = loose('users', managed=True)
    expires_at: Mapped[datetime | None] = moment()
    opened: Mapped[int] = col(default=0, managed=True)


class FileComment(Owned, Base):
    __tablename__ = 'file_comments'

    file_id: Mapped[int] = ref('files', fixed=True)
    author_id: Mapped[int | None] = loose('users', managed=True)
    body: Mapped[str] = col(Text)


class FileTag(Owned, Base):
    __tablename__ = 'file_tags'
    __table_args__ = (UniqueConstraint('organisation_id', 'name'),)

    name: Mapped[str] = col(String(40))


class FileTagLink(Owned, Base):
    __tablename__ = 'file_tag_links'
    __table_args__ = (UniqueConstraint('file_id', 'tag_id'),)

    file_id: Mapped[int] = ref('files')
    tag_id: Mapped[int] = ref('file_tags')


class FileLock(Owned, Base):
    """Somebody is editing the file; nobody else replaces it meanwhile."""
    __tablename__ = 'file_locks'
    __table_args__ = (UniqueConstraint('file_id'),)

    file_id: Mapped[int] = ref('files')
    user_id: Mapped[int] = ref('users')


class FileStar(Owned, Base):
    __tablename__ = 'file_stars'
    __table_args__ = (UniqueConstraint('file_id', 'user_id'),)

    file_id: Mapped[int] = ref('files')
    user_id: Mapped[int] = ref('users')


class Thumbnail(Owned, Base):
    __tablename__ = 'thumbnails'
    __table_args__ = (UniqueConstraint('file_id', 'width'),)

    file_id: Mapped[int] = ref('files')
    width: Mapped[int]
    storage_key: Mapped[str] = col(String(64))


class FileEvent(Owned, Base):
    __tablename__ = 'file_events'

    file_id: Mapped[int] = ref('files')
    kind: Mapped[str] = col(String(30))
    actor_id: Mapped[int | None] = loose('users')


class RetentionPolicy(Owned, Base):
    __tablename__ = 'retention_policies'

    name: Mapped[str] = col(String(80))
    folder_id: Mapped[int | None] = ref('folders')
    keep_days: Mapped[int] = col(ge=1, le=36500)
    action: Mapped[RetentionAction] = col(String(10), default=RetentionAction.ARCHIVE)
