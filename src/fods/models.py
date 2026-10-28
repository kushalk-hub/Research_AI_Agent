"""Small, provider-neutral contracts for plans and runtime state."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TaskState(StrEnum):
    PLANNED = "planned"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    tool: str = Field(min_length=1, max_length=80)
    args: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    priority: int = Field(default=0, ge=0, le=100)


class TaskPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: str = Field(min_length=1, max_length=2000)
    topic: str = Field(min_length=1, max_length=300)
    question: str = Field(min_length=1, max_length=1000)
    output_path: str = Field(min_length=1, max_length=500)
    tasks: list[Task] = Field(min_length=1, max_length=30)


class TaskRecord(BaseModel):
    task: Task
    state: TaskState = TaskState.PLANNED
    attempts: int = 0
    result: Any = None
    error: str = ""


class RunResult(BaseModel):
    run_id: str
    mode: str
    plan: TaskPlan
    states: dict[str, TaskRecord]
    succeeded: bool
    termination_reason: str
    events: list[dict[str, Any]]
