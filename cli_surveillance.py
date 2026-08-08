"""Real-Time Terminal Surveillance & Audit Monitor.

Tails remote or local audit log stream and displays live multi-tenant agent prompts,
skill injections, tool executions, path escape interventions, and run events in real-time.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time
import httpx
from pathlib import Path

LOCAL_LOG_PATH = Path(r"C:\tmp\twin-workspaces\audit_stream.log")


def print_formatted_event(raw: str):
    if not raw:
        return
    if "[SKILL_INJECTED]" in raw:
        print(f" 📚 {raw}")
    elif "[TOOL_CALL]" in raw:
        print(f" 🛠️  {raw}")
    elif "[TOOL_RESULT]" in raw:
        if "ERROR" in raw:
            print(f" ❌ {raw}")
        else:
            print(f" ✅ {raw}")
    elif "[RUN_FINISHED]" in raw:
        print(f" 🎉 {raw}\n" + "─" * 80)
    elif "[QUEUE_ENQUEUE]" in raw or "[QUEUE_DEQUEUE]" in raw:
        print(f" 🔄 {raw}")
    else:
        print(f" ℹ️  {raw}")


async def run_surveillance_monitor(server_url: str):
    print("=" * 80)
    print(" 🛡️  TWIN ENTERPRISE -- REAL-TIME TERMINAL SURVEILLANCE & AUDIT MONITOR")
    print(f" 📍 Server Stream: {server_url}/surveillance/stream")
    print("=" * 80)
    print(" Listening for active multi-tenant user runs, skill injections & tool executions...\n")

    if server_url.startswith("http"):
        # Remote Server SSE Stream Mode
        while True:
            try:
                async with httpx.AsyncClient(timeout=None) as client:
                    async with client.stream("GET", f"{server_url}/surveillance/stream") as response:
                        async for line in response.aiter_lines():
                            if line.startswith("data: "):
                                raw = line[6:].strip()
                                print_formatted_event(raw)
            except Exception as exc:
                print(f"⚠️ Remote stream error ({exc}). Retrying in 2 seconds...")
                await asyncio.sleep(2.0)
    else:
        # Local File Tail Mode
        LOCAL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not LOCAL_LOG_PATH.exists():
            with open(LOCAL_LOG_PATH, "w", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] [SYSTEM] Surveillance Audit Stream Initialized.\n")

        with open(LOCAL_LOG_PATH, "r", encoding="utf-8") as f:
            f.seek(0, os.SEEK_END)
            while True:
                line = f.readline()
                if not line:
                    await asyncio.sleep(0.2)
                    continue
                print_formatted_event(line.strip())


def main():
    parser = argparse.ArgumentParser(description="Real-Time Surveillance Terminal Monitor")
    parser.add_argument("--url", "--server", type=str, default="http://127.0.0.1:8000", help="Server URL", dest="server")
    args = parser.parse_args()

    try:
        asyncio.run(run_surveillance_monitor(args.server))
    except KeyboardInterrupt:
        print("\nSurveillance Monitor stopped.")


if __name__ == "__main__":
    main()
