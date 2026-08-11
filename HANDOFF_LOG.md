# ClaudeCGpt Handoff Log

Shared coordination log for Cody/Codex and Claude/VS Code so work does not overlap.

## Current Project Location

- Local folder: `C:\Users\Rebel\Desktop\ahahahaahahhh`
- Main script: `claudexgpt.py`
- GitHub repo reserved: `https://github.com/silverhand-ai/ClaudeCGpt`

## Current Constraints

- **2026-08-11: Claude/VS Code should not invoke `codex` CLI for a while** (no smoke tests, no primary/review/revise calls through `claudexgpt.py`). User needs Codex's usage headroom for something else right now. Any work that would normally require running Codex to verify should be skipped and flagged here for Cody/Codex to pick up and finish once it's back in use - not worked around by Claude. Lift this note once the user says Codex is free to use again.

## Phase 1 Target

Build the smallest useful ClaudeCGpt bridge:

- Accept one task description.
- Run the task through Claude Code CLI non-interactively.
- Run the task through Codex CLI non-interactively.
- Save each output separately.
- Show/save diffs for comparison.
- Do not auto-merge.
- Do not score.
- Do not decide a winner.

## Verified CLI Syntax

Claude Code (confirmed against `claude --help`, smoke-tested with a real file-writing task):

```powershell
claude -p "<task>" --output-format text --permission-mode acceptEdits
```

`--permission-mode acceptEdits` is required for headless runs that need to actually write files — without it, Edit/Write tool calls have no TTY to prompt against.

Codex (confirmed against `codex exec --help`, smoke-tested with a real file-writing task):

```powershell
codex exec "<task>" -s workspace-write --skip-git-repo-check
```

Correction: `codex exec` does **not** accept `-a/--ask-for-approval` — that flag only exists on the top-level interactive `codex` command, not the `exec` subcommand. Passing it to `exec` fails with "unexpected argument '-a' found". `exec` is non-interactive by default; `-s workspace-write` alone is what lets it write files. `--skip-git-repo-check` avoids a hard failure when the workspace isn't a git repo.

## Cody/Codex Notes

### 2026-08-10 23:50 America/New_York

Marked by: Cody/Codex

What I did:

- Read the pasted Claude/VS Code progress log from `C:\Users\Rebel\.codex\attachments\dc7e7fe2-f09f-4e30-8745-2eb6da4af7ec\pasted-text.txt`.
- Confirmed from that log that Claude/VS Code installed both CLIs with npm:
  - `npm install -g @anthropic-ai/claude-code`
  - `npm install -g @openai/codex`
- Confirmed from that log that both commands resolve through npm shims under `C:\Users\Rebel\AppData\Roaming\npm`.
- Inspected `C:\Users\Rebel\Desktop\ahahahaahahhh`.
- Found `claudexgpt.py` present.
- Read the script enough to confirm it is a real Phase 1 implementation shape: separate workspaces, parallel CLI runs, saved outputs, optional git diffs, no merge/scoring/decision.
- Tried to run a Python compile check but the available `python.exe` was only the Windows Store alias and `py.exe` reported no installed Python.
- Attempted to install portable Python under a non-`C:` drive at the user's request, but the earlier sandbox state blocked external-drive writes and then PowerShell command startup.
- After sandbox permissions changed to unrestricted, created this shared handoff log.

Why:

- The user wants Claude and Cody/Codex to coordinate through a shared file so we do not duplicate or overwrite each other's work.
- Python needs to be runnable before `claudexgpt.py` can be syntax-checked or smoke-tested locally.

## Claude/VS Code Notes

### 2026-08-10 23:52 (local)

Marked by: Claude/VS Code

What I did:

- Wrote `claudexgpt.py`: single-file, stdlib-only Python script. Copies the target dir into two disposable workspaces (`outputs/<timestamp>/claude_workspace`, `codex_workspace`), runs both CLIs concurrently via `subprocess` (with `shell=True` on Windows — required because npm installs `claude`/`codex` as `.cmd` shims, which `CreateProcess` can't launch directly without going through `cmd.exe`), captures stdout/stderr/exit code/duration for each into `outputs/<timestamp>/{claude,codex}_output.txt`, and if the target is a git repo, stages all changes in each workspace copy and saves/prints `{claude,codex}.diff`. No merge, no scoring, no winner-picking — just both results saved and printed for manual review.
- Missing/failed CLIs are handled per-tool (checked via `shutil.which` before running, wrapped in try/except at call time) — one missing or failing tool never blocks or crashes the run of the other.
- Found and fixed the `codex exec -a` bug noted above via direct testing (see Verified CLI Syntax).
- Fixed a `subprocess`-on-Windows bug where `.cmd` shims raised `FileNotFoundError` without `shell=True`.
- Found a working Python: the registered `python.exe` (Python 3.11) and the `py` launcher are both broken on this machine (`python.exe --version` fails with `0x80070003`, "cannot find the file specified"). Used `C:\Users\Rebel\.local\bin\python3.12.exe` (a `uv`-managed install) instead — that one works fine. Not fixed (out of scope), just noting it as the same blocker Cody/Codex hit.
- Smoke-tested end-to-end 4 times using throwaway git repos in the temp scratchpad (not this project folder): (1) real file-writing task in a git repo — both tools produced correct diffs; (2) non-git target dir — diff step correctly skipped; (3) both CLIs unreachable via PATH — clean graceful error, exit 1, no crash; (4) one CLI unreachable — the other still ran and reported results, the missing one reported clearly as `not_installed`.

Why:

- User asked for the smallest useful version: one task in, both CLIs run headless, outputs saved separately, diff shown if applicable, no auto-merge/scoring/deciding. Confirmed CLI syntax against `--help` output before writing any code, per explicit instruction not to guess flags.

Still open / not done by me:

- Git has not been initialized in this folder, and nothing has been pushed to `github.com/silverhand-ai/ClaudeCGpt`. Not done pending explicit user go-ahead (repo push is a shared-visibility action).
- The broken system Python (3.11 / `py` launcher) is unfixed — anyone running this script needs to either fix that or invoke `python3.12.exe` from `~/.local/bin` directly.
- `--yolo` flag exists in the script (bypasses permission/sandbox checks in both tools) but defaults off; not exercised in smoke tests beyond the default-safe path.

## Open Items

- Initialize git in `C:\Users\Rebel\Desktop\ahahahaahahhh` when the user is ready.
- Push first commit to `https://github.com/silverhand-ai/ClaudeCGpt.git` after the initial script is verified.

### 2026-08-10 23:59 America/New_York

Marked by: Cody/Codex

What I did:

- Installed portable Python 3.14.7 under `D:\Tools\Python\3.14.7`.
- Added `D:\Tools\Python\3.14.7` to the front of the user `PATH`.
- Updated the current shell `PATH` so `python` resolves immediately without opening a new terminal.
- Verified `python --version` reports `Python 3.14.7`.
- Verified `Get-Command python` resolves to `D:\Tools\Python\3.14.7\python.exe`.
- Ran:

```powershell
python -m py_compile "C:\Users\Rebel\Desktop\ahahahaahahhh\claudexgpt.py"
```

Verification:

- `claudexgpt.py` passed Python bytecode compilation with no syntax errors.

Why:

- The project script is Python, and the previous default `python` command was only resolving to the Windows Store alias.
- The user asked to install Python somewhere other than `C:\` and make sure it is on `PATH`.

### 2026-08-11 (local)

Marked by: Claude/VS Code

Starting Phase 2: optional `--cross-review` mode.

What I intend to change in `claudexgpt.py`:

- Add a `--cross-review` CLI flag, off by default. Default (no-flag) behavior must stay byte-for-byte identical to Phase 1 — no changes to the existing primary-run code path.
- When enabled, after both primary runs complete: have Claude review Codex's result and Codex review Claude's result, each review including the original task, the other tool's stdout/stderr/status, and its git diff (if available).
- Reviews will be read-only by construction, not just by prompt instruction: Claude's review call uses `--tools ""` (disables all tools), Codex's uses `-s read-only`. Just verified both directly — asked each to create a file under these flags and confirmed via `git status --porcelain` that nothing was written.
- Review prompts will be passed via stdin (`codex exec -` / `claude -p` with no positional arg), not as a CLI argument — verified this works for multi-line input on both. Passing a multi-line prompt as a literal argv element would go through `cmd.exe` (needed for the `.cmd` shims) which mishandles embedded newlines; stdin avoids that risk entirely for these prompts.
- Saved as `claude_review_of_codex.txt` / `codex_review_of_claude.txt` in the same timestamped run directory as the primary outputs.
- If the tool being reviewed is missing or didn't complete successfully (status != "ok"), or the reviewing tool itself is missing, that side of the cross-review is skipped with a `_SKIPPED.txt` marker recording why — no partial/misleading review file gets written.
- No auto-merge, no scoring, no winner logic added anywhere.

## Coordination Rule

Before editing `claudexgpt.py`, read this file and append a new dated note describing:

- what you changed,
- why you changed it,
- how you verified it,
- anything still blocked.

### 2026-08-11 00:04 America/New_York

Marked by: Cody/Codex

What I did:

- Prepared the folder for the first git push.
- Added `README.md`.
- Added `.gitignore` to keep generated `outputs/` and Python cache files out of version control.
- Initialized git in `C:\Users\Rebel\Desktop\ahahahaahahhh`.
- Created commit `09da191` with message `Initial ClaudeCGpt bridge CLI`.
- Renamed the branch to `main`.
- Added remote `origin` as `https://github.com/silverhand-ai/ClaudeCGpt.git`.
- Tried to push `main` to GitHub.

Why:

- The user asked to push the project.
- Keeping smoke-test outputs uncommitted makes the first repository commit focused on the reusable tool and coordination notes.

Verification / result:

- Local commit succeeded.
- Push failed with GitHub 403:
  - `Permission to silverhand-ai/ClaudeCGpt.git denied to damienbroke60356-a11y.`

Still blocked:

- Git is authenticated as a GitHub account that does not have write access to `silverhand-ai/ClaudeCGpt`.
- Retry `git push -u origin main` after authenticating git/GitHub CLI/browser credentials as an account with permission to that repository.

### 2026-08-11 (local) - Phase 2 complete

Marked by: Claude/VS Code

What I changed in `claudexgpt.py`:

- Added `--cross-review` flag (off by default). Verified the default (no-flag) path is byte-identical in behavior to Phase 1: same files written, no cross-review section printed, exit code 0, using the real CLIs (not a simulation).
- `run_tool()` now takes an optional `stdin_input` param (default `None`, so all existing Phase 1 call sites are unaffected). When set, the prompt is piped via stdin instead of being an argv element.
- New functions: `build_review_prompt()`, `build_reviewer_cmd()`, `write_review_file()`.
- When `--cross-review` is set, after both primary runs finish: Claude reviews Codex's result and Codex reviews Claude's, each saved to `claude_review_of_codex.txt` / `codex_review_of_claude.txt` in the same run directory.
- Review calls are hardcoded read-only regardless of `--yolo`: `claude -p --tools ""` (all tools disabled) and `codex exec -s read-only`. Verified directly (see previous entry) that both refuse to write a file under these flags.
- Review prompts go in via stdin (`input=` to `subprocess.run`), not as a CLI arg, to avoid `cmd.exe` mangling the multi-line prompt text (cmd.exe is the required intermediary for the npm `.cmd` shims on Windows via `shell=True`).
- Skip logic: a review is skipped (with a `<name>_SKIPPED.txt` marker recording the reason) if the tool being reviewed is missing or didn't finish with status `ok`, or if the reviewing tool itself is missing. If the reviewing tool IS installed but fails at call time (e.g. auth/API error), that's not pre-empted — it's attempted and the failure is captured in the normal `status: failed` review file, same as any other tool failure elsewhere in this script. Confirmed this distinction with a forced-failure test (see below).
- Workspace cleanup (`--no-keep-workspaces`) now happens after cross-review instead of immediately after each primary run, since review needs the workspace dir as `cwd`.

Verification:

```powershell
python -m py_compile claudexgpt.py
```
Result: compiled clean, no errors.

Smoke tests (throwaway git repos in a temp scratch dir, not this project folder):
1. `--cross-review` against a real 2-tool run: both primary diffs correct, both `claude_review_of_codex.txt` / `codex_review_of_claude.txt` written with sensible review text, prompt included in full in each file for auditability.
2. Confirmed via `git status --porcelain` in both `claude_workspace/` and `codex_workspace/` that the review calls made zero additional file changes beyond the primary run's own edit.
3. Forced one primary tool (codex) to fail via a PATH-shadowed stub `codex.cmd` that exits 1: `claude_review_of_codex` correctly skipped with a `_SKIPPED.txt` explaining why (codex, the reviewed tool, didn't complete successfully); `codex_review_of_claude` was still attempted (codex the *reviewer* was "installed", just failing) and correctly captured as `status: failed` with the stub's stderr in the file, no crash.
4. Re-ran without `--cross-review` (real CLIs): output set and exit code identical to pre-Phase-2 behavior - confirms the default path is unchanged.

Anything still risky/unfinished:

- Cross-review review-prompt construction embeds the *entire* stdout/stderr of the reviewed tool's primary run. For a very large/verbose primary run this could make the review prompt large; no truncation was added (kept minimal per the "small, stdlib-only" constraint) - a real concern only for unusually large tasks.
- Not addressed (pre-existing, out of scope for Phase 2): Phase 1's own primary task argument is still passed as an argv element through `cmd.exe`, so a user-supplied task description containing embedded newlines could hit the same quoting risk that motivated stdin for review prompts. Only cross-review's own prompts were changed to use stdin.

### 2026-08-11 (local) - verified an unlogged update

Marked by: Claude/VS Code

Found `claudexgpt.py` had been changed (no matching entry here, so I couldn't tell who by - reads like Codex given it directly closes the item I flagged above). Verified it rather than assuming it's safe, per the coordination rule.

What changed (as found, not by me):

- Added `--task-file` flag + `read_task()` - reads the task from a UTF-8 file instead of the CLI arg.
- Primary `claude`/`codex` calls now pipe the task via stdin instead of passing it as an argv element (`claude -p` with no positional prompt; `codex exec -`). This is exactly the fix for the risk I noted in my last entry (task text surviving `cmd.exe` argv quoting).
- Added `print_output_guide()` - prints a full list of every output file's path at the end of a run.

Verification performed:

```powershell
python -m py_compile claudexgpt.py
```
Result: compiled clean.

Smoke tests (throwaway git repo, temp scratch dir):
1. Default mode, task as CLI arg: Claude ran fine over stdin. Codex failed - but with `ERROR: You've hit your usage limit. Upgrade to Plus to continue using Codex... or try again at Sep 9th, 2026` in stderr. That's an account-level quota limit, unrelated to this code change - and the script handled it exactly as designed (`status: failed`, clear error captured in `codex_output.txt`, no crash, Claude's run unaffected).
2. `--task-file` with a genuinely multi-line task, plus `--cross-review`, against the same repo: file was read correctly, real newlines preserved through to Claude (confirmed in the diff - it correctly implemented what the multi-line task asked for), `claude_review_of_codex` correctly skipped with a reason (`codex` didn't complete successfully) via `_SKIPPED.txt`, `codex_review_of_claude` was attempted and correctly captured the same quota failure as `status: failed`, no crash.

Operationally important: **Codex CLI on this account is rate-limited until 2026-09-09** (per the error above). Any `claudexgpt.py` run before then will show Codex as failed - that's the account, not the tool.

Note for whoever made this change: please add your own dated entry for it per the Coordination Rule below - I'm logging this as a verification pass on an already-made change, not as the change's own record.

Also fixed a small doc bug while I was in there: README's "Verified CLI forms" section still showed the task embedded as a quoted argv element (`claude -p "<task>"` / `codex exec "<task>"`), which contradicted the correct stdin explanation elsewhere in the same file. Updated to `claude -p ...` / `codex exec - ...` with no task in the argv, matching actual current behavior.

### 2026-08-11 (local) - starting Phase 3: optional `--revise` mode

Marked by: Claude/VS Code

User asked what Phase 3 should be. Landed on: give each tool exactly one chance to revise its own output using the review written about it, still no merge/scoring/winner. User specifically flagged the cost/prompt-size tradeoff (this stacks a 3rd LLM call on top of primary+review, and naively could stack the same growing context each time) and asked for a mitigation before building it. Agreed approach:

- New `--revise` flag, separate from `--cross-review`. Passing `--revise` implies cross-review runs too (revision needs a review to work from) - `--cross-review` alone still means "just the two reviews, no revision," same as today.
- Revision prompt is deliberately trimmed, not a naive stack: task + the tool's own diff (already have it) + the *other* tool's review text of it (already have it, already concise by design). It does **not** re-embed the tool's own original stdout/stderr - that was only needed once, to generate the review; revision doesn't need to see its own rambling again, just the diff and the verdict.
- Revision runs in the tool's own existing primary workspace (already has the code from its first attempt), not a fresh copy - reuses `primary[name]["ws"]`, same permission/sandbox flags as the primary run (this is a tool editing its own prior work, not reviewing someone else's - the read-only constraint from cross-review doesn't apply here).
- Output: `claude_revised_output.txt` / `codex_revised_output.txt` (stdout/stderr) and `claude_revised.diff` / `codex_revised.diff` (cumulative diff of the workspace after revision, i.e. original attempt + revision combined) - if not a git repo, diff is skipped same as primary.
- Skipped (with a `_SKIPPED.txt` marker) if: the tool's own primary run didn't succeed, or the review written about it wasn't produced successfully (skipped/failed) - nothing to revise from in that case.
- Still no comparison/scoring between "before" and "after" diffs done by the script itself - that's on the human, same principle as everything else here.

Will implement, then verify with `python -m py_compile` and a real smoke test, then report back.

### 2026-08-11 (local) - Phase 3 complete, plus a real bug found and fixed

Marked by: Claude/VS Code

Implemented `--revise` as planned above. Verification:

```powershell
python -m py_compile claudexgpt.py
```
Result: compiled clean.

Smoke tests (throwaway git repo, temp scratch dir):
1. Real Claude + a stubbed `codex.cmd` (Codex's account is still quota-limited, so a real full happy-path run wasn't possible - see the earlier entry). Stub distinguishes `-s read-only` (review) vs `-s workspace-write` (primary/revise) calls so the actual orchestration logic gets exercised for real, only the "AI content" is canned. Full pipeline ran clean: both primaries ok -> both reviews ok -> both revisions ok. Claude's revision correctly left its file untouched because the (stubbed) review said it looked fine - confirms the "don't make unnecessary changes" instruction in the revision prompt is being followed, and confirms the trimmed prompt (task + own diff + review text, no re-embedded stdout) is sufficient for the model to make that call.
2. Default mode (no flags), real CLIs: identical output set to before Phase 3, no cross-review/revise sections - confirms no regression.
3. `--cross-review` alone (no `--revise`), real Claude + stub Codex: reviews ran, no revision files appeared - confirms `--revise` is the only thing that triggers revision, `--cross-review` alone is unchanged from Phase 2.
4. `--no-keep-workspaces` + `--revise` together: needed to confirm workspace cleanup was correctly deferred until after revision (revision needs the workspace as `cwd`) - this is where things got interesting, see below.

**Found a real, unrelated bug while running test 4, not caused by Phase 3's own code:** the user's C: drive was down to 88 KB free (out of 238 GB) mid-test. Investigated (with permission) rather than assuming it was pre-existing background noise. Root cause: `C:\Users\Rebel\outputs\` contained ~36 GB from an earlier run where the tool was invoked with both `-C` and `--outputs-dir` left at their defaults while the working directory was the user's home folder (`C:\Users\Rebel`) - meaning `outputs_dir` (default `"outputs"`, relative) resolved to a subdirectory *inside* the target being copied. `shutil.copytree` has no built-in protection against copying a directory into a subdirectory of itself - confirmed this directly in an isolated sandbox test. Because the target was enormous (135 GB) and the copy took a long time, the growing `outputs/` folder kept getting swept up into its own copy as it went, ballooning disk usage.

Fix applied to `claudexgpt.py`:
- Before creating `run_root` or copying anything, check whether `outputs_dir` is equal to or nested inside `target`. If so, refuse to run with a clear error explaining why, instead of silently copying the target into itself. Verified this blocks the exact reproduced hazard with zero side effects, and does not affect the normal documented usage pattern (target and outputs-dir in different locations, as in the README example) - re-tested that path after the fix, still works.
- Wrapped the primary `shutil.copytree` calls in `try/except OSError` so a disk-full or permission error during the copy fails with a clear message and `sys.exit(1)` instead of an unhandled traceback.

Disk cleanup itself (deleting the accumulated `C:\Users\Rebel\outputs\`) is a separate action from this code fix - handled directly with the user, not logged as script behavior since it's not something `claudexgpt.py` did to fix itself, it's manual cleanup of a past mistake.

Anything still risky/unfinished:

- The new guard only checks the `outputs_dir`/`target` relationship once, at startup. It does not (and doesn't need to) protect against a user manually pointing `--outputs-dir` somewhere unrelated that happens to have its own separate problems (e.g. a network drive, a read-only path) - those still fail via the new `OSError` handling around copytree, just with a generic message rather than a specific diagnosis.
- Revision's happy path was only verified against a stub for Codex, not two real CLIs simultaneously (blocked by the quota until Codex is unblocked). The orchestration logic is confirmed correct; the actual quality of a real Codex revision response is unverified.

### 2026-08-11 (local) - fixed a real "looks frozen" UX bug

Marked by: Claude/VS Code

User reported: after typing a task at the interactive `Task description:` prompt and hitting Enter, the terminal just stops - nothing prints, looks hung.

Root cause, confirmed by reading the code: `print(f"Task: {task}")` and the rest of the startup summary were placed *after* both `shutil.copytree` calls in `main()`, not before. Those copies can take real time on anything bigger than a toy repo, and during that whole window nothing was printed at all - looked exactly like a frozen terminal, because from the user's perspective it was silent from the moment they hit Enter until the first tool actually finished running.

Fix: moved `Task:` / `Target directory:` / new `Output directory:` prints to immediately after input is read and validated, before `run_root.mkdir()` or any copying starts. Added an explicit "Copying target directory into isolated workspaces (can take a while for larger projects)..." line plus a per-tool "- copying for claude/codex -> <path>" line right before each `shutil.copytree` call, and a "Copies done." after. Added `sys.stdout.flush()` at each of these points as a defensive measure in case output isn't line-buffered in whatever terminal it's run from.

Verification:
```powershell
python -m py_compile claudexgpt.py
```
Result: compiled clean.

Smoke test: real Claude + real Codex (Codex succeeded this run - quota may have reset), default mode, throwaway git repo. Confirmed the full startup summary (task, target dir, output dir, copy-in-progress lines, "Copies done.", git-repo-detected, running-N-tools) now all print immediately, well before either CLI actually starts - no more silent gap between hitting Enter and seeing output.

Not yet committed/pushed - same as everything else recently, holding for the user's go-ahead.

### 2026-08-11 (local) - default --outputs-dir moved to F:

Marked by: Claude/VS Code

User hit the self-copy guard again (correctly - ran with no `-C`/`--outputs-dir`, defaults resolved to `C:\Users\Rebel` both ways) and said to use D: or F: as the dumping location if one is needed. Checked free space: C: 66G free, D: 635G free, F: 1.1T free (most headroom) - picked F:.

Changed `--outputs-dir` default from relative `"outputs"` to `DEFAULT_OUTPUTS_DIR = r"F:\ClaudeXGPT_outputs"` (new constant near the top, alongside `CLAUDE_BIN`/`CODEX_BIN`). Still fully overridable via `--outputs-dir` as before - this only changes what happens when it's left unset.

Verification:
```powershell
python -m py_compile claudexgpt.py
```
Result: compiled clean.

Smoke test: real run with explicit small `-C` (a throwaway repo, not the home directory) and no `--outputs-dir` - confirmed output landed under `F:\ClaudeXGPT_outputs\<timestamp>\` automatically, no flag needed.

Note not acted on: the user's failing command still had no `-C` either, meaning target defaulted to `C:\Users\Rebel` (their whole home folder) - this fix only relocates *outputs*, it doesn't stop someone from pointing the *target* at their home directory, which would still copy ~170GB into two workspaces even with the disk-safety guard passing. Flagged this to the user directly rather than silently guessing they meant something else; not a code change since there's nothing invalid about deliberately targeting a huge directory, just wasteful.

### 2026-08-11 (local) - Phase 4: `--apply` (human-selection apply helper)

Marked by: Claude/VS Code

User said to build "whatever's next" while the Codex-usage constraint above is in effect. Landed on Phase 4 from the earlier roadmap discussion (Cody/Codex's original proposal, both of us agreed it was the right next step, unlike Phase 5's "combined patch synthesis" which I'd flagged as conflicting with the whole project's "no auto-merge" principle - not built, and I don't think it should be without a very different framing). Good fit for the current constraint too: applying an already-saved diff to the real target is pure git/file operations, no CLI usage at all.

What it does: new `--apply <run_dir> --apply-which {claude,codex,claude_revised,codex_revised}` mode. Short-circuits at the top of `main()` before any task-reading, CLI-availability checks, or workspace copying - it's a fully separate code path (`run_apply_mode()`), not a variant of the normal run. Takes `<run_dir>/<which>.diff` (a file already produced by a past normal run) and applies it to the target directory (`-C`/`--dir`) via `git apply`, after printing the full diff and target path and requiring explicit `y/N` confirmation (`--yes` skips the prompt for scripted use). This is the only code path in the whole tool that writes to the real target directory - every other mode only ever touches disposable copies.

Safety behavior:
- Refuses if `--apply-which` wasn't given.
- Refuses if the named diff file doesn't exist in `run_dir` (tool wasn't run there, was skipped, or run wasn't against a git repo).
- If the diff file exists but is empty (that tool made no changes), reports that and exits 0 - nothing to do, not an error.
- Refuses if the target isn't a git repo (needs `git apply`).
- Refuses if the target has any uncommitted changes (`git status --porcelain` non-empty) - won't mix the applied diff with unrelated edits.
- Runs `git apply --check` before the real `git apply`, so a diff that doesn't apply cleanly (e.g. target has diverged, or already has these changes) fails with git's own error and changes nothing, rather than a partial/broken apply.

Still true here same as everywhere else in this tool: no auto-merge, no scoring, no winner picked - the human already decided by choosing `--apply-which`.

Verification (all via hand-crafted fixtures / a zero-API-call stub, per the current Codex constraint - no real `codex exec` calls were made):
```powershell
python -m py_compile claudexgpt.py
```
Result: compiled clean.

1. Hand-crafted a throwaway git repo + a synthetic `claude.diff` (no CLI involved at all) to test the apply mechanics in isolation: decline (`n`) leaves target untouched; accept (`y`) applies correctly and the new file's content is exactly right.
2. Confirmed the dirty-target refusal by leaving the applied file uncommitted and re-running - refused with the uncommitted-changes message, then committed and re-tested clean.
3. Missing `--apply-which` errors clearly. Missing diff file (`--apply-which codex` when only `claude.diff` exists) errors clearly. Empty diff file reports "nothing to apply" and exits 0.
4. Re-applying an already-applied diff correctly fails at the `git apply --check` stage ("already exists in working directory"), target stays untouched, exit 1.
5. `--yes` correctly skips the confirmation prompt.
6. Full real-workflow regression: ran a normal (no `--apply`) pass with a real Claude call and a zero-API-call Codex stub (`exit /b 0`, never contacts the API) against a throwaway repo - output set identical to before Phase 4, confirming the new argparse options didn't break the normal path. Then applied the real `claude.diff` produced by that run to the same repo with `--apply` - worked end to end, file landed with the exact content Claude wrote.

Not yet committed/pushed. Nothing here required Codex - the constraint noted above is still in effect and wasn't touched.
