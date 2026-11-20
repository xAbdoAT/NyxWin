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
    print(f"\n{Color.BOLD}nyx{Color.RESET}  {Color.GRAY}native ios builds on windows{Color.RESET}")

def log_info(msg: str):
    print(f"  {Color.GRAY}·{Color.RESET}     {msg}")

def log_success(msg: str):
    print(f"  {Color.GREEN}ok{Color.RESET}    {msg}")

def log_warning(msg: str):
    print(f"  {Color.YELLOW}wait{Color.RESET}  {msg}")

def log_error(msg: str):
    print(f"  {Color.RED}fail{Color.RESET}  {msg}", file=sys.stderr)

def log_step(step_num: int, total_steps: int, title: str):
    print(f"\n{Color.BOLD}{title}{Color.RESET}")
