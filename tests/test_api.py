"""Tests for API endpoints."""

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from tests.conftest import TEST_API_KEY_RAW, TEST_API_KEY_HASH


@pytest.fixture
def mock_api_key():
    """Create a mock API key object."""
    key = MagicMock()
    key.id = "key_test123"
    key.key_hash = TEST_API_KEY_HASH
    key.key_prefix = "sk_test_this"
    key.name = "Test Key"
    key.tier = "pro"
    key.owner_email = "test@crawler.io"
    key.is_active = True
    key.rate_limit_per_minute = 500
    key.daily_limit = 100_000
    key.last_used_at = None
    return key


@pytest.fixture
def client(mock_api_key):
    """Create a test client with mocked dependencies."""
    from services.api.main import app
    from services.api.dependencies import rate_limit, get_db
    from shared.db.models import ApiKey

    # Override auth to return our mock key
    async def mock_rate_limit():
        return mock_api_key

    async def mock_get_db():
        session = AsyncMock()
        # db.execute() returns a sync result proxy in SQLAlchemy
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=mock_result)
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        yield session

    app.dependency_overrides[rate_limit] = mock_rate_limit
    app.dependency_overrides[get_db] = mock_get_db

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


class TestHealthEndpoints:
    def test_health(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_root(self, client):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Crawler.io API"
        assert "version" in data


class TestCreatorEndpoints:
    def test_lookup_creator_not_found_queues_collection(self, client):
        headers = {"Authorization": f"Bearer {TEST_API_KEY_RAW}"}

        with patch("services.api.routes.creators.cache") as mock_cache, \
             patch("services.api.routes.creators.collect_creator") as mock_collect, \
             patch("services.api.routes.creators.collect_posts") as mock_posts:

            mock_cache.get = AsyncMock(return_value=None)

            response = client.get(
                "/v1/creators/lookup?platform=instagram&username=newuser",
                headers=headers,
            )
            # 202 means collection was triggered
            assert response.status_code == 202

    def test_lookup_creator_invalid_platform(self, client):
        headers = {"Authorization": f"Bearer {TEST_API_KEY_RAW}"}
        response = client.get(
            "/v1/creators/lookup?platform=facebook&username=test",
            headers=headers,
        )
        assert response.status_code == 422  # Validation error


class TestPostEndpoints:
    def test_search_posts(self, client):
        headers = {"Authorization": f"Bearer {TEST_API_KEY_RAW}"}
        response = client.get("/v1/posts/search?q=test", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert "pagination" in data


class TestWebhookEndpoints:
    def test_create_webhook_invalid_events(self, client):
        headers = {"Authorization": f"Bearer {TEST_API_KEY_RAW}"}
        response = client.post(
            "/v1/webhooks",
            headers=headers,
            json={
                "url": "https://example.com/webhook",
                "events": ["invalid_event"],
                "secret": "a_very_secure_secret_key",
            },
        )
        assert response.status_code == 400
