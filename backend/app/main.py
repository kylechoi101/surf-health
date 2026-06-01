import json
import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.routes import router
from app.core.config import get_settings


# ---------------------------------------------------------------------------
# Structured JSON logging
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("surf_health.access")


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

def _client_ip_key(request: Request) -> str:
    """Real client IP for rate limiting.

    The service runs behind Cloudflare → Render's proxy, and uvicorn is not
    started with --proxy-headers, so ``request.client.host`` is the proxy IP —
    identical for every visitor. Keying the limiter on it collapses all traffic
    (web, mobile, crons, organic) into one global 60/min bucket, so a single
    busy minute 429s everyone at once. Prefer Cloudflare's ``CF-Connecting-IP``
    (set by the edge; clients cannot forge it), then the first ``X-Forwarded-For``
    hop, then the socket peer for local/dev.
    """
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


limiter = Limiter(key_func=_client_ip_key, default_limits=["120/minute"])


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Surf Health API",
    summary="California marine beach health forecast service",
    version="0.1.0",
)

# Attach limiter state so SlowAPI middleware can find it
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "HEAD", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
)

app.include_router(router)


# ---------------------------------------------------------------------------
# Structured request logging middleware
# ---------------------------------------------------------------------------

@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = str(uuid.uuid4())
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = round((time.monotonic() - start) * 1000, 1)
    logger.info(
        json.dumps(
            {
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            }
        )
    )
    return response


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    return {
        "name": "Surf Health API",
        "docs": "/docs",
        "status": "ok",
    }
