import os
import sys
import shutil
import json
import plistlib
from pathlib import Path
from typing import Optional, List

from nyxwin.config.paths import (
    get_package_root,
    get_templates_dir,
    get_tools_dir,
    get_sdk_root,
    get_sdks_root
)
from nyxwin.config.paths import (
    get_build_root,
    get_cache_root,
    get_backups_root,
)
from nyxwin.core.project import find_project_config_file
from nyxwin.core.workspace import (
    ProjectContext,
    Workspace,
    detect_project,
    detect_workspace,
    init_project,
    init_workspace,
    load_settings,
    save_settings,
    add_recent_project,
    set_active_project,
    add_recent_workspace,
    set_active_workspace,
)

class Toolchain:
    def __init__(self, root_dir: Optional[Path] = None, workspace_dir: Optional[Path] = None):
        self._package_root = (root_dir if root_dir else get_package_root()).resolve()
        self.tools_dir = get_tools_dir()
        self.templates_dir = get_templates_dir()
        self.explicit_workspace = bool(workspace_dir)

        # Resolve ProjectContext (auto-detect CWD -> explicit workspace_dir)
        if workspace_dir:
            proj_cand = detect_project(Path(workspace_dir))
            self.project = proj_cand if proj_cand else ProjectContext(Path(workspace_dir))
        else:
            cwd_proj = detect_project(Path.cwd())
            if cwd_proj:
                self.project = cwd_proj
            else:
                self.project = None

        self.workspace = self.project  # Compatibility alias

        if self.project:
            # Never register toolchain/repository root as a user project
            if self.project.path.resolve() != self.package_root.resolve():
                add_recent_project(self.project.path)
            self.project_dir = self.project.path
            self.workspace_dir = self.project.path
            self.projects_dir = self.project.projects_dir
            self.output_dir = self.project.dist_dir
            self.build_dir = self.project.build_dir
            self.cache_dir = self.project.cache_dir
            self.backups_dir = self.project.backups_dir
        else:
            self.project_dir = None
            self.workspace_dir = None
            self.projects_dir = Path.cwd()
            self.output_dir = Path.cwd() / "dist"
            self.build_dir = get_build_root()
            self.cache_dir = get_cache_root()
            self.backups_dir = get_backups_root()

        self.sdk_dir = self.find_sdk()

        # Binary Paths
        self.clang = self.find_executable("clang.exe")
        self.lld = self.find_executable("lld.exe")
        self.ld64 = self.find_ld64()
        self.swiftc = self.find_executable("swiftc.exe")
        self.swift_resource_dir = self.find_swift_resource_dir()
        self.ldid = self.tools_dir / "ldid.exe"
        self.patch_macho = self.tools_dir / "patch_macho.py"
        self.clang_rt = self.tools_dir / "libclang_rt.ios.a"

    @property
    def package_root(self) -> Path:
        return self._package_root

    @property
    def root_dir(self) -> Path:
        """Deprecated compatibility property; use package_root."""
        return self._package_root

    @property
    def active_project(self) -> Optional[ProjectContext]:
        """Returns the active standalone ProjectContext bound to this toolchain."""
        return self.project

    @property
    def has_active_project(self) -> bool:
        """Returns True if the toolchain has an active, valid standalone project bound."""
        if not self.project:
            return False
        cfg_p, _ = find_project_config_file(self.project.path)
        return cfg_p is not None

    def get_project_dir(self, name_or_path: Optional[str] = None) -> Optional[Path]:
        """Resolves a project directory from name, path, or active project."""
        if not name_or_path or name_or_path in (".", ""):
            return self.project.path if self.project else None
        try:
            cand = Path(name_or_path).resolve()
            if cand.is_dir():
                return cand
        except Exception:
            pass
        if self.project:
            found = self.project.get_project_dir(name_or_path)
            if found:
                return found
        if hasattr(self, "projects_dir") and self.projects_dir:
            try:
                cand_p = self.projects_dir / name_or_path
                if cand_p.is_dir():
                    return cand_p
            except Exception:
                pass
        return None

    def switch_project(self, new_proj_path: Optional[Path]):
        """Switches active project to a new standalone project directory."""
        if new_proj_path is None:
            self.clear_active_project()
            return
        new_p = Path(new_proj_path).resolve()
        proj_cand = detect_project(new_p)
        self.project = proj_cand if proj_cand else ProjectContext(new_p)
        self.workspace = self.project
        if self.project.path.resolve() != self.package_root.resolve():
            set_active_project(self.project.path)
        self.project_dir = self.project.path
        self.workspace_dir = self.project.path
        self.projects_dir = self.project.projects_dir
        self.output_dir = self.project.dist_dir
        self.build_dir = self.project.build_dir
        self.cache_dir = self.project.cache_dir
        self.backups_dir = self.project.backups_dir

    def clear_active_project(self):
        """Clears the currently active project context."""
        self.project = None
        self.workspace = None
        self.project_dir = None
        self.workspace_dir = None
        self.projects_dir = Path.cwd()
        self.output_dir = Path.cwd() / "dist"
        self.build_dir = get_build_root()
        self.cache_dir = get_cache_root()
        self.backups_dir = get_backups_root()

    # Backwards compatibility alias
    switch_workspace = switch_project

    def find_swift_resource_dir(self) -> Optional[Path]:
        ws_p = self.workspace.path if (hasattr(self, 'workspace') and self.workspace) else None
        sdk_root = get_sdk_root(ws_p)
        candidates = [
            sdk_root / "swift_resources" / "swift",
            sdk_root / "swift",
            self.root_dir / "sdk" / "swift_resources" / "swift",
            self.root_dir / "sdk" / "swift",
        ]
        custom_swift_res = os.environ.get("NYXWIN_SWIFT_RESOURCES")
        if custom_swift_res:
            candidates.insert(0, Path(custom_swift_res))

        for c in candidates:
            if c and c.is_dir() and (c / "iphoneos").is_dir():
                return c
        return None

    def find_executable(self, name: str) -> Optional[Path]:
        # 1. Prefer official LLVM installation first for clang/lld tools
        if name in ("clang.exe", "lld.exe", "ld64.lld.exe", "llvm-objdump.exe"):
            llvm_bin = Path(r"C:\Program Files\LLVM\bin") / name
            if llvm_bin.is_file():
                return llvm_bin

        # 2. Check dynamic Swift Toolchains
        for base_p in [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Swift" / "Toolchains",
            Path(r"C:\Program Files\Swift\Toolchains"),
            Path(r"C:\Local\Swift\Toolchains")
        ]:
            if base_p.is_dir():
                for tc in sorted(base_p.iterdir(), reverse=True):
                    cand = tc / "usr" / "bin" / name
                    if cand.is_file():
                        return cand

        # 3. Check in PATH
        found = shutil.which(name)
        if found:
            return Path(found)

        # 4. Check common installation directories on Windows
        common_paths = [
            Path(r"C:\Program Files\LLVM\bin") / name,
            Path(r"C:\Program Files (x86)\LLVM\bin") / name,
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "LLVM" / "bin" / name,
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Swift" / "bin" / name,
            self.tools_dir / name
        ]
        for p in common_paths:
            if p.is_file():
                return p
        return None

    def find_ld64(self) -> Optional[Path]:
        # Prefer official LLVM ld64.lld.exe first (iOS platform enabled)
        llvm_ld64 = Path(r"C:\Program Files\LLVM\bin\ld64.lld.exe")
        if llvm_ld64.is_file():
            return llvm_ld64
        found = shutil.which("ld64.lld.exe") or shutil.which("ld64.lld")
        if found:
            return Path(found)
        if self.lld and self.lld.is_file():
            ld64_candidate = self.lld.parent / "ld64.lld.exe"
            if ld64_candidate.is_file():
                return ld64_candidate
            return self.lld
        return None

    def find_sdk(self, requested_version: Optional[str] = None) -> Optional[Path]:
        ws_p = self.workspace.path if (hasattr(self, 'workspace') and self.workspace) else None
        search_roots: List[Path] = []

        # 1. Primary sdk_root
        sdk_root = get_sdk_root(ws_p)
        if sdk_root.is_dir() and sdk_root not in search_roots:
            search_roots.append(sdk_root)

        # 2. Canonical %LOCALAPPDATA%\NyxWin\SDKs
        canonical = get_sdks_root()
        if canonical.is_dir() and canonical not in search_roots:
            search_roots.append(canonical)

        # 3. Local package or checkout sdk/
        repo_cand = self.root_dir / "sdk"
        if repo_cand.is_dir() and repo_cand not in search_roots:
            search_roots.append(repo_cand)

        # 4. Standard system-wide installation (e.g. %SystemDrive%\iOS_SDK)
        sys_drive = os.environ.get("SystemDrive", "C:")
        sys_sdk = Path(f"{sys_drive}\\iOS_SDK")
        if sys_sdk.is_dir() and sys_sdk not in search_roots:
            search_roots.append(sys_sdk)

        for root in search_roots:
            # 1. If specific version requested (e.g. "27.0" or "iPhoneOS27.0.sdk")
            if requested_version:
                target_name = requested_version if requested_version.endswith(".sdk") else f"iPhoneOS{requested_version}.sdk"
                candidate = root / target_name
                if candidate.is_dir() and (candidate / "System" / "Library" / "Frameworks").is_dir():
                    return candidate

            # 2. Prefer stable iPhoneOS26.5.sdk for iOS 17/TrollStore compatibility
            pref = root / "iPhoneOS26.5.sdk"
            if pref.is_dir() and (pref / "System" / "Library" / "Frameworks").is_dir():
                return pref

            sdk_dirs = [d for d in root.iterdir() if d.is_dir() and d.name.startswith("iPhoneOS") and (d / "System" / "Library" / "Frameworks").is_dir()]
            if sdk_dirs:
                def sdk_sort_key(p):
                    name = p.name.replace("iPhoneOS", "").replace(".sdk", "")
                    parts = []
                    for x in name.split("."):
                        try:
                            parts.append(int(x))
                        except ValueError:
                            parts.append(0)
                    return parts
                sdk_dirs.sort(key=sdk_sort_key, reverse=True)
                return sdk_dirs[0]

        # 5. Fallback candidates
        candidates = [
            self.root_dir.parent / "Dependencies" / "iPhoneOS26.5.sdk",
            self.root_dir.parent / "iPhoneOS26.5.sdk",
            Path(f"{sys_drive}\\iOS_SDK\\iPhoneOS27.0.sdk"),
            Path(f"{sys_drive}\\iOS_SDK\\iPhoneOS26.5.sdk")
        ]
        for c in candidates:
            if c.is_dir() and (c / "System" / "Library" / "Frameworks").is_dir():
                return c
        return None

    def get_deployment_targets(self, requested_sdk: Optional[str] = None) -> List[str]:
        """
        Retrieves valid iOS deployment targets from SDKSettings.plist or SDKSettings.json
        in the active/requested iOS SDK.
        """
        sdk = self.find_sdk(requested_sdk) if requested_sdk else self.sdk_dir
        targets = []
        if sdk and sdk.is_dir():
            plist_p = sdk / "SDKSettings.plist"
            json_p = sdk / "SDKSettings.json"
            if plist_p.is_file():
                try:
                    with open(plist_p, "rb") as f:
                        d = plistlib.load(f)
                    targets = d.get("SupportedTargets", {}).get("iphoneos", {}).get("ValidDeploymentTargets") or d.get("ValidDeploymentTargets")
                except Exception:
                    pass
            if not targets and json_p.is_file():
                try:
                    with open(json_p, "r", encoding="utf-8") as f:
                        d = json.load(f)
                    targets = d.get("SupportedTargets", {}).get("iphoneos", {}).get("ValidDeploymentTargets") or d.get("ValidDeploymentTargets")
                except Exception:
                    pass

        def parse_ver(v: str):
            parts = []
            for p in str(v).split("."):
                try:
                    parts.append(int(p))
                except ValueError:
                    parts.append(0)
            return tuple(parts)

        if targets:
            return sorted(list(set(str(t) for t in targets)), key=parse_ver)

        defaults = [
            "12.0", "12.1", "12.2", "12.3", "12.4",
            "13.0", "13.1", "13.2", "13.3", "13.4", "13.5", "13.6",
            "14.0", "14.1", "14.2", "14.3", "14.4", "14.5", "14.6", "14.7",
            "15.0", "15.1", "15.2", "15.3", "15.4", "15.5", "15.6",
            "16.0", "16.1", "16.2", "16.3", "16.4", "16.5", "16.6",
            "17.0", "17.1", "17.2", "17.3", "17.4", "17.5", "17.6",
            "18.0", "18.1", "18.2", "18.3", "18.4", "18.5", "18.6"
        ]
        return sorted(defaults, key=parse_ver)
