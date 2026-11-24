"""Files keep their earlier contents, are locked while somebody edits them, go to the trash and
come back; folders do not go inside themselves; links for outsiders expire."""
import pytest

from sqlalchemy import select

from app.workspace.models.files import File, FileEvent, FileLock, FileVersion, Folder

CHECKSUM = 'a' * 64


@pytest.fixture
async def file(client, as_, at):
    response = await client.post(at('/files'), json={'name': 'plan.pdf', 'size': 10, 'checksum': CHECKSUM},
                                 headers=await as_('member'))
    return response.json()


async def replaced(client, as_, at, file, by='member', size=20):
    return await client.post(at(f'/files/{file["id"]}/contents'), json={'size': size, 'checksum': 'b' * 64},
                             headers=await as_(by))


async def test_a_file_is_stored_under_a_key_nobody_sees(file, db_session, people):
    row = await db_session.get(File, file['id'])

    assert len(row.storage_key) == 64
    assert 'storage_key' not in file
    assert (file['version'], file['uploaded_by_id']) == (1, people['member'].id)


async def test_new_contents_keep_the_old(client, as_, at, file, db_session, people):
    before = (await db_session.get(File, file['id'])).storage_key
    response = await replaced(client, as_, at, file, by='peer')

    assert (response.json()['version'], response.json()['size'], response.json()['uploaded_by_id']) == (
        2, 20, people['peer'].id,
    )
    kept = (await db_session.scalars(select(FileVersion))).all()
    assert [(v.number, v.size, v.checksum, v.storage_key, v.uploaded_by_id) for v in kept] == [
        (1, 10, CHECKSUM, before, people['member'].id),
    ]


async def test_a_rename_is_no_new_version(client, as_, at, file):
    response = await client.patch(at(f'/files/{file["id"]}'), json={'name': 'plan-v2.pdf'},
                                  headers=await as_('member'))

    assert (response.json()['name'], response.json()['version']) == ('plan-v2.pdf', 1)


@pytest.mark.parametrize('field', ['size', 'checksum', 'version', 'storage_key'])
async def test_contents_change_by_their_own_door(client, as_, at, file, field):
    response = await client.patch(at(f'/files/{file["id"]}'), json={field: 1}, headers=await as_('member'))

    assert response.status_code == 422


@pytest.mark.parametrize('body', [{'size': -1, 'checksum': CHECKSUM}, {'size': 1, 'checksum': 'xyz'},
                                  {'size': 2 ** 41, 'checksum': CHECKSUM}, {'size': 1}])
async def test_contents_malformed(client, as_, at, file, body):
    assert (await client.post(at(f'/files/{file["id"]}/contents'), json=body,
                              headers=await as_('member'))).status_code == 422


async def lock(client, as_, at, file, by='member', action='lock'):
    return await client.post(at(f'/files/{file["id"]}/{action}'), headers=await as_(by))


async def test_a_lock(client, as_, at, file, db_session, people):
    for _ in range(2):
        assert (await lock(client, as_, at, file)).status_code == 204

    locks = (await db_session.scalars(select(FileLock))).all()
    assert [lock_.user_id for lock_ in locks] == [people['member'].id]


async def test_a_locked_file_is_somebody_elses_to_edit(client, as_, at, file):
    await lock(client, as_, at, file)

    for response in (
        await lock(client, as_, at, file, by='peer'),
        await replaced(client, as_, at, file, by='peer'),
        await client.patch(at(f'/files/{file["id"]}'), json={'name': 'x'}, headers=await as_('peer')),
        await client.post(at(f'/files/{file["id"]}/trash'), headers=await as_('peer')),
    ):
        assert (response.status_code, response.json()) == (423, {'detail': 'somebody else is editing the file'})


async def test_a_locked_file_is_edited_by_whoever_locked_it(client, as_, at, file):
    await lock(client, as_, at, file)

    assert (await replaced(client, as_, at, file)).status_code == 200


@pytest.mark.parametrize('by, expected', [('member', 204), ('admin', 204), ('owner', 204), ('peer', 423)])
async def test_who_unlocks(client, as_, at, file, by, expected):
    await lock(client, as_, at, file)

    assert (await lock(client, as_, at, file, by=by, action='unlock')).status_code == expected


async def test_unlocked_it_is_anybodys(client, as_, at, file):
    await lock(client, as_, at, file)
    await lock(client, as_, at, file, action='unlock')

    assert (await replaced(client, as_, at, file, by='peer')).status_code == 200


async def test_unlock_what_is_not_locked(client, as_, at, file):
    assert (await lock(client, as_, at, file, by='peer', action='unlock')).status_code == 204


async def test_a_guest_locks_nothing(client, as_, at, file):
    assert (await lock(client, as_, at, file, by='guest')).status_code == 403


async def trash(client, as_, at, file, action='trash'):
    return await client.post(at(f'/files/{file["id"]}/{action}'), headers=await as_('member'))


async def test_trash_and_restore(client, as_, at, file):
    trashed = await trash(client, as_, at, file)
    restored = await trash(client, as_, at, file, 'restore')

    assert trashed.json()['trashed_at'] is not None
    assert restored.json()['trashed_at'] is None


async def test_a_file_in_the_trash_is_kept_as_it_is(client, as_, at, file):
    await trash(client, as_, at, file)

    changed = await client.patch(at(f'/files/{file["id"]}'), json={'name': 'x'}, headers=await as_('member'))
    assert (changed.status_code, changed.json()) == (409, {'detail': 'the file is in the trash'})
    assert (await replaced(client, as_, at, file)).status_code == 409
    assert (await trash(client, as_, at, file)).status_code == 409


async def test_restore_what_is_not_in_the_trash(client, as_, at, file):
    assert (await trash(client, as_, at, file, 'restore')).status_code == 409


async def test_what_happens_to_a_file_is_recorded(client, as_, at, file, db_session):
    await replaced(client, as_, at, file)
    await trash(client, as_, at, file)
    await trash(client, as_, at, file, 'restore')

    events = (await db_session.scalars(select(FileEvent).order_by(FileEvent.id))).all()
    assert [event.kind for event in events] == ['replaced', 'trashed', 'restored']


async def test_a_file_starred(client, as_, at, file):
    assert (await client.put(at(f'/files/{file["id"]}/star'), headers=await as_('guest'))).json() == {'count': 1}


@pytest.fixture
async def tree(new):
    """a / b / c"""
    a = await new(Folder, name='a')
    b = await new(Folder, name='b', parent_id=a.id)
    c = await new(Folder, name='c', parent_id=b.id)
    return a, b, c


async def moved(client, as_, at, folder, parent):
    return await client.patch(at(f'/folders/{folder.id}'), json={'parent_id': parent.id if parent else None},
                              headers=await as_('member'))


@pytest.mark.parametrize('folder, parent', [(0, 0), (0, 1), (0, 2), (1, 2)])
async def test_a_folder_does_not_go_inside_itself(client, as_, at, tree, folder, parent):
    response = await moved(client, as_, at, tree[folder], tree[parent])

    assert (response.status_code, response.json()) == (400, {'detail': 'a folder is not put inside itself'})


@pytest.mark.parametrize('folder, parent', [(2, 0), (1, None), (2, None)])
async def test_a_folder_moved(client, as_, at, tree, folder, parent):
    response = await moved(client, as_, at, tree[folder], None if parent is None else tree[parent])

    assert response.status_code == 200


async def test_a_folder_goes_with_what_is_in_it(client, as_, at, tree, db_session):
    await client.delete(at(f'/folders/{tree[0].id}'), headers=await as_('member'))

    assert (await db_session.scalars(select(Folder))).all() == []


async def test_a_file_outlives_its_folder(client, as_, at, new, db_session):
    folder = await new(Folder)
    kept = await new(File, folder_id=folder.id)
    await client.delete(at(f'/folders/{folder.id}'), headers=await as_('member'))

    await db_session.refresh(kept)
    assert kept.folder_id is None


async def link(client, as_, at, file, **fields):
    return await client.post(at('/share-links'), json={'file_id': file['id']} | fields, headers=await as_('member'))


async def test_a_link_for_outsiders(client, as_, at, file):
    first, second = (await link(client, as_, at, file)).json(), (await link(client, as_, at, file)).json()

    assert len(first['token']) >= 43
    assert first['token'] != second['token']
    assert first['opened'] == 0


@pytest.mark.freeze_time('2026-03-01 10:00:00')
@pytest.mark.parametrize('expires_at, expected', [
    ('2026-03-01T10:00:01Z', 201), ('2026-03-01T10:00:00Z', 400), ('2026-02-28T10:00:00Z', 400),
])
async def test_a_link_expires_later(client, as_, at, file, expires_at, expected):
    assert (await link(client, as_, at, file, expires_at=expires_at)).status_code == expected


async def test_a_link_token_is_not_given(client, as_, at, file):
    assert (await link(client, as_, at, file, token='mine')).status_code == 422
