# Install: pip install websockets
import asyncio
import websockets

connected_clients = set()

async def handler(websocket, path):
    # Add new client
    connected_clients.add(websocket)
    try:
        async for message in websocket:
            print(f"Received: {message}")
            # Broadcast to all clients
            await asyncio.gather(*[ws.send(message) for ws in connected_clients])
    except:
        pass
    finally:
        connected_clients.remove(websocket)

async def main():
    async with websockets.serve(handler, "0.0.0.0", 3000):
        print("Server running on ws://localhost:3000")
        await asyncio.Future()  # run forever

asyncio.run(main())
