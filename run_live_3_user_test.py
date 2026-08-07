"""Automated Live Verification of 3 User Prompts against Central Server."""

import asyncio
import time
import httpx

PROMPTS = {
    "user_1": "i want u to make set a timer for 10 secons and after that make a python file write code for finding prime numbers then get prime numbers then write it in a pdf name prim e",
    "user_2": "can u tell me what is the meaning of session in terms of computer also run a timer for 30 secs",
    "user_3": "hello can u tell me what is the current market cap of nvdia and can u write it in a docx file",
}

SERVER_URL = "http://127.0.0.1:8000"


async def execute_user_prompt(user_id: str, prompt: str):
    headers = {"Authorization": f"Bearer {user_id}"}
    session_id = f"session_test_{user_id}"

    async with httpx.AsyncClient(timeout=120.0) as client:
        print(f"[{user_id.upper()}] Submitting Prompt...")
        res = await client.post(
            f"{SERVER_URL}/runs",
            headers=headers,
            json={"session_id": session_id, "message": prompt},
        )

        if res.status_code != 202:
            print(f"[{user_id.upper()}] Failed to submit: {res.status_code} - {res.text}")
            return

        run_id = res.json()["run_id"]
        print(f"[{user_id.upper()}] Run {run_id} ENQUEUED. Waiting for completion...")

        start_t = time.time()
        last_status = "queued"
        while True:
            await asyncio.sleep(1.0)
            r = await client.get(f"{SERVER_URL}/runs/{run_id}", headers=headers)
            if r.status_code == 200:
                run_info = r.json()
                status = run_info["status"]

                if status != last_status:
                    last_status = status
                    print(f"[{user_id.upper()}] Status changed to: {status.upper()}")

                if status == "SUCCEEDED":
                    print("\n" + "=" * 65)
                    print(f"[{user_id.upper()}] FINISHED IN {time.time()-start_t:.1f}s")
                    print(f"RESPONSE:\n{run_info.get('text', '(No text)')}")
                    print("=" * 65 + "\n")
                    break
                elif status in ("FAILED", "CANCELLED"):
                    print("\n" + "=" * 65)
                    print(f"[{user_id.upper()}] FAILED ({status}): {run_info.get('error')}")
                    print("=" * 65 + "\n")
                    break


async def main():
    print("=" * 70)
    print("RUNNING LIVE 3-USER SIMULTANEOUS VERIFICATION TEST")
    print("=" * 70 + "\n")

    tasks = [execute_user_prompt(user_id, prompt) for user_id, prompt in PROMPTS.items()]
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
