# FODS Research Studio static prototype

This prototype is a standalone, offline visual review artifact. It uses only bundled synthetic data. It does not contact the FODS backend, use a model, search academic sources, persist runs, or make retrieval-quality claims.

## Open it

Open `index.html` directly in a current browser. It can also be served as static files by any local file server. Start page view: `index.html`; completed example: `index.html?view=completed`; trace: `index.html?view=trace`; FODS Lab: `index.html?view=lab`. Lab subviews: `?view=lab&lab=scheduler&event=5` and `?view=lab&lab=state&event=8`.

The research composer is intentionally non-submitting: its button displays a notice that no research run was started. The completed brief opens from the synthetic recent investigation. The recovery lesson explicitly says this event set contains no failure/retry events rather than inventing them.

## Genuine browser captures

Screenshots below were captured from the standalone HTML in the installed Google Chrome headless browser at 1600×1200 on 2026-11-01. The recovery image shows the prototype's explicit limitation note; it is not a recovery demonstration.

- [Research empty state](screenshots/research-empty.png)
- [Completed synthetic brief](screenshots/research-completed.png)
- [Trace event history](screenshots/trace.png)
- [FODS Lab dependency DAG](screenshots/fods-lab-dag.png)
- [Scheduler and inferred concurrency](screenshots/fods-lab-scheduler.png)
- [Task-state dictionary and stack](screenshots/fods-lab-state.png)
- [Library of investigations and contexts](screenshots/library.png)
- [Recovery lesson limitation note](screenshots/fods-lab-recovery-note.png)

These captures show the static design prototype, not the production application.
