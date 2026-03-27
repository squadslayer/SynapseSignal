import asyncio
import websockets
import json

async def test_ws():
    uri = "ws://localhost:8000/api/v1/ws/state"
    print(f"Connecting to {uri}...")
    try:
        async with websockets.connect(uri) as websocket:
            print("Status: Connected")
            
            # 1. Should receive initial state from Redis
            initial_state = await websocket.recv()
            print("\nReceived Initial State (from Redis):")
            print(json.dumps(json.loads(initial_state), indent=2))
            
            print("\nWaiting for real-time broadcast... (Send a POST request now)")
            
            # 2. Wait for the broadcast from our next POST ingest
            new_state = await websocket.recv()
            print("\nReceived Broadcast (Real-time):")
            print(json.dumps(json.loads(new_state), indent=2))
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_ws())
