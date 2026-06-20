# anyllm — Portable LLM Session Context

> *Git for LLM context.* Snapshot a dying session, brief the next model in 30 seconds, anywhere.

You researched the architecture in ChatGPT. Now you need Claude to write the code. Explaining it all over again wastes ten minutes — and even then, the second model misses half the decisions you already made.

**anyllm** solves this. It distills a long LLM session into a compact, instructional briefing you can paste into any other model — ChatGPT, Claude, Cursor, a fresh tab — and pick up exactly where you left off, without re-litigating finished work.

---

## Install

Requires Python 3.10+.

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
export ANTHROPIC_API_KEY=sk-ant-...   # optional; without it, distillation runs in offline mode
```

## Quickstart

```bash
cd your-project
anyllm init
anyllm pack                              # snapshot the most recent Claude Code session
anyllm prime --target chatgpt --copy     # briefing on the clipboard — paste and keep going
```

## Commands

| Command | What it does |
|---|---|
| `anyllm init` | Create a `.anyllm/` directory in the current project. |
| `anyllm pack` | Ingest the most recent LLM session, distill it, **merge** into `current.md`. |
| `anyllm prime --target <model> [--copy] [--write PATH]` | Render a copy-pasteable briefing for the target model. |
| `anyllm status` | Print task, decision counts, graph freshness, and merge state. |
| `anyllm log` | Table of every session packed, with per-session decision deltas. |
| `anyllm diff <session-id>` | Show the snapshot and merge summary from a past session. |

MVP ships with one ingestor (`claude-code`) and one adapter (`chatgpt`).

## How it works

Six stages, each with one job:

```
Ingestor → Distiller → [Graph Update] → Merger → Composer → Adapter
```

**Ingestor** reads `~/.claude/projects/*.jsonl` into a normalized transcript.

**Distiller** (Claude Sonnet) compresses it into a structured snapshot — what was decided, what was built, what's next — with per-section confidence scores so you know what to double-check.

**Merger** combines the new snapshot with the existing `current.md` instead of overwriting it. Decisions accumulate across sessions — they're never silently dropped.

**Storage** lives in `.anyllm/` as plain markdown and JSON. Hand-editable, diff-able, committable.

**Composer** wraps the snapshot in role framing and anti-repetition guards so the receiving model doesn't re-explore closed questions.

**Adapter** renders the briefing in the idiom of the target model — the same snapshot reads differently to ChatGPT vs. Cursor vs. a fresh Claude session.

---

## Confidence-Aware Snapshot Merging

Previously, `anyllm pack` overwrote `current.md` with the latest snapshot. Decisions made three sessions ago and not mentioned in the latest session were silently lost. Now, every `pack` **merges** the new snapshot into the existing one.

### Decision State Machine

Each decision from a previous `current.md` is classified:

- **CONFIRMED** — re-stated in the latest session, or verified by the codebase graph
- **ADDED** — new this session
- **STALE** — absent from the latest session and graph confidence is uncertain
- **ORPHANED** — code anchor deleted and absent for multiple sessions

### Sections That Never Get Dropped

- **Failed Approaches** — union of all sessions. If something failed once, the next model knows forever.
- **Open Questions** — carried forward until a session explicitly resolves one.

### Session Provenance

Every decision tracks which session introduced it and which sessions re-confirmed it. `current.md` includes a `merged_from` list and a `Session Provenance` table so anyone can audit exactly how the project's knowledge evolved.

### Graceful Degradation

Merging works without any extra tools. When graphify isn't installed, absent decisions are conservatively marked STALE (not orphaned). Set `merge.enabled: false` in config to revert to the old overwrite behavior.

---

## graphify Integration (Optional)

[graphify](https://github.com/anymindhq/graphify) builds a knowledge graph from your codebase via AST extraction. anyllm uses it to verify decisions against the actual code — not just what the LLM said.

```bash
# Install graphify separately
uv tool install graphifyy

# Build the initial graph (one-time)
graphify extract .

# anyllm auto-updates the graph on every pack
anyllm pack   # calls graphify extract --update internally
```

anyllm makes two types of graphify query:

- **Node confidence** — does this code anchor still exist, and how confident? (`EXTRACTED` / `INFERRED` / `AMBIGUOUS`)
- **Incremental update** — re-extract only changed files (fast, seconds not minutes)

graphify does not write to `current.md` or decide what decisions mean. It only answers: *"does this code still exist?"* The merge engine owns all logic.

### Config

```yaml
merge:
  enabled: true
  graphify_graph: "graphify-out/graph.json"
  graphify_timeout: 30        # seconds; subprocess timeout
  stale_threshold: 3          # sessions absent before ORPHANED
  auto_update_graph: true     # run graphify extract --update before merging
```

---

## Roadmap

- Additional ingestors: ChatGPT export, Gemini, raw markdown transcripts
- Additional adapters: Cursor, Gemini, local Llama
- `anyllm push` — sync context to a shared team workspace so collaborators join mid-session without a catch-up call
- Embedding-based decision matching for better paraphrase handling

---

## Philosophy

Every LLM session is stateless. You build up context painfully across dozens of turns, and the moment you switch models — or the context window fills — that shared understanding evaporates. `anyllm` treats context as a first-class artifact: something you build once, version, and carry forward, not something you reconstruct from memory every time.

The `.anyllm/` directory belongs in your repo. Commit it.