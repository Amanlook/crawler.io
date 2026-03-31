"""Verify Swagger docs and OpenAPI schema."""
import httpx
import asyncio

async def test():
    base = "http://localhost:8003"
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{base}/docs")
        print(f"Docs page: {r.status_code}")

        r2 = await c.get(f"{base}/openapi.json")
        print(f"OpenAPI schema: {r2.status_code}")
        if r2.status_code == 200:
            schema = r2.json()
            print(f"Title: {schema['info']['title']}")
            sec = list(schema.get("components", {}).get("securitySchemes", {}).keys())
            print(f"Security schemes: {sec}")
            print(f"Global security: {schema.get('security', [])}")
            tags = [t["name"] for t in schema.get("tags", [])]
            print(f"Tags: {tags}")
            paths = list(schema.get("paths", {}).keys())
            print(f"Endpoints ({len(paths)}): {paths}")

        h = {"Authorization": "Bearer sk_test_smoke_test_key_for_local_dev"}
        r3 = await c.get(f"{base}/v1/creators/cr_qnvo4urvptsa1cn4/posts", params={"limit": 1}, headers=h)
        print(f"\nPosts API: {r3.status_code}")
        if r3.status_code == 200:
            d = r3.json()
            print(f"Total count: {d['pagination']['total_count']}")

asyncio.run(test())
