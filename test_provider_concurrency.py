import asyncio
import os
import time
from dotenv import load_dotenv
from httpx import AsyncClient

load_dotenv()

API_KEY = os.getenv("TWIN_API_KEY")
BASE_URL = os.getenv("TWIN_BASE_URL")
MODEL = os.getenv("TWIN_MODEL")

async def fetch(client, i):
    start = time.time()
    try:
        response = await client.post(
            f"{BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": "Say exactly one word: Hi."}],
                "max_tokens": 5
            },
            timeout=30.0
        )
        duration = time.time() - start
        
        if response.status_code == 200:
            return (i, True, response.status_code, duration)
        else:
            return (i, False, response.status_code, duration)
    except Exception as e:
        duration = time.time() - start
        return (i, False, str(e), duration)

async def main():
    print(f"Testing concurrency against {BASE_URL} with model {MODEL}...")
    print("Sending 50 simultaneous extremely lightweight requests (negligible cost)...\n")
    
    start_total = time.time()
    async with AsyncClient() as client:
        tasks = [fetch(client, i) for i in range(50)]
        results = await asyncio.gather(*tasks)
    
    total_time = time.time() - start_total
    
    success = sum(1 for r in results if r[1] is True)
    failed = sum(1 for r in results if r[1] is False)
    
    print("--- RESULTS ---")
    print(f"Total Requests: 50")
    print(f"Successful: {success}")
    print(f"Failed/Throttled: {failed}")
    print(f"Total Time: {total_time:.2f} seconds\n")
    
    status_codes = {}
    for r in results:
        status_codes[r[2]] = status_codes.get(r[2], 0) + 1
        
    print("Status Codes:")
    for code, count in status_codes.items():
        print(f"  {code}: {count} times")
        
    if failed > 0:
        print("\nCONCLUSION: Concurrency IS the issue. The provider rate-limits you when too many requests hit at once.")
    elif total_time > 10:
        print("\nCONCLUSION: Provider queued the requests. Even though they succeeded, they took a long time to process because of concurrency limits.")
    else:
        print("\nCONCLUSION: Provider handled 50 concurrent requests easily.")

if __name__ == "__main__":
    asyncio.run(main())
