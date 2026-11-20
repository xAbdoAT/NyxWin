"""
NyxWin Theme and Terminal Capability System.
Provides semantic color tokens, capability detection (TrueColor, 256-color, 16-color,
no-color, ASCII), text formatting, visible width calculations, and symbol tables.
"""

import os
import re
import sys
from typing import Tuple, Dict, Any, Optional

# Semantic RGB Palette Tokens
PALETTE_RGB = {
    "GRAPHITE": (11, 14, 20),      # #0B0E14 - Foundation
    "SLATE_DEEP": (21, 27, 39),    # #151B27 - Panel base
    "SLATE_GRAY": (48, 57, 74),    # #30394A - Frame borders
    "WHITE_SOFT": (231, 237, 245), # #E7EDF5 - Primary text
    "GRAY_MUTED": (139, 149, 167), # #8B95A7 - Descriptions, pending
    "CYAN_ELEC": (70, 217, 255),   # #46D9FF - Cursor, selection focus
    "BLUE_AZURE": (87, 155, 255),  # #579BFF - Headers, navigation
    "VIOLET": (146, 133, 255),     # #9285FF - Highlights, metadata
    "TEAL": (67, 214, 189),        # #43D6BD - Progress spinners, activity
    "EMERALD": (77, 215, 138),     # #4DD78A - Success, verified
    "AMBER": (244, 199, 106),      # #F4C76A - Warnings, caution
    "CORAL_RED": (255, 101, 122),  # #FF657A - Errors, danger
}

# 256-Color Approximation Map (ANSI color numbers)
PALETTE_256 = {
    "GRAPHITE": 233,
    "SLATE_DEEP": 234,
    "SLATE_GRAY": 237,
    "WHITE_SOFT": 255,
    "GRAY_MUTED": 246,
    "CYAN_ELEC": 81,
    "BLUE_AZURE": 75,
    "VIOLET": 141,
    "TEAL": 43,
    "EMERALD": 78,
    "AMBER": 221,
    "CORAL_RED": 204,
}

# 16-Color Standard ANSI Map
PALETTE_16 = {
    "GRAPHITE": "\033[30m",
    "SLATE_DEEP": "\033[30m",
    "SLATE_GRAY": "\033[90m",
    "WHITE_SOFT": "\033[97m",
    "GRAY_MUTED": "\033[37m",
    "CYAN_ELEC": "\033[96m",
    "BLUE_AZURE": "\033[94m",
    "VIOLET": "\033[95m",
    "TEAL": "\033[36m",
    "EMERALD": "\033[92m",
    "AMBER": "\033[93m",
    "CORAL_RED": "\033[91m",
}

RESET_CODE = "\033[0m"
BOLD_CODE = "\033[1m"
DIM_CODE = "\033[2m"

# Semantic color aliases — legacy/shorthand names resolve to palette tokens
COLOR_ALIASES: Dict[str, str] = {
    "GREEN": "EMERALD",
    "RED": "CORAL_RED",
    "YELLOW": "AMBER",
    "CYAN": "CYAN_ELEC",
    "WHITE": "WHITE_SOFT",
    "GRAY": "GRAY_MUTED",
    "GREY": "GRAY_MUTED",
    "BLUE": "BLUE_AZURE",
    "PURPLE": "VIOLET",
    "MAGENTA": "VIOLET",
}

class TerminalCapabilities:
    """Detects and stores current terminal capabilities."""
    def __init__(self):
        self.is_interactive = self._check_interactive()
        self.has_color = self._check_color()
        self.truecolor = self._check_truecolor()
        self.color_256 = self._check_256color()
        self.unicode_supported = self._check_unicode()

    def _check_interactive(self) -> bool:
        if os.environ.get("NYXWIN_NON_INTERACTIVE") == "1":
            return False
        return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    def _check_color(self) -> bool:
        if os.environ.get("NO_COLOR"):
            return False
        if os.environ.get("NYXWIN_NON_INTERACTIVE") == "1":
            return False
        if not self._check_interactive():
            return False
        return True

    def _check_truecolor(self) -> bool:
        if not self.has_color:
            return False
        colorterm = os.environ.get("COLORTERM", "").lower()
        if colorterm in ("truecolor", "24bit"):
            return True
        # Windows Terminal (WT_SESSION) supports full 24-bit TrueColor
        if "WT_SESSION" in os.environ:
            return True
        # Modern VSCode terminal
        if os.environ.get("TERM_PROGRAM") == "vscode":
            return True
        return False

    def _check_256color(self) -> bool:
        if not self.has_color:
            return False
        term = os.environ.get("TERM", "").lower()
        return "256color" in term or self.truecolor or "WT_SESSION" in os.environ

    def _check_unicode(self) -> bool:
        # Check standard encoding
        encoding = getattr(sys.stdout, "encoding", "") or ""
        if encoding.lower().replace("-", "") in ("utf8", "utf16", "utf32"):
            return True
        # Windows terminal and VS Code are UTF-8 capable
        if "WT_SESSION" in os.environ or os.environ.get("TERM_PROGRAM") == "vscode":
            return True
        return True  # Default to True with UTF-8 reconfigure active

# Global capabilities instance (lazy/re-evaluable)
_CAPS: Optional[TerminalCapabilities] = None

def get_capabilities() -> TerminalCapabilities:
    global _CAPS
    if _CAPS is None:
        _CAPS = TerminalCapabilities()
    return _CAPS

def set_capabilities(caps: TerminalCapabilities):
    global _CAPS
    _CAPS = caps

def fg(color_key: str, text: str) -> str:
    """Applies foreground semantic color to text based on terminal capability."""
    caps = get_capabilities()
    if not caps.has_color:
        return text

    key = COLOR_ALIASES.get(color_key.upper(), color_key.upper())

    if caps.truecolor and key in PALETTE_RGB:
        r, g, b = PALETTE_RGB[key]
        return f"\033[38;2;{r};{g};{b}m{text}{RESET_CODE}"
    elif caps.color_256 and key in PALETTE_256:
        code_256 = PALETTE_256[key]
        return f"\033[38;5;{code_256}m{text}{RESET_CODE}"
    elif key in PALETTE_16:
        return f"{PALETTE_16[key]}{text}{RESET_CODE}"
    return text

def fg_rgb(r: int, g: int, b: int, text: str) -> str:
    """Applies direct RGB foreground color if truecolor is supported."""
    caps = get_capabilities()
    if not caps.has_color:
        return text
    if caps.truecolor:
        return f"\033[38;2;{r};{g};{b}m{text}{RESET_CODE}"
    return text

def bold(text: str) -> str:
    caps = get_capabilities()
    if not caps.has_color:
        return text
    return f"{BOLD_CODE}{text}{RESET_CODE}"

def dim(text: str) -> str:
    caps = get_capabilities()
    if not caps.has_color:
        return text
    return f"{DIM_CODE}{text}{RESET_CODE}"

def strip_ansi(s: str) -> str:
    """Removes all ANSI escape sequences from a string."""
    return re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', s)

def visible_length(s: str) -> int:
    """Returns the visible width of a string in terminal cells."""
    return len(strip_ansi(s))

def truncate_visible(s: str, max_width: int, ellipsis: str = "...") -> str:
    """Truncates string to maximum visible length, preserving ANSI reset if colored."""
    plain = strip_ansi(s)
    if len(plain) <= max_width:
        return s
    # Middle truncation if long path
    if "/" in plain or "\\" in plain:
        target_len = max(max_width - len(ellipsis), 4)
        half = target_len // 2
        return plain[:half] + ellipsis + plain[-half:]
    target_len = max(max_width - len(ellipsis), 1)
    return plain[:target_len] + ellipsis

def pad_visible(s: str, target_width: int, align: str = "left") -> str:
    """Pads string to target visible width, accounting for ANSI escapes."""
    vlen = visible_length(s)
    needed = max(0, target_width - vlen)
    if needed == 0:
        return s
    if align == "left":
        return s + (" " * needed)
    elif align == "right":
        return (" " * needed) + s
    elif align == "center":
        left_pad = needed // 2
        right_pad = needed - left_pad
        return (" " * left_pad) + s + (" " * right_pad)
    return s

# Unicode vs ASCII Symbols
SYMBOLS_UNICODE = {
    "CURSOR": "›",
    "CHECK": "✓",
    "SPINNER": "⠋",
    "BULLET_ACTIVE": "◉",
    "BULLET_PENDING": "○",
    "WARN": "⚠",
    "FAIL": "✕",
    "BREADCRUMB": "›",
    "STAR": "★",
    "FOLDER": "▪",
    # Rounded box elements
    "BOX_TL": "╭",
    "BOX_TR": "╮",
    "BOX_BL": "╰",
    "BOX_BR": "╯",
    "BOX_H": "─",
    "BOX_V": "│",
    "BOX_T_DOWN": "┬",
    "BOX_T_UP": "┴",
    "BOX_T_RIGHT": "├",
    "BOX_T_LEFT": "┤",
    "BOX_CROSS": "┼",
    "BAR_FILLED": "█",
    "BAR_UNFILLED": "░",
}

SYMBOLS_ASCII = {
    "CURSOR": ">",
    "CHECK": "OK",
    "SPINNER": "*",
    "BULLET_ACTIVE": "*",
    "BULLET_PENDING": "-",
    "WARN": "!",
    "FAIL": "X",
    "BREADCRUMB": ">",
    "STAR": "*",
    "FOLDER": "+",
    # ASCII box elements
    "BOX_TL": "+",
    "BOX_TR": "+",
    "BOX_BL": "+",
    "BOX_BR": "+",
    "BOX_H": "-",
    "BOX_V": "|",
    "BOX_T_DOWN": "+",
    "BOX_T_UP": "+",
    "BOX_T_RIGHT": "+",
    "BOX_T_LEFT": "+",
    "BOX_CROSS": "+",
    "BAR_FILLED": "#",
    "BAR_UNFILLED": "-",
}

def symbol(key: str) -> str:
    """Returns the appropriate Unicode or ASCII symbol based on terminal capabilities."""
    caps = get_capabilities()
    table = SYMBOLS_UNICODE if caps.unicode_supported else SYMBOLS_ASCII
    return table.get(key, "")

