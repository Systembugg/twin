"""Real-Time Terminal Surveillance & Audit Monitor.

Tails shared audit log stream and displays live multi-tenant agent prompts,
tool executions, path escape interventions, and run events in real-time.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time
from pathlib import Path

LOG_PATH = Path(r"C:\tmp\twin-workspaces\audit_stream.log")


async def run_surveillance_monitor():
    print("=" * 75)
    print("TWIN ENTERPRISE -- REAL-TIME TERMINAL SURVEILLANCE MONITOR")
    print(f"Log Stream: {LOG_PATH}")
    print("=" * 75)
    print("Listening for multi-tenant user prompts, tool calls, and completions...\n")

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
            print(line.strip())


def main():
    try:
        asyncio.run(run_surveillance_monitor())
    except KeyboardInterrupt:
        print("\nSurveillance Monitor stopped.")


if __name__ == "__main__":
    main()
