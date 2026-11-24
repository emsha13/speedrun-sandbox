"""Money: what customers are billed and have paid, and what the organisation itself spends."""
import enum

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped

from app.db import Base
from app.workspace.base import COUNTRY, CURRENCY, EMAIL, Owned, col, loose, moment, money, ref
from app.workspace.models.orgs import Decision


class InvoiceStatus(enum.StrEnum):
    DRAFT = 'draft'
    SENT = 'sent'
    PAID = 'paid'
    VOID = 'void'


class PaymentMethod(enum.StrEnum):
    CARD = 'card'
    TRANSFER = 'transfer'
    CASH = 'cash'


class Interval(enum.StrEnum):
    MONTH = 'month'
    YEAR = 'year'


class OrderStatus(enum.StrEnum):
    DRAFT = 'draft'
    ORDERED = 'ordered'
    RECEIVED = 'received'
    CANCELLED = 'cancelled'


class TaxRate(Owned, Base):
    __tablename__ = 'tax_rates'
    __table_args__ = (UniqueConstraint('organisation_id', 'name'),)

    name: Mapped[str] = col(String(60))
    percent: Mapped[Decimal] = col(Numeric(5, 2), ge=0, le=100)
    country: Mapped[str | None] = col(String(2), pattern=COUNTRY)


class Invoice(Owned, Base):
    __tablename__ = 'invoices'
    __table_args__ = (UniqueConstraint('organisation_id', 'number'),)

    company_id: Mapped[int] = ref('companies', fixed=True)
    number: Mapped[int] = col(managed=True)
    currency: Mapped[str] = col(String(3), default='EUR', pattern=CURRENCY, fixed=True)
    due_on: Mapped[date | None]
    notes: Mapped[str | None] = col(Text)
    status: Mapped[InvoiceStatus] = col(String(10), default=InvoiceStatus.DRAFT, managed=True)
    issued_on: Mapped[date | None] = col(managed=True)
    # Kept in step with the lines and the payments by whatever changes those.
    subtotal: Mapped[Decimal] = money(default=Decimal(0), managed=True)
    tax: Mapped[Decimal] = money(default=Decimal(0), managed=True)
    total: Mapped[Decimal] = money(default=Decimal(0), managed=True)
    paid: Mapped[Decimal] = money(default=Decimal(0), managed=True)


class InvoiceLine(Owned, Base):
    __tablename__ = 'invoice_lines'

    invoice_id: Mapped[int] = ref('invoices', fixed=True)
    description: Mapped[str] = col(String(300))
    quantity: Mapped[int] = col(default=1, ge=1, le=100000)
    unit_price: Mapped[Decimal] = money(ge=0)
    tax_rate_id: Mapped[int | None] = loose('tax_rates')


class Payment(Owned, Base):
    __tablename__ = 'payments'

    invoice_id: Mapped[int] = ref('invoices', fixed=True)
    amount: Mapped[Decimal] = money(gt=0)
    method: Mapped[PaymentMethod] = col(String(10))
    received_on: Mapped[date]
    reference: Mapped[str | None] = col(String(80))


class CreditNote(Owned, Base):
    __tablename__ = 'credit_notes'

    invoice_id: Mapped[int] = ref('invoices', fixed=True)
    amount: Mapped[Decimal] = money(gt=0)
    reason: Mapped[str] = col(String(300))


class Subscription(Owned, Base):
    __tablename__ = 'subscriptions'

    company_id: Mapped[int] = ref('companies', fixed=True)
    product_id: Mapped[int] = ref('products', fixed=True)
    quantity: Mapped[int] = col(default=1, ge=1, le=100000)
    interval: Mapped[Interval] = col(String(10), default=Interval.MONTH)
    started_on: Mapped[date]
    renews_on: Mapped[date | None]
    cancelled_at: Mapped[datetime | None] = moment(managed=True)


class SubscriptionEvent(Owned, Base):
    __tablename__ = 'subscription_events'

    subscription_id: Mapped[int] = ref('subscriptions')
    kind: Mapped[str] = col(String(30))
    actor_id: Mapped[int | None] = loose('users')


class BillingAddress(Owned, Base):
    __tablename__ = 'billing_addresses'

    company_id: Mapped[int] = ref('companies', fixed=True)
    line1: Mapped[str] = col(String(120))
    line2: Mapped[str | None] = col(String(120))
    city: Mapped[str] = col(String(80))
    postal_code: Mapped[str] = col(String(12))
    country: Mapped[str] = col(String(2), pattern=COUNTRY)


class Coupon(Owned, Base):
    __tablename__ = 'coupons'
    __table_args__ = (UniqueConstraint('organisation_id', 'code'),)

    code: Mapped[str] = col(String(30), fixed=True)
    percent_off: Mapped[int] = col(ge=1, le=100)
    valid_until: Mapped[date | None]
    max_uses: Mapped[int | None] = col(ge=1)
    used: Mapped[int] = col(default=0, managed=True)


class CouponRedemption(Owned, Base):
    __tablename__ = 'coupon_redemptions'
    __table_args__ = (UniqueConstraint('coupon_id', 'invoice_id'),)

    coupon_id: Mapped[int] = ref('coupons')
    invoice_id: Mapped[int] = ref('invoices')


class ExpenseCategory(Owned, Base):
    __tablename__ = 'expense_categories'
    __table_args__ = (UniqueConstraint('organisation_id', 'name'),)

    name: Mapped[str] = col(String(60))
    is_active: Mapped[bool] = col(default=True)


class Expense(Owned, Base):
    __tablename__ = 'expenses'

    category_id: Mapped[int | None] = loose('expense_categories')
    project_id: Mapped[int | None] = loose('projects')
    amount: Mapped[Decimal] = money(gt=0)
    currency: Mapped[str] = col(String(3), default='EUR', pattern=CURRENCY)
    spent_on: Mapped[date]
    vendor: Mapped[str | None] = col(String(120))
    description: Mapped[str | None] = col(String(500))
    submitted_by_id: Mapped[int | None] = loose('users', managed=True)
    status: Mapped[Decision] = col(String(10), default=Decision.PENDING, managed=True)
    decided_by_id: Mapped[int | None] = loose('users', managed=True)


class Budget(Owned, Base):
    __tablename__ = 'budgets'

    name: Mapped[str] = col(String(80))
    project_id: Mapped[int | None] = loose('projects')
    amount: Mapped[Decimal] = money(ge=0)
    currency: Mapped[str] = col(String(3), default='EUR', pattern=CURRENCY)
    starts_on: Mapped[date]
    ends_on: Mapped[date]


class Vendor(Owned, Base):
    __tablename__ = 'vendors'

    name: Mapped[str] = col(String(120))
    email: Mapped[str | None] = col(String(254), pattern=EMAIL)
    tax_number: Mapped[str | None] = col(String(40))
    country: Mapped[str | None] = col(String(2), pattern=COUNTRY)


class CostCentre(Owned, Base):
    __tablename__ = 'cost_centres'
    __table_args__ = (UniqueConstraint('organisation_id', 'code'),)

    code: Mapped[str] = col(String(20))
    name: Mapped[str] = col(String(80))
    department_id: Mapped[int | None] = loose('departments')


class PurchaseOrder(Owned, Base):
    __tablename__ = 'purchase_orders'

    vendor_id: Mapped[int] = ref('vendors', fixed=True)
    cost_centre_id: Mapped[int | None] = loose('cost_centres')
    reference: Mapped[str] = col(String(40))
    status: Mapped[OrderStatus] = col(String(10), default=OrderStatus.DRAFT)
    ordered_on: Mapped[date | None]
    requested_by_id: Mapped[int | None] = loose('users', managed=True)


class PurchaseOrderLine(Owned, Base):
    __tablename__ = 'purchase_order_lines'

    order_id: Mapped[int] = ref('purchase_orders', fixed=True)
    description: Mapped[str] = col(String(300))
    quantity: Mapped[int] = col(default=1, ge=1, le=100000)
    unit_price: Mapped[Decimal] = money(ge=0)
