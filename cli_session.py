"""Interactive Multi-Tenant CLI Session Terminal.

Routes all user prompts through Central Server API (POST /runs),
enforcing Rate Limiting and Worker Queue System!
"""

from __future__ import annotations

import argparse
import asyncio
import time
import httpx
from dotenv import load_dotenv

load_dotenv()


async def run_interactive_human_session(user_id: str, session_id: str, server_url: str = "http://127.0.0.1:8000"):
    print("=" * 65)
    print("REAL HUMAN INTERACTIVE AGENT SESSION (SERVER QUEUE ROUTED)")
    print(f"User ID    : {user_id}")
    print(f"Session ID : {session_id}")
    print(f"Server API : {server_url}")
    print("=" * 65)
    print("Type your message and press ENTER. Type 'exit' or 'quit' to stop.\n")

    headers = {"Authorization": f"Bearer {user_id}"}

    async with httpx.AsyncClient(timeout=120.0) as client:
        while True:
            try:
                user_msg = input(f"[{user_id}] > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nExiting session...")
                break

            if not user_msg:
                continue
            if user_msg.lower() in ("exit", "quit"):
                print("Session ended.")
                break

            print("\nSubmitting run to Central Queue & Rate Limiter...\n")

            try:
                # 1. Submit to POST /runs
                res = await client.post(
                    f"{server_url}/runs",
                    headers=headers,
                    json={"session_id": session_id, "message": user_msg},
                )

                if res.status_code == 429:
                    print("-" * 60)
                    print(f"⚠️ RATE LIMITED: {res.json().get('detail', 'Rate limit exceeded')}")
                    print("-" * 60 + "\n")
                    continue

                if res.status_code != 202:
                    print(f"Error submitting run: {res.status_code} - {res.text}")
                    continue

                run_data = res.json()
                run_id = run_data["run_id"]

                # 2. Stream GET /runs/{run_id}/events SSE live tool events
                start_t = time.time()
                try:
                    async with client.stream("GET", f"{server_url}/runs/{run_id}/events", headers=headers) as event_stream:
                        async for line in event_stream.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            raw_data = line[6:].strip()
                            try:
                                import json
                                evt = json.loads(raw_data)
                                evt_type = evt.get("type")
                                evt_data = evt.get("data", {})

                                if evt_type == "tool_call":
                                    tool_name = evt_data.get("tool", "")
                                    args = evt_data.get("args", {})
                                    if tool_name == "TodoWrite":
                                        todos = args.get("todos", [])
                                        print("\n📋 [Plan Created / Updated]:")
                                        for idx, t in enumerate(todos, 1):
                                            status = "✓" if t.get("status") == "completed" else " "
                                            print(f"   [{status}] Step {idx}: {t.get('text', '')}")
                                        print()
                                    elif tool_name == "Bash":
                                        cmd = args.get("command") or args.get("cmd") or ""
                                        print(f"🛠️ [Tool Call] Executing [Bash] -> Command: {cmd}")
                                    elif tool_name in ("WriteFile", "ReadFile", "EditFile"):
                                        path = args.get("path") or args.get("file") or ""
                                        print(f"🛠️ [Tool Call] Executing [{tool_name}] -> Target File: {path}")
                                    elif tool_name == "SearchKnowledge":
                                        q = args.get("query", "")
                                        print(f"🔍 [RAG Search] Querying Vector Knowledge -> '{q}'")
                                    else:
                                        print(f"🛠️ [Tool Call] Executing [{tool_name}] with args: {args}")
                                elif evt_type == "tool_result":
                                    tool_name = evt_data.get("tool", "")
                                    is_err = evt_data.get("is_error", False)
                                    dur = evt_data.get("duration_s", 0.0)
                                    status_str = "ERROR" if is_err else "SUCCESS"
                                    print(f"↳ [{tool_name}] -> {status_str} ({dur:.2f}s)")
                                elif evt_type == "text":
                                    txt = evt_data.get("text", "")
                                    if txt:
                                        print(f"\n💬 [Agent Output]\n{txt}")
                                elif evt_type == "run_finished":
                                    spend = evt_data.get("spend_usd", 0.0)
                                    turns = evt_data.get("iterations", 1)
                                    print("-" * 60)
                                    print(f"[Completed in {time.time()-start_t:.1f}s | Turns: {turns} | Spend: ${spend:.4f}]\n")
                                    break
                                elif evt_type == "run_failed":
                                    msg = evt_data.get("message", "Execution failed")
                                    print("-" * 60)
                                    print(f"❌ Run Failed: {msg}\n")
                                    break
                            except Exception:
                                pass
                except Exception:
                    # Fallback to polling if SSE stream closes
                    while True:
                        await asyncio.sleep(0.5)
                        r = await client.get(f"{server_url}/runs/{run_id}", headers=headers)
                        if r.status_code == 200:
                            run_info = r.json()
                            st = run_info["status"]
                            if st.upper() == "SUCCEEDED":
                                print("-" * 60)
                                print(f"RESPONSE:\n{run_info.get('text', '(Completed)')}")
                                print("-" * 60)
                                print(f"[Turns: {run_info['iterations']} | Spend: ${run_info['spend_usd']:.4f} | Time: {time.time()-start_t:.1f}s]\n")
                                break
                            elif st.upper() in ("FAILED", "CANCELLED"):
                                print("-" * 60)
                                print(f"❌ RUN {st.upper()}: {run_info.get('error', 'Execution error')}")
                                print("-" * 60 + "\n")
                                break

            except Exception as exc:
                print("-" * 60)
                print(f"API Exception ({type(exc).__name__}): {exc}")
                print("-" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Real Human Interactive Agent CLI")
    parser.add_argument("--user", type=str, default="user_1", help="User ID")
    parser.add_argument("--session", type=str, default="session_human_1", help="Session ID")
    parser.add_argument("--url", type=str, default="http://127.0.0.1:8000", help="Server URL")
    args = parser.parse_args()

    try:
        asyncio.run(run_interactive_human_session(args.user, args.session, args.url))
    except KeyboardInterrupt:
        print("\nSession stopped.")


if __name__ == "__main__":
    main()
