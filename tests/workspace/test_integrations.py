"""Keys and secrets are shown once and kept as digests; webhooks and integrations are switched off
and on."""
import pytest

from sqlalchemy import select

from app import security
from app.workspace.models.integrations import ApiKey, Integration, SyncRun, Webhook, WebhookDelivery


async def made_key(client, as_, at, name='CI'):
    response = await client.post(at('/api-keys'), json={'name': name}, headers=await as_('admin'))
    assert response.status_code == 201
    return response.json()


async def test_a_key_is_shown_once(client, as_, at, db_session):
    made = await made_key(client, as_, at)
    row = await db_session.get(ApiKey, made['id'])

    assert made['secret'].startswith('sk_')
    assert (row.prefix, row.key_digest) == (made['secret'][:12], security.digest(made['secret']))
    shown = (await client.get(at(f'/api-keys/{made["id"]}'), headers=await as_('admin'))).json()
    assert made['secret'] not in str(shown)
    assert 'key_digest' not in shown


async def test_two_keys_differ(client, as_, at):
    assert (await made_key(client, as_, at))['secret'] != (await made_key(client, as_, at))['secret']


async def test_a_key_has_whoever_made_it(client, as_, at, people):
    made = await made_key(client, as_, at)
    shown = (await client.get(at(f'/api-keys/{made["id"]}'), headers=await as_('admin'))).json()

    assert shown['created_by_id'] == people['admin'].id


async def test_a_key_revoked(client, as_, at):
    made = await made_key(client, as_, at)
    revoked = await client.post(at(f'/api-keys/{made["id"]}/revoke'), headers=await as_('admin'))
    again = await client.post(at(f'/api-keys/{made["id"]}/revoke'), headers=await as_('admin'))

    assert revoked.json()['revoked_at'] is not None
    assert (again.status_code, again.json()) == (409, {'detail': 'the key is revoked'})


@pytest.mark.parametrize('role', ['member', 'guest'])
async def test_keys_are_for_admins(client, as_, at, role):
    assert (await client.post(at('/api-keys'), json={'name': 'CI'}, headers=await as_(role))).status_code == 403


@pytest.mark.parametrize('name', ['', 'x' * 81])
async def test_a_key_of_a_malformed_name(client, as_, at, name):
    assert (await client.post(at('/api-keys'), json={'name': name}, headers=await as_('admin'))).status_code == 422


async def test_a_key_of_another_organisation(client, as_, at, new, other_org):
    theirs = await new(ApiKey, by='outsider', organisation=other_org)

    assert (await client.post(at(f'/api-keys/{theirs.id}/revoke'), headers=await as_('admin'))).status_code == 404


@pytest.fixture
async def webhook(client, as_, at):
    response = await client.post(at('/webhooks'), json={'url': 'https://example.com/hook', 'events': ['task.done']},
                                 headers=await as_('admin'))
    return response.json()


async def test_a_webhook_secret_is_kept_and_not_shown(webhook, db_session):
    row = await db_session.get(Webhook, webhook['id'])

    assert len(row.secret) == 64
    assert 'secret' not in webhook


async def test_a_webhook_secret_rotated(client, as_, at, webhook, db_session):
    before = (await db_session.get(Webhook, webhook['id'])).secret
    response = await client.post(at(f'/webhooks/{webhook["id"]}/rotate'), headers=await as_('admin'))

    assert response.json()['id'] == webhook['id']
    assert response.json()['secret'] != before
    db_session.expire_all()
    assert (await db_session.get(Webhook, webhook['id'])).secret == response.json()['secret']


async def test_a_webhook_tried(client, as_, at, webhook, db_session):
    response = await client.post(at(f'/webhooks/{webhook["id"]}/test'), headers=await as_('admin'))

    assert response.status_code == 201
    assert (response.json()['event'], response.json()['status']) == ('ping', 'queued')
    assert len((await db_session.scalars(select(WebhookDelivery))).all()) == 1


async def test_a_webhook_switched_off_is_not_tried(client, as_, at, webhook):
    await client.patch(at(f'/webhooks/{webhook["id"]}'), json={'is_active': False}, headers=await as_('admin'))
    response = await client.post(at(f'/webhooks/{webhook["id"]}/test'), headers=await as_('admin'))

    assert (response.status_code, response.json()) == (409, {'detail': 'the webhook is off'})


@pytest.mark.parametrize('url', ['example.com/hook', 'ftp://example.com', 'https://', 'https://a b'])
async def test_a_webhook_to_a_malformed_address(client, as_, at, url):
    assert (await client.post(at('/webhooks'), json={'url': url}, headers=await as_('admin'))).status_code == 422


async def test_a_webhook_on_the_record(client, as_, at, webhook):
    records = (await client.get(at('/audit-records'), headers=await as_('admin'))).json()

    assert [(row['action'], row['subject']) for row in records['items']] == [('create', 'webhooks')]


@pytest.fixture
async def integration(new):
    return await new(Integration)


async def sync(client, as_, at, integration):
    return await client.post(at(f'/integrations/{integration.id}/sync'), headers=await as_('admin'))


async def test_a_sync(client, as_, at, integration, db_session):
    response = await sync(client, as_, at, integration)

    assert (response.status_code, response.json()['status']) == (201, 'queued')
    assert len((await db_session.scalars(select(SyncRun))).all()) == 1


async def test_a_disabled_integration_does_not_sync(client, as_, at, new):
    response = await sync(client, as_, at, await new(Integration, is_enabled=False))

    assert (response.status_code, response.json()) == (409, {'detail': 'the integration is off'})


async def test_one_integration_of_a_provider(client, as_, at):
    body = {'provider': 'calendar-sync', 'name': 'Calendars'}
    for expected in (201, 409):
        assert (await client.post(at('/integrations'), json=body, headers=await as_('admin'))).status_code == expected


async def test_the_provider_is_set_once(client, as_, at, integration):
    response = await client.patch(at(f'/integrations/{integration.id}'), json={'provider': 'other'},
                                  headers=await as_('admin'))

    assert response.status_code == 422


async def test_an_integration_has_whoever_installed_it(client, as_, at, people):
    response = await client.post(at('/integrations'), json={'provider': 'p', 'name': 'P'}, headers=await as_('owner'))

    assert response.json()['installed_by_id'] == people['owner'].id
