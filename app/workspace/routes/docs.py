"""Documents."""
from fastapi import APIRouter, HTTPException, status

from app.models import now
from app.workspace.access import Context, Member
from app.workspace.crud import RowId, find, mark, out_of, resource
from app.workspace.models.docs import Document, DocumentComment, DocumentStar, DocumentStatus, DocumentVersion, Space
from app.workspace.models.orgs import MemberRole

router = APIRouter(tags=['documents'])


async def a_document_that_keeps_its_past(context: Context, document: Document, old) -> None:
    if old is None:
        return
    if document.parent_id == document.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'a document is not its own parent')
    before = {name: old.get(name, getattr(document, name)) for name in ('title', 'body')}
    if (before['title'], before['body']) != (document.title, document.body):
        context.session.add(DocumentVersion(
            organisation_id=context.org_id, document_id=document.id, number=document.version,
            author_id=context.user.id, **before,
        ))
        document.version += 1




@router.post('/documents/{row_id}/publish', response_model=out_of(Document))
async def publish_document(row_id: RowId, context: Member):
    document = await find(context, Document, row_id)
    if document.status != DocumentStatus.DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, f'the document is {document.status}')
    document.status, document.published_at = DocumentStatus.PUBLISHED, now()
    await context.session.commit()
    return document


@router.post('/documents/{row_id}/archive', response_model=out_of(Document))
async def archive_document(row_id: RowId, context: Member):
    document = await find(context, Document, row_id)
    if document.status == DocumentStatus.ARCHIVED:
        raise HTTPException(status.HTTP_409_CONFLICT, 'the document is archived')
    document.status = DocumentStatus.ARCHIVED
    await context.session.commit()
    return document


@router.post('/document-comments/{row_id}/resolve', response_model=out_of(DocumentComment))
async def resolve_comment(row_id: RowId, context: Member):
    comment = await find(context, DocumentComment, row_id)
    if comment.resolved_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, 'the comment is resolved')
    comment.resolved_at = now()
    await context.session.commit()
    return comment


mark(router, Document, DocumentStar, 'document_id', 'star')

resource(router, Space, write=MemberRole.ADMIN, search=('name', 'key'))
resource(
    router, Document, search=('title', 'body'), author='author_id', check=a_document_that_keeps_its_past,
)
resource(router, DocumentVersion, methods='list read')
resource(router, DocumentComment, author='author_id', own=True)
