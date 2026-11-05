"""
Status, Progress Bar, Summary, and Diagnostic Components.
"""

from typing import List, Tuple, Optional
from nyxwin.tui.theme import (
    fg, bold, dim, strip_ansi, visible_length, pad_visible, symbol
)
from nyxwin.tui.terminal import get_terminal_width
from nyxwin.tui.components.frame import render_panel

def render_status_badge(status_type: str, text: str) -> str:
    """Formats a colored status badge."""
    color_map = {
        "success": "EMERALD",
        "active": "CYAN_ELEC",
        "warning": "AMBER",
        "error": "CORAL_RED",
        "muted": "GRAY_MUTED",
        "highlight": "VIOLET"
    }
    col = color_map.get(status_type.lower(), "WHITE_SOFT")
    return fg(col, f"[{text}]")

def render_progress_bar(
    percentage: float,
    bar_width: int = 28,
    filled_char: Optional[str] = None,
    unfilled_char: Optional[str] = None
) -> str:
    """
    Renders a solid Unicode block progress bar.
    Format: [██████████████░░░░░░░░░░]  50%
    """
    clamped = max(0.0, min(100.0, percentage))
    fill_sym = filled_char or symbol("BAR_FILLED")
    unfill_sym = unfilled_char or symbol("BAR_UNFILLED")

    filled_len = int(round((clamped / 100.0) * bar_width))
    unfilled_len = max(0, bar_width - filled_len)

    bar = f"[{fg('TEAL', fill_sym * filled_len)}{fg('SLATE_GRAY', unfill_sym * unfilled_len)}]"
    pct_text = f" {int(clamped)}%"
    return f"{bar}{fg('WHITE_SOFT', pct_text)}"

def render_summary_card(
    title: str,
    details: List[Tuple[str, str]],
    is_success: bool = True,
    badge: str = "",
    width: Optional[int] = None
) -> str:
    """Renders a permanent operation completion summary card."""
    w = width or get_terminal_width()
    border_color = "EMERALD" if is_success else "CORAL_RED"
    title_color = "EMERALD" if is_success else "CORAL_RED"

    lines = []
    lines.append("")
    for label, val in details:
        lbl_fmt = fg("GRAY_MUTED", pad_visible(f"  {label}:", 18, align="left"))
        val_fmt = fg("WHITE_SOFT", val)
        lines.append(f"{lbl_fmt} {val_fmt}")
    lines.append("")

    return render_panel(
        title=title,
        content_lines=lines,
        badge=badge,
        width=w,
        border_color=border_color,
        title_color=title_color,
        badge_color="VIOLET"
    )

def render_diagnostic_panel(
    diagnostics_text: str,
    title: str = "COMPILER DIAGNOSTICS",
    width: Optional[int] = None
) -> str:
    """Renders a structured compiler error diagnostic panel preserving squiggles."""
    w = width or get_terminal_width()
    lines = [""]
    for l in diagnostics_text.splitlines():
        lines.append(f"  {l}")
    lines.append("")

    return render_panel(
        title=title,
        content_lines=lines,
        badge="ERROR",
        width=w,
        border_color="CORAL_RED",
        title_color="CORAL_RED",
        badge_color="CORAL_RED"
    )

