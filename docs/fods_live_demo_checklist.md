# FODS Research Studio Live Demo Checklist

## Before the demo

- [ ] Use the repository `.venv` and the commands in [`fods_live_demo_guide.md`](fods_live_demo_guide.md).
- [ ] Keep `RLA_DATA_DIR`, `RLA_RAW_DIR`, and `RLA_GRAPH_DIR` pointed at the isolated demo root.
- [ ] Confirm the configured Ollama planner responds and includes the configured model.
- [ ] Confirm the intended answer provider/model and FODS opt-in. Do not expose credential values.
- [ ] Confirm at least two academic source adapters are enabled and reachable.
- [ ] Start the production server and open its production route (not the static prototype).
- [ ] Decide whether this run needs fresh source requests; if yes, enable source-cache bypass.

## During the demo

- [ ] Enter and submit the research question from Research.
- [ ] Record the run ID and mode from the actual server response.
- [ ] Confirm the actual planner/model and source request events in Trace.
- [ ] Confirm task dependencies, queue snapshots, task-state transitions, and stack operations against the selected event cursor.
- [ ] Confirm active concurrent tasks are not represented as named workers; the runtime has no worker IDs.
- [ ] Confirm evidence records, citation IDs, saved brief and trace belong to that same run.
- [ ] Open Library, restore the persisted investigation, and replay its saved event history.
- [ ] Preserve failures as failures; never switch to fixture data and call it live success.

## Current status

This checklist is not yet fully executed. The latest preflight found Ollama unreachable and Gemini FODS opt-in disabled. Local browser use is disabled by Work settings; no production screenshots have been captured.
