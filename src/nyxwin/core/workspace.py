import os
import sys
import json
import shutil
from pathlib import Path
from typing import Optional, List, Dict

from nyxwin.config.paths import (
    GLOBAL_CONFIG_DIR,
    WORKSPACES_CONFIG_FILE,
    RECENT_PROJECTS_FILE,
    ensure_global_config_dir,
    get_project_build_dir,
    resolve_project_build_dir,
    get_project_cache_dir,
    get_project_backups_dir,
    get_recent_projects_file,
    get_settings_root,
)
from nyxwin.core.project import find_project_config_file, get_or_create_project_id, load_project_config

class ProjectContext:
    """
    Represents an active standalone NyxWin project.
    Every project is a standalone directory containing Config/Project.plist or Project.plist.
    Intermediates, compiler caches, and backups are stored externally under %LOCALAPPDATA%\\NyxWin.
    Deliverables are placed strictly in <ProjectDir>/dist/.
    """
    def __init__(self, path: Path, kind: str = "single"):
        self.path = path.resolve()
        self.kind = "single"  # NyxWin strictly operates in single-app mode
        self.dist_dir = self.path / "dist"
        self.output_dir = self.dist_dir  # Compatibility alias
        os.makedirs(self.dist_dir, exist_ok=True)

    @property
    def config_file(self) -> Optional[Path]:
        """Resolves the primary Project.plist configuration file."""
        cfg_p, _ = find_project_config_file(self.path)
        return cfg_p

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def project_id(self) -> str:
        """Stable project UUID from Config/.nyxproject."""
        try:
            cfg_p = self.config_file
            cfg = load_project_config(cfg_p) if cfg_p else {}
            return get_or_create_project_id(self.path, cfg or {})
        except Exception:
            return "unknown-id"

    @property
    def build_dir(self) -> Path:
        """Canonical external build intermediate directory."""
        cfg_p = self.config_file
        cfg = load_project_config(cfg_p) if cfg_p else {}
        d = resolve_project_build_dir(self.path, config=cfg, project_id=self.project_id)
        os.makedirs(d, exist_ok=True)
        return d

    @property
    def cache_dir(self) -> Path:
        """Canonical external compiler cache directory."""
        d = get_project_cache_dir(self.project_id)
        os.makedirs(d, exist_ok=True)
        return d

    @property
    def backups_dir(self) -> Path:
        """Canonical external backups directory."""
        d = get_project_backups_dir(self.name, self.project_id)
        os.makedirs(d, exist_ok=True)
        return d

    @property
    def projects_dir(self) -> Path:
        """Deprecated compatibility property: returns Projects/ if local directory exists, else parent."""
        local_p = self.path / "Projects"
        if local_p.is_dir():
            return local_p
        return self.path.parent

    def get_projects(self) -> List[Path]:
        """Returns valid project directory for this project context (strictly single-app)."""
        cfg_p = self.config_file
        if cfg_p is not None:
            return [self.path]
        return [self.path]

    def get_project_dir(self, name: str) -> Optional[Path]:
        """Resolves a project directory within or relative to this project (with legacy Projects/ fallback)."""
        if not name or name in (".", "", self.path.name):
            return self.path
        if name.lower() == self.path.name.lower():
            return self.path

        # 1. Direct child directory
        cand = self.path / name
        if cand.is_dir():
            return cand

        # 2. Inside Projects/ subdirectory if present (legacy compatibility)
        if (self.path / "Projects").is_dir():
            cand_p = self.path / "Projects" / name
            if cand_p.is_dir():
                return cand_p

        # 3. Path as given
        try:
            cand_path = Path(name).resolve()
            if cand_path.is_dir():
                return cand_path
        except Exception:
            pass

        return None

# Compatibility aliases
Project = ProjectContext
Workspace = ProjectContext

# --- Global Config & History Management ---
def load_settings() -> dict:
    """Loads recent projects and active project configuration without creating legacy directories."""
    # 1. Try modern canonical settings file
    recents_file = get_recent_projects_file()
    if recents_file.is_file():
        try:
            with open(recents_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "active_workspace" in data and "active_project" not in data:
                    data["active_project"] = data["active_workspace"]
                if "recent_workspaces" in data and "recent_projects" not in data:
                    data["recent_projects"] = data["recent_workspaces"]
                return data
        except Exception:
            pass

    # 2. Check legacy ~/.nyxwin/workspaces.json for automatic migration
    legacy_file = Path.home() / ".nyxwin" / "workspaces.json"
    if legacy_file.is_file():
        try:
            with open(legacy_file, "r", encoding="utf-8") as f:
                legacy_data = json.load(f)
            migrated = {
                "active_project": legacy_data.get("active_workspace"),
                "recent_projects": legacy_data.get("recent_workspaces", [])
            }
            save_settings(migrated)
            return migrated
        except Exception:
            pass

    return {"active_project": None, "recent_projects": [], "active_workspace": None, "recent_workspaces": []}

def save_settings(cfg: dict):
    """Saves recent projects and active project configuration."""
    recents_file = get_recent_projects_file()
    recents_file.parent.mkdir(parents=True, exist_ok=True)
    if "active_project" in cfg:
        cfg["active_workspace"] = cfg["active_project"]
    elif "active_workspace" in cfg:
        cfg["active_project"] = cfg["active_workspace"]

    if "recent_projects" in cfg:
        cfg["recent_workspaces"] = cfg["recent_projects"]
    elif "recent_workspaces" in cfg:
        cfg["recent_projects"] = cfg["recent_workspaces"]

    try:
        with open(recents_file, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"[!] Warning: Failed to save project history: {e}", file=sys.stderr)

# Compatibility aliases
load_workspace_config = load_settings
save_workspace_config = save_settings

def get_recent_projects(prune_missing: bool = False) -> List[str]:
    """
    Returns list of recently accessed project paths.
    If prune_missing is True, non-existent directories are purged from history.
    If False, all recorded paths are returned so the UI can identify stale entries.
    """
    cfg = load_settings()
    recents = cfg.get("recent_projects") or cfg.get("recent_workspaces", [])
    if not prune_missing:
        return list(recents)

    valid = []
    for r in recents:
        p = Path(r)
        if p.is_dir():
            valid.append(str(p.resolve()))
    if len(valid) != len(recents):
        cfg["recent_projects"] = valid
        cfg["recent_workspaces"] = valid
        save_settings(cfg)
    return valid

def prune_stale_recent_projects() -> int:
    """
    Removes non-existent directories from recent project history without deleting any filesystem data.
    Returns the count of pruned stale paths.
    """
    cfg = load_settings()
    recents = cfg.get("recent_projects") or cfg.get("recent_workspaces", [])
    valid = [r for r in recents if Path(r).is_dir()]
    pruned_count = len(recents) - len(valid)
    if pruned_count > 0:
        cfg["recent_projects"] = valid
        cfg["recent_workspaces"] = valid
        save_settings(cfg)
    return pruned_count

def remove_recent_project(path: Path) -> bool:
    """Removes a specific project path from recent project history without deleting filesystem data."""
    try:
        path_str = str(path.resolve())
    except Exception:
        path_str = str(path)
    cfg = load_settings()
    recents = list(cfg.get("recent_projects") or cfg.get("recent_workspaces", []))
    if path_str in recents:
        recents.remove(path_str)
        cfg["recent_projects"] = recents
        cfg["recent_workspaces"] = recents
        if cfg.get("active_project") == path_str:
            cfg["active_project"] = None
            cfg["active_workspace"] = None
        save_settings(cfg)
        return True
    return False

def add_recent_project(path: Path):
    """Adds a project path to the recent projects history."""
    try:
        path_str = str(path.resolve())
    except Exception:
        path_str = str(path)
    cfg = load_settings()
    recents = list(cfg.get("recent_projects") or cfg.get("recent_workspaces", []))
    if path_str in recents:
        recents.remove(path_str)
    recents.insert(0, path_str)
    cfg["recent_projects"] = recents[:20]
    cfg["active_project"] = path_str
    cfg["recent_workspaces"] = cfg["recent_projects"]
    cfg["active_workspace"] = path_str
    save_settings(cfg)

def set_active_project(path: Path):
    add_recent_project(path)

# Backwards compatibility aliases
get_recent_workspaces = get_recent_projects
add_recent_workspace = add_recent_project
set_active_workspace = set_active_project

# --- Project Detection & Initialization ---
def detect_project(target_path: Path) -> Optional[ProjectContext]:
    """
    Detects if a directory or any of its parents is a standalone NyxWin project.
    Resolution Order:
      1. Check target_path for Config/Project.plist or Project.plist directly.
      2. Check parent directories of target_path (in case invoked from a subfolder like Sources/).
      3. Never scans sibling projects or multi-app studio workspaces.
    """
    curr = target_path.resolve()

    # 1. Direct standalone project check on curr
    cfg_file, _ = find_project_config_file(curr)
    if cfg_file is not None:
        return ProjectContext(curr)

    # 2. Check upward in parent tree
    for parent in curr.parents:
        cfg_file, _ = find_project_config_file(parent)
        if cfg_file is not None:
            return ProjectContext(parent)

    return None

def init_project(target_path: Path, kind: str = "single") -> ProjectContext:
    """
    Initializes a new standalone NyxWin project.
    No .nyxworkspace marker is written; creates the directory and registers recent project.
    """
    target_path = target_path.resolve()
    os.makedirs(target_path, exist_ok=True)

    proj = ProjectContext(target_path, kind="single")
    add_recent_project(target_path)
    return proj

# Compatibility aliases
detect_workspace = detect_project
init_workspace = init_project
