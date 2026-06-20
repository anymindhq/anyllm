# PRD: anyllm — Confidence-Aware Snapshot Merging with graphify Integration

**Version:** 1.0  
**Status:** Ready for Implementation  
**Project:** anyllm  
**Scope:** Two tightly coupled features — graph-anchored snapshot merging and graphify as verification backend

---

## 1. Problem Statement

### 1.1 The Current Failure Mode

Every time `anyllm pack` runs, `current.md` is overwritten with the latest snapshot. This means:

- Decisions made three sessions ago and not mentioned in the latest session are silently dropped
- The next model has no way to distinguish "this decision was confirmed again" from "this decision was forgotten about"
- High-confidence knowledge (a refactored file, a pinned architecture choice) is treated identically to uncertain, session-local observations
- `current.md` reflects the *latest session*, not *project history*

The project is described as "Git for LLM context." But Git doesn't clobber your entire history with the latest commit. anyllm currently does exactly that.

### 1.2 Why Text Diffing Alone Cannot Fix It

Naively diffing old and new `current.md` fails because LLM-generated Markdown is paraphrastic and non-deterministic. The same decision can be worded differently across snapshots:

- Session 3: *"JWT validation was moved into `auth.py`"*
- Session 5: *"Authentication is handled by the `auth` module"*

These are the same fact. A text diff would treat them as two separate items. A codebase graph wouldn't — `auth.py → validate_jwt()` is either there or it isn't.

### 1.3 What graphify Provides

graphify builds a knowledge graph from your codebase using AST extraction (no API calls for code). Every relationship in the graph carries a confidence tag:

- `EXTRACTED` — verified directly from source code via tree-sitter AST
- `INFERRED` — semantically guessed from docs or comments
- `AMBIGUOUS` — uncertain, possibly from incomplete context

This confidence signal is exactly what the merge engine needs to decide whether a decision should be carried forward, flagged, or dropped.

---

## 2. Goals

- **G1:** `current.md` must accumulate project knowledge across sessions, not replace it
- **G2:** Decisions confirmed by the codebase graph (`EXTRACTED`) must survive even if the latest session didn't mention them
- **G3:** Superseded decisions must be traceable — the next model should know what was tried and replaced, not just what is current
- **G4:** The merge must degrade gracefully when graphify is not installed — text-based merging is still better than clobbering
- **G5:** No changes to the snapshot format consumed by `anyllm prime` — the output stays portable Markdown

---

## 3. Non-Goals

- Not implementing embedding/vector search (out of scope for this PRD)
- Not changing the adapter layer or the `prime` command output format
- Not replacing the distiller — graphify provides verification, not distillation
- Not requiring graphify as a hard dependency

---

## 4. Architecture

### 4.1 New Pipeline Step

Current `anyllm pack` flow:

```
1. Find project dir
2. Load config
3. Select ingestor
4. Normalize session
5. Save transcript
6. Distill → snapshot
7. Save snapshot → overwrite current.md   ← problem is here
8. Upsert index.json
```

New flow:

```
1. Find project dir
2. Load config
3. Select ingestor
4. Normalize session
5. Save transcript
6. Distill → new_snapshot.md
7. [NEW] graphify update --update (if graphify installed)
8. [NEW] merger.merge(current.md, new_snapshot.md, graph.json) → merged current.md
9. Save merged current.md
10. Upsert index.json
```

### 4.2 Module Map

| New / Changed Module | Responsibility |
|---|---|
| `merger.py` (new) | Three-state decision classification and merged Markdown rendering |
| `graph_bridge.py` (new) | Thin wrapper around graphify CLI / Python API for node queries |
| `storage.py` (changed) | Write merged `current.md` instead of latest snapshot |
| `cli.py` (changed) | Call merger after distillation; call graphify update if available |
| `config.py` (changed) | Add `graphify` config block |
| `current.md` frontmatter (changed) | Add `merged_from`, `graph_version`, `decision_provenance` fields |

### 4.3 Decision State Machine

Each decision extracted from a snapshot is classified into one of three states by the merge engine:

```
Decision (from prev current.md)
          |
          ├── appears in new snapshot?
          │         YES → CONFIRMED (update wording to latest)
          │
          ├── NOT in new snapshot → query graphify for code anchor
          │         |
          │         ├── graph node confidence = EXTRACTED → CONFIRMED (pinned by graph)
          │         ├── graph node confidence = INFERRED  → STALE (flag for verification)
          │         └── graph node gone / AMBIGUOUS       → ORPHANED (move to stale section)
          │
          └── NEW decision (only in new snapshot) → ADDED
```

New decisions from the new snapshot that have no counterpart in the old snapshot are always added. There is no merge conflict for additive knowledge.

---

## 5. Detailed Specification

### 5.1 `merger.py`

```python
@dataclass
class Decision:
    id: str                    # stable hash of normalized decision text
    text: str                  # human-readable decision
    code_anchor: str | None    # file path or symbol the decision refers to
    confidence: str            # EXTRACTED | INFERRED | AMBIGUOUS | UNKNOWN
    session_id: str            # which session introduced this decision
    sessions_confirmed: list[str]  # sessions that re-confirmed it

class MergeEngine:
    def merge(
        self,
        prev_md: str,
        new_md: str,
        graph_path: str | None = None,
    ) -> MergeResult:
        ...

@dataclass
class MergeResult:
    confirmed: list[Decision]   # carried forward with high confidence
    updated: list[Decision]     # superseded by new decision (old version archived)
    added: list[Decision]       # new this session
    stale: list[Decision]       # graph says uncertain, needs human check
    orphaned: list[Decision]    # code anchor gone, archived with note
    merged_md: str              # the final current.md content
```

**Key behaviors:**

- `parse_decisions()` extracts decisions from both old and new snapshot Markdown by parsing the `## Decisions` section. Each bullet is treated as one decision.
- Decision identity is determined by a normalized hash (strip punctuation, lowercase, stem key nouns) — this handles paraphrasing across sessions.
- `code_anchor` is extracted heuristically from the decision text: backtick-quoted identifiers, file paths in the text, or function names.
- If `graph_path` is None or graphify is unavailable, all decisions not in the new snapshot are classified as STALE (conservative fallback, not ORPHANED).

### 5.2 `graph_bridge.py`

Thin wrapper. Does not import graphify at module load time — all imports are deferred so anyllm runs normally without graphify installed.

```python
def graphify_available() -> bool:
    """Check if graphify CLI is on PATH."""
    ...

def query_node_confidence(graph_path: str, anchor: str) -> str:
    """
    Returns EXTRACTED | INFERRED | AMBIGUOUS | MISSING.
    Calls: graphify query "<anchor>" --graph <graph_path> --json
    Falls back to MISSING if graphify not available or query fails.
    """
    ...

def update_graph(project_path: str) -> bool:
    """
    Calls: graphify extract <project_path> --update
    Only re-extracts changed files. Returns True on success.
    Safe to call; no-ops if graphify not installed.
    """
    ...
```

**Important:** `graphify extract --update` only processes files changed since the last run. On a typical coding session this is fast (seconds, not minutes). The bridge must not block `anyllm pack` if graphify is slow — wrap in a subprocess with a 30-second timeout; if it times out, merge without graph verification.

### 5.3 `current.md` Frontmatter Schema

New required fields:

```yaml
---
task: "Implement OAuth2 middleware"
status: in_progress
snapshot_version: v1
distiller_version: v1
session_id: 2025-06-21-abc123
merged_from:
  - 2025-06-18-def456
  - 2025-06-19-ghi789
  - 2025-06-21-abc123
graph_version: "graphify-out/graph.json"
graph_hash: "sha256:a1b2c3..."   # hash of graph.json at merge time
confidence_report:
  confirmed: 8
  added: 3
  stale: 1
  orphaned: 0
---
```

`merged_from` lists every session whose decisions are still active in this file. This makes the rolling state auditable — anyone can trace which session introduced a given decision.

### 5.4 `current.md` Body Structure

The merged `current.md` has a new section layout:

```markdown
## Task
<unchanged from snapshot>

## Status
<from latest snapshot>

## Decisions
<!-- CONFIRMED: verified by graph or re-stated in latest session -->
- [CONFIRMED | auth.py] JWT validation lives in `validate_jwt()` inside `auth.py`. Moved in session 2025-06-18 to fix race condition in old middleware.
- [CONFIRMED | config.py] Database connection pool size is pinned at 10 to avoid exhausting RDS connections under load.

<!-- ADDED: new this session -->
- [NEW] Switched from `requests` to `httpx` for async-compatible HTTP calls.

## Superseded Decisions
<!-- Decisions replaced this session. Preserved so the next model knows what NOT to try. -->
- [SUPERSEDED by: NEW decision above] Originally used `requests` library for all HTTP calls. Replaced 2025-06-21.

## Code Map
<from latest snapshot>

## Failed Approaches
<merged: union of all sessions, never dropped>

## Next Step
<from latest snapshot>

## Open Questions
<merged: carried forward until explicitly resolved>

## Stale / Needs Verification
<!-- graphify confidence = INFERRED or AMBIGUOUS. Human or next model should verify. -->
- [STALE | confidence: INFERRED] `CacheManager` was described as wrapping Redis — graph cannot confirm this from source code alone.

## Session Provenance
<!-- Which session introduced which decision -->
| Decision anchor | Introduced | Last confirmed |
|---|---|---|
| auth.py → validate_jwt | 2025-06-18 | 2025-06-21 |
| config.py → POOL_SIZE | 2025-06-19 | 2025-06-21 |
```

**Two sections never get dropped across sessions:**

- `## Failed Approaches` — union of all sessions. If something failed once, the next model should know forever.
- `## Open Questions` — carried forward until a session explicitly marks one as resolved.

### 5.5 `config.yaml` New Block

```yaml
distiller:
  model: claude-sonnet-4-6
  budget_tokens: 2000

targets:
  default: chatgpt

framing:
  extra_rules: []
  tone: direct

# New block
merge:
  enabled: true                    # set false to revert to clobber behavior
  graphify_graph: "graphify-out/graph.json"   # relative to project root
  graphify_timeout: 30             # seconds; 0 = no timeout
  stale_threshold: 3               # sessions a decision can be absent before → ORPHANED
  auto_update_graph: true          # run graphify extract --update before merging
```

`stale_threshold` prevents decisions from being immediately orphaned when they're simply not relevant to the current session. A decision must be absent for N consecutive sessions AND have a non-EXTRACTED graph confidence before being moved to the stale section.

### 5.6 `anyllm status` Changes

Add merge state to the status output:

```
Project: my-api
Sessions: 7
Current snapshot: 2025-06-21-abc123
Merged from: 3 sessions
Decisions: 11 confirmed, 2 stale, 0 orphaned
Graph: graphify-out/graph.json (last updated: 2025-06-21 14:32)
graphify: installed (v0.8.33)
```

### 5.7 `anyllm log` Changes

Each log entry should show whether a decision was confirmed, added, or orphaned in that session:

```
2025-06-21  abc123  claude-sonnet-4-6  +3 decisions, 8 confirmed, 1 stale
2025-06-19  ghi789  claude-sonnet-4-6  +2 decisions, 6 confirmed, 0 stale
2025-06-18  def456  claude-sonnet-4-6  +5 decisions (initial)
```

---

## 6. graphify Integration Setup

### 6.1 How graphify Fits In

graphify is installed by the user, not bundled with anyllm. The integration works at the CLI level via subprocess calls to `graphify query` and `graphify extract`. This keeps anyllm's dependency surface clean.

Recommended user workflow after installing anyllm:

```bash
# 1. Install graphify
uv tool install graphifyy

# 2. Build the initial project graph (one-time)
graphify install   # registers graphify skill with Claude Code
/graphify .        # builds graphify-out/graph.json

# 3. anyllm now auto-updates the graph on every pack
anyllm pack        # calls graphify extract --update internally if auto_update_graph: true
```

### 6.2 What graphify Queries anyllm Uses

The bridge only makes two types of query:

**Node existence + confidence:**
```bash
graphify query "<anchor>" --graph graphify-out/graph.json --json
```
Returns a JSON object with `confidence: EXTRACTED | INFERRED | AMBIGUOUS` and `exists: true | false`.

**Graph update (incremental):**
```bash
graphify extract . --update
```
Only processes files changed since last run. Cheap to call on every pack.

### 6.3 What graphify Does NOT Control

graphify does not write to `current.md`. It does not decide what the decisions mean. It only answers the question: *"does this code anchor still exist, and how confident are you?"* The merge engine owns all logic.

---

## 7. Implementation Plan

### Phase 1 — Text-Only Merge (no graphify dependency)

**Goal:** Stop clobbering `current.md`. All decisions either confirmed (in new snapshot) or stale (not in new snapshot). No graph verification yet.

Deliverables:
- `merger.py` with `parse_decisions()`, stable decision ID hashing, and `render_merged_md()`
- Updated `storage.py` to call merger instead of direct write
- Updated `current.md` frontmatter schema with `merged_from` and `confidence_report`
- Updated `anyllm status` output
- Fixture-based tests for: same decision reworded, new decision added, old decision dropped

**Exit criteria:** `anyllm pack` run three times on a project produces a `current.md` that contains decisions from all three sessions, not just the latest.

### Phase 2 — graphify Bridge

**Goal:** Classify decisions by codebase truth, not just snapshot presence.

Deliverables:
- `graph_bridge.py` with `graphify_available()`, `query_node_confidence()`, `update_graph()`
- `merger.py` updated to use graph confidence for classification
- `config.yaml` new `merge:` block parsed in `config.py`
- `stale_threshold` logic (N consecutive absent sessions before ORPHANED)
- `Stale / Needs Verification` section in rendered `current.md`
- Tests with mock graphify responses for EXTRACTED / INFERRED / AMBIGUOUS / MISSING

**Exit criteria:** A decision about a deleted file is moved to ORPHANED after `stale_threshold` sessions. A decision about a confirmed code node survives even when not mentioned in the latest session.

### Phase 3 — Provenance and Polish

**Goal:** Make the merge history legible and the `prime` output richer.

Deliverables:
- `## Session Provenance` table in `current.md`
- `## Superseded Decisions` section populated when a decision is explicitly replaced
- `anyllm log` shows per-session decision deltas
- `anyllm diff <session-id>` shows what the merge added/confirmed/orphaned in that session
- `anyllm status` shows graphify version and graph freshness
- README updated with graphify setup instructions and merge behavior explanation

**Exit criteria:** A developer can run `anyllm log` and understand exactly how the project's decision history evolved across sessions.

---

## 8. Testing Strategy

### Unit Tests (all phases)

```
tests/
├── fixtures/
│   ├── snapshot_v1.md          # initial snapshot
│   ├── snapshot_v2.md          # same decisions, different wording
│   ├── snapshot_v3.md          # one new decision, one dropped
│   ├── graph_response_extracted.json
│   ├── graph_response_inferred.json
│   └── graph_response_missing.json
├── test_merger.py
│   ├── test_same_decision_reworded_is_confirmed
│   ├── test_new_decision_is_added
│   ├── test_dropped_decision_becomes_stale
│   ├── test_extracted_decision_survives_absence
│   ├── test_missing_node_decision_becomes_orphaned
│   ├── test_failed_approaches_never_dropped
│   ├── test_open_questions_carry_forward
│   └── test_stale_threshold_respected
├── test_graph_bridge.py
│   ├── test_graphify_not_available_returns_missing
│   ├── test_timeout_falls_back_gracefully
│   └── test_query_parses_confidence_correctly
└── test_storage_merge.py
    ├── test_current_md_contains_all_session_decisions
    └── test_merged_from_frontmatter_updated
```

### Integration Test

Run `anyllm pack` three times against a fixture project with a pre-built `graph.json`. Assert:
- `current.md` contains decisions from all three sessions
- `merged_from` lists all three session IDs
- One decision absent for 3 sessions (below `stale_threshold`) is still CONFIRMED if EXTRACTED by graph
- One decision about a deleted file is ORPHANED

---

## 9. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Decision ID hashing produces false matches (different decisions hash identically) | Medium | Medium | Use bigram overlap + anchor matching, not pure text hash; tune on fixture set |
| graphify query is slow on large codebases | Medium | Low | 30s timeout; fall back to text-only merge; cache last query result per anchor per session |
| graphify graph is stale (not run since last session) | High | Medium | `auto_update_graph: true` by default; warn in `anyllm status` if graph is older than last session |
| Decisions without clear code anchors cannot be verified | High | Low | Decisions without anchors are confirmed if they appear in new snapshot, stale if they don't — text-based fallback, not orphaned |
| LLM paraphrasing breaks decision ID matching | High | High | This is the hardest problem; Phase 1 must include manual validation of the hashing on real session pairs before Phase 2 begins |

---

## 10. Success Metrics

| Metric | Target | How Measured |
|---|---|---|
| Decision retention across 5 sessions | ≥ 90% of EXTRACTED decisions still present | Fixture-based integration test |
| False positive orphan rate | < 5% of valid decisions incorrectly orphaned | Manual review of 20 real session pairs |
| `anyllm pack` latency increase | < 5 seconds with graphify update | Benchmark on 50-file project |
| No-redo rate (downstream) | Measurable improvement over baseline | Manual: run same continuation task with old vs. new `current.md`, count how often model redoes finished work |

---

## 11. Open Questions

1. **Decision parsing granularity** — should sub-bullets under a decision be tracked as separate decisions or as one unit? Recommendation: treat the top-level bullet as the decision unit; sub-bullets are supporting evidence.

2. **Multi-task projects** — if `current.md` spans multiple tasks (task A done, task B in progress), should each task's decisions be tracked independently? Recommendation: out of scope for this PRD; model as a single decision pool for now.

3. **graphify graph location** — what if the user's graphify graph is not at `graphify-out/graph.json`? Config option `merge.graphify_graph` handles this, but should anyllm auto-discover it? Recommendation: auto-discover by walking up from project root, fall back to config value.

4. **Snapshot format versioning** — adding `merged_from` to frontmatter breaks existing `current.md` files. Need a migration path for users upgrading from pre-merge anyllm. Recommendation: if `merged_from` is absent, treat the file as a v0 snapshot and skip merge classification on first run; only carry forward subsequent sessions.