from __future__ import annotations

from pathlib import Path

from agentflow.prepared import ExecutionPaths, PreparedExecution
from agentflow.runners.local import LocalRunner
from agentflow.specs import ContainerTarget, NodeSpec


class ContainerRunner(LocalRunner):
    async def execute(self, node: NodeSpec, prepared: PreparedExecution, paths: ExecutionPaths, on_output, should_cancel):
        target = node.target
        if not isinstance(target, ContainerTarget):
            raise TypeError("ContainerRunner requires a ContainerTarget")

        self.materialize_runtime_files(paths.host_runtime_dir, prepared.runtime_files)
        app_mount = target.app_mount
        command = [
            target.engine,
            "run",
            "--rm",
            "-v",
            f"{paths.host_workdir}:{target.workdir_mount}",
            "-v",
            f"{paths.host_runtime_dir}:{target.runtime_mount}",
            "-v",
            f"{paths.app_root}:{app_mount}",
            "-w",
            prepared.cwd,
        ]
        for key, value in prepared.env.items():
            command.extend(["-e", f"{key}={value}"])
        if app_mount:
            command.extend(["-e", f"PYTHONPATH={app_mount}"])
        command.extend(target.extra_args)
        if target.entrypoint:
            command.extend(["--entrypoint", target.entrypoint])
        command.append(target.image)
        command.extend(prepared.command)
        container_prepared = PreparedExecution(
            command=command,
            env={},
            cwd=str(paths.host_workdir),
            trace_kind=prepared.trace_kind,
            runtime_files={},
            stdin=prepared.stdin,
        )
        return await super().execute(node, container_prepared, paths, on_output, should_cancel)
