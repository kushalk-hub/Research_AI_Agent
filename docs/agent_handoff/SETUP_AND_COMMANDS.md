# Setup and Commands

## 0. Dependency and environment checks

Run these before creating the venv. If any check fails, install the missing tool first.

```powershell
git --version
gh --version
py -3.12 --version
node --version
npm --version
docker --version
```

Ollama is required for the local planner and embedding models (`ollama/qwen3:4b` and
`ollama/nomic-embed-text`):

```powershell
ollama --version
ollama list
```

If `ollama` is missing, install it from https://ollama.com/download and restart the terminal.
If the models are missing, pull them:

```powershell
ollama pull qwen3:4b
ollama pull nomic-embed-text
```

If `ollama list` cannot connect, start the service:

```powershell
ollama serve
```

Playwright needs browser binaries in addition to `npm install`:

```powershell
cd stitch_aesthetic_markdown_reader
npx playwright install chromium
cd ..
```

After the Python venv and frontend dependencies are installed, verify the runtime and sources:

```powershell
.\.venv\Scripts\python.exe -m fods.cli doctor
.\.venv\Scripts\python.exe -m fods.cli sources
```

`doctor --llm` is optional and needs `GEMINI_API_KEY` in `.env`.

## 1. Clone and branch

```powershell
git clone https://github.com/kushalk-hub/Research_AI_Agent.git
cd Research_AI_Agent
git fetch origin
git checkout feature/studio-redesign
git pull --ff-only origin feature/studio-redesign
```

## 2. Python environment

The README's headline command is wrong for a fresh clone. Use the venv.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python.exe -m pip install -e ".[dev,tui]"
```

Copy `.env.example` to `.env`. Leave `GEMINI_API_KEY` blank for keyless degrade mode, or fill it in and run
`rla doctor --llm`.

## 3. Frontend dependencies

```powershell
cd stitch_aesthetic_markdown_reader
npm install
cd ..
```

## 4. Baseline checks (must pass before any edit)

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q
.\.venv\Scripts\python.exe -m ruff check src/ tests/
cd stitch_aesthetic_markdown_reader
npm run build
npm test
npm run test:e2e
cd ..
```

Expected baseline on this branch: pytest `859 passed, 1 skipped`; ruff clean; build green;
vitest `242 passed`; Playwright `11 passed`.

## 5. Serving for manual review

Backend only (old UI in Docker on 8765 is not the new shell):

```powershell
$env:PYTHONPATH = "D:\path\to\repo\src"
.\.venv\Scripts\python.exe -m fods.cli serve --host 127.0.0.1 --port 8877
```

Frontend dev (proxy target is `FODS_API_PORT`, default 8765):

```powershell
cd stitch_aesthetic_markdown_reader
$env:FODS_API_PORT = "8877"
npm run dev
```

Strict CSP is only sent by `fods serve` from a production build, not by Vite dev.

## 6. Commit style

Use a UTF-8 file without a BOM for commit messages:

```powershell
$msg = Get-Content -Raw path\to\message.txt
$path = "$env:TEMP\fods-msg.txt"
[System.IO.File]::WriteAllText($path, $msg, (New-Object System.Text.UTF8Encoding($false)))
git add -A
git commit -F $path
```

## 7. Venv tools, not PATH

The system Python 3.11 lacks `respx` and has an old ruff. Always use `.venv\Scripts\python.exe`.
