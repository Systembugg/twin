"""Multi-User Interactive CLI Launcher.

Allows testing N interactive users at once with -n / --users flag!

Usage:
  python multi_user_cli.py -n 3
"""

from __future__ import annotations

import argparse
import asyncio
import time
import httpx
from dotenv import load_dotenv

load_dotenv()


async def run_interactive_multi_user(num_users: int, server_url: str = "http://127.0.0.1:8000"):
    print("=" * 65)
    print(f"MULTI-USER INTERACTIVE CLI (-n {num_users} ACTIVE USERS)")
    print(f"Server API : {server_url}")
    print("=" * 65)
    print("Commands:")
    print("  <prompt>        -> Sends prompt to ALL active users simultaneously!")
    print("  u1 <prompt>     -> Sends prompt ONLY to User 1")
    print("  u2 <prompt>     -> Sends prompt ONLY to User 2")
    print("  exit / quit     -> Stop interactive session\n")

    user_ids = [f"user_{i}" for i in range(1, num_users + 1)]

    async with httpx.AsyncClient(timeout=120.0) as client:
        while True:
            try:
                raw_input = input(f"[{num_users} Users Mode] > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nExiting session...")
                break

            if not raw_input:
                continue
            if raw_input.lower() in ("exit", "quit"):
                print("Multi-user session ended.")
                break

            target_users = user_ids
            msg = raw_input

            # Check if user specified u1, u2, u3 prefix
            parts = raw_input.split(" ", 1)
            if len(parts) == 2 and parts[0].startswith("u") and parts[0][1:].isdigit():
                target_idx = int(parts[0][1:])
                if 1 <= target_idx <= num_users:
                    target_users = [f"user_{target_idx}"]
                    msg = parts[1]

            print(f"\n🚀 Submitting prompt to {len(target_users)} user session(s) in parallel...\n")

            async def send_user_prompt(u_id: str):
                headers = {"Authorization": f"Bearer {u_id}"}
                session_id = f"session_{u_id}"
                try:
                    res = await client.post(
                        f"{server_url}/runs",
                        headers=headers,
                        json={"session_id": session_id, "message": msg},
                    )
                    if res.status_code == 202:
                        run_id = res.json()["run_id"]
                        print(f"[{u_id.upper()}] Enqueued Run ID: {run_id[:12]}...")
                        # Poll for completion
                        while True:
                            await asyncio.sleep(2.0)
                            run_res = await client.get(f"{server_url}/runs/{run_id}", headers=headers)
                            if run_res.status_code == 200:
                                data = run_res.json()
                                st = data.get("status")
                                if st == "succeeded":
                                    print(f"\n" + "=" * 60)
                                    print(f"🎉 RESPONSE FOR [{u_id.upper()}]:")
                                    print(data.get("text", ""))
                                    if data.get("files"):
                                        print(f"📁 Generated Files: {[f['name'] for f in data['files']]}")
                                    print("=" * 60 + "\n")
                                    break
                                elif st in ("failed", "cancelled"):
                                    print(f"❌ [{u_id.upper()}] Failed: {data.get('error')}")
                                    break
                    elif res.status_code == 429:
                        print(f"⚠️ [{u_id.upper()}] Rate Limited 429")
                    else:
                        print(f"❌ [{u_id.upper()}] HTTP Error {res.status_code}")
                except Exception as exc:
                    print(f"❌ [{u_id.upper()}] Exception: {exc}")

            await asyncio.gather(*(send_user_prompt(u) for u in target_users))


def main():
    parser = argparse.ArgumentParser(description="Multi-User Interactive CLI Launcher")
    parser.add_argument("-n", "--users", type=int, default=3, help="Number of concurrent interactive users")
    parser.add_argument("--url", type=str, default="http://127.0.0.1:8000", help="Server URL")
    args = parser.parse_args()

    try:
        asyncio.run(run_interactive_multi_user(args.users, args.url))
    except KeyboardInterrupt:
        print("\nSession stopped.")


if __name__ == "__main__":
    main()
