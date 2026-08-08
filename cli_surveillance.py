"""Real-Time Terminal Surveillance & Audit Monitor.

Tails shared audit log stream and displays live multi-tenant agent prompts,
skill injections, tool executions, path escape interventions, and run events in real-time.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

LOG_PATH = Path(r"C:\tmp\twin-workspaces\audit_stream.log")


async def run_surveillance_monitor():
    print("=" * 80)
    print(" 🛡️  TWIN ENTERPRISE -- REAL-TIME TERMINAL SURVEILLANCE & AUDIT MONITOR")
    print(f" 📍 Log Stream: {LOG_PATH}")
    print("=" * 80)
    print(" Listening for active multi-tenant user runs, skill injections & tool executions...\n")

    # Clear previous audit log file at start
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] [SYSTEM] Surveillance Audit Stream Initialized.\n")

    # Tail the log file
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        f.seek(0, os.SEEK_END)
        while True:
            line = f.readline()
            if not line:
                await asyncio.sleep(0.2)
                continue

            raw = line.strip()
            if not raw:
                continue

            # Beautiful Formatting Parser
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


def main():
    try:
        asyncio.run(run_surveillance_monitor())
    except KeyboardInterrupt:
        print("\nSurveillance Monitor stopped.")


if __name__ == "__main__":
    main()
