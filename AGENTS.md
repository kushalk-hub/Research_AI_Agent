# AGENTS.md

Graph-based research literature agent (`rla`). Windows/PowerShell, Python 3.11+ (`pyproject.toml`).

## Setup: use the venv, and note the README's commands are wrong

`src/` is a src-layout package, and `src/rla` imports itself as `rla` (never `src.rla`).
`python -m src.rla.cli eval` — the README's headline command — fails with
`ModuleNotFoundError: No module named 'rla'`. The README also claims a `.venv` was already
configured; it was not, and it does not exist in a fresh clone.

The venv now exists (Python 3.12, the version `PLAN.md` §1 records as verified):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1          # or prefix commands with .\.venv\Scripts\
.\.venv\Scripts\python.exe -m pip install -e ".[dev,tui]"
```

`.env` exists as a copy of `.env.example` with `GEMINI_API_KEY` blank, so the pipeline runs
in keyless degrade mode (acquisition works, LLM stages are skipped). Fill in the key to
enable extraction/resolution/answering; `rla doctor --llm` verifies it against the live API.

**Use the venv's tools, not the ones on PATH.** The system Python 3.11 lacks `respx` (so
`test_p1_acquisition.py` fails to collect) and its `ruff` is 0.1.14, which reports 3 false
`UP038` hits that vanish under the pinned `ruff>=0.5`. Correct baseline, in the venv:

```powershell
python -m pytest tests/ -q          # 425 passed in ~54s
python -m pytest tests/test_p8_gap_validity.py -v   # one module
python -m ruff check src/           # All checks passed
```

Ruff config: line-length 100, `select = ["E","F","I","UP","B"]`.

## Commands

| Command | Reads | Needs a key? |
|---|---|---|
| `rla doctor [--llm]` | config, sources, cache | `--llm` does a live call, deliberately **uncached** |
| `rla sources` | probes every source against a throwaway cache DB | no |
| `rla build -t "…"` | acquisition (P1) | no — keyless sources |
| `rla ask "…"` | `data/graph/graph.json` only; no re-acquisition | yes for the answer |
| `rla report` | corpus + extractions + graph | no — every claim traces to a stored extraction |
| `rla run [--jsonl]` | full pipeline, streams `Event`s | degrades without a key |
| `rla tui -t "…"` | same event stream as `rla run` | needs `textual`; **Windows Terminal**, not conhost |
| `rla eval` | writes `data/eval/report.md` + `results.json` | no |

`rla eval` crashes with `FileNotFoundError` if `data/graph/graph.json` is absent. That path is
**gitignored** (`.gitignore` line `data/graph/`), so a fresh clone must run `rla run`/`rla build`
first. Relatedly, `.gitignore` has `eval/report.md` (root-relative) while the real output is
`data/eval/report.md`; the committed `data/eval/*` files are tracked despite that rule.

## Architecture

`src/rla/`: `cli.py` (typer) · `config.py` · `models.py` (pydantic) · `events.py` ·
`llm/` (base protocol, `gemini.py`, `embeddings.py`, `retry.py`, `prompts/templates.py`) ·
`sources/` (5 keyless adapters + key-gated `serpapi` + `dedup.py`) ·
`pipeline/` (query_expansion, acquisition, scoring, extraction, resolve, graph_build, traverse,
gaps, answer, orchestrator) · `store/` (SQLite cache, extraction_store, graph_store) ·
`eval/` (ground_truth, metrics, baseline_rag, judge, gap_validity, run_eval) · `tui/`.

Two invariants worth knowing before editing:

- **One event stream.** `Pipeline.run()` yields `Event(phase, kind, message, payload)`; stages
  take an `Emitter` rather than yielding themselves. `rla run --jsonl` and `rla tui` subscribe to
  the same generator, so they cannot drift. Phase order is `PIPELINE_PHASES` in `events.py` (10
  slots, asserted by the 80×24 TUI frame tests) and must include `FULLTEXT` even though that
  stage is a phase-2 stub.
- **Everything outbound goes through the SQLite cache.** Cache keys include `prompt_hash(prompt)`,
  so editing `llm/prompts/templates.py` invalidates exactly the calls that used it. A re-run must
  be able to complete with zero network calls. `llm/prompts/` is `.py`, not prompt files.

## Gotchas

- **Free-tier quota is per day, per model** (20 req/day observed), not per minute. `llm_rpm=15`
  pacing does not help. `llm/retry.py:is_daily_quota` detects it and fails fast; `llm_daily_budget`
  (default 15) is a local per-run cap. Cached calls are never charged. Do not "fix" a 429 by
  increasing retries.
- **Entity resolution must fail toward duplicates, not toward false lineage** — an over-merge
  silently deletes a lineage path. Tiers: normalised name → cosine ≥ 0.92 auto-merge → LLM judge
  in the band between. A judge failure or refusal never merges. Every decision/refusal is logged
  to `data/concepts.json` under `decisions`.
- **Edge direction is `A --EXTENDS--> B` = "B builds on A"** (parent → child, child strictly
  newer). Lineage edges are anchored only on concepts a paper *introduces*. Reversing this
  deletes every legitimate edge while keeping the impossible ones.
- **Extraction is content-hash resumable**; a changed abstract invalidates its stored extraction,
  and a corrupt `extractions.jsonl` line is skipped, not fatal.
- Citations in generated answers are validated against the traversed subgraph; unsupported IDs
  are stripped and reported in `stripped_citations`.
- Env prefix is `RLA_`, except `GEMINI_API_KEY`, which has an explicit no-prefix alias. `config.py`
  resolves `.env` and `data/` relative to `parents[2]`, not the CWD.

## Testing

- `pyproject.toml` sets `asyncio_mode = "auto"` and `testpaths = ["tests"]`; no `@pytest.mark.asyncio`.
- `tests/conftest.py` `settings` fixture redirects every path to `tmp_path`, zeroes
  `s2_delay_seconds`, and sets `max_retries=1`. Tests must not touch `data/`.
- `rla.llm.retry` keeps a process-global limiter/sender keyed to the running event loop; use
  `reset_limiter()` / `reset_spender()` between tests that call `asyncio.run` repeatedly.
- Test modules are named `test_p<N>_*.py` after the `PLAN.md` milestone they gate, not after the
  module under test.

## Evaluation honesty rules

`eval/run_eval.py` is the P8 gate and encodes non-negotiable rules: nothing is reported as
measured when it was not (no node/edge precision/recall — the shipped reference set has 0%
hand-labelled items), every score states its judge kind (heuristic vs LLM), unfavourable results
get equal prominence, coverage/denominator is printed next to every mean, and both arms get
symmetric evidence. `eval/ground_truth.py:assess_reference_set` refuses to report metrics for a
reference set that was not hand-labelled. Do not paper over a `NOT MEASURED` row.

`data/corpus.json`, `data/extractions.jsonl`, and `data/concepts.json` are **committed on
purpose** so eval numbers reproduce. Do not regenerate or reformat them casually.

## Repo noise

`full_test.out`, `run.log`, `results.txt`, `results2.txt`, `test_out.txt`, `test_output.txt`,
`test_p8_gap.out` are committed scratch output from past runs, not sources. Ignore them; don't
add more.

`PLAN.md` is the authoritative spec and gate-by-gate status (it records which milestones are
"implemented, gate unverified" because of the missing API key). `research-literature-agent-project-final.md`
is the read-only original spec; `PLAN.md` section numbers refer to it.
