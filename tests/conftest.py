"""Shared test fixtures and configuration."""

import asyncio
import hashlib
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shared.db.database import Base
from shared.db.models import ApiKey


# ─── Test database (in-memory SQLite won't work with PostgreSQL features,
#     so we use a test database or mock the session) ───────

TEST_API_KEY_RAW = "sk_test_thisisatestkeyforseedingdata123456"
TEST_API_KEY_HASH = hashlib.sha256(TEST_API_KEY_RAW.encode()).hexdigest()


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_db_session():
    """Return a mock async session for unit tests."""
    session = AsyncMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    return session


@pytest.fixture
def test_api_key():
    """Return a test ApiKey object."""
    return ApiKey(
        id="key_test123",
        key_hash=TEST_API_KEY_HASH,
        key_prefix="sk_test_this",
        name="Test Key",
        tier="pro",
        owner_email="test@crawler.io",
        is_active=True,
        rate_limit_per_minute=500,
        daily_limit=100_000,
    )


@pytest.fixture
def auth_headers():
    """Return authorization headers for test requests."""
    return {"Authorization": f"Bearer {TEST_API_KEY_RAW}"}
