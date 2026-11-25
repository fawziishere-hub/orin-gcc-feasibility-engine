import pytest


@pytest.fixture(autouse=True)
def offline_llm(settings):
    """Tests must never depend on (or pay for) a live DeepInfra call."""
    settings.DEEPINFRA_API_KEY = ""
