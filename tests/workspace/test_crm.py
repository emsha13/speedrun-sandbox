"""Deals move through the stages of their pipeline; leads become contacts."""
import pytest

from sqlalchemy import select

from app.workspace.models.crm import Company, Contact, Deal, DealStageChange, Lead, Pipeline, Stage, StageKind


@pytest.fixture
async def stages(new):
    """A pipeline of three stages — talking, won, lost — and the deal now at the first."""
    pipeline = await new(Pipeline)
    return {
        kind: await new(Stage, pipeline_id=pipeline.id, kind=kind, name=kind.value, position=position)
        for position, kind in enumerate(StageKind)
    }


@pytest.fixture
async def deal(new, stages):
    return await new(Deal, stage_id=stages[StageKind.OPEN].id)


async def move(client, as_, at, deal, stage, by='member'):
    return await client.post(at(f'/deals/{deal.id}/move'), json={'stage_id': stage.id}, headers=await as_(by))


async def test_a_deal_won(client, as_, at, deal, stages):
    response = await move(client, as_, at, deal, stages[StageKind.WON])

    assert response.status_code == 200
    assert response.json()['stage_id'] == stages[StageKind.WON].id
    assert response.json()['closed_at'] is not None


async def test_a_deal_lost_and_taken_up_again(client, as_, at, deal, stages):
    await move(client, as_, at, deal, stages[StageKind.LOST])
    response = await move(client, as_, at, deal, stages[StageKind.OPEN])

    assert response.json()['closed_at'] is None


async def test_every_move_is_recorded(client, as_, at, deal, stages, people, db_session):
    await move(client, as_, at, deal, stages[StageKind.WON])
    await move(client, as_, at, deal, stages[StageKind.OPEN], by='peer')

    changes = (await db_session.scalars(select(DealStageChange).order_by(DealStageChange.id))).all()
    assert [(c.from_stage_id, c.to_stage_id, c.changed_by_id) for c in changes] == [
        (stages[StageKind.OPEN].id, stages[StageKind.WON].id, people['member'].id),
        (stages[StageKind.WON].id, stages[StageKind.OPEN].id, people['peer'].id),
    ]


async def test_a_deal_stays_where_it_is(client, as_, at, deal, stages):
    response = await move(client, as_, at, deal, stages[StageKind.OPEN])

    assert (response.status_code, response.json()) == (409, {'detail': 'the deal is at that stage'})


async def test_a_deal_keeps_to_its_pipeline(client, as_, at, deal, new):
    elsewhere = await new(Stage)
    response = await move(client, as_, at, deal, elsewhere)

    assert (response.status_code, response.json()) == (400, {'detail': 'the stage is of another pipeline'})


async def test_a_deal_moves_to_no_stage_of_another_organisation(client, as_, at, deal, new, other_org):
    theirs = await new(Stage, by='outsider', organisation=other_org)

    assert (await move(client, as_, at, deal, theirs)).status_code == 400


async def test_a_deal_moves_to_no_stage_that_is_not(client, as_, at, deal):
    response = await client.post(at(f'/deals/{deal.id}/move'), json={'stage_id': 999999}, headers=await as_('member'))

    assert (response.status_code, response.json()) == (400, {'detail': 'no such stage'})


async def test_a_guest_moves_no_deal(client, as_, at, deal, stages):
    assert (await move(client, as_, at, deal, stages[StageKind.WON], by='guest')).status_code == 403


async def test_the_stage_is_not_set_by_hand(client, as_, at, deal, stages):
    response = await client.patch(at(f'/deals/{deal.id}'), json={'stage_id': stages[StageKind.WON].id},
                                  headers=await as_('member'))

    assert response.status_code == 422


@pytest.mark.parametrize('kind, closed', [(StageKind.OPEN, False), (StageKind.WON, True), (StageKind.LOST, True)])
async def test_a_deal_made_at_a_stage(client, as_, at, stages, kind, closed):
    response = await client.post(at('/deals'), json={'title': 'Big one', 'stage_id': stages[kind].id},
                                 headers=await as_('member'))

    assert (response.json()['closed_at'] is not None) == closed


@pytest.mark.parametrize('amount', ['-1', '12345678901.00', '1.001', 'lots'])
async def test_a_deal_of_a_malformed_amount(client, as_, at, stages, amount):
    body = {'title': 'Big one', 'stage_id': stages[StageKind.OPEN].id, 'amount': amount}

    assert (await client.post(at('/deals'), json=body, headers=await as_('member'))).status_code == 422


async def test_deals_by_stage(client, as_, at, deal, stages, new):
    won = await new(Deal, stage_id=stages[StageKind.WON].id)
    page = (await client.get(at('/deals'), params={'stage_id': stages[StageKind.WON].id},
                             headers=await as_('guest'))).json()

    assert [row['id'] for row in page['items']] == [won.id]


async def convert(client, as_, at, lead, by='member'):
    return await client.post(at(f'/leads/{lead.id}/convert'), headers=await as_(by))


async def test_a_lead_converted(client, as_, at, new, people, db_session):
    lead = await new(Lead, first_name='Ada', last_name='King', email='ada@example.com', company_name='Analytical',
                     owner_id=people['peer'].id)
    response = await convert(client, as_, at, lead)

    assert response.status_code == 201
    contact = response.json()
    assert (contact['first_name'], contact['last_name'], contact['email'], contact['owner_id']) == (
        'Ada', 'King', 'ada@example.com', people['peer'].id,
    )
    company = await db_session.get(Company, contact['company_id'])
    assert (company.name, company.owner_id) == ('Analytical', people['peer'].id)
    await db_session.refresh(lead)
    assert (lead.status, lead.contact_id) == ('converted', contact['id'])


async def test_a_lead_joins_the_company_that_is_there(client, as_, at, new, db_session):
    company = await new(Company, name='Analytical')
    lead = await new(Lead, company_name='Analytical')

    assert (await convert(client, as_, at, lead)).json()['company_id'] == company.id
    assert len((await db_session.scalars(select(Company))).all()) == 1


async def test_a_lead_does_not_join_a_company_of_another_organisation(client, as_, at, new, other_org):
    theirs = await new(Company, by='outsider', organisation=other_org, name='Analytical')
    lead = await new(Lead, company_name='Analytical')

    assert (await convert(client, as_, at, lead)).json()['company_id'] != theirs.id


async def test_a_lead_of_no_company(client, as_, at, new, db_session):
    lead = await new(Lead)

    assert (await convert(client, as_, at, lead)).json()['company_id'] is None
    assert (await db_session.scalars(select(Company))).all() == []


async def test_a_lead_converted_once(client, as_, at, new, db_session):
    lead = await new(Lead)
    await convert(client, as_, at, lead)
    response = await convert(client, as_, at, lead)

    assert (response.status_code, response.json()) == (409, {'detail': 'the lead is converted'})
    assert len((await db_session.scalars(select(Contact))).all()) == 1


async def test_a_converted_lead_is_kept_as_it_is(client, as_, at, new):
    lead = await new(Lead)
    await convert(client, as_, at, lead)
    response = await client.patch(at(f'/leads/{lead.id}'), json={'first_name': 'X'}, headers=await as_('member'))

    assert response.status_code == 409


@pytest.mark.parametrize('method, path', [('POST', '/leads'), ('PATCH', '/leads/{id}')])
async def test_a_lead_is_not_converted_by_hand(client, as_, at, new, method, path):
    lead = await new(Lead)
    body = {'first_name': 'Ada', 'last_name': 'King', 'status': 'converted'}
    response = await client.request(method, at(path.format(id=lead.id)), json=body, headers=await as_('member'))

    assert (response.status_code, response.json()) == (400, {'detail': 'a lead is converted by converting it'})


@pytest.mark.parametrize('status', ['qualified', 'lost', 'new'])
async def test_a_lead_moves_on_by_hand(client, as_, at, new, status):
    lead = await new(Lead)
    response = await client.patch(at(f'/leads/{lead.id}'), json={'status': status}, headers=await as_('member'))

    assert response.json()['status'] == status


async def test_a_guest_converts_no_lead(client, as_, at, new):
    assert (await convert(client, as_, at, await new(Lead), by='guest')).status_code == 403


async def test_contacts_searched_by_name_or_address(client, as_, at, new):
    ada = await new(Contact, first_name='Ada', last_name='King', email='countess@example.com')
    await new(Contact, first_name='Charles', last_name='Babbage', email='engine@example.com')

    for term in ('ada', 'KING', 'countess'):
        page = (await client.get(at('/contacts'), params={'search': term}, headers=await as_('guest'))).json()
        assert [row['id'] for row in page['items']] == [ada.id], term


@pytest.mark.parametrize('email', ['ada', 'ada@', '@example.com', 'ada example@x.com'])
async def test_a_contact_of_a_malformed_address(client, as_, at, email):
    body = {'first_name': 'Ada', 'last_name': 'King', 'email': email}

    assert (await client.post(at('/contacts'), json=body, headers=await as_('member'))).status_code == 422
