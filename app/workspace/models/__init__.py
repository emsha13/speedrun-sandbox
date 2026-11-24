"""Every table of the workspace. Importing this is what puts them into `Base.metadata`."""
from app.workspace.models import (                                                              # noqa: F401
    billing, calendar, crm, docs, files, helpdesk, integrations, messages, orgs, projects, reports, tasks,
)
