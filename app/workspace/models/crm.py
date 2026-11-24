"""Customers: companies, the people in them, and what is being sold to them."""
import enum

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped

from app.db import Base
from app.workspace.base import COUNTRY, CURRENCY, EMAIL, URL, Owned, col, loose, moment, money, ref


class StageKind(enum.StrEnum):
    OPEN = 'open'
    WON = 'won'
    LOST = 'lost'


class LeadStatus(enum.StrEnum):
    NEW = 'new'
    QUALIFIED = 'qualified'
    CONVERTED = 'converted'
    LOST = 'lost'


class ActivityKind(enum.StrEnum):
    CALL = 'call'
    MEETING = 'meeting'
    EMAIL = 'email'
    NOTE = 'note'


class QuoteStatus(enum.StrEnum):
    DRAFT = 'draft'
    SENT = 'sent'
    ACCEPTED = 'accepted'
    DECLINED = 'declined'


class Reach(enum.StrEnum):
    SENT = 'sent'
    OPENED = 'opened'
    REPLIED = 'replied'
    BOUNCED = 'bounced'


class Company(Owned, Base):
    __tablename__ = 'companies'

    name: Mapped[str] = col(String(120))
    domain: Mapped[str | None] = col(String(253))
    industry: Mapped[str | None] = col(String(60))
    employees: Mapped[int | None] = col(ge=1)
    country: Mapped[str | None] = col(String(2), pattern=COUNTRY)
    website: Mapped[str | None] = col(String(500), pattern=URL)
    phone: Mapped[str | None] = col(String(30))
    owner_id: Mapped[int | None] = loose('users')


class Contact(Owned, Base):
    __tablename__ = 'contacts'

    company_id: Mapped[int | None] = loose('companies')
    first_name: Mapped[str] = col(String(60))
    last_name: Mapped[str] = col(String(60))
    email: Mapped[str | None] = col(String(254), pattern=EMAIL)
    phone: Mapped[str | None] = col(String(30))
    position: Mapped[str | None] = col(String(80))
    owner_id: Mapped[int | None] = loose('users')
    is_unsubscribed: Mapped[bool] = col(default=False)


class ContactTag(Owned, Base):
    __tablename__ = 'contact_tags'
    __table_args__ = (UniqueConstraint('organisation_id', 'name'),)

    name: Mapped[str] = col(String(40))


class ContactTagLink(Owned, Base):
    __tablename__ = 'contact_tag_links'
    __table_args__ = (UniqueConstraint('contact_id', 'tag_id'),)

    contact_id: Mapped[int] = ref('contacts')
    tag_id: Mapped[int] = ref('contact_tags')


class Pipeline(Owned, Base):
    __tablename__ = 'pipelines'
    __table_args__ = (UniqueConstraint('organisation_id', 'name'),)

    name: Mapped[str] = col(String(60))
    is_default: Mapped[bool] = col(default=False)


class Stage(Owned, Base):
    __tablename__ = 'stages'

    pipeline_id: Mapped[int] = ref('pipelines', fixed=True)
    name: Mapped[str] = col(String(60))
    position: Mapped[int] = col(default=0, ge=0)
    probability: Mapped[int] = col(default=50, ge=0, le=100)
    kind: Mapped[StageKind] = col(String(10), default=StageKind.OPEN)


class Deal(Owned, Base):
    __tablename__ = 'deals'

    title: Mapped[str] = col(String(200))
    # A deal is in a pipeline by being at one of its stages. It changes stage by `move`, which
    # keeps the history, so the stage is set here once.
    stage_id: Mapped[int] = ref('stages', fixed=True)
    company_id: Mapped[int | None] = loose('companies')
    contact_id: Mapped[int | None] = loose('contacts')
    amount: Mapped[Decimal] = money(default=Decimal(0), ge=0)
    currency: Mapped[str] = col(String(3), default='EUR', pattern=CURRENCY)
    owner_id: Mapped[int | None] = loose('users')
    expected_on: Mapped[date | None]
    lost_reason: Mapped[str | None] = col(String(300))
    closed_at: Mapped[datetime | None] = moment(managed=True)


class DealStageChange(Owned, Base):
    __tablename__ = 'deal_stage_changes'

    deal_id: Mapped[int] = ref('deals')
    from_stage_id: Mapped[int | None] = loose('stages')
    to_stage_id: Mapped[int | None] = loose('stages')
    changed_by_id: Mapped[int | None] = loose('users')


class LeadSource(Owned, Base):
    __tablename__ = 'lead_sources'
    __table_args__ = (UniqueConstraint('organisation_id', 'name'),)

    name: Mapped[str] = col(String(60))


class Lead(Owned, Base):
    __tablename__ = 'leads'

    first_name: Mapped[str] = col(String(60))
    last_name: Mapped[str] = col(String(60))
    email: Mapped[str | None] = col(String(254), pattern=EMAIL)
    company_name: Mapped[str | None] = col(String(120))
    source_id: Mapped[int | None] = loose('lead_sources')
    owner_id: Mapped[int | None] = loose('users')
    status: Mapped[LeadStatus] = col(String(10), default=LeadStatus.NEW)
    contact_id: Mapped[int | None] = loose('contacts', managed=True)


class Activity(Owned, Base):
    __tablename__ = 'activities'

    kind: Mapped[ActivityKind] = col(String(10))
    subject: Mapped[str] = col(String(200))
    body: Mapped[str | None] = col(Text)
    contact_id: Mapped[int | None] = loose('contacts')
    company_id: Mapped[int | None] = loose('companies')
    deal_id: Mapped[int | None] = loose('deals')
    author_id: Mapped[int | None] = loose('users', managed=True)
    happened_at: Mapped[datetime] = moment()
    minutes: Mapped[int | None] = col(ge=0, le=1440)


class FollowUp(Owned, Base):
    __tablename__ = 'follow_ups'

    text: Mapped[str] = col(String(300))
    deal_id: Mapped[int | None] = loose('deals')
    contact_id: Mapped[int | None] = loose('contacts')
    assignee_id: Mapped[int | None] = loose('users')
    due_on: Mapped[date]
    is_done: Mapped[bool] = col(default=False)


class Product(Owned, Base):
    __tablename__ = 'products'
    __table_args__ = (UniqueConstraint('organisation_id', 'sku'),)

    name: Mapped[str] = col(String(120))
    sku: Mapped[str] = col(String(40))
    description: Mapped[str | None] = col(Text)
    price: Mapped[Decimal] = money(ge=0)
    currency: Mapped[str] = col(String(3), default='EUR', pattern=CURRENCY)
    is_active: Mapped[bool] = col(default=True)


class DealProduct(Owned, Base):
    __tablename__ = 'deal_products'

    deal_id: Mapped[int] = ref('deals', fixed=True)
    product_id: Mapped[int] = ref('products', fixed=True)
    quantity: Mapped[int] = col(default=1, ge=1, le=100000)
    unit_price: Mapped[Decimal] = money(ge=0)
    discount_percent: Mapped[int] = col(default=0, ge=0, le=100)


class Quote(Owned, Base):
    __tablename__ = 'quotes'

    deal_id: Mapped[int] = ref('deals', fixed=True)
    title: Mapped[str] = col(String(120))
    status: Mapped[QuoteStatus] = col(String(10), default=QuoteStatus.DRAFT)
    valid_until: Mapped[date | None]
    notes: Mapped[str | None] = col(Text)


class QuoteLine(Owned, Base):
    __tablename__ = 'quote_lines'

    quote_id: Mapped[int] = ref('quotes', fixed=True)
    product_id: Mapped[int | None] = loose('products')
    description: Mapped[str] = col(String(300))
    quantity: Mapped[int] = col(default=1, ge=1, le=100000)
    unit_price: Mapped[Decimal] = money(ge=0)


class Territory(Owned, Base):
    __tablename__ = 'territories'

    name: Mapped[str] = col(String(80))
    region: Mapped[str | None] = col(String(80))
    manager_id: Mapped[int | None] = loose('users')


class Competitor(Owned, Base):
    __tablename__ = 'competitors'

    name: Mapped[str] = col(String(120))
    website: Mapped[str | None] = col(String(500), pattern=URL)
    strengths: Mapped[str | None] = col(Text)
    weaknesses: Mapped[str | None] = col(Text)


class MailTemplate(Owned, Base):
    __tablename__ = 'mail_templates'

    name: Mapped[str] = col(String(80))
    subject: Mapped[str] = col(String(200))
    body: Mapped[str] = col(Text)
    author_id: Mapped[int | None] = loose('users', managed=True)
    is_shared: Mapped[bool] = col(default=True)


class Campaign(Owned, Base):
    __tablename__ = 'campaigns'

    name: Mapped[str] = col(String(120))
    template_id: Mapped[int | None] = loose('mail_templates')
    starts_on: Mapped[date | None]
    ends_on: Mapped[date | None]
    budget: Mapped[Decimal | None] = money(ge=0)
    is_running: Mapped[bool] = col(default=False)


class CampaignMember(Owned, Base):
    __tablename__ = 'campaign_members'
    __table_args__ = (UniqueConstraint('campaign_id', 'contact_id'),)

    campaign_id: Mapped[int] = ref('campaigns', fixed=True)
    contact_id: Mapped[int] = ref('contacts', fixed=True)
    reach: Mapped[Reach] = col(String(10), default=Reach.SENT)


class ExchangeRate(Owned, Base):
    __tablename__ = 'exchange_rates'
    __table_args__ = (UniqueConstraint('organisation_id', 'base', 'quote', 'day'),)

    base: Mapped[str] = col(String(3), pattern=CURRENCY, fixed=True)
    quote: Mapped[str] = col(String(3), pattern=CURRENCY, fixed=True)
    day: Mapped[date] = col(fixed=True)
    rate: Mapped[Decimal] = col(Numeric(12, 6), gt=0)
