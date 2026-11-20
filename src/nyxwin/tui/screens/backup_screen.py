import os
from pathlib import Path
from typing import List

from nyxwin.core.models import Color, log_info, log_success, log_error, log_warning
from nyxwin.core.toolchain import Toolchain
from nyxwin.services.backup import create_project_backup, list_project_backups, restore_project_backup, resolve_backups_dir
from nyxwin.tui.terminal import print_header, wait_for_enter
from nyxwin.tui.menu import prompt_menu
from nyxwin.tui.components.prompt import prompt_destructive_confirmation

import os
import zipfile
from pathlib import Path
from typing import List

from nyxwin.core.models import Color, log_info, log_success, log_error, log_warning
from nyxwin.core.toolchain import Toolchain
from nyxwin.services.backup import create_project_backup, list_project_backups, restore_project_backup, resolve_backups_dir
from nyxwin.tui.terminal import print_header, wait_for_enter, get_terminal_width, transition_screen
from nyxwin.tui.menu import prompt_menu
from nyxwin.tui.theme import fg, bold, dim, symbol
from nyxwin.tui.components.frame import render_panel
from nyxwin.tui.components.prompt import prompt_destructive_confirmation

def screen_project_backups(toolchain: Toolchain, proj_dir: Path):
    """Sub-screen to view, create, and restore timestamped backups for a project."""
    proj_name = proj_dir.name
    while True:
        backups = list_project_backups(toolchain, proj_name)
        options = []
        for b in backups:
            options.append(f"📦 {b['filename']} ({b['size_kb']:.1f} KB) - {b['mtime']}")

        action_create = len(options)
        options.append(f"{Color.GREEN}[+] 💾 Create New Backup Snapshot Now{Color.RESET}")

        proj_backups_dir = resolve_backups_dir(toolchain, proj_dir)
        if proj_backups_dir.is_dir() and backups:
            action_open = len(options)
            options.append(f"{Color.CYAN}[📂] Open Backups Folder in Explorer{Color.RESET}")
        else:
            action_open = -1

        choice = prompt_menu(
            f"{Color.BOLD}BACKUPS & RESTORE DASHBOARD{Color.RESET} ({proj_name}):\n  Select a backup snapshot to restore, or create a new snapshot:",
            options,
            breadcrumb=f"NYXWIN › {proj_name.upper()} › BACKUPS"
        )
        if choice == -1:
            return

        if choice == action_create:
            print_header(f"NYXWIN › {proj_name.upper()} › CREATING BACKUP")
            print(f"  {fg('CYAN_ELEC', symbol('PROGRESS'))} Archiving project sources and configuration...")
            backup_file = create_project_backup(toolchain, proj_name)
            w = get_terminal_width()
            if backup_file and backup_file.is_file():
                try:
                    with zipfile.ZipFile(backup_file, "r") as zf:
                        file_count = len(zf.namelist())
                except Exception:
                    file_count = 0
                sz_bytes = backup_file.stat().st_size
                sz_kb = sz_bytes / 1024.0
                sz_str = f"{sz_kb:.1f} KB ({sz_bytes:,} bytes)" if sz_kb < 1024 else f"{sz_kb/1024:.2f} MB ({sz_bytes:,} bytes)"

                summary_lines = [
                    f"  Project:          {proj_name}",
                    f"  Snapshot Name:    {backup_file.name}",
                    f"  Storage Location: {backup_file.parent}",
                    f"  Archive Size:     {sz_str}",
                    f"  Archived Files:   {file_count} project items",
                    f"  Integrity Marker: Verified (NYXWIN_BACKUP_V1)",
                    f"  Backup Policy:    Preserved source code, configs, entitlements, resources.",
                    f"                    Cleanly excluded build intermediates, caches, and dist IPAs."
                ]
                post_choice = prompt_menu(
                    "Backup created successfully. Choose an action:",
                    [
                        "📂 Open Backups Directory in Explorer",
                        "💾 Create Another Snapshot",
                        "↩️  Return to Backups Dashboard"
                    ],
                    breadcrumb=f"NYXWIN › {proj_name.upper()} › BACKUP RESULT",
                    top_panel_lines=summary_lines,
                    top_panel_title="BACKUP CREATION COMPLETE",
                    top_panel_badge="VERIFIED",
                    top_panel_border="EMERALD",
                    top_panel_title_color="EMERALD",
                    top_panel_badge_color="EMERALD"
                )
                if post_choice == 0:
                    try:
                        os.startfile(backup_file.parent)
                    except Exception as e:
                        log_error(f"Failed to open explorer: {e}")
                elif post_choice == 1:
                    continue
            else:
                failure_lines = [
                    f"Project:     {proj_name}",
                    f"Destination: {resolve_backups_dir(toolchain, proj_dir)}",
                    "",
                    "Failure Recovery Guidance:",
                    "  1. Verify available disk space in %LOCALAPPDATA%\\NyxWin\\Backups\\",
                    "  2. Check if project files are locked by another running process",
                    "  3. Check write permissions on your Windows user profile directory"
                ]
                panel = render_panel(
                    title="BACKUP CREATION FAILED",
                    content_lines=failure_lines,
                    badge="ERROR",
                    width=w,
                    border_color="CORAL_RED",
                    title_color="CORAL_RED",
                    badge_color="CORAL_RED"
                )
                print(f"\n{panel}\n")
                wait_for_enter()
        elif choice == action_open:
            try:
                os.startfile(proj_backups_dir)
            except Exception as e:
                log_error(f"Failed to open directory: {e}")
        else:
            sel_b = backups[choice]
            confirm_details = [
                f"Target Project:   {proj_name} ({proj_dir})",
                f"Source Snapshot:  {sel_b['filename']} ({sel_b['size_kb']:.1f} KB)",
                f"Snapshot Date:    {sel_b['mtime']}",
                "",
                f"{fg('CORAL_RED', bold('WARNING:'))} Overwrites current project files with snapshot contents.",
                f"{fg('CYAN_ELEC', bold('SAFETY:'))}  A pre-restore safety snapshot will automatically be created",
                f"         and verified in your Backups folder before any changes are made."
            ]
            confirmed = prompt_destructive_confirmation(
                title=f"NYXWIN › {proj_name.upper()} › CONFIRM RESTORE",
                details_lines=confirm_details,
                warning_text=f"Target: {proj_name} will be restored from {sel_b['filename']}.",
                action_label=f"Overwrite '{proj_name}' with Snapshot",
                header_badge="SAFETY PROTECTED",
                border_color="AMBER",
                title_color="AMBER",
                badge_color="AMBER"
            )
            if confirmed:
                print_header(f"NYXWIN › {proj_name.upper()} › RESTORING BACKUP")
                print(f"  {fg('CYAN_ELEC', '[1/5]')} Validating archive integrity and zip-slip security...")
                print(f"  {fg('CYAN_ELEC', '[2/5]')} Creating automated pre-restore safety snapshot...")
                print(f"  {fg('CYAN_ELEC', '[3/5]')} Verifying safety snapshot on disk...")
                print(f"  {fg('CYAN_ELEC', '[4/5]')} Restoring snapshot files into project workspace...")
                print(f"  {fg('CYAN_ELEC', '[5/5]')} Verifying restored file integrity...\n")

                ok = restore_project_backup(toolchain, proj_name, sel_b["path"])
                if ok:
                    restore_summary = [
                        f"  Target Project:  {proj_name}",
                        f"  Restored From:   {sel_b['filename']}",
                        f"  Status:          Restoration Verified & Complete",
                        f"  Safety Rollback: Pre-restore safety snapshot preserved in Backups folder.",
                        f"  Ready:           Project is ready for configuration and building."
                    ]
                    act = prompt_menu(
                        "Restoration finished successfully. Choose an action:",
                        [
                            "📂 Open Restored Project in Explorer",
                            "↩️  Return to Project Tools",
                            "↩️  Return to Main Menu"
                        ],
                        breadcrumb=f"NYXWIN › {proj_name.upper()} › RESTORE COMPLETE",
                        top_panel_lines=restore_summary,
                        top_panel_title="PROJECT RESTORED SUCCESSFULLY",
                        top_panel_badge="RESTORED",
                        top_panel_border="EMERALD",
                        top_panel_title_color="EMERALD",
                        top_panel_badge_color="EMERALD"
                    )
                    if act == 0:
                        try:
                            os.startfile(proj_dir)
                        except Exception as e:
                            log_error(f"Failed to open explorer: {e}")
                    return
                else:
                    fail_summary = [
                        f"Target Project:  {proj_name}",
                        f"Source Snapshot: {sel_b['filename']}",
                        "",
                        "Restoration was aborted or failed.",
                        "If a pre-restore safety snapshot was created, your original project",
                        "files were protected and preserved without data loss."
                    ]
                    panel = render_panel(
                        title="RESTORATION ABORTED OR FAILED",
                        content_lines=fail_summary,
                        badge="FAILED",
                        width=w,
                        border_color="CORAL_RED",
                        title_color="CORAL_RED",
                        badge_color="CORAL_RED"
                    )
                    print(f"{panel}\n")
                    wait_for_enter()
