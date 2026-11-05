import os
import sys
import shutil
import atexit
import signal
from typing import Tuple, Optional

from nyxwin.core.models import Color

# Ensure UTF-8 output on Windows consoles (prevents cp1256/charmap encode crashes)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Check msvcrt on Windows
try:
    import msvcrt
except ImportError:
    msvcrt = None

# Enable Windows Virtual Terminal Processing (VT100 / ANSI escape support)
def _enable_virtual_terminal_processing() -> bool:
    if os.name != "nt":
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # STD_OUTPUT_HANDLE = -11, STD_ERROR_HANDLE = -12
        for handle_id in (-11, -12):
            handle = kernel32.GetStdHandle(handle_id)
            if handle and handle != -1:
                mode = ctypes.c_uint32()
                if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                    kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        return True
    except Exception:
        return False

_enable_virtual_terminal_processing()

# Best-Effort Cursor Restoration and Signal Handling
_cursor_hidden = False

def hide_cursor():
    """Hides the terminal cursor during active animations/live rendering."""
    global _cursor_hidden
    if os.environ.get("NYXWIN_NON_INTERACTIVE") == "1":
        return
    if not _cursor_hidden and hasattr(sys.stderr, "write"):
        try:
            sys.stderr.write("\033[?25l")
            sys.stderr.flush()
            _cursor_hidden = True
        except Exception:
            pass

def restore_cursor():
    """Restores the terminal cursor visibility (best-effort on exit or interrupt)."""
    global _cursor_hidden
    if hasattr(sys.stderr, "write"):
        try:
            sys.stderr.write("\033[?25h")
            sys.stderr.flush()
            _cursor_hidden = False
        except Exception:
            pass

atexit.register(restore_cursor)

def _sigint_handler(signum, frame):
    restore_cursor()
    if callable(_orig_sigint_handler) and _orig_sigint_handler != _sigint_handler:
        _orig_sigint_handler(signum, frame)
    else:
        sys.exit(130)

try:
    _orig_sigint_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, _sigint_handler)
except Exception:
    _orig_sigint_handler = None

def transition_screen():
    """
    Transitions to a new full-screen interactive TUI page by clearing the visible
    terminal viewport and moving the cursor to home (1, 1), without erasing scrollback history.
    No-op if non-interactive, redirected, or NYXWIN_NON_INTERACTIVE=1.
    """
    if os.environ.get("NYXWIN_NON_INTERACTIVE") == "1":
        return
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return
    try:
        # CSI 2J clears the visible viewport. CSI H repositions cursor to (1, 1).
        # CSI 3J is explicitly avoided to preserve terminal scrollback.
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()
    except Exception:
        pass

def clear_screen(force_cls: bool = False):
    """
    Clears the visible viewport and repositions cursor to home without clearing scrollback.
    Maintains compatibility with existing callers while guaranteeing scrollback preservation.
    """
    transition_screen()

def copy_to_clipboard(text: str) -> bool:
    """
    Safely copies plain text to the system clipboard without shell=True or third-party packages.
    On Windows, pipes UTF-16LE text directly to clip.exe.
    Returns True on success, False on failure.
    """
    if not text:
        return False
    try:
        import subprocess
        if os.name == "nt":
            creation_flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            proc = subprocess.run(
                ["clip.exe"],
                input=text.encode("utf-16le"),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                creationflags=creation_flags
            )
            return proc.returncode == 0
        else:
            proc = subprocess.run(
                ["pbcopy"],
                input=text.encode("utf-8"),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True
            )
            return proc.returncode == 0
    except Exception:
        return False

def reposition_cursor(row: int = 1, col: int = 1):
    """Repositions cursor to specific 1-based row and column."""
    if os.environ.get("NYXWIN_NON_INTERACTIVE") == "1":
        return
    try:
        sys.stdout.write(f"\033[{row};{col}H")
        sys.stdout.flush()
    except Exception:
        pass

def move_cursor_up(lines: int = 1):
    """Moves cursor up N lines."""
    if lines <= 0 or os.environ.get("NYXWIN_NON_INTERACTIVE") == "1":
        return
    try:
        sys.stdout.write(f"\033[{lines}A")
        sys.stdout.flush()
    except Exception:
        pass

def clear_line():
    """Clears current line and repositions carriage to column 0."""
    if os.environ.get("NYXWIN_NON_INTERACTIVE") == "1":
        return
    try:
        sys.stdout.write("\033[2K\r")
        sys.stdout.flush()
    except Exception:
        pass

def get_terminal_dimensions() -> Tuple[int, int]:
    """Returns actual (columns, rows) of console."""
    try:
        size = shutil.get_terminal_size((80, 24))
        return size.columns, size.lines
    except Exception:
        return 80, 24

def get_terminal_width() -> int:
    """Returns responsive panel width clamped to standard tiers (74, 92, 112)."""
    try:
        cols, _ = get_terminal_dimensions()
        if cols >= 120:
            return 112
        elif cols >= 100:
            return 92
        elif cols >= 80:
            return 74
        return max(56, cols - 4)
    except Exception:
        return 74

def print_header(breadcrumb: str = ""):
    """Prints the application banner header with breadcrumb navigation using rounded panels."""
    clear_screen(force_cls=False)
    w = get_terminal_width()

    from nyxwin.tui.components.frame import render_panel
    title = breadcrumb if breadcrumb else "NYXWIN › WORKSPACE"
    header_box = render_panel(
        title=title,
        content_lines=["  Native Apple-Platform Toolchain & Project Builder for Windows"],
        badge="DEV WORKSPACE",
        width=w,
        border_color="SLATE_GRAY",
        title_color="BLUE_AZURE",
        badge_color="VIOLET"
    )
    print(header_box)
    print()

def read_key() -> str:
    """
    Reads a single keypress in Windows console without waiting for Enter.
    Returns: 'UP', 'DOWN', 'ENTER', 'ESC', 'BACKSPACE', or char.
    """
    if os.environ.get("NYXWIN_NON_INTERACTIVE") == "1":
        return "ESC"

    if not msvcrt or (hasattr(sys.stdin, "isatty") and not sys.stdin.isatty()):
        ch = sys.stdin.read(1)
        if not ch or ch in ("\x1b", "q", "Q", "\x03", "\x04"):
            return "ESC"
        if ch in ("\r", "\n"):
            return "ENTER"
        return ch

    ch = msvcrt.getwch()
    if ch in ("\x00", "\xe0"):
        ch2 = msvcrt.getwch()
        if ch2 == "H":
            return "UP"
        elif ch2 == "P":
            return "DOWN"
        elif ch2 == "K":
            return "LEFT"
        elif ch2 == "M":
            return "RIGHT"
        elif ch2 == "G":
            return "HOME"
        elif ch2 == "O":
            return "END"
        return "SPECIAL"
    elif ch in ("\r", "\n"):
        return "ENTER"
    elif ch == "\x1b":
        return "ESC"
    elif ch in ("\x08", "\x7f"):
        return "BACKSPACE"
    return ch

def prompt_input(prompt_text: str, default_value: str = "") -> str:
    """Prompts user for text input with optional default value."""
    if default_value:
        display_prompt = f"{Color.BOLD}{prompt_text}{Color.RESET} [{Color.CYAN}{default_value}{Color.RESET}]: "
    else:
        display_prompt = f"{Color.BOLD}{prompt_text}{Color.RESET}: "

    try:
        val = input(display_prompt).strip()
        return val if val else default_value
    except (KeyboardInterrupt, EOFError):
        print()
        return default_value

def wait_for_enter(prompt: str = "Press [Enter] to return to menu..."):
    """Waits for user to press Enter."""
    print(f"\n{Color.GRAY}{prompt}{Color.RESET}", end="", flush=True)
    try:
        if msvcrt:
            while True:
                k = read_key()
                if k in ("ENTER", "ESC"):
                    break
        else:
            input()
    except (KeyboardInterrupt, EOFError):
        pass
    print()
