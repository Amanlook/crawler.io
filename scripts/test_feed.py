"""Quick test of Instagram feed endpoints."""
import httpx
import asyncio

async def test():
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "X-IG-App-ID": "936619743392459",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://www.instagram.com/virat.kohli/",
        "Accept": "*/*",
    }

    async with httpx.AsyncClient(follow_redirects=True, timeout=10) as c:
        # Warmup
        r = await c.get("https://www.instagram.com/", headers={"User-Agent": headers["User-Agent"]})
        print(f"Cookies: {list(c.cookies.keys())}")
        await asyncio.sleep(2)

        # Test 1: Feed by username
        r1 = await c.get(
            "https://www.instagram.com/api/v1/feed/user/virat.kohli/username/",
            params={"count": 12},
            headers=headers,
        )
        print(f"1. Feed by username: {r1.status_code}")
        if r1.status_code == 200:
            d = r1.json()
            print(f"   Items: {len(d.get('items', []))}, next_max_id: {d.get('next_max_id', 'none')}")

        await asyncio.sleep(1)

        # Test 2: Feed by user ID
        r2 = await c.get(
            "https://www.instagram.com/api/v1/feed/user/2094200507/",
            params={"count": 12},
            headers=headers,
        )
        print(f"2. Feed by ID: {r2.status_code}")
        if r2.status_code == 200:
            d = r2.json()
            print(f"   Items: {len(d.get('items', []))}, next_max_id: {d.get('next_max_id', 'none')}")

        await asyncio.sleep(1)

        # Test 3: GraphQL POST with doc_ids
        csrf = c.cookies.get("csrftoken") or ""
        import json
        for doc_id in ["8845758582119845", "17991233890457762", "7950326061702512", "17880160963012870"]:
            variables = json.dumps({"id": "2094200507", "first": 12, "after": ""})
            r3 = await c.post(
                "https://www.instagram.com/graphql/query/",
                data={"doc_id": doc_id, "variables": variables},
                headers={**headers, "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": csrf},
            )
            status = r3.status_code
            keys = ""
            if status == 200:
                try:
                    d = r3.json()
                    data_root = d.get("data") or {}
                    keys = list(data_root.keys())[:5]
                except Exception:
                    keys = "parse error"
            print(f"3. GraphQL doc_id={doc_id}: {status} keys={keys}")
            await asyncio.sleep(1)

asyncio.run(test())
