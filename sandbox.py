#!/usr/bin/env python3
"""
harness/sandbox.py - Sandbox execution engine for NextAppStore

Provides a clean, isolated environment for running tests, linters,
and agent-generated commands inside Docker.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

# Paths
HARNESS_DIR = Path(__file__).resolve().parent
REPO_ROOT = HARNESS_DIR.parent
DOCKERFILE_PATH = HARNESS_DIR / "Dockerfile.sandbox"
IMAGE_NAME = "nextappstore-sandbox:latest"

# Runtime — prefer docker, fall back to podman (mirrors the deployment/ Makefile logic)
def _container_runtime() -> str:
    for rt in ("docker", "podman"):
        if shutil.which(rt):
            return rt
    raise FileNotFoundError("Neither 'docker' nor 'podman' found in PATH.")


@dataclasses.dataclass
class SandboxResult:
    """Represents the outcome of a command executed inside the sandbox."""
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def format_summary(self) -> str:
        status = "TIMEOUT" if self.timed_out else ("PASSED" if self.success else "FAILED")
        return (
            f"\n--- Sandbox Run Summary ---\n"
            f"Status:   {status} (exit code: {self.exit_code})\n"
            f"Duration: {self.duration_seconds:.2f}s\n"
            f"Command:  {self.command}\n"
            f"---------------------------"
        )


def ensure_image(force: bool = False) -> None:
    """Builds the sandbox Docker image if missing or if force=True."""
    rt = _container_runtime()
    if not force:
        inspect = subprocess.run(
            [rt, "image", "inspect", IMAGE_NAME],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if inspect.returncode == 0:
            return

    print(f"==> Building sandbox image '{IMAGE_NAME}' (Context: {REPO_ROOT}, Runtime: {rt})...")
    build_cmd = [
        rt, "build",
        "-f", str(DOCKERFILE_PATH),
        "-t", IMAGE_NAME,
        str(REPO_ROOT),
    ]
    subprocess.run(build_cmd, check=True)
    print("==> Sandbox image build completed successfully.\n")


def _copy_workspace_ephemeral(src: Path, dst: Path) -> None:
    """Copies repo to a temporary directory, ignoring unnecessary caches/git."""
    ignored = shutil.ignore_patterns(
        ".git",
        "__pycache__",
        "*.pyc",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
        ".venv",
        "venv",
    )
    for item in src.iterdir():
        dest_item = dst / item.name
        if item.is_dir():
            shutil.copytree(item, dest_item, ignore=ignored, symlinks=True)
        else:
            shutil.copy2(item, dest_item)


def run_in_sandbox(
    command: str,
    timeout: int = 300,
    ephemeral: bool = False,
    workspace_path: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
    stream_output: bool = False,
) -> SandboxResult:
    """
    Executes a shell command inside the Docker sandbox.

    Args:
        command: The command to execute in /workspace (e.g. 'bash harness/verify.sh fast')
        timeout: Maximum seconds allowed before killing the container.
        ephemeral: If True, copies the repo to an isolated temp directory first.
        workspace_path: Custom directory to mount into /workspace (defaults to REPO_ROOT).
        env: Additional environment variables for the container.
        stream_output: If True, prints stdout/stderr in real-time while capturing it.
    """
    ensure_image()

    start_time = time.time()
    source_workspace = (workspace_path or REPO_ROOT).resolve()
    rt = _container_runtime()

    def _execute(target_path: Path) -> SandboxResult:
        docker_cmd: List[str] = [
            rt, "run",
            "--rm",
            "-v", f"{target_path}:/workspace:rw",
            "-w", "/workspace",
        ]

        if env:
            for k, v in env.items():
                docker_cmd.extend(["-e", f"{k}={v}"])

        docker_cmd.extend([IMAGE_NAME, "/bin/bash", "-c", command])

        try:
            if stream_output:
                # Stream directly to stdout/stderr while capturing
                proc = subprocess.Popen(
                    docker_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                stdout_chunks: List[str] = []
                stderr_chunks: List[str] = []

                # Simple stdout/stderr reader
                if proc.stdout:
                    for line in iter(proc.stdout.readline, ""):
                        sys.stdout.write(line)
                        sys.stdout.flush()
                        stdout_chunks.append(line)
                proc.wait(timeout=timeout)
                stderr_content = proc.stderr.read() if proc.stderr else ""
                if stderr_content:
                    sys.stderr.write(stderr_content)
                    sys.stderr.flush()

                duration = time.time() - start_time
                return SandboxResult(
                    command=command,
                    exit_code=proc.returncode,
                    stdout="".join(stdout_chunks),
                    stderr=stderr_content,
                    duration_seconds=duration,
                    timed_out=False,
                )
            else:
                proc = subprocess.run(
                    docker_cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                duration = time.time() - start_time
                return SandboxResult(
                    command=command,
                    exit_code=proc.returncode,
                    stdout=proc.stdout,
                    stderr=proc.stderr,
                    duration_seconds=duration,
                    timed_out=False,
                )

        except subprocess.TimeoutExpired as exc:
            duration = time.time() - start_time
            # Kill any orphaned containers left running from this image
            orphans = subprocess.run(
                [rt, "ps", "-q", "--filter", f"ancestor={IMAGE_NAME}"],
                capture_output=True, text=True,
            )
            container_ids = orphans.stdout.split()
            if container_ids:
                subprocess.run([rt, "kill", *container_ids], capture_output=True)
            return SandboxResult(
                command=command,
                exit_code=-1,
                stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
                stderr=(exc.stderr or "") + f"\n[ERROR] Sandbox execution timed out after {timeout}s.",
                duration_seconds=duration,
                timed_out=True,
            )

    if ephemeral:
        with tempfile.TemporaryDirectory(prefix="appstore_sandbox_") as tmp_dir:
            temp_path = Path(tmp_dir)
            _copy_workspace_ephemeral(source_workspace, temp_path)
            return _execute(temp_path)
    else:
        return _execute(source_workspace)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run commands inside the NextAppStore isolated Docker sandbox."
    )
    parser.add_argument(
        "command",
        nargs="*",
        help="Command to run inside the sandbox. Defaults to 'bash harness/verify.sh fast'.",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Run fast verification suite (fast unit tests & linting).",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Run full verification suite (all tests & linting).",
    )
    parser.add_argument(
        "--ephemeral",
        action="store_true",
        help="Run in an isolated temp copy to guarantee no host files are touched or modified.",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Force rebuild the Docker sandbox image before running.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Timeout in seconds (default: 300).",
    )

    args = parser.parse_args()

    if args.rebuild:
        ensure_image(force=True)

    # Determine command
    if args.fast:
        cmd = "bash agentic-harness/verify.sh fast"
    elif args.full:
        cmd = "bash agentic-harness/verify.sh"
    elif args.command:
        cmd = " ".join(args.command)
    else:
        cmd = "bash agentic-harness/verify.sh fast"

    print(f"==> Launching in Sandbox (Ephemeral: {args.ephemeral}): '{cmd}'\n")
    result = run_in_sandbox(
        command=cmd,
        timeout=args.timeout,
        ephemeral=args.ephemeral,
        stream_output=True,
    )

    print(result.format_summary())
    sys.exit(result.exit_code)


if __name__ == "__main__":
    main()
