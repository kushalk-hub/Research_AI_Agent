# ADR-0007: Merge thresholds belong to an embedding space

## Status

Accepted (2026-10-02)

## Context

`AUTO_MERGE = 0.92` and `MAYBE_MERGE = 0.70` were calibrated against Gemini's
embedding space. Introducing a second embedding model (a local Nomic model, say)
means those numbers describe a different geometry.

Over-merging is the expensive error in this system: a wrongly fused concept
silently deletes the lineage path between two concepts. Under-merging only leaves
a visible duplicate.

## Decision

Thresholds are stored per **canonical** embedding model id (`Settings.canonical_model`,
`src/rla/config.py:244`; lookup in `thresholds_for`, `src/rla/pipeline/resolve.py:62`).
A model with no entry is `UNCALIBRATED`: automatic merging is disabled entirely,
every candidate above the judge floor becomes eligible for the existing bounded
judge path (subject to the most-similar-first ordering and the `MAX_JUDGE_CALLS`
budget), and the resolve report says so in a `warn` event.

Calibration is a separate, explicit pass (`calibrate`,
`src/rla/eval/merge_calibration.py:114`) that proposes a threshold from the
measured similarity distribution and **installs nothing**.

## Rationale

Failing toward duplicates keeps the failure visible and recoverable. Disabling
auto-merge does not mean every pair is judged — the floor and the budget still
apply, so switching embedding model cannot become unbounded pairwise LLM spend.

Keying by canonical id rather than bare name prevents two providers exposing the
same model name from colliding.

## Consequences

### Positive

- Switching to a new embedding model is safe by default: more duplicates, never a
  fused lineage path.

### Negative

- Resolution is more expensive on an uncalibrated space, because the judge is the
  only merge path. That is the correct direction.

### Neutral

- A threshold is only ever installed by a human committing it.

## Alternatives Considered

- **Reuse the Gemini thresholds for every embedding model.** Rejected: the numbers
  describe one geometry; applying them to another risks silent lineage deletion,
  the one error this system treats as unrecoverable.
- **Auto-install the calibrated threshold.** Rejected: calibration proposes, a human
  installs — automatic installation would trade an invisible duplicate problem for
  an invisible fusion problem.

## References

- `src/rla/pipeline/resolve.py:43` (`MergeThresholds`), `src/rla/pipeline/resolve.py:62`
  (`thresholds_for`), `src/rla/pipeline/resolve.py:274` (`resolve_concepts`)
- `src/rla/eval/merge_calibration.py:114` (`calibrate`)
- `src/rla/config.py:244` (`canonical_model`)
