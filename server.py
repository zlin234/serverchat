import os, asyncio, websockets

PORT = int(os.environ.get("PORT", 3000))
connected_clients = set()

async def handler(websocket, path):
    connected_clients.add(websocket)
    try:
        async for message in websocket:
            print(f"Received: {message}")
            await asyncio.gather(*[ws.send(message) for ws in connected_clients])
    finally:
        connected_clients.remove(websocket)

async def main():
    async with websockets.serve(handler, "0.0.0.0", PORT):
        print(f"Server running on ws://0.0.0.0:{PORT}")
        await asyncio.Future()

asyncio.run(main())
