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
DEFAULT_OUTPUTS_DIR = r"F:\ClaudeXGPT_outputs"

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

        self.python_var = tk.StringVar(value=sys.executable)
        self.target_var = tk.StringVar(value=str(APP_DIR))
        self.outputs_var = tk.StringVar(value=DEFAULT_OUTPUTS_DIR)
        self.timeout_var = tk.StringVar(value="1800")
        self.cross_review_var = tk.BooleanVar(value=False)
        self.revise_var = tk.BooleanVar(value=False)
        self.keep_workspaces_var = tk.BooleanVar(value=True)
        self.yolo_var = tk.BooleanVar(value=False)
        self.apply_run_var = tk.StringVar(value="")
        self.apply_target_var = tk.StringVar(value=str(APP_DIR))
        self.apply_which_var = tk.StringVar(value="claude")
        self.apply_yes_var = tk.BooleanVar(value=False)

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

        tabs = ttk.Notebook(root)
        tabs.pack(fill=tk.BOTH, expand=True, pady=(14, 0))

        run_tab = ttk.Frame(tabs, style="Panel.TFrame", padding=14)
        apply_tab = ttk.Frame(tabs, style="Panel.TFrame", padding=14)
        tabs.add(run_tab, text="Run")
        tabs.add(apply_tab, text="Apply")

        self._build_run_tab(run_tab)
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

    def _make_log(self, parent):
        frame = ttk.Frame(parent, style="Panel.TFrame")
        frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
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
        )
        scroll = ttk.Scrollbar(frame, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
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
        text_widget.configure(state=tk.NORMAL)

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
        if not Path(self.target_var.get()).is_dir():
            messagebox.showerror("Missing target", "Choose a valid target directory.")
            return

        cmd = [
            self.python_var.get(),
            str(CLI_PATH),
            task,
            "-C",
            self.target_var.get(),
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

        self.log_text.delete("1.0", tk.END)
        self._run_subprocess(cmd, self.log_text, "Running...")

    def _start_apply(self):
        if not Path(self.apply_run_var.get()).is_dir():
            messagebox.showerror("Missing run directory", "Choose a valid run output directory.")
            return
        if not Path(self.apply_target_var.get()).is_dir():
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

        self.apply_log_text.delete("1.0", tk.END)
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
                    self.apply_run_var.set(self.latest_run_dir)
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
                else:
                    self._append_log(target, payload)
        except queue.Empty:
            pass
        self.after(100, self._drain_messages)

    def _stop_process(self):
        if self.proc is not None:
            self.proc.terminate()
            self.status_var.set("Stopping...")

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
