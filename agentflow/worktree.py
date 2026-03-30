"""Git worktree management for isolated agent execution."""

from __future__ import annotations

import subprocess
from pathlib import Path


def create_worktree(repo_dir: Path, node_id: str, run_id: str) -> Path:
    """Create a git worktree for a node. Returns the worktree path."""
    safe_id = node_id.replace("/", "_")
    worktree_dir = repo_dir / ".agentflow" / "worktrees" / run_id / safe_id
    worktree_dir.parent.mkdir(parents=True, exist_ok=True)

    branch_name = f"agentflow/{run_id[:8]}/{safe_id}"

    result = subprocess.run(
        ["git", "worktree", "add", "-b", branch_name, str(worktree_dir)],
        cwd=str(repo_dir),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        # Branch might exist from a previous run -- try without -b
        result = subprocess.run(
            ["git", "worktree", "add", str(worktree_dir), "HEAD"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to create worktree for {node_id}: {result.stderr.strip()}")

    return worktree_dir


def remove_worktree(repo_dir: Path, worktree_dir: Path) -> None:
    """Remove a git worktree and its branch."""
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree_dir)],
        cwd=str(repo_dir),
        capture_output=True,
        text=True,
        timeout=30,
    )


def is_git_repo(path: Path) -> bool:
    """Check if path is inside a git repository."""
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=str(path),
        capture_output=True,
        text=True,
        timeout=5,
    )
    return result.returncode == 0
