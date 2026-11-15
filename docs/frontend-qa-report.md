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
- Final full project suite after the extraction-cache fixes: **807 passed, 1 skipped** in 138.40 seconds.
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

## Existing-data question check

After the successful long-context graph was built, `rla ask` answered a different question against that graph: “What evidence do these papers provide about length generalization and position interpolation, and which limitations remain?” It traversed the stored graph without re-acquiring papers. The answer said those exact concepts and limitations were not represented, then cited related long-context and benchmark concepts. Citation validation stripped no citations. This is a useful reuse test, while also showing that graph coverage depends on the evidence captured in the original run.

## Fixes made

1. Added `ExtractionStore.for_corpus()` to select records whose paper ID and content hash match the current corpus. Resolution and graph construction now use this current-corpus view while preserving the append-only extraction history.
2. When extraction content is reused by hash for a different provider paper ID, the pipeline now copies the cached facts onto the current paper ID and recalculates the extraction hash. This prevents a “reused” extraction from being counted while remaining unmatched during graph reconciliation.
3. Kept the no-corpus resolution path as a pending/skipped phase instead of asserting. The full suite exposed this guard case.

## Remaining findings

- Semantic Scholar was unavailable during these runs; DBLP returned a bot-check page. OpenAlex, arXiv, and Crossref supplied the live results. Runs therefore completed with partial-source status.
- Retrieval and scoring can still select papers that do not answer the user’s exact question. The answer stage abstained when it lacked support, which is safer than inventing details, but query expansion and relevance scoring need later quality work.
- The UI submitted live runs successfully and displayed the answer/evidence. One run emitted a browser console 404 during streaming; a later page-load pass did not reproduce an HTTP error, so the exact transient request remains unidentified.
