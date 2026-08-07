import subprocess
import os
import sys

env = os.environ.copy()
env["GROQ_API_KEY"] = os.environ.get("GROQ_API_KEY", "your-api-key")
env["TWIN_MODEL_PRICE"] = "0.59,0.79"

prompts = [
    "kya haal hai",
    "create notes.md with three bullets, then read it back",
    "write a.txt, b.txt and c.txt",
    "/quit"
]

input_data = "\n".join(prompts) + "\n"

python_exe = os.path.join(os.getcwd(), ".venv", "Scripts", "python.exe")

cmd = [
    python_exe, "-m", "twin.cli",
    "--persona", "persona.json",
    "--base-url", "groq",
    "--model", "llama-3.3-70b-versatile"
]

proc = subprocess.Popen(
    cmd,
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    env=env
)

stdout, stderr = proc.communicate(input=input_data)

print("=== STDOUT ===")
print(stdout)
print("=== STDERR ===")
print(stderr)
