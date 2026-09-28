# FODS_CP - Graph-Based Research Literature Agent

## Environment Setup

### Prerequisites
- Python 3.12+
- `.venv` virtual environment (already configured)

### Activate the Environment
```powershell
# From the project root (FODS_CP)
.\.venv\Scripts\activate.ps1
```

### Install Dependencies
```powershell
pip install -e .
```

### Verify Installation
```powershell
python -c "import rla; print('rla imported successfully')"
```

---

## How to Run It

### 1. Run the Evaluation (P8 Gate)
```powershell
python -m src.rla.cli eval
```

**What you get:**
- `data/eval/report.md` - Markdown report with comparison table and gap validity
- `data/eval/results.json` - Structured JSON output

**Honest results you'll see:**
```
corpus 63 papers | extracted 26 | held out 37
graph 90 nodes / 35 edges | 12 questions | judge: heuristic

Retrieved-evidence comparison (mean over questions)
dimension              graph   rag   delta  favours
citation_validity      1.000       -       -  not comparable
citation_support       1.000       -       -  not comparable
completeness               -       -       -  not comparable (judged)

Gap validity against held-out papers
6 gap(s): 5 refuted, 1 confirmed, 0 no signal, 0 not testable
refuted rate over testable gaps: 83% (higher means the gap analysis is doing worse)

  [refuted] Digital Twin                2024 (11.3) ...
  [refuted] Graph Attention Networks      2025 (5.1) ...
  [refuted] Mobile Edge Computing         2026 (14.2) ...
  [confirmed] Multi-Agent Reinforcement Learning

Extraction accuracy
  NOT MEASURED
  - reference set 'p8-reference' has 0% hand-labelled items

Limitations of this run
  - Node/edge precision and recall are NOT reported. The reference set is not hand-labelled.
  - No LLM judge ran: the Gemini free tier is a per-model daily cap and it is spent.
  - The two arms never surfaced the same paper for any question.
  - The baseline is retrieval-only. It does not generate an answer.
```

### 2. Run the Textual TUI (P7)
```powershell
python -m src.rla.cli tui
```

**What you get:**
- Live terminal UI with status strip, event log, traversal tree, and answer panel
- Keyboard bindings: `q` = Quit, `c` = Clear log
- KIRO-inspired dark theme (CSS restyling)
- Real-time pipeline phase counters and graph metrics

### 3. Run the Test Suite
```powershell
python -m pytest tests/ -q
```

**Result:** 425 passed in ~3 minutes

### 7. Run Lint Check
```powershell
python -m ruff check src/
```

**Result:** All checks passed

---

## Expected Output Types

### From `rla eval`
- **Markdown report** (`data/eval/report.md`): Human-readable comparison and gap analysis
- **JSON output** (`data/eval/results.json`): Machine-readable structured data
- **Console output**: Summary statistics shown during execution

### From `rla tui`
- **Status bar**: Phase strip + elapsed clock + counters (papers, concepts, nodes, edges)
- **Tree view**: Traversal subgraph as tree (concept -> paper attachments)
- **Log panel**: Colored event stream (ok=green, warn=yellow, error=bold red)
- **Answer panel**: Streamed answer text with citation highlights

### From Test Suite
- **425 passing tests** across P0–P8 phases
- Specific test modules test individual pipeline stages (state, app, cli, gaps, report)

---

## Project Structure (Key Directories)

```
FODS_CP/
src/rla/           - Main package
eval/             - Evaluation harness (ground_truth, metrics, etc.)
cli.py            - CLI entry point
tui/              - Textual TUI (app.py, state.py)
pipeline/         - Gap analysis, traversal, orchestrator
store/            - Extraction & graph stores
tests/            - 425 unit tests
data/             - Corpus (63 papers), extractions (26), graph (90 nodes/35 edges)
eval/             - Generated output (report.md, results.json)
README.md         - This file
```

---

## Known Constraints

| Constraint | Status |
|------------|--------|
| Gemini quota exhausted | Heuristic judge only (citation validity/support) |
| No hand-labelled reference set | Extraction accuracy = `NOT MEASURED` |
| 37 held-out papers for gap validation | Structural gaps only (no concept-level precision/recall) |
| Textual TUI (no KIRO migration) | KIRO-style CSS restyling applied |

---

## Development Notes

### Adding New Tests
```bash
# New P8 test example
python -m pytest tests/test_p8_*.py -v
```

### Modifying Evaluation Logic
```bash
# Edit src/rla/eval/run_eval.py for core logic
# Edit src/rla/eval/ground_truth.py for provenance schema
```

### Restyling the TUI
```bash
# Edit src/rla/tui/app.py CSS block for theme changes
```

---

Project complete: P0–P8 verified; P9 documented with KIRO-style CSS restyling.