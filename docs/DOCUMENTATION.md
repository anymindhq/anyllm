# anyllm — Complete Project Documentation

> *Git for LLM context. Snapshot a dying session, brief the next LLM in 30 seconds.*

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [The Problem It Solves](#2-the-problem-it-solves)
3. [Quick Start](#3-quick-start)
4. [CLI Commands Reference](#4-cli-commands-reference)
5. [Architecture](#5-architecture)
   - [Pipeline Overview](#51-pipeline-overview)
   - [Stage 1 — Ingestor](#52-stage-1--ingestor)
   - [Stage 2 — Distiller](#53-stage-2--distiller)
   - [Stage 3 — Storage](#54-stage-3--storage)
   - [Stage 4 — Composer](#55-stage-4--composer)
   - [Stage 5 — Adapter](#56-stage-5--adapter)
6. [File & Directory Structure](#6-file--directory-structure)
7. [Source File Breakdown](#7-source-file-breakdown)
   - [cli.py](#71-clipy)
   - [config.py](#72-configpy)
   - [storage.py](#73-storagepy)
   - [composer.py](#74-composerpy)
   - [ingestors/base.py](#75-ingestorsbasepy)
   - [ingestors/claude_code.py](#76-ingestorsclaude_codepy)
   - [ingestors/__init__.py](#77-ingestors__init__py)
   - [distiller/distiller.py](#78-distillerdistillerpy)
   - [distiller/prompts/v1.md](#79-distillerpromptsv1md)
   - [distiller/__init__.py](#710-distiller__init__py)
   - [adapters/base.py](#711-adaptersbasepy)
   - [adapters/chatgpt.py](#712-adapterschatgptpy)
   - [adapters/__init__.py](#713-adapters__init__py)
8. [The .anyllm/ Data Directory](#8-the-anyllm-data-directory)
9. [The Snapshot Format (`.anyllm` v0.1)](#9-the-snapshot-format-anyllm-v01)
10. [Key Data Flows](#10-key-data-flows)
    - [anyllm pack flow](#101-anyllm-pack-flow)
    - [anyllm prime flow](#102-anyllm-prime-flow)
11. [Configuration Reference](#11-configuration-reference)
12. [Design Principles](#12-design-principles)
13. [Tech Stack & Dependencies](#13-tech-stack--dependencies)
14. [Extension Points (Roadmap)](#14-extension-points-roadmap)
15. [Comparison to Other Tools](#15-comparison-to-other-tools)

---

## 1. Project Overview

**anyllm** (version `0.1.0`) is a local-first, open-source Python CLI that solves the **LLM session handoff problem**. When you're deep in a coding session with one AI tool (e.g. Claude Code) and need to switch to another (e.g. ChatGPT) — because credits ran out, the context window filled, or you want a second opinion — you normally spend 10–30 minutes re-explaining the full context to the new session.

`anyllm` eliminates that tax:

1. **`anyllm pack`** — reads your last LLM session, sends the transcript to Claude Sonnet, and produces a compressed, instructional *snapshot* in `.anyllm/current.md`.
2. **`anyllm prime --target chatgpt`** — wraps that snapshot in role framing, anti-repetition guards, and confidence flags, then renders a markdown briefing you can paste directly into any other LLM.

Everything is stored locally as plain markdown and JSON. No cloud. No database. No vendor lock-in.

---

## 2. The Problem It Solves

You are mid-task in an LLM coding session. One of these happens:
- **Context window fills up** — the model starts forgetting earlier decisions.
- **Credits/quota expire** — you switch providers immediately.
- **Provider outage** — you need a fallback, fast.
- **Second opinion** — you want to cross-check with a different model.

Without `anyllm`, the *re-briefing tax* is painful:  
→ Re-explain the project, the goal, what worked, what failed, all the architectural decisions made so far.  
→ Hope the new LLM doesn't re-ask questions you've already answered or re-implement code that's already done.

`anyllm` solves this with a 3-step flow:

```
anyllm pack  →  anyllm prime --target chatgpt --copy  →  paste into new session
```

The new LLM gets a compact, instructional briefing that tells it what the task is, what's done, what to avoid, and exactly what to do first.

---

## 3. Quick Start

**Prerequisites:** Python 3.10+, optionally an `ANTHROPIC_API_KEY`.

```bash
# 1. Install
python3 -m venv .venv
.venv/Scripts/pip install -e .        # Windows
# or: .venv/bin/pip install -e .      # Mac/Linux

# 2. Set API key (optional but recommended)
set ANTHROPIC_API_KEY=sk-ant-...      # Windows
# or: export ANTHROPIC_API_KEY=...    # Mac/Linux

# 3. Initialize anyllm in your project
cd your-project
anyllm init

# 4. After finishing a Claude Code session, pack it
anyllm pack

# 5. Generate a briefing for the next LLM
anyllm prime --target chatgpt --copy     # copies to clipboard
# Paste into ChatGPT and keep working!
```

> **Without an API key:** `anyllm pack` runs in *offline fallback mode* — it captures the transcript but produces a skeleton snapshot with all sections marked as low-confidence. Run with the key set to get a real distilled briefing.

---

## 4. CLI Commands Reference

All commands are exposed via the `anyllm` entry point (defined in `pyproject.toml`).

| Command | Description |
|---|---|
| `anyllm init` | Create a `.anyllm/` directory in the current project. Writes `config.yaml` with defaults. |
| `anyllm pack [--source claude-code] [--session <id>]` | Ingest the most recent (or specified) LLM session, distill it via Claude Sonnet, and write `current.md`. |
| `anyllm prime [--target chatgpt] [--copy] [--write PATH]` | Read `current.md`, wrap in briefing framing, render for the target LLM, and output to stdout / clipboard / file. |
| `anyllm status` | Show a summary of the current snapshot: project, date, distiller model, turn/token counts, Task, Status, Next step, and Confidence Report. |
| `anyllm log` | Print a Rich-formatted table of all sessions packed into this project (from `index.json`). |
| `anyllm diff <session-id>` | Print the raw snapshot markdown for one historical session. |
| `anyllm --version` | Show the installed version and exit. |

### `anyllm pack` options

| Flag | Default | Description |
|---|---|---|
| `--source` / `-s` | `claude-code` | Which ingestor to use. Currently only `claude-code` is implemented. |
| `--session` | *(most recent)* | Ingest a specific session by its UUID instead of the latest one. |

### `anyllm prime` options

| Flag | Default | Description |
|---|---|---|
| `--target` / `-t` | value from `config.yaml` | Which adapter to render for (`chatgpt`). |
| `--copy` | `False` | Copy the rendered primer to the clipboard (via `pyperclip`). |
| `--write PATH` | `None` | Write the primer to a file instead of stdout. |

---

## 5. Architecture

### 5.1 Pipeline Overview

`anyllm` implements a strict **5-stage linear pipeline**. Each stage has exactly one responsibility and a clean interface. Adding a new source or target only requires adding one new file in the right directory — the middle three stages never change.

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  Ingestor   │───▶│  Distiller  │───▶│   Storage   │───▶│  Composer   │───▶│   Adapter   │
│ (per source)│    │   (LLM)     │    │   (.anyllm/)│    │ (framing)   │    │ (per target)│
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
  raw JSONL     → NormalizedTranscript → snapshot.md   → briefing dict   → primer string
```

| Stage | Input | Output | Extensible? |
|---|---|---|---|
| Ingestor | Source-specific raw files | `NormalizedTranscript` | ✅ Add new ingestor class |
| Distiller | `NormalizedTranscript` dict + token budget | Snapshot markdown string | ⚙️ Swap model / edit prompt |
| Storage | Snapshot string + transcript dict | Files written to `.anyllm/` | — |
| Composer | `Snapshot` dataclass | Briefing `dict` | — |
| Adapter | Briefing `dict` | Primer `str` | ✅ Add new adapter class |

---

### 5.2 Stage 1 — Ingestor

**Location:** `src/anyllm/ingestors/`  
**Job:** Read raw session data from one specific source and normalize it into a `NormalizedTranscript`.

The `Ingestor` is a Python Protocol (structural interface):

```python
class Ingestor(Protocol):
    name: str
    def latest_session(self, project_root: Path) -> NormalizedTranscript | None: ...
```

**MVP implementation: `ClaudeCodeIngestor`**

Claude Code stores session transcripts as JSONL files at:
```
~/.claude/projects/<project-slug>/<session-uuid>.jsonl
```

Where `<project-slug>` is the project's absolute path with `/`, `\`, and `:` replaced by `-`:
- Linux: `/home/user/myproject` → `-home-user-myproject`
- Windows: `C:\Users\foo\myproject` → `C--Users-foo-myproject`

The ingestor:
1. Computes the project slug from the current working directory.
2. Lists all `.jsonl` files in that slug's directory, sorted by modification time.
3. Parses the most recent JSONL line-by-line into turns, extracting:
   - Role (`user` / `assistant`)
   - Plain text content
   - Tool calls (Edit, Write, Read, MultiEdit, NotebookEdit) → files touched
   - Timestamps for `started_at` / `ended_at`
   - Token usage counts
   - Model name

**Output — `NormalizedTranscript`:**
```python
@dataclass
class NormalizedTranscript:
    source: str           # "claude-code"
    session_id: str       # UUID from the JSONL filename
    started_at: str       # ISO timestamp of first message
    ended_at: str         # ISO timestamp of last message
    turns: list[dict]     # [{role, text, ts, tool_calls?}, ...]
    files_touched: list[str]  # deduplicated list of file paths from tool calls
    metadata: dict        # {model, token_count, source_path}
```

---

### 5.3 Stage 2 — Distiller

**Location:** `src/anyllm/distiller/`  
**Job:** Compress the `NormalizedTranscript` into a compact, instructional snapshot markdown string using an LLM call.

The `Distiller` class:
1. Loads the versioned system prompt from `prompts/v1.md`.
2. Builds a user message containing session metadata, YAML frontmatter to copy verbatim, and the entire turn transcript (soft-capped at 180,000 characters to avoid crushing the context window).
3. Calls `anthropic.messages.create()` with `claude-sonnet-4-6` (configurable).
4. If the model response doesn't start with `---` (YAML frontmatter), it splices the frontmatter on programmatically.
5. If no API key is set or `anthropic` is not installed, falls back to an *offline skeleton snapshot* with all sections marked `low`.

**Distiller prompt (v1.md):** A carefully engineered system prompt that enforces:
- **Instructional over descriptive** writing — for the next LLM, not a human recap.
- **Token budget discipline** — drop detail before padding.
- **Per-section confidence rating** — `high / medium / low`.
- **No invented facts** — if the transcript doesn't say it, it goes in "Could not determine".
- **Resumption fidelity** — the single most important output is: *what to do first, what not to redo*.

**Offline fallback:** If `ANTHROPIC_API_KEY` is not set, the distiller still produces a valid snapshot file with the correct structure, but every section carries `_conf: low_` and a notice to re-run with the API key.

---

### 5.4 Stage 3 — Storage

**Location:** `src/anyllm/storage.py`  
**Job:** Write and read all files in the `.anyllm/` data directory.

The `Paths` dataclass encapsulates all file paths relative to the project root:

| Property | Path |
|---|---|
| `anyllm_dir` | `.anyllm/` |
| `sessions_dir` | `.anyllm/sessions/` |
| `index_path` | `.anyllm/index.json` |
| `current_path` | `.anyllm/current.md` |
| `config_path` | `.anyllm/config.yaml` |

Key functions:

| Function | Description |
|---|---|
| `find_project_root()` | Walks up the directory tree from CWD looking for a `.anyllm/` directory. Falls back to CWD. |
| `init_project(root)` | Creates `.anyllm/` and `sessions/`, initializes `index.json` with `{"sessions": []}`. |
| `ensure_initialized(paths)` | Raises `RuntimeError` if `.anyllm/` doesn't exist (tells user to run `anyllm init`). |
| `write_transcript(paths, transcript)` | Writes `sessions/<date>-<id>.transcript.json`. |
| `write_snapshot(paths, transcript, snapshot_md)` | Writes `sessions/<date>-<id>.snapshot.md`. |
| `write_current(paths, snapshot_md)` | Overwrites `.anyllm/current.md` with the latest snapshot. |
| `append_index_entry(paths, entry)` | Upserts session metadata into `index.json` (deduplicates by `source` + `session_id`). |
| `load_index(paths)` | Returns `index.json` as a dict. Returns `{"sessions": []}` if file doesn't exist. |

Session filenames are formatted as `<YYYY-MM-DD>-<session-uuid>` for human-readable sorting.

---

### 5.5 Stage 4 — Composer

**Location:** `src/anyllm/composer.py`  
**Job:** Parse the snapshot markdown and wrap it in adapter-agnostic instructional framing.

**`parse_snapshot(md: str) -> Snapshot`**
- Extracts YAML frontmatter (between `---` delimiters) using PyYAML.
- Splits the body on `# Heading` lines into a `sections` dict.
- Returns a `Snapshot(frontmatter={...}, sections={"Task": "...", "Status": "...", ...})`.

**`compose(snapshot, *, target, extra_rules, tone) -> dict`**
- Adds a `role_preamble`: a paragraph telling the next LLM it is continuing an interrupted task and must use the briefing.
- Adds `anti_repetition` guard rules (do not restart, do not re-implement done parts, do not re-ask settled questions, do not retry failed approaches).
- Reads the `Confidence Report` section to extract any low-confidence sections and inserts a `verification_hooks` warning naming them.
- Merges `extra_rules` from `config.yaml`.
- Returns a flat `briefing` dict containing all of the above plus the parsed sections — ready for any adapter to render.

The composer is **adapter-agnostic**: it produces one canonical representation; adapters handle the final rendering shape per target LLM.

---

### 5.6 Stage 5 — Adapter

**Location:** `src/anyllm/adapters/`  
**Job:** Render the briefing dict into the final primer string for one specific target LLM.

The `Adapter` is a Python Protocol:

```python
class Adapter(Protocol):
    name: str
    def render(self, briefing: dict[str, Any]) -> str: ...
```

**MVP implementation: `ChatGPTAdapter`**

Renders a clean, markdown-formatted primer optimized for ChatGPT's quirks:
- **Shorter, structured** primers (avoids long XML-ish blobs).
- **Explicit role framing** at the top.
- Clear `## Ground rules` section with all anti-repetition and verification rules.
- Sections in a logical read order: Task → Status → Decisions → Code map → Tried & failed → Open questions → Confidence Report → **Your task right now**.
- Closes with an instruction to confirm which file/decision it'll touch first before proceeding.

**Future adapters (planned):**
- `claude` — `MEMORY.md`-shaped output with XML tags.
- `cursor` — `.cursorrules`-style file respecting size limits.
- `generic` — plain text for any web LLM.

---

## 6. File & Directory Structure

```
anyllm/                                  ← project root
├── .anyllm/                             ← local data store (created by anyllm init)
│   ├── config.yaml                   ← project-level config (model, budget, target, tone)
│   ├── index.json                    ← session log (all packed sessions' metadata)
│   ├── current.md                    ← the active snapshot (anyllm prime reads this)
│   └── sessions/                     ← per-session archives
│       ├── 2026-04-19-<uuid>.transcript.json   ← raw normalized transcript
│       └── 2026-04-19-<uuid>.snapshot.md       ← distilled snapshot
│
├── src/
│   └── anyllm/                          ← Python package root
│       ├── __init__.py               ← exposes __version__ = "0.1.0"
│       ├── cli.py                    ← Typer app, all 6 CLI commands
│       ├── config.py                 ← Config dataclass + YAML load/write
│       ├── storage.py                ← Paths dataclass + all file I/O helpers
│       ├── composer.py               ← parse_snapshot() + compose() functions
│       │
│       ├── ingestors/
│       │   ├── __init__.py           ← INGESTORS registry dict
│       │   ├── base.py               ← NormalizedTranscript dataclass + Ingestor Protocol
│       │   └── claude_code.py        ← ClaudeCodeIngestor (reads ~/.claude/projects/)
│       │
│       ├── distiller/
│       │   ├── __init__.py           ← re-exports Distiller, DistillerError
│       │   ├── distiller.py          ← Distiller class + offline fallback logic
│       │   └── prompts/
│       │       └── v1.md             ← versioned system prompt for the distiller LLM call
│       │
│       └── adapters/
│           ├── __init__.py           ← ADAPTERS registry dict
│           ├── base.py               ← Adapter Protocol
│           └── chatgpt.py            ← ChatGPTAdapter (markdown primer renderer)
│
├── pyproject.toml                    ← package metadata, dependencies, entry point
├── README.md                         ← user-facing quickstart
├── architechure.md                   ← detailed design document / spec
├── DOCUMENTATION.md                  ← this file
└── .gitignore                        ← excludes .venv, sessions/, current.md, index.json
```

---

## 7. Source File Breakdown

### 7.1 `cli.py`

**Path:** `src/anyllm/cli.py`  
**Size:** ~314 lines  
**Role:** Entry point for all CLI commands. Wires the pipeline together.

This is the only file that imports from all other modules. It contains:

- **`app`** — the `typer.Typer` instance registered as the `anyllm` console script.
- **Windows UTF-8 fix** — reconfigures `stdout`/`stderr` to UTF-8 at import time so Rich renders unicode characters cleanly on Windows (which defaults to `cp1252`).
- **`_paths()`** — helper that calls `find_project_root()` to locate the `.anyllm/` dir from any subdirectory and returns a `Paths` instance.
- **`init()`** — creates `.anyllm/` and writes default `config.yaml`.
- **`pack(source, session_id)`** — full pack pipeline:
  1. Looks up the ingestor class from the `INGESTORS` registry.
  2. Calls `latest_session()` or `session_by_id()`.
  3. Writes the transcript JSON.
  4. Constructs a `Distiller` and calls `distill()`.
  5. Writes the snapshot and updates `current.md`.
  6. Appends the metadata entry to `index.json`.
- **`prime(target, copy, write)`** — reads `current.md`, calls `parse_snapshot()` + `compose()`, instantiates the adapter, renders the primer; outputs to stdout, clipboard, or file.
- **`status()`** — shows frontmatter metadata and Task / Status / Next step / Confidence Report from `current.md`.
- **`log_cmd()`** — renders a Rich `Table` of all entries in `index.json`.
- **`diff(session_id)`** — looks up the session in `index.json`, finds the snapshot file, and prints its raw content.

---

### 7.2 `config.py`

**Path:** `src/anyllm/config.py`  
**Size:** 58 lines  
**Role:** Load and write project-level configuration from `.anyllm/config.yaml`.

```python
@dataclass
class Config:
    distiller_model: str = "claude-sonnet-4-6"
    budget_tokens: int = 2000
    default_target: str = "chatgpt"
    extra_rules: list[str] = field(default_factory=list)
    tone: str = "direct"
```

- **`Config.load(anyllm_dir)`** — reads `config.yaml` via PyYAML; returns a `Config` with defaults for any missing keys. Gracefully handles missing files.
- **`Config.write_default(anyllm_dir)`** — writes the default YAML structure when `anyllm init` creates a fresh project.

Default config written on `anyllm init`:
```yaml
distiller:
  model: claude-sonnet-4-6
  budget_tokens: 2000
targets:
  default: chatgpt
framing:
  extra_rules: []
  tone: direct
```

---

### 7.3 `storage.py`

**Path:** `src/anyllm/storage.py`  
**Size:** 112 lines  
**Role:** All filesystem I/O. No business logic; pure path resolution and file reads/writes.

Key design: the `Paths` dataclass is the single source of truth for where every file lives. Any component that needs to read or write a file must go through `Paths` — this makes it trivial to relocate the `.anyllm/` directory in the future.

The `find_project_root()` function walks up from CWD, so `anyllm` commands work from any subdirectory of a project that has been initialized.

`append_index_entry()` implements upsert semantics: if a session with the same `(source, session_id)` pair already exists in `index.json`, it is replaced rather than duplicated. This makes `anyllm pack` idempotent for the same session.

---

### 7.4 `composer.py`

**Path:** `src/anyllm/composer.py`  
**Size:** 132 lines  
**Role:** Parse the snapshot markdown and add instructional framing. This is the "editor" between raw distilled facts and the final rendered briefing.

**`Snapshot` dataclass:**
```python
@dataclass
class Snapshot:
    frontmatter: dict[str, Any]   # parsed YAML between --- delimiters
    sections: dict[str, str]      # {"Task": "...", "Status": "...", ...}
```

**`parse_snapshot(md)`:**
- Uses a regex to split YAML frontmatter from body.
- Iterates lines looking for `# Heading` patterns to split into sections.
- Handles snapshots with or without frontmatter.

**`compose(snapshot, *, target, extra_rules, tone)`:**
- Checks the `Confidence Report` section for any low-confidence sections and adds a specific verification warning.
- Adds 5 hard anti-repetition rules that every adapter renders.
- Passes `extra_rules` from `config.yaml` for user-customizable rules.
- Returns an adapter-agnostic `briefing` dict — adapters do rendering, not logic.

Defined `SECTION_ORDER = ["Task", "Status", "Decisions", "Code map", "Tried & failed", "Next step", "Open questions", "Confidence Report"]` — this canonical ordering ensures consistent rendering across all adapters.

---

### 7.5 `ingestors/base.py`

**Path:** `src/anyllm/ingestors/base.py`  
**Size:** 36 lines  
**Role:** Defines the `NormalizedTranscript` data model and the `Ingestor` Protocol.

`NormalizedTranscript.to_dict()` serializes to a plain dict for JSON storage, keeping the storage layer decoupled from the dataclass.

The `Ingestor` Protocol uses Python's structural typing — any class with `name: str` and `latest_session(project_root) -> NormalizedTranscript | None` satisfies it, without explicit inheritance. This makes adding new ingestors completely self-contained.

---

### 7.6 `ingestors/claude_code.py`

**Path:** `src/anyllm/ingestors/claude_code.py`  
**Size:** 152 lines  
**Role:** The only concrete ingestor in the MVP. Reads Claude Code's JSONL session files and produces a `NormalizedTranscript`.

**Key internals:**

| Function | Purpose |
|---|---|
| `_project_slug(root)` | Converts an absolute path to Claude Code's encoding (`/` → `-`, `\` → `-`, `:` → `-`). Handles both Unix and Windows paths. |
| `_flatten_content(content)` | Handles Claude's polymorphic `content` field — can be a string or a list of `{type: "text"}` / `{type: "tool_use"}` blocks. Extracts plain text and structured tool calls. |
| `_extract_files(tool_calls)` | Filters tool calls to `FILE_TOOLS = {Edit, Write, NotebookEdit, Read, MultiEdit}` and extracts `file_path` / `notebook_path` values. |
| `ClaudeCodeIngestor._session_files(root)` | Lists all JSONL files for this project, sorted by modification time. |
| `ClaudeCodeIngestor._normalize(jsonl_path)` | Main parsing loop — reads line-by-line, accumulates turns with timestamps, token counts, and touched files. Deduplicates `files_touched`. |
| `ClaudeCodeIngestor.session_by_id(root, id)` | Finds a specific session file by matching the filename stem to the UUID. |

The class stores `CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"` as a class-level constant, but it's injectable via the constructor for testing.

---

### 7.7 `ingestors/__init__.py`

**Path:** `src/anyllm/ingestors/__init__.py`  
**Size:** 9 lines  
**Role:** Registry and public API for the ingestors subpackage.

```python
INGESTORS: dict[str, type[Ingestor]] = {
    "claude-code": ClaudeCodeIngestor,
}
```

The CLI looks up the ingestor class by name from this registry. To add a new ingestor:
1. Create `ingestors/my_source.py` implementing the `Ingestor` Protocol.
2. Add `"my-source": MySourceIngestor` to `INGESTORS`.

---

### 7.8 `distiller/distiller.py`

**Path:** `src/anyllm/distiller/distiller.py`  
**Size:** 179 lines  
**Role:** The "brain" — makes the LLM API call that compresses the transcript into a structured snapshot.

**`_turns_to_text(turns, max_chars=180_000)`**  
Renders the turn list as plain text with role tags and timestamps. Tool calls are rendered as `<tool_calls>Name(input_summary)</tool_calls>`. Applies a soft 180k-character cap and appends a `[...truncated N more turns...]` notice when the transcript is very long.

**`_short_input(inp, limit=160)`**  
JSON-serializes tool input and truncates to 160 chars with a `…` suffix. Keeps the transcript compact while preserving information about what each tool call was doing.

**`Distiller.distill(transcript, project)`**  
Main method. Builds the YAML frontmatter and the user message (which includes the frontmatter to copy verbatim so the model can't reorder keys). Calls the Anthropic API and returns the raw markdown string.

**`Distiller._offline_snapshot(frontmatter, transcript)`**  
Offline fallback — produces a structurally valid snapshot with all sections marked `low` confidence and a `Next step` telling the user to set `ANTHROPIC_API_KEY` and re-run.

**`_yaml_frontmatter(data)`**  
Hand-rolled YAML serializer using `yaml.safe_dump(sort_keys=False)` to preserve key order in the snapshot frontmatter. Wrapped in `---` delimiters for the markdown format.

The Anthropic client is imported inside a `try/except ImportError` block at module level — making the distiller importable even without `anthropic` installed, which enables the offline fallback path.

---

### 7.9 `distiller/prompts/v1.md`

**Path:** `src/anyllm/distiller/prompts/v1.md`  
**Size:** 72 lines  
**Role:** The versioned system prompt for the distiller LLM call.

This is treated as a **versioned asset**, not throwaway code. The file version (`v1`) is embedded in the snapshot's YAML frontmatter (`prompt_version: v1`), making distillation reproducible — you always know which prompt produced which snapshot.

The prompt enforces:
- **Instructional output** — written for the next LLM, not as a human summary.
- **Token budget discipline** — explicitly told to drop content rather than waffle.
- **Confidence rating per section** — `high / medium / low`, no omissions.
- **No invented facts** — if uncertain, say so in "Could not determine", never fabricate.
- **Resumption fidelity** — *"Tried & failed"* section is called the "highest-leverage section" because it prevents loops in the next session.

The prompt includes a **template** with exact section headings and a **Guidance per section** block explaining what belongs in each one.

It is packaged with the distribution (`tool.setuptools.package-data` in `pyproject.toml`) so it's available at runtime regardless of install location.

---

### 7.10 `distiller/__init__.py`

**Path:** `src/anyllm/distiller/__init__.py`  
**Size:** 4 lines  
**Role:** Re-exports `Distiller` and `DistillerError` from the subpackage.

---

### 7.11 `adapters/base.py`

**Path:** `src/anyllm/adapters/base.py`  
**Size:** 12 lines  
**Role:** The `Adapter` Protocol — the structural interface all adapter classes must satisfy.

```python
class Adapter(Protocol):
    name: str
    def render(self, briefing: dict[str, Any]) -> str: ...
```

Adapters are pure renderers — no logic, no decisions. The Composer has already done all the reasoning; the adapter just templates the output for one specific LLM's preferences.

---

### 7.12 `adapters/chatgpt.py`

**Path:** `src/anyllm/adapters/chatgpt.py`  
**Size:** 83 lines  
**Role:** Renders the briefing dict as a copy-pasteable markdown primer tailored for ChatGPT.

**Rendering order:**
1. Title: `# Briefing: continuing work on \`{project}\``
2. Role preamble paragraph.
3. `## Ground rules` — all anti-repetition + verification_hooks + extra_rules as bullet points.
4. `## Task`
5. `## Status so far`
6. `## Decisions already made (respect these)`
7. `## Code map`
8. `## Tried & failed (do not redo)`
9. `## Open questions for the user`
10. `## Distiller confidence report`
11. `## Your task right now` — the `Next step` content, followed by an instruction to confirm the first file/decision before proceeding.

Sections are conditionally included — if a section is empty in the snapshot, it's omitted from the primer.

---

### 7.13 `adapters/__init__.py`

**Path:** `src/anyllm/adapters/__init__.py`  
**Size:** 9 lines  
**Role:** Registry and public API for the adapters subpackage.

```python
ADAPTERS: dict[str, type[Adapter]] = {
    "chatgpt": ChatGPTAdapter,
}
```

To add a new adapter:
1. Create `adapters/my_target.py` implementing the `Adapter` Protocol.
2. Add `"my-target": MyTargetAdapter` to `ADAPTERS`.

---

## 8. The `.anyllm/` Data Directory

Created by `anyllm init`. All files are plain text — hand-editable by the user, which is a core design principle.

### `config.yaml`
Project-specific settings. Hand-editable at any time.
```yaml
distiller:
  model: claude-sonnet-4-6      # which Anthropic model to use for distillation
  budget_tokens: 2000           # target output size for the snapshot (in tokens)
targets:
  default: chatgpt              # which adapter anyllm prime uses when --target is omitted
framing:
  extra_rules: []               # additional bullet points to include in every briefing
  tone: direct                  # passed to the composer (currently informational)
```

### `index.json`
An append-only log of every session packed. The `anyllm log` command renders this as a table.
```json
{
  "sessions": [
    {
      "source": "claude-code",
      "session_id": "c12eefd0-89ba-47c1-b61c-d4edb884ccfa",
      "started_at": "2026-04-19T21:11:16.997Z",
      "ended_at": "2026-04-19T21:29:43.987Z",
      "turn_count": 58,
      "token_count": 8564,
      "snapshot_path": ".anyllm\\sessions\\2026-04-19-<uuid>.snapshot.md",
      "transcript_path": ".anyllm\\sessions\\2026-04-19-<uuid>.transcript.json",
      "packed_at": "2026-04-19T21:30:16Z"
    }
  ]
}
```

### `current.md`
The canonical "what's going on right now" snapshot. This is what `anyllm prime` reads. It's overwritten by each `anyllm pack` call. In the MVP, it's a direct copy of the latest session snapshot; in a future version, it will be an LLM-assisted merge of all sessions.

### `sessions/<date>-<uuid>.transcript.json`
The full `NormalizedTranscript` dict serialized as JSON. Retained forever for `anyllm log` / `anyllm diff`. Not gitignored by default — the `.gitignore` only excludes `sessions/` to keep transcripts private, since they may contain code and secrets.

### `sessions/<date>-<uuid>.snapshot.md`
The distilled snapshot markdown for this session. Also retained forever. Used by `anyllm diff <session-id>`.

---

## 9. The Snapshot Format (`.anyllm` v0.1)

The snapshot is a plain markdown file with a YAML frontmatter header. It is the canonical data format of the entire project — the interface between the Distiller and everything downstream.

```markdown
---
anyllm_version: 0.1
project: myproject
generated_at: 2026-04-19T14:30:00Z
distilled_from:
  - source: claude-code
    session_id: abc123
    turn_count: 142
    token_count: 48230
budget_tokens: 2000
distiller_model: claude-sonnet-4-6
prompt_version: v1
---

# Task
<one paragraph: what the user is trying to accomplish>

# Status
<where things stand right now — done, in progress, blocked>

# Decisions
- <decision>. **Why:** <rationale>. _conf: high_
- <decision>. **Why:** <rationale>. _conf: medium_

# Code map
- `path/to/file.py` — <one line: what it does / what changed>

# Tried & failed
- <approach> — failed because <reason>. Don't redo.

# Next step
<one concrete action the next session should take first>

# Open questions
- <question that needs the user>

# Confidence Report
- Overall: medium
- High confidence: Task, Decisions, Next step
- Medium confidence: Code map
- Low confidence: none
- Omitted (budget): early debugging of legacy/old_auth.py
- Could not determine: whether backward compatibility with v1 tokens is required
```

**Key properties:**
- **Versioned** — `anyllm_version` and `prompt_version` allow the format to evolve without breaking old snapshots.
- **Markdown** — human-readable, hand-editable, diff-friendly.
- **Self-contained** — all information to resume a task is in one file.
- **Confidence-aware** — the `Confidence Report` section is mandatory and surfaced in every command output.

---

## 10. Key Data Flows

### 10.1 `anyllm pack` flow

```
anyllm pack
  │
  ├─ storage.find_project_root()            → locate .anyllm/
  ├─ Config.load(anyllm_dir)                   → read config.yaml
  ├─ INGESTORS["claude-code"]()             → instantiate ClaudeCodeIngestor
  ├─ ingestor.latest_session(project_root)  → NormalizedTranscript
  │     ├─ _project_slug(root)              → compute ~/.claude/projects/ subdir
  │     ├─ glob *.jsonl, sort by mtime       → most recent file
  │     └─ _normalize(jsonl_path)           → parse turns, extract files, count tokens
  │
  ├─ storage.write_transcript(paths, transcript.to_dict())
  │     → .anyllm/sessions/<date>-<uuid>.transcript.json
  │
  ├─ Distiller(model, budget_tokens)
  │     └─ distill(transcript, project)
  │           ├─ _load_prompt()             → prompts/v1.md
  │           ├─ _frontmatter(transcript)   → YAML metadata dict
  │           ├─ _user_message(...)         → header + frontmatter + turns text
  │           └─ anthropic.messages.create() → snapshot markdown string
  │
  ├─ storage.write_snapshot(paths, transcript, snapshot_md)
  │     → .anyllm/sessions/<date>-<uuid>.snapshot.md
  ├─ storage.write_current(paths, snapshot_md)
  │     → .anyllm/current.md  (overwrite)
  └─ storage.append_index_entry(paths, entry)
        → .anyllm/index.json  (upsert)
```

### 10.2 `anyllm prime` flow

```
anyllm prime --target chatgpt --copy
  │
  ├─ storage.find_project_root()            → locate .anyllm/
  ├─ Config.load(anyllm_dir)                   → read config.yaml (default_target, extra_rules, tone)
  ├─ paths.current_path.read_text()         → read .anyllm/current.md
  │
  ├─ composer.parse_snapshot(md)            → Snapshot(frontmatter, sections)
  │     ├─ regex extract YAML frontmatter
  │     └─ split body on # headings
  │
  ├─ composer.compose(snapshot, target, extra_rules, tone)  → briefing dict
  │     ├─ _low_confidence_sections(confidence_report)       → ["Code map"]
  │     ├─ role_preamble                                     → continuation framing
  │     ├─ anti_repetition                                   → 5 guard rules
  │     └─ verification_hooks                                → low-conf warnings
  │
  ├─ ADAPTERS["chatgpt"]().render(briefing)  → primer string
  │     └─ templates all sections into markdown
  │
  └─ pyperclip.copy(primer)                 → clipboard
     (or: typer.echo / path.write_text)
```

---

## 11. Configuration Reference

All configuration lives in `.anyllm/config.yaml`. It is created with defaults on `anyllm init` and can be edited manually at any time.

| Key | Default | Description |
|---|---|---|
| `distiller.model` | `claude-sonnet-4-6` | Anthropic model used for distillation. Any Anthropic model string is valid. |
| `distiller.budget_tokens` | `2000` | Target token count for the snapshot. The distiller prompt instructs the model to stay within this budget. |
| `targets.default` | `chatgpt` | Adapter used when `--target` is not specified. |
| `framing.extra_rules` | `[]` | Additional bullet-point rules appended to the `## Ground rules` section of every briefing. |
| `framing.tone` | `direct` | Tone preference passed to the composer (informational in MVP; hooks reserved for future use). |

---

## 12. Design Principles

These principles drive every design decision in `anyllm`. They're documented here because deviations from them are bugs, not features.

| Principle | Meaning |
|---|---|
| **Fidelity within budget** | Don't summarize until you compress. Set a token budget; maximize resumption fidelity within it. |
| **A briefing, not a summary** | Output is instructional — tells the next LLM what to do, what's done, what NOT to redo. |
| **Surface uncertainty** | Hidden confidence is how tooling silently lies. Every section has a confidence rating. |
| **Local-first** | No cloud. Transcripts may contain code and secrets. Everything stays on disk. |
| **Boring, hand-editable formats** | Snapshots are markdown. Users can fix distiller mistakes by hand. This is a feature, not a limitation. |
| **Cross-provider from day one** | The tool only matters if it works across Claude, ChatGPT, Cursor, etc. |

---

## 13. Tech Stack & Dependencies

| Component | Library | Version |
|---|---|---|
| CLI framework | `typer` | >=0.12 |
| Terminal rendering | `rich` | >=13.7 |
| YAML parsing | `pyyaml` | >=6.0 |
| LLM API (distillation) | `anthropic` | >=0.39 |
| Clipboard | `pyperclip` | >=1.8 |
| Testing | `pytest` | >=8.0 (dev only) |
| Python | — | >=3.10 |

**Build system:** `setuptools` with `pyproject.toml` (PEP 517/518 compliant).

**Entry point:** `anyllm = "anyllm.cli:app"` — the `anyllm` shell command maps to the `typer.Typer` app instance in `cli.py`.

**Package data:** `anyllm.distiller/prompts/*.md` is explicitly included in the distribution so `prompts/v1.md` is accessible at runtime after `pip install`.

---

## 14. Extension Points (Roadmap)

The architecture is explicitly designed for extension in two dimensions:

### Adding a new Ingestor (new source LLM)

1. Create `src/anyllm/ingestors/my_source.py`.
2. Implement the `Ingestor` Protocol:
   ```python
   class MySourceIngestor:
       name = "my-source"
       def latest_session(self, project_root: Path) -> NormalizedTranscript | None:
           ...
   ```
3. Add to `INGESTORS` in `ingestors/__init__.py`:
   ```python
   "my-source": MySourceIngestor,
   ```
4. Users can now run `anyllm pack --source my-source`.

**Planned ingestors:** `chatgpt` (export ZIPs), `cursor` (local SQLite), `clipboard` (paste-in fallback).

### Adding a new Adapter (new target LLM)

1. Create `src/anyllm/adapters/my_target.py`.
2. Implement the `Adapter` Protocol:
   ```python
   class MyTargetAdapter:
       name = "my-target"
       def render(self, briefing: dict[str, Any]) -> str:
           ...
   ```
3. Add to `ADAPTERS` in `adapters/__init__.py`:
   ```python
   "my-target": MyTargetAdapter,
   ```
4. Users can now run `anyllm prime --target my-target`.

**Planned adapters:** `claude` (MEMORY.md-shaped), `cursor` (.cursorrules), `generic` (plain text).

### Upgrading the Distiller Prompt

1. Create `src/anyllm/distiller/prompts/v2.md`.
2. Update `PROMPT_VERSION = "v2"` in `distiller.py`.
3. Old snapshots (with `prompt_version: v1`) remain interpretable since the format is versioned.

### Smart `current.md` Merge (v2)

Currently `anyllm pack` overwrites `current.md` with the latest snapshot. The planned upgrade is an LLM-assisted merge: `anyllm pack` reads the existing `current.md` plus the new session snapshot and produces a merged rolling project-level snapshot (superseding stale items, appending new ones) — like `git commit` accumulating a changelog.

---

## 15. Comparison to Other Tools

| Tool | Audience | Cross-provider | Open | Confidence-aware | Lightweight |
|---|---|---|---|---|---|
| mem0 | App developers | N/A (SDK) | Yes | No | Medium |
| Letta/MemGPT | App developers | N/A (SDK) | Yes | No | Heavy |
| Zep | App developers | N/A (SDK) | Partial | No | Heavy |
| Pieces | End-user devs | Some | No | No | Heavy |
| Claude MEMORY.md | Claude Code only | No | N/A | No | Yes |
| Cursor rules | Cursor only | No | N/A | No | Yes |
| **anyllm (this)** | **End-user devs** | **Yes (core goal)** | **Yes** | **Yes** | **Yes** |

The key differentiators are:

1. **Cross-provider portability** — the entire point of `anyllm` is moving context between different LLM tools, not staying within one ecosystem.
2. **Confidence-aware briefings** — every section in the snapshot is rated. Low-confidence claims are explicitly flagged so the next LLM knows where to verify rather than blindly trust.
3. **Open, boring format** — the `.anyllm` snapshot format is designed to potentially become a community standard, similar to how `.editorconfig` was adopted across tools.
4. **Lightweight and local** — no server, no database, no cloud dependencies. A `pip install` and an API key are all you need.

---

*Documentation generated for anyllm v0.1.0 — April 2026*
