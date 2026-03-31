# Crawler.io — Unified Social Media Data API Platform

## System Design Document

---

# 1. Product Definition

## Core Product

Crawler.io is a **developer-first API platform** that provides unified, normalized, near real-time public data from Instagram, TikTok, and YouTube through a single REST/GraphQL API.

Think of it as **Stripe for social media data** — one integration, all platforms, clean structured data.

## Value Proposition

| Pain Point | Crawler.io Solution |
|---|---|
| Each platform has different APIs, auth, and data formats | Single unified API with normalized schemas |
| Official APIs are limited, slow to approve, and restrictive | Public data available instantly, no platform approval needed |
| Building and maintaining scrapers is expensive | Managed infrastructure with 99.9% uptime |
| Data is stale by the time it reaches analytics tools | Near real-time updates (30s–5min latency) |
| Scaling scraping infra is operationally complex | Auto-scaling, proxy rotation, anti-detection handled |

## Target Customers

| Segment | Use Case | Willingness to Pay |
|---|---|---|
| **Influencer marketing platforms** | Creator discovery, campaign tracking, audience analytics | High ($500–5K/mo) |
| **Brand social listening tools** | Track mentions, engagement, trends | High |
| **Analytics SaaS products** | Competitive analysis, benchmarking | Medium–High |
| **E-commerce platforms** | UGC tracking, creator-driven commerce | Medium |
| **Agencies** | Reporting, ROI measurement | Medium |
| **Researchers / Data scientists** | Trend analysis, academic research | Low–Medium |

## Positioning & Differentiation

1. **Unified schema** — One data model across all platforms (competitors often return raw platform-specific data)
2. **Near real-time** — Sub-5-minute freshness (most competitors offer hourly or daily)
3. **Developer experience** — SDKs, webhooks, playground, excellent docs (like Stripe/Twilio)
4. **Transparent pricing** — Usage-based, no hidden costs
5. **Compliance-first** — Public data only, GDPR-aware, ToS-conscious design

---

# 2. System Architecture

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           CLIENTS                                       │
│  REST API  │  GraphQL  │  Webhooks  │  SDKs (Node, Python, Go)          │
└──────┬─────┴─────┬─────┴─────┬──────┴──────────────────────────────────┘
       │           │           │
┌──────▼───────────▼───────────▼──────────────────────────────────────────┐
│                        API GATEWAY                                       │
│  Kong / AWS API Gateway                                                  │
│  Auth (API Keys + JWT) │ Rate Limiting │ Request Routing │ Analytics     │
└──────┬──────────────────────────────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────────────────────────┐
│                      API SERVICE LAYER                                   │
│                                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                   │
│  │ Creator API   │  │  Post API     │  │ Analytics API │                  │
│  │ Service       │  │  Service      │  │ Service       │                  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                   │
│         │                 │                 │                             │
│  ┌──────▼─────────────────▼─────────────────▼───────┐                   │
│  │              Query & Cache Layer                   │                   │
│  │         Redis (hot) + PostgreSQL (warm)            │                   │
│  └──────────────────────────────────────────────────┘                   │
└─────────────────────────────────────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────────────────────────┐
│                    DATA PROCESSING LAYER                                 │
│                                                                          │
│  ┌────────────────┐    ┌──────────────────┐    ┌─────────────────┐      │
│  │  Normalizer     │    │  Deduplicator     │    │  Enrichment     │     │
│  │  Service        │───▶│  Service          │───▶│  Service        │     │
│  └────────┬───────┘    └──────────────────┘    └────────┬────────┘      │
│           │                                             │                │
│  ┌────────▼─────────────────────────────────────────────▼────────┐      │
│  │                    Apache Kafka / Redpanda                     │      │
│  │  Topics: raw.instagram │ raw.tiktok │ raw.youtube              │      │
│  │          normalized.posts │ normalized.creators                │      │
│  │          events.webhooks │ events.alerts                       │      │
│  └──────────────────────────┬────────────────────────────────────┘      │
└─────────────────────────────┼───────────────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────────────┐
│                    DATA INGESTION LAYER                                  │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────┐       │
│  │                   Job Scheduler (Temporal)                    │       │
│  │  Priority queues │ Retry logic │ Dead letter │ Cron triggers  │       │
│  └──────┬───────────┬───────────┬───────────────────────────────┘       │
│         │           │           │                                        │
│  ┌──────▼──────┐ ┌──▼────────┐ ┌▼────────────┐                         │
│  │ Instagram    │ │ TikTok    │ │ YouTube      │                        │
│  │ Collector    │ │ Collector │ │ Collector    │                         │
│  └──────┬──────┘ └──┬────────┘ └┬─────────────┘                        │
│         │           │           │                                        │
│  ┌──────▼───────────▼───────────▼──────────────┐                        │
│  │            Proxy & Session Manager           │                        │
│  │  IP Rotation │ Browser Pool │ Anti-Detection │                        │
│  └─────────────────────────────────────────────┘                        │
└─────────────────────────────────────────────────────────────────────────┘
```

## Data Flow (Ingestion to Delivery)

```
1. Scheduler triggers collection job (cron or on-demand)
       │
2. Collector picks proxy, creates session, fetches data
       │
3. Raw data → Kafka topic (raw.{platform})
       │
4. Normalizer consumes raw data, maps to unified schema
       │
5. Deduplicator checks for duplicate/unchanged data
       │
6. Enriched data → Kafka topic (normalized.{entity})
       │
7. Storage consumer writes to PostgreSQL + Redis cache
       │
8. Webhook dispatcher sends events to subscribed clients
       │
9. API serves data from Redis (hot) → PostgreSQL (warm) → S3 (cold)
```

## Storage Strategy

| Tier | Technology | Data | TTL |
|------|-----------|------|-----|
| **Hot** | Redis Cluster | Latest 24h of data, frequently queried creators | 24 hours |
| **Warm** | PostgreSQL (with TimescaleDB) | Last 90 days, all active data | 90 days |
| **Cold** | S3 + Parquet (queryable via DuckDB/Athena) | Historical data, analytics | Indefinite |
| **Search** | Elasticsearch | Full-text search on posts, hashtags, bios | 30 days |

---

# 3. Scraping & Data Collection Strategy

## Platform-Specific Approaches

### Instagram

```
Primary:   Instagram Graph API (for consented/business accounts)
Secondary: Instagram web API endpoints (graphql/query)
Fallback:  Browser-based scraping via Playwright

Endpoints targeted:
  - /api/v1/users/{user_id}/info/           → Profile data
  - /api/v1/feed/user/{user_id}/            → Posts
  - /api/v1/media/{media_id}/comments/      → Comments
  - /graphql/query/?query_hash=...          → Explore, hashtags
```

### TikTok

```
Primary:   TikTok Research API (if approved)
Secondary: TikTok web API (https://www.tiktok.com/api/...)
Fallback:  Playwright with stealth plugin

Endpoints targeted:
  - /api/user/detail/                       → Profile
  - /api/post/item_list/                    → User posts
  - /api/challenge/item_list/               → Hashtag posts
  - /api/comment/list/                      → Comments
```

### YouTube

```
Primary:   YouTube Data API v3 (official, generous quotas)
Secondary: YouTube innertube API (internal web API)
Fallback:  yt-dlp for metadata extraction

Endpoints targeted:
  - /youtube/v3/channels                    → Channel data
  - /youtube/v3/search                      → Search
  - /youtube/v3/videos                      → Video metrics
  - /youtubei/v1/browse                     → Innertube browsing
```

## Anti-Detection & Proxy Strategy

### Proxy Architecture

```
┌─────────────────────────────────────────────────┐
│              Proxy Manager Service               │
│                                                   │
│  ┌─────────────┐  ┌──────────────┐               │
│  │ Residential   │  │ Datacenter    │              │
│  │ Pool          │  │ Pool          │              │
│  │ (BrightData)  │  │ (self-hosted) │              │
│  │ 10K+ IPs      │  │ 500 IPs       │              │
│  └──────┬────────┘  └──────┬───────┘              │
│         │                  │                       │
│  ┌──────▼──────────────────▼───────┐              │
│  │        Smart Router              │              │
│  │  - Health scoring per IP         │              │
│  │  - Platform-specific rotation    │              │
│  │  - Geo-targeting                 │              │
│  │  - Cooldown management           │              │
│  │  - Auto-blacklist detection      │              │
│  └─────────────────────────────────┘              │
└─────────────────────────────────────────────────┘
```

### Proxy Rotation Logic (Pseudocode)

```python
class ProxyManager:
    def get_proxy(self, platform: str, priority: str = "normal") -> Proxy:
        # 1. Get healthy proxies for this platform
        candidates = self.pool.get_healthy(platform=platform)

        # 2. Filter out proxies in cooldown
        available = [p for p in candidates if not p.in_cooldown(platform)]

        # 3. Sort by success rate (last 1h)
        available.sort(key=lambda p: p.success_rate_1h, reverse=True)

        # 4. For high-priority jobs, use residential proxies
        if priority == "high":
            available = [p for p in available if p.type == "residential"]

        # 5. Pick with weighted random (favor higher success rate)
        proxy = weighted_random_choice(available)

        # 6. Mark as in-use
        proxy.mark_used(platform)
        return proxy

    def report_result(self, proxy: Proxy, platform: str, success: bool, status_code: int):
        proxy.record_result(success, status_code)

        if status_code in (429, 403):
            proxy.cooldown(platform, duration=random.randint(300, 900))  # 5–15 min

        if status_code == 401:
            proxy.cooldown(platform, duration=3600)  # 1 hour

        if proxy.success_rate_1h < 0.3:
            proxy.quarantine(duration=7200)  # 2 hours
```

### Rate Limit Handling

```python
class RateLimiter:
    """Per-platform adaptive rate limiter"""

    PLATFORM_DEFAULTS = {
        "instagram": {"rpm": 30, "burst": 5, "backoff_base": 60},
        "tiktok":    {"rpm": 60, "burst": 10, "backoff_base": 30},
        "youtube":   {"rpm": 100, "burst": 20, "backoff_base": 15},  # official API
    }

    async def acquire(self, platform: str, proxy_id: str):
        key = f"ratelimit:{platform}:{proxy_id}"

        # Token bucket algorithm
        tokens = await self.redis.get(key)
        if tokens and int(tokens) <= 0:
            wait_time = self.calculate_backoff(platform, proxy_id)
            await asyncio.sleep(wait_time)

        await self.redis.decr(key)

    def calculate_backoff(self, platform: str, proxy_id: str) -> float:
        consecutive_429s = self.get_consecutive_429s(platform, proxy_id)
        base = self.PLATFORM_DEFAULTS[platform]["backoff_base"]
        # Exponential backoff with jitter
        return min(base * (2 ** consecutive_429s) + random.uniform(0, 10), 3600)
```

### Fallback Chain

```
For each collection job:

  1. Try official API (if available and within quota)
     │ fail ──▶
  2. Try web/mobile API endpoints with rotating proxies
     │ fail ──▶
  3. Try headless browser (Playwright) with residential proxy
     │ fail ──▶
  4. Try different geo proxy (US → EU → Asia)
     │ fail ──▶
  5. Queue for retry with exponential backoff
     │ 3 retries failed ──▶
  6. Mark as degraded, alert ops, serve stale data with `stale: true` flag
```

---

# 4. Data Modeling

## Unified Schema

### Creator

```json
{
  "id": "cr_a1b2c3d4e5",
  "platform": "instagram",
  "platform_id": "12345678",
  "username": "johndoe",
  "display_name": "John Doe",
  "bio": "Travel photographer | NYC",
  "profile_image_url": "https://cdn.crawler.io/profiles/cr_a1b2c3d4e5.jpg",
  "is_verified": true,
  "follower_count": 1250000,
  "following_count": 843,
  "post_count": 2341,
  "engagement_rate": 3.42,
  "categories": ["photography", "travel"],
  "external_urls": [
    {"type": "website", "url": "https://johndoe.com"}
  ],
  "metrics_history": [
    {"date": "2026-03-30", "followers": 1249800, "engagement_rate": 3.38},
    {"date": "2026-03-31", "followers": 1250000, "engagement_rate": 3.42}
  ],
  "first_seen_at": "2025-06-15T10:30:00Z",
  "last_updated_at": "2026-03-31T14:22:10Z",
  "data_freshness": "live"
}
```

### Post

```json
{
  "id": "po_x9y8z7w6v5",
  "creator_id": "cr_a1b2c3d4e5",
  "platform": "instagram",
  "platform_post_id": "CxYz123AbC",
  "type": "reel",
  "content": {
    "text": "Sunrise at the Grand Canyon 🌄 #travel #photography",
    "hashtags": ["travel", "photography"],
    "mentions": ["@natgeo"],
    "media": [
      {
        "type": "video",
        "url": "https://cdn.crawler.io/media/po_x9y8z7w6v5/video.mp4",
        "thumbnail_url": "https://cdn.crawler.io/media/po_x9y8z7w6v5/thumb.jpg",
        "duration_seconds": 28,
        "width": 1080,
        "height": 1920
      }
    ]
  },
  "metrics": {
    "like_count": 45230,
    "comment_count": 892,
    "share_count": 1205,
    "view_count": 890000,
    "save_count": 3400,
    "engagement_rate": 5.62
  },
  "published_at": "2026-03-30T08:15:00Z",
  "collected_at": "2026-03-31T14:22:10Z",
  "metrics_updated_at": "2026-03-31T14:22:10Z"
}
```

### Engagement Metrics Snapshot (Time-Series)

```json
{
  "post_id": "po_x9y8z7w6v5",
  "timestamp": "2026-03-31T14:00:00Z",
  "metrics": {
    "like_count": 45230,
    "comment_count": 892,
    "share_count": 1205,
    "view_count": 890000,
    "save_count": 3400
  },
  "deltas": {
    "like_count": 1230,
    "comment_count": 45,
    "share_count": 89,
    "view_count": 52000,
    "save_count": 120
  },
  "interval": "1h"
}
```

## Database Schema (PostgreSQL + TimescaleDB)

```sql
-- Core tables
CREATE TABLE creators (
    id              TEXT PRIMARY KEY,            -- cr_xxxxx
    platform        TEXT NOT NULL,               -- instagram, tiktok, youtube
    platform_id     TEXT NOT NULL,
    username        TEXT NOT NULL,
    display_name    TEXT,
    bio             TEXT,
    profile_image   TEXT,
    is_verified     BOOLEAN DEFAULT FALSE,
    follower_count  BIGINT DEFAULT 0,
    following_count BIGINT DEFAULT 0,
    post_count      BIGINT DEFAULT 0,
    engagement_rate DECIMAL(5,2),
    categories      TEXT[],
    external_urls   JSONB,
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(platform, platform_id)
);

CREATE INDEX idx_creators_platform_username ON creators(platform, username);
CREATE INDEX idx_creators_followers ON creators(follower_count DESC);

CREATE TABLE posts (
    id                TEXT PRIMARY KEY,          -- po_xxxxx
    creator_id        TEXT NOT NULL REFERENCES creators(id),
    platform          TEXT NOT NULL,
    platform_post_id  TEXT NOT NULL,
    post_type         TEXT NOT NULL,             -- image, video, reel, short, story
    text_content      TEXT,
    hashtags          TEXT[],
    mentions          TEXT[],
    media             JSONB,
    like_count        BIGINT DEFAULT 0,
    comment_count     BIGINT DEFAULT 0,
    share_count       BIGINT DEFAULT 0,
    view_count        BIGINT DEFAULT 0,
    save_count        BIGINT DEFAULT 0,
    engagement_rate   DECIMAL(5,2),
    published_at      TIMESTAMPTZ,
    collected_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metrics_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(platform, platform_post_id)
);

CREATE INDEX idx_posts_creator ON posts(creator_id);
CREATE INDEX idx_posts_published ON posts(published_at DESC);
CREATE INDEX idx_posts_hashtags ON posts USING GIN(hashtags);

-- Time-series metrics (TimescaleDB hypertable)
CREATE TABLE metrics_snapshots (
    post_id         TEXT NOT NULL REFERENCES posts(id),
    captured_at     TIMESTAMPTZ NOT NULL,
    like_count      BIGINT,
    comment_count   BIGINT,
    share_count     BIGINT,
    view_count      BIGINT,
    save_count      BIGINT
);

SELECT create_hypertable('metrics_snapshots', 'captured_at');
CREATE INDEX idx_metrics_post ON metrics_snapshots(post_id, captured_at DESC);

-- Collection job tracking
CREATE TABLE collection_jobs (
    id              TEXT PRIMARY KEY,
    platform        TEXT NOT NULL,
    job_type        TEXT NOT NULL,              -- profile, posts, metrics
    target_id       TEXT NOT NULL,              -- creator_id or hashtag
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending, running, completed, failed
    priority        INT DEFAULT 5,
    retry_count     INT DEFAULT 0,
    last_error      TEXT,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

# 5. Tech Stack

| Layer | Technology | Justification |
|-------|-----------|---------------|
| **Backend API** | **Go (Fiber/Echo)** | High throughput, low memory, excellent concurrency. Perfect for I/O-bound API serving. |
| **Scraping Services** | **Python (aiohttp + Playwright)** | Best ecosystem for scraping: Playwright, BeautifulSoup, proxy libs. Async for throughput. |
| **Job Orchestration** | **Temporal** | Durable workflows, built-in retry/timeout, visibility UI. Far better than cron+Redis for this use case. |
| **Message Queue** | **Redpanda** (Kafka-compatible) | Kafka API compatibility, single binary, lower ops overhead. Switch to Kafka at scale. |
| **Primary DB** | **PostgreSQL 16 + TimescaleDB** | Battle-tested OLTP + native time-series for metrics. Rich indexing (GIN for arrays/JSONB). |
| **Cache** | **Redis Cluster** | Sub-ms reads for hot data, pub/sub for real-time events, rate limit counters. |
| **Search** | **Elasticsearch** | Full-text search on posts, bios, hashtags. Aggregations for trend analysis. |
| **Cold Storage** | **S3 + Parquet** | Cost-effective historical storage, queryable via DuckDB or Athena for analytics. |
| **API Gateway** | **Kong** (or AWS API Gateway) | Auth, rate limiting, analytics, request transformation. |
| **Infrastructure** | **AWS (ECS Fargate + RDS)** | Managed services reduce ops burden for small team. ECS over K8s for simplicity. |
| **Monitoring** | **Grafana + Prometheus + Loki** | Full observability stack, self-hosted, cost-effective. |
| **CI/CD** | **GitHub Actions** | Simple, integrated, free for private repos. |

### Why Go + Python (not mono-language)?

```
Go for API layer:       10x lower memory, 5x higher throughput vs Node/Python
Python for scrapers:    Playwright, aiohttp, BeautifulSoup ecosystem is unmatched
Temporal for glue:      Connects both languages via SDK, manages workflow state
```

For MVP, start with Python everywhere, then migrate API layer to Go when you hit scale.

---

# 6. Real-Time System Design

## Hybrid Event-Driven + Polling Architecture

```
┌──────────────────────────────────────────────────────┐
│                 COLLECTION TIERS                      │
│                                                       │
│  Tier 1: HIGH PRIORITY (30s–2min)                    │
│  ├── Tracked creators (customer subscriptions)        │
│  ├── Trending posts (>10K engagement in 1h)          │
│  └── Active campaigns being monitored                 │
│                                                       │
│  Tier 2: MEDIUM PRIORITY (5–15min)                   │
│  ├── Popular creators (>100K followers)              │
│  ├── Tracked hashtags                                 │
│  └── Recently published posts (<24h old)             │
│                                                       │
│  Tier 3: LOW PRIORITY (1h–6h)                        │
│  ├── Long-tail creators                               │
│  ├── Historical metrics updates                       │
│  └── Discovery/exploration crawls                     │
│                                                       │
│  Tier 4: BATCH (daily)                               │
│  ├── Full profile refreshes                           │
│  ├── Cold storage archival                            │
│  └── Analytics aggregation                            │
└──────────────────────────────────────────────────────┘
```

## Adaptive Polling Frequency

```python
def calculate_poll_interval(creator_id: str) -> int:
    """Returns poll interval in seconds"""

    creator = db.get_creator(creator_id)
    subscriptions = db.get_active_subscriptions(creator_id)

    # Base interval by follower tier
    if creator.follower_count > 1_000_000:
        base = 120       # 2 min
    elif creator.follower_count > 100_000:
        base = 300       # 5 min
    elif creator.follower_count > 10_000:
        base = 900       # 15 min
    else:
        base = 3600      # 1 hour

    # Boost for paid subscriptions
    if any(s.tier == "realtime" for s in subscriptions):
        base = min(base, 30)    # 30 seconds for premium
    elif any(s.tier == "pro" for s in subscriptions):
        base = min(base, 120)   # 2 min for pro

    # Boost for recently active creators
    last_post = db.get_latest_post(creator_id)
    if last_post and last_post.published_at > now() - timedelta(hours=1):
        base = base // 2  # Double frequency for active creators

    return base
```

## Webhook Delivery

```python
# When new/updated data is detected:
async def dispatch_webhooks(event: DataEvent):
    subscribers = await db.get_webhook_subscribers(
        event_type=event.type,
        filters=event.entity_filters  # creator_id, platform, hashtag
    )

    for sub in subscribers:
        payload = {
            "event": event.type,           # "post.created", "metrics.updated"
            "timestamp": event.timestamp,
            "data": event.payload,
        }
        signature = hmac.new(sub.secret, json.dumps(payload), hashlib.sha256).hexdigest()

        await queue.enqueue("webhook_delivery", {
            "url": sub.callback_url,
            "payload": payload,
            "headers": {"X-Crawler-Signature": signature},
            "max_retries": 5,
            "retry_backoff": "exponential",
        })
```

## Trade-offs

| Dimension | Choice | Trade-off |
|-----------|--------|-----------|
| Latency vs Cost | Tiered polling | Premium customers get 30s, free tier gets 1h. Cost scales with revenue. |
| Freshness vs Reliability | Serve stale + flag | Always return data, mark `data_freshness: "stale"` if collection failed. |
| Completeness vs Speed | Progressive enrichment | Return basic data fast, enrich (comments, full media) async. |

---

# 7. Scalability & Reliability

## Horizontal Scaling

```
┌─────────────────────────────────────────┐
│          Auto-Scaling Groups             │
│                                          │
│  API Layer:        2–20 instances        │
│    Scale on: request count > 1K/s        │
│                                          │
│  Scraper Workers:  5–100 instances       │
│    Scale on: job queue depth > 1000      │
│                                          │
│  Normalizer:       2–20 instances        │
│    Scale on: Kafka consumer lag > 5000   │
│                                          │
│  Webhook Workers:  2–10 instances        │
│    Scale on: delivery queue depth > 500  │
└─────────────────────────────────────────┘
```

## Fault Tolerance

```python
# Temporal workflow with retry policies
@workflow.defn
class CollectCreatorWorkflow:
    @workflow.run
    async def run(self, creator_id: str, platform: str):
        # Step 1: Fetch profile (retries 3x)
        profile = await workflow.execute_activity(
            fetch_profile,
            args=[creator_id, platform],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=5),
                backoff_coefficient=2.0,
                maximum_attempts=3,
                non_retryable_error_types=["PermanentError"],
            ),
        )

        # Step 2: Fetch recent posts
        posts = await workflow.execute_activity(
            fetch_posts,
            args=[creator_id, platform],
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # Step 3: Normalize and store (idempotent)
        await workflow.execute_activity(
            normalize_and_store,
            args=[profile, posts],
            retry_policy=RetryPolicy(maximum_attempts=5),
        )
```

## Monitoring & Alerting

| Metric | Alert Threshold | Action |
|--------|----------------|--------|
| Scraper success rate (per platform) | < 80% over 5 min | Page on-call, switch to fallback |
| API p99 latency | > 500ms | Scale up API instances |
| Kafka consumer lag | > 10K messages | Scale up consumers |
| Proxy pool health | < 50% healthy | Alert, add proxy capacity |
| Job queue depth | > 5K pending > 10 min | Scale up workers |
| Webhook delivery failures | > 5% over 15 min | Alert, check downstream |
| DB connection pool | > 80% utilized | Alert, check queries |
| Error rate (5xx) | > 1% | Page on-call |

### Key Dashboards

```
1. Platform Health Dashboard
   - Success/failure rates per platform
   - Avg collection latency per platform
   - Proxy health distribution

2. Data Freshness Dashboard
   - % of tracked entities updated in last 5min / 15min / 1h
   - Stale data heatmap by platform

3. API Dashboard
   - Request volume, latency percentiles
   - Error rates by endpoint
   - Top consumers by usage

4. Business Metrics
   - Active API keys
   - API calls by tier
   - Revenue per customer
```

## Handling Platform Schema Changes

```python
# Schema versioning with graceful degradation
class InstagramNormalizer:
    SCHEMA_VERSION = "2026.03.1"

    def normalize_post(self, raw: dict) -> Optional[Post]:
        try:
            return self._normalize_v2(raw)
        except (KeyError, TypeError) as e:
            # Schema might have changed — try legacy paths
            try:
                return self._normalize_v1(raw)
            except Exception:
                # Unknown schema — log raw data for analysis, alert team
                logger.error(f"Schema parse failure", extra={
                    "platform": "instagram",
                    "raw_sample": raw[:1000],
                    "error": str(e),
                })
                metrics.increment("schema_parse_failure", tags={"platform": "instagram"})
                # Store raw data in dead letter for debugging
                await kafka.produce("dead_letter.instagram", raw)
                return None
```

---

# 8. Legal & Compliance

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|-----------|
| Platform ToS violation (scraping) | High | Public data only, respect robots.txt, no login-wall bypass, rate limit compliance |
| CFAA / Computer Fraud claims | Medium | No credential stuffing, no auth bypass, operate from US entity |
| GDPR / Privacy claims | Medium | No PII beyond public profiles, honor deletion requests, DPA ready |
| IP litigation from platforms | Medium-High | Similar to hiQ v LinkedIn: public data has legal precedent, but unsettled |
| API access revocation | Medium | Multi-source fallback, don't depend solely on official APIs |

## Compliance Architecture

```
1. PUBLIC DATA ONLY
   - Never access private accounts
   - Never bypass login gates
   - Never store passwords or session tokens of end users

2. DATA MINIMIZATION
   - Only collect what customers need
   - Auto-delete data after retention period (90 days default)
   - Honor platform-specific data retention rules

3. OPT-OUT MECHANISM
   - Public page: crawler.io/opt-out
   - Any creator can request removal of their data
   - Process within 72 hours (automated)

4. LEGAL ENTITY
   - Register proper business entity
   - Terms of Service that prohibit misuse by customers
   - Customer DPA (Data Processing Agreement) for enterprise

5. ACCESS TRANSPARENCY
   - robots.txt compliance mode available
   - Identify bot with proper User-Agent when using official APIs
   - Don't disguise automated access as human traffic
```

## Safer Alternatives (Build Toward These)

```
Phase 1: Public data scraping (MVP - fast to market)
Phase 2: Official API integrations where available (YouTube Data API, TikTok Research API)
Phase 3: OAuth-based user-consented access (users connect their own accounts)
Phase 4: Platform partnerships (data licensing agreements)
```

---

# 9. MVP Roadmap

## Phase 1: Fast MVP (Weeks 1–6)

**Goal:** Prove the value proposition with one platform and land 5 paying customers.

```
Week 1–2: Foundation
  ├── Set up monorepo, CI/CD, staging environment
  ├── PostgreSQL + Redis on AWS RDS/ElastiCache
  ├── Basic API framework (FastAPI) with auth (API keys)
  └── Proxy manager with BrightData integration

Week 3–4: Instagram Collector
  ├── Profile scraper (username → structured data)
  ├── Posts scraper (last 50 posts with metrics)
  ├── Basic normalizer (raw → unified schema)
  ├── Job scheduler (simple: Celery + Redis)
  └── Store in PostgreSQL

Week 5–6: API + Launch
  ├── REST API: /creators, /posts, /search
  ├── API key management + usage tracking
  ├── Basic rate limiting (tier-based)
  ├── Documentation site (Mintlify or Readme.io)
  └── Landing page + sign-up flow
```

**Deliverables:**
- Instagram creator lookup API
- Instagram posts/metrics API
- Basic search by username
- <500ms API response time
- 99% uptime

## Phase 2: Expansion (Weeks 7–14)

**Goal:** Add TikTok + YouTube, webhooks, and self-serve dashboard.

```
Week 7–9: Multi-Platform
  ├── TikTok collector
  ├── YouTube collector (official API + supplementary)
  └── Unified schema validation across platforms

Week 10–11: Real-Time
  ├── Migrate to Redpanda/Kafka for event streaming
  ├── Webhook system (subscribe to creator/hashtag events)
  ├── Tiered polling (priority-based scheduling)
  └── Replace Celery with Temporal

Week 12–14: Product Polish
  ├── Customer dashboard (usage, API playground)
  ├── SDKs (Node.js, Python)
  ├── Advanced search (hashtag, keyword, date range)
  ├── Billing integration (Stripe usage-based)
  └── SOC 2 preparation started
```

## Phase 3: Scale (Weeks 15–26)

**Goal:** Handle 100M+ data points, enterprise features, profitability.

```
Week 15–18: Scale Infrastructure
  ├── Migrate API to Go for performance
  ├── Elasticsearch for full-text search
  ├── TimescaleDB for metrics history
  ├── S3 cold storage + data retention policies
  └── Auto-scaling on all worker layers

Week 19–22: Enterprise Features
  ├── GraphQL API
  ├── Bulk export endpoints
  ├── Custom collection schedules per customer
  ├── SLA monitoring and reporting
  └── OAuth-based data access (user consent flow)

Week 23–26: Moat Building
  ├── Trend detection & alerts
  ├── AI-powered creator categorization
  ├── Historical data analytics endpoints
  ├── Platform partnership outreach
  └── White-label API option
```

---

# 10. API Design

## Authentication

```
All requests require an API key in the header:
  Authorization: Bearer sk_live_a1b2c3d4e5f6g7h8

API keys are scoped:
  sk_live_*    → Production
  sk_test_*   → Sandbox (returns mock data, no rate limits)
```

## Core Endpoints

### Creators

```http
# Lookup creator by platform username
GET /v1/creators/lookup?platform=instagram&username=johndoe

# Get creator by ID
GET /v1/creators/cr_a1b2c3d4e5

# Search creators
GET /v1/creators/search?q=travel+photographer&platform=instagram&min_followers=10000&max_followers=1000000&verified=true

# Get creator's metrics history
GET /v1/creators/cr_a1b2c3d4e5/metrics?start_date=2026-03-01&end_date=2026-03-31&interval=daily

# Bulk lookup (up to 100)
POST /v1/creators/bulk-lookup
Body: {
  "lookups": [
    {"platform": "instagram", "username": "johndoe"},
    {"platform": "tiktok", "username": "janedoe"}
  ]
}
```

### Posts

```http
# Get posts by creator
GET /v1/creators/cr_a1b2c3d4e5/posts?limit=20&sort=-published_at&type=reel

# Get single post
GET /v1/posts/po_x9y8z7w6v5

# Search posts by hashtag
GET /v1/posts/search?hashtag=travel&platform=instagram&min_likes=1000&published_after=2026-03-01

# Search posts by keyword
GET /v1/posts/search?q=grand+canyon&platform=tiktok,instagram

# Get post metrics history
GET /v1/posts/po_x9y8z7w6v5/metrics?interval=hourly&start_date=2026-03-30
```

### Tracking & Webhooks

```http
# Subscribe to track a creator (enables near real-time updates)
POST /v1/tracking/creators
Body: {
  "platform": "instagram",
  "username": "johndoe",
  "frequency": "realtime"    // realtime (30s), frequent (5min), standard (1h)
}

# List tracked entities
GET /v1/tracking/creators?status=active

# Register a webhook
POST /v1/webhooks
Body: {
  "url": "https://yourapp.com/webhooks/crawler",
  "events": ["post.created", "metrics.updated", "creator.updated"],
  "filters": {
    "creator_ids": ["cr_a1b2c3d4e5"],
    "platforms": ["instagram"]
  },
  "secret": "whsec_your_signing_secret"
}
```

### Trending & Discovery

```http
# Trending hashtags
GET /v1/trends/hashtags?platform=tiktok&country=US&period=24h

# Trending creators (by growth rate)
GET /v1/trends/creators?platform=instagram&metric=follower_growth&period=7d&limit=50
```

## Pagination

All list endpoints return cursor-based pagination:

```json
{
  "data": [...],
  "pagination": {
    "has_more": true,
    "next_cursor": "eyJpZCI6MTIzNH0",
    "total_count": 2341
  }
}
```

## Rate Limiting

```
Response headers on every request:
  X-RateLimit-Limit: 1000
  X-RateLimit-Remaining: 987
  X-RateLimit-Reset: 1711900800

Rate limit tiers:
  Free:       100 requests/day
  Starter:    10K requests/day, 100/min
  Pro:        100K requests/day, 500/min
  Enterprise: Custom
```

## Error Format

```json
{
  "error": {
    "code": "rate_limit_exceeded",
    "message": "You have exceeded your rate limit of 100 requests per minute",
    "status": 429,
    "retry_after": 32
  },
  "request_id": "req_abc123"
}
```

---

# 11. Business Model

## Pricing Tiers

| Tier | Price | Included | Target |
|------|-------|----------|--------|
| **Free** | $0/mo | 100 API calls/day, 5 tracked creators, Instagram only | Developers evaluating |
| **Starter** | $99/mo | 10K calls/day, 50 tracked creators, all platforms, 1h freshness | Small startups |
| **Pro** | $499/mo | 100K calls/day, 500 tracked creators, 5min freshness, webhooks | Growing companies |
| **Enterprise** | Custom | Unlimited, 30s freshness, SLA, dedicated support, bulk export | Large platforms |

### Usage-Based Overages

```
Beyond tier limits:
  API calls:        $0.005 per call
  Tracked creators: $2/creator/month (realtime), $0.50 (standard)
  Webhook events:   $0.001 per event
  Bulk exports:     $0.01 per 1000 records
```

## Go-to-Market Strategy

### Week 1–4: Validate Demand
```
1. Launch on Product Hunt, Hacker News, Twitter/X
2. Post in influencer marketing communities (r/influencermarketing, Slack groups)
3. Cold email 50 influencer marketing platforms (they NEED this data)
4. Offer 3-month free Pro tier to first 10 customers
```

### Ideal First Niche: **Influencer Marketing Tools**

Why:
- Urgent pain point (they're all building scrapers internally)
- High willingness to pay ($500–5K/mo)
- Long-term contracts (sticky once integrated)
- Clear ROI (replaces 1–2 engineers maintaining scrapers)

### Sales Motion
```
Phase 1: Self-serve (Starter/Pro), developer-led adoption
Phase 2: Sales-assisted for Enterprise ($5K+/mo deals)
Phase 3: Platform partnerships & white-label deals
```

### Revenue Projections (Conservative)

```
Month 3:   10 customers ×  $200 avg = $2K  MRR
Month 6:   50 customers ×  $350 avg = $17.5K MRR
Month 12: 200 customers ×  $500 avg = $100K MRR
Month 18: 500 customers × $1000 avg = $500K MRR
```

---

# 12. Risks & Mitigation

## Technical Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Platform changes API/HTML structure | High | High | Schema versioning, dead letter queues, rapid response protocol (<24h fix), monitoring for parse failures |
| Mass IP blocking | Medium | High | Diverse proxy providers (3+), residential + datacenter mix, adaptive rate limiting, geo-distribution |
| Data quality degradation | Medium | Medium | Automated data quality checks (completeness, range validation), customer-reported issue fast-track |
| Kafka/Redpanda downtime | Low | High | Multi-AZ deployment, replication factor 3, fallback to direct DB writes |
| Database performance at scale | Medium | Medium | Read replicas, connection pooling (PgBouncer), query optimization, caching layer |

## Business Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Cease & desist from platforms | Medium | High | Legal counsel on retainer, pivot plan to user-consented model, public data legal precedent (hiQ v LinkedIn) |
| Competitor with official API access | Medium | High | Speed to market, better DX, multi-platform unified schema as moat |
| Low initial demand | Low-Medium | High | Start with niche (influencer marketing), validate before scaling |
| Platform launches competing product | Low | High | Multi-platform differentiation, avoid single-platform dependency |
| Key engineer leaves | Medium | Medium | Document everything, keep architecture simple, no heroics |

## Mitigation Playbook

### If platforms block aggressively:
```
1. Immediate: Switch to residential proxies, reduce frequency
2. Short-term: Implement browser fingerprint rotation
3. Medium-term: Add OAuth user-consented data flow
4. Long-term: Pursue official API partnerships
```

### If legal threat received:
```
1. Consult legal counsel (already on retainer)
2. Assess: C&D vs lawsuit vs API terms update
3. If C&D: Negotiate, demonstrate public data compliance
4. If serious: Pivot affected platform to user-consented model within 30 days
5. Communicate transparently to customers with migration path
```

### If data quality drops:
```
1. Automated alerts fire when quality score drops below threshold
2. On-call engineer investigates within 1 hour
3. Root cause: schema change? → Deploy fix
4. Root cause: blocking? → Rotate proxy pool, adjust frequency
5. Root cause: platform outage? → Serve stale data, notify customers
6. Post-mortem and update monitoring for similar future issues
```

---

# Appendix A: Project Structure

```
crawler.io/
├── services/
│   ├── api/                    # REST/GraphQL API (FastAPI → later Go)
│   │   ├── routes/
│   │   ├── middleware/
│   │   ├── models/
│   │   └── main.py
│   ├── collector/              # Platform-specific scrapers
│   │   ├── instagram/
│   │   ├── tiktok/
│   │   ├── youtube/
│   │   ├── base.py             # Abstract collector interface
│   │   └── proxy_manager.py
│   ├── normalizer/             # Raw → unified schema
│   │   ├── instagram.py
│   │   ├── tiktok.py
│   │   ├── youtube.py
│   │   └── schema.py
│   ├── scheduler/              # Job orchestration (Temporal workflows)
│   │   ├── workflows/
│   │   └── activities/
│   └── webhook/                # Webhook dispatch service
│       ├── dispatcher.py
│       └── retry.py
├── shared/
│   ├── db/                     # Database models & migrations
│   ├── kafka/                  # Kafka producers/consumers
│   ├── cache/                  # Redis wrapper
│   └── config/                 # Env config
├── infra/
│   ├── terraform/              # AWS infrastructure
│   ├── docker/                 # Dockerfiles
│   └── docker-compose.yml      # Local development
├── tests/
├── docs/
├── sdk/                        # Client SDKs
│   ├── python/
│   └── node/
└── scripts/
```

# Appendix B: Key Metrics to Track from Day 1

```
PRODUCT METRICS:
  - API calls per customer per day
  - Data freshness (p50, p95)
  - Time-to-first-API-call (TTFAC) for new signups
  - Webhook delivery success rate

INFRA METRICS:
  - Scraper success rate per platform
  - Proxy pool health (% healthy)
  - Queue depth and consumer lag
  - API latency (p50, p95, p99)
  - Error rates (4xx, 5xx)

BUSINESS METRICS:
  - MRR / ARR
  - Customer count by tier
  - Churn rate (monthly)
  - Cost per API call
  - Infrastructure cost as % of revenue
```
