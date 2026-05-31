"""Redis connectivity (hot state / cache). Used for readiness checks in Phase 1."""
from __future__ import annotations

import redis

from shelfsense_common.config import get_settings

_client = redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=2)


def ping_redis() -> bool:
    try:
        return bool(_client.ping())
    except Exception:
        return False
