"""Documents: spaces, pages, their versions and what is said about them."""
import enum

from datetime import datetime

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped

from app.db import Base
from app.workspace.base import KEY, Owned, col, loose, moment, ref


class DocumentStatus(enum.StrEnum):
    DRAFT = 'draft'
    PUBLISHED = 'published'
    ARCHIVED = 'archived'


class Access(enum.StrEnum):
    VIEW = 'view'
    COMMENT = 'comment'
    EDIT = 'edit'


class Space(Owned, Base):
    __tablename__ = 'spaces'
    __table_args__ = (UniqueConstraint('organisation_id', 'key'),)

    name: Mapped[str] = col(String(80))
    key: Mapped[str] = col(String(8), pattern=KEY)
    description: Mapped[str | None] = col(Text)
    icon: Mapped[str | None] = col(String(40))
    is_private: Mapped[bool] = col(default=False)


class SpaceMember(Owned, Base):
    __tablename__ = 'space_members'
    __table_args__ = (UniqueConstraint('space_id', 'user_id'),)

    space_id: Mapped[int] = ref('spaces', fixed=True)
    user_id: Mapped[int] = ref('users', fixed=True)
    access: Mapped[Access] = col(String(10), default=Access.VIEW)


class Document(Owned, Base):
    __tablename__ = 'documents'

    space_id: Mapped[int] = ref('spaces')
    parent_id: Mapped[int | None] = loose('documents')
    title: Mapped[str] = col(String(200))
    body: Mapped[str] = col(Text, default='')
    author_id: Mapped[int | None] = loose('users', managed=True)
    status: Mapped[DocumentStatus] = col(String(10), default=DocumentStatus.DRAFT, managed=True)
    # How many times the text has been saved; the versions table holds each of them.
    version: Mapped[int] = col(default=1, managed=True)
    published_at: Mapped[datetime | None] = moment(managed=True)
    updated_at: Mapped[datetime | None] = moment(managed=True)


class DocumentVersion(Owned, Base):
    """The text as it was before a save replaced it."""
    __tablename__ = 'document_versions'
    __table_args__ = (UniqueConstraint('document_id', 'number'),)

    document_id: Mapped[int] = ref('documents')
    number: Mapped[int]
    title: Mapped[str] = col(String(200))
    body: Mapped[str] = col(Text)
    author_id: Mapped[int | None] = loose('users')


class DocumentComment(Owned, Base):
    __tablename__ = 'document_comments'

    document_id: Mapped[int] = ref('documents', fixed=True)
    author_id: Mapped[int | None] = loose('users', managed=True)
    body: Mapped[str] = col(Text)
    # The words of the document the comment is about, when it is about some.
    quote: Mapped[str | None] = col(String(500))
    resolved_at: Mapped[datetime | None] = moment(managed=True)
    updated_at: Mapped[datetime | None] = moment(managed=True)


class DocumentLabel(Owned, Base):
    __tablename__ = 'document_labels'
    __table_args__ = (UniqueConstraint('document_id', 'label_id'),)

    document_id: Mapped[int] = ref('documents')
    label_id: Mapped[int] = ref('labels')


class DocumentTemplate(Owned, Base):
    __tablename__ = 'document_templates'

    name: Mapped[str] = col(String(80))
    category: Mapped[str | None] = col(String(40))
    body: Mapped[str] = col(Text)


class DocumentShare(Owned, Base):
    __tablename__ = 'document_shares'

    document_id: Mapped[int] = ref('documents', fixed=True)
    user_id: Mapped[int | None] = loose('users')
    team_id: Mapped[int | None] = loose('teams')
    access: Mapped[Access] = col(String(10), default=Access.VIEW)


class DocumentStar(Owned, Base):
    __tablename__ = 'document_stars'
    __table_args__ = (UniqueConstraint('document_id', 'user_id'),)

    document_id: Mapped[int] = ref('documents')
    user_id: Mapped[int] = ref('users')


class DocumentView(Owned, Base):
    __tablename__ = 'document_views'

    document_id: Mapped[int] = ref('documents')
    user_id: Mapped[int] = ref('users')


class DocumentAttachment(Owned, Base):
    __tablename__ = 'document_attachments'
    __table_args__ = (UniqueConstraint('document_id', 'file_id'),)

    document_id: Mapped[int] = ref('documents')
    file_id: Mapped[int] = ref('files')


class DocumentLink(Owned, Base):
    """One page mentions another."""
    __tablename__ = 'document_links'
    __table_args__ = (UniqueConstraint('source_id', 'target_id'),)

    source_id: Mapped[int] = ref('documents')
    target_id: Mapped[int] = ref('documents')


class GlossaryTerm(Owned, Base):
    __tablename__ = 'glossary_terms'
    __table_args__ = (UniqueConstraint('organisation_id', 'term'),)

    term: Mapped[str] = col(String(80))
    definition: Mapped[str] = col(Text)
    space_id: Mapped[int | None] = loose('spaces')


class Snippet(Owned, Base):
    __tablename__ = 'snippets'

    title: Mapped[str] = col(String(120))
    language: Mapped[str] = col(String(30), default='text')
    code: Mapped[str] = col(Text)
    author_id: Mapped[int | None] = loose('users', managed=True)
