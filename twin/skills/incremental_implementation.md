# Incremental Implementation Skill

## CORE PRINCIPLE
Follow the micro-loop: `implement -> test -> verify -> complete`

## GUIDELINES
1. Write small, testable chunks of code instead of giant monolithic scripts.
2. Verify file integrity (e.g. re-open `.pptx`/`.docx` files or run syntax checks) before declaring turn completion.
3. Catch errors early before they cascade.
