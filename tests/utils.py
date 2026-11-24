def bearer(token: str) -> dict:
    return {'Authorization': f'Bearer {token}'}


def mailed_code(outbox) -> str:
    """The code in the last letter, or the last text message, the application sent."""
    return outbox.call_args.args[-1].rsplit(' ', 1)[1]


def mailed_to(outbox) -> str:
    return outbox.call_args.args[0]


async def sign_in(client, login: str, password: str, user_agent: str = 'pytest') -> dict:
    """By address or by number: a number starts with a plus."""
    field = 'phone' if login.startswith('+') else 'email'
    response = await client.post(
        '/auth/login', json={field: login, 'password': password}, headers={'User-Agent': user_agent}
    )
    assert response.status_code == 200, response.text
    return response.json()
