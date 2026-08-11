#!/usr/bin/env python3
"""
ClaudeXGPT - run one task description through Claude Code and Codex CLI
non-interactively, save both outputs to files, and show diffs of what
each one changed in a copy of the target directory.

No auto-merge. No auto-decide. Just both outputs, side by side, for a
human to compare.

Confirmed invocation syntax (checked against `claude --help` and
`codex exec --help` on 2026-08-10):
    claude -p "<task>" --permission-mode acceptEdits --output-format text
    codex exec "<task>" -s workspace-write --skip-git-repo-check

Each tool runs in its own disposable copy of the target directory, so
neither sees the other's edits and your real files are never touched.
"""

import argparse
import concurrent.futures
import datetime
import shutil
import subprocess
import sys
from pathlib import Path

# On Windows, npm installs claude/codex as .cmd shims. subprocess can't
# CreateProcess a .cmd directly - it needs shell=True (which routes through
# cmd.exe, which resolves .cmd via PATHEXT). Not needed on other platforms.
USE_SHELL = sys.platform.startswith("win")

CLAUDE_BIN = "claude"
CODEX_BIN = "codex"

# Vendor/build directories excluded when copying the target directory into
# each tool's disposable workspace. Edit this list if your project needs
# something else excluded (or nothing at all).
COPY_IGNORE = shutil.ignore_patterns(
    "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
    ".next", "target", ".mypy_cache", ".pytest_cache",
)


def which_or_none(name):
    return shutil.which(name)


def is_git_repo(path):
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=15,
        )
        return result.returncode == 0
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False


def run_tool(name, cmd, cwd, timeout):
    """Run a CLI non-interactively, never raising. Always returns a result dict."""
    started = datetime.datetime.now()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            shell=USE_SHELL,
        )
        duration = (datetime.datetime.now() - started).total_seconds()
        return {
            "name": name,
            "cmd": cmd,
            "status": "ok" if proc.returncode == 0 else "failed",
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "duration": duration,
            "error": None,
        }
    except subprocess.TimeoutExpired as e:
        duration = (datetime.datetime.now() - started).total_seconds()
        return {
            "name": name, "cmd": cmd, "status": "timeout", "returncode": None,
            "stdout": (e.stdout or ""), "stderr": (e.stderr or ""),
            "duration": duration, "error": f"Timed out after {timeout}s",
        }
    except FileNotFoundError:
        return {
            "name": name, "cmd": cmd, "status": "not_installed", "returncode": None,
            "stdout": "", "stderr": "", "duration": 0.0,
            "error": f"'{cmd[0]}' is not installed or not on PATH",
        }
    except OSError as e:
        duration = (datetime.datetime.now() - started).total_seconds()
        return {
            "name": name, "cmd": cmd, "status": "error", "returncode": None,
            "stdout": "", "stderr": "", "duration": duration, "error": str(e),
        }


def get_diff(workspace):
    """Stage everything in the disposable workspace copy and return the diff text."""
    try:
        subprocess.run(
            ["git", "-C", str(workspace), "add", "-A"],
            capture_output=True, text=True, timeout=60,
        )
        result = subprocess.run(
            ["git", "-C", str(workspace), "diff", "--cached"],
            capture_output=True, text=True, timeout=60,
        )
        return result.stdout
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as e:
        return f"(could not compute diff: {e})"


def format_cmd(cmd):
    return subprocess.list2cmdline(cmd) if USE_SHELL else " ".join(
        f'"{c}"' if " " in c else c for c in cmd
    )


def write_output_file(path, result, diff_text):
    lines = [
        f"Tool: {result['name']}",
        f"Command: {format_cmd(result['cmd'])}",
        f"Status: {result['status']}",
        f"Exit code: {result['returncode']}",
        f"Duration: {result['duration']:.2f}s",
    ]
    if result["error"]:
        lines.append(f"Error: {result['error']}")
    lines.append("")
    lines.append("--- STDOUT ---")
    lines.append(result["stdout"] or "(empty)")
    lines.append("")
    lines.append("--- STDERR ---")
    lines.append(result["stderr"] or "(empty)")
    if diff_text is not None:
        lines.append("")
        lines.append("--- GIT DIFF ---")
        lines.append(diff_text or "(no changes)")
    path.write_text("\n".join(lines), encoding="utf-8")


def print_summary(result, output_path, diff_path):
    print(f"\n=== {result['name']} ===")
    print(f"status: {result['status']}" + (f" (exit {result['returncode']})" if result['returncode'] is not None else ""))
    print(f"duration: {result['duration']:.2f}s")
    if result["error"]:
        print(f"error: {result['error']}")
    print(f"output saved to: {output_path}")
    if diff_path:
        print(f"diff saved to: {diff_path}")


def main():
    parser = argparse.ArgumentParser(
        prog="claudexgpt",
        description="Run a task through Claude Code and Codex CLI non-interactively; save outputs; show diffs. No merging, no deciding.",
    )
    parser.add_argument("task", nargs="?", help="Task description. If omitted, you'll be prompted.")
    parser.add_argument("-C", "--dir", default=".", help="Target directory to work in (default: current directory).")
    parser.add_argument("--outputs-dir", default="outputs", help="Where to write results (default: ./outputs).")
    parser.add_argument("--timeout", type=int, default=1800, help="Per-tool timeout in seconds (default: 1800).")
    parser.add_argument(
        "--yolo", action="store_true",
        help="Fully bypass permission/sandbox checks in both tools (claude --dangerously-skip-permissions, "
             "codex --dangerously-bypass-approvals-and-sandbox). Only affects the disposable workspace copies, "
             "but those copies can still reach the network/system. Off by default.",
    )
    parser.add_argument(
        "--no-keep-workspaces", action="store_true",
        help="Delete the per-tool workspace copies after extracting output/diff (default: keep them for inspection).",
    )
    args = parser.parse_args()

    task = args.task or input("Task description: ").strip()
    if not task:
        print("No task description given.", file=sys.stderr)
        sys.exit(1)

    target = Path(args.dir).resolve()
    if not target.is_dir():
        print(f"Target directory does not exist: {target}", file=sys.stderr)
        sys.exit(1)

    claude_path = which_or_none(CLAUDE_BIN)
    codex_path = which_or_none(CODEX_BIN)

    if not claude_path:
        print(f"WARNING: '{CLAUDE_BIN}' not found on PATH. Claude Code will be skipped.", file=sys.stderr)
    if not codex_path:
        print(f"WARNING: '{CODEX_BIN}' not found on PATH. Codex CLI will be skipped.", file=sys.stderr)
    if not claude_path and not codex_path:
        print("Neither CLI is available. Nothing to run.", file=sys.stderr)
        sys.exit(1)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    outputs_dir = Path(args.outputs_dir).resolve()
    run_root = outputs_dir / timestamp
    run_root.mkdir(parents=True, exist_ok=True)

    repo_mode = is_git_repo(target)

    claude_cmd = [CLAUDE_BIN, "-p", task, "--output-format", "text"]
    claude_cmd += ["--dangerously-skip-permissions"] if args.yolo else ["--permission-mode", "acceptEdits"]

    codex_cmd = [CODEX_BIN, "exec", task, "--skip-git-repo-check"]
    codex_cmd += ["--dangerously-bypass-approvals-and-sandbox"] if args.yolo else ["-s", "workspace-write"]

    jobs = []
    if claude_path:
        ws = run_root / "claude_workspace"
        shutil.copytree(target, ws, ignore=COPY_IGNORE, symlinks=True)
        jobs.append(("claude", claude_cmd, ws))
    if codex_path:
        ws = run_root / "codex_workspace"
        shutil.copytree(target, ws, ignore=COPY_IGNORE, symlinks=True)
        jobs.append(("codex", codex_cmd, ws))

    print(f"Task: {task}")
    print(f"Target directory: {target}")
    print(f"Git repo detected: {repo_mode}")
    print(f"Running {len(jobs)} tool(s), timeout {args.timeout}s each...")

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {pool.submit(run_tool, name, cmd, ws, args.timeout): name for name, cmd, ws in jobs}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results[result["name"]] = result

    skipped = []
    if not claude_path:
        skipped.append({"name": "claude", "status": "not_installed", "error": f"'{CLAUDE_BIN}' not found on PATH"})
    if not codex_path:
        skipped.append({"name": "codex", "status": "not_installed", "error": f"'{CODEX_BIN}' not found on PATH"})

    any_failure = bool(skipped)
    for name, cmd, ws in jobs:
        result = results[name]
        diff_text = get_diff(ws) if repo_mode else None

        output_path = run_root / f"{name}_output.txt"
        write_output_file(output_path, result, diff_text)

        diff_path = None
        if diff_text is not None:
            diff_path = run_root / f"{name}.diff"
            diff_path.write_text(diff_text, encoding="utf-8")

        print_summary(result, output_path, diff_path)
        if diff_text:
            print(f"--- {name} diff ---")
            print(diff_text)
        elif repo_mode:
            print(f"({name} made no file changes)")

        if result["status"] != "ok":
            any_failure = True

        if args.no_keep_workspaces:
            shutil.rmtree(ws, ignore_errors=True)

    for s in skipped:
        print(f"\n=== {s['name']} ===")
        print(f"status: {s['status']}")
        print(f"error: {s['error']}")

    print(f"\nAll results saved under: {run_root}")
    print("No merge, no scoring, no decision made - review both outputs/diffs yourself.")

    sys.exit(1 if any_failure else 0)


if __name__ == "__main__":
    main()
