# anyllm — Portable LLM Session Context

> *Git for LLM context.* Snapshot a dying session, brief the next LLM in 30 seconds, anywhere.

---

## 1. The Problem

You're deep in a coding session with an LLM. Credits run out, the context window fills, the provider has an outage, or you simply want a second opinion from a different model. To keep going, you must:

1. Open a different tool/session/provider.
2. Re-explain the project, the task, what you've tried, what worked, what failed, the file layout, the decisions made, the open questions.
3. Hope the new LLM doesn't go in circles re-doing work the old one already finished.

This is a 10–30 minute tax every time. For a developer who hits this multiple times a week, it is the single biggest friction in LLM-assisted coding.

## 2. The Insight

The market is full of **memory systems for app builders** (mem0, Letta/MemGPT, Zep, LangChain memory). They are SDKs you embed in your *own* LLM app.

Nobody owns the **developer-mid-task handoff** problem. The closest thing — Pieces — is heavyweight, closed, and captures everything indiscriminately.

The opportunity is a small, sharp, open-source CLI with one job:

> Take the *useful* state out of one LLM session and inject it cleanly into another, **regardless of provider**.

The non-obvious hard part is **not storage**. It is:

1. **Distillation** — compress a 50k-token transcript into a 2k-token primer that preserves task-resumption fidelity.
2. **Instructional framing** — the output isn't a summary, it's a *briefing* that tells the next LLM what *not* to redo.
3. **Confidence surfacing** — flag what the distiller is unsure about so the user (or next LLM) knows where to verify.
4. **Provider adaptation** — Claude prefers structured/XML-ish, ChatGPT prefers markdown with explicit role framing, Cursor wants `.cursorrules`.
5. **Incrementality** — every session appends a delta to a rolling project snapshot. Like git commits.

## 3. Core Principles

These are the rules that decide every design call. Memorize them.

1. **Fidelity within budget.** Don't ship "accuracy over compression" — that just means pasting the transcript. Set a token budget; maximize task-resumption fidelity inside it.
2. **The primer is a briefing, not a summary.** Output must be *instructional*. It tells the next LLM what to do, what's already done, and what *not* to redo.
3. **Surface uncertainty.** If the distiller isn't sure, say so. Hidden uncertainty is how summary tools silently lie.
4. **Local-first.** No cloud. Transcripts contain code and secrets. Everything stays on disk.
5. **Boring, hand-editable formats.** Snapshots are markdown. Users can fix the distiller's mistakes manually. This is a feature.
6. **Cross-provider from day one.** Within-provider continuity is what `MEMORY.md` and Cursor rules already give you for free. The product only matters if it crosses tools.

---

## 4. The Product

A CLI: `anyllm`.

```bash
# Inside any project directory
anyllm init                              # creates a .anyllm/ folder
anyllm pack                              # snapshot the current/most-recent LLM session
anyllm status                            # show what's in the current snapshot (token count, sections, confidence)
anyllm prime --target chatgpt            # emit a copy-pasteable briefing
anyllm prime --target chatgpt --copy     # ...and put it on the clipboard
anyllm prime --target claude --write     # write a MEMORY.md-shaped file in place
anyllm log                               # session history
anyllm diff <session-id>                 # what that session added/changed
```

**One-line pitch:** *Your LLM session died. `anyllm pack`, `anyllm prime`, paste — keep going in any other tool.*

---

## 5. Architecture

### 5.1 The pipeline

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  Ingestor   │───▶│  Distiller  │───▶│   Storage   │───▶│  Composer   │───▶│   Adapter   │
│ (per source)│    │   (LLM)     │    │   (.anyllm/)│    │ (framing)   │    │ (per target)│
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
   raw transcript  → facts/decisions  → snapshot.md     → briefing JSON   → final primer
```

Five stages, each with one job. **Adding a new source = new ingestor. Adding a new target = new adapter.** The middle three never change.

### 5.2 Stages

#### A. Ingestor — *get raw transcripts in*

Reads from one source, outputs a normalized transcript.

- **MVP:** `claude-code` ingestor only. Reads JSONL transcripts from `~/.claude/projects/<project-slug>/*.jsonl`. Parses user/assistant turns, tool calls, file edits.
- **Later:** `chatgpt` (export ZIPs), `cursor` (local SQLite), `clipboard` (paste-in fallback for any web LLM).

Normalized transcript schema:

```json
{
  "source": "claude-code",
  "session_id": "abc123",
  "started_at": "...",
  "ended_at": "...",
  "turns": [
    { "role": "user", "text": "...", "ts": "..." },
    { "role": "assistant", "text": "...", "tool_calls": [...], "ts": "..." }
  ],
  "files_touched": ["src/auth.py"],
  "metadata": { "model": "claude-opus-4-7", "token_count": 48230 }
}
```

This normalization is what lets every downstream stage be source-agnostic.

#### B. Distiller — *the brain*

Single LLM call (MVP). Map/reduce later for sessions over the model's context window.

**Input:** normalized transcript + token budget (default 2000).
**Output:** structured **snapshot** in the `.anyllm` markdown format (section 5.4).

The distiller's job is **fact extraction with self-assessment**. It must:
- Extract task, status, decisions (with `Why:`), code map, failed attempts, next step, open questions.
- Self-rate **confidence** per section: high / medium / low.
- List what it had to omit due to budget, and what it couldn't determine from the transcript.

The confidence layer is the most important non-obvious piece. It's what makes the tool trustworthy instead of silently lossy.

**Distiller model:** Claude Sonnet by default (cheap, smart enough). Configurable.

The distiller prompt is a versioned asset, not throwaway code. It lives in `anyllm/distiller/prompts/v1.md` and is reproducibly tested against fixture transcripts.

#### C. Storage — `.anyllm/` directory

```
.anyllm/
├── config.yaml              # project config: target preferences, distill budget, model
├── index.json               # session log (id, source, timestamp, brief summary)
├── sessions/
│   ├── 2026-04-19-abc123.transcript.json   # normalized raw
│   └── 2026-04-19-abc123.snapshot.md       # distilled
└── current.md               # rolling project-level snapshot (what `anyllm prime` reads)
```

- Snapshots are **markdown**. The user can open and hand-edit them — this is the local-first, boring-format principle.
- `current.md` is the canonical "what's going on right now" file. In MVP, `anyllm pack` overwrites it with the latest session's snapshot. In v2, `anyllm pack` does an LLM-assisted *merge* (supersede stale items, append new). Designing for the merge from day one means no rewrite later.
- Per-session snapshots stay forever (cheap) so `anyllm log` / `anyllm diff` work.

#### D. Composer — *facts → briefing*

This is the stage your earlier notes were missing, and it's what makes the adapter layer cheap.

The composer takes the snapshot (raw facts) and adds the **instructional framing** that turns it into a *briefing*:

- Role preamble: *"You are continuing an existing coding task..."*
- Anti-repetition guards: *"Do NOT restart. Do NOT re-implement completed parts. Do NOT ignore prior decisions."*
- Verification hooks for low-confidence sections: *"The following decision is marked low-confidence — verify before relying on it."*
- The user's framing preferences from `config.yaml` (e.g. tone, extra rules they always want appended).

Composer output is a structured **briefing JSON** — adapter-agnostic, target-agnostic. One representation, many renderings.

#### E. Adapter — *render for one target*

Each adapter takes the composed briefing and emits the right shape for one target. Adapters are *renderers* — no logic, no decisions, just templating.

- **MVP:** `chatgpt` adapter. Markdown with explicit `## Context`, `## Decisions`, `## Your task`, role-framed first message, copy-pasteable.
- **Next:** `claude` adapter (`MEMORY.md`-shaped, XML tags, structured), `cursor` adapter (`.cursorrules` file), `generic` adapter (plain text for any other LLM).

Adapters know each provider's quirks:
- Claude → tolerates structure and length, prefers tagged sections.
- GPT → prefers markdown with clear role framing and shorter primers.
- Cursor → must respect `.cursorrules` size limits, code-style emphasis.

### 5.3 Why ChatGPT is the MVP target (not Claude)

Tempting to target Claude first because we're already in the Claude ecosystem. Wrong call.

- Within-Claude continuity is what `MEMORY.md` and `/resume` already give you for free.
- The product's *whole reason to exist* is **cross-provider portability**.
- The most relatable demo is: *"My Claude credits ran out — watch me finish the task in ChatGPT in 30 seconds."*

Build Claude → ChatGPT first. The Claude adapter is week 2.

### 5.4 The `.anyllm` snapshot format (v0)

Versioned. Markdown. Boring on purpose so it can become a standard.

```markdown
---
anyllm_version: 0.1
project: multiagent
generated_at: 2026-04-19T14:30:00Z
distilled_from:
  - source: claude-code
    session_id: abc123
    turn_count: 142
    token_count: 48230
budget_tokens: 2000
distiller_model: claude-sonnet-4-6
---

# Task
<one paragraph: what the user is trying to accomplish>

# Status
<where things stand right now — what's done, what's in progress>

# Decisions
- <decision>. **Why:** <rationale>. _conf: high_
- <decision>. **Why:** <rationale>. _conf: medium_

# Code map
- `path/to/file.py` — <one line: what it does / what changed>
  ```python
  # only the lines the next session needs
  ```

# Tried & failed
- <approach> — failed because <reason>. Don't redo.

# Next step
<one concrete action the next session should take first>

# Open questions
- <question that needs the user>

# Confidence Report
- Overall: medium
- High confidence: task, decisions, next step
- Medium confidence: code map (some files inferred from tool calls, not read)
- Low confidence: <none>
- Omitted (budget): early debugging exploration of `legacy/old_auth.py`
- Could not determine: whether the user wants to keep backward compatibility with v1 tokens
```

The **Confidence Report** is non-negotiable. It's the trust mechanism.

### 5.5 Key flows

**Flow 1 — Pack.**
`anyllm pack` →
1. Find the most recent session for this project (via configured ingestors).
2. Normalize → `sessions/<id>.transcript.json`.
3. Distill → `sessions/<id>.snapshot.md`.
4. Update `current.md` (MVP: copy. v2: LLM-assisted merge).
5. Append entry to `index.json`.

**Flow 2 — Prime.**
`anyllm prime --target chatgpt [--copy] [--write PATH]` →
1. Read `current.md`.
2. Compose into briefing JSON (add role framing, anti-repetition guards, verification hooks).
3. Render via `chatgpt` adapter.
4. Print to stdout (default), copy to clipboard (`--copy`), or write to file (`--write`).

**Flow 3 — Auto-pack on session end** (post-MVP).
A Claude Code `Stop` hook that runs `anyllm pack` automatically when a session ends. Zero-friction capture.

---

## 6. Differentiation

| Tool             | Audience            | Cross-provider  | Open  | Confidence-aware  | Lightweight  |
|------------------|---------------------|-----------------|-------|-------------------|--------------|
| mem0             | App developers      | N/A (SDK)       | Yes   | No                | Medium       |
| Letta/MemGPT     | App developers      | N/A (SDK)       | Yes   | No                | Heavy        |
| Zep              | App developers      | N/A (SDK)       | Partial | No              | Heavy        |
| Pieces           | End-user devs       | Some            | No    | No                | Heavy        |
| Claude MEMORY.md | Claude Code only    | No              | N/A   | No                | Yes          |
| Cursor rules     | Cursor only         | No              | N/A   | No                | Yes          |
| **anyllm (this)**   | **End-user devs**   | **Yes (core)**  | **Yes** | **Yes**         | **Yes**      |

Defensible wedge: **cross-provider portability + a published protocol spec + a confidence-aware briefing model**. If `.anyllm` is good, other tools could adopt the format natively, the same way `.editorconfig` got picked up.

---

## 7. Build Plan — 1 Week MVP

| Day | Work |
|-----|------|
| 1   | Repo scaffold (Python + typer). `.anyllm/` layout. `anyllm init`. Read fixture Claude Code JSONL transcripts; output normalized JSON. |
| 2   | Finish `claude-code` ingestor on real transcripts. Write 3–5 test fixtures of varying length. |
| 3   | Distiller v1: single-pass prompt, Claude Sonnet, 2k token budget. Output the snapshot format including Confidence Report. |
| 4   | Composer + `chatgpt` adapter. `anyllm prime --target chatgpt`. End-to-end smoke test. |
| 5   | Demo run: take a real 30–60 min Claude Code session, pack it, prime ChatGPT, watch ChatGPT continue correctly. Iterate the distiller prompt based on failures. |
| 6   | `anyllm status`, `anyllm log`, `--copy`, `--write`. Polish CLI. Write a 60-second README demo. |
| 7   | Buffer + record demo video. |

### Then — week 2 onward

- `claude` adapter (`MEMORY.md`-shaped output).
- `cursor` adapter.
- `clipboard` ingestor for any web LLM.
- The benchmark (next section). This is the secret weapon — don't skip.

---

## 8. The Benchmark — *the secret weapon*

Build a small evaluation harness in week 2:

- **Inputs:** ~10 canned coding sessions, each cut at the 80% mark (transcripts you've collected from real work).
- **Procedure:** for each, run `anyllm pack` → `anyllm prime --target X` → feed primer to a fresh LLM session → ask it to complete the task.
- **Measure:**
  - **Resumption fidelity** — did it complete the task without re-asking the user for already-decided things?
  - **No-redo rate** — did it avoid re-implementing finished work?
  - **Token efficiency** — primer tokens / original transcript tokens.
- **Report per (adapter, distiller model, token budget) combination.**

Why this matters:
- Nobody else has this benchmark.
- It gives you a publishable artifact: *"Task-Resumption Fidelity: A Benchmark for Cross-Provider LLM Context Handoff."*
- It keeps you honest while iterating the distiller prompt.

This single benchmark is what turns the project from "cool weekend hack" into something a staff engineer or recruiter takes seriously.

---

## 9. Tech Stack

- **Language:** Python (richest LLM ecosystem, fastest to ship).
- **CLI:** `typer`.
- **LLM clients:** `anthropic` SDK + `openai` SDK; distiller model swappable via `config.yaml`.
- **Storage:** plain files. No DB. Snapshots are markdown — users can hand-edit.
- **Testing:** `pytest` + recorded transcript fixtures so distillation is reproducible.
- **Clipboard:** `pyperclip` (cross-platform).

---

## 10. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Distillation quality is everything; bad primers = useless tool | The benchmark (section 8) keeps you honest. Start by hand-writing a perfect snapshot for one real session — if a hand-written one doesn't resume the task, the format is wrong. Fix the format before writing code. |
| Provider format churn (Claude `MEMORY.md` shape changes, etc.) | Adapters are small/swappable; protocol stays stable. |
| "Just paste the transcript yourself" objection | Only earns its keep on long sessions. Lead the demo with a 50k-token session that won't fit in ChatGPT's context. |
| Privacy — transcripts contain code and secrets | Local-first, no cloud, document this loudly in the README. |
| Hallucinated decisions from the distiller | Confidence Report. Every claim is rated; low-confidence items get an explicit "verify before relying" framing in the composed briefing. |
| Scope creep | Section 11 below. Hold the line. |

---

## 11. Out of Scope (for MVP)

Discipline matters. None of these in week 1:

- Multiple ingestors (just `claude-code`).
- Multiple adapters (just `chatgpt`).
- Map/reduce distillation pipeline.
- Auto-pack hooks.
- Smart `current.md` merge logic.
- Web UI / GUI.
- Vector search / semantic retrieval over old sessions.
- Multi-project knowledge base.

If a feature isn't required to make the demo in section 7 land, it doesn't ship in week 1.

---

## 12. Resume Narrative

> Built **anyllm**, an open-source CLI and protocol for portable LLM session context. Solves the credit-exhaustion handoff problem when developers move between Claude, ChatGPT, and Cursor mid-task. Designed a versioned `.anyllm` snapshot format with built-in confidence reporting, a distillation pipeline that compresses 50k-token transcripts into 2k-token instructional briefings, and per-provider adapters. Built a **task-resumption fidelity benchmark** — the first of its kind for this problem — and used it to tune the distiller from X% to Y% accuracy across providers.

The benchmark line is what makes a recruiter or staff engineer stop scrolling.

---

## 13. Decisions Locked

- **Name:** `anyllm`
- **Language:** Python
- **MVP target path:** Claude Code → ChatGPT
- **Repo visibility:** private until MVP works end-to-end and the demo is recorded; open-source after.
