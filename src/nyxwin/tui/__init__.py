from nyxwin.tui.terminal import print_header, prompt_input, wait_for_enter, clear_screen, read_key, transition_screen, copy_to_clipboard
from nyxwin.tui.menu import prompt_menu, prompt_boxed_menu, print_boxed_header

def run_interactive_menu(*args, **kwargs):
    from nyxwin.tui.screens.dashboard import run_interactive_menu as _run
    return _run(*args, **kwargs)
