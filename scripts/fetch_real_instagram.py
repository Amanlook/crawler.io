"""Fetch REAL public Instagram data and store it in the database.

Uses Instagram's public web endpoints with browser-like headers.

Usage:
  python3 scripts/fetch_real_instagram.py <username> [count|all]

For more than ~120 posts, you need an Instagram session cookie:
  1. Open instagram.com in Chrome, log in
  2. Open DevTools (F12) → Application → Cookies → instagram.com
  3. Copy the 'sessionid' value
  4. Export it: export IG_SESSION_ID='your_session_id_here'
  5. Run the script again
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone

import httpx

from shared.db.database import async_session_factory
from shared.db.models import Creator, Post, generate_id
from sqlalchemy import select

# Optional: set IG_SESSION_ID env var for authenticated requests (gets more posts)
IG_SESSION_ID = os.environ.get("IG_SESSION_ID", "")


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}

API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "X-IG-App-ID": "936619743392459",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.instagram.com/",
    "Origin": "https://www.instagram.com",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}


async def fetch_instagram_profile(client: httpx.AsyncClient, username: str) -> dict | None:
    """Try multiple strategies to get Instagram profile data."""

    cookies = {"sessionid": IG_SESSION_ID} if IG_SESSION_ID else None

    # Strategy 1: Web Profile Info API
    print(f"[1/3] Trying web profile API for @{username}...")
    try:
        resp = await client.get(
            "https://www.instagram.com/api/v1/users/web_profile_info/",
            params={"username": username},
            headers=API_HEADERS,
            cookies=cookies,
        )
        if resp.status_code == 200:
            data = resp.json()
            user = data.get("data", {}).get("user")
            if user:
                print(f"  ✓ Got profile via web API (pk={user.get('pk', user.get('id', '?'))})")
                return user
        print(f"  ✗ Status {resp.status_code}")
    except Exception as e:
        print(f"  ✗ {e}")

    # Strategy 2: ?__a=1&__d=dis
    print(f"[2/3] Trying public JSON endpoint for @{username}...")
    try:
        resp = await client.get(
            f"https://www.instagram.com/{username}/",
            params={"__a": "1", "__d": "dis"},
            headers=API_HEADERS,
            cookies=cookies,
        )
        if resp.status_code == 200:
            data = resp.json()
            user = data.get("graphql", {}).get("user") or data.get("user")
            if user:
                print(f"  ✓ Got profile via JSON endpoint")
                return user
        print(f"  ✗ Status {resp.status_code}")
    except Exception as e:
        print(f"  ✗ {e}")

    # Strategy 3: Scrape HTML for embedded JSON
    print(f"[3/3] Trying HTML scrape for @{username}...")
    try:
        resp = await client.get(
            f"https://www.instagram.com/{username}/",
            headers=HEADERS,
            cookies=cookies,
        )
        if resp.status_code == 200:
            # Look for JSON in script tags
            patterns = [
                r'window\._sharedData\s*=\s*({.*?});',
                r'window\.__additionalDataLoaded\([^,]+,\s*({.*?})\);',
                r'"ProfilePage":\[{"graphql":(.*?)}\]',
            ]
            for pattern in patterns:
                match = re.search(pattern, resp.text, re.DOTALL)
                if match:
                    try:
                        blob = json.loads(match.group(1))
                        user = (
                            blob.get("entry_data", {})
                            .get("ProfilePage", [{}])[0]
                            .get("graphql", {})
                            .get("user")
                        ) or blob.get("user")
                        if user:
                            print(f"  ✓ Got profile via HTML scrape")
                            return user
                    except (json.JSONDecodeError, IndexError):
                        continue
        print(f"  ✗ Status {resp.status_code}")
    except Exception as e:
        print(f"  ✗ {e}")

    return None


async def fetch_more_posts(client: httpx.AsyncClient, user_id: str, username: str, end_cursor: str | None, count: int = 50, cursor_type: str = "auto") -> tuple[list[dict], str | None, str]:
    """Fetch additional posts using multiple strategies. Returns (posts, next_cursor, cursor_type_used)."""
    import json as _json

    cookies = {"sessionid": IG_SESSION_ID} if IG_SESSION_ID else None
    csrf = client.cookies.get("csrftoken", domain="www.instagram.com") or client.cookies.get("csrftoken")
    extra_headers = {}
    if csrf:
        extra_headers["X-CSRFToken"] = csrf

    # Strategy 1: Feed API by username (works without auth, most reliable)
    if cursor_type in ("feed", "auto"):
        try:
            feed_headers = {
                **API_HEADERS,
                **extra_headers,
                "X-IG-App-ID": "936619743392459",
            }
            feed_url = f"https://www.instagram.com/api/v1/feed/user/{username}/username/"
            params = {"count": min(count, 33)}
            if end_cursor and cursor_type == "feed":
                params["max_id"] = end_cursor

            resp = await client.get(feed_url, params=params, headers=feed_headers, cookies=cookies)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", [])
                if items:
                    posts = [_convert_feed_item(item) for item in items]
                    next_max_id = data.get("next_max_id")
                    print(f"   ✓ Feed API (username) returned {len(posts)} posts")
                    return posts, next_max_id, "feed"
            if resp.status_code != 200:
                print(f"   ✗ Feed API (username) returned {resp.status_code}")
        except Exception as e:
            print(f"   ✗ Feed API (username) error: {e}")

    # Strategy 2: Feed API by user ID (needs session or fresh IP)
    if cursor_type in ("feed_id", "auto"):
        try:
            feed_headers = {
                **API_HEADERS,
                **extra_headers,
                "X-IG-App-ID": "936619743392459",
            }
            feed_url = f"https://www.instagram.com/api/v1/feed/user/{user_id}/"
            params = {"count": min(count, 33)}
            if end_cursor and cursor_type == "feed_id":
                params["max_id"] = end_cursor

            resp = await client.get(feed_url, params=params, headers=feed_headers, cookies=cookies)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", [])
                if items:
                    posts = [_convert_feed_item(item) for item in items]
                    next_max_id = data.get("next_max_id")
                    print(f"   ✓ Feed API (ID) returned {len(posts)} posts")
                    return posts, next_max_id, "feed_id"
            if resp.status_code != 200:
                print(f"   ✗ Feed API (ID) returned {resp.status_code}")
        except Exception as e:
            print(f"   ✗ Feed API (ID) error: {e}")

    return [], None, cursor_type


def _convert_feed_item(item: dict) -> dict:
    """Convert a feed API item to match the profile/GraphQL node format."""
    caption = item.get("caption")
    caption_text = caption.get("text", "") if isinstance(caption, dict) else (caption or "")

    node = {
        "shortcode": item.get("code", ""),
        "taken_at_timestamp": item.get("taken_at"),
        "is_video": item.get("media_type") == 2 or item.get("video_duration"),
        "product_type": item.get("product_type", ""),
        "video_url": item.get("video_url", ""),
        "display_url": (
            item.get("image_versions2", {}).get("candidates", [{}])[0].get("url", "")
            if item.get("image_versions2")
            else item.get("display_url", "")
        ),
        "thumbnail_src": item.get("thumbnail_url", ""),
        "video_view_count": item.get("view_count", 0) or item.get("play_count", 0),
        "edge_media_to_caption": {"edges": [{"node": {"text": caption_text}}]},
        "edge_liked_by": {"count": item.get("like_count", 0)},
        "edge_media_to_comment": {"count": item.get("comment_count", 0)},
    }
    if item.get("carousel_media"):
        node["edge_sidecar_to_children"] = True
    return node


def extract_posts_from_profile(user_data: dict) -> tuple[list[dict], str | None]:
    """Extract post nodes and pagination cursor from profile data."""
    media = user_data.get("edge_owner_to_timeline_media", {})
    edges = media.get("edges", []) or user_data.get("media", {}).get("nodes", [])
    posts = [edge.get("node", edge) for edge in edges]

    page_info = media.get("page_info", {})
    end_cursor = page_info.get("end_cursor") if page_info.get("has_next_page") else None

    return posts, end_cursor


def parse_creator(username: str, d: dict) -> dict:
    """Parse raw Instagram data into creator fields."""
    follower_count = (
        d.get("edge_followed_by", {}).get("count")
        or d.get("follower_count")
        or 0
    )
    following_count = (
        d.get("edge_follow", {}).get("count")
        or d.get("following_count")
        or 0
    )
    post_count = (
        d.get("edge_owner_to_timeline_media", {}).get("count")
        or d.get("media_count")
        or 0
    )
    bio = d.get("biography", d.get("bio", ""))
    external_url = d.get("external_url")
    external_urls = [{"type": "website", "url": external_url}] if external_url else []

    return {
        "platform_id": str(d.get("pk", d.get("id", ""))),
        "username": d.get("username", username),
        "display_name": d.get("full_name", ""),
        "bio": bio,
        "profile_image_url": d.get("profile_pic_url_hd", d.get("profile_pic_url")),
        "is_verified": d.get("is_verified", False),
        "follower_count": follower_count,
        "following_count": following_count,
        "post_count": post_count,
        "categories": [d.get("category_name")] if d.get("category_name") else [],
        "external_urls": external_urls,
    }


def parse_post(node: dict, creator_id: str) -> dict:
    """Parse a raw Instagram post node into post fields."""
    # Determine type
    if node.get("is_video") or node.get("product_type") == "clips":
        post_type = "reel" if node.get("product_type") == "clips" else "video"
    elif node.get("edge_sidecar_to_children") or node.get("media_type") == 8:
        post_type = "carousel"
    else:
        post_type = "image"

    # Caption
    caption = ""
    caption_edges = node.get("edge_media_to_caption", {}).get("edges", [])
    if caption_edges:
        caption = caption_edges[0].get("node", {}).get("text", "")
    if not caption:
        caption = node.get("caption", {}).get("text", "") if isinstance(node.get("caption"), dict) else (node.get("caption") or "")

    # Extract hashtags from caption
    hashtags = re.findall(r"#(\w+)", caption) if caption else []

    # Engagement
    like_count = (
        node.get("edge_liked_by", {}).get("count")
        or node.get("edge_media_preview_like", {}).get("count")
        or node.get("like_count", 0)
    )
    comment_count = (
        node.get("edge_media_to_comment", {}).get("count")
        or node.get("comment_count", 0)
    )
    view_count = node.get("video_view_count", 0) or node.get("view_count", 0)

    # Timestamp
    ts = node.get("taken_at_timestamp") or node.get("taken_at")
    published_at = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None

    # Media
    media_url = node.get("video_url") or node.get("display_url") or node.get("thumbnail_src", "")
    thumb = node.get("thumbnail_src") or node.get("display_url", "")

    return {
        "platform_post_id": node.get("shortcode", node.get("code", "")),
        "post_type": post_type,
        "text_content": caption,
        "hashtags": hashtags,
        "media": [{"type": post_type, "url": media_url, "thumbnail_url": thumb}] if media_url else [],
        "like_count": like_count,
        "comment_count": comment_count,
        "share_count": 0,
        "view_count": view_count,
        "published_at": published_at,
    }


async def store_real_data(username: str, creator_fields: dict, post_nodes: list[dict]):
    """Store the fetched data in the database, upserting (not deleting existing posts)."""

    async with async_session_factory() as session:
        # Check if creator exists — update or insert
        result = await session.execute(
            select(Creator).where(
                Creator.platform == "instagram",
                Creator.username == username,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing creator with real data
            for key, value in creator_fields.items():
                setattr(existing, key, value)
            creator_id = existing.id
            print(f"  Updated existing creator {creator_id}")

            # Get existing post IDs to avoid duplicates
            existing_posts_result = await session.execute(
                select(Post.platform_post_id).where(Post.creator_id == creator_id)
            )
            existing_post_ids = {row[0] for row in existing_posts_result.all()}
            print(f"  Existing posts in DB: {len(existing_post_ids)}")
        else:
            creator_id = generate_id("cr")
            creator = Creator(id=creator_id, platform="instagram", **creator_fields)
            session.add(creator)
            existing_post_ids = set()
            print(f"  Created new creator {creator_id}")

        # Insert new posts (skip existing ones)
        seen_post_ids = set()
        inserted = 0
        skipped = 0
        for node in post_nodes:
            fields = parse_post(node, creator_id)
            pid = fields["platform_post_id"]
            if not pid or pid in seen_post_ids or pid in existing_post_ids:
                skipped += 1
                continue
            seen_post_ids.add(pid)
            post = Post(
                id=generate_id("po"),
                creator_id=creator_id,
                platform="instagram",
                mentions=[],
                save_count=0,
                **fields,
            )
            session.add(post)
            inserted += 1

        await session.commit()
        total = len(existing_post_ids) + inserted
        print(f"  Inserted {inserted} new posts (skipped {skipped} dupes, total in DB: {total})")
        return creator_id


async def main():
    username = sys.argv[1] if len(sys.argv) > 1 else "virat.kohli"
    max_posts_arg = sys.argv[2] if len(sys.argv) > 2 else "all"
    fetch_all = max_posts_arg.lower() == "all"
    max_posts = 999_999 if fetch_all else int(max_posts_arg)

    print(f"\n{'='*60}")
    print(f"  Fetching REAL Instagram data for @{username}")
    print(f"  Target: {'ALL posts' if fetch_all else f'{max_posts} posts'}")
    if IG_SESSION_ID:
        print(f"  Auth: ✓ Using session cookie")
    else:
        print(f"  Auth: ✗ No session cookie")
    print(f"{'='*60}\n")

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        # Warmup: visit homepage to seed cookies (csrftoken, mid, ig_did, etc.)
        print("🔧 Warming up session (visiting instagram.com)...")
        try:
            warmup = await client.get("https://www.instagram.com/", headers=HEADERS)
            csrf = warmup.cookies.get("csrftoken", "")
            if csrf:
                print(f"   ✓ Got CSRF token and session cookies")
            else:
                print(f"   ⚠ No CSRF token but continuing...")
            await asyncio.sleep(1)
        except Exception as e:
            print(f"   ⚠ Warmup failed: {e}")

        user_data = await fetch_instagram_profile(client, username)

        if not user_data:
            print("\n❌ Could not fetch data from Instagram.")
            print("   Instagram blocks most automated requests without login cookies.")
            print("   Options:")
            print("   1. Set IG_SESSION_ID env var (from browser cookies)")
            print("   2. Configure BrightData proxy in .env")
            sys.exit(1)

        # Parse creator
        creator_fields = parse_creator(username, user_data)
        user_id = creator_fields["platform_id"]
        total_on_profile = creator_fields["post_count"]
        print(f"\n📊 Creator: {creator_fields['display_name']} (@{creator_fields['username']})")
        print(f"   Followers: {creator_fields['follower_count']:,}")
        print(f"   Total posts on profile: {total_on_profile:,}")
        print(f"   Bio: {creator_fields['bio'][:80]}...")

        # Get initial posts from profile (first 12)
        post_nodes, end_cursor = extract_posts_from_profile(user_data)
        print(f"\n📝 Got {len(post_nodes)} posts from profile page")

        # Paginate for ALL remaining posts using the SAME client (shares cookies)
        page = 1
        consecutive_failures = 0
        backoff_delay = 2.0  # Base delay between pages
        # First pagination call uses feed API without cursor (gets its own cursor type)
        cursor_type = "auto"
        while len(post_nodes) < max_posts:
            page += 1
            remaining = max_posts - len(post_nodes)
            batch = min(remaining, 33)
            pct = (len(post_nodes) / total_on_profile * 100) if total_on_profile else 0
            print(f"   Page {page} | {len(post_nodes)}/{total_on_profile} ({pct:.0f}%) | fetching {batch} more...")

            # Progressive delay: gets slower as we go deeper to avoid rate limits
            page_delay = backoff_delay + (page // 5) * 0.5
            await asyncio.sleep(page_delay)

            more_posts, end_cursor, cursor_type = await fetch_more_posts(client, user_id, username, end_cursor, batch, cursor_type)
            if not more_posts:
                consecutive_failures += 1
                if consecutive_failures >= 8:
                    print(f"   ⚠️  {consecutive_failures} consecutive failures — stopping")
                    if not IG_SESSION_ID:
                        print(f"\n   💡 TIP: For more posts, set IG_SESSION_ID environment variable.")
                        print(f"      1. Open instagram.com in Chrome → DevTools → Application → Cookies")
                        print(f"      2. Copy 'sessionid' value")
                        print(f"      3. export IG_SESSION_ID='your_session_id'")
                    break
                # Exponential backoff: 10s, 20s, 40s, 60s, 60s, 60s, 60s, 60s
                retry_delay = min(10 * (2 ** (consecutive_failures - 1)), 60)
                print(f"   ⏳ Rate limited — waiting {retry_delay}s before retry {consecutive_failures}/8...")
                await asyncio.sleep(retry_delay)
                # On 3rd failure, try refreshing the session cookies
                if consecutive_failures == 3:
                    print(f"   🔄 Refreshing session cookies...")
                    try:
                        await client.get("https://www.instagram.com/", headers=HEADERS)
                        await asyncio.sleep(2)
                    except Exception:
                        pass
                continue

            consecutive_failures = 0
            post_nodes.extend(more_posts)

            if not end_cursor:
                print(f"   No more pages available")
                break

    post_nodes = post_nodes[:max_posts]
    print(f"\n📝 Collected {len(post_nodes)} posts total")

    if post_nodes:
        for i, node in enumerate(post_nodes[:5]):
            fields = parse_post(node, "")
            print(f"   [{i+1}] {fields['post_type']} — ❤️ {fields['like_count']:,} — {fields['text_content'][:60]}...")
        if len(post_nodes) > 5:
            # Show last post too
            last = parse_post(post_nodes[-1], "")
            print(f"   ... {len(post_nodes) - 6} more ...")
            print(f"   [{len(post_nodes)}] {last['post_type']} — ❤️ {last['like_count']:,} — {last['text_content'][:60]}...")

    # Store in DB
    print(f"\n💾 Storing in database...")
    creator_id = await store_real_data(username, creator_fields, post_nodes)

    print(f"\n{'='*60}")
    print(f"  ✅ Done! Creator ID: {creator_id}")
    print(f"  Posts fetched: {len(post_nodes)} / {total_on_profile}")
    print(f"  API: GET /v1/creators/lookup?platform=instagram&username={username}")
    print(f"  Posts: GET /v1/creators/{creator_id}/posts?limit=100")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
