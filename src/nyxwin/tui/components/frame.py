"""
Frame and Panel Components.
Handles rounded Unicode panels, headers, breadcrumbs, dividers, and footers.
"""

from typing import List, Tuple, Optional
from nyxwin.tui.theme import (
    fg, bold, dim, strip_ansi, visible_length, pad_visible, symbol, get_capabilities
)
from nyxwin.tui.terminal import get_terminal_width

def render_panel(
    title: str,
    content_lines: List[str],
    badge: str = "",
    width: Optional[int] = None,
    border_color: str = "SLATE_GRAY",
    title_color: str = "BLUE_AZURE",
    badge_color: str = "VIOLET"
) -> str:
    """
    Renders content inside a single-line rounded Unicode panel.
    Format:
    ╭─ TITLE ────────────────────────────────────────── [BADGE] ─╮
    │  Content line                                              │
    ╰────────────────────────────────────────────────────────────╯
    """
    w = width or get_terminal_width()
    inner_w = max(10, w - 2)

    tl = symbol("BOX_TL")
    tr = symbol("BOX_TR")
    bl = symbol("BOX_BL")
    br = symbol("BOX_BR")
    h = symbol("BOX_H")
    v = symbol("BOX_V")

    # Header Top Line: ╭─ TITLE ───...── [BADGE] ─╮
    top_parts = [tl, h]
    used_len = 2

    if title:
        top_parts.append(" ")
        top_parts.append(fg(title_color, bold(title)))
        top_parts.append(" ")
        used_len += visible_length(title) + 2

    badge_part = ""
    badge_len = 0
    if badge:
        formatted_badge = f"[{badge}]"
        badge_part = f" {fg(badge_color, formatted_badge)} "
        badge_len = visible_length(formatted_badge) + 2

    # Calculate remaining horizontal line
    if badge_part:
        remaining_h = max(1, w - used_len - badge_len - 2)
    else:
        remaining_h = max(1, w - used_len - 1)

    top_parts.append(fg(border_color, h * remaining_h))
    if badge_part:
        top_parts.append(badge_part)
        top_parts.append(fg(border_color, h))
    top_parts.append(fg(border_color, tr))
    top_line = "".join(top_parts)

    # Content Lines: │  Content...  │
    body_lines = []
    max_body_w = max(4, inner_w - 2)
    for line in content_lines:
        if not line.strip():
            # Empty / blank line inside panel
            body_line = f"{fg(border_color, v)}{' ' * inner_w}{fg(border_color, v)}"
            body_lines.append(body_line)
            continue

        # Check existing leading whitespace indentation
        clean = strip_ansi(line)
        leading_spaces = len(clean) - len(clean.lstrip(" "))
        if leading_spaces < 2:
            formatted_line = (" " * (2 - leading_spaces)) + line
        else:
            formatted_line = line

        # Ensure content does not touch right border
        vlen = visible_length(formatted_line)
        if vlen > max_body_w:
            from nyxwin.tui.theme import truncate_visible
            formatted_line = truncate_visible(formatted_line, max_body_w)
            vlen = visible_length(formatted_line)

        padding_needed = max(0, inner_w - vlen)
        body_line = f"{fg(border_color, v)}{formatted_line}{' ' * padding_needed}{fg(border_color, v)}"
        body_lines.append(body_line)

    # Bottom Line: ╰──────...──────╯
    bottom_line = f"{fg(border_color, bl)}{fg(border_color, h * inner_w)}{fg(border_color, br)}"

    return "\n".join([top_line] + body_lines + [bottom_line])

def render_frame(
    content_lines: List[str],
    width: Optional[int] = None,
    border_color: str = "SLATE_GRAY"
) -> str:
    """Renders a simple bordered box without title bar."""
    return render_panel("", content_lines, badge="", width=width, border_color=border_color)

def render_header(
    breadcrumb: str = "NYXWIN › WORKSPACE",
    right_badge: str = "",
    subtitle: str = "",
    width: Optional[int] = None
) -> str:
    """Renders the top application header card."""
    lines = []
    if subtitle:
        lines.append(f"  {fg('GRAY_MUTED', subtitle)}")
    return render_panel(
        title=breadcrumb,
        content_lines=lines,
        badge=right_badge,
        width=width,
        border_color="SLATE_GRAY",
        title_color="BLUE_AZURE",
        badge_color="VIOLET"
    )

def render_divider(width: Optional[int] = None, border_color: str = "SLATE_GRAY") -> str:
    """Renders a horizontal panel divider line with intersecting T-joints."""
    w = width or get_terminal_width()
    inner_w = max(10, w - 2)
    left_t = symbol("BOX_T_RIGHT")
    right_t = symbol("BOX_T_LEFT")
    h = symbol("BOX_H")
    return f"{fg(border_color, left_t)}{fg(border_color, h * inner_w)}{fg(border_color, right_t)}"

def render_footer(
    shortcuts: Optional[List[Tuple[str, str]]] = None,
    width: Optional[int] = None
) -> str:
    """
    Renders standardized bottom controls bar:
    Format: [↑/↓] Navigate  •  [Enter] Select  •  [Esc] Back  •  [1-N] Select
    """
    if shortcuts is None:
        shortcuts = [
            ("↑/↓", "Navigate"),
            ("Enter", "Select"),
            ("Esc", "Back")
        ]

    parts = []
    for key, action in shortcuts:
        part = f"[{fg('WHITE_SOFT', key)}] {fg('GRAY_MUTED', action)}"
        parts.append(part)

    bullet = f" {fg('SLATE_GRAY', '•')} "
    bar = bullet.join(parts)
    return f"  {bar}"
