# Retrieval review benchmark

`retrieval_queries.json` is a fixed ten-question Graph Attention Networks set. It covers
overview, comparison, mechanism, lineage, limitations, evaluation, open problems, robustness,
efficiency, and evidence synthesis. The set is a reviewer workload, not a relevance ground truth.

`historical_review_pack.csv` contains 37 unlabeled candidate rows extracted from seven existing
FODS runs (two live, five simulated). Their profile is unknown in the event logs and the questions
do not match the fixed query set, so use this file only for annotation practice, not Quick/Deep
comparison.

## Paired live collection procedure

The first paired collection is 20 live runs: one Quick and one Deep run for each fixed query.
At current profile caps, that can dispatch up to 30 Quick source-query tasks (10 × 3) and 200
Deep source-query tasks (10 × 5 sources × 4 queries), for **up to 230 source requests** before
timeouts, cache reuse, or stop conditions. Use `--fresh-sources` to ensure these are actual
provider requests; check each source's current quota/rate limits before starting. Do not launch
the full set as one unattended batch. Run each Quick/Deep pair close together, retain both event
logs, and record the collection date and source outcomes. Use the deterministic fixture planner
so the collection does not spend Ollama planning calls. With Gemini opt-in unset, the final answer
uses the local evidence formatter and does not spend Gemini quota.

The current CLI has no retrieval-only switch. The live run also performs evidence selection,
citation validation, and brief output; those fields are retained in the review pack. A future
retrieval-only mode would be the smallest change to remove this extra work while preserving the
same source acquisition and runtime validation. Until then, do not describe this as a retrieval-only
benchmark.

Run the same question in both profiles, with separate new output paths and event logs. Example for
one fixed query (repeat for Q01–Q10, pairing the two runs before moving to the next query):

```powershell
$topic = "Graph attention networks"
$question = "How do graph attention methods differ in how they aggregate information from neighbors?"
python -m fods.cli run --topic $topic --question $question `
  --output "data/fods/briefs/Q02-quick.md" --event-log "data/fods/runs/Q02-quick.jsonl" `
  --mode live --planner fixture --profile quick --fresh-sources
python -m fods.cli run --topic $topic --question $question `
  --output "data/fods/briefs/Q02-deep.md" --event-log "data/fods/runs/Q02-deep.jsonl" `
  --mode live --planner fixture --profile deep --fresh-sources
```

After completing all ten pairs, collect the 20 logs once into a new blank-label pack; use a new
output name so human labels from an earlier pack cannot be overwritten:

```powershell
$runLogs = foreach ($i in 1..10) {
  $queryId = 'Q{0:D2}' -f $i
  "data/fods/runs/$queryId-quick.jsonl"
  "data/fods/runs/$queryId-deep.jsonl"
}
python -m fods.benchmark collect --query-set benchmarks/retrieval_queries.json `
  --output benchmarks/paired_review_YYYYMMDD.csv $runLogs
```

Score only after human annotation. A paired set is complete only when all ten questions have both
profiles. The collector makes no source or model calls, preserves blank labels, and refuses to
overwrite an existing review file.

After annotation, score the completed pack:

```powershell
python -m fods.benchmark score --input benchmarks/paired_review_YYYYMMDD.csv `
  --output benchmarks/paired_metrics_YYYYMMDD.json --k 5 10
```

Review each candidate and fill `reviewer_label` with `relevant`, `not_relevant`, or `uncertain`,
plus optional notes. A recall denominator is reported only when every candidate in that query/profile
pool has a binary label and every row is marked `judged_pool_complete=true`. Do not use uncertain
items as binary judgments. Latency is deduplicated by run ID; median and nearest-rank p90 include
their run denominator. Collection supports saved event logs and makes no source/model calls.

Run Quick and Deep live collections explicitly with `fods run`; those can consume source quota.
Record the run logs and do not overwrite them. Fixture/simulated runs verify reproducibility and
the harness only; they are not live retrieval-quality measurements. The current quality verdict is
`PENDING HUMAN REVIEW` because no human labels have been supplied.
