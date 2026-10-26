# Fundamentals of Data Structures Course Project — Master Plan

## 1. Project context and academic purpose

This is a course project for **Fundamentals of Data Structures (FODS)**. Its purpose is to demonstrate the team’s understanding of data structures and algorithms by applying them deliberately inside a small agentic system.

The project is **not** intended to be a production product, a general-purpose autonomous agent, or a clone of Google ADK, Codex, Claude Code, OpenCode, DeepSeek Harness, LangGraph, or any other framework. Those systems are studied as references for patterns that are already used in agent runtimes. Our contribution is an educational implementation that makes the selected data structures, algorithms, and runtime decisions observable and explainable to faculty.

The team will combine its existing understanding of LLM-based agents—reasoning, tool selection, execution, tracing, feedback, and reply loops—with the data-structure concepts taught in FODS.

## 2. Project description

The team will build a compact, traceable agent runtime. A user gives a natural-language request inside a restricted workspace. An LLM proposes a structured task plan. The project’s own runtime then validates the plan, schedules eligible tasks, calls safe tools, records all state transitions, applies a bounded retry/replanning policy when an operation fails, and produces a final response.

The preferred presentation is a lightweight web dashboard. It will display the proposed task/dependency graph and an inspectable execution trace, inspired by the transparency of developer tools such as Google ADK and DeepSeek Harness. A command-line presentation remains an acceptable implementation alternative if it better fits the development timeline; the runtime must not depend on the chosen interface.

## 3. Problem statement

LLM agents can produce plans and call tools, but their internal execution order, task dependencies, retries, and failures are difficult to inspect. That opacity makes it hard to demonstrate how fundamental data structures support agent behavior.

The problem is to design and implement a safe, limited-scope agent runtime in which the plan, ready work, execution context, task state, and recovery behavior are represented by appropriate data structures. The system must visibly demonstrate planning, execution, tracing, bounded recovery, and final response generation—not merely chat or plan generation.

## 4. Objectives

1. Apply FODS concepts as real runtime components rather than decorative labels.
2. Build a working demonstration that accepts an LLM-assisted structured plan and executes a controlled file-based workflow.
3. Make task dependencies, scheduling, state transitions, tool calls, errors, and retries inspectable.
4. Demonstrate why each selected structure or algorithm is appropriate through repeatable scenarios.
5. Keep the first assessment feasible before the 20th, while retaining a clear path to sequential and parallel multi-agent execution for the final version.

## 5. Agreed approach

### 5.1 Division of responsibility

| Component | Responsibility |
| --- | --- |
| LLM API | Interpret the request and propose a structured plan, task dependencies, tool choices, priorities, and expected outputs. |
| Project runtime | Validate the plan, reject invalid dependency cycles, determine which tasks are ready, schedule and execute them, manage task state, record trace events, enforce retry limits, and decide when to reply or report failure. |
| Safe tools | List/read workspace files, search text within them, and write or update only explicitly named files in the approved workspace. |
| Interface | Show the plan graph and execution trace. A web dashboard is preferred; CLI remains possible. |

The key principle is: **the LLM suggests; the FODS runtime governs.**

### 5.2 Core runtime flow

```text
Request
  → LLM proposes a structured plan
  → validate tasks and dependencies
  → detect cycles and calculate ready tasks
  → schedule ready tasks
  → execute an LLM action or safe tool
  → record event, output, and task state
  → retry/replan within a fixed limit if needed
  → return final response or a clear failure result
```

The initial plan graph should be acyclic. Reflection and retries are runtime transitions, not unbounded dependency cycles. Every retry must have a maximum number of attempts and a visible termination reason.

### 5.3 Data structures and algorithms

The project will choose structures based on the problem, rather than forcing a fixed list. The following are the current strongest candidates and must be justified in the implementation report.

| Candidate structure / algorithm | Planned use in the agent runtime |
| --- | --- |
| Directed graph / DAG | Store task dependencies and enable sequential, branching, and eventual parallel work. |
| Cycle detection and topological ordering | Reject invalid dependency plans and identify tasks whose prerequisites are complete. |
| Queue | Hold ready tasks under a simple FIFO scheduling policy. |
| Priority queue / heap | Optional alternative scheduler for ready tasks when an explicit priority rule is justified. |
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

### First assessment demo

The first demo will use one orchestrator and a controlled request such as:

> Receive a project request → plan subtasks → inspect files → generate or update a safe output file → reply with the result.

The tool scope will be limited to the approved workspace: list/read files, optional text search, and write/update of an explicitly named file. Every tool call will be traced. Actions should be reversible where practical.

### Final expansion

The intended final direction is a central orchestrator that supervises specialist worker agents. It should support both sequential dependencies and independent tasks that can run in parallel. The central orchestrator remains responsible for validation, scheduling, trace collection, retry policy, and final aggregation.

## 7. Demonstration and evaluation scenarios

The demonstration script should include these repeatable cases:

1. **Normal workflow:** dependent tasks such as read → summarize → write output; show graph and topological execution order.
2. **Parallel-ready work:** two independent tasks become ready, then their results join in a final task.
3. **Scheduling comparison:** run the same ready tasks under FIFO and one clearly defined priority rule; explain the changed order.
4. **Invalid plan:** create a cyclic dependency and show rejection before any tool is called.
5. **Controlled failure:** simulate a missing file or tool error; show the trace, retry/replanning limit, and final result.

Assessment evidence should prioritize correct behavior and clear explanations over raw speed benchmarks. A small baseline comparison—for example, a linear task list versus an explicit dependency graph, or FIFO versus a priority queue—is recommended when it helps explain a chosen structure.

## 8. Milestone plan

| Milestone | Target outcome |
| --- | --- |
| Planning and research | This master plan, source-backed research, scenario list, and data-structure mapping. |
| First assessment, before the 20th | One orchestrator, LLM chat/plan proposal, restricted file tools, graph validation, task states, trace view, and bounded retry demonstration. |
| Final project | Sequential and parallel worker-agent execution, mature visual inspection, scheduling comparison, and a complete course-focused explanation/report. |

Team roles are intentionally flexible. Work may be shared across runtime/data structures, LLM and tool integration, visualization, test scenarios, and documentation, with regular integration review.

## 9. Decisions deliberately deferred

The following are not finalized and should be chosen only after the architecture is converted into an implementation plan:

- LLM provider and model (OpenRouter, free model, or another option).
- Implementation language(s), including whether Python handles the agent/API layer and whether C++ is used for selected engine components.
- Web dashboard versus CLI for the first working interface.
- Exact scheduler priority formula and whether a priority queue is needed in the first demo.
- Exact retry count, timeout, and replanning policy.
- Final number and specialization of worker agents.

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
