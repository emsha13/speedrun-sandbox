def bearer(token: str) -> dict:
    return {'Authorization': f'Bearer {token}'}


def mailed_code(outbox) -> str:
    """The code in the last letter the application sent."""
    return outbox.call_args.args[2].rsplit(' ', 1)[1]


def mailed_to(outbox) -> str:
    return outbox.call_args.args[0]


async def sign_in(client, email: str, password: str, user_agent: str = 'pytest') -> dict:
    response = await client.post(
        '/auth/login', json={'email': email, 'password': password}, headers={'User-Agent': user_agent}
    )
    assert response.status_code == 200, response.text
    return response.json()
