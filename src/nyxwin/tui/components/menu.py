"""
Modern Menu Component.
Handles two-level interactive navigation, cursor movement, numeric shortcuts,
and visual item rendering adhering to the unified design system.
"""

import os
import sys
from typing import List, Tuple, Optional, Union, Dict, Any

from nyxwin.tui.theme import (
    fg, bold, dim, strip_ansi, visible_length, pad_visible, symbol
)
from nyxwin.tui.terminal import (
    get_terminal_width, read_key, clear_screen, reposition_cursor
)
from nyxwin.tui.components.frame import render_panel, render_footer

class MenuItem:
    """Represents an interactive or decorative menu item."""
    def __init__(
        self,
        label: str,
        description: str = "",
        key: Optional[str] = None,
        tag: str = "",
        tag_color: str = "GRAY_MUTED",
        is_separator: bool = False
    ):
        self.label = label
        self.description = description
        self.key = key
        self.tag = tag
        self.tag_color = tag_color
        self.is_separator = is_separator

def render_menu_lines(
    items: List[MenuItem],
    selected_index: int,
    inner_width: int,
    max_visible: int = 10,
    scroll_offset: int = 0
) -> Tuple[List[str], int]:
    """
    Renders lines for inside a menu panel.
    Returns (rendered_lines, adjusted_scroll_offset).
    """
    total = len(items)
    if total == 0:
        return ["  (no items)"], 0

    # Adjust scroll offset
    if selected_index < scroll_offset:
        scroll_offset = selected_index
    elif selected_index >= scroll_offset + max_visible:
        scroll_offset = selected_index - max_visible + 1

    lines = []
    visible_end = min(total, scroll_offset + max_visible)

    if scroll_offset > 0:
        lines.append(f"  {fg('GRAY_MUTED', '▲ ... (' + str(scroll_offset) + ' more above)')}")

    cursor_sym = symbol("CURSOR")

    for idx in range(scroll_offset, visible_end):
        item = items[idx]
        if item.is_separator:
            lines.append(f"  {fg('SLATE_GRAY', '─' * (inner_width - 4))}")
            continue

        is_selected = (idx == selected_index)

        # Cursor prefix
        if is_selected:
            cur_prefix = f" {fg('CYAN_ELEC', cursor_sym)} "
        else:
            cur_prefix = "   "

        # Key badge if present (e.g. [1])
        key_str = f"[{item.key}] " if item.key else ""

        # Main label
        if is_selected:
            label_fmt = fg("WHITE_SOFT", bold(f"{key_str}{item.label}"))
        else:
            label_fmt = fg("WHITE_SOFT", f"{key_str}{item.label}")

        # Tag if present (e.g. ACTIVE, DESTRUCTIVE)
        tag_fmt = ""
        if item.tag:
            tag_fmt = f" {fg(item.tag_color, f'[{item.tag}]')}"

        # Combine main line
        main_line = f"{cur_prefix}{label_fmt}{tag_fmt}"

        # Description if present
        if item.description:
            desc_indent = "        " if item.key else "     "
            # In expanded terminals (width >= 90), render description on same line if short
            desc_vlen = visible_length(item.description)
            main_vlen = visible_length(main_line)
            if inner_width >= 90 and (main_vlen + desc_vlen + 4 < inner_width):
                pad_space = inner_width - main_vlen - desc_vlen - 4
                combined = f"{main_line}{' ' * pad_space}{fg('GRAY_MUTED', item.description)}"
                lines.append(f" {combined}")
            else:
                lines.append(f" {main_line}")
                lines.append(f" {desc_indent}{fg('GRAY_MUTED', item.description)}")
        else:
            lines.append(f" {main_line}")

    if visible_end < total:
        remaining = total - visible_end
        lines.append(f"  {fg('GRAY_MUTED', '▼ ... (' + str(remaining) + ' more below)')}")

    return lines, scroll_offset

def prompt_modern_menu(
    header_title: str,
    items: List[Union[MenuItem, str]],
    header_badge: str = "",
    top_panel_lines: Optional[List[str]] = None,
    selected_index: int = 0,
    can_cancel: bool = True,
    shortcuts: Optional[List[Tuple[str, str]]] = None,
    width: Optional[int] = None,
    top_panel_border: Optional[str] = None,
    top_panel_title_color: Optional[str] = None,
    top_panel_badge_color: Optional[str] = None,
    actions_title: Optional[str] = None,
) -> int:
    """
    Renders a unified modern interactive two-panel or single-panel menu.
    Maintains composed structured context panels above the menu throughout redraws.
    Returns selected index (0-based) or -1 if canceled with ESC.
    """
    w = width or get_terminal_width()
    inner_w = max(10, w - 2)

    # Normalize items to MenuItem list
    menu_items: List[MenuItem] = []
    for i, it in enumerate(items):
        if isinstance(it, MenuItem):
            menu_items.append(it)
        else:
            # Check if string starts with bracketed key
            menu_items.append(MenuItem(label=str(it)))

    # Non-interactive CI guard
    if os.environ.get("NYXWIN_NON_INTERACTIVE") == "1":
        return min(selected_index, len(menu_items) - 1) if menu_items else -1

    current = max(0, min(selected_index, len(menu_items) - 1))
    scroll_offset = 0

    if shortcuts is None:
        shortcuts = [
            ("↑/↓", "Navigate"),
            ("Enter", "Select"),
        ]
        if can_cancel:
            shortcuts.append(("Esc", "Back"))
        if any(it.key for it in menu_items):
            shortcuts.append(("1-9", "Select"))

    while True:
        clear_screen(force_cls=False)

        # 1. Top context card if provided
        if top_panel_lines:
            top_panel = render_panel(
                title=header_title,
                content_lines=top_panel_lines,
                badge=header_badge,
                width=w,
                border_color=top_panel_border or "SLATE_GRAY",
                title_color=top_panel_title_color or "BLUE_AZURE",
                badge_color=top_panel_badge_color or "VIOLET"
            )
            print(top_panel)
            print()

        # 2. Actions / Menu panel
        menu_title = actions_title or ("ACTIONS" if top_panel_lines else header_title)
        menu_badge = "" if top_panel_lines else header_badge

        rendered_menu_lines, scroll_offset = render_menu_lines(
            items=menu_items,
            selected_index=current,
            inner_width=inner_w,
            max_visible=12,
            scroll_offset=scroll_offset
        )

        actions_panel = render_panel(
            title=menu_title,
            content_lines=rendered_menu_lines,
            badge=menu_badge,
            width=w
        )
        print(actions_panel)
        print()

        # 3. Standardized footer
        print(render_footer(shortcuts=shortcuts, width=w))

        # 4. Read key
        k = read_key()
        if k == "UP":
            current = (current - 1) % len(menu_items)
            while menu_items[current].is_separator:
                current = (current - 1) % len(menu_items)
        elif k == "DOWN":
            current = (current + 1) % len(menu_items)
            while menu_items[current].is_separator:
                current = (current + 1) % len(menu_items)
        elif k == "HOME":
            current = 0
        elif k == "END":
            current = len(menu_items) - 1
        elif k == "ENTER":
            return current
        elif k in ("ESC", "q", "Q") and can_cancel:
            return -1
        elif k in "1234567890":
            # Direct numeric jump if matching key found
            for idx, item in enumerate(menu_items):
                if item.key == k:
                    return idx

