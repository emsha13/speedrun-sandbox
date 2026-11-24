"""What connects the organisation to the world outside it."""
import enum

from datetime import datetime
from typing import Any

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped

from app.db import Base
from app.workspace.base import URL, Owned, col, loose, moment, ref
from app.workspace.models.messages import Delivery


class JobStatus(enum.StrEnum):
    QUEUED = 'queued'
    RUNNING = 'running'
    DONE = 'done'
    FAILED = 'failed'


class Transfer(enum.StrEnum):
    TASKS = 'tasks'
    CONTACTS = 'contacts'
    TICKETS = 'tickets'


class SsoKind(enum.StrEnum):
    SAML = 'saml'
    OIDC = 'oidc'


class Webhook(Owned, Base):
    __tablename__ = 'webhooks'

    url: Mapped[str] = col(String(500), pattern=URL)
    events: Mapped[list[str]] = col(JSONB, default=list)
    is_active: Mapped[bool] = col(default=True)
    # What deliveries are signed with. Made here, shown once, when the webhook is.
    secret: Mapped[str] = col(String(64), managed=True, hidden=True)
    failures: Mapped[int] = col(default=0, managed=True)


class WebhookDelivery(Owned, Base):
    __tablename__ = 'webhook_deliveries'

    webhook_id: Mapped[int] = ref('webhooks')
    event: Mapped[str] = col(String(60))
    status: Mapped[Delivery] = col(String(10), default=Delivery.QUEUED)
    response_code: Mapped[int | None]
    attempts: Mapped[int] = col(default=0)


class ApiKey(Owned, Base):
    __tablename__ = 'api_keys'

    name: Mapped[str] = col(String(80))
    # The first characters of the key, so its owner can tell which one a row is.
    prefix: Mapped[str] = col(String(12))
    key_digest: Mapped[str] = col(String(64), unique=True, hidden=True)
    created_by_id: Mapped[int | None] = loose('users')
    last_used_at: Mapped[datetime | None] = moment()
    revoked_at: Mapped[datetime | None] = moment()


class OauthApp(Owned, Base):
    __tablename__ = 'oauth_apps'

    name: Mapped[str] = col(String(80))
    client_id: Mapped[str] = col(String(40), unique=True, managed=True)
    redirect_url: Mapped[str] = col(String(500), pattern=URL)
    scopes: Mapped[list[str]] = col(JSONB, default=list)
    is_confidential: Mapped[bool] = col(default=True)


class OauthGrant(Owned, Base):
    __tablename__ = 'oauth_grants'
    __table_args__ = (UniqueConstraint('app_id', 'user_id'),)

    app_id: Mapped[int] = ref('oauth_apps')
    user_id: Mapped[int] = ref('users')
    scopes: Mapped[list[str]] = col(JSONB, default=list)


class Integration(Owned, Base):
    __tablename__ = 'integrations'
    __table_args__ = (UniqueConstraint('organisation_id', 'provider'),)

    provider: Mapped[str] = col(String(40), fixed=True)
    name: Mapped[str] = col(String(80))
    options: Mapped[dict[str, Any]] = col(JSONB, default=dict)
    is_enabled: Mapped[bool] = col(default=True)
    installed_by_id: Mapped[int | None] = loose('users', managed=True)


class SyncRun(Owned, Base):
    __tablename__ = 'sync_runs'

    integration_id: Mapped[int] = ref('integrations')
    status: Mapped[JobStatus] = col(String(10), default=JobStatus.QUEUED)
    items: Mapped[int] = col(default=0)
    error: Mapped[str | None] = col(String(300))
    finished_at: Mapped[datetime | None] = moment()


class ConnectedAccount(Owned, Base):
    """A member's own account somewhere else, linked to them here."""
    __tablename__ = 'connected_accounts'
    __table_args__ = (UniqueConstraint('user_id', 'provider'),)

    user_id: Mapped[int] = ref('users', managed=True)
    provider: Mapped[str] = col(String(40), fixed=True)
    external_id: Mapped[str] = col(String(120), fixed=True)
    display_name: Mapped[str | None] = col(String(120))


class ImportJob(Owned, Base):
    __tablename__ = 'import_jobs'

    what: Mapped[Transfer] = col(String(10))
    file_id: Mapped[int] = ref('files')
    started_by_id: Mapped[int | None] = loose('users', managed=True)
    status: Mapped[JobStatus] = col(String(10), default=JobStatus.QUEUED, managed=True)
    rows_read: Mapped[int] = col(default=0, managed=True)
    rows_refused: Mapped[int] = col(default=0, managed=True)


class ExportJob(Owned, Base):
    __tablename__ = 'export_jobs'

    what: Mapped[Transfer] = col(String(10))
    started_by_id: Mapped[int | None] = loose('users', managed=True)
    status: Mapped[JobStatus] = col(String(10), default=JobStatus.QUEUED, managed=True)
    file_id: Mapped[int | None] = loose('files', managed=True)


class ExternalLink(Owned, Base):
    """A thing here is the same as a thing in another system."""
    __tablename__ = 'external_links'
    __table_args__ = (UniqueConstraint('integration_id', 'subject', 'subject_id'),)

    integration_id: Mapped[int] = ref('integrations', fixed=True)
    subject: Mapped[str] = col(String(30), fixed=True)
    subject_id: Mapped[int] = col(fixed=True, ge=1)
    external_id: Mapped[str] = col(String(120))
    url: Mapped[str | None] = col(String(500), pattern=URL)


class AutomationRule(Owned, Base):
    __tablename__ = 'automation_rules'

    name: Mapped[str] = col(String(80))
    trigger: Mapped[str] = col(String(60))
    conditions: Mapped[list[dict[str, Any]]] = col(JSONB, default=list)
    actions: Mapped[list[dict[str, Any]]] = col(JSONB, default=list)
    is_enabled: Mapped[bool] = col(default=True)
    runs: Mapped[int] = col(default=0, managed=True)


class AutomationRun(Owned, Base):
    __tablename__ = 'automation_runs'

    rule_id: Mapped[int] = ref('automation_rules')
    status: Mapped[JobStatus] = col(String(10), default=JobStatus.DONE)
    detail: Mapped[str | None] = col(Text)


class SsoProvider(Owned, Base):
    __tablename__ = 'sso_providers'

    kind: Mapped[SsoKind] = col(String(10), fixed=True)
    name: Mapped[str] = col(String(80))
    issuer: Mapped[str] = col(String(500), pattern=URL)
    is_enabled: Mapped[bool] = col(default=False)


class AllowedNetwork(Owned, Base):
    __tablename__ = 'allowed_networks'
    __table_args__ = (UniqueConstraint('organisation_id', 'cidr'),)

    cidr: Mapped[str] = col(String(43), pattern=r'^[0-9a-f:.]+/[0-9]{1,3}$')
    label: Mapped[str | None] = col(String(80))


class FeatureFlag(Owned, Base):
    __tablename__ = 'feature_flags'
    __table_args__ = (UniqueConstraint('organisation_id', 'name'),)

    name: Mapped[str] = col(String(60), fixed=True, pattern=r'^[a-z][a-z0-9_.]*$')
    is_on: Mapped[bool] = col(default=False)
    note: Mapped[str | None] = col(String(300))
