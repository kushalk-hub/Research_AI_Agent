# FODS Demonstration Setup Checklist

## Environment

- [ ] Use the repository root and the project virtual environment. Python 3.12 is the verified CI version; the project requires Python 3.11 or newer.
- [ ] If setting up a fresh checkout, install the project and development/UI extras: `.\.venv\Scripts\python.exe -m pip install -e ".[dev,tui]"` (run from PowerShell; omit `tui` only if not using it).
- [ ] Keep `.env` private and use `.env.example` as the variable reference. Do not put provider keys in slides, traces, screenshots, shell history, or committed files.
- [ ] Confirm `python -m fods.cli --help` and command-specific help work before the presentation.

## Choose the demonstration path

### Recommended: deterministic fixture run

- [ ] Use `--mode simulate --planner fixture` for repeatability and no provider calls.
- [ ] Use a new, explicit brief filename. The run command requires topic, question, and workspace-relative `--output`.
- [ ] The exact accepted CI command is shown in [the assessment guide](fods_assessment_demo_guide.md). It passed in GitHub Actions and generated a brief, JSONL trace, and HTML visualization. Download the `fods-mvp-acceptance` artifact from [workflow run 41296050154](https://github.com/kushalk-hub/Research_AI_Agent/actions/runs/41296050154) if the files are needed locally; `data/fods/` is ignored and these CI files are not in this checkout.
- [ ] For a local fallback already available in this checkout, use run `5f0bf2d0b68d` (brief, JSONL and HTML). It is deterministic fixture simulation with a different topic (`FODS ready-queue comparison`), and is not the CI acceptance run.

### Optional: live providers

- [ ] Confirm academic source network access, configured provider readiness and rate/quota availability.
- [ ] For Ollama planning, start Ollama separately and verify the required model is installed (for example `ollama list` includes `qwen3:4b`); set `RLA_STRUCTURED_MODEL=ollama/qwen3:4b` as appropriate.
- [ ] Live source calls are separate from planner model calls. Set `--mode live`; choose `--planner ollama` only when Ollama is ready, or `auto` if configured fallback behavior is intended.
- [ ] For Gemini answer synthesis, configure `GEMINI_API_KEY` and explicitly set `RLA_FODS_ALLOW_GEMINI=1` in the server/CLI process before launching the run. A configured key alone is not opt-in.
- [ ] Rehearse live mode in advance. Do not switch to it during the assessment if sources, quota, or models are uncertain.

## Corpus and saved artifacts

- [ ] Check the topic context you intend to reuse in the workbench or `data/fods/topics/`.
- [ ] A fixture run can start without a prior saved context; it creates its own deterministic context.
- [ ] Know the output paths: brief in `data/fods/briefs/`, JSONL trace and HTML replay in `data/fods/runs/`.
- [ ] Do not overwrite original enrichment records or the original Graph Attention Networks graph. The graph demo uses an isolated data root at `.pytest-tmp/mvp-existing-context-demo-99861ac9`.
- [ ] Treat the isolated graph as a separate CLI demonstration, not part of the fixture run. Graph build/follow-up are optional and do not run as part of an ordinary brief request.

## Browser workbench

- [ ] From the repository root, start the local server: `.\.venv\Scripts\python.exe -m fods.cli serve --host 127.0.0.1 --port 8765`.
- [ ] Open `http://127.0.0.1:8765/` and confirm the five tabs load: Overview, Execution, FODS Lab, Evidence & answer, Runs & replay.
- [ ] Submit a short deterministic fixture run with a new filename. Verify events, evidence cards, citation-ID status and the saved brief.
- [ ] Rehearse one FODS Lab demonstration (cycle rejection, bounded source failure, citation guard, or FIFO vs priority) and confirm it behaves as labeled.
- [ ] If local loopback is denied, stop here. Do not change firewall, antivirus, or security settings. Use the saved HTML/JSONL/brief fallback or the downloaded CI bundle.

In this environment, the server startup command was verified and printed its listening URL. The browser request to `127.0.0.1:18765` timed out and a PowerShell HTTP request was denied by Windows (`WSAEACCES`). Therefore the workbench has **not** been successfully rehearsed interactively here; startup alone is not proof of browser access.

## CLI validation and rehearsal

Commands below are verified in this environment unless explicitly marked as setup-dependent:

```powershell
.\.venv\Scripts\python.exe -m fods.cli run --help
.\.venv\Scripts\python.exe -m fods.cli serve --help
.\.venv\Scripts\python.exe -m fods.cli replay --help
.\.venv\Scripts\python.exe -m fods.cli graph --help
.\.venv\Scripts\python.exe -m fods.cli replay ".pytest-tmp\docs-demo-replay\5f0bf2d0b68d.jsonl"
```

The replay command above was executed on a copy of the local trace. It printed `REPLAY ONLY` and produced an HTML file inside `.pytest-tmp/docs-demo-replay/`; the original run artifacts were not modified. The fixture acceptance command was executed in CI, not in this Windows session. A local fixture run is documented but should not be labeled locally verified here because loopback access is restricted.

For the isolated graph demonstration, use the exact read-only stats/follow-up commands in [the demo script](fods_live_demo_script.md). They were executed with `RLA_DATA_DIR` pointed at the isolated copy, and returned the recorded counts and evidence described in the artifact inventory.

## Rehearsal checklist

- [ ] Start with the research question and explain the expected scope.
- [ ] State whether the run is simulation, live retrieval, or replay before showing results.
- [ ] Show plan validation and task dependencies before scheduler details.
- [ ] Show one actual queue policy and explain that FIFO/priority dequeue order is recorded by runtime events.
- [ ] Show evidence cards and citation-ID validation; state clearly that IDs matching is not semantic entailment.
- [ ] Open the brief and then inspect or replay the matching trace.
- [ ] If showing the graph, state that it is a separately built snapshot from saved enrichment and that shared labels mean vocabulary overlap.
- [ ] Keep a local copy of artifacts and confirm paths before the presentation; do not depend on Actions being reachable during the talk.
- [ ] State that backend CI acceptance passed while the human-reviewed retrieval benchmark remains pending.

## Fallback plan

If live sources or models are unavailable, use fixture simulation or the accepted CI run. If the browser cannot reach the local server, open the already-generated HTML visualization, JSONL trace, and matching brief. The local fallback set is `data/fods/runs/5f0bf2d0b68d.html`, `data/fods/runs/5f0bf2d0b68d.jsonl`, and `data/fods/briefs/5f0bf2d0b68d.md`; the CI acceptance set has run ID `a358ed9efa63` and can be downloaded from workflow artifact `fods-mvp-acceptance`. Do not imply the local fallback is the CI run or that replay re-executed sources/models.
