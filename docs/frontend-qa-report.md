# Frontend and 5-Paper Pipeline QA

Date: 2026-11-15

## Test setup

- Exercised the built React frontend in headless Chrome through Playwright. The user's desktop was not used.
- Live runs were submitted from the frontend with `Papers to keep = 5`, a 300-second provider wait ceiling, and a 100-request per-run LLM budget.
- Run data was isolated in a temporary QA workspace; the committed corpus and extraction files were not used as test inputs.
- Providers available in this environment: Semantic Scholar, OpenAlex, arXiv, DBLP, and Crossref. SerpApi was not configured.
- The configured local models were Ollama `qwen3:4b` and `nomic-embed-text`; the answer role used Gemini `gemini-2.5-flash`.

## Automated checks

- The user-provided earlier run reports **805 passed, 1 skipped**.
- Final full project suite after the frontend limit, extraction-cache, summary, and favicon fixes: **808 passed, 1 skipped** in 138.27 seconds.
- Focused extraction and graph-integrity modules: **41 passed**; the no-corpus and resolution guard checks: **7 passed**.
- Ruff passed for the changed Python source and tests.
- `npm run build` passed. Vite prints a warning that the existing deferred `/shell-core.js` script is external to its module bundle; the built app serves that script separately.

## Live frontend runs at 5 papers

| Run | Topic and question | Result |
|---|---|---|
| `5a1eddb23e7c` | **AI for materials discovery.** “How are machine learning systems accelerating materials discovery, and what bottlenecks still prevent lab validation and deployment?” | Retrieved and selected 5 papers. OpenAlex, arXiv, and Crossref returned papers; Semantic Scholar requests failed and DBLP returned a bot-check HTML page. Extraction failed 0/5 because the configured Ollama server was not running. Graph and answer were skipped. Starting Ollama and checking `rla doctor --llm` resolved the local model availability issue. |
| `768b767de5d8` | **AI for climate modeling.** “How are machine learning weather and climate models improving regional forecasts, and what reliability gaps remain compared with physics-based models?” | Selected 5 papers; extracted 5/5; resolved 17 concepts; built a graph with 22 nodes and 19 edges; generated and saved an answer. Status was partial because Semantic Scholar and DBLP failed. The answer explicitly said the evidence did not address regional forecast performance or reliability gaps. The selected corpus also included weak matches (for example, reanalysis and water-management papers), so answer coverage was low despite a complete graph/answer path. |
| `531f506708f5` | **Long-context language models.** “Which methods extend transformer context windows, and what empirical limitations appear in retrieval, reasoning, and long-range factual consistency?” | Selected 5 papers and extracted all 5, then refused graph construction because 5 old extractions from the climate topic were still present in the append-only store. No answer was generated. This reproduced the stale-extraction failure seen in earlier CLI runs. |
| `f9b53a727f7b` | Same long-context topic and question, after filtering stored extractions by the current corpus. | Continued through resolution and answer, but the graph reported one paper without a matching extraction. Investigation showed that a cached extraction with the same content hash could retain a different provider paper ID. |
| `4bdc49a02c06` | Same long-context topic and question, after rebinding cached extractions to the current paper ID. | Reused all 5 matching extractions, resolved 14 concepts, built a graph with 5 papers and 14 concepts, and saved the answer. Status was partial due source failures. The answer described methods but correctly stated that empirical limitations were not present in the selected evidence. |
| `08d0cfe37fd3` | **AI for materials discovery.** “Which approaches combine machine learning with automated experiments to discover new materials, and what limits successful validation and scale-up?” | The React form exposed a 20-paper maximum and submitted `paper_limit=20`. It scored 60 candidates, selected 20, extracted 20/20, resolved 54 names to 47 concepts, built a graph with 20 paper nodes, and saved an answer. The answer supports ML approaches and a small-data limitation, while explicitly saying the selected papers do not establish how ML is integrated with automated experiments or how validation/scale-up are limited. Citations were not stripped. Several selected records were generic graph-learning papers rather than materials papers, so retrieval precision remains a concern. The run ended partial due Semantic Scholar and DBLP failures. |

The full 20-paper run record and title-level relevance triage are in [qa-20-paper-run.md](qa-20-paper-run.md).

## Deterministic demo and browser check

- Playwright submitted a deterministic demo on **Automated laboratory workflows** and received HTTP 202. It completed with 114 events, a visible evidence-backed answer, and no failed HTTP requests. The demo uses bundled fixtures and does not validate live retrieval quality.
- The page initially logged a missing `/favicon.ico`. Adding the inline SVG icon removed it; a fresh headless Chrome page load reported no console errors or failed HTTP responses.

## Existing-data question check

After the successful long-context graph was built, `rla ask` answered a different question against that graph: “What evidence do these papers provide about length generalization and position interpolation, and which limitations remain?” It traversed the stored graph without re-acquiring papers. The answer said those exact concepts and limitations were not represented, then cited related long-context and benchmark concepts. Citation validation stripped no citations. This is a useful reuse test, while also showing that graph coverage depends on the evidence captured in the original run.

## Fixes made

1. Added `ExtractionStore.for_corpus()` to select records whose paper ID and content hash match the current corpus. Resolution and graph construction now use this current-corpus view while preserving the append-only extraction history.
2. When extraction content is reused by hash for a different provider paper ID, the pipeline now copies the cached facts onto the current paper ID and recalculates the extraction hash. This prevents a “reused” extraction from being counted while remaining unmatched during graph reconciliation.
3. Kept the no-corpus resolution path as a pending/skipped phase instead of asserting. The full suite exposed this guard case.
4. Raised the frontend's configured paper cap to 20. The API returns the cap, and the React input reads it instead of carrying an independent maximum.
5. Extraction summary counts now use only paper IDs and hashes from the current run. The 20-paper run was performed before this counter correction, so its displayed 89-concept summary included historical records; the current-corpus graph count was 47 concepts.

## Remaining findings

- Semantic Scholar was unavailable during these runs; DBLP returned a bot-check page. OpenAlex, arXiv, and Crossref supplied the live results. Runs therefore completed with partial-source status.
- Retrieval and scoring can still select papers that do not answer the user’s exact question. The answer stage abstained when it lacked support, which is safer than inventing details, but query expansion and relevance scoring need later quality work.
- The UI submitted live runs successfully and displayed the answer/evidence. The only browser error found was the missing favicon described above; the corrected page load is clean.
