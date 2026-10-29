# Retrieval benchmark baseline

## Query set and current verdict

The fixed query set is [`benchmarks/retrieval_queries.json`](../benchmarks/retrieval_queries.json).
It contains ten distinct research intents for Graph Attention Networks. The annotation schema is
[`benchmarks/retrieval_review_template.csv`](../benchmarks/retrieval_review_template.csv).
No human relevance labels are included. Therefore retrieval quality is **PENDING HUMAN REVIEW**;
there are currently no defensible precision or recall claims.

A preliminary annotation file was generated from the existing, preserved FODS logs at
[`benchmarks/historical_review_pack.csv`](../benchmarks/historical_review_pack.csv): 37 unique
candidate rows across seven existing runs (two live, five simulated). The historical events do not
contain a Quick/Deep profile field, so all seven are marked `unknown`; the questions do not cover
the fixed ten-query set. These rows are useful for reviewer practice, not a paired profile baseline.
The saved scorer output is [`benchmarks/historical_review_metrics.json`](../benchmarks/historical_review_metrics.json):
0/37 reviewed, precision@5 and @10 withheld, recall withheld, three-source diversity, 11.9% observed
duplicate rate (37 unique paper rows from 42 source observations), 94.6% abstract coverage, and
zero candidate truncation. The event traces record 24 selected evidence papers and 17 cited papers;
all seven runs passed citation-ID validation. Across the seven mixed-mode historical runs,
acquisition median/p90 was 68.9/1,719.8 ms and total median/p90 was 96.7/20,363.1 ms. These are
historical runtime measurements with unknown profile and mixed live/simulated modes; they do not
compare Quick and Deep or establish retrieval quality. This checkout has no Quick/Deep measured
candidate or evidence counts yet.

## Frozen collection procedure

The collector consumes saved FODS JSONL events and performs no live calls. Save the Quick and Deep
event logs from the same source snapshot date, retain both logs, then collect one CSV review pack.
The collector retains paper identity and metadata, abstract excerpt, source/query provenance, rank,
evidence citation IDs, source outcomes, candidate counts/truncation, cache policies, and timings.
The scorer reports denominators for reviewed candidates and precision@5/@10. Recall is withheld
unless the judged pool is complete and all its labels are binary. Per-profile medians and nearest
rank p90s are measured across unique run IDs. Missing run logs, unavailable sources, or missing
timings remain missing; they are not filled with estimates.

## Measurements available in this checkout

The fixture suite validates event parsing, blank annotation fields, and the no-fabricated-label
scoring rule. Fixture outcomes are not measurements of live retrieval quality. No paired live
Quick/Deep benchmark run was made as part of this implementation pass, so candidate counts and
latency are not presented as a live profile baseline. The historical candidate count above is a
pack size, not a measured relevance or improvement result. Preserve the first matched live Quick/
Deep pack from the fixed query set before comparing later retrieval changes.

Phase 2.1 also ran a separate bounded OpenAlex reference-discovery smoke test against an existing
six-paper context. It resolved five references from two seeds in 1.32 seconds and saved a verified
child snapshot; this tested the one-hop reference workflow, not Quick/Deep retrieval quality. It is
not included in the historical review pack. The enrichment smoke test was blocked because the
configured local Ollama endpoint did not respond. No Gemini call was made.

Before collecting all ten paired questions, budget for up to 230 live source-query requests:
30 Quick (10 questions × 3 sources) plus 200 Deep (10 × 5 sources × 4 queries). Actual counts may
be lower when the runtime stops early or a request fails. The CLI does not currently expose a
retrieval-only run; the documented protocol uses `--planner fixture` and leaves Gemini opt-in off,
so it avoids LLM quota while retaining the normal evidence selection, citation gate, and brief
write. See [`benchmarks/README.md`](../benchmarks/README.md) for the paired run procedure. The
20-run collection remains **PENDING OPERATOR BUDGET REVIEW** and human relevance labels remain
**PENDING HUMAN REVIEW**.
