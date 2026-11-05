"""The window. Everything slow runs on a worker thread, which only talks back
through a queue: tkinter must only ever be touched from the main thread."""
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import restore
import update
from commands import Runner
from stack import Stack

POLL_MS = 100
MAX_LOG_LINES = 5000
PAD = 8
CHANGE_LABELS = {update.UPGRADE: "Needs upgrade", update.RESTART: "Restart only", None: ""}
TICKED, UNTICKED = "☑", "☐"


class App:
    def __init__(self, root, config, activity):
        self.root = root
        self.config = config
        self.activity = activity
        self.events = queue.Queue()
        self.stack = Stack(Runner(config.project_dir, self._emit_line), config)
        self.busy = False
        self.action_widgets = []
        self.status = None
        self.selected = set()
        self.backup_info = None

        root.title(f"Odoo Admin - {config.database}")
        root.geometry("1000x700")
        root.minsize(820, 600)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_header()
        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True, padx=PAD)
        notebook.add(self._build_update_tab(notebook), text="Update")
        notebook.add(self._build_restore_tab(notebook), text="Restore")
        self._build_log()

        root.after(POLL_MS, self._poll_events)
        self.refresh_overview()
        self._refresh_action_states()

    # Layout

    def _build_header(self):
        frame = ttk.Frame(self.root, padding=PAD)
        frame.pack(fill="x")
        self.overview_var = tk.StringVar(value="Reading status...")
        ttk.Label(frame, textvariable=self.overview_var, justify="left").pack(side="left", fill="x", expand=True)
        self._action(ttk.Button(frame, text="Back up now", command=self.backup_now)).pack(side="right")
        self._action(ttk.Button(frame, text="Refresh", command=self.refresh_overview)).pack(side="right", padx=PAD)

    def _build_update_tab(self, parent):
        tab = ttk.Frame(parent, padding=PAD)
        top = ttk.Frame(tab)
        top.pack(fill="x")
        self._action(ttk.Button(top, text="Check for updates", command=self.check_updates)).pack(side="left")
        self.update_info_var = tk.StringVar(value="Click Check for updates to see what is new.")
        ttk.Label(top, textvariable=self.update_info_var, wraplength=760, justify="left").pack(side="left", padx=PAD)

        self.commits = tk.Listbox(tab, height=4, activestyle="none")
        self.commits.pack(fill="x", pady=PAD)

        table = ttk.Frame(tab)
        table.pack(fill="both", expand=True)
        columns = ("tick", "module", "state", "change")
        self.module_tree = ttk.Treeview(table, columns=columns, show="headings", height=8, selectmode="none")
        for column, title, width, stretch in (
            ("tick", "", 40, False),
            ("module", "Module", 300, True),
            ("state", "Status", 130, False),
            ("change", "Change", 150, False),
        ):
            self.module_tree.heading(column, text=title)
            self.module_tree.column(column, width=width, stretch=stretch, anchor="center" if column == "tick" else "w")
        self.module_tree.tag_configure("changed", font=("Segoe UI", 9, "bold"))
        scrollbar = ttk.Scrollbar(table, command=self.module_tree.yview)
        self.module_tree.configure(yscrollcommand=scrollbar.set)
        self.module_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.module_tree.bind("<Button-1>", self._on_module_click)

        bottom = ttk.Frame(tab)
        bottom.pack(fill="x", pady=(PAD, 0))
        self.backup_first = tk.BooleanVar(value=True)
        self._action(ttk.Checkbutton(bottom, text="Back up before updating", variable=self.backup_first)).pack(side="left")
        self.update_button = self._action(ttk.Button(bottom, text="Update", command=self.start_update))
        self.update_button.pack(side="right")
        return tab

    def _build_restore_tab(self, parent):
        tab = ttk.Frame(parent, padding=PAD)
        row = ttk.Frame(tab)
        row.pack(fill="x")
        ttk.Label(row, text="Backup folder:").pack(side="left")
        self.folder_var = tk.StringVar()
        self._action(ttk.Entry(row, textvariable=self.folder_var)).pack(side="left", fill="x", expand=True, padx=PAD)
        self._action(ttk.Button(row, text="Choose folder...", command=self.choose_backup)).pack(side="left")
        self._action(ttk.Button(row, text="Check", command=self.verify_backup)).pack(side="left", padx=(PAD, 0))
        self.folder_var.trace_add("write", lambda *_: self._forget_backup())

        self.backup_info_var = tk.StringVar(value="Choose a backup folder to begin.")
        ttk.Label(tab, textvariable=self.backup_info_var, wraplength=900, justify="left").pack(fill="x", pady=PAD)

        self.restore_mode = tk.StringVar(value="copy")
        copy_box = ttk.LabelFrame(tab, text="Create a copy to inspect (safe)", padding=PAD)
        copy_box.pack(fill="x")
        self._action(ttk.Radiobutton(
            copy_box, text="Restore into a new database, with crons and mail disabled. Production is not affected.",
            variable=self.restore_mode, value="copy", command=self._refresh_action_states,
        )).pack(anchor="w")
        row = ttk.Frame(copy_box)
        row.pack(fill="x", pady=(PAD, 0))
        ttk.Label(row, text="Copy name:").pack(side="left")
        self.copy_name_var = tk.StringVar()
        self.copy_name_entry = self._action(ttk.Entry(row, textvariable=self.copy_name_var, width=50))
        self.copy_name_entry.pack(side="left", padx=PAD)

        overwrite_box = ttk.LabelFrame(tab, text="Overwrite production (dangerous)", padding=PAD)
        overwrite_box.pack(fill="x", pady=PAD)
        self._action(ttk.Radiobutton(
            overwrite_box,
            text=f"Replace {self.config.database} with this backup. Odoo stops during the swap; current data is backed up and kept.",
            variable=self.restore_mode, value="overwrite", command=self._refresh_action_states,
        )).pack(anchor="w")
        row = ttk.Frame(overwrite_box)
        row.pack(fill="x", pady=(PAD, 0))
        ttk.Label(row, text=f"Type {self.config.database} to confirm:").pack(side="left")
        self.confirm_var = tk.StringVar()
        self.confirm_var.trace_add("write", lambda *_: self._refresh_action_states())
        self.confirm_entry = self._action(ttk.Entry(row, textvariable=self.confirm_var, width=30))
        self.confirm_entry.pack(side="left", padx=PAD)

        self.restore_button = self._action(ttk.Button(tab, text="Restore", command=self.start_restore))
        self.restore_button.pack(anchor="e")
        return tab

    def _build_log(self):
        frame = ttk.Frame(self.root, padding=PAD)
        frame.pack(fill="both", expand=True)
        self.log_text = ScrolledText(frame, height=8, state="disabled", wrap="word", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)

    def _action(self, widget):
        """A widget to disable while an operation runs."""
        self.action_widgets.append(widget)
        return widget

    # Running work off the main thread

    def run_job(self, title, work, on_success=None, on_failure_note=""):
        if self.busy:
            return
        self.busy = True
        self._refresh_action_states()
        self._emit_line(f"=== {title}")

        def target():
            try:
                self.events.put(("done", title, work(), None, on_success, on_failure_note))
            except Exception as error:
                self.events.put(("done", title, None, error, on_success, on_failure_note))

        threading.Thread(target=target, daemon=True).start()

    def _emit_line(self, line):
        self.activity.write(line)
        self.events.put(("line", line))

    def _poll_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "line":
                    self._append_log(event[1])
                elif event[0] == "overview":
                    self.overview_var.set(event[1])
                else:
                    self._finish_job(*event[1:])
        except queue.Empty:
            pass
        self.root.after(POLL_MS, self._poll_events)

    def _finish_job(self, title, result, error, on_success, on_failure_note):
        self.busy = False
        if error:
            self._emit_line(f"=== {title}: ERROR: {error}")
            messagebox.showerror(title, f"{error}\n\n{on_failure_note}".strip())
        elif on_success:
            on_success(result)
        self._refresh_action_states()
        self.refresh_overview()

    def _append_log(self, line):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        excess = int(self.log_text.index("end-1c").split(".")[0]) - MAX_LOG_LINES
        if excess > 0:
            self.log_text.delete("1.0", f"{excess}.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _refresh_action_states(self):
        for widget in self.action_widgets:
            widget.configure(state="disabled" if self.busy else "normal")
        if self.busy:
            return
        self.update_button.configure(state="normal" if self.status and not self.status.blockers else "disabled")
        overwriting = self.restore_mode.get() == "overwrite"
        self.copy_name_entry.configure(state="disabled" if overwriting else "normal")
        self.confirm_entry.configure(state="normal" if overwriting else "disabled")
        ready = self.backup_info is not None and (
            not overwriting or self.confirm_var.get() == self.config.database
        )
        self.restore_button.configure(state="normal" if ready else "disabled")

    def _on_close(self):
        if self.busy and not messagebox.askyesno(
            "Running", "An operation is running. Closing now can leave the system half-done. Close anyway?",
            icon="warning", default="no",
        ):
            return
        self.root.destroy()

    # Header

    def refresh_overview(self):
        def work():
            try:
                info = self.stack.overview()
                text = (
                    f"Project: {self.config.project_dir}   |   Branch: {info.branch}   |   Free disk: {info.free_disk_gb:.0f} GB\n"
                    f"Commit: {info.commit}\n"
                    f"Services: {info.services or 'not running'}"
                )
            except Exception as error:
                text = f"Cannot read the status: {error}"
            self.events.put(("overview", text))

        threading.Thread(target=work, daemon=True).start()

    def backup_now(self):
        database = self.config.database
        self.run_job(
            "Back up now",
            lambda: self.stack.runner.run([str(self.config.backup_script), database]),
            on_success=lambda _: self._emit_line("=== Backup finished."),
        )

    # Update

    def check_updates(self):
        self.status = None
        self.run_job("Check for updates", lambda: update.check_for_updates(self.stack), on_success=self._show_status)

    def _show_status(self, status):
        self.status = status
        self.selected = {module.name for module in status.modules if module.selected_by_default}
        if status.blockers:
            text = "CANNOT UPDATE: " + " ".join(status.blockers)
        elif status.has_new_code:
            text = f"{len(status.commits)} new commit(s)."
            if status.needs_image_build:
                text += " Dockerfile or compose changed: the image will be rebuilt."
        else:
            text = "The code is up to date. Modules can still be selected to upgrade."
        self.update_info_var.set(text)
        self.commits.delete(0, "end")
        for commit in status.commits:
            self.commits.insert("end", commit)
        self._fill_modules()

    def _fill_modules(self):
        self.module_tree.delete(*self.module_tree.get_children())
        for module in self.status.modules:
            self.module_tree.insert(
                "", "end", iid=module.name,
                values=self._module_row(module), tags=("changed",) if module.change else (),
            )

    def _module_row(self, module):
        state = "Installed" if module.installed else ("Not installed" if module.state == "uninstalled" else module.state)
        tick = TICKED if module.name in self.selected else UNTICKED
        return (tick, module.name, state, CHANGE_LABELS[module.change])

    def _on_module_click(self, event):
        name = self.module_tree.identify_row(event.y)
        if not name or self.busy:
            return
        self.selected.symmetric_difference_update({name})
        module = next(module for module in self.status.modules if module.name == name)
        self.module_tree.item(name, values=self._module_row(module))

    def start_update(self):
        status = self.status
        names = [module.name for module in status.modules if module.name in self.selected]
        if not status.has_new_code and not names:
            messagebox.showinfo("Update", "There is no new code and no module is selected.")
            return
        steps = []
        if self.backup_first.get():
            steps.append(f"Back up {self.config.database}")
        if status.has_new_code:
            steps.append(f"Get {len(status.commits)} new commit(s)")
        if status.needs_image_build:
            steps.append("Rebuild the image")
        if names:
            steps.append("Update modules: " + ", ".join(names))
        steps.append("Restart Odoo if needed, which briefly interrupts users")
        warning = "" if self.backup_first.get() else "\n\nWARNING: backup is off. If this fails, there is no up-to-date copy to go back to."
        if not messagebox.askyesno("Update", "This will:\n- " + "\n- ".join(steps) + warning + "\n\nContinue?"):
            return
        backup = self.backup_first.get()
        self.run_job(
            "Update",
            lambda: update.run_update(self.stack, status, names, backup=backup),
            on_success=self._after_update,
            on_failure_note=f"Commit before the update: {status.current[:10]}. The steps after the error did not run. See the log below.",
        )

    def _after_update(self, _):
        self.status = None
        self.selected = set()
        self.update_info_var.set("Update finished. Click Check for updates to look again.")
        self.commits.delete(0, "end")
        self.module_tree.delete(*self.module_tree.get_children())
        messagebox.showinfo("Update", "Update finished.")

    # Restore

    def choose_backup(self):
        root = self.config.backup_root
        folder = filedialog.askdirectory(
            title="Choose a backup folder", initialdir=root if root.is_dir() else None, mustexist=True,
        )
        if folder:
            self.folder_var.set(folder)
            self.verify_backup()

    def _forget_backup(self):
        self.backup_info = None
        self.backup_info_var.set("Click Check to read this backup through.")
        self._refresh_action_states()

    def verify_backup(self):
        folder = self.folder_var.get().strip()
        if not folder:
            return

        def work():
            info = restore.inspect_backup(folder)
            objects = restore.verify_backup(self.stack, info)
            return info, objects

        self.run_job("Check backup", work, on_success=self._show_backup)

    def _show_backup(self, result):
        info, objects = result
        self.backup_info = info
        text = (
            f"Valid. Database in the backup: {info.source_database}   |   "
            f"Size: {info.size_mb:,.0f} MB   |   {objects} objects in the dump."
        )
        if info.online_only:
            text += f"\nNote: {', '.join(info.online_only)} only on OneDrive so far, downloaded when read."
        self.backup_info_var.set(text)
        self.copy_name_var.set(restore.default_copy_name(info.source_database))

    def start_restore(self):
        info = self.backup_info
        if self.restore_mode.get() == "overwrite":
            self._start_overwrite(info)
        else:
            self._start_copy(info)

    def _start_copy(self, info):
        target = self.copy_name_var.get().strip()
        if not messagebox.askyesno("Restore", f"Restore {info.folder.name}\ninto a new database: {target}\n\nContinue?"):
            return
        self.run_job(
            "Restore a copy",
            lambda: restore.restore_copy(self.stack, info, target),
            on_success=lambda name: messagebox.showinfo("Restore", f"Copy {name} created."),
        )

    def _start_overwrite(self, info):
        database = self.config.database
        confirmed = self.confirm_var.get()
        if not messagebox.askyesno(
            "OVERWRITE PRODUCTION",
            f"Replace all data of {database} with the backup:\n{info.folder.name}\n\n"
            f"- Current data is backed up to {self.config.safety_backup_root}\n"
            "- Every change made since this backup will be gone from the running system\n"
            "- Odoo stops during the swap\n\nAre you sure?",
            icon="warning", default="no",
        ):
            return
        self.run_job(
            "Overwrite production",
            lambda: restore.restore_overwrite(self.stack, info, confirmed),
            on_success=self._after_overwrite,
        )

    def _after_overwrite(self, keep):
        self.confirm_var.set("")
        messagebox.showinfo("Restore", f"Overwrite finished. Previous data kept as {keep}.")
