import pytest
from src.config.settings import settings


@pytest.fixture(autouse=True)
def force_mock_data(monkeypatch):
    """
    Force all agents to use mock data during tests by clearing the API key.
    This makes tests deterministic, fast, and network-free.
    """
    monkeypatch.setattr(settings, "RAPIDAPI_KEY", "")
    yield