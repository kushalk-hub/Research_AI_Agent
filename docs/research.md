# Agent-runtime patterns for a Fundamentals of Data Structures project

**Purpose.** This evidence scan identifies a defensible course-project direction: an agent runtime in which data structures are visible, necessary parts of planning, execution, tracing, retry, and response—not labels added after the fact. It is research input, not a final technical-stack decision.

**Research boundary.** Sources below are primary documentation or source repositories owned by the relevant framework projects. Claims about *our proposed implementation* are clearly marked as proposals; they are not claims that a framework internally uses a particular data structure.

## What current agent runtimes demonstrate

### 1. An agent runtime is more than a planner

Agent runtimes coordinate model turns, tool calls, routing/handoffs, execution state, error handling, and a final response. For example, the OpenAI Agents SDK describes its runner as managing turns, tools, guardrails, handoffs, and sessions; its built-in traces record model generations, tools, handoffs, guardrails, and custom events [OpenAI Agents SDK—Agents](https://openai.github.io/openai-agents-python/agents/), [Tracing](https://openai.github.io/openai-agents-python/tracing/). This supports the project’s intended scope: **plan → execute → observe/trace → recover or reply**, rather than a chatbot that only creates a plan.

Google ADK explicitly distinguishes deterministic workflow control from LLM reasoning: its documented workflow patterns run sub-agents sequentially, in parallel, or in a termination-controlled loop without consulting an AI model for orchestration [Google ADK workflow agents](https://github.com/google/adk-docs/blob/main/docs/agents/workflow-agents/index.md). ADK 2.0 documentation also points users toward graph-based and dynamic workflows for greater control [same source](https://github.com/google/adk-docs/blob/main/docs/agents/workflow-agents/index.md).

### 2. Visualisation is a legitimate first-class feature

The proposed visual runtime view is well grounded. Google ADK Web provides a chat interface, session and state inspection, event history, a visual workflow builder, execution-trace/event-log viewers, and an agent-structure graph view [Google ADK Web Interface](https://adk.dev/runtime/web-interface/). ADK traces are nested spans: an agent-run root contains LLM spans which may contain tool spans, producing a waterfall view of a reasoning loop [Google ADK Traces](https://adk.dev/observability/traces/).

LangGraph documentation likewise shows graph execution as named nodes and edges, supports rendering a graph, and documents fan-out/fan-in parallel execution [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/use-graph-api). Therefore, a UI which shows both (a) the **planned dependency graph** and (b) the **live execution trace** is useful and comparable in spirit to real agent-development tooling. It should be described as an educational runtime visualizer, not as a copy of ADK.

### 3. Retry and reply loops are real runtime behaviour

LangGraph documents per-node retry policies, timeouts, and recovery handlers; retries decide first, then recovery runs after attempts are exhausted [LangGraph fault tolerance](https://docs.langchain.com/oss/python/langgraph/fault-tolerance). It also gives the exact pattern relevant to the course project: save a tool error in state and route back so the model can see the failure and try again [Thinking in LangGraph](https://docs.langchain.com/oss/python/langgraph/thinking-in-langgraph).

This validates a bounded feedback loop in the demonstration: tool result or error becomes a runtime event, then the agent either selects another action, retries under policy, asks the user for clarification, or produces the final reply. Loops must have a maximum attempt/step limit and a visible termination reason.

## Data structures that earn their place

| Structure / algorithm | Proposed runtime responsibility | What the demo should make visible | Evidence / caution |
| --- | --- | --- | --- |
| **Directed graph / DAG** | Represent plan steps as vertices and prerequisites/routing conditions as edges. Validate dependencies; obtain a valid prerequisite-respecting schedule with **topological sort**. | Graph before execution; highlight completed, ready, running, failed, and blocked nodes. | Agent frameworks model workflows as nodes/edges and support fan-out/fan-in [LangGraph](https://docs.langchain.com/oss/python/langgraph/use-graph-api). A *DAG* is our proposal for the initial prerequisite plan—not a claim that all agent workflows are DAGs. |
| **Queue** | Hold ready, same-priority tasks awaiting execution; FIFO makes the policy simple and explainable. | Enqueue/dequeue animation, queue length, and why each task became ready. | A queue is a sound explicit implementation choice. As a concrete (but version-specific) precedent, ADK’s Python parallel-agent source uses `asyncio.Queue` to merge concurrent sub-agent event streams [source](https://github.com/google/adk-python/blob/main/src/google/adk/agents/parallel_agent.py). This is **not** evidence that its overall task scheduler is FIFO. |
| **Priority queue / heap** | Select from ready tasks by urgency, estimated cost, user priority, dependency depth, or retry time. | Heap/ordered-ready view; compare it with FIFO for the same plan. | This provides a measurable DSA choice. It must be presented as *our scheduler policy*, not asserted as an ADK/LangGraph implementation detail. |
| **Stack** | Maintain nested execution frames—agent → model turn → tool call—and optionally a compensation/undo history for safe reversible tools. | Current call stack and push/pop events; a failed nested tool returns control to its caller. | ADK and OpenAI document hierarchical/nested spans [ADK](https://adk.dev/observability/traces/), [OpenAI](https://openai.github.io/openai-agents-python/tracing/). A stack is an appropriate implementation/teaching model, not a documented framework internal. |
| **Tree** | Represent plan decomposition (parent task → subtasks) and the trace hierarchy (root run → agent/model/tool spans). | Expandable execution tree beside the dependency graph. | Trace parent/child hierarchy is documented by ADK and OpenAI tracing [ADK](https://adk.dev/observability/traces/), [OpenAI](https://openai.github.io/openai-agents-python/tracing/). |
| **Hash map / dictionary** | Index task state by ID, store results, attempts, tool metadata, and trace records. | Task detail lookup and trace/event correlation by ID. | This is a practical supporting structure; it should be briefly documented but not distract from the three core assessed structures. |
| **Cycle detection** | Reject accidental cyclic prerequisite plans before scheduling. | A clear “invalid plan: cycle detected” explanation. | Necessary if topological ordering is used. Reflection/retry loops should be runtime transitions with bounds, not unbounded dependency cycles in the initial DAG. |

## Recommended conceptual architecture for the first demonstration

```text
User request
    ↓
LLM planner / router ── produces structured tasks, dependencies, and tool choices
    ↓
Plan validator ── cycle detection + topological readiness calculation
    ↓
Ready queue / priority queue ── selects next executable task
    ↓
Executor ── calls LLM or a safe tool (read file first; writes only with approval)
    ↓
Event log + trace tree + task-state map ── UI/CLI visualises every transition
    ↓
Result evaluator ── success → final reply; transient failure → bounded retry; unclear input → ask user
```

The diagram separates two ideas which should not be conflated:

1. The **plan DAG** answers “what must happen before what?” and enables topological scheduling.
2. The **runtime transition graph** includes retry, reflection, approval, and reply paths. It may contain controlled cycles, but each cycle needs a bound and a recorded exit condition.

For independent ready tasks, a later milestone can run work in parallel. Existing workflow runtimes demonstrate fan-out/fan-in: LangGraph executes parallel branches concurrently and runs the joining node only after both finish [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/use-graph-api). The course runtime can first simulate this in a deterministic mode, then add real parallel workers once task-state concurrency is safe.

## Focused academic project claim

> **Proposed problem statement:** LLM agents can choose tools and generate plans, but their control flow is often difficult for learners to inspect and explain. For a Fundamentals of Data Structures course project, build a small, safe agent runtime that represents task dependencies explicitly, schedules ready tasks through justified queue policies, traces nested execution, and demonstrates bounded retry/reply loops. The purpose is to demonstrate the team’s understanding of data structures and algorithms through an agentic-system application, not to claim a production framework or a new agent architecture.

This creates an evaluable distinction from “an LLM wrapper”: swapping FIFO and priority scheduling changes the observed execution order; introducing a dependency edge changes readiness; a failure changes retry state and trace; a cyclic plan is rejected; and each effect can be shown to an assessor.

## Existing systems examined as references

These systems are references for observable patterns, terminology, and interface ideas. The course project must implement its own compact orchestration engine; it must not copy their codebase or claim to reproduce their internals.

| System | What the team can learn from it | Boundary for this project |
| --- | --- | --- |
| **Google ADK** | Deterministic sequential, parallel, and loop workflow patterns; visual workflow and trace inspection. | Use the documented concepts as inspiration; do not depend on ADK as the core engine. |
| **LangGraph** | Explicit nodes and edges, fan-out/fan-in, retry and recovery patterns. | Use as an architectural reference; implement the selected graph and scheduler logic ourselves. |
| **OpenAI Agents SDK** | A runtime needs more than planning: tools, handoffs, sessions, traces, and final responses are part of the execution loop. | Reference its public documentation only; the project runtime remains independent. |
| **OpenCode** | An open-source coding agent with explicit build/plan modes, a general subagent, tool registration, scoped tool lookup, permission declarations, and bounded tool outputs. | Study only small patterns such as a tool registry and clear tool boundaries; do not build a coding-agent clone. |
| **Codex** | Its public source and guidance illustrate visible planning, task-status transitions, tool execution, and progress updates. | Treat it as a broad agent-harness reference, not a template for the course architecture. |
| **Claude Code** | Its official documentation illustrates planned execution, tool/MCP integration, configurable hooks, and a lead agent coordinating parallel subagents. | Use behavior documented publicly; no internal implementation claim is made. |
| **DeepSeek Harness** | It offers an especially relevant reference for the proposed trace view: an append-only session log records prompts, reasoning, tools/results, scheduling, and context injections; its UI reconstructs a run from that event stream. | Adopt the educational idea of a traceable event log, but build only the minimal structures needed for the course demonstration. |

### Source-supported observations from the additional references

- The [OpenCode repository](https://github.com/anomalyco/opencode) identifies itself as an open-source coding agent and documents separate build and read-only plan agents plus a general subagent. Its [tool-architecture notes](https://github.com/anomalyco/opencode/blob/dev/packages/core/src/tool/AGENTS.md) describe canonical tool registration, scoped lookup, permission declarations, invocation, and output bounding. The course project can study this as evidence that tool execution benefits from an explicit registry and clear side-effect boundaries.
- The [OpenAI Codex source repository](https://github.com/openai/codex) contains guidance requiring a plan before tool calls and explicit task-status transitions. This is a reference for visible execution status, not evidence that the proposed course data structures are Codex internals.
- [Claude Code’s official overview](https://code.claude.com/docs/en/overview) documents planning and verifying changes, MCP-connected tools, hooks, and a lead agent coordinating parallel agents. Its internals are not used as a source-level implementation reference here.
- [DeepSeek Harness’s official site](https://deepseek.com/harness/en/) describes an open-source, plugin-composed harness in which models, tools, sessions, sandboxes, loops, scheduling, and the UI are capabilities. It also documents its append-only session log and trajectory view. These provide a direct visual-tracing reference for the proposed dashboard.

## Suggested assessment scenarios

1. **Sequential file-analysis request:** split “read file → summarize → write report” into dependent tasks; show graph and topological order.
2. **Parallel research request:** two independent safe read/search tasks fan out, then a synthesizer fan-ins; show queue states and trace tree.
3. **Priority conflict:** two ready tasks with different urgency; run once with FIFO and once with priority queue; compare order and waiting time.
4. **Tool failure:** a controlled missing-file or simulated API failure; show attempt counter, retry policy, fallback/clarification, and final trace outcome.
5. **Invalid plan:** deliberately create a dependency cycle; show detection before tools run.

For an early demo, tools should be restricted to deterministic or read-only actions and a simulated failure. File writing can be added after there is an approval/confirmation boundary and an event record. This keeps the demo reliable while still proving execution, not just planning.

## Questions this research leaves for the team

1. Which two or three safe task types will be the fixed demonstration domain? A narrow domain makes schedules and failures repeatable.
2. Is the first-assessment UI a terminal visualisation, a lightweight browser dashboard, or both? The core runtime should expose events independently of the UI.
3. Which scheduling policy is the comparison baseline: FIFO versus a single explicit priority rule, or FIFO versus shortest-estimated-job? Avoid unexplained “AI priority.”
4. What is the precise stop policy for retries/reflection—maximum attempts, maximum total steps, timeout, and user escalation?
5. Which decisions are delegated to the LLM, and which remain deterministic runtime policy? The cleanest learning split is: LLM proposes structured intent/task candidates; the runtime validates, schedules, executes, and records transitions.

## Source list

- [Google ADK: Web Interface](https://adk.dev/runtime/web-interface/) — development UI, state/event inspection, builder and structure graph.
- [Google ADK: Agent activity traces](https://adk.dev/observability/traces/) — hierarchical spans and waterfall trace model.
- [Google ADK documentation/source: template workflow agents](https://github.com/google/adk-docs/blob/main/docs/agents/workflow-agents/index.md) — deterministic sequential, parallel, and loop workflow patterns; graph/dynamic workflow direction.
- [Google ADK Python: parallel-agent source](https://github.com/google/adk-python/blob/main/src/google/adk/agents/parallel_agent.py) — concrete queue-based event-stream merging; implementation detail, not an API guarantee.
- [LangGraph: Use the Graph API](https://docs.langchain.com/oss/python/langgraph/use-graph-api) — nodes/edges, fan-out/fan-in, concurrency and retry details.
- [LangGraph: Fault tolerance](https://docs.langchain.com/oss/python/langgraph/fault-tolerance) — retry, timeout, and recovery ordering.
- [LangGraph: Thinking in LangGraph](https://docs.langchain.com/oss/python/langgraph/thinking-in-langgraph) — error-to-state-and-loop-back pattern.
- [OpenAI Agents SDK: Agents](https://openai.github.io/openai-agents-python/agents/) and [Tracing](https://openai.github.io/openai-agents-python/tracing/) — runtime responsibilities and trace/span hierarchy.
- [OpenCode repository](https://github.com/anomalyco/opencode) and [core tool architecture](https://github.com/anomalyco/opencode/blob/dev/packages/core/src/tool/AGENTS.md) — open-source agent modes, subagent concept, tool registration, scoped lookup, permissions, and output bounding.
- [OpenAI Codex source repository](https://github.com/openai/codex) — public source and task-execution guidance.
- [Claude Code overview](https://code.claude.com/docs/en/overview) — official behavior documentation for tool integration, hooks, and coordinated parallel agents.
- [DeepSeek Harness](https://deepseek.com/harness/en/) — official open-source harness description, plugin composition, append-only trace log, and trajectory inspection.

*Sources checked 13 September 2026.*
