import pytest


@pytest.fixture(scope="session")
def spark():
    """One local Spark session for the whole test run (starting Spark takes seconds)."""
    from pricecatcher.spark import get_spark

    session = get_spark("pricecatcher-tests")
    yield session
    session.stop()
