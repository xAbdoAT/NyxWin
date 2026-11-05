"""
Configuration package for NyxWin.
"""
from nyxwin.config.paths import (
    USER_CONFIG_DIR,
    RUNTIME_DATA_DIR,
    DEFAULT_PROJECTS_DIR,
    WORKSPACES_CONFIG_FILE,
    GLOBAL_CONFIG_DIR,
    get_package_root,
    get_templates_dir,
    get_tools_dir,
    get_sdk_root,
    resolve_project_build_dir,
    is_safe_subpath,
    detect_legacy_paths,
)

__all__ = [
    "USER_CONFIG_DIR",
    "RUNTIME_DATA_DIR",
    "DEFAULT_PROJECTS_DIR",
    "WORKSPACES_CONFIG_FILE",
    "GLOBAL_CONFIG_DIR",
    "get_package_root",
    "get_templates_dir",
    "get_tools_dir",
    "get_sdk_root",
    "resolve_project_build_dir",
    "is_safe_subpath",
    "detect_legacy_paths",
]
