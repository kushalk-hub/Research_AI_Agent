# FODS product brief

Use this concise brief to design a new research workspace from first principles. It contains product needs and truthfulness rules only; it does not prescribe a visual style, navigation, page layout, or component arrangement.

## What the product does

FODS helps people investigate research questions using academic literature and an agent runtime. A researcher can start an investigation, follow its progress, read an answer grounded in selected evidence, inspect how the system executed, and return to earlier investigations or saved research contexts. A technical user can study the runtime's task dependencies, scheduling decisions, state changes, and event history.

Design a coherent product that serves both audiences without forcing every researcher to understand the execution internals before getting value from research.

## Capabilities to represent

- Create a new investigation with a question, optional topic, and a choice between live research and deterministic synthetic simulation. Advanced configuration may be available for technical users.
- Show empty, loading, active, completed, partially completed, failed, and cancelled investigation states.
- Present the recorded answer/brief, citation identifiers, evidence records, and any saved artifact. Let users inspect the source metadata and exact stored excerpt when one exists.
- Inspect the chronological execution trace with filters, event selection, readable event details, and optional raw event data.
- Explore the agent runtime's task dependency graph, scheduler/queue decisions, task state map, per-task stack operations, and event playback/cursor.
- Browse recorded investigations and saved contexts. Start a replay from a saved investigation and make its provenance clear.
- Work across desktop, tablet, and mobile, with keyboard access and accessible alternatives for visual graph/timeline interactions.

You may organize these capabilities into any original information architecture. Every capability must remain findable. Deliver page/state mockups for the inventory in `MOCKUP_DELIVERABLES.md` and document any assumptions or backend questions in `DESIGN.md`.

## Concepts and data truth

- An investigation is a single run with one submitted question. A draft for a future investigation is separate from any selected historical result.
- Execution can be live research, deterministic simulation, or replay. Replay displays recorded events from a source investigation and does not initiate new research or model work.
- Run identity, question, actual mode, replay origin, answer, citations, evidence, saved brief, and trace must stay associated with the same run or a clearly recorded linked source run.
- Provider/model attribution may appear only when actual use is recorded. A configured model is not evidence that it ran. Unknown values should remain visibly unknown.
- Citation identifier validation does not prove that a source semantically supports a claim. Keep these concepts distinct.
- Evidence text and answer structure must be stored content. Never invent summaries, findings, quotes, excerpts, authors, source identity, or semantic support.
- Event relationships, task durations, worker identity, queue contents, heap snapshots, graph relations, benchmark scores, and quality metrics must not be fabricated. Show a clear unavailable/not-recorded state when evidence is absent.
- A recorded empty queue differs from a queue snapshot that was never recorded. Concurrent execution lanes inferred from timing must be labeled as inferred; do not imply worker identities without them being supplied.
- Task-state and stack views must reflect recorded operations. Incomplete history must be identified as incomplete. Moving backward through playback changes the displayed historical cursor; it does not roll back runtime effects.
- Synthetic simulation content must be clearly identified and must not be presented as live research or evaluation evidence.
- Static mockups must not connect to external services or contain secrets.

## Design freedom

You choose the product name treatment, palette, typography, page hierarchy, navigation, layout, component language, icons, illustrations, density, and responsive transformations. Create a fresh visual identity and original compositions. The only fixed elements are the user needs, capabilities, and truthfulness requirements above.
