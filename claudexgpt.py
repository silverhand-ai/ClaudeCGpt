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

Optional --revise (implies --cross-review): gives each tool exactly one
chance to revise its own prior work using the review written about it
(own diff + that review's text, not its own stdout again - kept small
on purpose). Still no merge/scoring/winner - a third round of files.

Tasks are piped via stdin to both CLIs, so multi-line prompts and prompts
loaded from --task-file do not have to survive cmd.exe argv quoting on
Windows.

Optional --apply <run_dir> --apply-which {claude,codex,claude_revised,codex_revised}:
applies an already-saved diff from a past run to the real target directory
(-C/--dir), after showing it and asking for explicit y/N confirmation. This
is the only thing in the whole tool that writes to the real target - every
other mode only ever touches disposable copies. The human already chose by
picking --apply-which; there is still no auto-merge, scoring, or winner.

Optional --chat <chat_dir>: one turn of a persistent multi-turn conversation
with both tools, kept alive via claude --resume / codex exec resume (session
ids stored in <chat_dir>/chat_state.json). If <chat_dir> doesn't exist yet,
this is turn 1 and -C/--dir must point at the target to copy into fresh
workspaces there; later turns reuse the same workspaces and -C is ignored.
The message for the turn is the normal task argument/--task-file/prompt.
Diffs are refreshed after each turn using the same filenames a normal run
produces, so a chat directory is fully usable from the GUI's existing
Compare/Apply tabs (or --apply) without any special-casing.
"""

import argparse
import concurrent.futures
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

# On Windows, npm installs claude/codex as .cmd shims. subprocess can't
# CreateProcess a .cmd directly - it needs shell=True (which routes through
# cmd.exe, which resolves .cmd via PATHEXT). Not needed on other platforms.
USE_SHELL = sys.platform.startswith("win")

CLAUDE_BIN = "claude"
CODEX_BIN = "codex"

# C: is space-constrained on this machine (ran to near-zero free space once
# already - see HANDOFF_LOG.md). Default output location lives on F: instead,
# which has the most headroom. Override anytime with --outputs-dir.
DEFAULT_OUTPUTS_DIR = r"F:\ClaudeXGPT_outputs"

# Vendor/build directories excluded when copying the target directory into
# each tool's disposable workspace. Edit this list if your project needs
# something else excluded (or nothing at all).
COPY_IGNORE = shutil.ignore_patterns(
    "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
    ".next", "target", ".mypy_cache", ".pytest_cache",
)


def would_nest_inside(outputs_dir, target):
    """True if outputs_dir is target itself or a subdirectory of it - copying
    target into a workspace under outputs_dir would then copy target into a
    subdirectory of itself. shutil.copytree has no protection against that
    (confirmed: this happened for real once, see HANDOFF_LOG.md)."""
    return outputs_dir == target or target in outputs_dir.parents


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


def read_task(args):
    if args.task and args.task_file:
        print("Provide either a task argument or --task-file, not both.", file=sys.stderr)
        sys.exit(1)
    if args.task_file:
        try:
            return Path(args.task_file).read_text(encoding="utf-8").strip()
        except OSError as e:
            print(f"Could not read task file: {e}", file=sys.stderr)
            sys.exit(1)
    if args.task:
        return args.task.strip()
    return input("Task description: ").strip()


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


def build_revision_prompt(task, own_diff, review_text):
    """Deliberately does NOT re-embed the tool's own original stdout/stderr - that
    was only needed once, to produce the review. Revision only needs the diff it
    produced and the verdict on it, to keep this from stacking prompt size on
    top of the (already trimmed) review step."""
    diff_section = own_diff if own_diff else "(no changes made previously)"
    return (
        f"ORIGINAL TASK:\n{task}\n\n"
        "You previously attempted this task. Below is your own diff from that attempt, "
        "followed by another AI tool's review of it.\n\n"
        f"YOUR PREVIOUS DIFF:\n{diff_section}\n\n"
        f"REVIEW OF YOUR ATTEMPT:\n{review_text or '(empty)'}\n\n"
        "If the review identifies real problems, revise your files in this workspace to address "
        "them. If the review finds no real issues, leave your files as they are - do not make "
        "unnecessary changes.\n\n"
        "This is your own workspace from your previous attempt; make changes directly, as you did before."
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


def print_output_guide(run_root, primary, cross_review, revise=False):
    print("\nOutput guide:")
    for name in ("claude", "codex"):
        print(f"- {name} output: {run_root / f'{name}_output.txt'}")
        if name in primary:
            print(f"- {name} workspace: {primary[name]['ws']}")
            if primary[name]["diff_text"] is not None:
                print(f"- {name} diff: {run_root / f'{name}.diff'}")
    if cross_review:
        print(f"- Claude review of Codex: {run_root / 'claude_review_of_codex.txt'}")
        print(f"- Codex review of Claude: {run_root / 'codex_review_of_claude.txt'}")
    if revise:
        print(f"- Claude revised (using Codex's review): {run_root / 'claude_revised_output.txt'} "
              f"(+ .diff if it changed anything)")
        print(f"- Codex revised (using Claude's review): {run_root / 'codex_revised_output.txt'} "
              f"(+ .diff if it changed anything)")


APPLY_CHOICES = ("claude", "codex", "claude_revised", "codex_revised")


def run_apply_mode(args):
    """The only thing in this tool that writes to the real target directory.
    Takes an already-saved diff from a past run and applies it, after showing
    it in full and getting explicit confirmation. No merge, no scoring, no
    auto-picking - the human already picked by choosing --apply-which."""
    if not args.apply_which:
        print("--apply requires --apply-which {claude,codex,claude_revised,codex_revised}.", file=sys.stderr)
        sys.exit(1)

    run_dir = Path(args.apply).resolve()
    if not run_dir.is_dir():
        print(f"--apply directory does not exist: {run_dir}", file=sys.stderr)
        sys.exit(1)

    diff_path = run_dir / f"{args.apply_which}.diff"
    if not diff_path.is_file():
        print(
            f"No diff file found for '{args.apply_which}' in {run_dir} (expected {diff_path.name}). "
            "Either that tool wasn't run in that folder, made no changes, was skipped, or the run "
            "wasn't against a git repo.",
            file=sys.stderr,
        )
        sys.exit(1)

    diff_text = diff_path.read_text(encoding="utf-8")
    if not diff_text.strip():
        print(f"{diff_path.name} is empty - '{args.apply_which}' made no changes in that run. Nothing to apply.")
        sys.exit(0)

    target = Path(args.dir or ".").resolve()
    if not target.is_dir():
        print(f"Target directory does not exist: {target}", file=sys.stderr)
        sys.exit(1)

    if not is_git_repo(target):
        print(f"Target directory is not a git repository: {target}. --apply uses 'git apply', so the "
              "target must be a git repo.", file=sys.stderr)
        sys.exit(1)

    status = subprocess.run(
        ["git", "-C", str(target), "status", "--porcelain"], capture_output=True, text=True, timeout=15
    )
    if status.stdout.strip():
        print(
            f"Refusing to apply: target directory has uncommitted changes:\n\n{status.stdout}\n"
            "Commit or stash them first, so this diff doesn't get mixed in with unrelated edits.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"About to apply '{args.apply_which}' from {run_dir} to {target}:\n")
    print(diff_text)
    print(f"Target: {target}")
    print(f"Diff: {diff_path}")

    if not args.yes:
        answer = input("\nApply this diff to the target directory? [y/N] ").strip().lower()
        if answer != "y":
            print("Not applied.")
            sys.exit(0)

    check = subprocess.run(
        ["git", "-C", str(target), "apply", "--check", str(diff_path)], capture_output=True, text=True, timeout=30
    )
    if check.returncode != 0:
        print(f"Diff does not apply cleanly to {target}:\n{check.stderr}", file=sys.stderr)
        print("Nothing was changed.", file=sys.stderr)
        sys.exit(1)

    result = subprocess.run(
        ["git", "-C", str(target), "apply", str(diff_path)], capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        print(f"git apply failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    print(f"\nApplied. {target} now has the changes from '{args.apply_which}' ({run_dir.name}).")
    print("Nothing else was decided for you - review the result yourself (git diff, git status, tests, etc.).")
    sys.exit(0)


CHAT_BEGIN = "###CLAUDEXGPT_CHAT_{}_BEGIN###"
CHAT_END = "###CLAUDEXGPT_CHAT_{}_END###"

OTHER_NAME = {"claude": "Codex/GPT", "codex": "Claude"}


def build_crosstalk_message(human_message, other_display_name, other_reply):
    """Wrap the human's message with what the other AI most recently said, so
    each side is actually responding to a real 3-way conversation instead of
    two independent one-on-one chats with the same human."""
    if not other_reply:
        return human_message
    return (
        f"[{other_display_name} just said, in our shared 3-way conversation]:\n{other_reply.strip()}\n\n"
        f"[Now responding to the human, who said]:\n{human_message}"
    )


def run_chat_mode(args, message):
    """One turn of a persistent 3-way conversation. Each call is still a
    normal one-shot subprocess invocation, same as every other mode here -
    the "conversation" is session ids threaded through claude --resume /
    codex exec resume, plus each side's last reply carried forward so the
    other side can actually respond to it. Turns are sequential (not
    parallel): whoever goes second in a round sees what the first one just
    said this round; whoever goes first sees what the other said last round."""
    chat_dir = Path(args.chat).resolve()
    state_path = chat_dir / "chat_state.json"
    claude_ws = chat_dir / "claude_workspace"
    codex_ws = chat_dir / "codex_workspace"

    if state_path.is_file():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    else:
        target = Path(args.dir).resolve() if args.dir else None
        if target is not None:
            if not target.is_dir():
                print(f"Target directory does not exist: {target}", file=sys.stderr)
                sys.exit(1)
            if would_nest_inside(chat_dir, target):
                print(
                    f"Refusing to start: chat directory ({chat_dir}) is inside or equal to the target "
                    f"directory ({target}). Pick a chat directory outside the target.",
                    file=sys.stderr,
                )
                sys.exit(1)
        chat_dir.mkdir(parents=True, exist_ok=True)
        try:
            for bin_name, ws in ((CLAUDE_BIN, claude_ws), (CODEX_BIN, codex_ws)):
                if not which_or_none(bin_name):
                    continue
                if target is not None:
                    shutil.copytree(target, ws, ignore=COPY_IGNORE, symlinks=True)
                else:
                    # No target - pure conversation. Still git-init an empty
                    # workspace so get_diff()/is_git_repo() work unmodified
                    # if either side happens to write a file mid-conversation.
                    ws.mkdir(parents=True, exist_ok=True)
                    subprocess.run(["git", "init", "-q", str(ws)], capture_output=True, timeout=15)
                    git_env = {
                        **os.environ,
                        "GIT_AUTHOR_NAME": "claudexgpt", "GIT_AUTHOR_EMAIL": "claudexgpt@localhost",
                        "GIT_COMMITTER_NAME": "claudexgpt", "GIT_COMMITTER_EMAIL": "claudexgpt@localhost",
                    }
                    subprocess.run(
                        ["git", "-C", str(ws), "commit", "--allow-empty", "-q", "-m", "chat start"],
                        capture_output=True, timeout=15, env=git_env,
                    )
        except OSError as e:
            print(f"Failed to set up chat workspace: {e}", file=sys.stderr)
            sys.exit(1)
        state = {
            "claude_session_id": None, "codex_session_id": None,
            "last_claude_reply": None, "last_codex_reply": None,
            "target": str(target) if target else None,
        }
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    claude_path = which_or_none(CLAUDE_BIN)
    codex_path = which_or_none(CODEX_BIN)
    available = [n for n, p, ws in (("claude", claude_path, claude_ws), ("codex", codex_path, codex_ws)) if p and ws.is_dir()]
    if not available:
        print("Neither CLI has a workspace in this chat directory - nothing to send to.", file=sys.stderr)
        sys.exit(1)

    first = args.chat_first if args.chat_first in available else available[0]
    order = [first] + [n for n in available if n != first]

    def build_cmd(name):
        ws = claude_ws if name == "claude" else codex_ws
        if name == "claude":
            if state["claude_session_id"]:
                cmd = [CLAUDE_BIN, "-p", "--resume", state["claude_session_id"], "--output-format", "text"]
            else:
                state["claude_session_id"] = str(uuid.uuid4())
                cmd = [CLAUDE_BIN, "-p", "--session-id", state["claude_session_id"], "--output-format", "text"]
            cmd += ["--dangerously-skip-permissions"] if args.yolo else ["--permission-mode", "acceptEdits"]
        else:
            if state["codex_session_id"]:
                cmd = [CODEX_BIN, "exec", "resume", state["codex_session_id"], "-", "--skip-git-repo-check"]
                if args.yolo:
                    cmd += ["--dangerously-bypass-approvals-and-sandbox"]
            else:
                cmd = [CODEX_BIN, "exec", "-", "--skip-git-repo-check"]
                cmd += ["--dangerously-bypass-approvals-and-sandbox"] if args.yolo else ["-s", "workspace-write"]
        return cmd, ws

    results = {}
    for name in order:
        other = "codex" if name == "claude" else "claude"
        other_reply = results[other]["stdout"] if other in results else state.get(f"last_{other}_reply")
        turn_message = build_crosstalk_message(message, OTHER_NAME[name], other_reply)

        cmd, ws = build_cmd(name)
        result = run_tool(name, cmd, ws, args.timeout, turn_message)
        results[name] = result

        if name == "codex" and not state.get("codex_session_id"):
            m = re.search(r"session id:\s*([0-9a-fA-F-]+)", result.get("stderr") or "")
            if m:
                state["codex_session_id"] = m.group(1)

        if result["status"] == "ok":
            state[f"last_{name}_reply"] = result["stdout"]

    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    for name, ws in (("claude", claude_ws), ("codex", codex_ws)):
        if name in results and ws.is_dir() and is_git_repo(ws):
            (chat_dir / f"{name}.diff").write_text(get_diff(ws), encoding="utf-8")

    for name in order:
        print(CHAT_BEGIN.format(name.upper()))
        r = results[name]
        print(f"status: {r['status']}" + (f" (exit {r['returncode']})" if r["returncode"] is not None else ""))
        if r["error"]:
            print(f"error: {r['error']}")
        print(r["stdout"] or "(empty)")
        if r["status"] != "ok" and r["stderr"]:
            print("--- stderr ---")
            print(r["stderr"])
        print(CHAT_END.format(name.upper()))

    sys.exit(0 if all(r["status"] == "ok" for r in results.values()) else 1)


def main():
    # On Windows, stdout/stderr default to the system ANSI codepage (cp1252
    # here) instead of UTF-8 whenever they're not a real console - which is
    # always true when the GUI captures this process's output via a pipe.
    # Claude/Codex replies routinely contain emoji or other non-Latin1
    # characters, and print() on those crashes outright under cp1252
    # (confirmed: this happened for real, mid-chat, from "Hello world! 👋").
    # Force UTF-8 unconditionally, before anything else prints.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        prog="claudexgpt",
        description="Run a task through Claude Code and Codex CLI non-interactively; save outputs; show diffs. No merging, no deciding.",
    )
    parser.add_argument("task", nargs="?", help="Task description. If omitted, you'll be prompted.")
    parser.add_argument(
        "--task-file",
        help="Read the task description from a UTF-8 text file. Useful for multi-line prompts.",
    )
    parser.add_argument(
        "-C", "--dir", default=None,
        help="Target directory to work in (default: current directory, except with --chat starting a "
             "new conversation - there, omitting this means a target-free conversation with no files "
             "copied in, since -C's usual '.' default would otherwise silently mean 'copy whatever "
             "directory the process happens to be running in', which has bitten this project before). "
             "With --apply, this is the real directory the chosen diff gets applied to.",
    )
    parser.add_argument(
        "--apply", metavar="RUN_DIR",
        help="Apply an already-saved diff from a past run (RUN_DIR is an outputs/<timestamp> folder) to "
             "the target directory (-C/--dir), instead of running any CLI. Requires --apply-which. Shows "
             "the full diff and target, then asks for explicit y/N confirmation (skip with --yes). Refuses "
             "if the target has uncommitted changes or the diff doesn't apply cleanly. This is the only "
             "thing in this tool that writes to your real target directory - everything else only ever "
             "touches disposable copies. No merge, no scoring - you already chose by picking --apply-which.",
    )
    parser.add_argument(
        "--apply-which", choices=APPLY_CHOICES,
        help="Which saved result to apply when using --apply.",
    )
    parser.add_argument(
        "--yes", "-y", action="store_true",
        help="Skip the confirmation prompt for --apply. Has no effect otherwise.",
    )
    parser.add_argument(
        "--chat", metavar="CHAT_DIR",
        help="Send one turn of a persistent 3-way conversation (you, claude, codex), instead of a "
             "one-shot run. CHAT_DIR stores the conversation's state and workspaces. If it doesn't exist "
             "yet, this is turn 1; pass -C/--dir if you want the conversation to happen inside a copy of "
             "a real project (files can then be read/edited as part of the conversation), or omit -C for "
             "a target-free conversation with nothing copied in. Later turns to the same CHAT_DIR reuse "
             "whatever was set up on turn 1 and ignore -C. The message is the normal task argument / "
             "--task-file / prompt. Turns are sequential, not parallel - whichever tool goes second in a "
             "round is shown what the first one just said (see --chat-first), and each side carries the "
             "other's latest reply forward turn to turn via claude --resume / codex exec resume, so they "
             "are genuinely responding to each other, not just independently to you. Diffs refresh after "
             "each turn using the normal claude.diff/codex.diff filenames, so a chat directory works with "
             "--apply and the GUI's Compare/Apply tabs without any special-casing. Ignores "
             "--cross-review/--revise/--no-keep-workspaces.",
    )
    parser.add_argument(
        "--chat-first", choices=("claude", "codex"), default="codex",
        help="Which tool responds first in each --chat round (default: codex). The other one then sees "
             "what it just said before replying.",
    )
    parser.add_argument(
        "--outputs-dir", default=DEFAULT_OUTPUTS_DIR,
        help=f"Where to write results (default: {DEFAULT_OUTPUTS_DIR} - kept off C: on purpose, "
             "which is space-constrained on this machine; override anytime).",
    )
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
    parser.add_argument(
        "--revise", action="store_true",
        help="After cross-review (implied automatically if this is set, even without --cross-review), give "
             "each tool exactly one chance to revise its own work in its own workspace using the review "
             "written about it (task + its own diff + that review's text - not its own original stdout again, "
             "to keep the prompt from stacking). Saved as claude_revised_output.txt / claude_revised.diff and "
             "codex_revised_output.txt / codex_revised.diff. Skipped per-side (with a _SKIPPED.txt) if that "
             "tool's primary run failed or the review of it wasn't produced. Still no merge, scoring, or "
             "winner - a third round of files to read, nothing more. Off by default.",
    )
    args = parser.parse_args()

    if args.apply:
        run_apply_mode(args)
        return

    task = read_task(args)
    if not task:
        print("No task description given.", file=sys.stderr)
        sys.exit(1)

    if args.chat:
        # Target validation for --chat is conditional (only required for a
        # brand-new chat directory), so it's handled inside run_chat_mode
        # rather than by the general target check right below this.
        run_chat_mode(args, task)
        return

    target = Path(args.dir or ".").resolve()
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

    if would_nest_inside(outputs_dir, target):
        print(
            f"Refusing to run: --outputs-dir ({outputs_dir}) is inside or equal to the target "
            f"directory ({target}). This would copy the target into a subdirectory of itself. "
            "Point --outputs-dir somewhere outside the target (e.g. run from a different folder, "
            "or pass an explicit --outputs-dir path elsewhere).",
            file=sys.stderr,
        )
        sys.exit(1)

    run_root = outputs_dir / timestamp

    print(f"Task: {task}")
    print(f"Target directory: {target}")
    print(f"Output directory: {run_root}")
    sys.stdout.flush()

    run_root.mkdir(parents=True, exist_ok=True)

    repo_mode = is_git_repo(target)

    claude_cmd = [CLAUDE_BIN, "-p", "--output-format", "text"]
    claude_cmd += ["--dangerously-skip-permissions"] if args.yolo else ["--permission-mode", "acceptEdits"]

    codex_cmd = [CODEX_BIN, "exec", "-", "--skip-git-repo-check"]
    codex_cmd += ["--dangerously-bypass-approvals-and-sandbox"] if args.yolo else ["-s", "workspace-write"]

    print("Copying target directory into isolated workspaces (can take a while for larger projects)...")
    sys.stdout.flush()

    jobs = []
    try:
        if claude_path:
            ws = run_root / "claude_workspace"
            print(f"- copying for claude -> {ws}")
            sys.stdout.flush()
            shutil.copytree(target, ws, ignore=COPY_IGNORE, symlinks=True)
            jobs.append(("claude", claude_cmd, ws))
        if codex_path:
            ws = run_root / "codex_workspace"
            print(f"- copying for codex -> {ws}")
            sys.stdout.flush()
            shutil.copytree(target, ws, ignore=COPY_IGNORE, symlinks=True)
            jobs.append(("codex", codex_cmd, ws))
    except OSError as e:
        print(f"Failed to copy target directory into a disposable workspace: {e}", file=sys.stderr)
        print("No CLI has been run yet - nothing to clean up beyond the partial copy above.", file=sys.stderr)
        sys.exit(1)

    print("Copies done.")
    print(f"Git repo detected: {repo_mode}")
    print(f"Running {len(jobs)} tool(s), timeout {args.timeout}s each - this is the slow part, please wait...")
    sys.stdout.flush()

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {pool.submit(run_tool, name, cmd, ws, args.timeout, task): name for name, cmd, ws in jobs}
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

    cross_review_enabled = args.cross_review or args.revise
    reviews = {}  # review_name -> {"result", "reviewer", "reviewed"} - kept around for --revise
    if cross_review_enabled:
        why = "--cross-review" if args.cross_review else "--revise (implies cross-review)"
        print(f"\nCross-review requested ({why}): read-only, no file edits, no merging/scoring/winner.")
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
                    reviews[review_name] = {"result": r, "reviewer": reviewer, "reviewed": reviewed, "prompt": prompt}

            for review_name, reviewer, reviewed in review_specs:
                r = reviews[review_name]["result"]
                review_path = run_root / f"{review_name}.txt"
                write_review_file(review_path, reviewer, reviewed, reviews[review_name]["prompt"], r)
                print(f"\n=== {review_name} ===")
                print(f"status: {r['status']}" + (f" (exit {r['returncode']})" if r["returncode"] is not None else ""))
                print(f"duration: {r['duration']:.2f}s")
                if r["error"]:
                    print(f"error: {r['error']}")
                print(f"saved to: {review_path}")
                if r["status"] != "ok":
                    any_failure = True

    if args.revise:
        print("\nRevision requested (--revise): each tool gets one chance to revise its own work using the "
              "review written about it. Still no merge/scoring/winner.")
        revise_cmds = {"claude": claude_cmd, "codex": codex_cmd}
        revise_specs = []
        for name in ("claude", "codex"):
            other = "codex" if name == "claude" else "claude"
            review_name = f"{other}_review_of_{name}"
            revision_name = f"{name}_revised"

            if name not in primary or primary[name]["result"]["status"] != "ok":
                skip_reason = f"'{name}' primary run did not complete successfully - nothing to revise"
            elif review_name not in reviews or reviews[review_name]["result"]["status"] != "ok":
                skip_reason = f"'{review_name}' is not available (skipped or failed) - nothing to revise from"
            else:
                skip_reason = None

            if skip_reason:
                skip_path = run_root / f"{revision_name}_SKIPPED.txt"
                skip_path.write_text(f"Revision skipped.\nReason: {skip_reason}\n", encoding="utf-8")
                print(f"\n=== {revision_name} ===")
                print(f"skipped: {skip_reason}")
                print(f"recorded to: {skip_path}")
                continue

            revise_specs.append((revision_name, name, review_name))

        if revise_specs:
            revise_results = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(revise_specs)) as pool:
                futures = {}
                for revision_name, name, review_name in revise_specs:
                    prompt = build_revision_prompt(
                        task, primary[name]["diff_text"], reviews[review_name]["result"]["stdout"]
                    )
                    cmd = revise_cmds[name]
                    cwd = primary[name]["ws"]
                    fut = pool.submit(run_tool, revision_name, cmd, cwd, args.timeout, prompt)
                    futures[fut] = (revision_name, name)
                for fut in concurrent.futures.as_completed(futures):
                    revision_name, name = futures[fut]
                    r = fut.result()
                    revise_results[revision_name] = (r, name)

            for revision_name, name, review_name in revise_specs:
                r, _ = revise_results[revision_name]
                diff_text = get_diff(primary[name]["ws"]) if repo_mode else None

                output_path = run_root / f"{revision_name}_output.txt"
                write_output_file(output_path, r, diff_text)

                diff_path = None
                if diff_text is not None:
                    diff_path = run_root / f"{revision_name}.diff"
                    diff_path.write_text(diff_text, encoding="utf-8")

                print_summary(r, output_path, diff_path)
                if diff_text:
                    print(f"--- {revision_name} diff (cumulative: original attempt + revision) ---")
                    print(diff_text)
                elif repo_mode:
                    print(f"({revision_name} made no additional file changes)")

                if r["status"] != "ok":
                    any_failure = True

    if args.no_keep_workspaces:
        for name in primary:
            shutil.rmtree(primary[name]["ws"], ignore_errors=True)

    print(f"\nAll results saved under: {run_root}")
    print_output_guide(run_root, primary, cross_review_enabled, args.revise)
    print("No merge, no scoring, no decision made - review both outputs/diffs yourself.")

    sys.exit(1 if any_failure else 0)


if __name__ == "__main__":
    main()
