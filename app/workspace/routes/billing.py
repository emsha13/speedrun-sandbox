"""Money. Members see it, admins change it, and every change is on the record."""
from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.models import now
from app.workspace.access import Admin, Context
from app.workspace.crud import RowId, find, out_of, resource
from app.workspace.models.billing import (
    Expense, Invoice, InvoiceLine, InvoiceStatus, Payment, Subscription, SubscriptionEvent, TaxRate,
)
from app.workspace.models.orgs import Decision, MemberRole

router = APIRouter(tags=['billing'])
MEMBER, ADMIN = MemberRole.MEMBER, MemberRole.ADMIN
CENT = Decimal('0.01')
InvoiceOut = out_of(Invoice)


class Verdict(BaseModel):
    approve: bool


async def a_draft(context: Context, invoice_id: int) -> Invoice:
    """The invoice, locked — if it may still be changed. What has gone out to a customer stays
    as it went."""
    invoice = await context.session.get(Invoice, invoice_id, with_for_update=True)
    if invoice.status != InvoiceStatus.DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, f'the invoice is {invoice.status}')
    return invoice


async def add_up(context: Context, invoice: Invoice) -> None:
    lines = await context.session.execute(
        select(InvoiceLine.quantity, InvoiceLine.unit_price, func.coalesce(TaxRate.percent, 0))
        .outerjoin(TaxRate, TaxRate.id == InvoiceLine.tax_rate_id).where(InvoiceLine.invoice_id == invoice.id)
    )
    subtotal = tax = Decimal('0.00')
    for quantity, unit_price, percent in lines:
        subtotal += quantity * unit_price
        tax += (quantity * unit_price * percent / 100).quantize(CENT)
    invoice.subtotal, invoice.tax, invoice.total = subtotal, tax, subtotal + tax


async def a_numbered_invoice(context: Context, invoice: Invoice, old) -> None:
    if old is None:
        last = await context.session.scalar(
            select(func.max(Invoice.number)).where(Invoice.organisation_id == context.org_id)
        )
        invoice.number = (last or 0) + 1
    elif invoice.status != InvoiceStatus.DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, f'the invoice is {invoice.status}')


async def a_line_of_a_draft(context: Context, line: InvoiceLine, old) -> None:
    invoice = await a_draft(context, line.invoice_id)
    context.session.add(line)
    await context.session.flush()
    await add_up(context, invoice)


async def a_line_less(context: Context, line: InvoiceLine) -> None:
    await add_up(context, await a_draft(context, line.invoice_id))


async def a_payment_of_what_is_owed(context: Context, payment: Payment, old) -> None:
    invoice = await context.session.get(Invoice, payment.invoice_id, with_for_update=True)
    if invoice.status != InvoiceStatus.SENT:
        raise HTTPException(status.HTTP_409_CONFLICT, f'the invoice is {invoice.status}')
    if payment.amount > invoice.total - invoice.paid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'more than is owed')
    invoice.paid += payment.amount
    if invoice.paid == invoice.total:
        invoice.status = InvoiceStatus.PAID


async def a_payment_taken_back(context: Context, payment: Payment) -> None:
    invoice = await context.session.get(Invoice, payment.invoice_id, with_for_update=True)
    invoice.paid -= payment.amount
    if invoice.status == InvoiceStatus.PAID:
        invoice.status = InvoiceStatus.SENT



async def a_live_subscription(context: Context, subscription: Subscription, old) -> None:
    if old is not None and subscription.cancelled_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, 'the subscription is cancelled')


async def an_expense_still_pending(context: Context, expense: Expense, old) -> None:
    if old is not None and expense.status != Decision.PENDING:
        raise HTTPException(status.HTTP_409_CONFLICT, 'the expense is decided')



@router.post('/invoices/{row_id}/send', response_model=InvoiceOut)
async def send_invoice(row_id: RowId, context: Admin):
    await find(context, Invoice, row_id)
    invoice = await a_draft(context, row_id)
    lines = await context.session.scalar(
        select(func.count()).select_from(InvoiceLine).where(InvoiceLine.invoice_id == row_id)
    )
    if not lines:
        raise HTTPException(status.HTTP_409_CONFLICT, 'the invoice has no lines')
    invoice.status, invoice.issued_on = InvoiceStatus.SENT, now().date()
    await context.session.commit()
    return invoice


@router.post('/invoices/{row_id}/void', response_model=InvoiceOut)
async def void_invoice(row_id: RowId, context: Admin):
    invoice = await find(context, Invoice, row_id)
    if invoice.status in (InvoiceStatus.PAID, InvoiceStatus.VOID):
        raise HTTPException(status.HTTP_409_CONFLICT, f'the invoice is {invoice.status}')
    if invoice.paid:
        raise HTTPException(status.HTTP_409_CONFLICT, 'the invoice is partly paid')
    invoice.status = InvoiceStatus.VOID
    await context.session.commit()
    return invoice


@router.post('/subscriptions/{row_id}/cancel', response_model=out_of(Subscription))
async def cancel_subscription(row_id: RowId, context: Admin):
    subscription = await find(context, Subscription, row_id)
    if subscription.cancelled_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, 'the subscription is cancelled')
    subscription.cancelled_at, subscription.renews_on = now(), None
    context.session.add(SubscriptionEvent(
        organisation_id=context.org_id, subscription_id=row_id, kind='cancelled', actor_id=context.user.id,
    ))
    await context.session.commit()
    return subscription


@router.post('/expenses/{row_id}/decide', response_model=out_of(Expense))
async def decide_expense(row_id: RowId, data: Verdict, context: Admin):
    expense = await find(context, Expense, row_id)
    if expense.status != Decision.PENDING:
        raise HTTPException(status.HTTP_409_CONFLICT, 'the expense is decided')
    if expense.submitted_by_id == context.user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, 'nobody decides their own expense')
    expense.status = Decision.APPROVED if data.approve else Decision.REJECTED
    expense.decided_by_id = context.user.id
    await context.session.commit()
    return expense


def kept(model, **options) -> None:
    """The usual doors of a table of the books: read by members, changed by admins, on record."""
    resource(router, model, **{'read': MEMBER, 'write': ADMIN, 'audited': True} | options)


kept(TaxRate, methods='list create delete')
kept(Invoice, check=a_numbered_invoice)
kept(InvoiceLine, check=a_line_of_a_draft, gone=a_line_less)
kept(Payment, methods='list read create delete', check=a_payment_of_what_is_owed, gone=a_payment_taken_back)
kept(Subscription, check=a_live_subscription)
kept(Expense, write=MEMBER, author='submitted_by_id', own=True, check=an_expense_still_pending)
