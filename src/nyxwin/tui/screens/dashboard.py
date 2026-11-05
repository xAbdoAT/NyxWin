import os
import sys
import time
import shutil
import zipfile
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from nyxwin.core.models import Color, log_info, log_success, log_error, log_warning, print_banner
from nyxwin.core.toolchain import Toolchain
from nyxwin.core.project import load_project_config, save_project_config, find_project_config_file
from nyxwin.config.paths import get_cache_root
from nyxwin.core.workspace import (
    Workspace,
    detect_workspace,
    init_workspace,
    get_recent_projects,
    add_recent_project,
    remove_recent_project,
    prune_stale_recent_projects,
    get_recent_workspaces,
    set_active_workspace,
)
from nyxwin.core.paths import is_safe_subpath
from nyxwin.build.pipeline import build_project, get_last_build_tracker
from nyxwin.core.diagnostics import save_diagnostics_report, generate_diagnostics_report_text
from nyxwin.services.backup import create_project_backup, list_project_backups, restore_project_backup
from nyxwin.services.icon import generate_app_icons
from nyxwin.services.git_service import get_project_git_status, init_project_git
from nyxwin.tui.terminal import (
    print_header, prompt_input, wait_for_enter, clear_screen, read_key,
    get_terminal_width, transition_screen, copy_to_clipboard
)
from nyxwin.tui.menu import prompt_menu, prompt_boxed_menu, print_boxed_header
from nyxwin.tui.theme import fg, bold, dim, symbol, pad_visible, visible_length
from nyxwin.tui.components.frame import render_panel, render_footer
from nyxwin.tui.components.menu import MenuItem, prompt_modern_menu
from nyxwin.tui.components.table import render_column_table
from nyxwin.tui.components.prompt import prompt_destructive_confirmation
from nyxwin.tui.screens.config_screen import screen_project_config
from nyxwin.tui.screens.backup_screen import screen_project_backups
from nyxwin.tui.screens.sdk_screen import screen_sdk_manager
from nyxwin.tui.screens.diagnostics_screen import screen_build_diagnostics_viewer, screen_build_log_viewer

def _render_build_completion_summary(tracker: Any, ipa_p: Path, success: bool):
    """Renders the stable build completion summary card at the top of the viewport."""
    transition_screen()
    w = get_terminal_width()
    bld_elapsed = getattr(tracker, "format_build_elapsed", lambda: "00:00")()
    proj_name = getattr(tracker, "project_name", "Project")
    target_triple = getattr(tracker, "target_triple", "arm64-apple-ios")
    profile = getattr(tracker, "profile", "auto").capitalize()
    warnings = getattr(tracker, "warnings", [])
    has_warnings = len(warnings) > 0

    if success:
        title = "BUILD SUCCEEDED WITH WARNINGS" if has_warnings else "BUILD SUCCEEDED"
        badge = f"{proj_name} · {bld_elapsed}"

        abs_ipa = Path(ipa_p).resolve()
        display_ipa = str(abs_ipa)
        proj_dir = getattr(tracker, "project_dir", None)
        if proj_dir:
            try:
                rel = abs_ipa.relative_to(Path(proj_dir).resolve())
                display_ipa = str(rel)
            except ValueError:
                display_ipa = str(abs_ipa)
        else:
            try:
                rel = abs_ipa.relative_to(Path.cwd().resolve())
                display_ipa = str(rel)
            except ValueError:
                display_ipa = abs_ipa.name

        size_bytes = ipa_p.stat().st_size if ipa_p.is_file() else 0
        if size_bytes >= 1024 * 1024:
            size_str = f"{size_bytes / (1024.0 * 1024.0):.2f} MB"
        else:
            size_str = f"{size_bytes / 1024.0:.1f} KB"

        details = [
            ("Target", f"{proj_name} ({target_triple})"),
            ("Profile", profile),
            ("Output IPA", f"{display_ipa} ({size_str})"),
            ("Duration", f"Total build time: {bld_elapsed}"),
            ("Pipeline", "SCAN, COMPILE, LINK, PATCH, SIGN, PACKAGE (Completed)")
        ]
        log_p = getattr(tracker, "log_path", None)
        if log_p and Path(log_p).is_file():
            details.append(("Build Log", str(log_p)))
        if has_warnings:
            details.append(("Warnings", f"{len(warnings)} warning(s) produced during compilation"))

        from nyxwin.tui.components.status import render_summary_card
        card = render_summary_card(
            title=title,
            details=details,
            is_success=True,
            badge=badge,
            width=w
        )
        print(card)
    else:
        from nyxwin.tui.components.progress import STAGE_NAMES
        stage_idx = getattr(tracker, "active_stage_idx", 2)
        failed_stage_label = STAGE_NAMES.get(stage_idx, "BUILD")
        failed_stage_name = tracker.stages[stage_idx - 1].name if (tracker and 1 <= stage_idx <= len(tracker.stages)) else "Build"

        content_lines = [""]
        completed_stages = [s for s in getattr(tracker, "stages", []) if s.status == "completed"]
        if completed_stages:
            content_lines.append(f"  {fg('GRAY_MUTED', bold('COMPLETED'))}")
            check_sym = symbol("CHECK")
            for s in completed_stages:
                icon = fg("EMERALD", check_sym)
                lbl = fg("GRAY_MUTED", pad_visible(s.label, 8, align="left"))
                det = s.detail if s.detail else s.name
                content_lines.append(f"  {icon}  {lbl} {fg('WHITE_SOFT', det)}")
            content_lines.append("")

        content_lines.append(f"  {fg('CORAL_RED', bold('FAILED'))}")
        fail_sym = symbol("FAIL")
        content_lines.append(f"  {fg('CORAL_RED', fail_sym)}  {fg('CORAL_RED', bold(failed_stage_label))}")
        content_lines.append("")

        diag = getattr(tracker, "failure_diagnostic", {}) or {}
        diag_tool = (diag.get("tool") or failed_stage_label).upper()
        diag_category = diag.get("category", f"{diag_tool} DIAGNOSTIC")
        diag_box_w = max(20, w - 8)

        content_lines.append(f"  {fg('CORAL_RED', '┌─ ' + diag_category + ' ' + '─' * max(2, diag_box_w - visible_length(diag_category) - 5) + '┐')}")
        content_lines.append(f"  {fg('CORAL_RED', '│')} {' ' * (diag_box_w - 2)} {fg('CORAL_RED', '│')}")
        content_lines.append(f"  {fg('CORAL_RED', '│')}  {fg('WHITE_SOFT', bold(diag.get('message', 'Build failed')))}")
        content_lines.append(f"  {fg('CORAL_RED', '│')} {' ' * (diag_box_w - 2)} {fg('CORAL_RED', '│')}")
        content_lines.append(f"  {fg('CORAL_RED', '│')}  {fg('GRAY_MUTED', pad_visible('Tool:', 12))} {fg('WHITE_SOFT', diag.get('tool', 'toolchain'))}")
        content_lines.append(f"  {fg('CORAL_RED', '│')}  {fg('GRAY_MUTED', pad_visible('Exit code:', 12))} {fg('WHITE_SOFT', str(diag.get('exit_code', 1)))}")
        log_p = getattr(tracker, "log_path", None)
        if log_p and Path(log_p).is_file():
            content_lines.append(f"  {fg('CORAL_RED', '│')}  {fg('GRAY_MUTED', pad_visible('Build Log:', 12))} {fg('WHITE_SOFT', str(log_p))}")
        if diag.get("file"):
            content_lines.append(f"  {fg('CORAL_RED', '│')}  {fg('GRAY_MUTED', pad_visible('Location:', 12))} {fg('CYAN_ELEC', str(diag['file']))}")
        content_lines.append(f"  {fg('CORAL_RED', '│')} {' ' * (diag_box_w - 2)} {fg('CORAL_RED', '│')}")
        content_lines.append(f"  {fg('CORAL_RED', '└' + '─' * (diag_box_w) + '┘')}")
        content_lines.append("")
        content_lines.append(f"  {fg('GRAY_MUTED', f'Build terminated during {failed_stage_name.lower()}.')}")
        content_lines.append("")

        panel = render_panel(
            title="BUILD FAILED",
            content_lines=content_lines,
            badge=failed_stage_label,
            width=w,
            border_color="CORAL_RED",
            title_color="CORAL_RED",
            badge_color="CORAL_RED"
        )
        print(panel)

def screen_build_project_flow(toolchain: Toolchain, selected_proj_dir: Path, profile: str = "auto"):
    """
    Executes build flow for a project with clean screen transitions,
    project-relative IPA path presentation, and rich diagnostics viewing/copying/saving actions.
    """
    while True:
        transition_screen()
        success = build_project(toolchain, selected_proj_dir, profile=profile)
        tracker = get_last_build_tracker()

        ipa_p = getattr(tracker, "ipa_path", None)
        if not ipa_p or not ipa_p.is_file():
            cand = selected_proj_dir / "dist" / f"{selected_proj_dir.name}.ipa"
            if not cand.is_file() and toolchain.output_dir:
                alt = toolchain.output_dir / f"{selected_proj_dir.name}.ipa"
                ipa_p = alt if alt.is_file() else cand
            else:
                ipa_p = cand

        out_folder = ipa_p.parent if ipa_p.parent.is_dir() else selected_proj_dir / "dist"
        warnings = getattr(tracker, "warnings", []) if tracker else []
        has_warnings = len(warnings) > 0
        failure_diag = getattr(tracker, "failure_diagnostic", None) if tracker else None
        errors = getattr(tracker, "errors", []) if tracker else []
        has_failure_diag = failure_diag is not None or len(errors) > 0
        log_p = getattr(tracker, "log_path", None)

        status_msg = ""
        status_is_error = False

        while True:
            shortcuts = []
            if success:
                shortcuts.append(("O", "Open IPA"))
                if has_warnings:
                    shortcuts.append(("W", f"View Warnings ({len(warnings)})"))
                    shortcuts.append(("C", "Copy All Warnings"))
                    shortcuts.append(("S", "Save Diagnostics"))
                if log_p and Path(log_p).is_file():
                    shortcuts.append(("L", "View Build Log"))
                shortcuts.append(("P", "Copy Full IPA Path"))
                shortcuts.append(("R", "Rebuild"))
                shortcuts.append(("Esc", "Back"))
            else:
                if has_failure_diag or has_warnings:
                    shortcuts.append(("W", "View Diagnostics"))
                    shortcuts.append(("C", "Copy Diagnostics"))
                    shortcuts.append(("S", "Save Diagnostics"))
                if log_p and Path(log_p).is_file():
                    shortcuts.append(("L", "View Build Log"))
                shortcuts.append(("R", "Retry Build"))
                shortcuts.append(("Esc", "Back"))

            if status_msg:
                color_name = "CORAL_RED" if status_is_error else "EMERALD"
                print(f"\n  {fg(color_name, status_msg)}")
                status_msg = ""
                status_is_error = False

            action_parts = []
            for key, act in shortcuts:
                action_parts.append(f"[{fg('WHITE_SOFT', key)}] {fg('GRAY_MUTED', act)}")
            footer_bar = f" {fg('SLATE_GRAY', '•')} ".join(action_parts)
            print(f"\n  {footer_bar}\n", end="", flush=True)

            if os.environ.get("NYXWIN_NON_INTERACTIVE") == "1" or not (hasattr(sys.stdout, "isatty") and sys.stdout.isatty()):
                return

            try:
                k = read_key()
            except Exception:
                return

            if k in ("o", "O") and success:
                try:
                    os.startfile(out_folder)
                    status_msg = "✔ Opened output folder in Explorer."
                    status_is_error = False
                except Exception as e:
                    status_msg = f"✕ Failed to open output folder: {e}"
                    status_is_error = True

            elif k in ("p", "P") and success:
                abs_str = str(ipa_p.resolve())
                ok = copy_to_clipboard(abs_str)
                if ok:
                    status_msg = f"✔ Full IPA path copied to clipboard: {abs_str}"
                    status_is_error = False
                else:
                    status_msg = f"⚠ Clipboard unavailable. Full path: {abs_str}"
                    status_is_error = True

            elif k in ("w", "W") and (has_warnings or not success):
                screen_build_diagnostics_viewer(tracker, selected_proj_dir, is_success=success)
                _render_build_completion_summary(tracker, ipa_p, success)

            elif k in ("c", "C") and (has_warnings or not success):
                all_text = generate_diagnostics_report_text(tracker, selected_proj_dir, is_success=success)
                ok = copy_to_clipboard(all_text)
                if ok:
                    count_str = f" ({len(warnings)})" if has_warnings else ""
                    status_msg = f"✔ All compiler diagnostics{count_str} copied to clipboard."
                    status_is_error = False
                else:
                    dest = save_diagnostics_report(tracker, selected_proj_dir, is_success=success)
                    status_msg = f"⚠ Clipboard unavailable. Diagnostics saved to: {dest.name}"
                    status_is_error = True

            elif k in ("s", "S") and (has_warnings or not success):
                try:
                    dest = save_diagnostics_report(tracker, selected_proj_dir, is_success=success)
                    status_msg = f"✔ Complete diagnostics report saved to: {dest}"
                    status_is_error = False
                except Exception as e:
                    status_msg = f"✕ Failed to save diagnostics: {e}"
                    status_is_error = True

            elif k in ("l", "L") and log_p and Path(log_p).is_file():
                screen_build_log_viewer(tracker, Path(log_p))
                _render_build_completion_summary(tracker, ipa_p, success)

            elif k in ("r", "R"):
                break  # Break inner loop to rebuild

            elif k in ("ESC", "q", "Q", "ENTER"):
                return

def screen_select_build_profile(toolchain: Toolchain, proj_dir: Path) -> Optional[str]:
    """
    Renders build profile selection with rich descriptions, intended signing use cases,
    and clear limitations formatted for readability at 80x24.
    """
    cfg = load_project_config(proj_dir) or {}
    proj_name = cfg.get("Name") or cfg.get("CFBundleName") or proj_dir.name

    desc = (
        f"Select Entitlement Profile for '{proj_name}':\n"
        f"  • Auto:       Uses Config/Entitlements.plist as configured in Project Settings.\n"
        f"  • Jailbreak / TrollStore Entitlements (Advanced):\n"
        f"                Injects root/unsandboxed keys (platform-application, no-sandbox).\n"
        f"                Note: Injected keys require OS exploit/trustcache to become active.\n"
        f"  • Sandboxed:  Standard user sandbox (get-task-allow). For sideload signing."
    )
    options = [
        "🚀 1. Auto (Config/Entitlements.plist) — Use active project entitlements",
        "👑 2. Jailbreak / TrollStore Entitlements (Advanced) — Injects root/unsandboxed keys",
        "📦 3. Sandboxed (Standard Sideload Profile) — Standard sandbox (get-task-allow)",
        "↩️  Back to Menu"
    ]
    choice = prompt_menu(
        desc,
        options,
        breadcrumb=f"NYXWIN › {proj_name.upper()} › BUILD PROFILE"
    )
    if choice == 0:
        return "auto"
    elif choice == 1:
        return "trollstore"
    elif choice == 2:
        return "sandboxed"
    else:
        return None

def screen_export_project(toolchain: Toolchain, proj_dir: Path):
    """Exports project to portable clean source ZIP with rich summary and actions."""
    proj_name = proj_dir.name
    while True:
        fmt_choice = prompt_menu(
            f"Export '{proj_name}' — Create Portable Source Archive:\n"
            f"  Packages complete project sources, assets, and configuration into a clean ZIP.",
            [
                "📁 1. Export Portable Source Archive (.zip)",
                "↩️  Back to Project Tools"
            ],
            breadcrumb=f"NYXWIN › {proj_name.upper()} › EXPORT"
        )
        if fmt_choice in (-1, 1):
            return

        format_type = "standard"
        out_dir = proj_dir / "dist"
        os.makedirs(out_dir, exist_ok=True)
        out_zip = out_dir / f"{proj_name}_source.zip"

        print_header(f"EXPORTING {proj_name.upper()}")
        print(f"  {fg('CYAN_ELEC', symbol('PROGRESS'))} Packaging clean source distribution...")
        from nyxwin.services.export_service import export_project
        res_zip = export_project(proj_dir, out_zip=out_zip, format_type=format_type, verbose=True)

        w = get_terminal_width()
        if res_zip and res_zip.is_file():
            try:
                with zipfile.ZipFile(res_zip, "r") as zf:
                    file_count = len(zf.namelist())
            except Exception:
                file_count = 0
            sz_bytes = res_zip.stat().st_size
            sz_kb = sz_bytes / 1024.0
            sz_str = f"{sz_kb:.1f} KB ({sz_bytes:,} bytes)" if sz_kb < 1024 else f"{sz_kb/1024:.2f} MB ({sz_bytes:,} bytes)"
            fmt_desc = "Standard Portable Source Zip"

            summary_lines = [
                f"  Project:          {proj_name}",
                f"  Format Profile:   {fmt_desc}",
                f"  Archive Name:     {res_zip.name}",
                f"  Full Destination: {res_zip.resolve()}",
                f"  Archive Size:     {sz_str}",
                f"  Packaged Files:   {file_count} files",
                f"  Exclusion Policy: Cleanly excluded build/, dist/, .cache/, .git/, and temporary binaries."
            ]
            post_act = prompt_menu(
                "Export package ready. Choose an action:",
                [
                    "📂 Open Output Folder in Explorer",
                    "↩️  Return to Project Tools"
                ],
                breadcrumb=f"NYXWIN › {proj_name.upper()} › EXPORT COMPLETE",
                top_panel_lines=summary_lines,
                top_panel_title="PROJECT EXPORT COMPLETE",
                top_panel_badge="PACKAGED",
                top_panel_border="EMERALD",
                top_panel_title_color="EMERALD",
                top_panel_badge_color="EMERALD"
            )
            if post_act == 0:
                try:
                    os.startfile(out_dir)
                except Exception as e:
                    log_error(f"Failed to open explorer: {e}")
                return
            else:
                return
        else:
            wait_for_enter("Export failed. Press [Enter] to return to menu...")
            return

def screen_clean_intermediates(toolchain: Toolchain, proj_dir: Path):
    """
    Renders dedicated clean build intermediates screen with metrics,
    space calculation, scope distinction, and empty-state handling.
    """
    from nyxwin.core.project import find_project_config_file, load_project_config, get_or_create_project_id
    from nyxwin.config.paths import resolve_project_build_dir, get_project_build_dir

    cfg_file, _ = find_project_config_file(proj_dir)
    cfg = (load_project_config(cfg_file) or {}) if cfg_file else {}
    proj_name = cfg.get("Name") or cfg.get("CFBundleName") or proj_dir.name
    proj_id = get_or_create_project_id(proj_dir, cfg or {})

    canonical_build = resolve_project_build_dir(proj_dir, config=cfg, project_id=proj_id)
    target_build_dirs = {canonical_build}
    legacy_folder_build = get_project_build_dir(proj_dir.name, proj_id)
    if legacy_folder_build.is_dir() and legacy_folder_build != canonical_build:
        target_build_dirs.add(legacy_folder_build)
    legacy_local_build = proj_dir / "build"
    if legacy_local_build.is_dir():
        target_build_dirs.add(legacy_local_build)

    total_files = 0
    total_bytes = 0
    for b_dir in target_build_dirs:
        if b_dir.is_dir():
            for root, _, files in os.walk(b_dir):
                for f in files:
                    try:
                        p = Path(root) / f
                        total_bytes += p.stat().st_size
                        total_files += 1
                    except Exception:
                        pass

    w = get_terminal_width()
    print_header(f"NYXWIN › {proj_name.upper()} › CLEAN BUILD INTERMEDIATES")

    sz_kb = total_bytes / 1024.0
    sz_str = f"{sz_kb:.1f} KB ({total_bytes:,} bytes)" if sz_kb < 1024 else f"{sz_kb/1024:.2f} MB ({total_bytes:,} bytes)"

    info_lines = [
        f"Active Project:       {proj_name}",
        f"Build Directory:      {canonical_build}",
        f"Target Intermediates: Object files (*.o), dependency rules (*.d), build_manifest.json",
        "",
        "Safe Preservation Guarantee:",
        "  • Distribution Packages:  dist/*.ipa deliverables are preserved.",
        "  • Compiler Caches:        %LOCALAPPDATA%\\NyxWin\\Cache\\ is preserved.",
        "  • Recovery Snapshots:     %LOCALAPPDATA%\\NyxWin\\Backups\\ is preserved.",
        "  • Project Source Code:    All source files and configurations are preserved."
    ]
    info_panel = render_panel(
        title="BUILD INTERMEDIATES CLEANUP",
        content_lines=info_lines,
        badge="SAFE CLEANUP",
        width=w,
        border_color="SLATE_GRAY",
        title_color="CYAN_ELEC"
    )
    print(f"\n{info_panel}\n")

    if total_files == 0:
        clean_lines = [
            f"No build intermediates found for project '{proj_name}'.",
            f"Directory: {canonical_build}",
            "Build workspace is already clean. No action needed."
        ]
        panel = render_panel(
            title="WORKSPACE ALREADY CLEAN",
            content_lines=clean_lines,
            badge="ALREADY CLEAN",
            width=w,
            border_color="EMERALD",
            title_color="EMERALD",
            badge_color="EMERALD"
        )
        print(f"{panel}\n")
    else:
        for b_dir in target_build_dirs:
            if b_dir.is_dir():
                shutil.rmtree(b_dir, ignore_errors=True)

        res_lines = [
            f"Cleaned build intermediates for '{proj_name}'.",
            f"Reclaimed Storage: {sz_str}",
            f"Removed Files:     {total_files} intermediate build artifacts",
            f"Status:            Workspace is pristine and ready for clean build."
        ]
        panel = render_panel(
            title="BUILD INTERMEDIATES CLEANED",
            content_lines=res_lines,
            badge="CLEANED",
            width=w,
            border_color="EMERALD",
            title_color="EMERALD",
            badge_color="EMERALD"
        )
        print(f"{panel}\n")

    wait_for_enter()

def screen_clean_compiler_cache(toolchain: Toolchain, proj_dir: Path):
    """
    Renders dedicated compiler cache cleanup screen with metrics,
    space calculation, cache categories, and empty-state handling.
    """
    from nyxwin.core.project import find_project_config_file, load_project_config, get_or_create_project_id
    from nyxwin.config.paths import get_project_cache_dir

    cfg_file, _ = find_project_config_file(proj_dir)
    cfg = (load_project_config(cfg_file) or {}) if cfg_file else {}
    proj_name = cfg.get("Name") or cfg.get("CFBundleName") or proj_dir.name
    proj_id = get_or_create_project_id(proj_dir, cfg or {})

    cache_dir = get_project_cache_dir(proj_id)

    total_files = 0
    total_bytes = 0
    if cache_dir.is_dir():
        for root, _, files in os.walk(cache_dir):
            for f in files:
                try:
                    p = Path(root) / f
                    total_bytes += p.stat().st_size
                    total_files += 1
                except Exception:
                    pass

    w = get_terminal_width()
    print_header(f"NYXWIN › {proj_name.upper()} › CLEAN COMPILER CACHE")

    sz_kb = total_bytes / 1024.0
    sz_str = f"{sz_kb:.1f} KB ({total_bytes:,} bytes)" if sz_kb < 1024 else f"{sz_kb/1024:.2f} MB ({total_bytes:,} bytes)"

    info_lines = [
        f"Active Project:       {proj_name}",
        f"Cache Directory:      {cache_dir}",
        f"Cache Scope:          Clang precompiled modules (*.pcm), Swift module caches (*.swiftmodule)",
        "",
        "Safe Preservation Guarantee:",
        "  • Build Intermediates:  %LOCALAPPDATA%\\NyxWin\\Build\\ is preserved.",
        "  • Output Packages:      dist/*.ipa deliverables are preserved.",
        "  • Recovery Snapshots:   %LOCALAPPDATA%\\NyxWin\\Backups\\ is preserved.",
        "  • Project Source Code:  All source files and configurations are preserved."
    ]
    info_panel = render_panel(
        title="COMPILER CACHE CLEANUP",
        content_lines=info_lines,
        badge="SAFE CLEANUP",
        width=w,
        border_color="SLATE_GRAY",
        title_color="CYAN_ELEC"
    )
    print(f"\n{info_panel}\n")

    if total_files == 0:
        clean_lines = [
            f"No cached compiler modules found for project '{proj_name}'.",
            f"Directory: {cache_dir}",
            "Compiler cache is already empty. No action needed."
        ]
        panel = render_panel(
            title="CACHE ALREADY CLEAN",
            content_lines=clean_lines,
            badge="ALREADY CLEAN",
            width=w,
            border_color="EMERALD",
            title_color="EMERALD",
            badge_color="EMERALD"
        )
        print(f"{panel}\n")
    else:
        shutil.rmtree(cache_dir, ignore_errors=True)
        cache_dir.mkdir(parents=True, exist_ok=True)

        res_lines = [
            f"Cleaned compiler module cache for '{proj_name}'.",
            f"Reclaimed Storage: {sz_str}",
            f"Removed Files:     {total_files} cached modules and PCH headers",
            f"Status:            Compiler cache purged. Compilers will rebuild modules on next run."
        ]
        panel = render_panel(
            title="COMPILER CACHE PURGED",
            content_lines=res_lines,
            badge="CLEANED",
            width=w,
            border_color="EMERALD",
            title_color="EMERALD",
            badge_color="EMERALD"
        )
        print(f"{panel}\n")

    wait_for_enter()

def screen_project_git(toolchain: Toolchain, proj_dir: Path):
    """Sub-screen to view Git status, commit, and initialize Git repo with proper unborn HEAD handling."""
    proj_name = proj_dir.name
    while True:
        stat = get_project_git_status(proj_dir)
        w = get_terminal_width()

        if not stat["has_git"]:
            act = prompt_menu(
                f"Project '{proj_name}' is not currently a Git repository.\n"
                f"Initialize a new local Git repository with NyxWin standard .gitignore?",
                [
                    "✨ Initialize Git Repository with standard .gitignore",
                    "↩️  Back to Project Tools"
                ],
                breadcrumb=f"NYXWIN › {proj_name.upper()} › GIT INIT"
            )
            if act == 0:
                if init_project_git(proj_dir):
                    log_success(f"Initialized Git repository for '{proj_name}'!")
                else:
                    log_error(f"Failed to initialize Git repository for '{proj_name}'.")
                wait_for_enter()
            else:
                return
        else:
            branch_str = stat.get("branch") or "main"
            has_commits = stat.get("has_commits", False)
            commit_count = stat.get("commit_count", 0)
            latest_commit = stat.get("latest_commit")
            is_clean = stat.get("clean", True)
            mod_cnt = stat.get("modified_count", 0)
            stage_cnt = stat.get("staged_count", 0)
            untr_cnt = stat.get("untracked_count", 0)

            if has_commits:
                commit_info = f"{commit_count} commits recorded"
                latest_info = latest_commit if latest_commit else "None"
            else:
                commit_info = "0 commits (Initial repository — unborn HEAD)"
                latest_info = "None — No commits recorded yet"

            if is_clean:
                tree_info = "Clean (No uncommitted changes)"
            else:
                tree_info = f"{mod_cnt} modified, {stage_cnt} staged, {untr_cnt} untracked"

            options = [
                "📊 View Detailed Status (git status)",
                "💾 Stage & Commit All Changes",
                "📜 View Commit History (git log)",
                "↩️  Back to Project Tools"
            ]

            title_desc = (
                f"Git Repository Dashboard ({branch_str}):\n"
                f"  {commit_info}\n"
                f"  Working tree: {tree_info}"
            )

            choice = prompt_menu(
                title_desc,
                options,
                breadcrumb=f"NYXWIN › {proj_name.upper()} › GIT"
            )
            if choice in (-1, 3):
                return

            if choice == 0:
                print_header(f"GIT STATUS: {proj_name}")
                subprocess.run(["git", "-C", str(proj_dir), "status"])
                wait_for_enter()
            elif choice == 1:
                print_header(f"GIT COMMIT: {proj_name}")
                if is_clean:
                    print(f"\n  {fg('EMERALD', '✓')} Working tree is clean. Nothing to commit.\n")
                    wait_for_enter()
                else:
                    msg = prompt_input("Enter commit message")
                    if msg and msg.strip():
                        subprocess.run(["git", "-C", str(proj_dir), "add", "."], capture_output=True)
                        res = subprocess.run(["git", "-C", str(proj_dir), "commit", "-m", msg.strip()])
                        if res.returncode == 0:
                            log_success("Changes committed successfully!")
                        else:
                            log_error("Commit failed or nothing to commit.")
                    wait_for_enter()
            elif choice == 2:
                print_header(f"GIT HISTORY: {proj_name}")
                if not has_commits:
                    print(f"\n  {fg('AMBER', '!')} {fg('WHITE_SOFT', 'This repository has no commits yet (unborn HEAD).')}")
                    print(f"  {fg('GRAY_MUTED', 'Create an initial commit using option [2] Stage & Commit All Changes.')}\n")
                else:
                    subprocess.run(["git", "-C", str(proj_dir), "log", "-n", "8", "--oneline", "--decorate"])
                wait_for_enter()

def get_project_tools_options(proj_name: str) -> List[str]:
    """Returns the options list for the Project Tools submenu."""
    return [
        "📤  Export Project (.zip)",
        "💾  Backups & Restore Snapshots",
        "🧹  Clean Build Intermediates",
        "⚡  Clean Compiler Cache for This Project",
        "🐙  Git Repository (Status, Commit, History)",
        "📂  Open Project Folder in Explorer"
    ]

def get_global_tools_options() -> List[str]:
    """Returns the options list for the Global Tools submenu."""
    return [
        "📦  iOS SDK Manager",
        "🩺  Toolchain Doctor",
        "🦅  Clean Swift Compiler Module Cache",
        "⚡  Clean All Global Compiler Caches (%LOCALAPPDATA%\\NyxWin\\Cache\\)",
        "🔄  Check for Updates"
    ]

def get_main_menu_state(toolchain: Toolchain) -> Tuple[str, List[str], bool, Optional[Path]]:
    """
    Evaluates the active project state and returns:
    (menu_title, menu_options, has_active_proj, curr_p)
    """
    has_active_proj = toolchain.has_active_project
    curr_p = toolchain.workspace.path if (has_active_proj and toolchain.workspace) else None

    if has_active_proj and curr_p:
        cfg = load_project_config(curr_p) or {}
        proj_name = cfg.get("Name") or cfg.get("CFBundleName") or curr_p.name
        bundle_id = cfg.get("BundleIdentifier", "Unknown")
        target_ver = str(cfg.get("DeploymentTarget", "17.0"))
        scheme = cfg.get("TargetType", "Application")
        compiler = cfg.get("Compiler", "swiftc")
        b_ver = str(cfg.get("Version", "1.0"))

        has_icon = (curr_p / "Resources" / "AppIcon60x60.png").is_file() or (curr_p / "Resources" / "AppIcon.png").is_file()
        icon_status = f"{Color.GREEN}Configured{Color.RESET}" if has_icon else f"{Color.YELLOW}None / Default{Color.RESET}"

        git_stat = get_project_git_status(curr_p)
        if git_stat["has_git"]:
            clean_str = "clean" if git_stat["clean"] else "uncommitted changes"
            git_badge = f"{Color.GREEN}{git_stat['branch']} ({clean_str}){Color.RESET}"
        else:
            git_badge = f"{Color.YELLOW}Not initialized{Color.RESET}"

        menu_title = f"""{Color.BOLD}PROJECT: {Color.CYAN}{proj_name}{Color.RESET}
  {Color.WHITE}Target:{Color.RESET} iOS {target_ver} · {scheme} ({compiler})
  {Color.WHITE}Path:{Color.RESET} {curr_p}
  {Color.WHITE}Bundle ID:{Color.RESET} {bundle_id} · {Color.WHITE}Version:{Color.RESET} {b_ver}
  {Color.WHITE}Git:{Color.RESET} {git_badge} · {Color.WHITE}App Icon:{Color.RESET} {icon_status}"""

        menu_options = [
            "🚀  Build IPA",
            "⚙️   Project Settings",
            "🧰  Project Tools",
            "🔄  Open / Switch Project",
            "🛠️   Global Tools",
            "🚪  Exit"
        ]
        return menu_title, menu_options, True, curr_p
    else:
        cwd_str = str(Path.cwd().resolve())
        menu_title = f"""{Color.BOLD}No project selected{Color.RESET}
  {Color.WHITE}Current directory:{Color.RESET} {cwd_str}"""

        menu_options = [
            "📂  Open Project",
            "✨  Create New Project",
            "📥  Import Project Archive",
            "🛠️   Global Tools",
            "🚪  Exit"
        ]
        return menu_title, menu_options, False, None

def screen_project_tools(toolchain: Toolchain, proj_dir: Path):
    """Submenu for project-scoped tools: export, backups, cleaning, git, and explorer."""
    cfg = load_project_config(proj_dir) or {}
    proj_name = cfg.get("Name") or cfg.get("CFBundleName") or proj_dir.name
    options = get_project_tools_options(proj_name)

    while True:
        choice = prompt_menu(
            f"{Color.BOLD}PROJECT TOOLS{Color.RESET} ({proj_name}):\n  Select a project tool or maintenance action:",
            options,
            breadcrumb=f"NYXWIN › {proj_name.upper()} › TOOLS"
        )
        if choice == -1:
            return

        if choice == 0:
            screen_export_project(toolchain, proj_dir)
        elif choice == 1:
            screen_project_backups(toolchain, proj_dir)
        elif choice == 2:
            screen_clean_intermediates(toolchain, proj_dir)
        elif choice == 3:
            screen_clean_compiler_cache(toolchain, proj_dir)
        elif choice == 4:
            screen_project_git(toolchain, proj_dir)
        elif choice == 5:
            try:
                os.startfile(proj_dir)
            except Exception as e:
                log_error(f"Failed to open directory: {e}")
                wait_for_enter()

def screen_global_tools(toolchain: Toolchain):
    """Submenu for global utilities: SDK manager, doctor, global module & compiler caches, and updates."""
    while True:
        options = get_global_tools_options()

        choice = prompt_menu(
            f"{Color.BOLD}GLOBAL TOOLS & UTILITIES{Color.RESET}:\n  Select a global utility or maintenance action:",
            options,
            breadcrumb="NYXWIN › GLOBAL TOOLS"
        )
        if choice == -1:
            return

        if choice == 0:
            screen_sdk_manager(toolchain)
        elif choice == 1:
            screen_doctor(toolchain)
        elif choice == 2:
            print_header("CLEAN SWIFT MODULE CACHE")
            from nyxwin.cli import cmd_clean_module_cache
            cmd_clean_module_cache(toolchain)
            wait_for_enter()
        elif choice == 3:
            confirmed = prompt_destructive_confirmation(
                title="PURGE GLOBAL CACHES",
                warning_text="Target directory: %LOCALAPPDATA%\\NyxWin\\Cache\nScope: Swift compilation modules and object file caches.\n\nNote: Project source files, backups, and output IPAs will NOT be deleted.",
                action_label="Purge All Global Compiler Caches"
            )
            if confirmed:
                cache_root = get_cache_root()
                if cache_root.is_dir():
                    shutil.rmtree(cache_root, ignore_errors=True)
                    cache_root.mkdir(parents=True, exist_ok=True)
                    log_success(f"Cleaned global compiler cache: {cache_root}")
                else:
                    log_info("Global compiler cache is already clean.")
                wait_for_enter()
        elif choice == 4:
            print_header("NYXWIN › GLOBAL TOOLS › CHECK FOR UPDATES")
            from nyxwin.services.updater import check_for_updates, perform_update
            info = check_for_updates(channel="release")
            if not info["checked"]:
                log_error(f"Could not check for updates: {info.get('error')}")
                wait_for_enter()
            else:
                print(f"\n  Current Version: {Color.CYAN}v{info['current_version']}{Color.RESET}")
                print(f"  Latest Version:  {Color.GREEN}v{info['latest_version']}{Color.RESET}")
                if info["update_available"]:
                    upd_choice = prompt_menu(
                        f"A new version of NyxWin (v{info['latest_version']}) is available!\nWould you like to download and install it now?",
                        ["✅  Yes, Update Now (Official Release)", "🚀  Pull Latest Development Commit (main branch)", "❌  Cancel"],
                        breadcrumb="NYXWIN › GLOBAL TOOLS › UPDATE"
                    )
                    if upd_choice in (0, 1):
                        ch = "dev" if upd_choice == 1 else "release"
                        ok, msg = perform_update(channel=ch, force=(upd_choice == 1))
                        if ok:
                            log_success(msg)
                        else:
                            log_error(msg)
                        wait_for_enter()
                else:
                    log_success(f"NyxWin is up to date (v{info['current_version']}).")
                    upd_choice = prompt_menu(
                        "Choose an update action:",
                        ["🔙  Return to Global Tools", "🚀  Force Pull Latest Development Commit (main branch)"],
                        breadcrumb="NYXWIN › GLOBAL TOOLS › UPDATE"
                    )
                    if upd_choice == 1:
                        ok, msg = perform_update(channel="dev", force=True)
                        if ok:
                            log_success(msg)
                        else:
                            log_error(msg)
                        wait_for_enter()

def screen_open_project(toolchain: Toolchain):
    """Screen to select from recent projects, enter a path, create, or import a standalone project."""
    while True:
        recents = get_recent_projects(prune_missing=False)
        cur_p_str = str(toolchain.workspace.path.resolve()) if (toolchain.workspace and toolchain.workspace.path) else ""
        options = []
        has_stale_entries = False

        for r in recents:
            p = Path(r)
            if not p.is_dir():
                has_stale_entries = True
                options.append(f"⚠️  {p.name} [{r}] {Color.RED}(Directory Missing){Color.RESET}")
            else:
                cfg_p, _ = find_project_config_file(p)
                if not cfg_p:
                    valid_tag = f" {Color.YELLOW}(Missing Project.plist){Color.RESET}"
                else:
                    valid_tag = ""
                badge = f" {Color.GREEN}★ (active){Color.RESET}" if str(p.resolve()) == cur_p_str else ""
                options.append(f"📁 {p.name} [{r}]{valid_tag}{badge}")

        action_browse = len(options)
        options.append(f"{Color.GREEN}[+] 📂 Enter Project Directory Path{Color.RESET}")

        action_new = len(options)
        options.append(f"{Color.GREEN}[+] ✨ Create New Standalone Project{Color.RESET}")

        action_import = len(options)
        options.append(f"{Color.GREEN}[+] 📥 Import Project Archive (.zip){Color.RESET}")

        if has_stale_entries:
            action_clear_stale = len(options)
            options.append(f"{Color.YELLOW}[×] 🧹 Clear Missing Projects from History{Color.RESET}")
        else:
            action_clear_stale = -1

        choice = prompt_menu(
            "Select an existing standalone project to open, or enter a path:",
            options,
            breadcrumb="NYXWIN › OPEN PROJECT"
        )
        if choice == -1:
            return

        if choice == action_browse:
            print_header("NYXWIN › OPEN PROJECT › ENTER DIRECTORY")
            dir_str = prompt_input("Enter path to project directory")
            if dir_str:
                target_p = Path(dir_str.strip('"').strip("'")).resolve()
                if not target_p.is_dir():
                    log_error(f"Directory not found: {target_p}")
                    wait_for_enter()
                else:
                    cfg_p, _ = find_project_config_file(target_p)
                    if not cfg_p:
                        log_warning(f"No Project.plist found in {target_p}.")
                        conf = prompt_menu(
                            f"Directory '{target_p.name}' lacks a valid Project.plist configuration.\nDo you still want to switch to this directory?",
                            ["❌ Cancel", "⚠️ Yes, open anyway"]
                        )
                        if conf != 1:
                            continue
                    toolchain.switch_project(target_p)
                    add_recent_project(target_p)
                    return
        elif choice == action_new:
            screen_create_project(toolchain)
            if toolchain.has_active_project:
                return
        elif choice == action_import:
            screen_import_project(toolchain)
            if toolchain.has_active_project:
                return
        elif choice == action_clear_stale and action_clear_stale != -1:
            removed = prune_stale_recent_projects()
            log_success(f"Pruned {removed} missing project(s) from history.")
            wait_for_enter()
        else:
            sel_path = Path(recents[choice])
            if not sel_path.is_dir():
                log_error(f"Project directory does not exist on disk:\n  {sel_path}")
                conf = prompt_menu(
                    "Remove this missing project from recent history?",
                    ["⚠️ Yes, remove from history", "❌ Keep in history"]
                )
                if conf == 0:
                    remove_recent_project(sel_path)
                    log_success("Removed from history.")
                    wait_for_enter()
                continue

            cfg_p, _ = find_project_config_file(sel_path)
            if not cfg_p:
                log_warning(f"Directory lacks Project.plist: {sel_path}")
                conf = prompt_menu(
                    f"Selected folder '{sel_path.name}' has no Project.plist.\nOpen anyway?",
                    ["❌ Cancel", "⚠️ Yes, open folder"]
                )
                if conf != 1:
                    continue

            toolchain.switch_project(sel_path)
            add_recent_project(sel_path)
            return

def screen_import_project(toolchain: Toolchain):
    """Import project from ZIP archive into a standalone project directory."""
    print_header("IMPORT PROJECT ARCHIVE")
    archive_str = prompt_input("Enter path to .zip archive to import")
    if not archive_str:
        return

    archive_p = Path(archive_str.strip('"').strip("'"))
    if not archive_p.is_file():
        log_error(f"Archive not found: {archive_p}")
        wait_for_enter()
        return

    dest_str = prompt_input("Enter destination directory (leave blank for current directory)", ".")
    dest_dir = Path(dest_str.strip('"').strip("'")).resolve() if dest_str else Path.cwd()

    from nyxwin.services.export_service import import_project
    ok, dest, msg = import_project(archive_p, target_dir=dest_dir)
    if ok and dest:
        toolchain.switch_project(dest)
        add_recent_project(dest)
        return
    else:
        log_error(msg)
        wait_for_enter()

def screen_create_project(toolchain: Toolchain):
    """Interactive 2-step New Project Scaffolding Wizard (Swift-First)."""
    template_items = [
        MenuItem(
            label="SwiftUI Application",
            key="1",
            description="Swift 6.x · Modern declarative user interface"
        ),
        MenuItem(
            label="UIKit Application (Swift)",
            key="2",
            description="Swift 6.x · Native UIKit with programmatic interface"
        ),
    ]
    template_types = ["swiftui", "swift-uikit"]

    while True:
        c1 = prompt_modern_menu(
            header_title="NYXWIN › CREATE PROJECT",
            header_badge="Step 1/2",
            top_panel_lines=["Select an iOS application template:"],
            items=template_items,
            can_cancel=True
        )
        if c1 == -1:
            return

        selected_label = template_items[c1].label
        selected_type = template_types[c1]

        w = get_terminal_width()
        clear_screen(force_cls=False)
        top_panel = render_panel(
            title="NYXWIN › CREATE PROJECT › CONFIGURE",
            content_lines=[
                f"Selected Template: {selected_label}",
                "Provide project identity, minimum deployment target, and destination directory."
            ],
            badge="Step 2/2",
            width=w,
            title_color="CYAN_ELEC",
            badge_color="VIOLET"
        )
        print(top_panel)
        print()

        name = prompt_input("Enter Project Name (e.g. MySuperApp)")
        if not name:
            continue

        default_bundle = f"com.example.{name.lower()}"
        bundle_id = prompt_input("Enter Bundle Identifier", default_bundle)
        target = prompt_input("Minimum iOS Deployment Target", "17.0")
        dest_str = prompt_input("Enter parent folder for project (leave blank for current directory)", ".")
        out_dir = Path(dest_str.strip('"').strip("'")).resolve() if dest_str else Path.cwd()

        from nyxwin.cli import cmd_new
        if cmd_new(toolchain, selected_type, name, out_dir=out_dir, bundle_id=bundle_id, deployment_target=target):
            new_proj = out_dir / name
            if new_proj.is_dir():
                toolchain.switch_project(new_proj)
                add_recent_project(new_proj)

                # Intentional completion screen for interactive wizard mode
                if os.environ.get("NYXWIN_NON_INTERACTIVE") != "1" and hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
                    gen_files = "Config/Project.plist, Config/Entitlements.plist, .gitignore, README.md"
                    creation_details = [
                        f"  Project Name:      {name}",
                        f"  Template Type:     {selected_label} ({selected_type})",
                        f"  Project Directory: {new_proj.resolve()}",
                        f"  Bundle Identifier: {bundle_id}",
                        f"  Deployment Target: iOS {target}",
                        f"  Generated Configs: {gen_files}",
                        f"  Status:            Scaffolding complete. Project active and ready to build."
                    ]
                    post_act = prompt_menu(
                        "Project scaffolded successfully. Choose an action:",
                        [
                            "🚀 Open Active Project Dashboard",
                            "📂 Open Project Folder in Explorer",
                            "🔨 Build Project Now"
                        ],
                        breadcrumb="NYXWIN › CREATE PROJECT › SUCCESS",
                        top_panel_lines=creation_details,
                        top_panel_title="PROJECT CREATED SUCCESSFULLY",
                        top_panel_badge="READY",
                        top_panel_border="EMERALD",
                        top_panel_title_color="EMERALD",
                        top_panel_badge_color="EMERALD",
                        can_cancel=False
                    )
                    if post_act == 1:
                        try:
                            os.startfile(new_proj)
                        except Exception:
                            pass
                    elif post_act == 2:
                        screen_build_project_flow(toolchain, new_proj)
                return
        else:
            wait_for_enter("Project creation failed. Press [Enter] to return...")
            return

def screen_doctor(toolchain: Toolchain):
    """Toolchain Doctor Screen."""
    clear_screen()
    w = get_terminal_width()
    can_build_c = bool(toolchain.clang and toolchain.lld and toolchain.sdk_dir and toolchain.ldid)
    can_build_swift = bool(can_build_c and toolchain.swiftc)

    badge = "STATUS: READY" if can_build_swift else ("STATUS: C ONLY" if can_build_c else "STATUS: ATTENTION")
    badge_col = "GREEN" if can_build_swift else ("YELLOW" if can_build_c else "RED")

    top_p = render_panel(
        title="NYXWIN › TOOLCHAIN DOCTOR",
        content_lines=[
            "All required compilers and libraries verified for native Windows iOS builds." if can_build_swift
            else "Some toolchain components require attention. See diagnostics below."
        ],
        badge=badge,
        width=w,
        border_color="SLATE_GRAY",
        title_color="CYAN_ELEC",
        badge_color=badge_col
    )
    print(top_p)
    print()

    # Build rows for table
    headers = ["COMPONENT", "STATUS / VERSION", "PATH / DETAILS"]
    rows = []

    # 1. Clang
    if toolchain.clang and toolchain.clang.is_file():
        try:
            ver = subprocess.check_output([str(toolchain.clang), "--version"], text=True).splitlines()[0]
        except Exception:
            ver = "Installed"
        rows.append([f"{fg('GREEN', '✓')} Clang C/C++", ver[:22], str(toolchain.clang)])
    else:
        rows.append([f"{fg('RED', '✗')} Clang C/C++", "MISSING", "Run 'winget install LLVM.LLVM'"])

    # 2. LLD
    if toolchain.lld and toolchain.lld.is_file():
        rows.append([f"{fg('GREEN', '✓')} LLVM Linker (lld)", "Installed", str(toolchain.lld)])
    else:
        rows.append([f"{fg('RED', '✗')} LLVM Linker (lld)", "MISSING", "Run 'winget install LLVM.LLVM'"])

    # 3. ld64
    if toolchain.ld64 and toolchain.ld64.is_file():
        rows.append([f"{fg('GREEN', '✓')} Mach-O Linker (ld64)", "Installed", str(toolchain.ld64)])
    else:
        rows.append([f"{fg('YELLOW', '!')} Mach-O Linker", "Using lld", "Fallback to lld64.lld"])

    # 4. Swift
    if toolchain.swiftc and toolchain.swiftc.is_file():
        try:
            ver = subprocess.check_output([str(toolchain.swiftc), "--version"], text=True).splitlines()[0]
        except Exception:
            ver = "Installed"
        rows.append([f"{fg('GREEN', '✓')} Swift Compiler", ver[:22], str(toolchain.swiftc)])
    else:
        rows.append([f"{fg('YELLOW', '!')} Swift Compiler", "MISSING (Swift only)", "Run 'winget install Swift.Toolchain'"])

    # 5. Swift Target Resources
    if toolchain.swift_resource_dir and toolchain.swift_resource_dir.is_dir():
        rows.append([f"{fg('GREEN', '✓')} Swift Target Libs", "iphoneos/arm64", str(toolchain.swift_resource_dir)])
    else:
        rows.append([f"{fg('YELLOW', '!')} Swift Target Libs", "MISSING (Swift only)", "Required for Swift iOS builds"])

    # 6. iOS SDK
    if toolchain.sdk_dir and toolchain.sdk_dir.is_dir():
        frameworks_count = len(list((toolchain.sdk_dir / "System" / "Library" / "Frameworks").glob("*.framework")))
        rows.append([f"{fg('GREEN', '✓')} iOS SDK ({toolchain.sdk_dir.name})", f"{frameworks_count} frameworks", str(toolchain.sdk_dir)])
    else:
        rows.append([f"{fg('RED', '✗')} iOS SDK", "MISSING", "Run 'nyx sdk install 26.5'"])

    # 7. ldid
    if toolchain.ldid and toolchain.ldid.is_file():
        rows.append([f"{fg('GREEN', '✓')} Code Signer (ldid)", "Ad-hoc signer", str(toolchain.ldid)])
    else:
        rows.append([f"{fg('RED', '✗')} Code Signer (ldid)", "MISSING", "tools/ldid.exe not found"])

    # 8. Mach-O Patcher
    if toolchain.patch_macho and toolchain.patch_macho.is_file():
        rows.append([f"{fg('GREEN', '✓')} Mach-O Patcher", "Patch #31 verified", str(toolchain.patch_macho)])
    else:
        rows.append([f"{fg('RED', '✗')} Mach-O Patcher", "MISSING", "tools/patch_macho.py not found"])

    # 9. Compiler Runtime
    if toolchain.clang_rt and toolchain.clang_rt.is_file():
        rows.append([f"{fg('GREEN', '✓')} Compiler Runtime", "ARM64/ARM64e", str(toolchain.clang_rt)])
    else:
        rows.append([f"{fg('YELLOW', '!')} Compiler Runtime", "MISSING", "libclang_rt.ios.a not found"])

    table_lines = render_column_table(
        headers=headers,
        rows=rows,
        width=w - 4
    )
    doctor_panel = render_panel(
        title="ENVIRONMENT HEALTH",
        content_lines=table_lines,
        badge="DIAGNOSTICS",
        width=w,
        border_color="SLATE_GRAY",
        title_color="CYAN_ELEC"
    )
    print(doctor_panel)
    print()

    # Storage layout panel
    import nyxwin.config.paths as npaths
    storage_lines = [
        f"Active Project: {toolchain.workspace_dir or 'None'}",
        f"Storage Root:   {npaths.USER_CONFIG_DIR} (Build, Cache, SDKs, Backups)",
    ]
    storage_p = render_panel(
        title="STORAGE & RUNTIME LAYOUT",
        content_lines=storage_lines,
        badge="",
        width=w,
        border_color="SLATE_GRAY",
        title_color="GRAY_MUTED"
    )
    print(storage_p)
    print()
    print(render_footer([("Enter / Esc", "Back to Menu")], width=w))
    wait_for_enter()

# Compatibility aliases
screen_projects_manager = screen_open_project
screen_project_dashboard = screen_project_tools
screen_switch_workspace = screen_open_project
screen_manage_workspaces = screen_open_project
screen_clean_cache = screen_global_tools

def run_interactive_menu():
    """Main interactive terminal loop for NyxWin."""
    toolchain = Toolchain()
    selected_idx = 0

    while True:
        menu_title, menu_options, has_active_proj, curr_p = get_main_menu_state(toolchain)

        if has_active_proj and curr_p:
            # STATE B: Active Project Dashboard
            cfg = load_project_config(curr_p) or {}
            proj_name = cfg.get("Name") or cfg.get("CFBundleName") or curr_p.name

            choice = prompt_menu(
                f"{menu_title}\n\n  Select an action:",
                menu_options,
                selected_index=min(selected_idx, len(menu_options) - 1),
                breadcrumb=f"NYXWIN › {proj_name.upper()}"
            )

            if choice in (-1, 5):
                clear_screen()
                print(f"\n{Color.CYAN}Thank you for using NyxWin! Goodbye.{Color.RESET}\n")
                break

            selected_idx = choice

            if choice == 0:
                # Direct Build: Start compilation immediately using project entitlements (Config/Entitlements.plist)
                screen_build_project_flow(toolchain, curr_p)
            elif choice == 1:
                screen_project_config(toolchain, curr_p)
            elif choice == 2:
                screen_project_tools(toolchain, curr_p)
            elif choice == 3:
                screen_open_project(toolchain)
            elif choice == 4:
                screen_global_tools(toolchain)

        else:
            # STATE A: No active project
            choice = prompt_menu(
                f"{menu_title}\n\n  Select an action:",
                menu_options,
                selected_index=min(selected_idx, len(menu_options) - 1),
                breadcrumb="NYXWIN"
            )

            if choice in (-1, 4):
                clear_screen()
                print(f"\n{Color.CYAN}Thank you for using NyxWin! Goodbye.{Color.RESET}\n")
                break

            selected_idx = choice

            if choice == 0:
                screen_open_project(toolchain)
            elif choice == 1:
                screen_create_project(toolchain)
            elif choice == 2:
                screen_import_project(toolchain)
            elif choice == 3:
                screen_global_tools(toolchain)
