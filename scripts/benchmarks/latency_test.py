import asyncio
import time
import httpx

BRIDGE_URL = "http://127.0.0.1:5000/v1/audio/speech"
PAYLOAD = {
    "input": "测试延迟性能。",
    "voice": "胡桃",
    "model": "cosyvoice-v1"
}

async def benchmark():
    print(f"Connecting to {BRIDGE_URL}...")
    start_time = time.time()
    first_byte_time = None
    total_size = 0
    
    async with httpx.AsyncClient() as client:
        try:
            async with client.stream("POST", BRIDGE_URL, json=PAYLOAD, timeout=60) as resp:
                print(f"Status: {resp.status_code}")
                if resp.status_code != 200:
                    print(await resp.read())
                    return

                print("Receiving stream...")
                async for chunk in resp.aiter_bytes():
                    if first_byte_time is None:
                        first_byte_time = time.time()
                        print(f"First Byte Received after: {first_byte_time - start_time:.4f}s")
                    
                    total_size += len(chunk)
                    # print(f"Received chunk: {len(chunk)} bytes")
        except Exception as e:
            print(f"Error: {e}")
            return

    end_time = time.time()
    print(f"Total Time: {end_time - start_time:.4f}s")
    print(f"First Byte Latency: {first_byte_time - start_time:.4f}s" if first_byte_time else "No data")
    print(f"Total Size: {total_size} bytes")

if __name__ == "__main__":
    asyncio.run(benchmark())
