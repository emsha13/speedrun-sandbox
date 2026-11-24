"""Customers and what is being sold to them."""
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.models import now
from app.workspace.access import Context, Member
from app.workspace.crud import INT4, RowId, find, out_of, resource
from app.workspace.models.crm import (
    Activity, Company, Contact, Deal, DealStageChange, Lead, LeadStatus, Pipeline, Product, Stage, StageKind,
)
from app.workspace.models.orgs import MemberRole

router = APIRouter(tags=['crm'])
ADMIN = MemberRole.ADMIN


class Move(BaseModel):
    stage_id: int = Field(ge=1, le=INT4)


async def a_deal_at_a_stage(context: Context, deal: Deal, old) -> None:
    if old is None:
        stage = await context.session.get(Stage, deal.stage_id)
        deal.closed_at = None if stage.kind == StageKind.OPEN else now()


async def a_lead_not_yet_converted(context: Context, lead: Lead, old) -> None:
    if old is not None and old.get('status', lead.status) == LeadStatus.CONVERTED:
        raise HTTPException(status.HTTP_409_CONFLICT, 'the lead is converted')
    # Converted is what `convert` makes a lead, with the contact that goes with it.
    if lead.status == LeadStatus.CONVERTED:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'a lead is converted by converting it')



@router.post('/deals/{row_id}/move', response_model=out_of(Deal))
async def move_deal(row_id: RowId, data: Move, context: Member):
    session = context.session
    deal = await find(context, Deal, row_id)
    here = await session.get(Stage, deal.stage_id)
    there = await session.get(Stage, data.stage_id)
    if there is None or there.organisation_id != context.org_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'no such stage')
    if there.pipeline_id != here.pipeline_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'the stage is of another pipeline')
    if there.id == here.id:
        raise HTTPException(status.HTTP_409_CONFLICT, 'the deal is at that stage')
    session.add(DealStageChange(
        organisation_id=context.org_id, deal_id=deal.id, from_stage_id=here.id, to_stage_id=there.id,
        changed_by_id=context.user.id,
    ))
    deal.stage_id = there.id
    # Won and lost are where a deal ends; moved back among the open stages, it is open again.
    deal.closed_at = None if there.kind == StageKind.OPEN else now()
    await session.commit()
    return deal


@router.post('/leads/{row_id}/convert', response_model=out_of(Contact), status_code=status.HTTP_201_CREATED)
async def convert_lead(row_id: RowId, context: Member):
    """A lead becomes a contact — in the company it named, made now if nobody had it yet."""
    session = context.session
    lead = await find(context, Lead, row_id)
    if lead.status == LeadStatus.CONVERTED:
        raise HTTPException(status.HTTP_409_CONFLICT, 'the lead is converted')
    company = None
    if lead.company_name:
        company = await session.scalar(
            select(Company).where(Company.organisation_id == context.org_id, Company.name == lead.company_name)
            .order_by(Company.id).limit(1)
        )
        if company is None:
            company = Company(organisation_id=context.org_id, name=lead.company_name, owner_id=lead.owner_id)
            session.add(company)
            await session.flush()
    contact = Contact(
        organisation_id=context.org_id, company_id=company.id if company else None, first_name=lead.first_name,
        last_name=lead.last_name, email=lead.email, owner_id=lead.owner_id,
    )
    session.add(contact)
    await session.flush()
    lead.status, lead.contact_id = LeadStatus.CONVERTED, contact.id
    await session.commit()
    return contact


resource(router, Company, search=('name', 'domain'))
resource(router, Contact, search=('first_name', 'last_name', 'email'))
resource(router, Pipeline, methods='list create delete', write=ADMIN)
resource(router, Stage, methods='list create delete', write=ADMIN)
resource(router, Deal, search=('title',), check=a_deal_at_a_stage)
resource(router, Lead, search=('first_name', 'last_name', 'email', 'company_name'), check=a_lead_not_yet_converted)
resource(router, Activity, author='author_id', own=True, search=('subject',))
resource(router, Product, write=ADMIN, search=('name', 'sku'))
