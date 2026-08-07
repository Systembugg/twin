# twin — a digital-twin agent harness

An agentic loop that writes in your voice and does real work (files, shell,
multi-step tasks), built to run many users' runs concurrently.

Two structural decisions shape everything else:

- **The harness is owned; the sandbox is leased.** The loop is small and it is
  the product. Container isolation is a security project, not a feature — it
  sits behind `SandboxFactory` so the backend is a config change.
- **Runs are jobs, not HTTP requests.** A run takes minutes and ~20 model
  calls. `POST /runs` enqueues and returns a `run_id`; workers execute;
  progress comes back over SSE. This is what makes 50+ concurrent users work.

## Layout

```
twin/
  harness.py       the loop — the only file that orchestrates a run
  persona.py       voice: verbatim samples + the stable, cached system prefix
  limits.py        per-run iteration / wall-clock / spend budget
  compaction.py    summarise the middle when the window fills
  hooks.py         permission gates + audit seam
  events.py        the event type emitted to SSE and persisted
  errors.py        recoverable (-> tool_result) vs. terminal (-> stop the run)
  llm/             ModelClient protocol; Anthropic, OpenAI-protocol, fake
  tools/           ReadFile WriteFile EditFile ListDir Bash TodoWrite
  sandbox/         Sandbox protocol + a local filesystem implementation
  store/           ConversationStore protocol + in-memory and Postgres
  runtime/         api.py, worker.py, queue.py, ratelimit.py
  cli.py           single-process REPL, no infra required
schema.sql         Postgres tables
tests/             41 tests: loop, caps, tenancy, resumability, provider swap
```

## Run it

### Locally, no infrastructure

```bash
cd harness
pip install -e '.[dev]'
cp persona.example.json persona.json     # then fill it in — see below
export ANTHROPIC_API_KEY=sk-...
python -m twin.cli --persona persona.json
```

This uses `InMemoryStore` and `LocalSandbox` but the *same* `run_harness()`
that production uses. If behaviour differs between the CLI and the API, the
difference is infrastructure, not the loop.

### With Groq, Ollama, vLLM, or any OpenAI-protocol endpoint

```bash
pip install -e '.[openai]'
export GROQ_API_KEY=gsk_...
python -m twin.cli --persona persona.json \
  --base-url groq --model llama-3.3-70b-versatile
```

Shorthands: `groq`, `openrouter`, `together`, `ollama`, `vllm`, `lmstudio`, or a
full URL. Same via env for the workers: `TWIN_BASE_URL`, `TWIN_MODEL`,
`TWIN_API_KEY`.

Three differences to know about, all of them real:

- **No prompt caching.** The protocol has no equivalent, so your persona prefix
  is re-billed every turn instead of costing ~0.1×. On Groq that's cheap; on a
  paid non-Anthropic API it isn't.
- **Set `TWIN_MODEL_PRICE="<in>,<out>"`** (USD per 1M tokens) or the spend cap
  cannot fire — an unpriced model is costed at zero. Iteration and wall-clock
  caps still bound the run.
- **Tool-calling reliability is the real risk.** The adapter handles malformed
  JSON arguments by passing `{}` so the tool returns an error the model can see
  and correct, rather than crashing the run. But a model that loops, forgets it
  already read a file, or invents tool names will do that here too. The harness
  makes that visible and bounded; it can't make a weaker model reliable.

### Production

```bash
psql "$TWIN_DATABASE_URL" -f schema.sql

export TWIN_DATABASE_URL=postgres://...
export TWIN_REDIS_URL=redis://...
export ANTHROPIC_API_KEY=sk-...

uvicorn twin.runtime.api:build_default_app --factory --workers 4
python -m twin.runtime.worker          # run several; they self-balance
```

Workers pull from a Redis stream consumer group, so scaling is just running
more of them. `WorkerConfig.max_concurrent_runs` (default 8) × worker count is
your concurrency ceiling; 8 workers covers 50+ users comfortably, since users
are not all mid-run at the same instant.

### Tests

```bash
pytest                      # normal, 41 tests
python3 dev/minirunner.py   # fallback where pytest cannot be installed
```

## The persona

`persona.example.json` is a template. Fill it with **15–20 of your own real
messages, verbatim** — not a description of how you write. Cover both
registers: casual banter and explaining something technical. Don't clean them
up; the typos and the code-switching are the signal. If the voice is off, add
samples. Adding instructions *about* your style instead is the common mistake
and it does not work as well.

Samples live in the cached system prefix, so they cost ~0.1× after the first
turn of a session.

## Swap points

| Want to change | Touch only |
|---|---|
| Sandbox backend (E2B, Modal, Managed Agents) | `sandbox/`, implement `SandboxFactory` |
| Storage | `store/`, implement `ConversationStore` |
| Model / provider | `TWIN_BASE_URL`; new protocols go in `llm/`, chosen in `llm/factory.py` |
| Add a tool | `tools/`, register in `default_registry()` **at the end** |

Registration order is part of the cached prefix. Inserting a tool in the middle
of the list silently destroys every downstream cache hit.

## Before you deploy

Three things are deliberately unfinished, because a plausible-looking default
for any of them is worse than an error:

1. **`authenticate()` in `twin/runtime/api.py` raises `NotImplementedError`.**
   Wire it to your identity provider. It maps an `Authorization` header to a
   `user_id`; every tenancy check downstream depends on that being right.
2. **`LocalSandbox` is a correctness boundary, not a security boundary.** It
   blocks path traversal and symlink escapes, and runs commands with a minimal
   environment in their own process group. It does *not* contain hostile code.
   Before running untrusted input from multiple tenants, lease real containers
   behind the same `SandboxFactory` interface.
3. **Secrets must not enter the sandbox.** Any tool needing credentials should
   execute host-side. An agent that reads untrusted files is directly exposed
   to prompt injection, and a model-visible secret is an exfiltratable secret.

## Verification checklist

1. **Voice** — five casual messages sound like you.
2. **Loop** — "create notes.md with three bullets, then read it back" in one
   turn, no nudging.
3. **Parallel tools** — ask for three files at once; all three results come
   back in a single user message and it still parallelises next turn.
4. **Resumability** — `kill -9` a worker mid-run. Another worker reclaims it
   and it completes. (Covered by `test_run_resumes_after_a_worker_dies`.)
5. **Cache** (Anthropic only) — after two turns `usage.cache_read_input_tokens`
   is non-zero. Zero means something volatile leaked into the system prefix.
   On an OpenAI-protocol endpoint it is always zero by design.
6. **Isolation** — user A requests user B's run and gets 404, and still gets
   404 with the system prompt removed entirely.
7. **Runaway** — each of the iteration, time, and spend caps halts a run
   independently, with the other two left slack.
8. **Load** — 50 concurrent runs: watch queue depth and sandbox count, not
   response time. Success is bounded queue depth and no orphaned sandboxes.
9. **Compaction** — drive a run past the context threshold; it continues
   coherently, keeping the persona and the original task.

Items 4, 6, 7, and 9 have tests. The rest need a real key and real load.
