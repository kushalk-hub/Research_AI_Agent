# FODS Research Agent: From Question to Evidence-Backed Brief

## 1. Project context and academic purpose

This is a course project for **Fundamentals of Data Structures (FODS)**. Its purpose is to demonstrate the team’s understanding of data structures and algorithms by applying them deliberately inside a small agentic system.

The project is **not** intended to be a production product, a general-purpose autonomous agent, or a clone of Google ADK, Codex, Claude Code, OpenCode, DeepSeek Harness, LangGraph, or any other framework. Those systems are studied as references for patterns that are already used in agent runtimes. Our contribution is an educational implementation that makes the selected data structures, algorithms, and runtime decisions observable and explainable to faculty.

The team will combine its existing understanding of LLM-based agents—reasoning, tool selection, execution, tracing, feedback, and reply loops—with the data-structure concepts taught in FODS.

## 2. Project description

The team will build a fast research-paper agent with an observable FODS runtime. Given a research question, Qwen proposes a structured plan with independent academic-source tasks. The runtime validates the plan, detects cycles, schedules ready tasks, collects and stores reusable evidence, and controls the execution. Qwen can enrich context after it is answerable; Gemini synthesizes the selected evidence into a cited answer; the runtime validates citations and saves the brief only to an explicitly named file inside the approved workspace.

The presentation shows the actual task graph, ready queue, task states, source calls, trace, citation-validation decision, and output result. It distinguishes live source execution, deterministic simulated execution, and replay of a recorded event log. The local browser visualizer and CLI/TUI consume the same runtime events; the browser does not own scheduling or credentials.

## 3. Problem statement

LLM agents can produce plans and call tools, but their internal execution order, task dependencies, retries, and failures are difficult to inspect. That opacity makes it hard to demonstrate how fundamental data structures support agent behavior.

The problem is to design and implement a safe, limited-scope agent runtime in which the plan, ready work, execution context, task state, and recovery behavior are represented by appropriate data structures. The system must visibly demonstrate planning, execution, tracing, bounded recovery, and final response generation—not merely chat or plan generation.

## 4. Objectives

1. Apply FODS concepts as real runtime components rather than decorative labels.
2. Build a working demonstration that accepts an LLM-assisted structured plan and executes a bounded research workflow with controlled source tools and an explicitly scoped output-file tool.
3. Make task dependencies, scheduling, state transitions, tool calls, errors, and retries inspectable.
4. Demonstrate why each selected structure or algorithm is appropriate through repeatable scenarios.
5. Deliver a fast first answerable context from a small, bounded paper set; enrich it incrementally instead of blocking on one LLM extraction per paper.

## 5. Agreed approach

### 5.1 Division of responsibility

| Component | Responsibility |
| --- | --- |
| LLM API | Interpret the request and propose a structured plan, task dependencies, tool choices, priorities, and expected outputs. |
| Project runtime | Validate plans and tool arguments, reject cycles before tools run, schedule source tasks, manage states and traces, enforce retry limits, validate citations, and gate output writes. |
| Research tools | Search one academic source per task, normalize/deduplicate records, retrieve evidence from saved context, and preserve provenance/citation links. The runtime controls dispatch; no hidden multi-source scheduler lives inside a tool. |
| Workspace output tool | Save a cited brief only to an explicitly named path resolved inside the approved workspace, and only after citation validation passes. |
| Interface | Show the plan graph, queue, source calls, context reuse, citation checks, and trace from the shared event stream. |

The key principle is: **the LLM suggests; the FODS runtime governs.**

### 5.2 Core runtime flow

```text
Research question
  → Qwen proposes structured source tasks
  → validate task/tool arguments and dependencies
  → detect cycles and calculate readiness
  → FODS scheduler dispatches independent source tasks
  → normalize, deduplicate, persist reusable evidence context
  → optionally enrich context with bounded Qwen extraction after first context is ready
  → retrieve selected evidence and ask Gemini for the cited answer
  → validate citations against selected evidence
  → save only after validation, or record failure/recovery
  → return answer and a clear run result
```

The plan graph must be acyclic. Retries/replanning are bounded runtime transitions, not dependency cycles. Every retry has a maximum attempt count and a visible termination reason. Citation validation is a prerequisite of the output-file task; failed validation cannot result in a success-marked brief.

### 5.3 Data structures and algorithms

The project will choose structures based on the problem, rather than forcing a fixed list. The following are the current strongest candidates and must be justified in the implementation report.

| Candidate structure / algorithm | Planned use in the agent runtime |
| --- | --- |
| Directed graph / DAG | Store task dependencies and enable sequential, branching, and eventual parallel work. |
| Cycle detection and topological ordering | Reject invalid dependency plans and identify tasks whose prerequisites are complete. |
| Queue | Hold ready tasks under a simple FIFO scheduling policy. |
| Priority queue / heap | Compare with FIFO using a simple, fixed priority rule on the same ready tasks. |
| Stack / trace tree | Represent nested agent/model/tool activity, error returns, and execution history. |
| Hash map / dictionary | Index task state, outputs, retry counters, registered tools, and trace events by identifier. |

The report and demo must explain why each implemented structure is used, what operation it supports, and how it changes observable behavior. If a structure is not useful, it should not be added merely to increase the list.

### 5.4 Task states and recovery

Every task will use explicit state transitions:

```text
planned → ready → running → completed
                       ↘ failed → retry/replan → ready or final failure
```

Failures will be recorded with the tool/action, error details, attempt count, and decision made. The system may retry or submit failure context for replanning only within a fixed policy. It must then give a clear final failure result rather than looping indefinitely.

## 6. Demonstration scope

### Proposed first assessment demo — From research question to evidence-backed brief

1. Qwen proposes a structured research plan with independent academic-source tasks.
2. The FODS runtime validates the plan, rejects cycles, and schedules source tasks using its own DAG, readiness algorithm, and queue.
3. Source results are normalized, deduplicated, and persisted with metadata, abstracts, provenance, and citation links.
4. A follow-up question retrieves supporting evidence and produces a cited answer. Citations are checked against the evidence selected for the answer.
5. The runtime validates and saves the cited brief to an explicitly named file inside the approved workspace.
6. The demo repeats the question using saved context, then demonstrates FIFO vs priority scheduling, cycle rejection, and bounded failure recovery.

The demo distinguishes live source execution, deterministic simulated execution, and replay of a recorded event log. Replay proves event reproducibility, not live scheduler concurrency. If citation validation fails, the brief is not reported as successfully saved and validated; the trace records the failure and chosen recovery action.

The initial context is bounded and answerable from abstracts/citation metadata. Concept extraction is incremental and resumable; first-answer generation does not wait on one model extraction per paper.

### Final expansion

Later expansion may add full-text extraction, broader evidence sets, and additional source adapters. The same FODS runtime remains responsible for validation, scheduling, trace collection, retry policy, citation checks, and final aggregation.

## 7. Demonstration and evaluation scenarios

The demonstration script should include these repeatable cases:

1. **Normal research workflow:** source search → merge/context → retrieve → cite-check → save brief; show graph and topological order.
2. **Parallel-ready sources:** independent academic-source tasks run under the runtime scheduler, then join at normalization/context persistence.
3. **Scheduling comparison:** run the same ready tasks under FIFO and a fixed static-priority rule; explain the changed order.
4. **Invalid plan:** create a cyclic dependency and show rejection before any source or file tool is called.
5. **Controlled failure:** simulate a source/tool failure; show attempts, bounded retry/replanning, blocked dependents, and final reason.
6. **Citation guard:** force a citation absent from selected evidence; show validation failure and that the output write is not marked successful.

Assessment evidence should show correct behavior and explain the selected structures. Report measured time to first context and answer separately from model-load time; do not substitute raw token-generation speed for workflow timing. The FIFO/priority comparison is a required repeatable scenario.

## 8. Milestone plan

| Milestone | Target outcome |
| --- | --- |
| Planning and research | This master plan, source-backed research, scenario list, and data-structure mapping. |
| First assessment | LLM-proposed plan, runtime-owned source-task scheduling, fast reusable evidence context, cited answer, guarded output write, graph/queue/trace visualization, FIFO-vs-priority comparison, cycle rejection, and bounded recovery. |
| Later expansion | Optional full-text enrichment, broader corpora, more source adapters, and improved visualization after the vertical slice is measured. |

Team roles are intentionally flexible. Work may be shared across runtime/data structures, LLM and tool integration, visualization, test scenarios, and documentation, with regular integration review.

## 9. Decisions deliberately deferred

The following implementation parameters remain to be measured or finalized:

- Initial paper cap and first-context latency on the presentation machine.
- Static priority values used in the scheduler comparison.
- Retry/timeout limits for each source tool and whether one bounded replan is enabled.
- The current interactive browser view is implemented. Further UI polish is optional and must not add a second scheduler or claim unimplemented concept extraction.

The first vertical slice now uses a standalone, offline HTML run view generated from the same event log. Live data performance and the presentation-machine paper cap still require rehearsal measurements.

## 10. Research findings and existing-system references

The detailed cited evidence is in [research.md](research.md). Its central findings are:

- Modern agent runtimes cover plan creation, tool execution, state, error handling, traces, and final responses—not planning alone.
- Google ADK and LangGraph validate explicit sequential, parallel, and looped workflow control, as well as visual graph/trace inspection.
- OpenAI Agents SDK and Google ADK demonstrate nested runtime traces; this supports a visible trace tree or stack model.
- OpenCode, Codex, Claude Code, and DeepSeek Harness provide useful references for tool boundaries, state/progress visibility, agent coordination, and traceable event logs.
- The project must distinguish between documented facts about those systems and the team’s own data-structure design choices. A DAG, queue/priority queue, stack, and map are proposed educational choices—not claims about another system’s hidden internals.

## 11. Reference sources

The full annotated source list is in [research.md](research.md). Principal sources include:

- [Google ADK workflow agents](https://github.com/google/adk-docs/blob/main/docs/agents/workflow-agents/index.md), [Web Interface](https://adk.dev/runtime/web-interface/), and [traces](https://adk.dev/observability/traces/)
- [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/use-graph-api) and [fault tolerance](https://docs.langchain.com/oss/python/langgraph/fault-tolerance)
- [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/agents/) and [tracing](https://openai.github.io/openai-agents-python/tracing/)
- [OpenCode source](https://github.com/anomalyco/opencode) and [tool architecture](https://github.com/anomalyco/opencode/blob/dev/packages/core/src/tool/AGENTS.md)
- [OpenAI Codex source](https://github.com/openai/codex)
- [Claude Code overview](https://code.claude.com/docs/en/overview)
- [DeepSeek Harness](https://deepseek.com/harness/en/)
