"""
Centralized path resolution and filesystem safety layer for NyxWin.

Resolves application resources, user configurations, runtime data,
and handles legacy repository layout detection.
"""
import os
import sys
from pathlib import Path
from typing import Optional, Dict, Any

import re

# 1. Canonical Machine-Local Data Root (%LOCALAPPDATA%\NyxWin)
def get_nyxwin_data_root() -> Path:
    """
    Resolves the authoritative canonical machine-local data root for NyxWin.
    All runtime data (Build, Cache, Backups, Settings, Logs, Temp, SDKs) lives here.
    """
    env_override = os.environ.get("NYXWIN_DATA_DIR")
    if env_override:
        return Path(env_override).resolve()

    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        return (Path(localappdata) / "NyxWin").resolve()

    userprofile = os.environ.get("USERPROFILE", os.path.expanduser("~"))
    return (Path(userprofile) / ".nyxwin").resolve()

RUNTIME_DATA_DIR = get_nyxwin_data_root()

# 2. Canonical Sub-Directory Resolvers under %LOCALAPPDATA%\NyxWin\
def get_build_root() -> Path:
    """Returns the root directory for all project build intermediates."""
    return get_nyxwin_data_root() / "Build"

def get_cache_root() -> Path:
    """Returns the root directory for compiler module and object caches."""
    return get_nyxwin_data_root() / "Cache"

def get_backups_root() -> Path:
    """Returns the root directory for project recovery backups."""
    return get_nyxwin_data_root() / "Backups"

def get_settings_root() -> Path:
    """Returns the root directory for tool configuration and recent project settings."""
    return get_nyxwin_data_root() / "Settings"

def get_logs_root() -> Path:
    """Returns the root directory for diagnostic and operational logs."""
    return get_nyxwin_data_root() / "Logs"

def get_temp_root() -> Path:
    """Returns the root directory for NyxWin-managed disposable temporary work."""
    return get_nyxwin_data_root() / "Temp"

def get_sdks_root() -> Path:
    """Returns the root directory for managed iOS SDK installations."""
    return get_nyxwin_data_root() / "SDKs"

def get_app_install_root() -> Path:
    """Returns the managed installation directory for the NyxWin application engine (%LOCALAPPDATA%\\NyxWin\\app)."""
    return get_nyxwin_data_root() / "app"

def get_bin_root() -> Path:
    """Returns the directory for global CLI launcher shims (%LOCALAPPDATA%\\NyxWin\\bin)."""
    return get_nyxwin_data_root() / "bin"

def get_project_build_dir(project_name: str, project_id: str) -> Path:
    """Returns the isolated build directory for a specific project: Build/<safe-name>-<id>/"""
    safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', project_name)
    return get_build_root() / f"{safe_name}-{project_id}"

def resolve_project_build_dir(
    project_dir: Path,
    config: Optional[Dict[str, Any]] = None,
    project_id: Optional[str] = None
) -> Path:
    """
    Authoritative canonical resolver for project build intermediate directories.
    Consistently resolves: %LOCALAPPDATA%\\NyxWin\\Build\\<safe_name>-<project_id>\\
    - Uses Name from configuration if present and non-empty.
    - Falls back to project_dir.name if display name is absent.
    - Resolves or generates stable project_id from Config/.nyxproject.
    """
    from nyxwin.core.project import find_project_config_file, load_project_config, get_or_create_project_id

    p_dir = Path(project_dir).resolve()
    cfg = config
    if cfg is None:
        cfg_file, _ = find_project_config_file(p_dir)
        cfg = load_project_config(cfg_file) if cfg_file else {}

    cfg_dict = cfg if isinstance(cfg, dict) else {}
    raw_name = (
        cfg_dict.get("Name")
        or cfg_dict.get("CFBundleDisplayName")
        or cfg_dict.get("CFBundleName")
        or cfg_dict.get("CFBundleExecutable")
        or p_dir.name
    )
    name_str = str(raw_name).strip() if raw_name else p_dir.name
    if not name_str:
        name_str = p_dir.name

    p_id = project_id
    if not p_id:
        p_id = get_or_create_project_id(p_dir, cfg_dict)

    return get_project_build_dir(name_str, p_id)

def get_project_cache_dir(project_id: str) -> Path:
    """Returns the compiler cache directory for a specific project: Cache/<id>/"""
    return get_cache_root() / project_id

def get_project_backups_dir(project_name: str, project_id: str) -> Path:
    """Returns the backup storage directory for a specific project: Backups/<safe-name>-<id>/"""
    safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', project_name)
    return get_backups_root() / f"{safe_name}-{project_id}"

def get_recent_projects_file() -> Path:
    """Returns path to the recent projects registry file in Settings/."""
    return get_settings_root() / "recent_projects.json"

RECENT_PROJECTS_FILE = get_recent_projects_file()

# 3. User-level configuration directory (%APPDATA%\NyxWin, with ~/.nyxwin fallback)
def _resolve_config_dir() -> Path:
    env_override = os.environ.get("NYXWIN_CONFIG_DIR")
    if env_override:
        return Path(env_override).resolve()

    appdata = os.environ.get("APPDATA")
    if appdata:
        cand = Path(appdata) / "NyxWin"
        return cand.resolve()

    return (Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / ".nyxwin").resolve()

USER_CONFIG_DIR = _resolve_config_dir()
GLOBAL_CONFIG_DIR = (Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / ".nyxwin").resolve()

# 3. Default user projects directory (%USERPROFILE%\NyxProjects)
def _resolve_projects_dir() -> Path:
    env_override = os.environ.get("NYXWIN_PROJECTS_DIR")
    if env_override:
        return Path(env_override).resolve()

    userprofile = os.environ.get("USERPROFILE", os.path.expanduser("~"))
    return (Path(userprofile) / "NyxProjects").resolve()

DEFAULT_PROJECTS_DIR = _resolve_projects_dir()

# 4. Workspaces configuration file resolution
def get_workspaces_config_file() -> Path:
    env_override = os.environ.get("NYXWIN_WORKSPACES_FILE")
    if env_override:
        return Path(env_override).resolve()

    primary = USER_CONFIG_DIR / "workspaces.json"
    legacy = GLOBAL_CONFIG_DIR / "workspaces.json"

    if primary.is_file():
        return primary
    if legacy.is_file():
        return legacy
    return primary

WORKSPACES_CONFIG_FILE = get_workspaces_config_file()

def ensure_user_config_dir() -> Path:
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return USER_CONFIG_DIR

def ensure_global_config_dir() -> Path:
    GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return GLOBAL_CONFIG_DIR

def get_package_root() -> Path:
    """
    Returns the root directory of the NyxWin source checkout or installed package.
    """
    # 1. Check if running from repository checkout (has pyproject.toml and nyx.bat or main.py)
    repo_cand = Path(__file__).resolve().parents[3]
    if (repo_cand / "pyproject.toml").is_file() and ((repo_cand / "nyx.bat").is_file() or (repo_cand / "main.py").is_file()):
        return repo_cand

    # 2. Check if running from package root (src/nyxwin or site-packages/nyxwin)
    pkg_cand = Path(__file__).resolve().parents[1]
    return pkg_cand

def get_templates_dir() -> Path:
    """Resolves templates directory using importlib.resources or package directory."""
    # 1. Supported standard resource access via importlib.resources
    try:
        from importlib.resources import files
        res_cand = Path(str(files("nyxwin").joinpath("resources", "templates")))
        if res_cand.is_dir():
            return res_cand
    except Exception:
        pass

    # 2. Direct package resources path
    pkg_res = Path(__file__).resolve().parents[1] / "resources" / "templates"
    if pkg_res.is_dir():
        return pkg_res

    # 3. Development root fallback
    root = get_package_root()
    cand = root / "templates"
    if cand.is_dir():
        return cand

    return pkg_res

def get_tools_dir() -> Path:
    """Resolves tools directory containing ldid.exe, patch_macho.py, platform_check.c, libclang_rt.ios.a."""
    # 1. Supported standard resource access via importlib.resources
    try:
        from importlib.resources import files
        res_cand = Path(str(files("nyxwin").joinpath("resources", "tools")))
        if res_cand.is_dir():
            return res_cand
    except Exception:
        pass

    # 2. Direct package resources path
    pkg_res = Path(__file__).resolve().parents[1] / "resources" / "tools"
    if pkg_res.is_dir():
        return pkg_res

    # 3. Development root fallback
    root = get_package_root()
    cand = root / "tools"
    if cand.is_dir():
        return cand

    return pkg_res

def get_sdk_root(workspace_dir: Optional[Path] = None) -> Path:
    """
    Resolves managed or fallback iOS SDK directory.
    Precedence:
      1. Environment override (NYXWIN_SDK_DIR)
      2. Canonical managed SDKs directory (%LOCALAPPDATA%\\NyxWin\\SDKs) if populated
      3. Explicit project-local override (workspace_dir / "sdk") if populated with valid iPhoneOS*.sdk
      4. Development repository fallback (root / "sdk") if populated
      5. System-wide fallback (%SystemDrive%\\iOS_SDK)
      6. Canonical managed SDKs root (default return)
    """
    env_override = os.environ.get("NYXWIN_SDK_DIR")
    if env_override:
        return Path(env_override).resolve()

    canonical_sdks = get_sdks_root()
    if canonical_sdks.is_dir() and any(canonical_sdks.glob("iPhoneOS*.sdk")):
        return canonical_sdks

    if workspace_dir:
        ws_sdk = Path(workspace_dir) / "sdk"
        if ws_sdk.is_dir() and any(ws_sdk.glob("iPhoneOS*.sdk")):
            return ws_sdk

    root = get_package_root()
    repo_sdk = root / "sdk"
    if repo_sdk.is_dir() and any(repo_sdk.glob("iPhoneOS*.sdk")):
        return repo_sdk

    # Check active workspace/project from config
    try:
        cfg_file = get_workspaces_config_file()
        if cfg_file.is_file():
            import json
            with open(cfg_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                act = cfg.get("active_workspace") or cfg.get("active_project")
                if act and (Path(act) / "sdk").is_dir() and any((Path(act) / "sdk").glob("iPhoneOS*.sdk")):
                    return (Path(act) / "sdk").resolve()
    except Exception:
        pass

    # System-level fallback location if present (e.g. %SystemDrive%\\iOS_SDK)
    sys_drive = os.environ.get("SystemDrive", "C:")
    sys_sdk = Path(f"{sys_drive}\\iOS_SDK")
    if sys_sdk.is_dir() and any(sys_sdk.glob("iPhoneOS*.sdk")):
        return sys_sdk

    return canonical_sdks

def detect_legacy_paths(root: Optional[Path] = None) -> Dict[str, Path]:
    """
    Detects if legacy runtime directories (Projects, Cache, Output, Backups, sdk)
    exist beside the source code or in root.
    """
    target = root or get_package_root()
    detected = {}
    for name in ["Projects", "Cache", "Output", "Backups", "sdk"]:
        folder = target / name
        if folder.is_dir():
            detected[name] = folder.resolve()
    return detected

def is_safe_subpath(target_path: Path, base_dir: Path) -> bool:
    """
    Security check: Verifies that target_path resolves strictly within base_dir,
    preventing path traversal attacks (e.g. '../..').
    """
    try:
        resolved_target = target_path.resolve()
        resolved_base = base_dir.resolve()
        return resolved_target == resolved_base or resolved_base in resolved_target.parents
    except Exception:
        return False
