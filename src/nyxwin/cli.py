import os
import sys
import shutil
import zipfile
import plistlib
import subprocess
import argparse
from pathlib import Path
from typing import Optional

# Ensure UTF-8 output on Windows consoles (prevents cp1256/cp1252 charmap encode crashes)
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

import nyxwin
from nyxwin.core.models import Color, print_banner, log_info, log_success, log_warning, log_error
from nyxwin.core.paths import is_safe_subpath, get_templates_dir, WORKSPACES_CONFIG_FILE, RUNTIME_DATA_DIR
from nyxwin.core.toolchain import Toolchain
from nyxwin.core.project import (
    create_project_id_file,
    find_project_config_file,
    find_entitlements_file,
    get_or_create_project_id,
)
from nyxwin.core.workspace import (
    Workspace,
    detect_workspace,
    init_workspace,
    load_workspace_config,
    save_workspace_config,
    get_recent_projects,
    add_recent_project,
    get_recent_workspaces,
    set_active_workspace
)
from nyxwin.build.pipeline import build_project
from nyxwin.services.backup import create_project_backup, list_project_backups, restore_project_backup
from nyxwin.services.icon import generate_app_icons
from nyxwin.services.sdk_manager import fetch_available_sdks, get_installed_sdks, install_sdk
from nyxwin.tui.screens.dashboard import run_interactive_menu
from nyxwin.tui.theme import fg, bold, dim
from nyxwin.tui.components.table import render_column_table, render_key_value_grid
from nyxwin.tui.components.status import render_status_badge

def cmd_doctor(toolchain: Toolchain):
    """Inspects and reports status of all required compilation and linking tools."""
    print(f"\n{Color.BOLD}Checking NyxWin Toolchain Environment...{Color.RESET}\n")

    rows = []

    # 1. Clang
    if toolchain.clang and toolchain.clang.is_file():
        try:
            ver = subprocess.check_output([str(toolchain.clang), "--version"], text=True).splitlines()[0]
            rows.append([render_status_badge("success", "OK"), "Clang Compiler", f"{toolchain.clang} ({ver})"])
        except Exception:
            rows.append([render_status_badge("success", "OK"), "Clang Compiler", str(toolchain.clang)])
    else:
        rows.append([render_status_badge("error", "MISSING"), "Clang Compiler", "Not found. Run 'winget install LLVM.LLVM' or add clang.exe to PATH."])

    # 2. LLD / ld64
    if toolchain.lld and toolchain.lld.is_file():
        rows.append([render_status_badge("success", "OK"), "LLVM Linker (lld)", str(toolchain.lld)])
        if toolchain.ld64 and toolchain.ld64.is_file():
            rows.append([render_status_badge("success", "OK"), "Mach-O Linker (ld64)", str(toolchain.ld64)])
    else:
        rows.append([render_status_badge("error", "MISSING"), "LLVM Linker (lld)", "Not found. Run 'winget install LLVM.LLVM'."])

    # 3. Swift Compiler
    if toolchain.swiftc and toolchain.swiftc.is_file():
        try:
            ver = subprocess.check_output([str(toolchain.swiftc), "--version"], text=True).splitlines()[0]
            rows.append([render_status_badge("success", "OK"), "Swift Compiler", f"{toolchain.swiftc} ({ver})"])
        except Exception:
            rows.append([render_status_badge("success", "OK"), "Swift Compiler", str(toolchain.swiftc)])
    else:
        rows.append([render_status_badge("warning", "OPTIONAL"), "Swift Compiler", "Not found (required for Swift/SwiftUI projects)"])

    # 4. Swift Target Resources
    if toolchain.swift_resource_dir and toolchain.swift_resource_dir.is_dir():
        rows.append([render_status_badge("success", "OK"), "Swift Target Libs", f"{toolchain.swift_resource_dir} (arm64/arm64e)"])
    else:
        rows.append([render_status_badge("warning", "OPTIONAL"), "Swift Target Libs", "Not found (required for Swift/SwiftUI projects)"])

    # 5. iOS SDK
    if toolchain.sdk_dir and toolchain.sdk_dir.is_dir():
        sdk_name = toolchain.sdk_dir.name
        frameworks_count = len(list((toolchain.sdk_dir / "System" / "Library" / "Frameworks").glob("*.framework")))
        rows.append([render_status_badge("success", "OK"), f"iOS SDK ({sdk_name})", f"{toolchain.sdk_dir} ({frameworks_count} frameworks)"])
    else:
        rows.append([render_status_badge("error", "MISSING"), "iOS SDK", "No SDK found in sdk/ directory. Run 'nyx sdk install 27.0'"])

    # 6. ldid (Ad-Hoc Signing)
    if toolchain.ldid and toolchain.ldid.is_file():
        rows.append([render_status_badge("success", "OK"), "Code Signer (ldid)", str(toolchain.ldid)])
    else:
        rows.append([render_status_badge("error", "MISSING"), "Code Signer (ldid)", "tools/ldid.exe not found."])

    # 7. Mach-O Patcher
    if toolchain.patch_macho and toolchain.patch_macho.is_file():
        rows.append([render_status_badge("success", "OK"), "Mach-O Patcher", f"{toolchain.patch_macho} (Patch #31)"])
    else:
        rows.append([render_status_badge("error", "MISSING"), "Mach-O Patcher", "tools/patch_macho.py not found."])

    # 8. Compiler Runtime (libclang_rt.ios.a)
    if toolchain.clang_rt and toolchain.clang_rt.is_file():
        rows.append([render_status_badge("success", "OK"), "Compiler Runtime", f"{toolchain.clang_rt} (Universal ARM64/ARM64e)"])
    else:
        rows.append([render_status_badge("warning", "OPTIONAL"), "Compiler Runtime", "libclang_rt.ios.a not found."])

    for line in render_column_table(["STATUS", "COMPONENT", "RESOLVED PATH / DETAILS"], rows):
        print(line)

    # 9. Workspace & Data Paths
    print(f"\n{Color.BOLD}Paths & Runtime Layout:{Color.RESET}")
    path_pairs = [
        ("Active Project", str(toolchain.workspace_dir)),
        ("User Config", str(nyxwin.config.paths.USER_CONFIG_DIR)),
        ("Runtime Data", str(nyxwin.config.paths.RUNTIME_DATA_DIR)),
        ("Build Root", str(nyxwin.config.paths.get_build_root())),
        ("Cache Root", str(nyxwin.config.paths.get_cache_root())),
        ("Backups Root", str(nyxwin.config.paths.get_backups_root())),
        ("Settings Root", str(nyxwin.config.paths.get_settings_root())),
    ]
    for line in render_key_value_grid(path_pairs, key_width=18):
        print(line)

    legacy = nyxwin.config.paths.detect_legacy_paths(toolchain.package_root)
    if legacy:
        print(f"\n  {render_status_badge('warning', 'NOTE')} Legacy directories detected in repository root: {', '.join(legacy.keys())}")
        print(f"         Inspect with '{Color.CYAN}nyx data paths{Color.RESET}' or migrate safely with '{Color.CYAN}nyx data migrate --dry-run{Color.RESET}'")

    print("\n" + fg("SLATE_GRAY", "─" * 70))
    can_build_c = bool(toolchain.clang and toolchain.lld and toolchain.sdk_dir and toolchain.ldid)
    can_build_swift = bool(can_build_c and toolchain.swiftc)

    if can_build_swift:
        log_success("All tools installed! Ready to compile C, Objective-C, and Swift/SwiftUI apps for iOS on Windows.")
    elif can_build_c:
        log_success("C and Objective-C iOS toolchain ready! (Install Swift.Toolchain to compile Swift/SwiftUI).")
    else:
        log_warning("Some required tools are missing. Review the items marked [MISSING] above.")

def cmd_new(
    toolchain: Toolchain,
    project_type: str,
    project_name: str,
    out_dir: Optional[Path] = None,
    bundle_id: Optional[str] = None,
    deployment_target: str = "17.0"
) -> bool:
    """Scaffolds a new native iOS application project."""
    pt = project_type.lower()
    templates_dir = get_templates_dir()
    if pt == "swiftui":
        src_template_dir = templates_dir / "Application" / "Swift" / "SwiftUI"
        compiler = "swiftc"
    elif pt in ("swift-uikit", "swift", "uikit"):
        src_template_dir = templates_dir / "Application" / "Swift" / "UIKit"
        compiler = "swiftc"
    else:
        log_error(f"Project type '{project_type}' is no longer supported.\nNyxWin is now focused exclusively on Swift iOS applications ('swiftui' or 'swift-uikit').")
        return False

    if out_dir is None:
        if toolchain and getattr(toolchain, "explicit_workspace", False) and toolchain.workspace:
            out_dir = toolchain.workspace.path
        else:
            out_dir = Path.cwd()

    target_dir = out_dir / project_name
    if target_dir.exists():
        log_error(f"Directory already exists: {target_dir}")
        return False

    os.makedirs(target_dir / "Config", exist_ok=True)
    os.makedirs(target_dir / "Resources", exist_ok=True)

    if not bundle_id:
        bundle_id = f"com.example.{project_name.lower()}"

    entitlements_content = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict/>
</plist>
"""
    with open(target_dir / "Config" / "Entitlements.plist", "w", encoding="utf-8") as f:
        f.write(entitlements_content)

    is_app = True

    if src_template_dir and src_template_dir.is_dir():
        for item in src_template_dir.iterdir():
            target_name = item.name.replace("__APP_NAME__", project_name)
            dest = target_dir / target_name
            if item.is_file():
                content = item.read_text(encoding="utf-8", errors="ignore")
                content = content.replace("__APP_NAME__", project_name)
                dest.write_text(content, encoding="utf-8")
            elif item.is_dir():
                shutil.copytree(item, dest)
    else:
        # Fallback default ContentView.swift
        if compiler == "swiftc":
            (target_dir / f"{project_name}App.swift").write_text(f"""import SwiftUI

@main
struct {project_name}App: App {{
    var body: some Scene {{
        WindowGroup {{
            ContentView()
        }}
    }}
}}
""", encoding="utf-8")
            (target_dir / "ContentView.swift").write_text(f"""import SwiftUI

struct ContentView: View {{
    var body: some View {{
        NavigationStack {{
            VStack(spacing: 24) {{
                Image(systemName: "swift")
                    .font(.system(size: 60))
                    .foregroundStyle(.tint)
                Text("Hello, iOS!")
                    .font(.title2)
                    .fontWeight(.bold)
            }}
            .padding()
            .navigationTitle("{project_name}")
        }}
    }}
}}
""", encoding="utf-8")
    # Generate Project.plist (Native Independent Schema v1.0)
    frameworks = ["SwiftUI", "UIKit"] if pt == "swiftui" else ["UIKit"]
    weak_frameworks = ["SwiftUICore"] if pt == "swiftui" else []

    clang_flags = [
        "-target", f"arm64-apple-ios$(DeploymentTarget)",
        "-isysroot", "$(SDKROOT)",
        "-framework", "UIKit"
    ]
    swift_flags = [
        "-target", f"arm64-apple-ios$(DeploymentTarget)",
        "-Xllvm", "-aarch64-use-tbi",
        "-Xfrontend", "-enable-objc-interop",
        "-sdk", "$(SDKROOT)",
        "-parse-as-library"
    ]

    bundle_info = {
        "CFBundleExecutable": "$(ExecutableName)",
        "CFBundleIdentifier": "$(BundleIdentifier)",
        "CFBundleName": "$(Name)",
        "CFBundleVersion": "$(BuildNumber)",
        "CFBundleShortVersionString": "$(Version)",
        "MinimumOSVersion": "$(DeploymentTarget)",
        "CFBundlePackageType": "APPL",
        "UIDeviceFamily": [1, 2],
        "UIRequiresFullScreen": False,
        "UILaunchScreen": {},
        "UISupportedInterfaceOrientations~ipad": [
            "UIInterfaceOrientationPortrait",
            "UIInterfaceOrientationPortraitUpsideDown",
            "UIInterfaceOrientationLandscapeLeft",
            "UIInterfaceOrientationLandscapeRight"
        ],
        "UISupportedInterfaceOrientations": [
            "UIInterfaceOrientationPortrait",
            "UIInterfaceOrientationLandscapeLeft",
            "UIInterfaceOrientationLandscapeRight"
        ],
        "UIApplicationSceneManifest": {
            "UIApplicationSupportsMultipleScenes": False,
            "UISceneConfigurations": {
                "UIWindowSceneSessionRoleApplication": [
                    {
                        "UISceneConfigurationName": "Default Configuration",
                        "UISceneDelegateClassName": "SceneDelegate"
                    }
                ]
            }
        }
    }

    proj_plist_data = {
        "SchemaVersion": "1.0",
        "TargetType": "Application",
        "Name": project_name,
        "ExecutableName": project_name,
        "BundleIdentifier": bundle_id,
        "Version": "1.0.0",
        "BuildNumber": "1",
        "DeploymentTarget": str(deployment_target),
        "Compiler": compiler,
        "ClangFlags": clang_flags,
        "SwiftFlags": swift_flags,
        "LinkerFlags": [],
        "Frameworks": frameworks,
        "WeakFrameworks": weak_frameworks,
        "BundleInfo": bundle_info
    }

    with open(target_dir / "Config" / "Project.plist", "wb") as f:
        plistlib.dump(proj_plist_data, f)

    # 1. Create persistent project identity
    create_project_id_file(target_dir, project_name)

    # 2. Write Git ignore configuration
    gitignore_content = """# NyxWin Build & Intermediate Artifacts
build/
dist/
.nyx/
*.ipa
*.o
*.dSYM
*.zip

# NyxWin Machine-Local Identity
Config/.nyxproject
.nyxproject

# Operating System & IDE Metadata
.DS_Store
Thumbs.db
.vscode/
.idea/

# Python Cache
__pycache__/
*.pyc
"""
    (target_dir / ".gitignore").write_text(gitignore_content, encoding="utf-8")

    # 3. Write project README
    readme_content = f"""# {project_name}

Native iOS application built with [NyxWin](https://github.com/xAbdoAT/NyxWin).

## Structure
- `Config/`: `Project.plist` (Project configuration), `Entitlements.plist`, and `.nyxproject`.
- `Resources/`: App icons, image assets, and bundle resources.
- Root source files: Main application code.
- `dist/`: Packaged `.ipa` release binaries.

Intermediate build objects, compiler caches, and recovery backups are managed externally under `%LOCALAPPDATA%\\NyxWin`.

## Build Commands
```powershell
# Build application from within this folder
nyx build

# Clean build artifacts
nyx clean
```
"""
    (target_dir / "README.md").write_text(readme_content, encoding="utf-8")

    # Generate and store project ID
    get_or_create_project_id(target_dir, proj_plist_data)
    add_recent_project(target_dir)

    print(f"\n{Color.BOLD}Project Created Successfully:{Color.RESET}\n")
    details = [
        ("Project Name", project_name),
        ("Template Type", project_type),
        ("Location", str(target_dir)),
        ("Bundle ID", bundle_id),
        ("Target iOS", f"iOS {deployment_target}"),
        ("Compiler", compiler),
    ]
    for line in render_key_value_grid(details, key_width=18):
        print(line)

    cd_hint = f'cd "{project_name}"'
    print(f"\n  {render_status_badge('success', 'READY')} Scaffolding complete with native configuration and gitignore.")
    print(f"  To build immediately:\n    {fg('CYAN_ELEC', cd_hint)}\n    {fg('CYAN_ELEC', 'nyx build')}\n")
    return True

def cmd_clean(toolchain: Toolchain, project_name: Optional[str] = None, clean_cache: bool = False, clean_build: bool = True):
    """
    Cleans external build intermediates (%LOCALAPPDATA%\\NyxWin\\Build\\<safe-name>-<id>\\)
    and any legacy build/ folders.
    Optionally cleans external compiler caches (%LOCALAPPDATA%\\NyxWin\\Cache\\<id>\\).
    Never deletes dist/, backups, source code, or unrelated projects.
    """
    proj_dir = None
    if project_name:
        # Check path traversal
        if ".." in project_name or Path(project_name).is_absolute():
            cand = Path(project_name).resolve()
            if toolchain.workspace:
                allowed_roots = [toolchain.workspace.path, toolchain.workspace.projects_dir]
                if not any(is_safe_subpath(cand, r) for r in allowed_roots):
                    print(f"  {render_status_badge('error', 'BLOCKED')} Path traversal detected: {project_name}")
                    log_error(f"Path traversal detected: {project_name}")
                    return
            proj_dir = cand
        elif toolchain.workspace:
            proj_dir = toolchain.workspace.get_project_dir(project_name)
        else:
            proj_dir = Path(project_name).resolve()
    else:
        if toolchain.workspace:
            proj_dir = toolchain.workspace.path
        else:
            proj_dir = Path.cwd()

    if not proj_dir or not proj_dir.is_dir():
        print(f"  {render_status_badge('error', 'NOT FOUND')} Project directory not found: {project_name or 'current directory'}")
        log_error(f"Project directory not found: {project_name or 'current directory'}")
        return

    from nyxwin.core.project import find_project_config_file, load_project_config, get_or_create_project_id
    from nyxwin.config.paths import resolve_project_build_dir, get_project_build_dir, get_project_cache_dir

    cfg_file, _ = find_project_config_file(proj_dir)
    raw_cfg = load_project_config(cfg_file) if cfg_file else {}
    cfg = raw_cfg if isinstance(raw_cfg, dict) else {}

    proj_id = get_or_create_project_id(proj_dir, cfg or {})
    canonical_build = resolve_project_build_dir(proj_dir, config=cfg, project_id=proj_id)
    target_build_dirs = {canonical_build}

    # Constrained legacy fallback: if an older build dir was keyed solely by folder name with identical project ID
    legacy_folder_build = get_project_build_dir(proj_dir.name, proj_id)
    if legacy_folder_build.is_dir() and legacy_folder_build != canonical_build:
        target_build_dirs.add(legacy_folder_build)

    if clean_build and clean_cache:
        print(f"\n{Color.BOLD}Cleaning Project Intermediates & Compiler Cache...{Color.RESET}\n")
    elif clean_cache:
        print(f"\n{Color.BOLD}Cleaning Project Compiler Cache...{Color.RESET}\n")
    else:
        print(f"\n{Color.BOLD}Cleaning Project Build Intermediates...{Color.RESET}\n")

    cleaned_build_any = False
    if clean_build:
        for ext_build_dir in target_build_dirs:
            if ext_build_dir.is_dir():
                shutil.rmtree(ext_build_dir, ignore_errors=True)
                print(f"  {render_status_badge('success', 'CLEANED')} Build intermediates: {fg('WHITE_SOFT', str(ext_build_dir))}")
                cleaned_build_any = True

        # Clean legacy local build/ folder if present
        legacy_build = proj_dir / "build"
        if legacy_build.is_dir():
            shutil.rmtree(legacy_build, ignore_errors=True)
            print(f"  {render_status_badge('success', 'CLEANED')} Legacy build directory: {fg('WHITE_SOFT', str(legacy_build))}")
            cleaned_build_any = True

        if not cleaned_build_any:
            primary_build = get_project_build_dir(proj_dir.name, proj_id)
            print(f"  {render_status_badge('muted', 'CLEAN')} No build intermediates found in {fg('WHITE_SOFT', str(primary_build))}")

    if clean_cache:
        ext_cache = get_project_cache_dir(proj_id)
        if ext_cache.is_dir():
            shutil.rmtree(ext_cache, ignore_errors=True)
            print(f"  {render_status_badge('success', 'CLEANED')} Compiler cache: {fg('WHITE_SOFT', str(ext_cache))}")
        else:
            print(f"  {render_status_badge('muted', 'CLEAN')} No compiler cache found for project ID {fg('WHITE_SOFT', str(proj_id))}")
    print()

def cmd_clean_cache(toolchain: Toolchain, project_name: Optional[str] = None):
    """Cleans external compiler cache for the specified or active project (%LOCALAPPDATA%\\NyxWin\\Cache\\<id>\\)."""
    return cmd_clean(toolchain, project_name=project_name, clean_cache=True, clean_build=False)

def cmd_clean_module_cache(toolchain: Toolchain):
    """Cleans Swift compiler module caches."""
    print(f"\n{Color.BOLD}Cleaning Swift Compiler Module Caches...{Color.RESET}\n")
    cleared = 0
    from nyxwin.config.paths import get_sdks_root
    dirs_to_check = [
        get_sdks_root() / "swift_resources" / "ModuleCache",
        get_sdks_root() / "ModuleCache",
        toolchain.root_dir / "sdk" / "swift_resources" / "ModuleCache",
        toolchain.root_dir / "sdk" / "ModuleCache",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Swift" / "ModuleCache"
    ]
    for d in dirs_to_check:
        if d.is_dir():
            for f in d.iterdir():
                try:
                    if f.is_file():
                        os.remove(f)
                    elif f.is_dir():
                        shutil.rmtree(f)
                    cleared += 1
                except Exception:
                    pass
    if cleared > 0:
        print(f"  {render_status_badge('success', 'CLEANED')} Swift module cache ({cleared} items removed across cache paths)\n")
    else:
        print(f"  {render_status_badge('muted', 'CLEAN')} Swift module cache is already clean (0 items found)\n")

def cmd_setup_path(toolchain: Toolchain):
    """Generates global CLI launcher shims in %LOCALAPPDATA%\\NyxWin\\bin and adds to Windows User PATH."""
    from nyxwin.config.paths import get_bin_root
    app_root = toolchain.root_dir.resolve()
    if app_root.name == "nyxwin" and app_root.parent.name == "src":
        cand = app_root.parent.parent
        if (cand / "main.py").is_file():
            app_root = cand

    bin_dir = get_bin_root()
    bin_dir.mkdir(parents=True, exist_ok=True)

    py_exe = sys.executable or "python"
    main_py = app_root / "main.py"
    src_dir = app_root / "src"

    shim_content = (
        f"@echo off\r\n"
        f"set \"PYTHONPATH={src_dir};%PYTHONPATH%\"\r\n"
        f"\"{py_exe}\" \"{main_py}\" %*\r\n"
    )
    for shim_name in ("nyx.cmd", "nyxwin.cmd"):
        try:
            (bin_dir / shim_name).write_text(shim_content, encoding="utf-8")
        except Exception:
            pass

    target_dir = str(bin_dir.resolve())
    log_info(f"Registering '{target_dir}' in Windows User PATH environment variable...")
    ps_cmd = f"""
    $target = '{target_dir}'
    $currentPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $paths = $currentPath -split ';' | Where-Object {{ $_ -ne '' }}
    if ($paths -notcontains $target) {{
        $newPath = ($paths + $target) -join ';'
        [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
        Write-Host "SUCCESS"
    }} else {{
        Write-Host "ALREADY_PRESENT"
    }}
    """
    res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True)
    out = res.stdout.strip()
    if "SUCCESS" in out:
        log_success(f"Added '{target_dir}' to Windows User PATH!")
        print(f"\n  {Color.GREEN}You can now open CMD or PowerShell anywhere and type:{Color.RESET}")
        print(f"    {Color.CYAN}nyx{Color.RESET}   or   {Color.CYAN}nyxwin{Color.RESET}\n")
    elif "ALREADY_PRESENT" in out:
        log_success(f"'{target_dir}' is already present in your User PATH.")
        print(f"  You can run {Color.CYAN}nyx{Color.RESET} or {Color.CYAN}nyxwin{Color.RESET} from any folder.")
    else:
        log_warning(f"Could not automatically update PATH: {res.stderr.strip() or out}")

def main():
    """Main CLI entry point for NyxWin."""
    parser = argparse.ArgumentParser(
        prog="nyx",
        description="NyxWin - Native iOS Toolchain & IPA Builder for Windows"
    )
    parser.add_argument("--version", "-V", action="version", version=f"NyxWin {nyxwin.__version__}")
    parser.add_argument("--project", "-p", dest="workspace", default=None, help="Path to standalone project directory (default: current directory or active project)")
    parser.add_argument("--workspace", "-w", dest="workspace", default=None, help=argparse.SUPPRESS)

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # doctor
    subparsers.add_parser("doctor", help="Inspect and report status of all required tools")

    # menu
    subparsers.add_parser("menu", help="Launch the interactive terminal TUI menu")

    # new
    new_parser = subparsers.add_parser("new", help="Create a new iOS project")
    new_parser.add_argument("type", choices=["swiftui", "swift-uikit", "uikit"], help="Project template type ('swiftui' or 'swift-uikit')")
    new_parser.add_argument("name", help="Project name")
    new_parser.add_argument("--out", default=None, help="Output directory (default: ./<name>)")
    new_parser.add_argument("--bundle-id", default=None, help="Bundle identifier (e.g. com.myorg.myapp)")
    new_parser.add_argument("--target", default="17.0", help="Minimum iOS deployment target (default: 17.0)")

    # build
    build_parser = subparsers.add_parser("build", help="Compile and package an iOS project into an IPA")
    build_parser.add_argument("project", nargs="?", default=".", help="Path to project directory (default: current directory)")
    build_parser.add_argument("--target", default=None, help="Target triple (e.g. arm64-apple-ios17.0)")
    build_parser.add_argument("--sdk", default=None, help="Specific SDK version to use (e.g. 27.0, 26.5)")
    build_parser.add_argument("--profile", choices=["auto", "trollstore", "sandboxed"], default="auto", help="Entitlement profile: auto, trollstore, or sandboxed")
    build_parser.add_argument("--verbose", "-v", action="store_true", help="Print detailed command invocations")

    # clean
    clean_parser = subparsers.add_parser("clean", help="Clean external build intermediates (%%LOCALAPPDATA%%\\NyxWin\\Build\\)")
    clean_parser.add_argument("project", nargs="?", default=None, help="Project name or path (leave blank for current project)")
    clean_parser.add_argument("--cache", action="store_true", help="Also clean external compilation cache")

    # clean-cache
    clean_cache_parser = subparsers.add_parser("clean-cache", help="Clean external compiler caches (%%LOCALAPPDATA%%\\NyxWin\\Cache\\)")
    clean_cache_parser.add_argument("project", nargs="?", default=None, help="Project name or path (leave blank for current project)")

    # clean-module-cache
    subparsers.add_parser("clean-module-cache", help="Clean Swift compiler module caches")

    # export
    export_parser = subparsers.add_parser("export", help="Export a project to ZIP archive")
    export_parser.add_argument("project", nargs="?", default=".", help="Project name or path (default: .)")
    export_parser.add_argument("--format", choices=["standard"], default="standard", help="Archive format (default: standard)")
    export_parser.add_argument("--out", default=None, help="Output ZIP filepath")

    # import
    import_parser = subparsers.add_parser("import", help="Import a project from a ZIP archive")
    import_parser.add_argument("archive", help="Path to .zip archive")
    import_parser.add_argument("--name", default=None, help="Custom project name")
    import_parser.add_argument("--target", "-d", default=None, help="Destination directory (default: current directory)")

    # set-icon
    icon_parser = subparsers.add_parser("set-icon", help="Generate all iPhone & iPad app icon sizes")
    icon_parser.add_argument("project", help="Project name or path")
    icon_parser.add_argument("image", help="Path to source image (PNG/JPG)")

    # backup
    backup_parser = subparsers.add_parser("backup", help="Create a timestamped backup snapshot of a project")
    backup_parser.add_argument("project", help="Project name or path")

    # list-backups
    list_b_parser = subparsers.add_parser("list-backups", help="List all backup snapshots for a project")
    list_b_parser.add_argument("project", help="Project name or path")

    # restore
    restore_parser = subparsers.add_parser("restore", help="Restore a project from a backup snapshot")
    restore_parser.add_argument("project", help="Project name to restore into")
    restore_parser.add_argument("backup", help="Path to backup .zip archive")

    # sdk
    sdk_parser = subparsers.add_parser("sdk", help="Manage iOS SDKs")
    sdk_sub = sdk_parser.add_subparsers(dest="sdk_command", help="SDK subcommands")
    sdk_sub.add_parser("list", help="List installed and available iOS SDKs")
    sdk_install_p = sdk_sub.add_parser("install", help="Download and install an SDK (e.g. 26.5, 27.0)")
    sdk_install_p.add_argument("version", help="SDK version (e.g. 26.5, 27.0)")

    # setup-path
    subparsers.add_parser("setup-path", help="Add NyxWin to Windows User PATH")

    # update
    update_parser = subparsers.add_parser("update", help="Check for and install NyxWin updates from GitHub")
    update_parser.add_argument("--check", action="store_true", help="Only check if an update is available without installing")
    update_parser.add_argument("--dev", action="store_true", help="Pull latest development commit directly from main branch")
    update_parser.add_argument("--force", action="store_true", help="Force re-download and apply update even if version matches")

    # data
    data_parser = subparsers.add_parser("data", help="Inspect active data paths and perform safe migration")
    data_sub = data_parser.add_subparsers(dest="data_command", help="Data subcommands")
    data_sub.add_parser("paths", help="Display active configuration, data, project, and legacy paths")
    data_mig = data_sub.add_parser("migrate", help="Safely copy legacy repository data to modern standard directories")
    data_mig.add_argument("--dry-run", action="store_true", default=True, help="Simulate migration without modifying files (default)")
    data_mig.add_argument("--apply", dest="dry_run", action="store_false", help="Apply migration and copy files")

    # config
    cfg_parser = subparsers.add_parser("config", help="Inspect configuration")
    cfg_sub = cfg_parser.add_subparsers(dest="config_command", help="Config subcommands")
    cfg_show = cfg_sub.add_parser("show", help="Show active configuration and workspace settings")
    cfg_show.add_argument("project", nargs="?", default=None, help="Optional project name to inspect")

    # workspace (deprecated)
    ws_parser = subparsers.add_parser("workspace", help="[Deprecated] Multi-app workspace commands have been retired")
    ws_parser.add_argument("workspace_args", nargs="*", help=argparse.SUPPRESS)

    args = parser.parse_args()

    toolchain = Toolchain(workspace_dir=getattr(args, "workspace", None))

    if args.command == "doctor":
        print_banner()
        cmd_doctor(toolchain)
    elif args.command == "menu":
        run_interactive_menu()
    elif args.command == "new":
        print_banner()
        out_p = Path(args.out) if args.out else None
        cmd_new(toolchain, args.type, args.name, out_p, bundle_id=args.bundle_id, deployment_target=getattr(args, "target", "17.0"))
    elif args.command == "build":
        print_banner()
        build_project(toolchain, Path(args.project), args.target, args.verbose, getattr(args, "sdk", None), profile=args.profile)
    elif args.command == "clean":
        print_banner()
        cmd_clean(toolchain, args.project, clean_cache=getattr(args, "cache", False), clean_build=True)
    elif args.command == "clean-cache":
        print_banner()
        cmd_clean_cache(toolchain, args.project)
    elif args.command == "clean-module-cache":
        print_banner()
        cmd_clean_module_cache(toolchain)
    elif args.command == "export":
        print_banner()
        from nyxwin.services.export_service import export_project
        proj_dir = None
        if getattr(args, "project", None) and args.project != ".":
            cand = Path(args.project).resolve()
            if cand.is_dir():
                proj_dir = cand
            elif toolchain.workspace:
                proj_dir = toolchain.workspace.get_project_dir(args.project)
        elif toolchain.workspace:
            proj_dir = toolchain.workspace.path
        else:
            proj_dir = Path.cwd()

        if proj_dir and proj_dir.is_dir():
            print(f"\n{Color.BOLD}Exporting Portable Project Archive: {proj_dir.name}...{Color.RESET}\n")
            out_z = Path(args.out) if getattr(args, "out", None) else None
            fmt = getattr(args, "format", "standard")
            exported_p = export_project(proj_dir, out_zip=out_z, format_type=fmt, verbose=True)
            if exported_p and exported_p.is_file():
                size_kb = exported_p.stat().st_size / 1024
                pairs = [
                    ("Project Name", proj_dir.name),
                    ("Archive Format", f"{fmt.title()} Portable Zip"),
                    ("Output Archive", str(exported_p)),
                    ("Archive Size", f"{size_kb:.1f} KB"),
                ]
                for line in render_key_value_grid(pairs, key_width=18):
                    print(line)
                print(f"\n  {render_status_badge('success', 'EXPORTED')} Source package created (build artifacts and caches excluded).\n")
        else:
            print(f"\n  {render_status_badge('error', 'NOT FOUND')} Project directory not found: {args.project}\n")
    elif args.command == "import":
        print_banner()
        print(f"\n{Color.BOLD}Importing Project Archive...{Color.RESET}\n")
        from nyxwin.services.export_service import import_project
        archive_p = Path(args.archive)
        target_dir = Path(args.target).resolve() if getattr(args, "target", None) else Path.cwd()
        ok, dest, msg = import_project(archive_p, target_dir=target_dir, new_name=getattr(args, "name", None))
        if ok and dest:
            pairs = [
                ("Archive File", archive_p.name),
                ("Destination", str(dest)),
                ("Project Name", dest.name),
                ("Project Identity", "Fresh persistent ID assigned (cache safe)"),
            ]
            for line in render_key_value_grid(pairs, key_width=18):
                print(line)
            print(f"\n  {render_status_badge('success', 'IMPORTED')} {msg}\n")
        else:
            print(f"  {render_status_badge('error', 'FAILED')} {msg}\n")
    elif args.command == "set-icon":
        print_banner()
        generate_app_icons(toolchain, args.project, Path(args.image))
    elif args.command == "backup":
        print_banner()
        print(f"\n{Color.BOLD}Creating Snapshot Backup: {args.project}...{Color.RESET}\n")
        bf = create_project_backup(toolchain, args.project)
        if bf:
            size_kb = bf.stat().st_size / 1024
            pairs = [
                ("Project", str(args.project)),
                ("Snapshot File", bf.name),
                ("Location", str(bf.parent)),
                ("Archive Size", f"{size_kb:.1f} KB"),
            ]
            for line in render_key_value_grid(pairs, key_width=16):
                print(line)
            print(f"\n  {render_status_badge('success', 'BACKUP')} Snapshot archive verified and stored safely.\n")
        else:
            print(f"  {render_status_badge('error', 'FAILED')} Could not create backup for project: {args.project}\n")
    elif args.command == "list-backups":
        print_banner()
        backups = list_project_backups(toolchain, args.project)
        if backups:
            print(f"\n{Color.BOLD}--- Backups for {args.project} ---{Color.RESET}\n")
            rows = []
            for b in backups:
                rows.append([
                    render_status_badge("success", "BACKUP"),
                    b['filename'],
                    f"{b['size_kb']:.1f} KB",
                    str(b['mtime'])
                ])
            for line in render_column_table(["STATUS", "SNAPSHOT FILE", "SIZE", "CREATED DATE"], rows):
                print(line)
            print()
        else:
            print(f"\n  {render_status_badge('muted', 'EMPTY')} No backups found for project: {args.project}\n")
    elif args.command == "restore":
        print_banner()
        print(f"\n{Color.BOLD}Restoring Project Snapshot: {args.project}...{Color.RESET}\n")
        b_path = Path(args.backup)
        if not b_path.is_file():
            print(f"  {render_status_badge('error', 'NOT FOUND')} Backup archive does not exist: {b_path}\n")
        else:
            ok = restore_project_backup(toolchain, args.project, b_path)
            if ok:
                pairs = [
                    ("Target Project", str(args.project)),
                    ("Source Archive", b_path.name),
                    ("Safety Snapshot", "Created in Backups directory before restore"),
                ]
                for line in render_key_value_grid(pairs, key_width=18):
                    print(line)
                print(f"\n  {render_status_badge('success', 'RESTORED')} Project successfully restored from snapshot.\n")
            else:
                print(f"\n  {render_status_badge('error', 'FAILED')} Restore operation did not complete successfully.\n")
    elif args.command == "setup-path":
        print_banner()
        cmd_setup_path(toolchain)
    elif args.command == "update":
        print_banner()
        from nyxwin.services.updater import perform_update
        channel = "dev" if getattr(args, "dev", False) else "release"
        ok, msg = perform_update(
            channel=channel,
            check_only=getattr(args, "check", False),
            force=getattr(args, "force", False),
        )
        if ok:
            log_success(msg)
        else:
            log_error(msg)
            sys.exit(1)
    elif args.command == "workspace":
        print_banner()
        print(f"\n{Color.YELLOW}[NOTE] Multi-app workspace commands have been retired.{Color.RESET}")
        print("NyxWin now operates strictly on standalone single-app projects.")
        print("Every project is self-contained with its own Config/Project.plist or Project.plist.\n")
        print("To build a project:")
        print(f"  {Color.CYAN}nyx build [PATH]{Color.RESET}")
        print("To clean build intermediates:")
        print(f"  {Color.CYAN}nyx clean [PATH]{Color.RESET}")
        print("To clean compiler caches:")
        print(f"  {Color.CYAN}nyx clean-cache [PATH]{Color.RESET}\n")
    elif args.command == "sdk":
        print_banner()
        if args.sdk_command == "list" or not args.sdk_command:
            installed = get_installed_sdks(toolchain)
            print(f"\n{Color.BOLD}--- Installed iOS SDKs ---{Color.RESET}\n")
            if installed:
                rows = []
                for s in installed:
                    act_badge = fg("EMERALD", "★ Active") if s["is_active"] else fg("GRAY_MUTED", "No")
                    rows.append([
                        render_status_badge("success", "INSTALLED"),
                        s['name'],
                        f"iOS {s['version']}",
                        f"{s['frameworks_count']} frameworks",
                        act_badge
                    ])
                for line in render_column_table(["STATUS", "SDK NAME", "IOS VERSION", "FRAMEWORKS", "ACTIVE"], rows):
                    print(line)
            else:
                print(f"  {render_status_badge('warning', 'EMPTY')} No SDKs installed in sdk/ directory.")

            print(f"\n{Color.BOLD}--- Available for Download (xybp888/iOS-SDKs) ---{Color.RESET}\n")
            remote = fetch_available_sdks()
            if remote:
                rem_rows = []
                for r in remote[:10]:
                    is_inst = any(inst["name"] == r["name"] for inst in installed)
                    badge = render_status_badge("success", "INSTALLED") if is_inst else render_status_badge("active", "AVAILABLE")
                    sz_str = f"~{r['size'] / (1024*1024):.0f} MB" if r.get("size") else "Unknown"
                    status_text = fg("EMERALD", "Ready to build") if is_inst else fg("CYAN_ELEC", "Downloadable")
                    rem_rows.append([badge, r['name'], sz_str, status_text])
                for line in render_column_table(["STATUS", "REMOTE SDK PACKAGE", "SIZE", "STATUS"], rem_rows):
                    print(line)
            else:
                print(f"  {render_status_badge('warning', 'UNAVAILABLE')} Unable to fetch remote SDK list.")

            print(f"\nTo install an SDK:\n  {Color.CYAN}nyx sdk install <version>{Color.RESET} (e.g. nyx sdk install 27.0)\n")
        elif args.sdk_command == "install":
            install_sdk(toolchain, args.version)
    elif args.command == "data":
        print_banner()
        from nyxwin.services.migration import (
            get_active_paths_summary,
            plan_data_migration,
            execute_data_migration,
        )
        if args.data_command == "paths" or not args.data_command:
            summary = get_active_paths_summary()
            print(f"\n{Color.BOLD}--- NyxWin Active & Configured Paths ---{Color.RESET}")
            pairs = [
                ("Package Root", str(summary["package_root"])),
                ("User Config", str(summary["user_config_dir"])),
                ("Runtime Data", str(summary["runtime_data_dir"])),
                ("Default Projects", str(summary["default_projects_dir"])),
            ]
            for line in render_key_value_grid(pairs, key_width=20):
                print(line)
            print()
            if summary["has_legacy_data"]:
                print(f"  {render_status_badge('warning', 'LEGACY')} Repository directories detected:")
                for k, v in summary["legacy_detected"].items():
                    print(f"      • {fg('CYAN_ELEC', k):12} → {v}")
                print(f"\n  To preview migration to standard directories:")
                print(f"    {Color.CYAN}nyx data migrate --dry-run{Color.RESET}")
                print(f"  To execute safe migration:")
                print(f"    {Color.CYAN}nyx data migrate --apply{Color.RESET}\n")
            else:
                log_success("No legacy directories detected. Storage layout is modern.")
        elif args.data_command == "migrate":
            plan = plan_data_migration()
            print(f"\n{Color.BOLD}--- NyxWin Safe Data Migration Plan ---{Color.RESET}")
            print(f"  Source Root:          {plan.source_root}")
            print(f"  Target Projects:      {plan.target_projects_dir}")
            print(f"  Target Data:          {plan.target_data_dir}")
            print(f"  Total Files:          {plan.total_files}")
            print(f"  Total Data:           {plan.total_bytes / (1024*1024):.2f} MB")
            print(f"  Destination Conflicts:{plan.conflict_count} (conflicts will NOT be overwritten)")
            print(f"  Available Space:      {plan.available_space_bytes / (1024*1024):.2f} MB")
            if plan.warnings:
                print(f"\n  {Color.YELLOW}Warnings / Notes:{Color.RESET}")
                for w in plan.warnings:
                    print(f"    - {w}")

            if args.dry_run:
                print(f"\n  [{Color.CYAN}DRY-RUN{Color.RESET}] No files were copied.")
                print(f"  Run with {Color.BOLD}--apply{Color.RESET} to perform verified file copy:")
                print(f"    {Color.CYAN}nyx data migrate --apply{Color.RESET}\n")
            else:
                print(f"\n{Color.BOLD}Executing Migration (Preserving Original Sources)...{Color.RESET}")
                res = execute_data_migration(plan, dry_run=False)
                if res.success:
                    log_success(res.message)
                    if res.report_file:
                        print(f"  Report written to: {res.report_file}")
                else:
                    log_error(res.message)
    elif args.command == "config":
        print_banner()
        from nyxwin.core.project import load_project_config, find_project_config_file
        if args.config_command == "show" or not args.config_command:
            proj_name = getattr(args, "project", None)
            if proj_name:
                p_dir = Path(proj_name).resolve() if Path(proj_name).is_dir() else (toolchain.workspace.get_project_dir(proj_name) if toolchain.workspace else None)
                if p_dir:
                    cfg_p, _ = find_project_config_file(p_dir)
                    if cfg_p:
                        cfg = load_project_config(cfg_p)
                        print(f"\n{Color.BOLD}--- Configuration for '{p_dir.name}' ({cfg_p.name}) ---{Color.RESET}")
                        pairs = []
                        for k, v in cfg.items():
                            if isinstance(v, (str, int, float, bool)):
                                pairs.append((str(k), str(v)))
                            elif isinstance(v, list):
                                pairs.append((str(k), f"[{len(v)} items: {', '.join(str(x) for x in v[:3])}{'...' if len(v)>3 else ''}]"))
                            elif isinstance(v, dict):
                                pairs.append((str(k), f"{{{len(v)} keys}}"))
                        for line in render_key_value_grid(pairs, key_width=28):
                            print(line)
                    else:
                        log_error(f"Project configuration (Project.plist) not found in {p_dir}")
                else:
                    log_error(f"Project directory not found: {proj_name}")
            else:
                cfg = load_workspace_config()
                print(f"\n{Color.BOLD}--- NyxWin Global & Project Configuration ---{Color.RESET}")
                pairs = [
                    ("Active Project", str(cfg.get('active_project') or cfg.get('active_workspace', str(toolchain.workspace_dir)))),
                    ("Config File", str(WORKSPACES_CONFIG_FILE)),
                    ("User Config Dir", str(nyxwin.config.paths.USER_CONFIG_DIR)),
                ]
                for line in render_key_value_grid(pairs, key_width=18):
                    print(line)
                recent = get_recent_projects()
                print(f"\n  {fg('GRAY_MUTED', 'Recent Projects:')}")
                if recent:
                    for r in recent:
                        print(f"    • {fg('WHITE_SOFT', str(r))}")
                else:
                    print(f"    {fg('DARK_GRAY', '(None recorded)')}")
                print()
    else:
        # Default with no arguments: Launch the interactive menu!
        run_interactive_menu()

if __name__ == "__main__":
    main()
