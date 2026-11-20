"""
Table and Data Grid Components.
Renders structured key-value grids and column data tables with clean alignment.
"""

from typing import List, Tuple, Optional
from nyxwin.tui.theme import (
    fg, bold, dim, strip_ansi, visible_length, pad_visible, symbol
)
from nyxwin.tui.terminal import get_terminal_width

def render_key_value_grid(
    pairs: List[Tuple[str, str]],
    width: Optional[int] = None,
    key_width: int = 16,
    key_color: str = "GRAY_MUTED",
    value_color: str = "WHITE_SOFT"
) -> List[str]:
    """
    Renders aligned key-value pairs.
    Example:
      Target:   arm64-apple-ios17.0
      Runtime:  Swift 6.0 (swiftc)
    """
    lines = []
    for k, v in pairs:
        formatted_k = pad_visible(f"  {k}:", key_width, align="left")
        k_colored = fg(key_color, formatted_k)
        v_colored = fg(value_color, v)
        lines.append(f"{k_colored} {v_colored}")
    return lines

def render_column_table(
    headers: List[str],
    rows: List[List[str]],
    col_widths: Optional[List[int]] = None,
    width: Optional[int] = None,
    title: Optional[str] = None
) -> List[str]:
    """
    Renders a column table with headers and row data.
    """
    w = width or get_terminal_width()
    inner_w = max(10, w - 4)

    # Calculate column widths automatically if not specified
    num_cols = len(headers)
    if not col_widths or len(col_widths) != num_cols:
        col_widths = []
        for c in range(num_cols):
            max_c = visible_length(headers[c])
            for r in rows:
                if c < len(r):
                    max_c = max(max_c, visible_length(r[c]))
            col_widths.append(max_c + 2)

    # Format Header Row
    hdr_parts = []
    for c, h in enumerate(headers):
        hdr_parts.append(pad_visible(h, col_widths[c], align="left"))
    hdr_line = "  " + "".join(hdr_parts)
    hdr_line_colored = fg("BLUE_AZURE", bold(hdr_line))

    # Divider
    div_line = "  " + fg("SLATE_GRAY", "─" * min(inner_w - 2, visible_length(hdr_line)))

    # Format Rows
    lines = []
    if title:
        lines.append(f"  {fg('CYAN_ELEC', bold(title))}")
        lines.append("")
    lines.extend([hdr_line_colored, div_line])
    for row in rows:
        row_parts = []
        for c in range(num_cols):
            cell = row[c] if c < len(row) else ""
            row_parts.append(pad_visible(cell, col_widths[c], align="left"))
        lines.append("  " + "".join(row_parts))

    return lines

