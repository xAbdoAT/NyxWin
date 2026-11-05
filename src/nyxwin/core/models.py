import sys

class Color:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    GRAY = "\033[90m"

def print_banner():
    banner = f"""{Color.CYAN}
======================================================================
  _   _             __        ___
 | \\ | |_   ___  __ \\ \\      / (_)_ __
 |  \\| | | | \\ \\/ /  \\ \\ /\\ / /| | '_ \\
 | |\\  | |_| |>  <    \\ V  V / | | | | |
 |_| \\_|\\__, /_/\\_\\    \\_/\\_/  |_|_| |_|
        |___/
 Native iOS Toolchain & IPA Builder for Windows (No macOS / No WSL)
 Developed by Abdo AT (@xAbdoAT)
======================================================================
{Color.RESET}"""
    print(banner)

def log_info(msg: str):
    print(f"{Color.BLUE}[INFO]{Color.RESET} {msg}")

def log_success(msg: str):
    print(f"{Color.GREEN}[SUCCESS]{Color.RESET} {msg}")

def log_warning(msg: str):
    print(f"{Color.YELLOW}[WARNING]{Color.RESET} {msg}")

def log_error(msg: str):
    print(f"{Color.RED}[ERROR]{Color.RESET} {msg}", file=sys.stderr)

def log_step(step_num: int, total_steps: int, title: str):
    print(f"\n{Color.BOLD}{Color.CYAN}[Step {step_num}/{total_steps}] {title}{Color.RESET}")
