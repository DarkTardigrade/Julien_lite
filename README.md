# Julien Lite
*This project was co-authored with Claude Code. I had the idea and wrote a
significant amount of the code myself; Claude helped catch issues, 
find bugs, and wrote most of the README and commit messages.*

*Warning, this code has gone through very few testing as of this point*

A self-contained, portable AI agent with persistent memory. Drop `main.py` and `tools.py` into any project, instantiate `Julien`, and it creates and manages its own SQLite memory database right beside the folder. Multiple independent instances can run in the same process without sharing memory.

---

## How it works

Each `Julien` instance runs an **agentic loop**: on every call to `Msg`, the model receives its system prompt, the full conversation history, and a list of tools. It keeps calling tools — searching the web, reading and writing memory — until it calls `sendUser` (or `done`), which ends the turn. As a safety net, the loop is capped at `Julien.MAX_TURNS` (currently `10`) — on the final turn, tools are taken away entirely so the model is forced to produce a plain-text reply instead of silently running out of turns.

Long-term memory is handled by [LivingMemory](https://github.com/DarkTardigrade/LivingMemory). Conversation turns are stored under the `"conv"` tag. Before every model call, `cleanCov()` checks whether `conv + sys_msg` fits the context budget; if not, it backs the whole conversation up into existing topic tags, then trims `conv` down in stages (keeping the newest 40, then 30, 20, 10, 5, 2, and finally wiping it entirely if nothing else fits) — trying to preserve as much recent context as it can before resorting to a full wipe. Each topic tag is compressed by a local AI model whenever it grows too large.

---

## Requirements

- Python 3.9+
- [Ollama](https://ollama.com) running locally with your chosen model pulled
- [LivingMemory](https://github.com/DarkTardigrade/LivingMemory) — declared as a pinned git dependency in `pyproject.toml`, along with the other Python dependencies (`ollama`, `rich`, `duckduckgo-search`, `trafilatura`).

```bash
pip install -e .
```

---

## Installation

Install from source:

```bash
git clone https://github.com/DarkTardigrade/Julien_lite.git
cd Julien_lite
pip install .
```

> **Not yet published to PyPI** — `pip install Julien_lite` will **not** work. Install from source as shown above.

---

## Quick start

```python
from main import Julien

j = Julien(julienModel="qwen3:14b")
response = j.Msg("Hello!")
print(response)

j.saveMem()  # flush conversation to long-term memory on exit
```

---

## API reference

### Constructor

```python
Julien(
    julienModel   = "qwen3:14b",   # required — no default
    memModel      = None,          # falls back to julienModel if omitted
    contextWindow = 2048,
    DB_PATH       = "<beside main.py>/JulienMemory.db",
    timeout       = 180,
    sys_msg       = "...",
    autoTags      = [],
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `julienModel` | `str` | *required* | Model used for conversation |
| `memModel` | `str` | `None` (falls back to `julienModel`) | Model used for memory compression |
| `contextWindow` | `int` | `2048` | Token budget — must match the `num_ctx` Ollama is using |
| `DB_PATH` | `str` | beside `main.py` | Path to the SQLite memory database |
| `timeout` | `int` | `180` | Ollama client timeout in seconds |
| `sys_msg` | `str` | built-in prompt | Julien's system prompt |
| `autoTags` | `list` | `[]` | Memory categories to create on first run (safe to include every startup) |

**`contextWindow`** controls when conversation history is flushed to long-term memory. It must match the `num_ctx` value Ollama is actually using, otherwise the budget math will be wrong.

Common values for `qwen3:14b`:
- `2048` — Ollama default (no config needed)
- `~40000` — set `OLLAMA_CONTEXT_LENGTH=40000` before starting Ollama
- `131072` — requires a YaRN Modelfile (see [Extended context](#extended-context))

**`sys_msg` size limits** are enforced at startup:
- Over `contextWindow // 8` → `WARNING` log, continues normally
- Over `contextWindow // 2` → raises `ValueError`, does not start

**`autoTags`** accepts plain strings or dicts with `name` and `desc`. Tags are only created if they don't already exist:

```python
autoTags=[
    {"name": "About The User", "desc": "Facts about the person Julien talks to"},
    {"name": "Ongoing Projects", "desc": "Work and projects the user is involved in"},
]
```

---

### Public methods

#### `Msg(user_msg: str) -> str`

Send a message and get a response. Runs the full agentic loop — tool calls, memory reads, and web searches happen internally. Returns the final reply as a plain string, or `""` if the model never produced one (including on the forced final turn).

| Parameter | Type | Description |
|-----------|------|-------------|
| `user_msg` | `str` | The user's message |

**Returns:** `str` — the model's final reply to the user.

---

#### `saveMem() -> None`

Flushes the current conversation into every existing long-term memory tag, then compresses any tag that's over budget. Call this on graceful shutdown. If no memory tags exist yet, the flush is skipped (nothing to file into) and `conv` is left alone rather than being wiped with nowhere for it to go.

If the process is hard-killed, the current conversation stays in the `"conv"` tag and is picked up automatically next session (it is trimmed automatically once it grows too large, via `cleanCov()`).

---

## Tools

These are the tools available to Julien during the agentic loop. They are defined in `tools.py`. None of their results are returned to the caller — they're written straight into the conversation so Julien can see and act on them, but only `sendUser` (or the forced final-turn reply, or an unrecoverable error) actually produces the string `Msg` returns.

| Tool | Description |
|------|-------------|
| `sendUser` | Sends the final reply to the user and ends the turn. |
| `done` | Ends the turn with no reply, when nothing more needs to be said. |
| `think` | Writes a private thought straight into the conversation — visible to Julien next turn, never shown to the user. |
| `memorize` | Reads long-term memory. Call without `category` to browse tag names, then again with `category` to read one. |
| `remember` | Writes new information into a memory category. If `tag_name` matches an existing category, it's added there; if not, a new category is created on the spot using `desc`. |
| `GoogleSearch` | DuckDuckGo search. Rate-limited to one request per 2 seconds, shared across all instances. Fetches full page content for the top 3 results. |

### Adding a new tool

Two additions to `tools.py` are required:

1. A schema entry in the `tools` list (sent to the model)
2. A backend function and a corresponding `elif` branch in `_Dispatch`

`_Dispatch` signature: `_Dispatch(mem, table, name, args=None)`. It returns `None` for a tool that succeeded (any result is already written into `conv` inside the branch itself), or a string for a genuinely unrecognized tool name. `main.py`'s `_runTool()` is what actually decides whether a turn stops — it checks `name` directly for `"sendUser"`/`"done"`, and also catches any exception `_Dispatch` raises (e.g. missing/malformed args) and treats that as a stop too, surfacing the error text as the turn's output instead of crashing or retrying silently.

---

## Logging

Uses Python's standard `logging` module under the name `"Julien"`. **Not silent by default** — `main.py` calls `logging.basicConfig(level=logging.INFO, ...)` itself at import time, so INFO-level logs go to stderr as soon as you `import main`, unless your host application configures logging (adds a handler to the root logger) first.

```python
# More detail during development
import logging
logging.getLogger("Julien").setLevel(logging.DEBUG)

# Attach a custom handler for UI integration
logging.getLogger("Julien").addHandler(your_handler)
```

| Level | What is logged |
|-------|---------------|
| `DEBUG` | Turn-by-turn loop activity, raw model output, tool calls and results |
| `INFO` | `saveMem` lifecycle events (via LivingMemory's `cleanAll`/`cleanTag`) |
| `WARNING` | `sys_msg` over the soft token budget, failed tool calls |

---

## Extended context

To use 128k context with `qwen3:14b`, create a custom Modelfile once:

```
FROM qwen3:14b
PARAMETER num_ctx 131072
PARAMETER rope_freq_base 1000000
PARAMETER rope_freq_scale 0.5
```

```bash
ollama create qwen3-big -f Modelfile
ollama serve  # start with OLLAMA_CONTEXT_LENGTH=131072
```

Then instantiate with:

```python
Julien(julienModel="qwen3-big", contextWindow=131072)
```

---

## Key behaviours

- **Text-parsed tool calls** — `qwen3:14b` sometimes writes tool calls as plain JSON in the content field instead of using Ollama's structured `tool_calls`. `_parseTextToolCall()` catches these by scanning for `{"name": ..., "arguments": ...}` using brace-depth tracking.
- **`<think>` blocks** — `qwen3:14b` outputs `<think>...</think>` chain-of-thought blocks as part of its content. These appear in `Raw content` debug logs and are normal.
- **History rebuilt each turn** — conversation history is fetched from the database on every loop iteration. There is no in-memory message list.
- **No separate "thinking" tag** — tool results, thoughts, and search replies all go straight into `conv`, which is what makes them visible to Julien on the next turn.
- **Turn cap with a forced reply** — `Msg` calls `_Brain()` up to `MAX_TURNS` times; on the last one, tools are withheld so the model must answer in plain text rather than exhausting the loop with nothing to show for it.
- **`sys_msg` always rewritten** — the system prompt is deleted and rewritten from the constructor argument on every startup, so prompt edits take effect immediately without clearing the database.
- **LivingMemory version is pinned, not auto-updated** — `pyproject.toml` pins an exact LivingMemory tag, and `main.py` checks the installed version against `MIN_LIVINGMEMORY_VERSION` at import time, raising a clear `ImportError` (with an upgrade command) if it's too old. To move to a newer LivingMemory, bump both the pin and `MIN_LIVINGMEMORY_VERSION` together, then `pip install --upgrade -e .`.
- **Multiple instances** — each instance gets its own `DB_PATH` and `self.TABLE = "Julien"`. Two instances sharing the same `DB_PATH` would share the same table and corrupt each other's memory; use distinct paths.

---

## License

MIT
