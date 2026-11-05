import os
import re
import sys
from typing import List, Tuple, Optional

from nyxwin.core.models import Color
from nyxwin.tui.terminal import print_header, read_key, clear_screen, get_terminal_width

from nyxwin.tui.theme import fg, bold, dim, strip_ansi, visible_length, symbol
from nyxwin.tui.components.frame import render_panel, render_footer

def prompt_menu(
    title: str,
    options: List[str],
    selected_index: int = 0,
    breadcrumb: str = "",
    can_cancel: bool = True,
    top_panel_lines: Optional[List[str]] = None,
    top_panel_title: Optional[str] = None,
    top_panel_badge: Optional[str] = None,
    top_panel_border: Optional[str] = None,
    top_panel_title_color: Optional[str] = None,
    top_panel_badge_color: Optional[str] = None,
) -> int:
    """
    Renders an interactive scrolling keyboard-driven menu inside modern rounded panels.
    Supports composed layouts by maintaining structured context cards (top_panel_lines)
    above the actions panel throughout redraw cycles.
    Returns the selected option index, or -1 if canceled with ESC.
    """
    if not options:
        return -1

    if os.environ.get("NYXWIN_NON_INTERACTIVE") == "1":
        return min(selected_index, len(options) - 1)

    current = max(0, min(selected_index, len(options) - 1))
    max_visible = 10
    scroll_offset = 0
    w = get_terminal_width()
    inner_w = max(10, w - 2)
    cursor_sym = symbol("CURSOR")

    # Context lines for top panel:
    # Use explicitly passed top_panel_lines if provided; otherwise derive from title
    if top_panel_lines is not None:
        effective_top_lines = top_panel_lines
    else:
        raw_title_lines = [l for l in title.splitlines() if "Select an action" not in l and "Select a" not in l]
        effective_top_lines = []
        for l in raw_title_lines:
            if l.strip():
                effective_top_lines.append(f"  {l.strip()}")

    top_badge = top_panel_badge if top_panel_badge is not None else ""
    if not top_badge:
        if "PROJECT:" in title or "PROJECT TOOLS" in title:
            top_badge = "ACTIVE"
        elif "No project" in title:
            top_badge = "NO PROJECT"

    top_title = top_panel_title if top_panel_title else (breadcrumb if breadcrumb else "NYXWIN › WORKSPACE")
    border_col = top_panel_border or "SLATE_GRAY"
    title_col = top_panel_title_color or "BLUE_AZURE"
    badge_col = top_panel_badge_color or "VIOLET"

    while True:
        # Adjust scroll window
        if current < scroll_offset:
            scroll_offset = current
        elif current >= scroll_offset + max_visible:
            scroll_offset = current - max_visible + 1

        clear_screen(force_cls=False)

        # 1. Top context card if title lines present
        if effective_top_lines:
            top_panel = render_panel(
                title=top_title,
                content_lines=effective_top_lines,
                badge=top_badge,
                width=w,
                border_color=border_col,
                title_color=title_col,
                badge_color=badge_col
            )
            print(top_panel)
            print()

        # 2. Render visible items inside lower actions panel
        visible_end = min(len(options), scroll_offset + max_visible)
        menu_lines = []

        if scroll_offset > 0:
            menu_lines.append(f"  {fg('GRAY_MUTED', '▲ ... (' + str(scroll_offset) + ' more above)')}")

        for idx in range(scroll_offset, visible_end):
            opt = options[idx]
            lines = opt.splitlines()
            main_line = lines[0]
            sub_lines = lines[1:] if len(lines) > 1 else []

            if idx == current:
                cursor = f"{fg('CYAN_ELEC', cursor_sym)} "
                line_str = f" {cursor}{fg('WHITE_SOFT', bold(main_line))}"
                menu_lines.append(line_str)
                for sl in sub_lines:
                    menu_lines.append(f"     {fg('GRAY_MUTED', sl)}")
            else:
                cursor = "  "
                line_str = f" {cursor}{fg('WHITE_SOFT', main_line)}"
                menu_lines.append(line_str)
                for sl in sub_lines:
                    menu_lines.append(f"     {fg('GRAY_MUTED', sl)}")

        if visible_end < len(options):
            remaining = len(options) - visible_end
            menu_lines.append(f"  {fg('GRAY_MUTED', '▼ ... (' + str(remaining) + ' more below)')}")

        lower_title = "ACTIONS" if effective_top_lines else top_title
        actions_panel = render_panel(
            title=lower_title,
            content_lines=menu_lines,
            badge="",
            width=w,
            border_color="SLATE_GRAY",
            title_color="CYAN_ELEC" if effective_top_lines else "BLUE_AZURE",
            badge_color="VIOLET"
        )
        print(actions_panel)
        print()

        # 3. Footer hints
        footer_items = [("↑/↓", "Navigate"), ("Enter", "Select")]
        if can_cancel:
            footer_items.append(("Esc", "Back"))
        print(render_footer(footer_items, width=w))

        # 4. Input loop
        k = read_key()
        if k == "UP":
            current = (current - 1) % len(options)
        elif k == "DOWN":
            current = (current + 1) % len(options)
        elif k == "HOME":
            current = 0
        elif k == "END":
            current = len(options) - 1
        elif k == "ENTER":
            return current
        elif k in ("ESC", "q", "Q") and can_cancel:
            return -1
        elif k in "123456789":
            num_idx = int(k) - 1
            if 0 <= num_idx < len(options):
                return num_idx

def visible_len(s: str) -> int:
    """Calculates visible character width, stripping ANSI escape sequences."""
    clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', s)
    return len(clean)

def render_boxed_menu(
    header_left: str,
    header_right: str = "",
    subheader: str = "",
    title: str = "",
    subtitle: str = "",
    items: List[Tuple[str, str]] = None,
    current_idx: int = 0,
    width: int = 70,
    desc_indent: int = 5,
    title_gap: bool = True
) -> str:
    lines = []
    box_color = Color.GRAY
    reset = Color.RESET

    # Top border
    lines.append(f"{box_color}┌{'─' * width}┐{reset}")

    # Header section
    right_str = f"{Color.BOLD}{header_right}{reset} " if header_right else ""
    right_vis = f"{header_right} " if header_right else ""
    left_str = f" {Color.BOLD}{header_left}{reset}"
    left_vis = f" {header_left}"
    gap = max(0, width - visible_len(left_vis) - visible_len(right_vis))
    lines.append(f"{box_color}│{reset}{left_str}{' ' * gap}{right_str}{box_color}│{reset}")

    if subheader:
        sub_line = f" {subheader}"
        sub_pad = max(0, width - visible_len(sub_line))
        lines.append(f"{box_color}│{reset}{Color.GRAY}{sub_line}{reset}{' ' * sub_pad}{box_color}│{reset}")

    # Divider
    lines.append(f"{box_color}├{'─' * width}┤{reset}")
    lines.append(f"{box_color}│{' ' * width}│{reset}")

    # Title & Subtitle
    if title:
        t_line = f"  {title}"
        pad = max(0, width - visible_len(t_line))
        lines.append(f"{box_color}│{reset}{Color.BOLD}{Color.WHITE}{t_line}{reset}{' ' * pad}{box_color}│{reset}")
    if subtitle:
        if title and title_gap:
            lines.append(f"{box_color}│{' ' * width}│{reset}")
        s_line = f"  {subtitle}"
        pad = max(0, width - visible_len(s_line))
        lines.append(f"{box_color}│{reset}{Color.GRAY}{s_line}{reset}{' ' * pad}{box_color}│{reset}")

    lines.append(f"{box_color}│{' ' * width}│{reset}")

    # Items
    for idx, (label, desc) in enumerate(items or []):
        is_sel = (idx == current_idx)
        if is_sel:
            cursor = f"{Color.CYAN}❯{reset}  "
            cursor_vis = "❯  "
            main_vis = f"  {cursor_vis}{label}"
            pad = max(0, width - visible_len(main_vis))
            lines.append(f"{box_color}│{reset}  {cursor}{Color.BOLD}{Color.WHITE}{label}{reset}{' ' * pad}{box_color}│{reset}")
        else:
            main_vis = f"     {label}"
            pad = max(0, width - visible_len(main_vis))
            lines.append(f"{box_color}│{reset}     {label}{' ' * pad}{box_color}│{reset}")

        if desc:
            spaces = " " * desc_indent
            desc_vis = f"{spaces}{desc}"
            pad = max(0, width - visible_len(desc_vis))
            desc_color = Color.GRAY
            lines.append(f"{box_color}│{reset}{spaces}{desc_color}{desc}{reset}{' ' * pad}{box_color}│{reset}")

        lines.append(f"{box_color}│{' ' * width}│{reset}")

    # Footer
    lines.append(f"{box_color}├{'─' * width}┤{reset}")
    footer_text = "  ↑ ↓ Navigate     ENTER Select     ESC Back"
    pad = max(0, width - visible_len(footer_text))
    lines.append(f"{box_color}│{reset}{Color.GRAY}{footer_text}{reset}{' ' * pad}{box_color}│{reset}")
    lines.append(f"{box_color}└{'─' * width}┘{reset}")

    return "\n".join(lines)

def prompt_boxed_menu(
    header_left: str,
    header_right: str = "",
    subheader: str = "",
    title: str = "",
    subtitle: str = "",
    items: List[Tuple[str, str]] = None,
    selected_index: int = 0,
    width: int = 70,
    desc_indent: int = 5,
    title_gap: bool = True,
    can_cancel: bool = True
) -> int:
    """
    Renders an interactive keyboard-driven menu inside a clean single-line box.
    Returns the selected option index, or -1 if canceled with ESC.
    """
    if not items:
        return -1

    current = max(0, min(selected_index, len(items) - 1))

    while True:
        clear_screen()
        box_str = render_boxed_menu(
            header_left=header_left,
            header_right=header_right,
            subheader=subheader,
            title=title,
            subtitle=subtitle,
            items=items,
            current_idx=current,
            width=width,
            desc_indent=desc_indent,
            title_gap=title_gap
        )
        try:
            print(box_str)
        except UnicodeEncodeError:
            print(box_str.encode("ascii", "replace").decode("ascii"))

        k = read_key()
        if k == "UP":
            current = (current - 1) % len(items)
        elif k == "DOWN":
            current = (current + 1) % len(items)
        elif k == "HOME":
            current = 0
        elif k == "END":
            current = len(items) - 1
        elif k == "ENTER":
            return current
        elif k == "ESC" and can_cancel:
            return -1

def print_boxed_header(
    breadcrumb: str,
    title: str = "",
    subtitle: str = "",
    width: int = 70
):
    """Prints a clean boxed header for input dialogs."""
    clear_screen()
    box_color = Color.GRAY
    reset = Color.RESET
    lines = []
    lines.append(f"{box_color}┌{'─' * width}┐{reset}")
    line_content = f" {breadcrumb}"
    pad = max(0, width - visible_len(line_content))
    lines.append(f"{box_color}│{reset}{Color.BOLD}{line_content}{reset}{' ' * pad}{box_color}│{reset}")
    lines.append(f"{box_color}├{'─' * width}┤{reset}")
    lines.append(f"{box_color}│{' ' * width}│{reset}")
    if title:
        t_content = f"  {title}"
        pad = max(0, width - visible_len(t_content))
        lines.append(f"{box_color}│{reset}{Color.BOLD}{Color.WHITE}{t_content}{reset}{' ' * pad}{box_color}│{reset}")
    if subtitle:
        s_content = f"  {subtitle}"
        pad = max(0, width - visible_len(s_content))
        lines.append(f"{box_color}│{reset}{Color.GRAY}{s_content}{reset}{' ' * pad}{box_color}│{reset}")
    lines.append(f"{box_color}│{' ' * width}│{reset}")
    lines.append(f"{box_color}└{'─' * width}┘{reset}")
    try:
        print("\n".join(lines))
    except UnicodeEncodeError:
        print("\n".join(lines).encode("ascii", "replace").decode("ascii"))
    print()
