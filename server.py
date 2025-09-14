# server.py
import os
import asyncio
import json
import uuid
from collections import deque, defaultdict
from typing import Dict, Set, Tuple, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn

REDIS_URL = os.environ.get("REDIS_URL")  # e.g. redis://:password@host:6379/0
PORT = int(os.environ.get("PORT", 8000))
HISTORY_LIMIT = int(os.environ.get("HISTORY_LIMIT", 100))

# If REDIS_URL is provided, we will use redis.asyncio
use_redis = bool(REDIS_URL)
r = None
if use_redis:
    import redis.asyncio as redis
    r = redis.from_url(REDIS_URL, decode_responses=True)

app = FastAPI()

# Local fallback structures used if no Redis available (single-instance testing)
local_pub_queues: Dict[str, asyncio.Queue] = defaultdict(asyncio.Queue)
local_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=HISTORY_LIMIT))

# Local structure: channel -> set of (websocket, conn_id)
local_channels: Dict[str, Set[Tuple[WebSocket, str]]] = defaultdict(set)

# Subscriber tasks per channel (either redis subscriber or local queue consumer)
sub_tasks: Dict[str, asyncio.Task] = {}

async def send_json_safe(ws: WebSocket, payload: dict):
    try:
        await ws.send_text(json.dumps(payload))
    except Exception:
        # socket broken or closed - ignore here; cleanup occurs elsewhere
        pass

async def publish_message(channel: str, payload: dict):
    text = json.dumps(payload)
    # store in history
    if use_redis:
        await r.rpush(f"chat:hist:{channel}", text)
        await r.ltrim(f"chat:hist:{channel}", -HISTORY_LIMIT, -1)
        # publish to redis channel
        await r.publish(f"chat:pub:{channel}", text)
    else:
        # local history and local pub
        local_history[channel].append(text)
        q = local_pub_queues[channel]
        # non-blocking put
        await q.put(text)

async def ensure_subscriber(channel: str):
    if sub_tasks.get(channel):
        return
    if use_redis:
        sub_tasks[channel] = asyncio.create_task(redis_subscriber(channel))
    else:
        sub_tasks[channel] = asyncio.create_task(local_queue_consumer(channel))

async def redis_subscriber(channel: str):
    """Listen to redis pubsub for a channel and forward to local clients (skip origin)."""
    pubsub = r.pubsub()
    await pubsub.subscribe(f"chat:pub:{channel}")
    try:
        async for message in pubsub.listen():
            if not message:
                continue
            if message.get("type") != "message":
                continue
            data_raw = message.get("data")
            try:
                payload = json.loads(data_raw)
            except:
                continue
            origin = payload.get("origin_id")
            # forward to local websockets except origin
            clients = list(local_channels.get(channel, set()))
            coros = []
            for ws, cid in clients:
                if cid == origin:
                    continue
                if ws.client_state.name != "CONNECTED":
                    local_channels[channel].discard((ws, cid))
                    continue
                coros.append(send_json_safe(ws, payload))
            if coros:
                await asyncio.gather(*coros, return_exceptions=True)
    finally:
        await pubsub.unsubscribe(f"chat:pub:{channel}")
        sub_tasks.pop(channel, None)

async def local_queue_consumer(channel: str):
    """Consume local queue and forward to local websockets (skip origin)."""
    q = local_pub_queues[channel]
    while True:
        try:
            text = await q.get()
        except asyncio.CancelledError:
            break
        try:
            payload = json.loads(text)
        except:
            continue
        origin = payload.get("origin_id")
        clients = list(local_channels.get(channel, set()))
        coros = []
        for ws, cid in clients:
            if cid == origin:
                continue
            if ws.client_state.name != "CONNECTED":
                local_channels[channel].discard((ws, cid))
                continue
            coros.append(send_json_safe(ws, payload))
        if coros:
            await asyncio.gather(*coros, return_exceptions=True)

@app.get("/")
async def health():
    return {"ok": True}

@app.websocket("/ws/{channel}")
async def ws_endpoint(websocket: WebSocket, channel: str):
    await websocket.accept()
    conn_id = str(uuid.uuid4())
    local_channels[channel].add((websocket, conn_id))

    # send history once
    if use_redis:
        hist = await r.lrange(f"chat:hist:{channel}", 0, -1)
        for item in hist:
            try:
                await websocket.send_text(item)
            except:
                pass
    else:
        hist = list(local_history.get(channel, []))
        for item in hist:
            try:
                await websocket.send_text(item)
            except:
                pass

    # ensure subscriber running for this channel
    await ensure_subscriber(channel)

    try:
        while True:
            text = await websocket.receive_text()
            # expect JSON with username and text
            try:
                data = json.loads(text)
            except:
                data = {"text": text}
            username = data.get("username", "Anonymous")
            message_text = data.get("text", "").strip()
            if not message_text:
                continue

            payload = {
                "username": username,
                "text": message_text,
                "channel": channel,
                "origin_id": conn_id,
                "ts": asyncio.get_event_loop().time()
            }
            await publish_message(channel, payload)

            # Do not echo back to sender from server; show immediate in client UI instead.
    except WebSocketDisconnect:
        pass
    finally:
        local_channels[channel].discard((websocket, conn_id))
    return

if __name__ == "__main__":
    if use_redis:
        print("Using Redis at", REDIS_URL)
    else:
        print("Running in local fallback mode (no Redis). Good for local testing.")
    print(f"Starting server on 0.0.0.0:{PORT}")
    uvicorn.run("server:app", host="0.0.0.0", port=PORT, log_level="info")
