# server.py
import os
import asyncio
from aiohttp import web, WSMsgType

clients = set()

async def index(request):
    return web.Response(text="OK")  # Render health check / root

async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    clients.add(ws)
    print("Client connected. Total:", len(clients))
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                text = msg.data.strip()
                if not text:
                    continue
                # broadcast to all connected clients (skip closed)
                coros = []
                for c in list(clients):
                    if c.closed:
                        clients.discard(c)
                        continue
                    coros.append(c.send_str(text))
                if coros:
                    await asyncio.gather(*coros, return_exceptions=True)
            elif msg.type == WSMsgType.ERROR:
                print("WS connection error:", ws.exception())
    finally:
        clients.discard(ws)
        print("Client disconnected. Total:", len(clients))
    return ws

if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 3000))
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/ws", websocket_handler)

    print("Starting on 0.0.0.0:%d" % PORT)
    web.run_app(app, host="0.0.0.0", port=PORT)
