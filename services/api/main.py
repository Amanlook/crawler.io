"""Crawler.io — Unified Social Media Data API"""

import pathlib
import time
import uuid

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from shared.config.logging import setup_logging
from shared.config.settings import get_settings
from services.api.routes import creators, posts, creator_posts, tracking, webhooks

settings = get_settings()
setup_logging("DEBUG" if settings.app_debug else "INFO")
logger = structlog.get_logger()

# ─── Tag metadata for docs sidebar ───────────────
tags_metadata = [
    {
        "name": "Creators",
        "description": "Lookup, search, and manage creator profiles across Instagram, TikTok, and YouTube.",
    },
    {
        "name": "Posts",
        "description": "Search, retrieve, and analyze posts with engagement metrics. Supports filtering by platform, hashtag, likes, views, and date range.",
    },
    {
        "name": "Tracking",
        "description": "Subscribe to real-time tracking of creators. Get automatic data collection at configurable frequencies.",
    },
    {
        "name": "Webhooks",
        "description": "Register webhook endpoints to receive real-time notifications when tracked creator data changes.",
    },
    {
        "name": "System",
        "description": "Health checks and API status.",
    },
]

app = FastAPI(
    title="Crawler.io API",
    description="""
# Crawler.io — Unified Social Media Data API

One integration, all platforms. Fetch creator profiles, posts, and engagement metrics from **Instagram**, **TikTok**, and **YouTube** through a single normalized API.

## Authentication

All endpoints require a **Bearer token** in the `Authorization` header:

```
Authorization: Bearer sk_test_smoke_test_key_for_local_dev
```

Click the **🔒 Authorize** button on the right to enter your API key, then test any endpoint directly from this page.

## Quick Start

1. **Lookup a creator** → `GET /v1/creators/lookup?platform=instagram&username=virat.kohli`
2. **Get their posts** → `GET /v1/creators/{creator_id}/posts?limit=20`
3. **Search posts** → `GET /v1/posts/search?platform=instagram&min_likes=1000000`
4. **Paginate** → Pass `cursor` from `pagination.next_cursor` to get the next page

## Rate Limits

| Tier | Requests/min | Daily limit |
|------|-------------|-------------|
| Free | 10 | 100 |
| Starter | 100 | 10,000 |
| Pro | 500 | 100,000 |
| Enterprise | 2,000 | 1,000,000 |

Rate limit info is returned in response headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`.
""",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=tags_metadata,
    swagger_ui_parameters={
        "persistAuthorization": True,
        "docExpansion": "list",
        "filter": True,
        "tryItOutEnabled": True,
        "displayRequestDuration": True,
    },
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.api_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Middleware ────────────────────────────────────

@app.middleware("http")
async def request_middleware(request: Request, call_next) -> Response:
    request_id = str(uuid.uuid4())[:12]
    structlog.contextvars.bind_contextvars(request_id=request_id)

    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time"] = f"{duration_ms}ms"

    # Rate limit headers (set by rate_limit dependency)
    if hasattr(request.state, "rate_limit_limit"):
        response.headers["X-RateLimit-Limit"] = str(request.state.rate_limit_limit)
        response.headers["X-RateLimit-Remaining"] = str(request.state.rate_limit_remaining)
        response.headers["X-RateLimit-Reset"] = str(request.state.rate_limit_reset)

    logger.info(
        "request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=duration_ms,
    )
    return response


# ─── Routes ───────────────────────────────────────

# Note: search routes need to be registered before parameterized routes
# to avoid /search being caught by /{id} patterns.
# FastAPI handles this correctly when routes are on the same router.

app.include_router(creators.router, prefix="/v1")
app.include_router(posts.router, prefix="/v1")
app.include_router(creator_posts.router, prefix="/v1")
app.include_router(tracking.router, prefix="/v1")
app.include_router(webhooks.router, prefix="/v1")


# ─── Health & Info ────────────────────────────────

@app.get("/health", tags=["System"])
async def health():
    """Check API health status."""
    return {"status": "ok", "service": "crawler-io-api"}


@app.get("/", tags=["System"])
async def root():
    """API root — links to docs and health check."""
    return {
        "name": "Crawler.io API",
        "version": "1.0.0",
        "docs": "/docs",
        "documentation": "/documentation",
        "redoc": "/redoc",
        "health": "/health",
    }


# ─── Documentation UI ────────────────────────────

_STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"


@app.get("/documentation", include_in_schema=False)
async def documentation_ui():
    """Serve the custom API documentation UI."""
    html = (_STATIC_DIR / "docs.html").read_text()
    return HTMLResponse(html)


app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


# ─── Custom OpenAPI schema with Bearer auth ───────

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=tags_metadata,
    )
    # Add security scheme
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "API Key",
            "description": "Enter your API key (e.g. `sk_test_smoke_test_key_for_local_dev`)",
        }
    }
    # Apply security globally to all endpoints
    openapi_schema["security"] = [{"BearerAuth": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi
