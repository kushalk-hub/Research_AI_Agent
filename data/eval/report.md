==========================================================================
rla eval - graph vs RAG-over-abstracts
==========================================================================
corpus 100 papers | extracted 0 | held out 100
graph 206 nodes / 323 edges | 12 questions | judge: heuristic

Retrieved-evidence comparison (mean over questions)
--------------------------------------------------------------------------
dimension              graph     rag   delta  favours
citation_validity          -       -       -  not comparable
citation_support           -       -       -  not comparable
completeness               -       -       -  not comparable (judged)

Gap validity against held-out papers
--------------------------------------------------------------------------
no gaps were available to check

Extraction accuracy
--------------------------------------------------------------------------
  NOT MEASURED
  - reference set 'p8-reference' has 0% hand-labelled items

Limitations of this run
--------------------------------------------------------------------------
  - Node/edge precision and recall are NOT reported. The reference set is not hand-labelled, so a number computed against it would measure the generator against itself. See the reference-set section.
  - No LLM judge ran: the Gemini free tier is a per-model daily cap and it is spent. Correctness and completeness are therefore not scored at all. The citation numbers are mechanical and are labelled as such; they are not substitutes for a judge's opinion.
  - The two arms never surfaced the same paper for any question. That is a finding about the two retrieval strategies, not a quality result.
  - The baseline is retrieval-only. It retrieves and shows abstracts; it does not generate an answer, because generating one needs the same LLM budget that is unavailable. The graph arm is likewise given its subgraph as text. This is a comparison of retrieved evidence, not of answer quality.
==========================================================================