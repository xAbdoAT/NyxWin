"""
Build Diagnostics Viewer Screen.
Allows developers to inspect, paginate, copy, and save all compiler warnings
and failure diagnostics with complete notes, snippets, and caret information.
"""

import os
import sys
from pathlib import Path
from typing import Optional, List, Any

from nyxwin.core.models import Color
from nyxwin.core.diagnostics import save_diagnostics_report, generate_diagnostics_report_text
from nyxwin.tui.theme import fg, bold, dim, symbol, pad_visible, visible_length
from nyxwin.tui.terminal import transition_screen, copy_to_clipboard, read_key, get_terminal_width
from nyxwin.tui.components.frame import render_panel

def screen_build_diagnostics_viewer(
    tracker: Any,
    project_dir: Optional[Path] = None,
    is_success: bool = True
):
    """
    Dedicated interactive diagnostics screen displaying all compiler warnings or failure details.
    Provides copying current/all warnings and saving full diagnostics reports.
    """
    if tracker is None:
        return

    warnings: List[Any] = getattr(tracker, "warnings", [])
    failure_diag = getattr(tracker, "failure_diagnostic", None)
    errors: List[str] = getattr(tracker, "errors", [])
    proj_name = getattr(tracker, "project_name", "Project")
    target_triple = getattr(tracker, "target_triple", "arm64-apple-ios")

    # Non-interactive fallback: dump diagnostics directly and return
    if os.environ.get("NYXWIN_NON_INTERACTIVE") == "1" or not (hasattr(sys.stdout, "isatty") and sys.stdout.isatty()):
        print(f"\n--- NyxWin Diagnostics for {proj_name} ---")
        if failure_diag:
            print(f"Error ({failure_diag.get('tool', 'toolchain')}): {failure_diag.get('message', 'Build failure')}")
            if failure_diag.get("file"):
                print(f"Location: {failure_diag.get('file')}:{failure_diag.get('line', '')}")
        for idx, w in enumerate(warnings, 1):
            print(f"[{idx}/{len(warnings)}] {getattr(w, 'raw_text', str(w))}")
        print()
        return

    curr_idx = 0
    total_warnings = len(warnings)
    status_msg = ""
    status_is_error = False

    while True:
        transition_screen()
        w = get_terminal_width()

        content_lines: List[str] = []

        # 1. Header meta line
        meta_left = f"{proj_name} · {target_triple}"
        if not is_success:
            meta_right = "BUILD FAILED"
        else:
            meta_right = f"{total_warnings} Warning{'s' if total_warnings != 1 else ''}"

        inner_content_w = max(10, w - 6)
        spacing = max(2, inner_content_w - visible_length(meta_left) - visible_length(meta_right))
        content_lines.append(f"  {fg('GRAY_MUTED', meta_left)}{' ' * spacing}{fg('AMBER' if is_success else 'CORAL_RED', bold(meta_right))}")
        content_lines.append(f"  {fg('SLATE_GRAY', '─' * max(2, w - 8))}")
        content_lines.append("")

        # 2. Body: Failure Diagnostic OR Warning Items
        if not is_success and failure_diag:
            content_lines.append(f"  {fg('CORAL_RED', bold('FATAL ERROR DIAGNOSTIC'))}")
            content_lines.append("")
            tool = failure_diag.get("tool", "compiler")
            cat = failure_diag.get("category", "BUILD FAILURE")
            msg = failure_diag.get("message", "Build terminated with error")
            exit_code = failure_diag.get("exit_code", 1)

            content_lines.append(f"  {fg('GRAY_MUTED', pad_visible('Tool:', 14))} {fg('WHITE_SOFT', tool)} ({cat})")
            content_lines.append(f"  {fg('GRAY_MUTED', pad_visible('Exit code:', 14))} {fg('WHITE_SOFT', str(exit_code))}")
            if failure_diag.get("file"):
                loc_str = str(failure_diag["file"])
                if failure_diag.get("line"):
                    loc_str += f":{failure_diag['line']}"
                    if failure_diag.get("col"):
                        loc_str += f":{failure_diag['col']}"
                content_lines.append(f"  {fg('GRAY_MUTED', pad_visible('Location:', 14))} {fg('CYAN_ELEC', loc_str)}")
            content_lines.append(f"  {fg('GRAY_MUTED', pad_visible('Error:', 14))} {fg('CORAL_RED', bold(msg))}")

            if failure_diag.get("snippet"):
                content_lines.append("")
                content_lines.append(f"  {fg('GRAY_MUTED', 'Source Context:')}")
                content_lines.append(f"    {fg('WHITE_SOFT', failure_diag['snippet'])}")
                if failure_diag.get("caret"):
                    content_lines.append(f"    {fg('CORAL_RED', failure_diag['caret'])}")

            if total_warnings > 0:
                content_lines.append("")
                content_lines.append(f"  {fg('SLATE_GRAY', '─' * max(2, w - 8))}")
                content_lines.append(f"  {fg('AMBER', f'Also captured {total_warnings} non-fatal compiler warning(s).')}")

        elif total_warnings > 0:
            w_item = warnings[curr_idx]
            warn_sym = symbol("WARN")

            # Warning title badge
            badge_title = f"{warn_sym}  WARNING [{curr_idx + 1}/{total_warnings}]"
            content_lines.append(f"  {fg('AMBER', bold(badge_title))}")
            content_lines.append("")

            tool = getattr(w_item, "tool", "compiler")
            content_lines.append(f"  {fg('GRAY_MUTED', pad_visible('Tool:', 14))} {fg('WHITE_SOFT', tool)}")
            if getattr(w_item, "file_loc", ""):
                content_lines.append(f"  {fg('GRAY_MUTED', pad_visible('Location:', 14))} {fg('CYAN_ELEC', w_item.file_loc)}")
            content_lines.append(f"  {fg('GRAY_MUTED', pad_visible('Severity:', 14))} {fg('AMBER', 'Warning')}")
            content_lines.append(f"  {fg('GRAY_MUTED', pad_visible('Message:', 14))} {fg('WHITE_SOFT', bold(getattr(w_item, 'message', str(w_item))))}")

            # Snippet & Caret
            snippet = getattr(w_item, "snippet", "")
            caret = getattr(w_item, "caret", "")
            if snippet:
                content_lines.append("")
                content_lines.append(f"  {fg('GRAY_MUTED', 'Source Context:')}")
                content_lines.append(f"    {fg('WHITE_SOFT', snippet)}")
                if caret:
                    content_lines.append(f"    {fg('AMBER', caret)}")

            # Associated Notes
            notes = getattr(w_item, "notes", [])
            if notes:
                content_lines.append("")
                content_lines.append(f"  {fg('GRAY_MUTED', 'Associated Notes:')}")
                for note in notes:
                    loc = f"{note['file_loc']}: " if note.get("file_loc") else ""
                    content_lines.append(f"    • {fg('TEAL', loc)}{fg('WHITE_SOFT', note.get('message', ''))}")

            # Fix-it guidance
            fixits = getattr(w_item, "fixits", [])
            if fixits:
                content_lines.append("")
                content_lines.append(f"  {fg('GRAY_MUTED', 'Suggested Fix-it:')}")
                for f_item in fixits:
                    content_lines.append(f"    ✔ {fg('EMERALD', f_item)}")

            # Raw diagnostic excerpt if complex
            raw_text = getattr(w_item, "raw_text", "")
            raw_lines = raw_text.splitlines()
            if len(raw_lines) > 4:
                content_lines.append("")
                content_lines.append(f"  {fg('DARK_GRAY', 'Complete Compiler Output:')}")
                for rl in raw_lines[:6]:
                    content_lines.append(f"    {fg('DARK_GRAY', rl)}")
                if len(raw_lines) > 6:
                    content_lines.append(f"    {fg('DARK_GRAY', f'... ({len(raw_lines) - 6} more lines)')}")

        else:
            content_lines.append(f"  {fg('EMERALD', '✔ No compiler warnings or fatal diagnostics recorded.')}")

        content_lines.append("")

        # 3. Render container panel
        panel_title = "BUILD DIAGNOSTICS"
        panel_badge = f"Warning {curr_idx + 1}/{total_warnings}" if total_warnings > 0 else "Clean"
        panel_border = "AMBER" if total_warnings > 0 else ("CORAL_RED" if not is_success else "EMERALD")

        panel = render_panel(
            title=panel_title,
            content_lines=content_lines,
            badge=panel_badge,
            width=w,
            border_color=panel_border,
            title_color="CYAN_ELEC",
            badge_color="VIOLET"
        )
        print(panel)

        # 4. Status confirmation line if an action just ran
        if status_msg:
            msg_color = "CORAL_RED" if status_is_error else "EMERALD"
            print(f"\n  {fg(msg_color, status_msg)}")
            status_msg = ""
            status_is_error = False

        # 5. Bottom Navigation Bar
        shortcuts = []
        if total_warnings > 0:
            shortcuts.append(("C", "Copy Current"))
            shortcuts.append(("A", "Copy All"))
        elif not is_success:
            shortcuts.append(("C", "Copy Error"))
        shortcuts.append(("S", "Save Report"))
        if total_warnings > 1:
            shortcuts.append(("←/→", "Prev/Next"))
        shortcuts.append(("Esc", "Back to Summary"))

        action_parts = []
        for key, act in shortcuts:
            action_parts.append(f"[{fg('WHITE_SOFT', key)}] {fg('GRAY_MUTED', act)}")
        footer_bar = f" {fg('SLATE_GRAY', '•')} ".join(action_parts)
        print(f"\n  {footer_bar}\n", end="", flush=True)

        # 6. Read interactive key
        try:
            k = read_key()
        except Exception:
            break

        if k in ("c", "C"):
            # Copy current warning or failure diagnostic
            if total_warnings > 0:
                current_text = getattr(warnings[curr_idx], "raw_text", str(warnings[curr_idx]))
                ok = copy_to_clipboard(current_text)
                if ok:
                    status_msg = f"✔ Warning [{curr_idx + 1}/{total_warnings}] copied to clipboard."
                    status_is_error = False
                else:
                    dest = save_diagnostics_report(tracker, project_dir, is_success)
                    status_msg = f"⚠ Clipboard unavailable. Report saved to: {dest.name}"
                    status_is_error = True
            elif not is_success and failure_diag:
                err_text = str(failure_diag.get("message", "Error"))
                ok = copy_to_clipboard(err_text)
                if ok:
                    status_msg = "✔ Error diagnostic copied to clipboard."
                    status_is_error = False
                else:
                    dest = save_diagnostics_report(tracker, project_dir, is_success)
                    status_msg = f"⚠ Clipboard unavailable. Report saved to: {dest.name}"
                    status_is_error = True

        elif k in ("a", "A"):
            # Copy all warnings
            all_text = generate_diagnostics_report_text(tracker, project_dir, is_success)
            ok = copy_to_clipboard(all_text)
            if ok:
                status_msg = f"✔ All {total_warnings} warnings and diagnostics copied to clipboard."
                status_is_error = False
            else:
                dest = save_diagnostics_report(tracker, project_dir, is_success)
                status_msg = f"⚠ Clipboard unavailable. Report saved to: {dest.name}"
                status_is_error = True

        elif k in ("s", "S"):
            # Save diagnostics report
            try:
                dest = save_diagnostics_report(tracker, project_dir, is_success)
                status_msg = f"✔ Complete diagnostics report saved to: {dest}"
                status_is_error = False
            except Exception as e:
                status_msg = f"✕ Failed to save report: {e}"
                status_is_error = True

        elif k in ("LEFT", "h", "H", "p", "P", "["):
            if total_warnings > 1:
                curr_idx = (curr_idx - 1) % total_warnings

        elif k in ("RIGHT", "l", "L", "n", "N", "]"):
            if total_warnings > 1:
                curr_idx = (curr_idx + 1) % total_warnings

        elif k in ("ESC", "q", "Q", "ENTER"):
            break

def screen_build_log_viewer(tracker: Any, log_path: Path):
    """
    Dedicated interactive build transcript viewer screen.
    Enables developers to inspect, paginate, copy, and open the persistent build log.
    """
    if not log_path or not Path(log_path).is_file():
        return

    try:
        raw_text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        raw_text = ""

    lines = raw_text.splitlines() if raw_text else ["No log content available."]
    proj_name = getattr(tracker, "project_name", "Project")

    # Non-interactive fallback
    if os.environ.get("NYXWIN_NON_INTERACTIVE") == "1" or not (hasattr(sys.stdout, "isatty") and sys.stdout.isatty()):
        print(f"\n--- NyxWin Build Log ({log_path.name}) ---")
        for line in lines[-40:]:
            print(line)
        print()
        return

    page_size = 22
    total_pages = max(1, (len(lines) + page_size - 1) // page_size)
    curr_page = 0
    status_msg = ""
    status_is_error = False

    while True:
        transition_screen()
        w = get_terminal_width()

        start_idx = curr_page * page_size
        end_idx = min(start_idx + page_size, len(lines))
        page_lines = lines[start_idx:end_idx]

        content_lines: List[str] = []

        # 1. Header meta line
        meta_left = f"{proj_name} · {log_path.name}"
        meta_right = f"Page {curr_page + 1}/{total_pages} ({len(lines)} lines)"

        inner_content_w = max(10, w - 6)
        spacing = max(2, inner_content_w - visible_length(meta_left) - visible_length(meta_right))
        content_lines.append(f"  {fg('GRAY_MUTED', meta_left)}{' ' * spacing}{fg('CYAN_ELEC', bold(meta_right))}")
        content_lines.append(f"  {fg('SLATE_GRAY', '─' * max(2, w - 8))}")
        content_lines.append("")

        # 2. Body lines
        for l in page_lines:
            stripped = l.strip()
            if stripped.startswith("[STAGE"):
                content_lines.append(f"  {fg('CYAN_ELEC', bold(l))}")
            elif "FAILED" in l or "✕" in l or "Error:" in l:
                content_lines.append(f"  {fg('CORAL_RED', l)}")
            elif "SUCCEEDED" in l or "✔" in l:
                content_lines.append(f"  {fg('EMERALD', l)}")
            elif "WARNING" in l or "⚠" in l:
                content_lines.append(f"  {fg('AMBER', l)}")
            elif stripped.startswith("---") or stripped.startswith("==="):
                content_lines.append(f"  {fg('SLATE_GRAY', l)}")
            else:
                content_lines.append(f"  {fg('WHITE_SOFT', l)}")

        content_lines.append("")

        # 3. Render Panel
        panel = render_panel(
            title="BUILD LOG TRANSCRIPT",
            content_lines=content_lines,
            badge=f"{log_path.name}",
            width=w,
            border_color="CYAN_ELEC",
            title_color="CYAN_ELEC",
            badge_color="CYAN_ELEC"
        )
        print(panel)

        if status_msg:
            msg_color = "CORAL_RED" if status_is_error else "EMERALD"
            print(f"\n  {fg(msg_color, status_msg)}")
            status_msg = ""
            status_is_error = False

        # 4. Navigation bar
        shortcuts = [
            ("O", "Open in Editor"),
            ("C", "Copy Full Log"),
            ("P", "Copy Path"),
        ]
        if total_pages > 1:
            shortcuts.append(("←/→", "Prev/Next"))
        shortcuts.append(("Esc", "Back to Summary"))

        action_parts = []
        for key, act in shortcuts:
            action_parts.append(f"[{fg('WHITE_SOFT', key)}] {fg('GRAY_MUTED', act)}")
        footer_bar = f" {fg('SLATE_GRAY', '•')} ".join(action_parts)
        print(f"\n  {footer_bar}\n", end="", flush=True)

        try:
            k = read_key()
        except Exception:
            break

        if k in ("o", "O"):
            try:
                os.startfile(str(log_path.resolve()))
                status_msg = "✔ Opened build log in default editor."
                status_is_error = False
            except Exception as e:
                status_msg = f"✕ Failed to open log file: {e}"
                status_is_error = True

        elif k in ("c", "C"):
            ok = copy_to_clipboard(raw_text)
            if ok:
                status_msg = f"✔ Full build log ({len(lines)} lines) copied to clipboard."
                status_is_error = False
            else:
                status_msg = f"⚠ Clipboard unavailable. Log path: {log_path}"
                status_is_error = True

        elif k in ("p", "P"):
            abs_p = str(log_path.resolve())
            ok = copy_to_clipboard(abs_p)
            if ok:
                status_msg = f"✔ Log path copied to clipboard: {abs_p}"
                status_is_error = False
            else:
                status_msg = f"Log path: {abs_p}"
                status_is_error = False

        elif k in ("LEFT", "h", "H", "[", "UP", "k", "K"):
            if total_pages > 1:
                curr_page = (curr_page - 1) % total_pages

        elif k in ("RIGHT", "]", "DOWN", "j", "J", "SPACE"):
            if total_pages > 1:
                curr_page = (curr_page + 1) % total_pages

        elif k in ("ESC", "q", "Q", "ENTER"):
            break
