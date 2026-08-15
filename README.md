# ClaudeCGpt

One window where you, Claude, and Codex can talk, compare, revise, and apply work - with a human deciding everything that matters.

It started as a one-shot "run the same task through both CLIs and diff the results" harness. It's grown into that plus a real 3-way conversation mode, review/revision passes, and a way to apply whichever result you actually want. Through all of it: no auto-merge, no scoring, no winner-picking. The tool never decides anything for you - it just makes it faster to see what each side did (or said) and act on it.

## Requirements

- Python 3.11+
- Claude Code CLI on `PATH`
- Codex CLI on `PATH`
- Git, for diff generation and `--apply`
- Tkinter (for the GUI only - the CLI is stdlib-only otherwise)

Verified CLI forms (task/message is piped via stdin, not passed as an argument - see below):

```powershell
claude -p --output-format text --permission-mode acceptEdits
codex exec - -s workspace-write --skip-git-repo-check
```

## The four things this tool does

### 1. Compare - run one task through both, side by side

```powershell
python .\claudexgpt.py "Add a function called greet(name) that returns 'Hello, ' + name to a new file greet.py" -C "C:\path\to\target"
```

Each tool runs non-interactively in its own disposable copy of the target directory, so neither sees the other's edits and your real files are never touched. Outputs, and diffs (if the target is a git repo), are saved and printed for you to read.

For multi-line prompts, put the task in a text file instead:

```powershell
python .\claudexgpt.py --task-file .\task.txt -C "C:\path\to\target"
```

If no task is given, the script prompts for one interactively.

Add `--cross-review` to have each tool read the other's diff and write a read-only review of it (no file access during review, regardless of `--yolo`). Add `--revise` (implies `--cross-review`) to additionally give each tool one chance to revise its own work using the review written about it. Both are off by default.

```powershell
python .\claudexgpt.py --task-file .\task.txt -C "C:\path\to\target" --cross-review --revise
```

### 2. Chat - an actual 3-way conversation

```powershell
python .\claudexgpt.py "hey, what do you two think about..." --chat "F:\ClaudeXGPT_outputs\my_conversation"
```

Not two independent one-on-ones with the same human - a real conversation. Turns are sequential: whichever tool replies second in a round is shown what the first one *just* said, and each side's latest reply carries forward round to round (`--chat-first {codex,claude}`, default `codex`, picks who goes first). Session continuity is real `claude --resume` / `codex exec resume`, not prompt-stuffing.

Add `--discuss` when you want them to put their brains together before control returns to you. It runs the normal human-triggered round, then adds bounded agent-to-agent discussion rounds:

```powershell
python .\claudexgpt.py "talk this through before I decide" --chat "F:\ClaudeXGPT_outputs\my_conversation" --discuss --discussion-rounds 2
```

`-C`/`--dir` is only needed on the *first* message of a new chat directory, and only if you want the conversation to happen inside a copy of a real project (so files can be read/edited as part of talking). Omit it for a target-free conversation - nothing gets copied, it's just the three of you talking. Later messages to the same chat directory ignore `-C` and reuse whatever was set up on turn 1.

Diffs refresh after every turn using the same `claude.diff`/`codex.diff` filenames a normal run produces, so a chat directory works with `--apply` and the GUI's Compare/Apply tabs with no special-casing. Chat directories also append a readable `chat_transcript.md` and structured `chat_turns.jsonl` after every turn.

### 3. Apply - pick one, apply it for real

```powershell
python .\claudexgpt.py --apply "F:\ClaudeXGPT_outputs\20260101_120000" --apply-which claude -C "C:\path\to\real\project"
```

`--apply-which` is one of `claude`, `codex`, `claude_revised`, `codex_revised`. Shows the full diff, refuses if the target has uncommitted changes or the diff won't apply cleanly, and asks for explicit `y/N` confirmation (`--yes` to skip it). **This is the only thing in the whole tool that writes to a real target directory** - every other mode only ever touches disposable copies. You already decided by picking `--apply-which`; nothing here merges or scores anything.

### 4. The GUI - all three of the above without memorizing flags

```powershell
.\launch_gui.cmd
```

Four tabs:

- **Run** - target folder, task box, `Cross-review`/`Revise once`/`Keep workspaces`/`Yolo` toggles, live output log, open-latest-output.
- **Chat** - the 3-way conversation as a single scrolling thread (You / Claude / Codex, color-coded), optional target, "First to speak" control, bounded discussion mode, and transcript opener.
- **Compare** - load any run directory and see Claude's and Codex's diffs side by side with syntax coloring, an Original/Revised toggle per side, and the other tool's review of each diff shown underneath. "Apply this" jumps straight to Apply, pre-filled.
- **Apply** - pick a run directory and a result, confirm, done.

The theme is Claude orange/gray on one side, GPT black/white on the other, and a green wireframe bridge in the middle.

## Where results are written

Default output location is `F:\ClaudeXGPT_outputs` (kept off `C:` on purpose - override anytime with `--outputs-dir`). A normal run writes to `<outputs-dir>\<timestamp>\`; a chat conversation writes to whatever directory you pointed `--chat` at.

Files you may see in a run/chat directory, depending on what was used:

- `claude_output.txt`, `codex_output.txt` - stdout/stderr/status/duration
- `claude.diff`, `codex.diff` - refreshed after every chat turn, or written once per normal run
- `claude_review_of_codex.txt`, `codex_review_of_claude.txt` - with `--cross-review`
- `claude_revised_output.txt`/`claude_revised.diff`, `codex_revised_output.txt`/`codex_revised.diff` - with `--revise`
- `claude_workspace\`, `codex_workspace\` - the disposable copies themselves (chat conversations keep these persistently, since the conversation continues inside them)
- `chat_state.json` - session ids and last replies, chat directories only
- `chat_transcript.md` - readable full conversation transcript, chat directories only
- `chat_turns.jsonl` - structured append-only turn log, chat directories only

The original target directory is copied before any tool touches anything (or not copied at all, for a target-free chat) - nothing here modifies your real files except `--apply`, on purpose, with confirmation.

The task/message is piped to both CLIs via stdin, which keeps multi-line prompts from getting mangled by Windows command-line quoting.
