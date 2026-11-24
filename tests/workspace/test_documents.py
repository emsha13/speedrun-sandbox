"""Documents keep their past, go through draft, published and archived, and take comments that
get resolved."""
import pytest

from sqlalchemy import select

from app.workspace.models.docs import Document, DocumentComment, DocumentStatus, DocumentVersion, Space


@pytest.fixture
async def document(client, as_, at, new):
    space = await new(Space)
    response = await client.post(at('/documents'), json={'space_id': space.id, 'title': 'Plan', 'body': 'One'},
                                 headers=await as_('member'))
    return response.json()


async def edit(client, as_, at, document, by='peer', **changes):
    return await client.patch(at(f'/documents/{document["id"]}'), json=changes, headers=await as_(by))


async def versions(db_session):
    rows = await db_session.scalars(select(DocumentVersion).order_by(DocumentVersion.number))
    return [(row.number, row.title, row.body) for row in rows]


async def test_a_new_document_is_a_draft_of_version_one(document, people):
    assert (document['status'], document['version'], document['author_id']) == ('draft', 1, people['member'].id)


async def test_a_save_keeps_what_was_there(client, as_, at, document, db_session, people):
    response = await edit(client, as_, at, document, body='Two')

    assert (response.json()['body'], response.json()['version']) == ('Two', 2)
    assert response.json()['updated_at'] is not None
    assert await versions(db_session) == [(1, 'Plan', 'One')]
    version = await db_session.scalar(select(DocumentVersion))
    assert version.author_id == people['peer'].id


async def test_every_save_is_kept(client, as_, at, document, db_session):
    await edit(client, as_, at, document, body='Two')
    await edit(client, as_, at, document, title='Plan B')
    response = await edit(client, as_, at, document, title='Plan C', body='Three')

    assert response.json()['version'] == 4
    assert await versions(db_session) == [(1, 'Plan', 'One'), (2, 'Plan', 'Two'), (3, 'Plan B', 'Two')]


@pytest.mark.parametrize('changes', [{'title': 'Plan'}, {'body': 'One'}, {}, {'title': 'Plan', 'body': 'One'}])
async def test_a_save_of_the_same_text_is_no_version(client, as_, at, document, db_session, changes):
    response = await edit(client, as_, at, document, **changes)

    assert response.json()['version'] == 1
    assert await versions(db_session) == []


async def test_a_move_is_no_version(client, as_, at, document, db_session, new):
    parent = await new(Document, space_id=document['space_id'])
    response = await edit(client, as_, at, document, parent_id=parent.id)

    assert (response.json()['parent_id'], response.json()['version']) == (parent.id, 1)


async def test_the_versions_are_listed(client, as_, at, document):
    await edit(client, as_, at, document, body='Two')
    page = (await client.get(at('/document-versions'), params={'document_id': document['id']},
                             headers=await as_('guest'))).json()

    assert [(row['number'], row['body']) for row in page['items']] == [(1, 'One')]


async def test_the_versions_go_with_the_document(client, as_, at, document, db_session):
    await edit(client, as_, at, document, body='Two')
    await client.delete(at(f'/documents/{document["id"]}'), headers=await as_('member'))

    assert await versions(db_session) == []


async def test_a_document_is_not_its_own_parent(client, as_, at, document):
    response = await edit(client, as_, at, document, parent_id=document['id'])

    assert response.status_code == 400


@pytest.mark.parametrize('field', ['version', 'status', 'author_id', 'published_at'])
async def test_what_a_document_keeps_itself(client, as_, at, document, field):
    assert (await edit(client, as_, at, document, **{field: 3})).status_code == 422


async def act(client, as_, at, document, action, by='member'):
    return await client.post(at(f'/documents/{document["id"]}/{action}'), headers=await as_(by))


async def test_publish(client, as_, at, document):
    response = await act(client, as_, at, document, 'publish')

    assert response.json()['status'] == 'published'
    assert response.json()['published_at'] is not None


async def test_archive_a_draft(client, as_, at, document):
    assert (await act(client, as_, at, document, 'archive')).json()['status'] == 'archived'


async def test_archive_what_is_published(client, as_, at, document):
    await act(client, as_, at, document, 'publish')
    response = await act(client, as_, at, document, 'archive')

    assert response.json()['status'] == 'archived'
    assert response.json()['published_at'] is not None


@pytest.mark.parametrize('actions, expected', [
    (['publish', 'publish'], 'the document is published'),
    (['archive', 'publish'], 'the document is archived'),
    (['archive', 'archive'], 'the document is archived'),
])
async def test_out_of_turn(client, as_, at, document, actions, expected):
    for action in actions:
        response = await act(client, as_, at, document, action)

    assert (response.status_code, response.json()) == (409, {'detail': expected})


@pytest.mark.parametrize('action', ['publish', 'archive'])
async def test_a_guest_neither_publishes_nor_archives(client, as_, at, document, action):
    assert (await act(client, as_, at, document, action, by='guest')).status_code == 403


async def test_search_finds_words_inside(client, as_, at, document):
    await edit(client, as_, at, document, body='The quarterly numbers, at last')
    page = (await client.get(at('/documents'), params={'search': 'QUARTER'}, headers=await as_('guest'))).json()

    assert [row['id'] for row in page['items']] == [document['id']]


async def test_documents_by_status(client, as_, at, new, document):
    other = await new(Document, status=DocumentStatus.PUBLISHED)
    page = (await client.get(at('/documents'), params={'status': 'published'}, headers=await as_('guest'))).json()

    assert [row['id'] for row in page['items']] == [other.id]


async def test_a_comment_resolved(client, as_, at, new):
    comment = await new(DocumentComment)
    response = await client.post(at(f'/document-comments/{comment.id}/resolve'), headers=await as_('peer'))

    assert response.json()['resolved_at'] is not None


async def test_a_comment_resolved_once(client, as_, at, new):
    comment = await new(DocumentComment)
    await client.post(at(f'/document-comments/{comment.id}/resolve'), headers=await as_('peer'))

    response = await client.post(at(f'/document-comments/{comment.id}/resolve'), headers=await as_('peer'))
    assert (response.status_code, response.json()) == (409, {'detail': 'the comment is resolved'})


async def test_a_comment_edited_keeps_the_time(client, as_, at, document):
    made = (await client.post(at('/document-comments'), json={'document_id': document['id'], 'body': 'Hm'},
                              headers=await as_('member'))).json()
    edited = await client.patch(at(f'/document-comments/{made["id"]}'), json={'body': 'Hmm'},
                                headers=await as_('member'))

    assert made['updated_at'] is None
    assert edited.json()['updated_at'] is not None


async def test_a_document_starred(client, as_, at, document):
    response = await client.put(at(f'/documents/{document["id"]}/star'), headers=await as_('guest'))

    assert response.json() == {'count': 1}


async def test_a_space_key_once(client, as_, at):
    for expected in (201, 409):
        response = await client.post(at('/spaces'), json={'name': 'Eng', 'key': 'ENG'}, headers=await as_('admin'))
        assert response.status_code == expected
