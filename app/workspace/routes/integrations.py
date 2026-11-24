"""What connects the organisation to the world outside. Admins only, and on the record."""
import secrets

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app import security
from app.models import now
from app.workspace.access import Admin, Context
from app.workspace.crud import RowId, find, out_of, resource
from app.workspace.models.integrations import ApiKey, AutomationRule, Integration, SyncRun, Webhook, WebhookDelivery
from app.workspace.models.orgs import MemberRole

router = APIRouter(tags=['integrations'])
ADMIN = MemberRole.ADMIN


class NewKey(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class Secret(BaseModel):
    """Shown once, when it is made: only its digest, or nothing, is kept to be shown again."""
    id: int
    secret: str


async def a_webhook_with_a_secret(context: Context, webhook: Webhook, old) -> None:
    if old is None:
        webhook.secret = secrets.token_hex(32)




@router.post('/api-keys', response_model=Secret, status_code=status.HTTP_201_CREATED)
async def create_api_key(data: NewKey, context: Admin):
    key = 'sk_' + secrets.token_urlsafe(32)
    row = ApiKey(
        organisation_id=context.org_id, name=data.name, prefix=key[:12], key_digest=security.digest(key),
        created_by_id=context.user.id,
    )
    context.session.add(row)
    await context.session.commit()
    return Secret(id=row.id, secret=key)


@router.post('/api-keys/{row_id}/revoke', response_model=out_of(ApiKey))
async def revoke_api_key(row_id: RowId, context: Admin):
    key = await find(context, ApiKey, row_id)
    if key.revoked_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, 'the key is revoked')
    key.revoked_at = now()
    await context.session.commit()
    return key


@router.post('/webhooks/{row_id}/rotate', response_model=Secret)
async def rotate_webhook_secret(row_id: RowId, context: Admin):
    webhook = await find(context, Webhook, row_id)
    webhook.secret = secrets.token_hex(32)
    await context.session.commit()
    return Secret(id=webhook.id, secret=webhook.secret)


@router.post('/webhooks/{row_id}/test', response_model=out_of(WebhookDelivery), status_code=status.HTTP_201_CREATED)
async def test_webhook(row_id: RowId, context: Admin):
    webhook = await find(context, Webhook, row_id)
    if not webhook.is_active:
        raise HTTPException(status.HTTP_409_CONFLICT, 'the webhook is off')
    delivery = WebhookDelivery(organisation_id=context.org_id, webhook_id=webhook.id, event='ping')
    context.session.add(delivery)
    await context.session.commit()
    return delivery


@router.post('/integrations/{row_id}/sync', response_model=out_of(SyncRun), status_code=status.HTTP_201_CREATED)
async def sync_integration(row_id: RowId, context: Admin):
    integration = await find(context, Integration, row_id)
    if not integration.is_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, 'the integration is off')
    run = SyncRun(organisation_id=context.org_id, integration_id=integration.id)
    context.session.add(run)
    await context.session.commit()
    return run


def kept(model, **options) -> None:
    resource(router, model, **{'read': ADMIN, 'write': ADMIN, 'audited': True} | options)


kept(Webhook, check=a_webhook_with_a_secret)
kept(ApiKey, methods='list read delete')
kept(Integration, author='installed_by_id')
kept(AutomationRule, search=('name', 'trigger'))
