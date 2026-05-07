"""In-process pub/sub bus for session progress events.

Emitters call ``publish_progress``; WebSocket subscribers read from per-session
asyncio queues. The bus is intentionally lightweight (single-process FastAPI);
swap for Redis pub/sub if the app ever needs multi-worker deployment.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

_subscribers: dict[int, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
_lock = asyncio.Lock()


async def subscribe(session_id: int) -> asyncio.Queue[dict[str, Any]]:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
    async with _lock:
        _subscribers[session_id].add(queue)
    return queue


async def unsubscribe(session_id: int, queue: asyncio.Queue) -> None:
    async with _lock:
        _subscribers[session_id].discard(queue)
        if not _subscribers[session_id]:
            _subscribers.pop(session_id, None)


async def publish_progress(
    session_id: int, event: str, data: dict[str, Any] | None = None
) -> None:
    payload = {"event": event, "data": data or {}}
    async with _lock:
        queues = list(_subscribers.get(session_id, ()))
    for q in queues:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass
