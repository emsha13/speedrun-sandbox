"""The workspace's doors: an organisation's own, and everything inside one under `/orgs/{org_id}`."""
from app.workspace.routes import (
    billing, calendar, crm, docs, files, helpdesk, integrations, messages, orgs, projects, reports,
)

INSIDE = '/orgs/{org_id}'
# (router, prefix)
routers = [(orgs.router, ''), (orgs.inside, INSIDE)] + [
    (section.router, INSIDE)
    for section in (projects, docs, calendar, helpdesk, crm, billing, messages, integrations, files, reports)
]
