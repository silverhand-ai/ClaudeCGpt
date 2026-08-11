# ClaudeCGpt

ClaudeCGpt is a tiny bridge for comparing Claude Code and Codex on the same task.

It takes one task description, runs it through both CLIs non-interactively in separate disposable workspace copies, saves each output, and shows/saves diffs when the target directory is a git repo.

No auto-merge. No scoring. No winner-picking.

## Requirements

- Python 3.11+
- Claude Code CLI on `PATH`
- Codex CLI on `PATH`
- Git, for diff generation

Verified CLI forms (task is piped via stdin, not passed as an argument - see below):

```powershell
claude -p --output-format text --permission-mode acceptEdits
codex exec - -s workspace-write --skip-git-repo-check
```

## Usage

From this folder:

```powershell
python .\claudexgpt.py "Add a function called greet(name) that returns 'Hello, ' + name to a new file greet.py" -C "C:\path\to\target"
```

For multi-line prompts, put the task in a text file:

```powershell
python .\claudexgpt.py --task-file .\task.txt -C "C:\path\to\target"
```

If no task is provided, the script prompts for one:

```powershell
python .\claudexgpt.py -C "C:\path\to\target"
```

To enable Phase 2 cross-review:

```powershell
python .\claudexgpt.py --task-file .\task.txt -C "C:\path\to\target" --cross-review
```

Results are written under:

```text
outputs\<timestamp>\
```

Each run may include:

- `claude_output.txt`
- `codex_output.txt`
- `claude.diff`
- `codex.diff`
- `claude_review_of_codex.txt` when `--cross-review` is enabled
- `codex_review_of_claude.txt` when `--cross-review` is enabled
- `claude_workspace\`
- `codex_workspace\`

The original target directory is copied before either tool runs, so the script does not directly modify the target.

The task is piped to both CLIs via stdin, which keeps multi-line prompts from getting mangled by Windows command-line quoting.

## GUI

Launch the desktop wrapper with:

```powershell
.\launch_gui.cmd
```

Or directly:

```powershell
C:\Users\Rebel\.local\bin\python3.12.exe .\claudexgpt_gui.py
```

The GUI is a small Tkinter control panel around `claudexgpt.py`.

- Pick a target folder.
- Paste a task.
- Choose `Cross-review`, `Revise once`, `Keep workspaces`, or `Yolo`.
- Run and watch the CLI output stream live.
- Open the latest output folder.
- Apply a chosen saved diff through the Apply tab.

The theme uses Claude orange/gray on one side, GPT black/white on the other, and a green wireframe bridge in the middle.
