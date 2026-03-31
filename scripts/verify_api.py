"""Verify DB data via API."""
import httpx
import asyncio

API_KEY = "sk_test_smoke_test_key_for_local_dev"
BASE = "http://localhost:8000"

async def main():
    async with httpx.AsyncClient() as c:
        headers = {"Authorization": f"Bearer {API_KEY}"}
        
        # Lookup creator
        r = await c.get(f"{BASE}/v1/creators/lookup", params={"platform": "instagram", "username": "virat.kohli"}, headers=headers)
        print(f"Creator lookup: {r.status_code}")
        if r.status_code == 200:
            d = r.json()
            print(f"  ID: {d['id']}")
            print(f"  Name: {d['display_name']}")
            print(f"  Followers: {d['follower_count']:,}")
            print(f"  Post count (profile): {d['post_count']}")
        
        # Get posts via search
        r2 = await c.get(f"{BASE}/v1/posts/search", params={"platform": "instagram", "limit": 5}, headers=headers)
        print(f"\nPosts search: {r2.status_code}")
        if r2.status_code == 200:
            d2 = r2.json()
            items = d2.get("data", [])
            print(f"  Posts returned: {len(items)}")
            if items:
                p = items[0]
                print(f"  First post: {p.get('post_type', '?')} - likes: {p.get('engagement', {}).get('like_count', 0):,}")

        # Count all posts by searching with high limit
        r3 = await c.get(f"{BASE}/v1/posts/search", params={"platform": "instagram", "limit": 100}, headers=headers)
        if r3.status_code == 200:
            d3 = r3.json()
            items3 = d3.get("data", [])
            has_more = d3.get("has_more", False)
            print(f"\n  Posts with limit=100: {len(items3)}, has_more: {has_more}")

asyncio.run(main())
