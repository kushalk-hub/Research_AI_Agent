# AGENT_COORDINATOR — shared coordination contract

This file is the single coordination contract for three parallel implementation agents.
It is not an implementation plan and does not replace any plan. When this document and
an implementation plan disagree on architecture, this document wins. When this document
and the repository disagree on what is implemented, the repository wins — the status
lines below say which is which.

## 0. Repository state (verified)

- Branches merged on `integration/prototype-baseline`: Agent A (data integrity,
  incl. `rla status`), Agent B (P12 provider/routing, incl. the fallback-category
  fix, committed as `1ba50bc`), Agent C (TUI, incl. back-compat shim for
  pre-routing modules).
- Verification: **668 passed, ruff clean** (see README "Development and testing").
  The earlier "561 passed, 1 known A8 failure" line is superseded: the deferred
  A8 dispatch assertion has landed and the suite is fully green.
- Known environment notes (recorded, not to be silently fixed):
  1. Gemini model availability varies by key (retired, renamed, or tier-gated),
     so verify with `rla doctor --llm` rather than assuming a model is servable
     (`doctor --llm` hint for a 404/`NOT_FOUND`: "model retired; pick a current
     one in .env").
  2. The Ollama server runs `OLLAMA_NUM_PARALLEL=1`; `RLA_MAX_CONCURRENCY=4` may
     therefore queue locally. Do not change either setting without measurement.

## 1. Mission

The repository is being developed by three specialized agents under one architecture:

- **Agent A → Data Integrity**
- **Agent B → P12 Provider/Routing**
- **Agent C → TUI**

The purpose of this document is to prevent overlapping edits, architectural drift,
duplicated logic, and agents making incompatible design decisions.

## 2. Locked architecture

```
Pipeline stage
      ↓
   LLMClient
      ↓
ProviderRouter
      ↓
 MultiBackend
      ↓
┌───────────────┬────────────────┬────────────────┐
│ GeminiClient  │ LiteLLMBackend │ OllamaBackend  │
│ native SDK    │ OpenRouter/... │ native /api    │
└───────────────┴────────────────┴────────────────┘
```

Locked rules (from the P12 plan and spec):

- `ProviderRouter` owns model precedence, capability gating, and fallback
  eligibility/order. Nothing else decides these.
- `MultiBackend` is a backend/facade, not a router. It resolves a canonical model
  id to its owning backend and delegates the call. It contains no fallback logic.
- Pipeline stages must not acquire provider-specific knowledge (ADR-001).
- Provider-specific code belongs under `src/rla/llm/`.
- Canonical model identity is the single model identity used downstream — provider
  resolution, cache keys, threshold lookup, and display all consume it.

## 3. Current routing contract

Status: stages 2–4 below are **implemented**. Stage 1 is **locked by design, lands in
P12 Task 4** — do not assume `ProviderRouter.overrides` exists until then.

Precedence, highest first:

1. **session override** — transient TUI/CLI-run control *(locked, pending Task 4)*
2. **explicit `model=`** — call-site default
3. **configured stage role** — `RLA_STRUCTURED_MODEL` / `RLA_ANSWER_MODEL`
4. **fast model** — fallback for anything else

Session-over-explicit is a deliberate P12 contract change, not a restatement of the
old rule. The old rule ("explicit always wins") survives beneath the new rung, and
`test_an_explicit_model_argument_still_wins` is retargeted — not deleted — to prove it.

Roles used by the override mechanism: `structured` (query expansion, relevance scoring,
extraction, resolution) and `answer`. Unmapped stages read no override.

## 4. Model identity rules

| Input | Result |
|---|---|
| `ollama/qwen3:4b` | valid → Ollama |
| `gemini/gemini-2.5-flash` | valid → Gemini |
| `gemini-2.5-flash` | valid → canonicalized Gemini identity |
| `qwen3:4b` | **ERROR** — ambiguous bare id |
| `foo/bar` | **ERROR** — unknown provider prefix |

Ambiguous bare IDs must never silently resolve to the configured default provider.
Both errors are raised before any network request and name the fix
(`ModelResolutionError`, `src/rla/errors.py`).

## 5. Ollama performance fact

Measured on this machine, same model/paper/schema/temperature, GPU-resident:

| Route | Prompt tokens | Per paper |
|---|---|---|
| LiteLLM → `/v1/chat/completions` | ~4096 | ~92.6s |
| Native `/api/generate` (`format: <schema>`) | ~662 | ~5–8s |

Measured speedup: **~11.4x.**

Interpretation, stated exactly: **native API ≠ higher intrinsic model TPS.**
Native API = removal of compatibility/prefill overhead. The current decode floor is
roughly **55 tok/s** on the measured GPU — a separate hardware/model throughput concern.
Never route `ollama/…` through LiteLLM. Never claim the native API increases intrinsic
token-generation capability.

## 6. Workstream ownership

### Agent A — Data Integrity

Owns:

- `src/rla/store/extraction_store.py`
- `src/rla/store/graph_store.py`
- `src/rla/pipeline/graph_build.py`
- relevant integrity tests (`tests/test_p4b_integrity.py`, `test_p0_graph.py`, `test_p4_graph_build.py`)
- `rla status`
- committed data reconciliation

Implements **only** `docs/superpowers/plans/2026-10-02-data-integrity-and-reconciliation.md`.
That plan is explicitly independent of P12. Do not implement provider/TUI work. Do not
modify P12 files merely because another change would be convenient.

### Agent B — P12 Provider/Routing

Owns:

- `src/rla/config.py` (routing/model-identity settings only)
- `src/rla/errors.py` (routing error types only)
- `src/rla/llm/*`
- `src/rla/cli.py` (routing surfaces: flags, `doctor`; not TUI widgets)
- provider/routing tests (`tests/test_p12_*.py`, `test_p9_*.py`, `test_p10_*.py` where routing is concerned)
- P12 architecture/docs/ADRs where applicable

Owns the remaining P12 tasks **except TUI implementation**, i.e. Tasks 4, 5, 7–12 as
written. Do not modify `src/rla/tui/*` except by explicit coordination. Note the split
inside P12 Task 6: the router-side pieces (session overrides, `on_fallback`, precedence)
are B's; the panel, widgets and status rows in `src/rla/tui/*` are C's. The interface
between them is `ProviderRouter.set_override` / `clear_overrides` and the `on_fallback`
observer.

### Agent C — TUI

Owns:

- `src/rla/tui/*`
- TUI-specific tests (`tests/test_p7_*.py`, `tests/test_p12_tui_selector.py`)
- TUI-focused documentation

Design requirements live in: P12 spec §8.2 (`docs/superpowers/specs/2026-10-02-multi-provider-routing-design.md`),
P12 plan Task 6 (`docs/superpowers/plans/2026-10-02-multi-provider-routing.md`),
`PLAN.md` P7, and `docs/OPERATIONS_GUIDE.md` §2.3–2.4. Read those, do not re-derive them.

Do not modify: `ProviderRouter`, `MultiBackend`, `factory`, provider backends, core CLI
routing, embedding logic, data-integrity code. If the TUI requires an API/interface that
does not yet exist, report the required interface instead of silently changing routing
architecture. In particular: verify the answer path does not block the Textual event
loop before claiming streaming is complete; if the routing/backend contract must change
to achieve this, report the required interface to Agent B.

## 7. Shared files

These require coordination — announce in your report **before** modifying:

- `README.md`
- `.env.example`
- `PLAN.md`
- documentation shared by multiple workstreams
- `tests/conftest.py`
- `src/rla/cli.py` — Agent A adds the `rla status` command here (data-integrity
  plan, Task 3); Agent B adds routing flags and `doctor` changes here (P12, Task 5).
  Coordinate so the two command sets do not collide.
- `src/rla/pipeline/resolve.py` — belongs to Agent B (merge thresholds, P12 Task 9).
  Agent A reads from it but does not modify it; threshold questions go to B.

## 8. Git/worktree policy

- Each agent works in a separate git worktree/branch. No two sessions edit the same
  checkout simultaneously.
- Branch names: `agent/integrity`, `agent/p12`, `agent/tui`.
- Each logical task gets its own commit.
- No force-push. No rewriting another agent's commit.

## 9. SDD workflow

All implementation agents use `/subagent-driven-development`:

read plan → choose one task → dispatch fresh implementation subagent → review
implementation → run tests → commit → report → continue

A subagent must not silently carry unrelated work from a previous task.

## 10. Conflict rule

If an agent discovers an architectural conflict, an interface mismatch, a dependency on
another agent's unfinished work, a need to modify another agent's ownership area, or a
change to an already-locked contract, it must **STOP and report the conflict** rather
than improvising.

## 11. Testing contract

Every agent runs, before every commit:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q
.\.venv\Scripts\python.exe -m ruff check src/ tests/
```

Do not weaken tests merely to make them pass. Preserve architectural acceptance tests
(A1 structural test, A8 dispatch contract, cache-identity tests).

## 12. Agent reporting contract

Every report contains exactly these sections:

```text
STATUS:

WORK COMPLETED:

FILES CHANGED:

COMMITS:

TESTS:

LINT:

ARCHITECTURAL DECISIONS:

ASSUMPTIONS:

BLOCKERS:

CHANGES REQUIRED FROM OTHER AGENTS:

NEXT TASK:
```

## 13. Integration order

```
Current: P12 Tasks 1–3 ✅

         ┌───────────────┐
         │ Agent A       │
         │ Data Integrity│
         └───────┬───────┘
                 │
                 │ parallel
                 │
         ┌───────▼───────┐
         │ Agent B       │
         │ P12 Routing   │
         └───────┬───────┘
                 │
                 │ interface
                 │
         ┌───────▼───────┐
         │ Agent C       │
         │ TUI           │
         └───────────────┘
```

- Agents A and B may proceed independently.
- Agent C may begin with TUI inspection, tests, layout, and UI scaffolding, but
  routing integration must use the interfaces defined by Agent B
  (`set_override`/`clear_overrides`, `on_fallback`, `role_models`/`resolved_role`).

## 14. Definition of done

The workstreams are not complete merely because individual tests pass. Final
integration must prove, at minimum:

- P12 full suite, data-integrity full suite, TUI tests
- routing integration (per-stage dispatch across providers in one run)
- full pytest green (except the known deferred A8 assertion, until Task 7 lands it)
- ruff clean
- real Ollama path (native `/api/generate`)
- real Gemini path
- cross-provider fallback (fault on one provider served by another)
- fully local path (local text + local embeddings, zero Gemini calls)
- TUI chat with streaming that does not block the event loop
- TUI model selection showing configured / override / resolved
- data integrity protection (stale/superseded store refuses graph creation)

## 15. Explicit non-goals

- no corpus fingerprint yet
- no redesign of graph format
- no arbitrary automatic model-selection heuristics
- no automatic threshold installation (calibration proposes; a human installs)
- no unsupported provider guessing (ambiguous ids raise)
- no intrinsic TPS claims for native Ollama

Do not add anything outside this scope without explicit approval.
