"""Launch N interactive CLI sessions in separate PowerShell windows automatically.

Usage:
  python launch_sessions.py -n 3
"""

import argparse
import subprocess
import sys
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Launch N Interactive User Sessions in Separate Windows")
    parser.add_argument("-n", "--users", type=int, default=3, help="Number of interactive user windows to open")
    args = parser.parse_args()

    app_dir = Path(__file__).parent.resolve()
    venv_python = app_dir / ".venv" / "Scripts" / "python.exe"

    print("=" * 65)
    print(f"🚀 LAUNCHING {args.users} INTERACTIVE USER TERMINALS AUTOMATICALLY...")
    print("=" * 65)

    for i in range(1, args.users + 1):
        user_id = f"user_{i}"
        session_id = f"session_{i}"
        
        # Windows command to open a new separate powershell window running cli_session.py
        cmd = [
            "powershell",
            "-Command",
            f"Start-Process powershell -ArgumentList '-NoExit', '-Command', 'cd ''{app_dir}''; & ''{venv_python}'' cli_session.py --user {user_id} --session {session_id}'"
        ]
        subprocess.run(cmd)
        print(f"  ✅ Spawned Terminal Window #{i} for [{user_id}]")

    print("\n🎉 All interactive windows launched! Switch to your open terminal windows and start typing prompts!")

if __name__ == "__main__":
    main()
