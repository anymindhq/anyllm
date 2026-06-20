# anyllm: Technical Architecture and Implementation

## Why This Project Exists

LLM coding sessions build up important working context: the task, completed work, technical decisions, failed approaches, relevant files, and the next action. That context is usually lost when a developer changes providers, reaches a context limit, runs out of credits, or starts a fresh session.

**anyllm** makes this context portable. It converts a long coding session into a compact, structured briefing that another LLM can use to continue the work without restarting or repeating earlier mistakes.

The project is designed around three principles:

- **Cross-provider portability:** session context should not belong to one LLM vendor.
- **Local-file-first storage:** artifacts are editable Markdown and JSON files inside the project.
- **Resumption over summarization:** output must tell the next model what to do, what is complete, and what not to repeat.

## Architecture Overview

anyllm is a Python CLI built as a five-stage processing pipeline:

```text
                         anyllm pack

Claude Code JSONL
       |
       v
+----------------+    +-----------------------+    +----------------+
| Source Ingestor| -> | Normalized Transcript | -> |   Distiller    |
+----------------+    +-----------------------+    +----------------+
                                                           |
                                                           v
                                                  Snapshot Markdown
                                                           |
                               +---------------------------+
                               v
                         .anyllm/ Storage
                               |
                               | anyllm prime
                               v
+----------------+    +-----------------------+    +----------------+
| Target Adapter | <- |  Composed Briefing    | <- |    Composer    |
+----------------+    +-----------------------+    +----------------+
       |
       v
Target-specific primer
```

Each stage has one responsibility. Source-specific behavior stays in ingestors, target-specific behavior stays in adapters, and the middle of the pipeline remains provider-independent.

## System Components

### CLI Orchestrator

`src/anyllm/cli.py` is the application entry point and composition root. It defines the Typer commands, resolves ingestors and adapters from registries, coordinates the pipeline, and displays output using Rich.

The CLI exposes:

| Command | Responsibility |
|---|---|
| `anyllm init` | Create the `.anyllm/` project structure and default configuration |
| `anyllm pack` | Ingest, distill, and persist a session snapshot |
| `anyllm prime` | Generate a target-specific continuation briefing |
| `anyllm status` | Show the current task, status, next step, and confidence |
| `anyllm log` | Show packed session history |
| `anyllm diff <session-id>` | Display a historical session snapshot |

### Ingestor Layer

The ingestor layer converts provider-specific session files into a common contract.

`ClaudeCodeIngestor` currently reads:

```text
~/.claude/projects/<encoded-project-path>/*.jsonl
```

It parses user and assistant turns, timestamps, model details, token usage, tool calls, and files touched. Malformed JSON lines are skipped so partially valid sessions can still be recovered.

The normalized output is represented by `NormalizedTranscript`:

```text
NormalizedTranscript
|-- source
|-- session_id
|-- started_at
|-- ended_at
|-- turns[]
|   |-- role
|   |-- text
|   |-- timestamp
|   `-- tool_calls[]
|-- files_touched[]
`-- metadata
    |-- model
    |-- token_count
    `-- source_path
```

This contract isolates the rest of the system from Claude Code's JSONL structure.

### Distillation Layer

`src/anyllm/distiller/distiller.py` converts a normalized transcript into a compact Markdown snapshot.

The distiller:

1. Loads the versioned prompt from `distiller/prompts/v1.md`.
2. Builds snapshot frontmatter containing project and session provenance.
3. Converts transcript turns into a prompt-friendly representation.
4. Soft-caps transcript content at 180,000 characters.
5. Calls the configured Anthropic model.
6. Repairs missing frontmatter when necessary.
7. Returns a valid offline skeleton when an API key is unavailable.

The default output budget is 2,000 tokens. The output is instructional rather than conversational and uses these fixed sections:

```text
Task
Status
Decisions
Code map
Tried & failed
Next step
Open questions
Confidence Report
```

The confidence report is part of the architecture, not optional metadata. It allows uncertain information to be verified instead of silently trusted.

### Storage Layer

`src/anyllm/storage.py` persists project context using plain files:

```text
.anyllm/
|-- config.yaml
|-- index.json
|-- current.md
`-- sessions/
    |-- <date>-<session-id>.transcript.json
    `-- <date>-<session-id>.snapshot.md
```

Responsibilities are separated as follows:

- `current.md` is the latest snapshot consumed by `prime`.
- `sessions/` preserves historical transcripts and snapshots.
- `index.json` stores searchable session metadata.
- `config.yaml` controls the model, token budget, target, tone, and additional rules.

Index entries are deduplicated using `(source, session_id)`, making repeated packing of the same session logically idempotent.

### Composer Layer

`src/anyllm/composer.py` parses snapshot Markdown into a `Snapshot` object and creates a target-independent briefing dictionary.

The composer adds:

- Role framing for continuation of an existing task
- Rules preventing restarts and duplicate implementation
- Warnings for low-confidence sections
- User-configured rules and tone
- The concrete next action

This separation is important: behavioral instructions are defined once and shared by every target adapter.

### Adapter Layer

Adapters render the canonical briefing for a specific receiving model. They do not perform ingestion, storage, or semantic decision-making.

The current `ChatGPTAdapter` renders Markdown containing ground rules, task state, decisions, code context, failed attempts, confidence information, and the immediate next step.

New adapters implement:

```python
class Adapter(Protocol):
    name: str

    def render(self, briefing: dict[str, Any]) -> str:
        ...
```

They are registered in the `ADAPTERS` dictionary, allowing the CLI to select them by name.

## Runtime Sequences

### Pack Sequence

```text
User -> CLI: anyllm pack
CLI -> Config: load project settings
CLI -> Ingestor registry: resolve source
CLI -> Ingestor: load and normalize session
CLI -> Storage: write transcript JSON
CLI -> Distiller: create snapshot
Distiller -> Anthropic API: distill transcript (online mode)
Distiller -> CLI: snapshot Markdown
CLI -> Storage: write historical snapshot
CLI -> Storage: replace current.md
CLI -> Storage: upsert index entry
CLI -> User: packed successfully
```

If online distillation fails, the command exits without intentionally replacing `current.md`. If no API key is configured, the distiller produces a low-confidence offline snapshot instead.

### Prime Sequence

```text
User -> CLI: anyllm prime --target chatgpt
CLI -> Storage: read current.md
CLI -> Composer: parse and compose briefing
Composer -> CLI: canonical briefing dictionary
CLI -> Adapter registry: resolve target
CLI -> Adapter: render briefing
Adapter -> CLI: primer text
CLI -> User: stdout, clipboard, or file
```

## Configuration

Default `.anyllm/config.yaml`:

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

The package requires Python 3.10+ and uses Typer, Rich, PyYAML, the Anthropic SDK, and Pyperclip.

## Architectural Decisions

| Decision | Reason |
|---|---|
| Linear five-stage pipeline | Keeps responsibilities clear and independently extensible |
| Normalized transcript contract | Prevents provider formats from leaking into the core |
| Markdown snapshot protocol | Human-readable, editable, diffable, and easy to version |
| File-based persistence | Avoids infrastructure and keeps context with the project |
| Separate composer and adapters | Shares behavioral rules while allowing target-specific rendering |
| Versioned distiller prompt | Makes semantic output changes traceable and testable |
| Explicit confidence report | Surfaces information loss and uncertain decisions |

## Extension Architecture

### Adding a Source

1. Implement the `Ingestor` protocol.
2. Convert source data into `NormalizedTranscript`.
3. Register the implementation in `INGESTORS`.
4. Add representative transcript fixtures.

### Adding a Target

1. Implement the `Adapter` protocol.
2. Render the canonical briefing without changing its meaning.
3. Preserve confidence warnings and anti-repetition rules.
4. Register the implementation in `ADAPTERS`.

This structure allows new providers to be added without modifying storage, composition, or the snapshot format.

## Security and Reliability Boundaries

- Session files and generated artifacts are stored locally.
- Online distillation sends transcript content to Anthropic.
- Secrets are not currently detected or redacted before transmission.
- File writes are direct rather than atomic.
- Concurrent `pack` commands are not protected by a project lock.
- Transcript limits are character-based rather than token-aware.
- The repository currently has no automated test suite.

The product should therefore be described as **local-file-first**, not completely local, until local distillation and secret-redaction options are implemented.

## Recommended Implementation Priorities

1. Add fixture-based tests for ingestion, storage, parsing, composition, and adapter rendering.
2. Use explicit UTF-8 encoding and atomic file replacement for all persisted artifacts.
3. Add project-level locking around `pack` and index updates.
4. Detect or redact credentials before online distillation.
5. Add a resumption-fidelity benchmark covering no-redo rate and decision adherence.
6. Add Claude and generic adapters, followed by more source ingestors.
7. Replace latest-only `current.md` behavior with a confidence-aware merge process.

The core architecture should remain stable as anyllm grows: **normalize every source, preserve a versioned snapshot, compose one canonical briefing, and render it through small target-specific adapters.**
