"""Dynamic Multi-User Terminal Launcher.

Spawns:
1. Central Queue & Dashboard Server (Background Server)
2. Main Real-Time Terminal Surveillance Monitor (Terminal Window 1)
3. N User Session Terminals (Terminal Windows 2, 3, 4...)
"""

import argparse
import os
import subprocess
import sys
import time

VENV_PYTHON = os.path.abspath(r".\.venv\Scripts\python.exe")


def main():
    parser = argparse.ArgumentParser(description="Dynamic Multi-User CLI Launcher")
    parser.add_argument("--users", type=int, default=3, help="Number of user terminals to spawn")
    args = parser.parse_args()

    num_users = max(1, args.users)

    print("=" * 70)
    print(f"🚀 Launching Twin Enterprise (1 Central Server + 1 Surveillance + {num_users} User Terminals)")
    print("=" * 70)

    # 1. Start Central Server & Worker Queue Process in new PowerShell window
    print("1. Launching Central API Server & Queue System...")
    cmd_server = f'start powershell -NoExit -Command "& \'{VENV_PYTHON}\' run_dashboard_server.py"'
    subprocess.Popen(cmd_server, shell=True)
    time.sleep(2.5)

    # 2. Start Surveillance Monitor Terminal
    print("2. Launching Main Surveillance Monitor Terminal...")
    cmd_surveillance = f'start powershell -NoExit -Command "& \'{VENV_PYTHON}\' cli_surveillance.py"'
    subprocess.Popen(cmd_surveillance, shell=True)
    time.sleep(1.0)

    # 3. Start N User Interactive Terminals
    for i in range(1, num_users + 1):
        user_id = f"user_{i}"
        session_id = f"session_human_{i}"
        print(f"3. Launching Interactive Queue Terminal for {user_id}...")

        cmd_user = f'start powershell -NoExit -Command "& \'{VENV_PYTHON}\' cli_session.py --user {user_id} --session {session_id}"'
        subprocess.Popen(cmd_user, shell=True)
        time.sleep(0.4)

    print(f"\n✅ Enterprise Cluster Started! (1 Server + 1 Surveillance + {num_users} User Terminals)")


if __name__ == "__main__":
    main()
