import asyncio
import time
import httpx
import json

BRIDGE_URL = "http://127.0.0.1:5000/v1/audio/speech"
# Direct API might be http://127.0.0.1:9880/tts/tavern or similar, but we test the bridge 
# because user uses SAP -> Bridge -> API.

async def test_case(name, input_text, expect_error=False):
    print(f"\n--- Test Case: {name} ---")
    print(f"Input: '{input_text}' (Len: {len(input_text)})")
    
    payload = {
        "input": input_text,
        "voice": "胡桃",
        "model": "cosyvoice-v1"
    }
    
    start_time = time.time()
    first_byte_time = None
    total_size = 0
    status_code = 0
    
    try:
        async with httpx.AsyncClient() as client:
            async with client.stream("POST", BRIDGE_URL, json=payload, timeout=60) as resp:
                status_code = resp.status_code
                print(f"Status: {status_code}")
                
                if status_code != 200:
                    content = await resp.read()
                    print(f"Error Response: {content.decode()}")
                    if not expect_error:
                         print("❌ UNEXPECTED ERROR")
                    else:
                         print("✅ Expected Error Received")
                    return

                print("Stream started...")
                async for chunk in resp.aiter_bytes():
                    if first_byte_time is None:
                        first_byte_time = time.time()
                        latency = first_byte_time - start_time
                        print(f"⚡ First Byte Latency: {latency:.4f}s")
                    
                    total_size += len(chunk)
    
    except Exception as e:
        print(f"❌ Exception: {repr(e)}")
        return

    end_time = time.time()
    total_time = end_time - start_time
    print(f"Total Time: {total_time:.4f}s")
    print(f"Total Size: {total_size} bytes")
    
    if first_byte_time:
         print(f"✅ Success (Streamed)")
    else:
         print(f"⚠️ Success (No Data / Empty Stream)")

async def main():
    # 1. Normal Case
    await test_case("Normal Text", "你好呀，我是胡桃！找我有什么事情吗？")
    
    # 2. Short Text (Now should be handled by silence fallback)
    await test_case("Short Text", "你好", expect_error=False)
    
    # 3. Punctuation Only (Should be cleaned to empty/short)
    await test_case("Punctuation", "。。。")
    
    # 4. Long Text (Checking buffering)
    await test_case("Long Text", "春江潮水连海平，海上明月共潮生。滟滟随波千万里，何处春江无月明。因为这句话很长，所以我们看看流式效果。")

if __name__ == "__main__":
    asyncio.run(main())
