"""Launcher Script: Opens 4 separate Windows PowerShell terminals simultaneously!

1. Main Surveillance Monitor Terminal
2. User 1 Interactive Terminal (Financial Analyst)
3. User 2 Interactive Terminal (Python Coder)
4. User 3 Interactive Terminal (Casual Chat)
"""

import subprocess
import sys
import time

PYTHON_EXE = sys.executable

def main():
    print("=" * 60)
    print("🚀 Launching Multi-User CLI Terminal Suite...")
    print("=" * 60)

    # 1. Launch Surveillance Terminal in new window
    print("1. Opening Main Surveillance Monitor Terminal...")
    subprocess.Popen(
        f'start powershell -NoExit -Command "{PYTHON_EXE} cli_surveillance.py"',
        shell=True,
    )
    time.sleep(1)

    # 2. Launch User 1 Session Terminal in new window
    print("2. Opening User 1 Terminal (user_1)...")
    subprocess.Popen(
        f'start powershell -NoExit -Command "{PYTHON_EXE} cli_session.py --user user_1"',
        shell=True,
    )
    time.sleep(0.5)

    # 3. Launch User 2 Session Terminal in new window
    print("3. Opening User 2 Terminal (user_2)...")
    subprocess.Popen(
        f'start powershell -NoExit -Command "{PYTHON_EXE} cli_session.py --user user_2"',
        shell=True,
    )
    time.sleep(0.5)

    # 4. Launch User 3 Session Terminal in new window
    print("4. Opening User 3 Terminal (user_3)...")
    subprocess.Popen(
        f'start powershell -NoExit -Command "{PYTHON_EXE} cli_session.py --user user_3"',
        shell=True,
    )

    print("\n✅ All 4 terminals popped open successfully!")
    print("  -> Use each User Terminal to type custom prompts.")
    print("  -> Use the Surveillance Terminal to monitor real-time execution!")

if __name__ == "__main__":
    main()
