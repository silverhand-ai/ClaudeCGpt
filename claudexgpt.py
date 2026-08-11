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

Optional --cross-review (off by default, Phase 1 behavior otherwise
unchanged): after both primary runs finish, has Claude review Codex's
result and Codex review Claude's, read-only (claude --tools "", codex
-s read-only - neither can write files during review). Still no
merging, scoring, or winner - just two more files to read.
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


def run_tool(name, cmd, cwd, timeout, stdin_input=None):
    """Run a CLI non-interactively, never raising. Always returns a result dict.

    If stdin_input is given, it's piped in as the prompt instead of the command
    carrying it as an argv element. Needed for cross-review prompts, which are
    multi-line: an argv element goes through cmd.exe (required for the npm
    .cmd shims on Windows) which mishandles embedded newlines, but stdin does not.
    """
    started = datetime.datetime.now()
    try:
        run_kwargs = dict(
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=USE_SHELL,
        )
        if stdin_input is not None:
            run_kwargs["input"] = stdin_input
        else:
            run_kwargs["stdin"] = subprocess.DEVNULL
        proc = subprocess.run(cmd, **run_kwargs)
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


def build_review_prompt(task, reviewed_name, reviewed_result, diff_text):
    status_line = f"Status: {reviewed_result['status']}"
    if reviewed_result["returncode"] is not None:
        status_line += f" (exit code {reviewed_result['returncode']})"
    diff_section = diff_text if diff_text else "(no diff available - not a git repo, or no changes made)"
    return (
        f"ORIGINAL TASK:\n{task}\n\n"
        f"You are reviewing another AI coding tool's ({reviewed_name}) attempt at the task above.\n"
        f"Do not modify any files. Only respond with your review as text.\n\n"
        f"{reviewed_name.upper()} RESULT:\n"
        f"{status_line}\n"
        f"Duration: {reviewed_result['duration']:.2f}s\n\n"
        f"--- STDOUT ---\n{reviewed_result['stdout'] or '(empty)'}\n\n"
        f"--- STDERR ---\n{reviewed_result['stderr'] or '(empty)'}\n\n"
        f"--- GIT DIFF ---\n{diff_section}\n\n"
        "Give a concise review focused on:\n"
        "- Correctness\n"
        "- Risks\n"
        "- Missing tests or verification\n"
        "- Whether the diff appears to satisfy the original task\n\n"
        "Do not modify files during this review. Only write your review response as text."
    )


def build_reviewer_cmd(reviewer_name):
    """Commands for review mode always run read-only, regardless of --yolo:
    the review must never write files, so this isn't user-configurable."""
    if reviewer_name == "claude":
        return [CLAUDE_BIN, "-p", "--output-format", "text", "--tools", ""]
    return [CODEX_BIN, "exec", "-", "--skip-git-repo-check", "-s", "read-only"]


def write_review_file(path, reviewer, reviewed, prompt, result):
    lines = [
        f"Review: {reviewer} reviewing {reviewed}'s result",
        f"Command: {format_cmd(result['cmd'])} (prompt piped via stdin)",
        f"Status: {result['status']}",
        f"Exit code: {result['returncode']}",
        f"Duration: {result['duration']:.2f}s",
    ]
    if result["error"]:
        lines.append(f"Error: {result['error']}")
    lines.append("")
    lines.append("--- REVIEW PROMPT (sent via stdin) ---")
    lines.append(prompt)
    lines.append("")
    lines.append("--- REVIEW RESPONSE (stdout) ---")
    lines.append(result["stdout"] or "(empty)")
    lines.append("")
    lines.append("--- STDERR ---")
    lines.append(result["stderr"] or "(empty)")
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
    parser.add_argument(
        "--cross-review", action="store_true",
        help="After both primary runs complete, have Claude review Codex's result and Codex review Claude's "
             "result (original task + the other tool's stdout/stderr/status/diff). Reviews are read-only by "
             "construction (claude --tools \"\", codex -s read-only) - they cannot write files, regardless of "
             "--yolo. Saved as claude_review_of_codex.txt / codex_review_of_claude.txt in the same run "
             "directory. If the reviewed tool didn't complete successfully, or either tool is unavailable, "
             "that side is skipped with a _SKIPPED.txt marker explaining why. No merging, scoring, or winner "
             "is chosen. Off by default; does not affect default behavior.",
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
    primary = {}  # name -> {"result", "diff_text", "ws"} - kept around for --cross-review
    for name, cmd, ws in jobs:
        result = results[name]
        diff_text = get_diff(ws) if repo_mode else None
        primary[name] = {"result": result, "diff_text": diff_text, "ws": ws}

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

    for s in skipped:
        print(f"\n=== {s['name']} ===")
        print(f"status: {s['status']}")
        print(f"error: {s['error']}")

    if args.cross_review:
        print("\nCross-review requested (--cross-review): read-only, no file edits, no merging/scoring/winner.")
        review_specs = []
        for reviewer, reviewed in (("claude", "codex"), ("codex", "claude")):
            review_name = f"{reviewer}_review_of_{reviewed}"
            if reviewer == "claude" and not claude_path:
                skip_reason = "reviewer 'claude' is not installed"
            elif reviewer == "codex" and not codex_path:
                skip_reason = "reviewer 'codex' is not installed"
            elif reviewed not in primary:
                skip_reason = f"'{reviewed}' did not run (not installed)"
            elif primary[reviewed]["result"]["status"] != "ok":
                skip_reason = f"'{reviewed}' did not complete successfully (status: {primary[reviewed]['result']['status']})"
            else:
                skip_reason = None

            if skip_reason:
                skip_path = run_root / f"{review_name}_SKIPPED.txt"
                skip_path.write_text(f"Cross-review skipped.\nReason: {skip_reason}\n", encoding="utf-8")
                print(f"\n=== {review_name} ===")
                print(f"skipped: {skip_reason}")
                print(f"recorded to: {skip_path}")
                continue

            review_specs.append((review_name, reviewer, reviewed))

        if review_specs:
            review_results = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(review_specs)) as pool:
                futures = {}
                for review_name, reviewer, reviewed in review_specs:
                    prompt = build_review_prompt(
                        task, reviewed, primary[reviewed]["result"], primary[reviewed]["diff_text"]
                    )
                    cmd = build_reviewer_cmd(reviewer)
                    cwd = primary[reviewed]["ws"]
                    fut = pool.submit(run_tool, review_name, cmd, cwd, args.timeout, prompt)
                    futures[fut] = (review_name, reviewer, reviewed, prompt)
                for fut in concurrent.futures.as_completed(futures):
                    review_name, reviewer, reviewed, prompt = futures[fut]
                    r = fut.result()
                    review_results[review_name] = (r, reviewer, reviewed, prompt)

            for review_name, reviewer, reviewed in review_specs:
                r, _, _, prompt = review_results[review_name]
                review_path = run_root / f"{review_name}.txt"
                write_review_file(review_path, reviewer, reviewed, prompt, r)
                print(f"\n=== {review_name} ===")
                print(f"status: {r['status']}" + (f" (exit {r['returncode']})" if r["returncode"] is not None else ""))
                print(f"duration: {r['duration']:.2f}s")
                if r["error"]:
                    print(f"error: {r['error']}")
                print(f"saved to: {review_path}")
                if r["status"] != "ok":
                    any_failure = True

    if args.no_keep_workspaces:
        for name in primary:
            shutil.rmtree(primary[name]["ws"], ignore_errors=True)

    print(f"\nAll results saved under: {run_root}")
    print("No merge, no scoring, no decision made - review both outputs/diffs yourself.")

    sys.exit(1 if any_failure else 0)


if __name__ == "__main__":
    main()
