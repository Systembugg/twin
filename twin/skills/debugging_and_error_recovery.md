# Debugging & Error Recovery Skill

## CORE PRINCIPLE
When an error occurs, perform structured triage instead of blind retries:
`reproduce -> localize -> reduce -> fix -> guard`

## GUIDELINES
1. Localize: Identify the exact line or parameter that failed from the log traceback.
2. Reduce: Narrow down to the minimal failing unit.
3. Fix & Shift Strategy: Never repeat the exact same broken code or tool parameters.
4. Guard: Verify the fix works so the bug cannot recur.
