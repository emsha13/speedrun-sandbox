"""An organisation with somebody of every role in it, and another organisation beside it."""
import pytest

from app import services
from app.models import User
from app.workspace.models.orgs import MemberRole, Membership, Organisation, OrgSettings, Plan
from tests.harness.hashing import hash_for_a_fixture
from tests.utils import bearer
from tests.workspace.factory import make

# Who is in the organisation, and as what. `peer` is a second plain member: somebody whose rows
# are not one's own and who is no admin either.
ROLES = {
    'owner': MemberRole.OWNER, 'admin': MemberRole.ADMIN, 'member': MemberRole.MEMBER, 'peer': MemberRole.MEMBER,
    'guest': MemberRole.GUEST,
}
# The least of the people who may do what needs the role.
WHO = {MemberRole.GUEST: 'guest', MemberRole.MEMBER: 'member', MemberRole.ADMIN: 'admin', MemberRole.OWNER: 'owner'}


@pytest.fixture(autouse=True)
def _an_empty_database(clear_db):
    pass


@pytest.fixture
async def people(db_session, password):
    """Everybody in the organisation, and `outsider`, who owns the other one. Each is made the way
    a user is, with a hash of their own — six hashes a test, as such fixtures usually have it."""
    users = {
        name: User(
            email=f'{name}@example.com', password_hash=hash_for_a_fixture(password), first_name=name.title(),
            last_name='Lee', is_active=True,
        )
        for name in (*ROLES, 'outsider')
    }
    db_session.add_all(users.values())
    await db_session.commit()
    return users


async def founded(session, name: str, slug: str, members: dict) -> Organisation:
    # On the plan with seats to spare: the free one is full with the five people here.
    organisation = Organisation(name=name, slug=slug, plan=Plan.TEAM)
    session.add(organisation)
    await session.flush()
    session.add(OrgSettings(organisation_id=organisation.id))
    session.add_all(
        Membership(organisation_id=organisation.id, user_id=user.id, role=role) for user, role in members.items()
    )
    await session.commit()
    return organisation


@pytest.fixture
async def org(db_session, people):
    return await founded(db_session, 'Acme', 'acme', {people[name]: role for name, role in ROLES.items()})


@pytest.fixture
async def other_org(db_session, people):
    return await founded(db_session, 'Globex', 'globex', {people['outsider']: MemberRole.OWNER})


@pytest.fixture
def as_(db_session, people):
    """`await as_('member')`: the headers of somebody signed in. The session is opened straight in
    the database — the door to sign in by has tests of its own."""
    signed = {}

    async def headers(name: str) -> dict:
        if name not in signed:
            tokens = await services.open_session(db_session, people[name], 'pytest')
            signed[name] = bearer(tokens.access_token)
        return signed[name]
    return headers


@pytest.fixture
def at(org):
    """`at('/tasks')`: the path inside the organisation."""
    return lambda path: f'/orgs/{org.id}{path}'


@pytest.fixture
def new(db_session, org, people):
    """`await new(Task, title='…')`: a row in the organisation, straight in the database, with
    whatever it needs made too. Every user it names is `by`."""
    async def _new(model, by='member', organisation=None, **given):
        return await make(db_session, model, (organisation or org).id, people[by].id, **given)
    return _new
