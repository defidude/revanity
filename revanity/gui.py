"""
CustomTkinter GUI for revanity.

Provides a modern dark-themed interface for vanity address generation
with real-time progress, difficulty estimation, and result export.
"""

import os
import sys
from typing import Optional

try:
    import customtkinter as ctk
    HAS_CTK = True
except ImportError:
    HAS_CTK = False

from revanity import __version__
from revanity.matcher import MatchMode, MatchPattern, validate_hex_pattern, estimate_difficulty
from revanity.generator import VanityGenerator, GeneratorResult, GeneratorStats
from revanity.export import prepare_export, save_identity_file, save_identity_text, ExportedIdentity
from revanity.verify import verify_with_rns

POLL_MS = 200


class ReVanityApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(f"revanity v{__version__}")
        self.geometry("720x850")
        self.minsize(620, 750)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.generator: Optional[VanityGenerator] = None
        self.current_results: list[GeneratorResult] = []
        self.current_export: Optional[ExportedIdentity] = None
        self._radio_buttons: list = []

        self._build_ui()
        self._update_difficulty()

    # ── Click-target fixes ───────────────────────────────────────────
    # CustomTkinter on macOS has a known bug where clicking on the
    # text label inside a CTkButton or CTkRadioButton does not fire
    # the command.  We work around this by binding <Button-1> on
    # every internal child widget so clicks propagate correctly.

    @staticmethod
    def _fix_button_click(btn, command):
        """Bind <Button-1> on all child widgets of a CTkButton."""
        def handler(event):
            if str(btn.cget("state")) == "disabled":
                return
            command()
        for child in btn.winfo_children():
            child.bind("<Button-1>", handler)
            for grandchild in child.winfo_children():
                grandchild.bind("<Button-1>", handler)

    @staticmethod
    def _fix_radio_click(rb, variable, value, command):
        """Bind <Button-1> on all child widgets of a CTkRadioButton."""
        def handler(event):
            if str(rb.cget("state")) == "disabled":
                return
            variable.set(value)
            rb.select()
            if command:
                command()
        for child in rb.winfo_children():
            child.bind("<Button-1>", handler)
            for grandchild in child.winfo_children():
                grandchild.bind("<Button-1>", handler)

    # ── UI Construction ──────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        self._build_header()
        self._build_settings()
        self._build_controls()
        self._build_progress()
        self._build_results()

    def _build_header(self):
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="ew", padx=15, pady=(15, 5))

        ctk.CTkLabel(
            frame, text="revanity",
            font=ctk.CTkFont(size=26, weight="bold"),
        ).pack()
        ctk.CTkLabel(
            frame, text="Reticulum / LXMF Vanity Address Generator",
            font=ctk.CTkFont(size=13),
        ).pack()

    def _build_settings(self):
        frame = ctk.CTkFrame(self)
        frame.grid(row=1, column=0, sticky="ew", padx=15, pady=5)
        frame.grid_columnconfigure(1, weight=1)

        row = 0

        # Destination type
        ctk.CTkLabel(frame, text="Destination:", anchor="w").grid(
            row=row, column=0, sticky="w", padx=(15, 5), pady=6
        )
        dest_frame = ctk.CTkFrame(frame, fg_color="transparent")
        dest_frame.grid(row=row, column=1, sticky="ew", padx=(0, 15), pady=6)

        self.dest_var = ctk.StringVar(value="lxmf.delivery")
        self.dest_menu = ctk.CTkOptionMenu(
            dest_frame, variable=self.dest_var,
            values=["lxmf.delivery", "nomadnetwork.node", "Custom..."],
            command=self._on_dest_changed, width=200,
        )
        self.dest_menu.pack(side="left")

        self.custom_dest_entry = ctk.CTkEntry(
            dest_frame, placeholder_text="app.aspect", width=180
        )

        row += 1

        # Match mode
        ctk.CTkLabel(frame, text="Match Mode:", anchor="w").grid(
            row=row, column=0, sticky="w", padx=(15, 5), pady=6
        )
        mode_frame = ctk.CTkFrame(frame, fg_color="transparent")
        mode_frame.grid(row=row, column=1, sticky="ew", padx=(0, 15), pady=6)

        self.mode_var = ctk.StringVar(value="prefix")
        self._radio_buttons = []
        for m in ["prefix", "suffix", "contains", "regex"]:
            rb = ctk.CTkRadioButton(
                mode_frame, text=m.capitalize(),
                variable=self.mode_var, value=m,
                command=self._update_difficulty,
            )
            rb.pack(side="left", padx=6)
            self._radio_buttons.append(rb)
            self._fix_radio_click(rb, self.mode_var, m, self._update_difficulty)

        row += 1

        # Pattern
        ctk.CTkLabel(frame, text="Pattern:", anchor="w").grid(
            row=row, column=0, sticky="w", padx=(15, 5), pady=6
        )
        self.pattern_var = ctk.StringVar()
        self.pattern_var.trace_add("write", lambda *_: self._update_difficulty())
        self.pattern_entry = ctk.CTkEntry(
            frame, textvariable=self.pattern_var,
            placeholder_text="e.g. dead, cafe, beef (hex characters)",
        )
        self.pattern_entry.grid(
            row=row, column=1, sticky="ew", padx=(0, 15), pady=6
        )

        row += 1

        # Workers
        ctk.CTkLabel(frame, text="Workers:", anchor="w").grid(
            row=row, column=0, sticky="w", padx=(15, 5), pady=6
        )
        worker_frame = ctk.CTkFrame(frame, fg_color="transparent")
        worker_frame.grid(row=row, column=1, sticky="ew", padx=(0, 15), pady=6)
        worker_frame.grid_columnconfigure(0, weight=1)

        cpu = os.cpu_count() or 4
        default_workers = max(1, cpu - 1)
        self.workers_var = ctk.IntVar(value=default_workers)

        self.workers_slider = ctk.CTkSlider(
            worker_frame, from_=1, to=cpu,
            number_of_steps=max(1, cpu - 1),
            variable=self.workers_var,
            command=self._on_workers_changed,
        )
        self.workers_slider.grid(row=0, column=0, sticky="ew", padx=(0, 10))

        self.workers_label = ctk.CTkLabel(
            worker_frame, text=f"{default_workers} / {cpu}",
            width=60, anchor="e",
        )
        self.workers_label.grid(row=0, column=1)

        row += 1

        # Difficulty estimate
        self.difficulty_label = ctk.CTkLabel(
            frame, text="Enter a hex pattern above to begin",
            font=ctk.CTkFont(size=12, slant="italic"),
        )
        self.difficulty_label.grid(
            row=row, column=0, columnspan=2, sticky="ew", padx=15, pady=(3, 10)
        )

    def _build_controls(self):
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid(row=2, column=0, sticky="ew", padx=15, pady=5)

        # Center the buttons
        inner = ctk.CTkFrame(frame, fg_color="transparent")
        inner.pack()

        self.start_btn = ctk.CTkButton(
            inner, text="Start Search", command=self._start_search,
            width=160, height=40,
            font=ctk.CTkFont(size=15, weight="bold"),
        )
        self.start_btn.pack(side="left", padx=(0, 10))
        self._fix_button_click(self.start_btn, self._start_search)

        self.stop_btn = ctk.CTkButton(
            inner, text="Stop", command=self._stop_search,
            width=100, height=40, state="disabled",
            fg_color="#555555", hover_color="#666666",
        )
        self.stop_btn.pack(side="left")
        self._fix_button_click(self.stop_btn, self._stop_search)

    def _build_progress(self):
        frame = ctk.CTkFrame(self)
        frame.grid(row=3, column=0, sticky="new", padx=15, pady=5)
        frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            frame, text="Progress",
            font=ctk.CTkFont(size=13, weight="bold"), anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=15, pady=(8, 2))

        self.progress_bar = ctk.CTkProgressBar(frame, mode="indeterminate")
        self.progress_bar.grid(row=1, column=0, sticky="ew", padx=15, pady=4)
        self.progress_bar.set(0)

        self.stats_label = ctk.CTkLabel(
            frame, text="Idle",
            font=ctk.CTkFont(family="Courier", size=12), anchor="w",
        )
        self.stats_label.grid(row=2, column=0, sticky="ew", padx=15, pady=(0, 8))

    def _build_results(self):
        frame = ctk.CTkFrame(self)
        frame.grid(row=4, column=0, sticky="nsew", padx=15, pady=(5, 15))
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(4, weight=1)

        ctk.CTkLabel(
            frame, text="Results",
            font=ctk.CTkFont(size=13, weight="bold"), anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=15, pady=(8, 2))

        self.results_text = ctk.CTkTextbox(
            frame, font=ctk.CTkFont(family="Courier", size=12),
            wrap="word",
        )
        self.results_text.grid(row=1, column=0, sticky="nsew", padx=15, pady=4)
        self.results_text.configure(state="disabled")

        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.grid(row=2, column=0, sticky="ew", padx=15, pady=(2, 10))

        self.save_btn = ctk.CTkButton(
            btn_frame, text="Save .identity", command=self._save_identity,
            state="disabled", width=130,
        )
        self.save_btn.pack(side="left", padx=(0, 8))
        self._fix_button_click(self.save_btn, self._save_identity)

        self.copy_btn = ctk.CTkButton(
            btn_frame, text="Copy Address", command=self._copy_address,
            state="disabled", width=130,
        )
        self.copy_btn.pack(side="left", padx=(0, 8))
        self._fix_button_click(self.copy_btn, self._copy_address)

        self.verify_btn = ctk.CTkButton(
            btn_frame, text="Verify with RNS", command=self._verify_result,
            state="disabled", width=130,
        )
        self.verify_btn.pack(side="left")
        self._fix_button_click(self.verify_btn, self._verify_result)

    # ── Callbacks ────────────────────────────────────────────────────

    def _on_dest_changed(self, value):
        if value == "Custom...":
            self.custom_dest_entry.pack(side="left", padx=(10, 0))
        else:
            self.custom_dest_entry.pack_forget()
        self._update_difficulty()

    def _on_workers_changed(self, value):
        cpu = os.cpu_count() or 4
        self.workers_label.configure(text=f"{int(value)} / {cpu}")

    def _update_difficulty(self):
        pattern = self.pattern_var.get().strip()
        if not pattern:
            self.difficulty_label.configure(text="Enter a hex pattern above to begin")
            return

        mode_str = self.mode_var.get()
        mode = MatchMode(mode_str)

        try:
            if mode != MatchMode.REGEX:
                cleaned = validate_hex_pattern(pattern)
            else:
                cleaned = pattern
            mp = MatchPattern(mode=mode, pattern=cleaned)
            diff = estimate_difficulty(mp)
            if diff["expected_attempts"]:
                self.difficulty_label.configure(
                    text=f"Difficulty: ~{diff['expected_attempts']:,} expected attempts"
                )
            else:
                self.difficulty_label.configure(
                    text="Difficulty: Unknown (regex pattern)"
                )
        except ValueError as e:
            self.difficulty_label.configure(text=str(e))

    # ── Input locking ────────────────────────────────────────────────

    def _lock_inputs(self):
        """Disable all settings inputs during an active search."""
        self.pattern_entry.configure(state="disabled")
        self.dest_menu.configure(state="disabled")
        self.workers_slider.configure(state="disabled")
        for rb in self._radio_buttons:
            rb.configure(state="disabled")

    def _unlock_inputs(self):
        """Re-enable all settings inputs after a search ends."""
        self.pattern_entry.configure(state="normal")
        self.dest_menu.configure(state="normal")
        self.workers_slider.configure(state="normal")
        for rb in self._radio_buttons:
            rb.configure(state="normal")

    # ── Search Control ───────────────────────────────────────────────

    def _start_search(self):
        pattern = self.pattern_var.get().strip()
        if not pattern:
            self._append_result("Please enter a pattern.\n")
            return

        mode = MatchMode(self.mode_var.get())
        dest = self.dest_var.get()
        if dest == "Custom...":
            dest = self.custom_dest_entry.get().strip()
            if not dest or "." not in dest:
                self._append_result("Custom destination must be in format 'app.aspect'\n")
                return

        try:
            self.generator = VanityGenerator(
                pattern=pattern,
                mode=mode,
                dest_type=dest,
                num_workers=int(self.workers_var.get()),
            )
        except ValueError as e:
            self._append_result(f"Error: {e}\n")
            return

        # Lock UI
        self._lock_inputs()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal", fg_color="#c0392b", hover_color="#e74c3c")
        self.save_btn.configure(state="disabled")
        self.copy_btn.configure(state="disabled")
        self.verify_btn.configure(state="disabled")
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()
        self.current_results = []
        self.current_export = None
        self._clear_results()

        diff = self.generator.get_difficulty()
        if diff["expected_attempts"]:
            self._append_result(
                f"Searching for {mode.value}='{self.generator.pattern_str}' "
                f"(~{diff['expected_attempts']:,} expected attempts)\n"
                f"Using {self.generator.num_workers} worker processes...\n\n"
            )
        else:
            self._append_result(
                f"Searching for {mode.value}='{self.generator.pattern_str}'\n"
                f"Using {self.generator.num_workers} worker processes...\n\n"
            )

        self.generator.start()
        self._poll()

    def _poll(self):
        if self.generator is None:
            return

        stats = self.generator.poll()

        elapsed_str = self._format_time(stats.elapsed)
        rate_str = self._format_rate(stats.rate)
        self.stats_label.configure(
            text=f"Checked: {stats.total_checked:,}  |  "
                 f"Rate: {rate_str}/sec  |  "
                 f"Elapsed: {elapsed_str}"
        )

        if stats.results_found > len(self.current_results):
            new_results = self.generator.results[len(self.current_results):]
            for result in new_results:
                self.current_results.append(result)
                export = prepare_export(
                    result.private_key, result.identity_hash,
                    result.dest_type, result.dest_hash_hex,
                )
                self.current_export = export
                self._display_result(result, export)

        if stats.is_running:
            self.after(POLL_MS, self._poll)
        else:
            self._search_finished()

    def _stop_search(self):
        if self.generator:
            self.generator.stop()
        self._search_finished()

    def _search_finished(self):
        self.progress_bar.stop()
        self.progress_bar.configure(mode="determinate")
        self.progress_bar.set(1.0 if self.current_results else 0)
        # Unlock UI
        self._unlock_inputs()
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled", fg_color="#555555", hover_color="#666666")
        if self.current_results:
            self.save_btn.configure(state="normal")
            self.copy_btn.configure(state="normal")
            self.verify_btn.configure(state="normal")
            self._append_result("\nSearch complete.\n")
        else:
            self._append_result("\nSearch stopped (no match found).\n")

    # ── Display Helpers ──────────────────────────────────────────────

    def _clear_results(self):
        self.results_text.configure(state="normal")
        self.results_text.delete("1.0", "end")
        self.results_text.configure(state="disabled")

    def _append_result(self, text: str):
        self.results_text.configure(state="normal")
        self.results_text.insert("end", text)
        self.results_text.configure(state="disabled")
        self.results_text.see("end")

    def _display_result(self, result: GeneratorResult, export: ExportedIdentity):
        lines = [
            "=" * 52,
            "  MATCH FOUND",
            f"  LXMF Address:   {export.dest_hashes.get('lxmf.delivery', result.dest_hash_hex)}",
        ]
        if "nomadnetwork.node" in export.dest_hashes:
            lines.append(f"  NomadNet Node:  {export.dest_hashes['nomadnetwork.node']}")
        lines.extend([
            f"  Identity Hash:  {export.identity_hash_hex}",
            f"  Time:  {self._format_time(result.elapsed)}  |  "
            f"Checked: {result.total_checked:,}  |  "
            f"Rate: {self._format_rate(result.rate)}/sec",
            "=" * 52,
            "",
        ])
        self._append_result("\n".join(lines))

    @staticmethod
    def _format_time(seconds: float) -> str:
        if seconds < 1:
            return f"{seconds * 1000:.0f}ms"
        elif seconds < 60:
            return f"{seconds:.1f}s"
        elif seconds < 3600:
            return f"{seconds / 60:.1f}m"
        elif seconds < 86400:
            return f"{seconds / 3600:.1f}h"
        else:
            return f"{seconds / 86400:.1f}d"

    @staticmethod
    def _format_rate(rate: float) -> str:
        if rate < 1000:
            return f"{rate:.0f}"
        elif rate < 1_000_000:
            return f"{rate / 1000:.1f}K"
        else:
            return f"{rate / 1_000_000:.2f}M"

    # ── Action Buttons ───────────────────────────────────────────────

    def _save_identity(self):
        if not self.current_results:
            return
        from tkinter import filedialog
        result = self.current_results[-1]
        path = filedialog.asksaveasfilename(
            defaultextension=".identity",
            initialfile=f"{result.dest_hash_hex}.identity",
            filetypes=[
                ("Identity files", "*.identity"),
                ("All files", "*.*"),
            ],
        )
        if path:
            save_identity_file(result.private_key, path)
            export = self.current_export or prepare_export(
                result.private_key, result.identity_hash,
                result.dest_type, result.dest_hash_hex,
            )
            txt_path = path.rsplit(".", 1)[0] + ".txt"
            save_identity_text(export, txt_path)
            self._append_result(f"\nSaved: {path}\nInfo:  {txt_path}\n")

    def _copy_address(self):
        if not self.current_results:
            return
        result = self.current_results[-1]
        self.clipboard_clear()
        self.clipboard_append(result.dest_hash_hex)
        self._append_result("Address copied to clipboard.\n")

    def _verify_result(self):
        if not self.current_results:
            return
        result = self.current_results[-1]
        export = self.current_export or prepare_export(
            result.private_key, result.identity_hash,
            result.dest_type, result.dest_hash_hex,
        )
        v = verify_with_rns(
            result.private_key,
            export.identity_hash_hex,
            result.dest_hash_hex,
            dest_name=result.dest_type,
        )
        if v["rns_available"]:
            id_ok = "PASS" if v["identity_hash_match"] else "FAIL"
            dest_ok = "PASS" if v["dest_hash_match"] else "FAIL"
            self._append_result(
                f"\nRNS Verification:\n"
                f"  Identity hash: {id_ok}\n"
                f"  Dest hash:     {dest_ok}\n"
            )
        else:
            self._append_result(f"\nRNS not available: {v['error']}\n")


def run_gui() -> int:
    if not HAS_CTK:
        print(
            "CustomTkinter is required for the GUI.\n"
            "Install with: pip install customtkinter\n"
            "\nFalling back to CLI mode. Run with --help for usage.",
            file=sys.stderr,
        )
        return 1

    app = ReVanityApp()
    app.mainloop()
    return 0
