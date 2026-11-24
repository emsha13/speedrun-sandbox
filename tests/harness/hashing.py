"""What a password hash costs the suite.

bcrypt is slow on purpose: at the cost the application hashes with, a hash is a quarter of a
second. A test makes a user or two and signs in, so it pays that two or three times over.
"""
import functools

import bcrypt

from tests.harness import options


def set_the_cost() -> None:
    """Called before `app` is imported: a module of it hashes at import."""
    if options.hash == 'cheap':
        # At the lowest cost bcrypt takes a hash is as real — salted, checked by the same
        # `checkpw`, which reads the cost out of the hash. What the cost buys is time against a
        # guesser, and no test measures that. The application's own code is untouched.
        gensalt = bcrypt.gensalt
        bcrypt.gensalt = lambda rounds=4, prefix=b'2b': gensalt(rounds, prefix)


def hash_for_a_fixture(password: str) -> str:
    """The hash a fixture stores for a user it creates."""
    from app.security import hash_password

    if options.hash == 'cached':
        # The half-measure: the fixtures' users nearly all have one password, so its hash is
        # computed once a run. Every sign-in still checks a password at full cost, and so does
        # every hash the application itself makes.
        return _hashed_once(password)
    return hash_password(password)


@functools.cache
def _hashed_once(password: str) -> str:
    from app.security import hash_password

    return hash_password(password)
