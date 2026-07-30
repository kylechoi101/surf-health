"""Shared rate-limiter instance.

Extracted from main.py so that route modules can import it without a
circular dependency (main → routes → main).
"""
from fastapi import Request
from slowapi import Limiter


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
