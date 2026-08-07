import subprocess
import os
import sys

env = os.environ.copy()
key = os.environ.get("OPENROUTER_API_KEY", "your-api-key")
env["TWIN_API_KEY"] = key
env["OPENAI_API_KEY"] = key
env["TWIN_MODEL_PRICE"] = "0.59,0.79"

prompt = """build a small expense tracker cli in python. requirements:
- expenses.py with an Expense dataclass and a Tracker class that can add(amount, category), total(), and by_category() returning a dict
- cli.py that takes commands: add <amount> <category>, report, storing data in expenses.json
- test_expenses.py with at least 4 tests using plain asserts, no pytest
run test_expenses.py to verify. then add a top command that prints the single biggest category, run tests again, and update README.md with usage examples.
/quit
"""

python_exe = os.path.join(os.getcwd(), ".venv", "Scripts", "python.exe")

cmd = [
    python_exe, "-m", "twin.cli",
    "--persona", "persona.json",
    "--base-url", "openrouter",
    "--model", "inclusionai/ling-3.0-flash:free"
]

proc = subprocess.Popen(
    cmd,
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    env=env
)

stdout, stderr = proc.communicate(input=prompt)

print("=== STDOUT ===")
print(stdout)
print("=== STDERR ===")
print(stderr)
