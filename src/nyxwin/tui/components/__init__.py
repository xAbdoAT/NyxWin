"""
NyxWin Reusable TUI Component Library.
Provides modern, responsive terminal components adhering to Direction B (Modern Terminal Workspace).
"""

from nyxwin.tui.components.frame import (
    render_frame, render_panel, render_header, render_divider, render_footer
)
from nyxwin.tui.components.menu import (
    MenuItem, prompt_modern_menu, render_menu_lines
)
from nyxwin.tui.components.table import (
    render_key_value_grid, render_column_table
)
from nyxwin.tui.components.prompt import (
    prompt_text_input, prompt_destructive_confirmation
)
from nyxwin.tui.components.status import (
    render_progress_bar, render_status_badge, render_summary_card, render_diagnostic_panel
)

__all__ = [
    "render_frame", "render_panel", "render_header", "render_divider", "render_footer",
    "MenuItem", "prompt_modern_menu", "render_menu_lines",
    "render_key_value_grid", "render_column_table",
    "prompt_text_input", "prompt_destructive_confirmation",
    "render_progress_bar", "render_status_badge", "render_summary_card", "render_diagnostic_panel"
]

