"""Quick test: can we fetch @ring from Instagram inline?"""
import asyncio
import httpx

BROWSER = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
API = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "X-IG-App-ID": "936619743392459",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.instagram.com/",
    "Origin": "https://www.instagram.com",
}


async def main():
    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as c:
        # warmup
        w = await c.get("https://www.instagram.com/", headers=BROWSER)
        print(f"Warmup: {w.status_code}, cookies: {list(c.cookies.keys())}")
        await asyncio.sleep(1)

        # Strategy 1: web_profile_info
        print("\n--- Strategy 1: web_profile_info ---")
        r = await c.get(
            "https://www.instagram.com/api/v1/users/web_profile_info/",
            params={"username": "ring"},
            headers=API,
        )
        print(f"Status: {r.status_code}")
        if r.status_code == 200:
            d = r.json()
            user = d.get("data", {}).get("user")
            if user:
                pk = user.get("pk", user.get("id", "?"))
                name = user.get("full_name", "?")
                fc = user.get("edge_followed_by", {})
                followers = fc.get("count", 0) if isinstance(fc, dict) else user.get("follower_count", 0)
                print(f"  Found: {name} (pk={pk}, followers={followers})")
            else:
                print(f"  No user data in response. Keys: {list(d.keys())}")
        else:
            print(f"  Response: {r.text[:300]}")

        # Strategy 2: __a=1
        print("\n--- Strategy 2: __a=1&__d=dis ---")
        r2 = await c.get(
            "https://www.instagram.com/ring/",
            params={"__a": "1", "__d": "dis"},
            headers=API,
        )
        print(f"Status: {r2.status_code}")
        if r2.status_code == 200:
            try:
                d2 = r2.json()
                user2 = d2.get("graphql", {}).get("user") or d2.get("user")
                if user2:
                    print(f"  Found: {user2.get('full_name', '?')}")
                else:
                    print(f"  No user. Keys: {list(d2.keys())}")
            except Exception as e:
                print(f"  JSON parse error: {e}")
                print(f"  Body: {r2.text[:200]}")
        else:
            print(f"  Response: {r2.text[:300]}")


asyncio.run(main())
