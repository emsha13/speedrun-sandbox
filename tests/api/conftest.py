import pytest


@pytest.fixture(autouse=True)
def _an_empty_database(clear_db):
    """Every test here goes through the application to the database. The unit tests beside this
    directory touch neither, and pay for neither."""
