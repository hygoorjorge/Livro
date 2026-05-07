import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.logging import get_logger
from app.workers.progress import subscribe, unsubscribe

router = APIRouter(prefix="/ws", tags=["ws"])
logger = get_logger(__name__)


@router.websocket("/sessions/{session_id}/progress")
async def session_progress(ws: WebSocket, session_id: int):
    await ws.accept()
    queue = await subscribe(session_id)
    try:
        await ws.send_json({"event": "connected", "data": {"session_id": session_id}})
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=30)
                await ws.send_json(payload)
            except asyncio.TimeoutError:
                await ws.send_json({"event": "ping", "data": {}})
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("ws error session=%d: %s", session_id, exc)
    finally:
        await unsubscribe(session_id, queue)
