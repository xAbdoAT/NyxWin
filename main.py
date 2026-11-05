#!/usr/bin/env python3
"""
NyxWin — Native iOS Toolchain & IPA Builder for Windows.
Main CLI and TUI launcher.
Developed by Abdo AT (@xAbdoAT)
"""

import sys
from pathlib import Path

# Ensure src/ is on sys.path for direct script execution
_PKG_SRC = Path(__file__).resolve().parent / "src"
if str(_PKG_SRC) not in sys.path:
    sys.path.insert(0, str(_PKG_SRC))

# Re-export core primitives for script accessibility
from nyxwin.core.models import (
    Color,
    print_banner,
    log_info,
    log_success,
    log_warning,
    log_error,
)
from nyxwin.core.project import (
    load_project_config,
    save_project_config,
    find_project_config_file,
    expand_macro_variables,
)
from nyxwin.core.diagnostics import format_compiler_diagnostics
from nyxwin.core.toolchain import Toolchain
from nyxwin.core.workspace import (
    ProjectContext,
    Project,
    Workspace,
    detect_project,
    detect_workspace,
    init_project,
    init_workspace,
    load_settings,
    save_settings,
    load_workspace_config,
    save_workspace_config,
    get_recent_projects,
    add_recent_project,
    set_active_project,
)
from nyxwin.build.pipeline import build_project
from nyxwin.services.backup import (
    create_project_backup,
    list_project_backups,
    restore_project_backup,
)
from nyxwin.services.icon import generate_app_icons
from nyxwin.services.sdk_manager import (
    fetch_available_sdks,
    get_installed_sdks,
    install_sdk,
)
from nyxwin.tui.screens.dashboard import run_interactive_menu
from nyxwin.cli import (
    main,
    cmd_doctor,
    cmd_new,
    cmd_clean,
    cmd_clean_cache,
    cmd_clean_module_cache,
    cmd_setup_path,
)

# Compatibility alias
cmd_build = build_project

__all__ = [
    "Color",
    "print_banner",
    "log_info",
    "log_success",
    "log_warning",
    "log_error",
    "format_compiler_diagnostics",
    "load_project_config",
    "save_project_config",
    "find_project_config_file",
    "expand_macro_variables",
    "Toolchain",
    "ProjectContext",
    "Project",
    "Workspace",
    "detect_project",
    "detect_workspace",
    "init_project",
    "init_workspace",
    "load_settings",
    "save_settings",
    "load_workspace_config",
    "save_workspace_config",
    "get_recent_projects",
    "add_recent_project",
    "set_active_project",
    "build_project",
    "cmd_build",
    "cmd_doctor",
    "cmd_new",
    "cmd_clean",
    "cmd_clean_cache",
    "cmd_clean_module_cache",
    "cmd_setup_path",
    "create_project_backup",
    "list_project_backups",
    "restore_project_backup",
    "generate_app_icons",
    "fetch_available_sdks",
    "get_installed_sdks",
    "install_sdk",
    "run_interactive_menu",
    "main",
]

if __name__ == "__main__":
    main()
