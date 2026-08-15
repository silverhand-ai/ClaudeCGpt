#!/usr/bin/env python3
"""
Small Tkinter GUI for ClaudeCGpt.

Theme:
- Claude lane: orange/gray
- GPT/Codex lane: black/white
- Middle bridge: green wireframe

The GUI is intentionally a wrapper around claudexgpt.py. It does not
reimplement orchestration logic; it builds commands, runs the CLI, and streams
stdout/stderr into the app.
"""

import datetime
import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


APP_DIR = Path(__file__).resolve().parent
CLI_PATH = APP_DIR / "claudexgpt.py"

# Import the real default rather than duplicating the constant - keeps this in
# sync with claudexgpt.py automatically instead of two copies drifting apart.
sys.path.insert(0, str(APP_DIR))
from claudexgpt import DEFAULT_OUTPUTS_DIR  # noqa: E402

COLORS = {
    "bg": "#111315",
    "panel": "#181B1F",
    "panel2": "#101214",
    "border": "#2A2F35",
    "text": "#F4F3EE",
    "muted": "#B1ADA1",
    "claude": "#C15F3C",
    "claude_soft": "#DE7356",
    "gpt": "#FFFFFF",
    "gpt_dark": "#000000",
    "wire": "#10A37F",
    "wire_dim": "#0B5D4A",
    "wire_glow": "#7FFFD4",
    "human": "#E8C547",
    "danger": "#E05252",
}


class ClaudeCGptGui(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ClaudeCGpt")
        self.geometry("1120x760")
        self.minsize(960, 640)
        self.configure(bg=COLORS["bg"])

        self.proc = None
        self.worker = None
        self.messages = queue.Queue()
        self.latest_run_dir = None
        # Chat has its own proc/worker (not self.proc/self.worker) so a
        # conversation can run independently of a Run/Apply operation
        # instead of being mutually exclusive with them.
        self.chat_proc = None
        self.chat_worker = None
        self.chat_dir = None
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.python_var = tk.StringVar(value=sys.executable)
        # Deliberately blank, not APP_DIR: defaulting the target to this
        # project's own folder means an unchanged "Run" click silently copies
        # this folder instead of erroring. Blank makes the existing
        # is_dir() validation catch it and force an explicit pick, same
        # principle as the CLI's own explicit-choice design throughout.
        self.target_var = tk.StringVar(value="")
        self.outputs_var = tk.StringVar(value=DEFAULT_OUTPUTS_DIR)
        self.timeout_var = tk.StringVar(value="1800")
        self.cross_review_var = tk.BooleanVar(value=False)
        self.revise_var = tk.BooleanVar(value=False)
        self.keep_workspaces_var = tk.BooleanVar(value=True)
        self.yolo_var = tk.BooleanVar(value=False)
        self.apply_run_var = tk.StringVar(value="")
        self.apply_target_var = tk.StringVar(value="")
        self.apply_which_var = tk.StringVar(value="claude")
        self.apply_yes_var = tk.BooleanVar(value=False)

        self.compare_run_var = tk.StringVar(value="")
        self.compare_claude_variant_var = tk.StringVar(value="claude")
        self.compare_codex_variant_var = tk.StringVar(value="codex")

        self.chat_target_var = tk.StringVar(value="")
        self.chat_timeout_var = tk.StringVar(value="300")
        self.chat_yolo_var = tk.BooleanVar(value=False)
        self.chat_status_var = tk.StringVar(value="No conversation started.")
        self.chat_first_var = tk.StringVar(value="codex")

        self._configure_styles()
        self._build_ui()
        self.after(100, self._drain_messages)

    def _configure_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=COLORS["bg"])
        style.configure("Panel.TFrame", background=COLORS["panel"])
        style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["text"])
        style.configure("Muted.TLabel", background=COLORS["bg"], foreground=COLORS["muted"])
        style.configure("Panel.TLabel", background=COLORS["panel"], foreground=COLORS["text"])
        style.configure("TCheckbutton", background=COLORS["panel"], foreground=COLORS["text"])
        style.map("TCheckbutton", background=[("active", COLORS["panel"])])
        style.configure("TNotebook", background=COLORS["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background=COLORS["panel2"], foreground=COLORS["muted"], padding=(14, 8))
        style.map("TNotebook.Tab", background=[("selected", COLORS["panel"])], foreground=[("selected", COLORS["text"])])
        style.configure("Accent.TButton", background=COLORS["wire"], foreground=COLORS["gpt_dark"], padding=(14, 8))
        style.map("Accent.TButton", background=[("active", COLORS["wire_glow"])])
        style.configure("Danger.TButton", background=COLORS["danger"], foreground=COLORS["text"], padding=(14, 8))
        style.configure("Human.TButton", background=COLORS["human"], foreground=COLORS["gpt_dark"], padding=(14, 8))
        style.configure("TButton", background=COLORS["border"], foreground=COLORS["text"], padding=(10, 6))
        style.configure("TEntry", fieldbackground=COLORS["panel2"], foreground=COLORS["text"], insertcolor=COLORS["text"])
        style.configure("TCombobox", fieldbackground=COLORS["panel2"], foreground=COLORS["text"])

    def _build_ui(self):
        root = ttk.Frame(self, padding=16)
        root.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(root)
        header.pack(fill=tk.X)

        title_block = ttk.Frame(header)
        title_block.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(
            title_block,
            text="ClaudeCGpt",
            bg=COLORS["bg"],
            fg=COLORS["text"],
            font=("Segoe UI", 24, "bold"),
        ).pack(anchor="w")
        tk.Label(
            title_block,
            text="compare the minds, keep the wheel",
            bg=COLORS["bg"],
            fg=COLORS["muted"],
            font=("Segoe UI", 10),
        ).pack(anchor="w")

        self.bridge = tk.Canvas(header, height=86, width=420, bg=COLORS["bg"], highlightthickness=0)
        self.bridge.pack(side=tk.RIGHT)
        self._draw_bridge()

        ttk.Button(header, text="Restart", command=self._restart_app).pack(side=tk.RIGHT, anchor="n", padx=(0, 12))

        self.tabs = ttk.Notebook(root)
        self.tabs.pack(fill=tk.BOTH, expand=True, pady=(14, 0))

        run_tab = ttk.Frame(self.tabs, style="Panel.TFrame", padding=14)
        chat_tab = ttk.Frame(self.tabs, style="Panel.TFrame", padding=14)
        compare_tab = ttk.Frame(self.tabs, style="Panel.TFrame", padding=14)
        apply_tab = ttk.Frame(self.tabs, style="Panel.TFrame", padding=14)
        self.tabs.add(run_tab, text="Run")
        self.tabs.add(chat_tab, text="Chat")
        self.tabs.add(compare_tab, text="Compare")
        self.tabs.add(apply_tab, text="Apply")
        self.apply_tab = apply_tab
        self.compare_tab = compare_tab

        self._build_run_tab(run_tab)
        self._build_chat_tab(chat_tab)
        self._build_compare_tab(compare_tab)
        self._build_apply_tab(apply_tab)

    def _draw_bridge(self):
        c = self.bridge
        c.delete("all")
        h = 86
        mid = h // 2
        c.create_text(44, 18, text="CLAUDE", fill=COLORS["claude"], font=("Segoe UI", 9, "bold"))
        c.create_text(374, 18, text="GPT", fill=COLORS["gpt"], font=("Segoe UI", 9, "bold"))
        c.create_oval(24, 34, 64, 74, outline=COLORS["claude"], width=2)
        c.create_rectangle(354, 34, 394, 74, outline=COLORS["gpt"], width=2)
        points = [(112, mid), (156, 26), (210, mid), (264, 26), (308, mid), (264, 60), (210, mid), (156, 60)]
        for i in range(len(points)):
            x1, y1 = points[i]
            x2, y2 = points[(i + 1) % len(points)]
            c.create_line(x1, y1, x2, y2, fill=COLORS["wire_dim"], width=1)
        for x, y in points:
            c.create_oval(x - 4, y - 4, x + 4, y + 4, fill=COLORS["wire"], outline=COLORS["wire_glow"])
        c.create_line(64, 54, 112, mid, fill=COLORS["wire"], width=2)
        c.create_line(308, mid, 354, 54, fill=COLORS["wire"], width=2)
        c.create_text(210, 76, text="green wireframe exchange layer", fill=COLORS["wire_glow"], font=("Segoe UI", 8))

    def _build_run_tab(self, parent):
        top = ttk.Frame(parent, style="Panel.TFrame")
        top.pack(fill=tk.X)
        self._path_row(top, "Python", self.python_var, self._browse_python)
        self._path_row(top, "Target", self.target_var, self._browse_target)
        self._path_row(top, "Outputs", self.outputs_var, self._browse_outputs)

        ttk.Label(parent, text="Task", style="Panel.TLabel").pack(anchor="w", pady=(12, 4))
        self.task_text = tk.Text(
            parent,
            height=9,
            bg=COLORS["panel2"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief=tk.FLAT,
            wrap=tk.WORD,
            padx=10,
            pady=8,
            font=("Consolas", 10),
        )
        self.task_text.pack(fill=tk.X)

        controls = ttk.Frame(parent, style="Panel.TFrame")
        controls.pack(fill=tk.X, pady=10)
        ttk.Checkbutton(controls, text="Cross-review", variable=self.cross_review_var).pack(side=tk.LEFT, padx=(0, 14))
        ttk.Checkbutton(controls, text="Revise once", variable=self.revise_var).pack(side=tk.LEFT, padx=(0, 14))
        ttk.Checkbutton(controls, text="Keep workspaces", variable=self.keep_workspaces_var).pack(side=tk.LEFT, padx=(0, 14))
        ttk.Checkbutton(controls, text="Yolo", variable=self.yolo_var).pack(side=tk.LEFT, padx=(0, 14))
        ttk.Label(controls, text="Timeout", style="Panel.TLabel").pack(side=tk.LEFT, padx=(10, 4))
        ttk.Entry(controls, textvariable=self.timeout_var, width=8).pack(side=tk.LEFT)

        buttons = ttk.Frame(parent, style="Panel.TFrame")
        buttons.pack(fill=tk.X, pady=(0, 10))
        self.run_button = ttk.Button(buttons, text="Run ClaudeCGpt", style="Accent.TButton", command=self._start_run)
        self.run_button.pack(side=tk.LEFT)
        self.stop_button = ttk.Button(buttons, text="Stop", style="Danger.TButton", command=self._stop_process, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=8)
        ttk.Button(buttons, text="Open Latest Output", command=self._open_latest_output).pack(side=tk.LEFT, padx=8)
        ttk.Button(buttons, text="Open Project", command=lambda: self._open_path(APP_DIR)).pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(parent, textvariable=self.status_var, style="Panel.TLabel").pack(anchor="w")
        self.log_text = self._make_log(parent)

    def _build_chat_tab(self, parent):
        self._path_row(parent, "Target (optional)", self.chat_target_var, self._browse_chat_target)

        top = ttk.Frame(parent, style="Panel.TFrame")
        top.pack(fill=tk.X, pady=(4, 10))
        ttk.Button(top, text="New Conversation", style="Accent.TButton", command=self._new_chat).pack(side=tk.LEFT)
        ttk.Label(top, text="First to speak", style="Panel.TLabel").pack(side=tk.LEFT, padx=(14, 4))
        ttk.Combobox(
            top, textvariable=self.chat_first_var, values=("codex", "claude"), state="readonly", width=8,
        ).pack(side=tk.LEFT)
        ttk.Checkbutton(top, text="Yolo", variable=self.chat_yolo_var).pack(side=tk.LEFT, padx=(14, 4))
        ttk.Label(top, text="Timeout", style="Panel.TLabel").pack(side=tk.LEFT, padx=(10, 4))
        ttk.Entry(top, textvariable=self.chat_timeout_var, width=8).pack(side=tk.LEFT)
        ttk.Label(top, textvariable=self.chat_status_var, style="Panel.TLabel").pack(side=tk.LEFT, padx=(16, 0))

        ttk.Label(
            parent,
            text="A real 3-way conversation, not two separate one-on-ones: each turn is sequential, and "
                 "whoever replies second is shown what the other one just said, so they're actually "
                 "responding to each other.",
            style="Panel.TLabel", wraplength=1000,
        ).pack(anchor="w", pady=(0, 8))

        self.chat_thread_text = self._make_log(parent)
        self.chat_thread_text.tag_configure("chat_you", foreground=COLORS["human"], font=("Consolas", 9, "bold"))
        self.chat_thread_text.tag_configure("chat_claude", foreground=COLORS["claude_soft"], font=("Consolas", 9, "bold"))
        self.chat_thread_text.tag_configure("chat_codex", foreground=COLORS["gpt"], font=("Consolas", 9, "bold"))
        self.chat_thread_text.tag_configure("chat_error", foreground=COLORS["danger"])

        ttk.Label(parent, text="Message", style="Panel.TLabel").pack(anchor="w", pady=(10, 4))
        self.chat_input = tk.Text(
            parent, height=4, bg=COLORS["panel2"], fg=COLORS["text"], insertbackground=COLORS["text"],
            relief=tk.FLAT, wrap=tk.WORD, padx=10, pady=8, font=("Consolas", 10),
        )
        self.chat_input.pack(fill=tk.X)

        buttons = ttk.Frame(parent, style="Panel.TFrame")
        buttons.pack(fill=tk.X, pady=(8, 0))
        self.chat_send_button = ttk.Button(buttons, text="Send", style="Human.TButton", command=self._chat_send, state=tk.DISABLED)
        self.chat_send_button.pack(side=tk.LEFT)
        self.chat_stop_button = ttk.Button(buttons, text="Stop", style="Danger.TButton", command=self._stop_chat_process, state=tk.DISABLED)
        self.chat_stop_button.pack(side=tk.LEFT, padx=8)
        ttk.Button(buttons, text="View in Compare", command=self._view_chat_in_compare).pack(side=tk.LEFT, padx=8)

    def _browse_chat_target(self):
        path = filedialog.askdirectory(title="Select target directory (optional)")
        if path:
            self.chat_target_var.set(path)

    def _new_chat(self):
        # Target is optional here (unlike Run/Apply) - a 3-way conversation
        # doesn't need a project directory at all, just two AIs and a human.
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.chat_dir = Path(self.outputs_var.get()) / f"chat_{timestamp}"
        self._clear_log(self.chat_thread_text)
        target = self.chat_target_var.get()
        self.chat_status_var.set(
            f"New conversation: {self.chat_dir.name}" + (f" (target: {target})" if target else " (no target)")
        )
        self.chat_send_button.configure(state=tk.NORMAL)

    def _chat_send(self):
        if self.chat_dir is None:
            messagebox.showerror("No conversation", "Click 'New Conversation' first.")
            return
        if self.chat_proc is not None:
            messagebox.showwarning("Already sending", "Wait for the current message to finish.")
            return
        message = self.chat_input.get("1.0", tk.END).strip()
        if not message:
            return

        self._append_chat("You: ", "chat_you")
        self._append_chat(message + "\n\n")
        self.chat_input.delete("1.0", tk.END)

        cmd = [
            self.python_var.get(), str(CLI_PATH), message,
            "--chat", str(self.chat_dir),
            "--chat-first", self.chat_first_var.get(),
            "--timeout", self.chat_timeout_var.get(),
        ]
        target = self.chat_target_var.get()
        if target:
            # Blank means "no target" to the CLI too (see run_chat_mode) -
            # only pass -C when there's a real value, never an empty string
            # (Path("").is_dir() is True, same footgun fixed in Run/Apply).
            cmd += ["-C", target]
        if self.chat_yolo_var.get():
            cmd.append("--yolo")

        self.chat_send_button.configure(state=tk.DISABLED)
        self.chat_stop_button.configure(state=tk.NORMAL)
        self.chat_status_var.set("Sending...")
        self.chat_worker = threading.Thread(target=self._chat_worker_run, args=(cmd,), daemon=True)
        self.chat_worker.start()

    def _chat_worker_run(self, cmd):
        try:
            self.chat_proc = subprocess.Popen(
                cmd, cwd=str(APP_DIR), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
            )
            stdout, stderr = self.chat_proc.communicate()
            self.messages.put(("CHAT_RESULT", (stdout, stderr, self.chat_proc.returncode)))
        except OSError as e:
            self.messages.put(("CHAT_ERROR", str(e)))
        finally:
            self.chat_proc = None
            self.messages.put(("CHAT_DONE", None))

    def _append_chat(self, text, tag=None):
        self.chat_thread_text.configure(state=tk.NORMAL)
        self.chat_thread_text.insert(tk.END, text, tag) if tag else self.chat_thread_text.insert(tk.END, text)
        self.chat_thread_text.see(tk.END)
        self.chat_thread_text.configure(state=tk.DISABLED)

    def _render_chat_result(self, stdout, stderr, code):
        # Blocks appear in the CLI's actual speaking order for that round
        # (see run_chat_mode) - sort by where each marker shows up rather
        # than a fixed claude-then-codex order, so the thread reads as a
        # real back-and-forth instead of always favoring one side visually.
        blocks = []
        for name in ("CLAUDE", "CODEX"):
            begin, end = f"###CLAUDEXGPT_CHAT_{name}_BEGIN###", f"###CLAUDEXGPT_CHAT_{name}_END###"
            start_idx, end_idx = stdout.find(begin), stdout.find(end)
            if start_idx != -1 and end_idx != -1:
                blocks.append((start_idx, name, stdout[start_idx + len(begin):end_idx].strip("\n")))
        blocks.sort(key=lambda b: b[0])

        for _, name, content in blocks:
            label, tag = ("Claude", "chat_claude") if name == "CLAUDE" else ("Codex", "chat_codex")
            self._append_chat(f"{label}: ", tag)
            self._append_chat(content + "\n\n")
        if not blocks:
            self._append_chat("(no response found - the CLI call may have failed before replying)\n\n", "chat_error")
        if code != 0:
            note = f"[claudexgpt --chat exited {code}]"
            if stderr.strip():
                note += f"\n{stderr.strip()}"
            self._append_chat(note + "\n\n", "chat_error")

    def _stop_chat_process(self):
        if self.chat_proc is not None:
            self._kill_process_tree(self.chat_proc.pid)
            self.chat_status_var.set("Stopping...")

    def _view_chat_in_compare(self):
        if self.chat_dir is None:
            messagebox.showerror("No conversation", "Start a conversation first.")
            return
        self.compare_run_var.set(str(self.chat_dir))
        self._load_compare_run()
        self.tabs.select(self.compare_tab)

    def _build_compare_tab(self, parent):
        self._path_row(parent, "Run Dir", self.compare_run_var, self._browse_compare_run)
        ttk.Button(parent, text="Load", style="Accent.TButton", command=self._load_compare_run).pack(anchor="w", pady=(4, 10))

        columns = ttk.Frame(parent, style="Panel.TFrame")
        columns.pack(fill=tk.BOTH, expand=True)
        columns.columnconfigure(0, weight=1)
        columns.columnconfigure(1, weight=1)
        columns.rowconfigure(0, weight=1)

        (
            self.compare_claude_text,
            self.compare_claude_revised_radio,
            self.compare_review_codex_text,
        ) = self._build_compare_column(
            columns, col=0, tool="claude", label="CLAUDE", color=COLORS["claude"],
            variant_var=self.compare_claude_variant_var, review_title="Codex's review of this",
        )
        (
            self.compare_codex_text,
            self.compare_codex_revised_radio,
            self.compare_review_claude_text,
        ) = self._build_compare_column(
            columns, col=1, tool="codex", label="GPT / CODEX", color=COLORS["gpt"],
            variant_var=self.compare_codex_variant_var, review_title="Claude's review of this",
        )

    def _build_compare_column(self, parent, col, tool, label, color, variant_var, review_title):
        frame = ttk.Frame(parent, style="Panel.TFrame")
        frame.grid(row=0, column=col, sticky="nsew", padx=(0, 8) if col == 0 else (8, 0))

        tk.Label(frame, text=label, bg=COLORS["panel"], fg=color, font=("Segoe UI", 11, "bold")).pack(anchor="w")

        radios = ttk.Frame(frame, style="Panel.TFrame")
        radios.pack(anchor="w", pady=(2, 6))
        ttk.Radiobutton(
            radios, text="Original", variable=variant_var, value=tool,
            command=lambda: self._on_compare_variant_change(tool),
        ).pack(side=tk.LEFT)
        revised_radio = ttk.Radiobutton(
            radios, text="Revised", variable=variant_var, value=f"{tool}_revised",
            command=lambda: self._on_compare_variant_change(tool), state=tk.DISABLED,
        )
        revised_radio.pack(side=tk.LEFT, padx=(10, 0))

        diff_text = self._make_diff_view(frame)

        ttk.Label(frame, text=review_title, style="Panel.TLabel").pack(anchor="w", pady=(8, 2))
        review_text = self._make_log(frame, height=7)

        ttk.Button(
            frame, text="Apply this", style="Human.TButton",
            command=lambda: self._jump_to_apply(variant_var.get()),
        ).pack(anchor="w", pady=(6, 0))

        return diff_text, revised_radio, review_text

    def _make_diff_view(self, parent):
        text = self._make_log(parent)
        text.tag_configure("diff_add", foreground=COLORS["wire"])
        text.tag_configure("diff_del", foreground=COLORS["danger"])
        text.tag_configure("diff_hunk", foreground=COLORS["human"])
        text.tag_configure("diff_meta", foreground=COLORS["muted"])
        return text

    def _browse_compare_run(self):
        path = filedialog.askdirectory(title="Select run output directory")
        if path:
            self.compare_run_var.set(path)

    def _load_compare_run(self):
        run_dir_str = self.compare_run_var.get()
        if not run_dir_str or not Path(run_dir_str).is_dir():
            messagebox.showerror("Missing run directory", "Choose a valid run output directory first.")
            return
        run_dir = Path(run_dir_str)
        self._load_compare_side(run_dir, "claude")
        self._load_compare_side(run_dir, "codex")
        self._load_compare_review(run_dir, "claude_review_of_codex", self.compare_review_claude_text)
        self._load_compare_review(run_dir, "codex_review_of_claude", self.compare_review_codex_text)

    def _load_compare_side(self, run_dir, tool):
        variant_var = self.compare_claude_variant_var if tool == "claude" else self.compare_codex_variant_var
        revised_radio = self.compare_claude_revised_radio if tool == "claude" else self.compare_codex_revised_radio

        has_revised = (run_dir / f"{tool}_revised.diff").is_file() or (run_dir / f"{tool}_revised_SKIPPED.txt").is_file()
        revised_radio.configure(state=tk.NORMAL if has_revised else tk.DISABLED)
        if not has_revised and variant_var.get() == f"{tool}_revised":
            variant_var.set(tool)

        self._refresh_compare_side(run_dir, tool)

    def _on_compare_variant_change(self, tool):
        run_dir_str = self.compare_run_var.get()
        if run_dir_str and Path(run_dir_str).is_dir():
            self._refresh_compare_side(Path(run_dir_str), tool)

    def _refresh_compare_side(self, run_dir, tool):
        variant_var = self.compare_claude_variant_var if tool == "claude" else self.compare_codex_variant_var
        text_widget = self.compare_claude_text if tool == "claude" else self.compare_codex_text
        which = variant_var.get()

        diff_path = run_dir / f"{which}.diff"
        skip_path = run_dir / f"{which}_SKIPPED.txt"
        output_path = run_dir / f"{which}_output.txt"

        if diff_path.is_file():
            self._render_diff(text_widget, diff_path.read_text(encoding="utf-8", errors="replace"))
        elif skip_path.is_file():
            self._render_plain(text_widget, "SKIPPED\n\n" + skip_path.read_text(encoding="utf-8", errors="replace"))
        elif output_path.is_file():
            self._render_plain(text_widget, "(no diff file for this run - not a git repo, or made no changes)\n")
        else:
            self._render_plain(text_widget, f"(no data found for '{which}' in this run directory)\n")

    def _load_compare_review(self, run_dir, name, text_widget):
        path = run_dir / f"{name}.txt"
        skip_path = run_dir / f"{name}_SKIPPED.txt"
        if path.is_file():
            self._render_plain(text_widget, path.read_text(encoding="utf-8", errors="replace"))
        elif skip_path.is_file():
            self._render_plain(text_widget, "SKIPPED\n\n" + skip_path.read_text(encoding="utf-8", errors="replace"))
        else:
            self._render_plain(text_widget, "(no review found - --cross-review may not have been used for this run)\n")

    def _render_plain(self, text_widget, text):
        text_widget.configure(state=tk.NORMAL)
        text_widget.delete("1.0", tk.END)
        text_widget.insert(tk.END, text)
        text_widget.configure(state=tk.DISABLED)

    def _render_diff(self, text_widget, diff_text):
        text_widget.configure(state=tk.NORMAL)
        text_widget.delete("1.0", tk.END)
        if not diff_text.strip():
            text_widget.insert(tk.END, "(no changes)")
        else:
            for line in diff_text.splitlines(keepends=True):
                if line.startswith("+++") or line.startswith("---") or line.startswith("diff --git") or line.startswith("index "):
                    tag = "diff_meta"
                elif line.startswith("@@"):
                    tag = "diff_hunk"
                elif line.startswith("+"):
                    tag = "diff_add"
                elif line.startswith("-"):
                    tag = "diff_del"
                else:
                    tag = None
                text_widget.insert(tk.END, line, tag) if tag else text_widget.insert(tk.END, line)
        text_widget.configure(state=tk.DISABLED)

    def _jump_to_apply(self, which):
        run_dir_str = self.compare_run_var.get()
        if not run_dir_str:
            messagebox.showerror("No run loaded", "Load a run directory in the Compare tab first.")
            return
        self.apply_run_var.set(run_dir_str)
        self.apply_which_var.set(which)
        if not self.apply_target_var.get():
            self.apply_target_var.set(self.target_var.get())
        self.tabs.select(self.apply_tab)

    def _build_apply_tab(self, parent):
        self._path_row(parent, "Python", self.python_var, self._browse_python)
        self._path_row(parent, "Run Dir", self.apply_run_var, self._browse_apply_run)
        self._path_row(parent, "Target", self.apply_target_var, self._browse_apply_target)

        row = ttk.Frame(parent, style="Panel.TFrame")
        row.pack(fill=tk.X, pady=10)
        ttk.Label(row, text="Apply which", style="Panel.TLabel").pack(side=tk.LEFT, padx=(0, 8))
        combo = ttk.Combobox(
            row,
            textvariable=self.apply_which_var,
            values=("claude", "codex", "claude_revised", "codex_revised"),
            state="readonly",
            width=22,
        )
        combo.pack(side=tk.LEFT)
        ttk.Checkbutton(row, text="Skip GUI confirmation", variable=self.apply_yes_var).pack(side=tk.LEFT, padx=16)

        buttons = ttk.Frame(parent, style="Panel.TFrame")
        buttons.pack(fill=tk.X, pady=(0, 10))
        self.apply_button = ttk.Button(buttons, text="Apply Chosen Diff", style="Human.TButton", command=self._start_apply)
        self.apply_button.pack(side=tk.LEFT)
        self.apply_stop_button = ttk.Button(buttons, text="Stop", style="Danger.TButton", command=self._stop_process, state=tk.DISABLED)
        self.apply_stop_button.pack(side=tk.LEFT, padx=8)

        ttk.Label(
            parent,
            text="Apply is the only mode that writes to the real target. The CLI still performs its own git safety checks.",
            style="Panel.TLabel",
        ).pack(anchor="w")
        self.apply_log_text = self._make_log(parent)

    def _path_row(self, parent, label, variable, command):
        row = ttk.Frame(parent, style="Panel.TFrame")
        row.pack(fill=tk.X, pady=3)
        ttk.Label(row, text=label, style="Panel.TLabel", width=9).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=variable).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        ttk.Button(row, text="Browse", command=command).pack(side=tk.LEFT)

    def _make_log(self, parent, height=None):
        frame = ttk.Frame(parent, style="Panel.TFrame")
        if height is None:
            frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        else:
            # Fixed-size panel (e.g. the smaller review boxes in Compare) -
            # don't expand and eat space from the main diff view above it.
            frame.pack(fill=tk.X, pady=(8, 0))
        text = tk.Text(
            frame,
            bg="#080A0B",
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief=tk.FLAT,
            wrap=tk.WORD,
            font=("Consolas", 9),
            padx=10,
            pady=8,
            height=height if height is not None else 10,
        )
        scroll = ttk.Scrollbar(frame, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        text.configure(state=tk.DISABLED)
        return text

    def _browse_python(self):
        path = filedialog.askopenfilename(title="Select Python", filetypes=[("Python", "python*.exe"), ("All files", "*.*")])
        if path:
            self.python_var.set(path)

    def _browse_target(self):
        path = filedialog.askdirectory(title="Select target directory")
        if path:
            self.target_var.set(path)
            self.apply_target_var.set(path)

    def _browse_outputs(self):
        path = filedialog.askdirectory(title="Select outputs directory")
        if path:
            self.outputs_var.set(path)

    def _browse_apply_run(self):
        path = filedialog.askdirectory(title="Select run output directory")
        if path:
            self.apply_run_var.set(path)

    def _browse_apply_target(self):
        path = filedialog.askdirectory(title="Select target directory")
        if path:
            self.apply_target_var.set(path)

    def _append_log(self, text_widget, text):
        text_widget.configure(state=tk.NORMAL)
        text_widget.insert(tk.END, text)
        text_widget.see(tk.END)
        text_widget.configure(state=tk.DISABLED)

    def _clear_log(self, text_widget):
        text_widget.configure(state=tk.NORMAL)
        text_widget.delete("1.0", tk.END)
        text_widget.configure(state=tk.DISABLED)

    def _set_running(self, running):
        state = tk.DISABLED if running else tk.NORMAL
        stop_state = tk.NORMAL if running else tk.DISABLED
        self.run_button.configure(state=state)
        self.apply_button.configure(state=state)
        self.stop_button.configure(state=stop_state)
        self.apply_stop_button.configure(state=stop_state)

    def _start_run(self):
        task = self.task_text.get("1.0", tk.END).strip()
        if not task:
            messagebox.showerror("Missing task", "Paste or type a task first.")
            return
        target = self.target_var.get()
        # Path("").is_dir() is True (pathlib normalizes "" to "." - the
        # current directory), so an empty target would silently pass this
        # check and run against APP_DIR (the subprocess's cwd) instead of
        # failing loudly - exactly the footgun the blank default was
        # supposed to prevent. Reject blank explicitly before is_dir().
        if not target or not Path(target).is_dir():
            messagebox.showerror("Missing target", "Choose a valid target directory.")
            return

        cmd = [
            self.python_var.get(),
            str(CLI_PATH),
            task,
            "-C",
            target,
            "--outputs-dir",
            self.outputs_var.get(),
            "--timeout",
            self.timeout_var.get(),
        ]
        if self.cross_review_var.get():
            cmd.append("--cross-review")
        if self.revise_var.get():
            cmd.append("--revise")
        if not self.keep_workspaces_var.get():
            cmd.append("--no-keep-workspaces")
        if self.yolo_var.get():
            cmd.append("--yolo")

        self._clear_log(self.log_text)
        self._run_subprocess(cmd, self.log_text, "Running...")

    def _start_apply(self):
        # Same Path("").is_dir() == True footgun as _start_run - reject
        # blank explicitly, don't let it silently fall through to cwd.
        run_dir = self.apply_run_var.get()
        if not run_dir or not Path(run_dir).is_dir():
            messagebox.showerror("Missing run directory", "Choose a valid run output directory.")
            return
        apply_target = self.apply_target_var.get()
        if not apply_target or not Path(apply_target).is_dir():
            messagebox.showerror("Missing target", "Choose a valid target directory.")
            return
        if not self.apply_yes_var.get():
            ok = messagebox.askyesno(
                "Apply selected diff?",
                "This will ask the CLI to apply the selected saved diff to the real target directory.\n\n"
                f"Run dir: {self.apply_run_var.get()}\n"
                f"Target: {self.apply_target_var.get()}\n"
                f"Choice: {self.apply_which_var.get()}\n\n"
                "The CLI will still run its git safety checks before applying.",
            )
            if not ok:
                return

        cmd = [
            self.python_var.get(),
            str(CLI_PATH),
            "--apply",
            self.apply_run_var.get(),
            "--apply-which",
            self.apply_which_var.get(),
            "-C",
            self.apply_target_var.get(),
            "--yes",
        ]

        self._clear_log(self.apply_log_text)
        self._run_subprocess(cmd, self.apply_log_text, "Applying...")

    def _run_subprocess(self, cmd, log_widget, status):
        if self.proc is not None:
            messagebox.showwarning("Already running", "A command is already running.")
            return
        self.status_var.set(status)
        self._set_running(True)
        self._append_log(log_widget, "> " + subprocess.list2cmdline(cmd) + "\n\n")
        self.worker = threading.Thread(target=self._worker_run, args=(cmd, log_widget), daemon=True)
        self.worker.start()

    def _worker_run(self, cmd, log_widget):
        try:
            self.proc = subprocess.Popen(
                cmd,
                cwd=str(APP_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            for line in self.proc.stdout:
                match = re.search(r"All results saved under:\s*(.+)\s*$", line)
                if match:
                    self.latest_run_dir = match.group(1).strip()
                    # Tk variables/widgets aren't safe to touch off the main
                    # thread - route through the message queue like everything
                    # else here, instead of calling .set() directly.
                    self.messages.put(("RUN_DIR", self.latest_run_dir))
                self.messages.put((log_widget, line))
            code = self.proc.wait()
            self.messages.put((log_widget, f"\n[exit {code}]\n"))
            self.messages.put(("STATUS", "Ready." if code == 0 else f"Finished with exit {code}."))
        except OSError as e:
            self.messages.put((log_widget, f"\n[error] {e}\n"))
            self.messages.put(("STATUS", "Error."))
        finally:
            self.proc = None
            self.messages.put(("DONE", None))

    def _drain_messages(self):
        try:
            while True:
                target, payload = self.messages.get_nowait()
                if target == "STATUS":
                    self.status_var.set(payload)
                elif target == "DONE":
                    self._set_running(False)
                elif target == "RUN_DIR":
                    self.apply_run_var.set(payload)
                    self.compare_run_var.set(payload)
                    self._load_compare_run()
                elif target == "CHAT_RESULT":
                    stdout, stderr, code = payload
                    self._render_chat_result(stdout, stderr, code)
                elif target == "CHAT_ERROR":
                    self._append_chat(f"[error] {payload}\n\n", "chat_error")
                elif target == "CHAT_DONE":
                    self.chat_send_button.configure(state=tk.NORMAL)
                    self.chat_stop_button.configure(state=tk.DISABLED)
                    self.chat_status_var.set(f"Conversation: {self.chat_dir.name}" if self.chat_dir else "Ready.")
                else:
                    self._append_log(target, payload)
        except queue.Empty:
            pass
        self.after(100, self._drain_messages)

    def _stop_process(self):
        if self.proc is not None:
            self._kill_process_tree(self.proc.pid)
            self.status_var.set("Stopping...")

    def _kill_process_tree(self, pid):
        # proc.terminate() only signals the immediate claudexgpt.py process,
        # not the claude/codex child processes it may have spawned via
        # subprocess.run() - those would be left running in the background,
        # still consuming API usage, with the GUI showing "Stopped". /T kills
        # the whole tree rooted at pid instead of just the one process.
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

    def _kill_all_running(self):
        # Shared by close and restart - neither should leave a claude/codex
        # call running unattended in the background, same reasoning as the
        # Stop button.
        if self.proc is not None:
            self._kill_process_tree(self.proc.pid)
        if self.chat_proc is not None:
            self._kill_process_tree(self.chat_proc.pid)

    def _on_close(self):
        self._kill_all_running()
        self.destroy()

    def _restart_app(self):
        if not messagebox.askyesno("Restart", "Close and relaunch ClaudeCGpt now? Any running message/task will be stopped."):
            return
        self._kill_all_running()
        try:
            subprocess.Popen([sys.executable, str(Path(__file__).resolve())], cwd=str(APP_DIR))
        except OSError as e:
            messagebox.showerror("Restart failed", f"Could not relaunch: {e}")
            return
        self.destroy()

    def _open_latest_output(self):
        if self.latest_run_dir:
            self._open_path(Path(self.latest_run_dir))
        elif Path(self.outputs_var.get()).exists():
            self._open_path(Path(self.outputs_var.get()))
        else:
            messagebox.showinfo("No output yet", "No output directory has been created yet.")

    def _open_path(self, path):
        try:
            os.startfile(str(path))
        except OSError as e:
            messagebox.showerror("Open failed", str(e))


def main():
    app = ClaudeCGptGui()
    app.mainloop()


if __name__ == "__main__":
    main()
