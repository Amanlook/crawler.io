"""Seed script: creates a test API key and sample data for local development."""

import asyncio
import hashlib
import secrets

from shared.db.database import async_session_factory, engine, Base
from shared.db.models import ApiKey, Creator, Post, generate_id


async def seed():
    # Create tables if they don't exist (for quick local dev without Alembic)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as session:
        # ─── Create test API key ──────────────────────
        raw_key = f"sk_test_{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        api_key = ApiKey(
            key_hash=key_hash,
            key_prefix=raw_key[:12],
            name="Development Key",
            tier="pro",
            owner_email="dev@crawler.io",
            rate_limit_per_minute=500,
            daily_limit=100_000,
        )
        session.add(api_key)

        # ─── Sample Instagram creator ─────────────────
        creator = Creator(
            id=generate_id("cr"),
            platform="instagram",
            platform_id="12345678",
            username="johndoe",
            display_name="John Doe",
            bio="Travel photographer | NYC 📸",
            is_verified=True,
            follower_count=1_250_000,
            following_count=843,
            post_count=2341,
            engagement_rate=3.42,
            categories=["photography", "travel"],
            external_urls=[{"type": "website", "url": "https://johndoe.com"}],
        )
        session.add(creator)
        await session.flush()

        # ─── Sample posts ─────────────────────────────
        for i in range(5):
            post = Post(
                id=generate_id("po"),
                creator_id=creator.id,
                platform="instagram",
                platform_post_id=f"CxYz{i:03d}AbC",
                post_type="reel" if i % 2 == 0 else "image",
                text_content=f"Sample post #{i+1} #travel #photography",
                hashtags=["travel", "photography"],
                mentions=[],
                media=[{
                    "type": "video" if i % 2 == 0 else "image",
                    "url": f"https://example.com/media/{i}.mp4",
                    "thumbnail_url": f"https://example.com/media/{i}_thumb.jpg",
                }],
                like_count=10000 + i * 5000,
                comment_count=200 + i * 100,
                share_count=50 + i * 25,
                view_count=100000 + i * 50000 if i % 2 == 0 else 0,
            )
            session.add(post)

        await session.commit()

        print("=" * 60)
        print("🌱 Database seeded successfully!")
        print("=" * 60)
        print(f"\n  API Key (save this):  {raw_key}")
        print(f"  Key prefix:           {raw_key[:12]}...")
        print(f"  Tier:                 pro")
        print(f"  Creator:              @johndoe (Instagram)")
        print(f"  Sample posts:         5")
        print(f"\n  Test with:")
        print(f'  curl -H "Authorization: Bearer {raw_key}" http://localhost:8000/v1/creators/lookup?platform=instagram&username=johndoe')
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(seed())
