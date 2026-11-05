"""
Dynamic Build Workspace & Progress Engine.
Handles dynamic focus stage visibility, named semantic labels (SCAN, COMPILE, LINK, PATCH, SIGN, PACKAGE),
thread-safe warning feeds, independent monotonic timers, and inline failure diagnostics.
"""

import os
import sys
import time
import threading
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any

from nyxwin.tui.theme import (
    fg, bold, dim, strip_ansi, visible_length, pad_visible, symbol, truncate_visible
)
from nyxwin.tui.terminal import (
    get_terminal_width, move_cursor_up, clear_line, hide_cursor, restore_cursor, transition_screen
)
from nyxwin.tui.components.frame import render_panel
from nyxwin.tui.components.status import render_progress_bar, render_summary_card

# 10-frame Braille spinner
SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

STAGE_NAMES = {
    1: "SCAN",
    2: "COMPILE",
    3: "LINK",
    4: "PATCH",
    5: "SIGN",
    6: "PACKAGE",
}

class WarningItem:
    """Thread-safe representation of a compiler/tool diagnostic warning."""
    def __init__(self, raw_text: str, default_tool: str = "Compiler"):
        self.raw_text = str(raw_text).strip()
        self.file_loc = ""
        self.file = ""
        self.line: Optional[int] = None
        self.col: Optional[int] = None
        self.severity = "Warning"
        self.tool = "Compiler" if default_tool in (None, "", "none") else default_tool
        self.message = self.raw_text
        self.snippet = ""
        self.caret = ""
        self.notes: List[Dict[str, str]] = []
        self.fixits: List[str] = []
        self.all_lines = [l.rstrip() for l in self.raw_text.splitlines()]
        self._parse()

    def _parse(self):
        import re
        lines = self.all_lines
        if not lines:
            return

        warn_re = re.compile(r"^((?:[a-zA-Z]:)?[^:]+):(\d+):(\d+):\s*warning:\s*(.*)$", re.IGNORECASE)
        note_re = re.compile(r"^((?:[a-zA-Z]:)?[^:]+):(\d+):(\d+):\s*note:\s*(.*)$", re.IGNORECASE)

        main_warn_idx = -1
        for idx, line in enumerate(lines):
            m = warn_re.match(line.strip())
            if m:
                main_warn_idx = idx
                file_raw = m.group(1).strip()
                file_name = os.path.basename(file_raw) or file_raw
                self.file = file_name
                try:
                    self.line = int(m.group(2).strip())
                    self.col = int(m.group(3).strip())
                except ValueError:
                    pass
                self.file_loc = f"{file_name}:{m.group(2).strip()}:{m.group(3).strip()}"
                self.message = m.group(4).strip()
                if file_name.endswith(".swift"):
                    self.tool = "swiftc"
                elif file_name.endswith((".c", ".m", ".cpp", ".mm", ".h")):
                    self.tool = "clang"
                break
            elif "warning:" in line.lower():
                main_warn_idx = idx
                self.message = line.split("warning:", 1)[1].strip()
                prefix = line[:line.lower().index("warning:")].strip().rstrip(":")
                if "clang++" in prefix.lower():
                    self.tool = "clang++"
                elif "clang" in prefix.lower():
                    self.tool = "clang"
                elif "swift" in prefix.lower():
                    self.tool = "swiftc"
                elif "ld64" in prefix.lower() or "lld" in prefix.lower():
                    self.tool = "ld64.lld"
                break

        if self.tool in (None, "", "none"):
            self.tool = "Compiler"

        if main_warn_idx != -1:
            i = main_warn_idx + 1
            while i < len(lines):
                line_str = lines[i]
                if not line_str.strip():
                    i += 1
                    continue
                if "note:" in line_str.lower() or "warning:" in line_str.lower():
                    break
                if ("^" in line_str or "~" in line_str) and not self.caret:
                    self.caret = line_str
                elif not self.snippet:
                    self.snippet = line_str.strip()
                i += 1

        for idx, line in enumerate(lines):
            line_str = line.strip()
            nm = note_re.match(line_str)
            if nm:
                note_file = os.path.basename(nm.group(1).strip()) or nm.group(1).strip()
                note_loc = f"{note_file}:{nm.group(2).strip()}:{nm.group(3).strip()}"
                note_msg = nm.group(4).strip()
                self.notes.append({"file_loc": note_loc, "message": note_msg})
            elif "note:" in line_str.lower():
                self.notes.append({"file_loc": "", "message": line_str.split("note:", 1)[1].strip()})
            elif "fix-it:" in line_str.lower():
                self.fixits.append(line_str.split("fix-it:", 1)[1].strip())

    def __str__(self) -> str:
        return self.raw_text

    def __contains__(self, item: str) -> bool:
        return item in self.raw_text

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, str):
            return self.raw_text == other or self.message == other
        return super().__eq__(other)

def parse_warning_items(raw_text: str, default_tool: str = "Compiler") -> List[WarningItem]:
    """
    Splits multiple compiler warnings within a diagnostic block into distinct WarningItems,
    preserving associated snippets, carets, and notes with each warning.
    """
    if not raw_text or not raw_text.strip():
        return []

    lines = raw_text.splitlines()
    import re
    warn_hdr_re = re.compile(r"^((?:[a-zA-Z]:)?[^:]+:\d+:\d+:\s*warning:|(?:[a-zA-Z0-9_\.\-]+:\s*)?warning:|\bwarning:)", re.IGNORECASE)
    err_hdr_re = re.compile(r"^((?:[a-zA-Z]:)?[^:]+:\d+:\d+:\s*(?:fatal\s+)?error:|(?:[a-zA-Z0-9_\.\-]+:\s*)?(?:fatal\s+)?error:)", re.IGNORECASE)

    warning_chunks: List[List[str]] = []
    current_chunk: List[str] = []

    for line in lines:
        l_str = line.strip()
        if warn_hdr_re.search(l_str):
            if current_chunk:
                warning_chunks.append(current_chunk)
            current_chunk = [line]
        elif err_hdr_re.search(l_str):
            if current_chunk:
                warning_chunks.append(current_chunk)
                current_chunk = []
        else:
            if current_chunk:
                current_chunk.append(line)

    if current_chunk:
        warning_chunks.append(current_chunk)

    effective_tool = "Compiler" if default_tool in (None, "", "none") else default_tool
    items: List[WarningItem] = []
    for chunk in warning_chunks:
        chunk_text = "\n".join(chunk).strip()
        if chunk_text:
            items.append(WarningItem(chunk_text, default_tool=effective_tool))
    return items

class StageInfo:
    def __init__(self, index: int, label: str, name: str):
        self.index = index
        self.label = label  # "SCAN", "COMPILE", "LINK", "PATCH", "SIGN", "PACKAGE"
        self.name = name
        self.status = "pending"  # "pending", "in_progress", "completed", "failed"
        self.detail = ""
        self.started_at: float = 0.0
        self.completed_at: float = 0.0

class BuildProgressTracker:
    """Thread-safe state container for build stages, timers, and compilation events."""
    def __init__(
        self,
        project_name: str,
        target_triple: str,
        profile: str = "auto",
        project_dir: Optional[Path] = None
    ):
        self.project_name = project_name
        self.target_triple = target_triple
        self.profile = profile
        self.project_dir = Path(project_dir).resolve() if project_dir else None
        self.ipa_path: Optional[Path] = None
        self.build_started_at = time.monotonic()
        self.stage_started_at = time.monotonic()
        self.start_time = self.build_started_at  # for backward compatibility
        self.lock = threading.RLock()

        self.stages = [
            StageInfo(1, "SCAN", "Discover Source Files"),
            StageInfo(2, "COMPILE", "Compile Sources"),
            StageInfo(3, "LINK", "Link Mach-O Executable"),
            StageInfo(4, "PATCH", "Apply Header Patch #31"),
            StageInfo(5, "SIGN", "Inject Entitlements & Codesign"),
            StageInfo(6, "PACKAGE", "Package Application Bundle & .ipa")
        ]
        self.active_stage_idx = 0
        self.spinner_frame = 0

        # Sub-stage compilation telemetry
        self.compilation_mode = "none"  # "swift", "c", "both"
        self.c_total = 0
        self.c_completed = 0
        self.c_cached = 0
        self.c_current_file = ""

        self.swift_files_count = 0
        self.swift_module_name = ""
        self.swift_elapsed = 0.0

        # Warnings and errors
        self.warnings: List[WarningItem] = []
        self.errors: List[str] = []
        self.failure_diagnostic: Optional[Dict[str, Any]] = None

        # Observability & Persistent Transcript
        self.transcript: Optional[Any] = None
        self.log_path: Optional[Path] = None
        self.recent_operations: List[str] = []

    def record_operation(self, op_desc: str = "", *args, **kwargs):
        """Records an active operation line for the live TUI workspace display and BuildTranscript."""
        line = ""
        if "tool" in kwargs and kwargs["tool"] in ("clang", "swiftc"):
            tool = kwargs["tool"]
            inp = kwargs.get("input_file", "")
            out = kwargs.get("output_file", "")
            el = kwargs.get("elapsed", 0.0)
            cached = kwargs.get("cached", False)
            if cached:
                line = f"{tool} {inp} (cached)"
            else:
                line = f"{tool} {inp} -> {out} [{el:.2f}s]"
            if self.transcript:
                self.transcript.record_compile(**kwargs)
        elif "tool" in kwargs and kwargs["tool"] in ("ld64.lld", "lld"):
            el = kwargs.get("elapsed", 0.0)
            out_bin = Path(kwargs.get("output_binary", "")).name
            line = f"ld64.lld -> {out_bin} [{el:.2f}s]"
            if self.transcript:
                self.transcript.record_link(**kwargs)
        elif "tool" in kwargs and kwargs["tool"] == "ldid":
            el = kwargs.get("elapsed", 0.0)
            in_bin = Path(kwargs.get("input_binary", "")).name
            line = f"ldid -> {in_bin} [{el:.2f}s]"
            self.signing_info = dict(kwargs)
            if self.transcript:
                self.transcript.record_sign(**kwargs)
        elif "operation" in kwargs and "ipa_path" in kwargs:
            el = kwargs.get("elapsed", 0.0)
            ipa = Path(kwargs.get("ipa_path", "")).name
            line = f"packager -> {ipa} [{el:.2f}s]"
            if self.transcript:
                self.transcript.record_package(**kwargs)
        elif op_desc:
            line = op_desc
        elif kwargs:
            line = str(kwargs)

        if line:
            with self.lock:
                self.recent_operations.append(line)
                if len(self.recent_operations) > 6:
                    self.recent_operations.pop(0)

    def start_stage(self, stage_idx: int, detail: str = ""):
        with self.lock:
            now = time.monotonic()
            self.active_stage_idx = stage_idx
            self.stage_started_at = now
            for s in self.stages:
                if s.index < stage_idx:
                    if s.status != "failed":
                        s.status = "completed"
                elif s.index == stage_idx:
                    s.status = "in_progress"
                    s.started_at = now
                    if detail:
                        s.detail = detail
                else:
                    s.status = "pending"

    def complete_stage(self, stage_idx: int, summary: str = ""):
        with self.lock:
            now = time.monotonic()
            for s in self.stages:
                if s.index == stage_idx:
                    s.status = "completed"
                    s.completed_at = now
                    if summary:
                        s.detail = summary

    def fail_stage(self, stage_idx: int, error_msg: str = "", diagnostic_info: Optional[Dict[str, Any]] = None):
        with self.lock:
            self.active_stage_idx = stage_idx
            for s in self.stages:
                if s.index == stage_idx:
                    s.status = "failed"
                    if error_msg:
                        s.detail = error_msg
            if diagnostic_info:
                self.failure_diagnostic = diagnostic_info

    def get_build_elapsed(self) -> float:
        return max(0.0, time.monotonic() - self.build_started_at)

    def get_stage_elapsed(self) -> float:
        return max(0.0, time.monotonic() - self.stage_started_at)

    def format_build_elapsed(self) -> str:
        elapsed = self.get_build_elapsed()
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)
        return f"{mins:02d}:{secs:02d}"

    def format_stage_elapsed(self) -> str:
        elapsed = self.get_stage_elapsed()
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)
        return f"{mins:02d}:{secs:02d}"

    def format_elapsed(self) -> str:
        """Backward compatibility helper matching existing tests."""
        return self.format_build_elapsed()

    def update_c_progress(self, completed: int, total: int, cached: int = 0, current: str = ""):
        with self.lock:
            self.compilation_mode = "c"
            self.c_completed = completed
            self.c_total = total
            self.c_cached = cached
            if current:
                self.c_current_file = current

    def update_swift_progress(self, module_name: str, count: int, elapsed: float = 0.0):
        with self.lock:
            self.compilation_mode = "swift"
            self.swift_module_name = module_name
            self.swift_files_count = count
            self.swift_elapsed = elapsed

    def add_warning(self, warn_text: str):
        with self.lock:
            mode_tool = "clang" if self.compilation_mode == "c" else ("swiftc" if self.compilation_mode == "swift" else "Compiler")
            items = parse_warning_items(warn_text, default_tool=mode_tool)
            if items:
                self.warnings.extend(items)
            else:
                self.warnings.append(WarningItem(warn_text, default_tool=mode_tool))

    def add_error(self, err_text: str):
        with self.lock:
            self.errors.append(str(err_text).strip())

    def tick_spinner(self):
        with self.lock:
            self.spinner_frame = (self.spinner_frame + 1) % len(SPINNER_FRAMES)

class LiveProgressManager:
    """
    Manages the in-place multi-line terminal rendering container.
    Guarantees single ownership of the live build frame, thread-safe rendering,
    integrated warning feed, honest indeterminate progress, and reliable cursor restoration.
    """
    def __init__(self, tracker: BuildProgressTracker, width: Optional[int] = None):
        self.tracker = tracker
        self.width = width or get_terminal_width()
        self.is_interactive = self._check_interactive()
        self.lines_rendered = 0
        self.closed = False
        self._stop_event = threading.Event()
        self._anim_thread: Optional[threading.Thread] = None
        self._render_lock = threading.RLock()

    def _check_interactive(self) -> bool:
        if os.environ.get("NYXWIN_NON_INTERACTIVE") == "1":
            return False
        return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    def start(self):
        """Initializes live rendering or prints initial non-interactive notice."""
        if not self.is_interactive:
            profile_name = self.tracker.profile.capitalize()
            print(f"[NyxWin Build] Target: {self.tracker.project_name} ({self.tracker.target_triple}) Profile: {profile_name}")
            return

        transition_screen()
        hide_cursor()
        self.render()

        # Start animation background thread for 100ms spinner and timer updates
        self._anim_thread = threading.Thread(target=self._animation_loop, daemon=True)
        self._anim_thread.start()

    def _animation_loop(self):
        while not self._stop_event.is_set():
            time.sleep(0.1)
            if self._stop_event.is_set():
                break
            self.tracker.tick_spinner()
            self.render()

    def render(self):
        """Redraws the pinned multi-line live status frame in place with thread safety."""
        with self._render_lock:
            if not self.is_interactive or self.closed:
                return

            w = get_terminal_width()
            self.width = w

            # Dynamic Focus: Completed stages and active stage ONLY
            completed_stages = [s for s in self.tracker.stages if s.status == "completed"]
            active_stage = None
            for s in self.tracker.stages:
                if s.status == "in_progress":
                    active_stage = s
                    break

            active_label = active_stage.label if active_stage else "BUILD"
            build_time_str = self.tracker.format_build_elapsed()

            # Header meta line
            profile_name = self.tracker.profile.upper()
            target_str = self.tracker.target_triple
            meta_left = f"{target_str} · {profile_name}"
            meta_right = f"Build {build_time_str}"
            inner_content_w = max(10, w - 6)
            spacing = max(2, inner_content_w - visible_length(meta_left) - visible_length(meta_right))
            meta_line = f"  {fg('GRAY_MUTED', meta_left)}{' ' * spacing}{fg('CYAN_ELEC', bold(meta_right))}"

            content_lines: List[str] = [
                meta_line,
                f"  {fg('SLATE_GRAY', '─' * max(2, w - 8))}",
                ""
            ]

            # 1. Completed stages section (concise history)
            if completed_stages:
                content_lines.append(f"  {fg('GRAY_MUTED', bold('COMPLETED'))}")
                check_sym = symbol("CHECK")
                for s in completed_stages:
                    icon = fg("EMERALD", check_sym)
                    lbl = fg("GRAY_MUTED", pad_visible(s.label, 8, align="left"))
                    det = s.detail if s.detail else s.name
                    content_lines.append(f"  {icon}  {lbl} {fg('WHITE_SOFT', det)}")
                content_lines.append("")

            # 2. Current operation section (expanded focus)
            if active_stage:
                content_lines.append(f"  {fg('GRAY_MUTED', bold('CURRENT OPERATION'))}")
                bullet_sym = symbol("BULLET_ACTIVE")
                content_lines.append(f"  {fg('CYAN_ELEC', bullet_sym)}  {fg('WHITE_SOFT', bold(active_stage.label))}")

                # Context details
                if active_stage.label == "SCAN":
                    content_lines.append(f"     Scanning source files in {self.tracker.project_name}...")
                elif active_stage.label == "COMPILE":
                    if self.tracker.compilation_mode == "swift":
                        mod = self.tracker.swift_module_name or self.tracker.project_name
                        cnt = self.tracker.swift_files_count
                        content_lines.append(f"     Swift module: {mod}")
                        content_lines.append(f"     Whole-module compilation · {cnt} source files")
                    elif self.tracker.compilation_mode == "c":
                        tot = self.tracker.c_total or 1
                        done = self.tracker.c_completed
                        cached = self.tracker.c_cached
                        cur = self.tracker.c_current_file or "compiling"
                        pct = (done / tot) * 100.0
                        bar = render_progress_bar(pct, bar_width=18)
                        content_lines.append(f"     C/ObjC compilation · {bar}")
                        content_lines.append(f"     {done}/{tot} files ({cached} cached) · {cur}")
                    else:
                        content_lines.append(f"     {active_stage.detail or active_stage.name}")
                elif active_stage.label == "LINK":
                    content_lines.append("     Mach-O executable linking (ld64.lld)")
                elif active_stage.label == "PATCH":
                    content_lines.append("     Applying Header Patch #31 (chained fixups)")
                elif active_stage.label == "SIGN":
                    prof_cap = self.tracker.profile.capitalize()
                    content_lines.append(f"     Injecting Entitlements ({prof_cap}) & ldid")
                elif active_stage.label == "PACKAGE":
                    content_lines.append("     Assembling .app bundle and creating .ipa")
                else:
                    content_lines.append(f"     {active_stage.detail or active_stage.name}")

                if self.tracker.recent_operations:
                    content_lines.append("")
                    for op in self.tracker.recent_operations[-3:]:
                        content_lines.append(f"     {fg('SLATE_GRAY', '›')} {fg('WHITE_SOFT', op)}")

                content_lines.append("")
                # Separate Monotonic Timers
                stg_time = self.tracker.format_stage_elapsed()
                content_lines.append(f"     {fg('GRAY_MUTED', 'Stage elapsed:')} {fg('WHITE_SOFT', stg_time)}")
                content_lines.append(f"     {fg('GRAY_MUTED', 'Build elapsed:')} {fg('WHITE_SOFT', build_time_str)}")
                content_lines.append("")

                # Spinner Activity Line
                action_map = {
                    "SCAN": "Scanning",
                    "COMPILE": "Compiling",
                    "LINK": "Linking",
                    "PATCH": "Patching",
                    "SIGN": "Signing",
                    "PACKAGE": "Packaging"
                }
                verb = action_map.get(active_stage.label, "Processing")
                spinner_sym = SPINNER_FRAMES[self.tracker.spinner_frame]
                content_lines.append(f"     {fg('CYAN_ELEC', spinner_sym)} {verb}...")
                content_lines.append("")

            # 3. Warning feed section (RECENT DIAGNOSTICS)
            if self.tracker.warnings:
                content_lines.append(f"  {fg('GRAY_MUTED', bold('RECENT DIAGNOSTICS'))}")
                warn_sym = symbol("WARN")
                max_warn = 3 if w >= 100 else 2
                recent = self.tracker.warnings[-max_warn:]
                for w_item in recent:
                    if w_item.file_loc:
                        content_lines.append(f"  {fg('AMBER', warn_sym)}  {fg('WHITE_SOFT', w_item.file_loc)}")
                        content_lines.append(f"     {fg('GRAY_MUTED', w_item.message)}")
                    else:
                        content_lines.append(f"  {fg('AMBER', warn_sym)}  {fg('GRAY_MUTED', w_item.message)}")
                total_w = len(self.tracker.warnings)
                if total_w > len(recent):
                    content_lines.append(f"     {fg('DARK_GRAY', f'({total_w - len(recent)} earlier warning(s) hidden)')}")
                content_lines.append("")

            panel_output = render_panel(
                title=f"BUILDING {self.tracker.project_name.upper()}",
                content_lines=content_lines,
                badge=active_label,
                width=w,
                border_color="SLATE_GRAY",
                title_color="CYAN_ELEC",
                badge_color="VIOLET"
            )
            footer = f"  [{fg('WHITE_SOFT', 'Ctrl+C')}] {fg('GRAY_MUTED', 'Abort Build')}"
            full_text = f"{panel_output}\n{footer}\n"
            new_lines_count = len(full_text.splitlines())

            # In-place line rewriting
            if self.lines_rendered > 0:
                move_cursor_up(self.lines_rendered)

            sys.stdout.write(full_text)
            sys.stdout.flush()
            self.lines_rendered = new_lines_count

    def close(self):
        """Stops live animation and restores cursor visibility."""
        with self._render_lock:
            if not self.closed:
                self._stop_event.set()
                if self._anim_thread and self._anim_thread.is_alive():
                    self._anim_thread.join(timeout=0.3)
                self.closed = True
                restore_cursor()

    def print_warning(self, warning_text: str):
        """Preserves and emits a compiler warning cleanly inside the live diagnostic feed."""
        with self._render_lock:
            self.tracker.add_warning(warning_text)
            if not self.is_interactive:
                print(f"[WARNING] {warning_text.strip()}")
            else:
                self.render()

    def finish_success(self, ipa_path: Path, size_bytes: int, artifact_label: str = "Output IPA"):
        """Collapses live frame into a permanent build success summary card."""
        self.close()
        if getattr(self.tracker, "transcript", None) and not getattr(self.tracker.transcript, "log_path", None):
            try:
                self.tracker.log_path = self.tracker.transcript.finalize(is_success=True)
            except Exception:
                pass
        bld_elapsed = self.tracker.format_build_elapsed()

        # Clean transition: clear visible viewport without erasing scrollback
        if self.is_interactive:
            transition_screen()
            self.lines_rendered = 0

        has_warnings = len(self.tracker.warnings) > 0
        title = "BUILD SUCCEEDED WITH WARNINGS" if has_warnings else "BUILD SUCCEEDED"
        badge = f"{self.tracker.project_name} · {bld_elapsed}"

        abs_ipa = Path(ipa_path).resolve()
        self.tracker.ipa_path = abs_ipa

        # Project-relative primary display path
        display_ipa = str(abs_ipa)
        if self.tracker.project_dir:
            try:
                rel = abs_ipa.relative_to(Path(self.tracker.project_dir).resolve())
                display_ipa = str(rel)
            except ValueError:
                display_ipa = str(abs_ipa)
        else:
            try:
                rel = abs_ipa.relative_to(Path.cwd().resolve())
                display_ipa = str(rel)
            except ValueError:
                display_ipa = abs_ipa.name

        if size_bytes >= 1024 * 1024:
            size_str = f"{size_bytes / (1024.0 * 1024.0):.2f} MB"
        else:
            size_str = f"{size_bytes / 1024.0:.1f} KB"

        prof_raw = self.tracker.profile.lower()
        prof_desc = "TrollStore (Legacy Preset)" if prof_raw == "trollstore" else ("Sandboxed (Legacy Preset)" if prof_raw == "sandboxed" else "Project Configuration")

        signing_method_str = "ldid (Ad-Hoc)"
        ent_file_str = "Config/Entitlements.plist"
        if getattr(self.tracker, "signing_info", None):
            sig_info = self.tracker.signing_info
            signing_method_str = sig_info.get("signing_method") or sig_info.get("mode") or "ldid (Ad-Hoc)"
            ent_p = sig_info.get("entitlements_file")
            if ent_p:
                try:
                    if self.tracker.project_dir:
                        ent_file_str = str(Path(ent_p).relative_to(self.tracker.project_dir))
                    else:
                        ent_file_str = Path(ent_p).name
                except Exception:
                    ent_file_str = Path(ent_p).name
            keys_cnt = len(sig_info.get("entitlements_keys", []))
            if keys_cnt > 0:
                ent_file_str += f" ({keys_cnt} key{'s' if keys_cnt != 1 else ''})"

        details = [
            ("Target", f"{self.tracker.project_name} ({self.tracker.target_triple})"),
            ("Entitlements", f"{ent_file_str} [{prof_desc}]"),
            ("Signing", "ldid (Ad-Hoc / Pseudo-Signing)"),
            ("Provisioning", "None"),
            ("Distribution", "No Apple signing authorization"),
            (artifact_label, f"{display_ipa} ({size_str})"),
            ("Duration", f"Total build time: {bld_elapsed}"),
            ("Pipeline", "SCAN, COMPILE, LINK, PATCH, SIGN, PACKAGE (Completed)")
        ]
        log_p = getattr(self.tracker, "log_path", None)
        if log_p and Path(log_p).is_file():
            details.append(("Build Log", str(log_p)))
        if has_warnings:
            details.append(("Warnings", f"{len(self.tracker.warnings)} warning(s) produced during compilation"))

        card = render_summary_card(
            title=title,
            details=details,
            is_success=True,
            badge=badge,
            width=self.width
        )
        print(card)

    def finish_failure(
        self,
        stage_idx: int,
        error_msg: str,
        tool: Optional[str] = None,
        exit_code: int = 1,
        diagnostic_text: Optional[str] = None
    ):
        """Collapses live frame and shows the inline diagnostic card beneath the failed stage."""
        self.close()
        if getattr(self.tracker, "transcript", None) and not getattr(self.tracker.transcript, "log_path", None):
            try:
                self.tracker.log_path = self.tracker.transcript.finalize(
                    is_success=False,
                    failure_stage=stage_idx,
                    failure_reason=error_msg
                )
            except Exception:
                pass

        from nyxwin.core.diagnostics import parse_diagnostic_details
        diag_source = diagnostic_text or ("\n".join(self.tracker.errors) if self.tracker.errors else error_msg)
        default_tool_name = tool or STAGE_NAMES.get(stage_idx, "Toolchain")
        diag = parse_diagnostic_details(diag_source, default_tool=default_tool_name)

        self.tracker.fail_stage(stage_idx, error_msg, diagnostic_info=diag)

        # Clean transition: clear visible viewport without erasing scrollback
        if self.is_interactive:
            transition_screen()
            self.lines_rendered = 0

        failed_stage_label = STAGE_NAMES.get(stage_idx, "BUILD")
        failed_stage_name = self.tracker.stages[stage_idx - 1].name if 1 <= stage_idx <= len(self.tracker.stages) else "Unknown Stage"

        w = get_terminal_width()
        content_lines: List[str] = [""]

        # 1. Completed stages history
        completed_stages = [s for s in self.tracker.stages if s.status == "completed"]
        if completed_stages:
            content_lines.append(f"  {fg('GRAY_MUTED', bold('COMPLETED'))}")
            check_sym = symbol("CHECK")
            for s in completed_stages:
                icon = fg("EMERALD", check_sym)
                lbl = fg("GRAY_MUTED", pad_visible(s.label, 8, align="left"))
                det = s.detail if s.detail else s.name
                content_lines.append(f"  {icon}  {lbl} {fg('WHITE_SOFT', det)}")
            content_lines.append("")

        # 2. Failed stage
        content_lines.append(f"  {fg('CORAL_RED', bold('FAILED'))}")
        fail_sym = symbol("FAIL")
        content_lines.append(f"  {fg('CORAL_RED', fail_sym)}  {fg('CORAL_RED', bold(failed_stage_label))}")
        content_lines.append("")

        # 3. Inline Diagnostic Card
        diag_box_w = max(20, w - 8)
        diag_tool = (diag.get("tool") or default_tool_name).upper()
        diag_category = diag.get("category", f"{diag_tool} DIAGNOSTIC")

        diag_card_lines = []
        diag_card_lines.append(f"  {fg('CORAL_RED', '┌─ ' + diag_category + ' ' + '─' * max(2, diag_box_w - visible_length(diag_category) - 5) + '┐')}")
        diag_card_lines.append(f"  {fg('CORAL_RED', '│')} {' ' * (diag_box_w - 2)} {fg('CORAL_RED', '│')}")

        msg = diag.get("message") or error_msg
        diag_card_lines.append(f"  {fg('CORAL_RED', '│')}  {fg('WHITE_SOFT', bold(msg))}")
        diag_card_lines.append(f"  {fg('CORAL_RED', '│')} {' ' * (diag_box_w - 2)} {fg('CORAL_RED', '│')}")

        diag_card_lines.append(f"  {fg('CORAL_RED', '│')}  {fg('GRAY_MUTED', pad_visible('Tool:', 12))} {fg('WHITE_SOFT', diag.get('tool') or default_tool_name)}")
        diag_card_lines.append(f"  {fg('CORAL_RED', '│')}  {fg('GRAY_MUTED', pad_visible('Exit code:', 12))} {fg('WHITE_SOFT', str(exit_code))}")
        log_p = getattr(self.tracker, "log_path", None)
        if log_p and Path(log_p).is_file():
            diag_card_lines.append(f"  {fg('CORAL_RED', '│')}  {fg('GRAY_MUTED', pad_visible('Build Log:', 12))} {fg('WHITE_SOFT', str(log_p))}")

        if diag.get("file"):
            loc_str = f"{diag['file']}"
            if diag.get("line"):
                loc_str += f":{diag['line']}"
                if diag.get("col"):
                    loc_str += f":{diag['col']}"
            diag_card_lines.append(f"  {fg('CORAL_RED', '│')}  {fg('GRAY_MUTED', pad_visible('Location:', 12))} {fg('CYAN_ELEC', loc_str)}")

        if diag.get("snippet"):
            diag_card_lines.append(f"  {fg('CORAL_RED', '│')} {' ' * (diag_box_w - 2)} {fg('CORAL_RED', '│')}")
            diag_card_lines.append(f"  {fg('CORAL_RED', '│')}    {fg('WHITE_SOFT', diag['snippet'])}")
            if diag.get("caret"):
                diag_card_lines.append(f"  {fg('CORAL_RED', '│')}    {fg('CORAL_RED', diag['caret'])}")

        diag_card_lines.append(f"  {fg('CORAL_RED', '│')} {' ' * (diag_box_w - 2)} {fg('CORAL_RED', '│')}")
        diag_card_lines.append(f"  {fg('CORAL_RED', '└' + '─' * (diag_box_w) + '┘')}")

        content_lines.extend(diag_card_lines)
        content_lines.append("")
        content_lines.append(f"  {fg('GRAY_MUTED', f'Build terminated during {failed_stage_name.lower()}.')}")
        content_lines.append("")

        panel = render_panel(
            title="BUILD FAILED",
            content_lines=content_lines,
            badge=failed_stage_label,
            width=w,
            border_color="CORAL_RED",
            title_color="CORAL_RED",
            badge_color="CORAL_RED"
        )
        print(panel)
