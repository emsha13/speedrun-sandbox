"""Invoices add up their lines, go out once and are paid up to what they ask; expenses are
decided by somebody else."""
import pytest

from decimal import Decimal

from app.workspace.models.billing import Expense, Invoice, InvoiceStatus, Subscription, TaxRate
from app.workspace.models.crm import Company


@pytest.fixture
async def invoice(client, as_, at, new):
    company = await new(Company)
    response = await client.post(at('/invoices'), json={'company_id': company.id}, headers=await as_('admin'))
    return response.json()


async def line(client, as_, at, invoice, quantity, price, tax_rate=None):
    body = {'invoice_id': invoice['id'], 'description': 'Work', 'quantity': quantity, 'unit_price': price}
    if tax_rate is not None:
        body['tax_rate_id'] = tax_rate.id
    return await client.post(at('/invoice-lines'), json=body, headers=await as_('admin'))


async def read(client, as_, at, invoice):
    return (await client.get(at(f'/invoices/{invoice["id"]}'), headers=await as_('member'))).json()


def sums(invoice) -> tuple:
    return invoice['subtotal'], invoice['tax'], invoice['total']


async def test_invoices_are_numbered(client, as_, at, invoice, new):
    company = await new(Company)
    second = await client.post(at('/invoices'), json={'company_id': company.id}, headers=await as_('admin'))

    assert (invoice['number'], second.json()['number']) == (1, 2)
    assert (invoice['status'], sums(invoice)) == ('draft', ('0.00', '0.00', '0.00'))


async def test_an_invoice_adds_up(client, as_, at, invoice, new):
    vat = await new(TaxRate, percent=Decimal('19.00'))
    await line(client, as_, at, invoice, 3, '10.00', vat)
    await line(client, as_, at, invoice, 1, '0.99')

    assert sums(await read(client, as_, at, invoice)) == ('30.99', '5.70', '36.69')


async def test_tax_is_rounded_by_the_line(client, as_, at, invoice, new):
    vat = await new(TaxRate, percent=Decimal('19.00'))
    for _ in range(3):
        await line(client, as_, at, invoice, 1, '0.05', vat)

    assert sums(await read(client, as_, at, invoice)) == ('0.15', '0.03', '0.18')


async def test_an_invoice_adds_up_again_without_a_line(client, as_, at, invoice):
    first = (await line(client, as_, at, invoice, 2, '5.00')).json()
    await line(client, as_, at, invoice, 1, '1.00')
    await client.delete(at(f'/invoice-lines/{first["id"]}'), headers=await as_('admin'))

    assert sums(await read(client, as_, at, invoice)) == ('1.00', '0.00', '1.00')


async def test_an_invoice_adds_up_again_with_a_line_changed(client, as_, at, invoice):
    made = (await line(client, as_, at, invoice, 2, '5.00')).json()
    await client.patch(at(f'/invoice-lines/{made["id"]}'), json={'quantity': 3}, headers=await as_('admin'))

    assert sums(await read(client, as_, at, invoice)) == ('15.00', '0.00', '15.00')


async def test_the_sums_are_not_set_by_hand(client, as_, at, invoice):
    for field in ('subtotal', 'total', 'paid', 'status', 'number'):
        response = await client.patch(at(f'/invoices/{invoice["id"]}'), json={field: 1}, headers=await as_('admin'))
        assert response.status_code == 422, field


async def send(client, as_, at, invoice, by='admin'):
    return await client.post(at(f'/invoices/{invoice["id"]}/send'), headers=await as_(by))


@pytest.fixture
async def sent(client, as_, at, invoice):
    """An invoice of 100.00, gone out."""
    await line(client, as_, at, invoice, 4, '25.00')
    await send(client, as_, at, invoice)
    return invoice


@pytest.mark.freeze_time('2026-04-30 23:30:00')
async def test_send(client, as_, at, invoice):
    await line(client, as_, at, invoice, 1, '1.00')
    response = await send(client, as_, at, invoice)

    assert (response.json()['status'], response.json()['issued_on']) == ('sent', '2026-04-30')


async def test_an_empty_invoice_does_not_go_out(client, as_, at, invoice):
    response = await send(client, as_, at, invoice)

    assert (response.status_code, response.json()) == (409, {'detail': 'the invoice has no lines'})


async def test_an_invoice_goes_out_once(client, as_, at, sent):
    response = await send(client, as_, at, sent)

    assert (response.status_code, response.json()) == (409, {'detail': 'the invoice is sent'})


@pytest.mark.parametrize('role', ['member', 'guest'])
async def test_invoices_go_out_by_admins(client, as_, at, invoice, role):
    await line(client, as_, at, invoice, 1, '1.00')

    assert (await send(client, as_, at, invoice, by=role)).status_code == 403


async def test_what_has_gone_out_stays(client, as_, at, sent):
    changed = await client.patch(at(f'/invoices/{sent["id"]}'), json={'notes': 'x'}, headers=await as_('admin'))
    added = await line(client, as_, at, sent, 1, '1.00')

    assert (changed.status_code, added.status_code) == (409, 409)


async def pay(client, as_, at, invoice, amount):
    return await client.post(at('/payments'), json={
        'invoice_id': invoice['id'], 'amount': amount, 'method': 'transfer', 'received_on': '2026-05-02',
    }, headers=await as_('admin'))


async def test_paid_in_part(client, as_, at, sent):
    response = await pay(client, as_, at, sent, '40.00')

    assert response.status_code == 201
    now = await read(client, as_, at, sent)
    assert (now['paid'], now['status']) == ('40.00', 'sent')


async def test_paid_in_full(client, as_, at, sent):
    await pay(client, as_, at, sent, '40.00')
    await pay(client, as_, at, sent, '60.00')

    now = await read(client, as_, at, sent)
    assert (now['paid'], now['status']) == ('100.00', 'paid')


@pytest.mark.parametrize('first, second', [('100.01', None), ('60.00', '40.01')])
async def test_paid_more_than_is_owed(client, as_, at, sent, first, second):
    response = await pay(client, as_, at, sent, first)
    if second:
        response = await pay(client, as_, at, sent, second)

    assert (response.status_code, response.json()) == (400, {'detail': 'more than is owed'})


async def test_a_draft_is_not_paid(client, as_, at, invoice):
    assert (await pay(client, as_, at, invoice, '1.00')).status_code == 409


async def test_a_paid_invoice_is_not_paid_again(client, as_, at, sent):
    await pay(client, as_, at, sent, '100.00')

    assert (await pay(client, as_, at, sent, '1.00')).json() == {'detail': 'the invoice is paid'}


@pytest.mark.parametrize('amount', ['0', '-5.00', '0.001'])
async def test_a_payment_of_nothing(client, as_, at, sent, amount):
    assert (await pay(client, as_, at, sent, amount)).status_code == 422


async def test_a_payment_taken_back(client, as_, at, sent):
    payment = (await pay(client, as_, at, sent, '100.00')).json()
    response = await client.delete(at(f'/payments/{payment["id"]}'), headers=await as_('admin'))

    assert response.status_code == 204
    now = await read(client, as_, at, sent)
    assert (now['paid'], now['status']) == ('0.00', 'sent')


async def void(client, as_, at, invoice):
    return await client.post(at(f'/invoices/{invoice["id"]}/void'), headers=await as_('admin'))


@pytest.mark.parametrize('sent_first', [False, True])
async def test_void(client, as_, at, invoice, sent_first):
    if sent_first:
        await line(client, as_, at, invoice, 1, '1.00')
        await send(client, as_, at, invoice)

    assert (await void(client, as_, at, invoice)).json()['status'] == 'void'


async def test_what_is_partly_paid_is_not_void(client, as_, at, sent):
    await pay(client, as_, at, sent, '1.00')

    assert (await void(client, as_, at, sent)).json() == {'detail': 'the invoice is partly paid'}


@pytest.mark.parametrize('status', [InvoiceStatus.PAID, InvoiceStatus.VOID])
async def test_what_is_settled_is_not_void(client, as_, at, new, status):
    invoice = await new(Invoice, status=status)
    response = await void(client, as_, at, {'id': invoice.id})

    assert (response.status_code, response.json()) == (409, {'detail': f'the invoice is {status}'})


async def test_money_is_read_by_members_and_not_by_guests(client, as_, at, invoice):
    assert (await client.get(at('/invoices'), headers=await as_('member'))).status_code == 200
    assert (await client.get(at('/invoices'), headers=await as_('guest'))).status_code == 403


async def cancel(client, as_, at, subscription):
    return await client.post(at(f'/subscriptions/{subscription.id}/cancel'), headers=await as_('admin'))


async def test_a_subscription_cancelled(client, as_, at, new):
    subscription = await new(Subscription)
    response = await cancel(client, as_, at, subscription)

    assert response.json()['cancelled_at'] is not None
    assert response.json()['renews_on'] is None


async def test_a_subscription_cancelled_once(client, as_, at, new):
    subscription = await new(Subscription)
    await cancel(client, as_, at, subscription)

    assert (await cancel(client, as_, at, subscription)).status_code == 409


async def test_a_cancelled_subscription_is_kept_as_it_is(client, as_, at, new):
    subscription = await new(Subscription)
    await cancel(client, as_, at, subscription)
    response = await client.patch(at(f'/subscriptions/{subscription.id}'), json={'quantity': 2},
                                  headers=await as_('admin'))

    assert response.status_code == 409


async def decide(client, as_, at, expense, approve, by='admin'):
    return await client.post(at(f'/expenses/{expense.id}/decide'), json={'approve': approve},
                             headers=await as_(by))


@pytest.fixture
async def expense(new, people):
    return await new(Expense, submitted_by_id=people['member'].id)


@pytest.mark.parametrize('approve, status', [(True, 'approved'), (False, 'rejected')])
async def test_an_expense_decided(client, as_, at, expense, people, approve, status):
    response = await decide(client, as_, at, expense, approve)

    assert (response.json()['status'], response.json()['decided_by_id']) == (status, people['admin'].id)


async def test_an_expense_decided_once(client, as_, at, expense):
    await decide(client, as_, at, expense, True)

    assert (await decide(client, as_, at, expense, False)).status_code == 409


async def test_nobody_decides_their_own_expense(client, as_, at, new, people):
    own = await new(Expense, submitted_by_id=people['admin'].id)

    assert (await decide(client, as_, at, own, True)).status_code == 403


async def test_a_member_decides_no_expense(client, as_, at, expense):
    assert (await decide(client, as_, at, expense, True, by='peer')).status_code == 403


async def test_a_decided_expense_is_kept_as_it_is(client, as_, at, expense):
    await decide(client, as_, at, expense, True)
    response = await client.patch(at(f'/expenses/{expense.id}'), json={'vendor': 'X'}, headers=await as_('member'))

    assert (response.status_code, response.json()) == (409, {'detail': 'the expense is decided'})


async def test_an_expense_is_submitted_by_a_member(client, as_, at, people):
    body = {'amount': '12.50', 'spent_on': '2026-05-01'}
    response = await client.post(at('/expenses'), json=body, headers=await as_('member'))

    assert response.status_code == 201
    assert (response.json()['submitted_by_id'], response.json()['status']) == (people['member'].id, 'pending')
