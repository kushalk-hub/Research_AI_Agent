# FODS Research Studio Live Demo Guide

**Status:** Reproducible instructions; live acceptance remains blocked until the configured Ollama planner is reachable and the browser workflow can be verified. This document does not claim a live run.

## Isolated local setup

From the repository root in PowerShell:

```powershell
$demoRoot = Join-Path (Get-Location) '.pytest-tmp/fods-live-demo'
New-Item -ItemType Directory -Force -Path $demoRoot | Out-Null
$env:RLA_DATA_DIR = Join-Path $demoRoot 'data'
$env:RLA_RAW_DIR = Join-Path $demoRoot 'raw'
$env:RLA_GRAPH_DIR = Join-Path $demoRoot 'graph'
```

Install the repository's existing environment if needed:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,tui]"
```

Configure providers through the existing `.env`/environment settings. Live planning requires a reachable Ollama server and the configured structured model (currently configured as `ollama/qwen3:4b`). Gemini answering additionally requires `GEMINI_API_KEY` and the explicit `RLA_FODS_ALLOW_GEMINI=1` opt-in. Never paste credentials into the browser, source files, screenshots or logs.

Check the local planner without printing credentials:

```powershell
Invoke-RestMethod http://localhost:11434/api/tags -TimeoutSec 3 |
  Select-Object -ExpandProperty models | Select-Object -ExpandProperty name
```

## Start the production app

In the same PowerShell session, after provider configuration:

```powershell
.\.venv\Scripts\python.exe -m fods.cli serve --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765/`. The app writes only beneath the isolated `.pytest-tmp/fods-live-demo` data root for this session. Use `/?legacy=1` to open the preserved classic workbench.

## Run an investigation

1. In **Research**, enter a narrow, answerable academic question, such as: “How does graph attention assign weights to neighboring nodes, and what limitation did the original GAT paper identify?”
2. Choose **Fresh live research**. Leave **Reuse saved context** unchecked for a new source acquisition.
3. Open **Advanced execution settings** and check **Bypass the source cache for this run** when fresh network retrieval is required.
4. Submit **Start investigation**. The run uses the configured planner and real academic source adapters. Provider failures remain failures in Trace.
5. Inspect the same run ID in Research, Trace, FODS Lab, and Library. Check model/source events, cache policy, citation-ID validation, brief save, persisted JSONL trace and replay.
6. Treat citation-ID validation as ID membership only; it does not establish semantic claim support.

## Current machine readiness

At the latest preflight, the structured planner was configured as `ollama/qwen3:4b`, but Ollama was unreachable. Gemini had a credential configured, while the FODS Gemini opt-in was disabled. The full live browser acceptance therefore has not been run. Do not describe simulation or replay as live source/model evidence.

The Windows Computer Use inventory also reported local browser use disabled in Work settings, so production screenshots and manual browser verification are pending. No firewall, browser privacy or security setting should be changed to work around that restriction.

## Artifacts

- Isolated app data: `.pytest-tmp/fods-live-demo/data/`
- Persisted event logs: `.pytest-tmp/fods-live-demo/data/fods/runs/`
- Briefs: `.pytest-tmp/fods-live-demo/data/fods/briefs/`
- Screenshot status: [`fods_screenshot_inventory.md`](fods_screenshot_inventory.md)
- Acceptance status: [`fods_frontend_acceptance_report.md`](fods_frontend_acceptance_report.md)
