from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Awaitable, Callable

from pydantic import BaseModel, Field

from agentflow.prepared import ExecutionPaths, PreparedExecution
from agentflow.specs import NodeSpec


class RawExecutionResult(BaseModel):
    exit_code: int
    stdout_lines: list[str] = Field(default_factory=list)
    stderr_lines: list[str] = Field(default_factory=list)
    timed_out: bool = False
    cancelled: bool = False


StreamCallback = Callable[[str, str], Awaitable[None]]
CancelCallback = Callable[[], bool]


class Runner(ABC):
    @abstractmethod
    async def execute(
        self,
        node: NodeSpec,
        prepared: PreparedExecution,
        paths: ExecutionPaths,
        on_output: StreamCallback,
        should_cancel: CancelCallback,
    ) -> RawExecutionResult:
        raise NotImplementedError

    def materialize_runtime_files(self, base_dir: Path, runtime_files: dict[str, str]) -> None:
        for relative_path, content in runtime_files.items():
            target = base_dir / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
