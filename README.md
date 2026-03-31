# Crawler.io

**Unified Social Media Data API** — One integration, all platforms.

Crawler.io provides normalized, near real-time public data from Instagram, TikTok, and YouTube through a single REST API.

## Quick Start

### Prerequisites
- Python 3.11+
- Docker & Docker Compose
- Make

### Setup

```bash
# Clone and setup
cd crawler.io
make setup
source .venv/bin/activate

# Start infrastructure (PostgreSQL + Redis)
docker compose up -d postgres redis

# Run database migrations
make migrate

# Seed with test data (creates API key + sample data)
python scripts/seed.py

# Start the API server
make api
```

The API is now running at `http://localhost:8000`
- Docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

### Start Collection Workers

```bash
# In a separate terminal
make worker

# In another terminal (periodic scheduler)
make beat
```

### Full Docker Setup

```bash
# Start everything: API + worker + beat + postgres + redis
docker compose up -d --build
```

## API Usage

```bash
# Set your API key (from seed output)
export API_KEY="sk_test_..."

# Look up a creator
curl -H "Authorization: Bearer $API_KEY" \
  "http://localhost:8000/v1/creators/lookup?platform=instagram&username=johndoe"

# Search creators
curl -H "Authorization: Bearer $API_KEY" \
  "http://localhost:8000/v1/creators/search?platform=instagram&min_followers=10000"

# Get creator's posts
curl -H "Authorization: Bearer $API_KEY" \
  "http://localhost:8000/v1/creators/{creator_id}/posts?limit=10"

# Search posts by hashtag
curl -H "Authorization: Bearer $API_KEY" \
  "http://localhost:8000/v1/posts/search?hashtag=travel&platform=instagram"

# Track a creator for real-time updates
curl -X POST -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"platform":"instagram","username":"johndoe","frequency":"frequent"}' \
  "http://localhost:8000/v1/tracking/creators"

# Register a webhook
curl -X POST -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://yourapp.com/webhook","events":["post.created"],"secret":"your-webhook-secret!!"}' \
  "http://localhost:8000/v1/webhooks"
```

## Project Structure

```
crawler.io/
├── services/
│   ├── api/                # FastAPI REST API
│   │   ├── main.py         # App entry point
│   │   ├── schemas.py      # Pydantic request/response models
│   │   ├── dependencies.py # Auth, rate limiting, DB sessions
│   │   └── routes/         # Endpoint handlers
│   ├── collector/          # Platform data collectors
│   │   ├── base.py         # Abstract collector + error types
│   │   ├── proxy_manager.py # Proxy rotation & health tracking
│   │   ├── instagram/      # Instagram-specific collector
│   │   ├── tiktok/         # TikTok-specific collector
│   │   └── youtube/        # YouTube-specific collector
│   ├── normalizer/         # Raw → unified schema mapping
│   │   ├── base.py         # Abstract normalizer + shared types
│   │   ├── instagram.py    # Instagram data normalization
│   │   ├── tiktok.py       # TikTok data normalization
│   │   ├── youtube.py      # YouTube data normalization
│   │   └── registry.py     # Platform → normalizer mapping
│   └── scheduler/          # Job orchestration
│       ├── celery_app.py   # Celery configuration
│       └── tasks.py        # Collection & processing tasks
├── shared/
│   ├── config/             # App settings & logging
│   ├── db/                 # SQLAlchemy models & database
│   └── cache/              # Redis cache wrapper
├── tests/                  # Test suite
├── alembic/                # Database migrations
├── infra/docker/           # Dockerfiles
├── scripts/                # Utility scripts
├── docs/                   # System design & API spec
└── docker-compose.yml      # Local dev environment
```

## Development

```bash
# Run tests
make test

# Lint & format
make lint
make format

# Create a new migration
make migrate-create MSG="add new table"
```

## Architecture

See [docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md) for the full system design document.

```
Client → API Gateway → FastAPI → PostgreSQL / Redis
                                      ↑
              Celery Workers → Collectors → Proxy Manager
                   ↑                            ↓
              Celery Beat          Instagram / TikTok / YouTube
              (periodic)              ↓
                              Normalizer → DB + Cache
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| API | FastAPI (Python) |
| Database | PostgreSQL 16 |
| Cache | Redis 7 |
| Task Queue | Celery + Redis |
| Scraping | aiohttp + Playwright |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic |

## License

Proprietary — All rights reserved.
