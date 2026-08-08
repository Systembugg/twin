# Bash & Shell Execution Skill Cheatsheet

## CRITICAL GOTCHAS & RULES
1. **Incremental Execution:** Break long multi-command scripts into individual steps or short chained bash calls.
2. **Directory & Workspace Scoping:** Always verify directory location with `pwd` or `ls` before attempting relative operations.
3. **Structured Error Triage (`reproduce -> localize -> fix -> guard`):**
   - If a bash command fails, read stderr carefully.
   - Do NOT re-run the exact same command without modifying parameters or fixing missing dependencies.
   - Check if required packages are installed in `.venv`.
