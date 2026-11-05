"""
Prompt and Confirmation Components.
Handles text input prompts and safe destructive confirmation screens.
"""

import os
import sys
from typing import Optional, List

from nyxwin.tui.theme import fg, bold, dim, symbol
from nyxwin.tui.terminal import get_terminal_width, read_key, clear_screen
from nyxwin.tui.components.frame import render_panel, render_footer
from nyxwin.tui.components.menu import MenuItem, prompt_modern_menu

def prompt_text_input(label: str, default_value: str = "", width: Optional[int] = None) -> str:
    """Prompts user for text input with styled labels and default value."""
    if os.environ.get("NYXWIN_NON_INTERACTIVE") == "1":
        return default_value

    if default_value:
        display_prompt = f"  {fg('WHITE_SOFT', bold(label))} [{fg('CYAN_ELEC', default_value)}]: "
    else:
        display_prompt = f"  {fg('WHITE_SOFT', bold(label))}: "

    try:
        val = input(display_prompt).strip()
        return val if val else default_value
    except (KeyboardInterrupt, EOFError):
        print()
        return default_value

def prompt_destructive_confirmation(
    title: str,
    warning_text: str = "",
    action_label: str = "Overwrite and Continue",
    width: Optional[int] = None,
    details_lines: Optional[List[str]] = None,
    header_badge: str = "WARNING",
    border_color: str = "AMBER",
    title_color: str = "AMBER",
    badge_color: str = "AMBER",
) -> bool:
    """
    Renders a destructive warning prompt where Cancel is always the default option (index 0).
    Displays structured contextual details and safety guarantees directly above the prompt.
    Returns True only if user explicitly selects the destructive option.
    """
    w = width or get_terminal_width()
    warn_sym = symbol("WARN")

    warning_lines = []
    if details_lines:
        for dl in details_lines:
            warning_lines.append(f"  {dl}" if not dl.startswith("  ") else dl)
        if warning_text:
            warning_lines.append("")

    if warning_text:
        for wt in warning_text.splitlines():
            if wt.strip():
                warning_lines.append(f"  {wt.strip()}")
            else:
                warning_lines.append("")

    warning_lines.append("")
    warning_lines.append(f"  {fg('AMBER', bold(warn_sym + ' WARNING: This action cannot be undone!'))}")

    items = [
        MenuItem(
            label="Cancel (Safe - keep current files)",
            key="1",
            tag="SAFE",
            tag_color="EMERALD"
        ),
        MenuItem(
            label=f"{action_label}",
            key="2",
            tag="DESTRUCTIVE",
            tag_color="CORAL_RED"
        ),
    ]

    choice = prompt_modern_menu(
        header_title=title,
        items=items,
        header_badge=header_badge,
        top_panel_lines=warning_lines,
        top_panel_border=border_color,
        top_panel_title_color=title_color,
        top_panel_badge_color=badge_color,
        selected_index=0,  # SAFE CANCEL IS DEFAULT
        can_cancel=True,
        width=w
    )

    return choice == 1

