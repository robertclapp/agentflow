from __future__ import annotations

import asyncio
import os
from contextlib import suppress

from agentflow.prepared import ExecutionPaths, PreparedExecution
from agentflow.runners.base import RawExecutionResult, Runner, StreamCallback
from agentflow.specs import NodeSpec


class LocalRunner(Runner):
    async def _consume_stream(self, stream, stream_name: str, buffer: list[str], on_output: StreamCallback) -> None:
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip("\n")
            buffer.append(text)
            await on_output(stream_name, text)

    async def execute(
        self,
        node: NodeSpec,
        prepared: PreparedExecution,
        paths: ExecutionPaths,
        on_output: StreamCallback,
        should_cancel,
    ) -> RawExecutionResult:
        self.materialize_runtime_files(paths.host_runtime_dir, prepared.runtime_files)
        env = os.environ.copy()
        env.update(prepared.env)
        process = await asyncio.create_subprocess_exec(
            *prepared.command,
            cwd=prepared.cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE if prepared.stdin is not None else None,
        )
        if prepared.stdin is not None and process.stdin is not None:
            process.stdin.write(prepared.stdin.encode("utf-8"))
            await process.stdin.drain()
            process.stdin.close()

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        stdout_task = asyncio.create_task(self._consume_stream(process.stdout, "stdout", stdout_lines, on_output))
        stderr_task = asyncio.create_task(self._consume_stream(process.stderr, "stderr", stderr_lines, on_output))
        wait_task = asyncio.create_task(process.wait())
        deadline = asyncio.get_running_loop().time() + node.timeout_seconds
        timed_out = False
        cancelled = False

        try:
            while not wait_task.done():
                if should_cancel():
                    cancelled = True
                    process.terminate()
                    break
                if asyncio.get_running_loop().time() >= deadline:
                    timed_out = True
                    process.kill()
                    break
                await asyncio.sleep(0.1)
            await wait_task
        finally:
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            if timed_out:
                stderr_lines.append(f"Timed out after {node.timeout_seconds}s")
                await on_output("stderr", stderr_lines[-1])
            if cancelled:
                stderr_lines.append("Cancelled by user")
                await on_output("stderr", stderr_lines[-1])
            with suppress(ProcessLookupError):
                if not wait_task.done():
                    process.kill()
                    await wait_task

        exit_code = process.returncode if process.returncode is not None else (130 if cancelled else 124)
        return RawExecutionResult(
            exit_code=exit_code,
            stdout_lines=stdout_lines,
            stderr_lines=stderr_lines,
            timed_out=timed_out,
            cancelled=cancelled,
        )
