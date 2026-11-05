import plistlib
from pathlib import Path
from typing import Dict, Any

from nyxwin.core.models import Color, log_success, log_error, log_info
from nyxwin.core.toolchain import Toolchain
from nyxwin.core.project import load_project_config, save_project_config, find_project_config_file
from nyxwin.services.icon import generate_app_icons
from nyxwin.tui.terminal import print_header, prompt_input, wait_for_enter
from nyxwin.tui.menu import prompt_menu

def screen_change_icon(toolchain: Toolchain, proj_dir: Path):
    """Sub-screen to manage application icons."""
    proj_name = proj_dir.name
    res_dir = proj_dir / "Resources"
    has_icon = (res_dir / "AppIcon60x60.png").is_file() or (res_dir / "AppIcon.png").is_file()
    icon_count = len(list(res_dir.glob("AppIcon*.png"))) if res_dir.is_dir() else 0
    status_str = f"Configured ({icon_count} icon assets in Resources/)" if has_icon else "None / Default"

    while True:
        icon_opts = [
            "🖼️   Select Master Image & Regenerate Icons (PNG / JPG)",
            "📂  Open Resources Folder in Explorer"
        ]
        choice = prompt_menu(
            f"Application Icons ({proj_name}):\n  Current Status: {status_str}",
            icon_opts,
            breadcrumb=f"NYXWIN › {proj_name.upper()} › SETTINGS › APP ICON"
        )
        if choice == -1:
            return

        if choice == 0:
            print_header(f"NYXWIN › {proj_name.upper()} › GENERATE ICONS")
            print(f"  {Color.WHITE}Provide a square PNG or JPG image (preferably 1024x1024 or 512x512).{Color.RESET}\n")
            img_path_str = prompt_input("Enter path to icon image (PNG/JPG)")
            if not img_path_str:
                continue

            img_p = Path(img_path_str.strip('"').strip("'"))
            if not img_p.is_file():
                log_error(f"File not found: {img_p}")
                wait_for_enter()
                continue

            generate_app_icons(toolchain, proj_dir.name, img_p)
            wait_for_enter()
            has_icon = (res_dir / "AppIcon60x60.png").is_file() or (res_dir / "AppIcon.png").is_file()
            icon_count = len(list(res_dir.glob("AppIcon*.png"))) if res_dir.is_dir() else 0
            status_str = f"Configured ({icon_count} icon assets in Resources/)" if has_icon else "None / Default"
        elif choice == 1:
            try:
                import os
                os.makedirs(res_dir, exist_ok=True)
                os.startfile(res_dir)
            except Exception as e:
                log_error(f"Failed to open directory: {e}")
                wait_for_enter()

def screen_flags_editor(proj_dir: Path, cfg: dict, flag_key: str, title: str, proj_name: str):
    """Sub-screen to add, remove, and reorder compiler/linker flags."""
    while True:
        flags = cfg.get(flag_key, [])
        options = []
        for i, flg in enumerate(flags):
            options.append(f"[{i+1}] {flg}")
        options.append(f"{Color.GREEN}[+] Add New Flag{Color.RESET}")

        choice = prompt_menu(
            f"{Color.BOLD}Edit {title}{Color.RESET} ({len(flags)} flags currently defined):\n  Select a flag to edit/remove or add a new one:",
            options,
            breadcrumb=f"NYXWIN › {proj_name.upper()} › SETTINGS › {title.upper()}"
        )
        if choice == -1:
            return

        if choice == len(flags):
            # Add new flag
            print_header(f"NYXWIN › {proj_name.upper()} › SETTINGS › ADD FLAG")
            new_val = prompt_input(f"Enter new {title} flag (e.g. -DDEBUG or -framework MyFw)")
            if new_val:
                flags.append(new_val)
                cfg[flag_key] = flags
                save_project_config(proj_dir, cfg)
                log_success(f"Added flag: {new_val}")
                wait_for_enter()
        else:
            # Edit or remove existing flag
            sel_flag = flags[choice]
            act_options = [
                f"✏️  Edit flag value",
                f"🗑️  Remove flag",
                f"⬆️  Move Up",
                f"⬇️  Move Down"
            ]
            act_choice = prompt_menu(
                f"Selected Flag: {Color.CYAN}{sel_flag}{Color.RESET}\nChoose action:",
                act_options,
                breadcrumb=f"NYXWIN › {proj_name.upper()} › SETTINGS › FLAG ACTION"
            )
            if act_choice == 0:
                print_header(f"NYXWIN › {proj_name.upper()} › SETTINGS › EDIT FLAG")
                edited = prompt_input(f"Edit flag value", sel_flag)
                if edited and edited != sel_flag:
                    flags[choice] = edited
                    cfg[flag_key] = flags
                    save_project_config(proj_dir, cfg)
            elif act_choice == 1:
                flags.pop(choice)
                cfg[flag_key] = flags
                save_project_config(proj_dir, cfg)
            elif act_choice == 2 and choice > 0:
                flags[choice], flags[choice-1] = flags[choice-1], flags[choice]
                cfg[flag_key] = flags
                save_project_config(proj_dir, cfg)
            elif act_choice == 3 and choice < len(flags) - 1:
                flags[choice], flags[choice+1] = flags[choice+1], flags[choice]
                cfg[flag_key] = flags
                save_project_config(proj_dir, cfg)

def screen_entitlements_manager(proj_dir: Path, proj_name: str):
    """Sub-screen to view, toggle, and edit entitlements in Config/Entitlements.plist."""
    ent_file = proj_dir / "Config" / "Entitlements.plist"
    while True:
        ent_data = {}
        if ent_file.is_file():
            try:
                with open(ent_file, "rb") as f:
                    ent_data = plistlib.load(f)
            except Exception:
                ent_data = {}

        keys = sorted(list(ent_data.keys()))
        options = []
        max_k_len = max((len(k) for k in keys), default=30)
        col_k_w = min(max(max_k_len, 26), 34)

        for k in keys:
            v = ent_data[k]
            if isinstance(v, bool):
                state_badge = f"{Color.GREEN}[X]{Color.RESET}" if v else f"{Color.DARK_GRAY}[ ]{Color.RESET}"
                val_display = f"{Color.GREEN}true {Color.RESET}" if v else f"{Color.RED}false{Color.RESET}"
                action_hint = f"{Color.DARK_GRAY}› toggle{Color.RESET}"
            elif isinstance(v, list):
                state_badge = f"{Color.YELLOW}[#]{Color.RESET}"
                val_display = f"{Color.CYAN}[{len(v)} items]{Color.RESET}"
                action_hint = f"{Color.DARK_GRAY}› edit{Color.RESET}"
            elif isinstance(v, str):
                state_badge = f"{Color.CYAN}[S]{Color.RESET}"
                v_disp = v if len(v) <= 12 else v[:9] + "..."
                val_display = f"{Color.WHITE}\"{v_disp}\"{Color.RESET}"
                action_hint = f"{Color.DARK_GRAY}› edit{Color.RESET}"
            else:
                state_badge = f"{Color.MAGENTA}[*]{Color.RESET}"
                val_display = f"{Color.WHITE}{v}{Color.RESET}"
                action_hint = f"{Color.DARK_GRAY}› edit{Color.RESET}"

            k_padded = k.ljust(col_k_w)
            options.append(f"{state_badge} {k_padded} {val_display.ljust(12)} {action_hint}")

        action_add = len(options)
        options.append(f"{Color.GREEN}[+] Add Entitlement Key{Color.RESET}")

        action_trollstore = len(options)
        options.append(f"{Color.YELLOW}[★] Load Jailbreak / TrollStore Entitlements (Advanced){Color.RESET}")

        action_sandbox = len(options)
        options.append(f"{Color.BLUE}[★] Load Clean Sandboxed Entitlements{Color.RESET}")

        ent_cnt = len(keys)
        choice = prompt_menu(
            f"{Color.BOLD}Entitlements Manager{Color.RESET} ({ent_file.name} — {ent_cnt} keys configured):\n"
            f"  Select an entitlement to configure, or load a preset:",
            options,
            breadcrumb=f"NYXWIN › {proj_name.upper()} › SETTINGS › ENTITLEMENTS"
        )
        if choice == -1:
            return

        if choice == action_add:
            print_header(f"NYXWIN › {proj_name.upper()} › SETTINGS › ADD ENTITLEMENT")
            new_k = prompt_input("Enter entitlement key (e.g. get-task-allow)")
            if new_k:
                type_choice = prompt_menu(
                    "Select Value Type:",
                    ["Boolean (true)", "Boolean (false)", "String value", "Array of strings"],
                    breadcrumb=f"NYXWIN › {proj_name.upper()} › SETTINGS › ADD ENTITLEMENT"
                )
                if type_choice == -1:
                    continue
                if type_choice == 0:
                    ent_data[new_k] = True
                elif type_choice == 1:
                    ent_data[new_k] = False
                elif type_choice == 2:
                    ent_data[new_k] = prompt_input("Enter string value")
                elif type_choice == 3:
                    raw = prompt_input("Enter comma-separated items")
                    ent_data[new_k] = [x.strip() for x in raw.split(",") if x.strip()]
                with open(ent_file, "wb") as f:
                    plistlib.dump(ent_data, f)
                log_success(f"Added entitlement: {new_k}")
                wait_for_enter()
        elif choice == action_trollstore:
            print_header(f"NYXWIN › {proj_name.upper()} › SETTINGS › LOAD PRESET")
            print(f"  {Color.YELLOW}This will overwrite current entitlements with the Jailbreak / TrollStore preset:{Color.RESET}")
            print(f"  {Color.DIM}Note: Injected private keys require OS-level authorization (CoreTrust/trustcache) to bypass sandboxing.{Color.RESET}\n")
            print("    • platform-application: true")
            print("    • com.apple.private.security.no-sandbox: true")
            print("    • com.apple.private.security.no-container: true")
            print("    • task_for_pid-allow: true")
            print("    • get-task-allow: true\n")
            confirm = prompt_input("Overwrite current entitlements? (y/N)")
            if confirm and confirm.strip().lower() in ("y", "yes"):
                ent_data = {
                    "platform-application": True,
                    "com.apple.private.security.no-sandbox": True,
                    "com.apple.private.security.no-container": True,
                    "task_for_pid-allow": True,
                    "get-task-allow": True,
                }
                with open(ent_file, "wb") as f:
                    plistlib.dump(ent_data, f)
                log_success("Loaded Jailbreak / TrollStore Entitlements Preset!")
                wait_for_enter()
        elif choice == action_sandbox:
            print_header(f"NYXWIN › {proj_name.upper()} › SETTINGS › LOAD PRESET")
            print(f"  {Color.BLUE}This will overwrite current entitlements with the Sandboxed preset:{Color.RESET}")
            print("    • get-task-allow: true\n")
            confirm = prompt_input("Overwrite current entitlements? (y/N)")
            if confirm and confirm.strip().lower() in ("y", "yes"):
                ent_data = {
                    "get-task-allow": True,
                }
                with open(ent_file, "wb") as f:
                    plistlib.dump(ent_data, f)
                log_success("Loaded Sandboxed Entitlements!")
                wait_for_enter()
        else:
            sel_k = keys[choice]
            cur_v = ent_data[sel_k]
            if isinstance(cur_v, bool):
                target_state = not cur_v
                state_str = "false" if cur_v else "true"
                act = prompt_menu(
                    f"Entitlement: {Color.CYAN}{sel_k}{Color.RESET}\nCurrent Value: {Color.GREEN if cur_v else Color.RED}{'true' if cur_v else 'false'}{Color.RESET}\nChoose action:",
                    [
                        f"🔄  Toggle Value (set to {state_str})",
                        "🗑️   Remove Entitlement Key",
                    ],
                    breadcrumb=f"NYXWIN › {proj_name.upper()} › SETTINGS › EDIT ENTITLEMENT"
                )
                if act == 0:
                    ent_data[sel_k] = target_state
                    with open(ent_file, "wb") as f:
                        plistlib.dump(ent_data, f)
                elif act == 1:
                    confirm = prompt_input(f"Remove '{sel_k}'? (y/N)")
                    if confirm and confirm.strip().lower() in ("y", "yes"):
                        ent_data.pop(sel_k, None)
                        with open(ent_file, "wb") as f:
                            plistlib.dump(ent_data, f)
            else:
                act = prompt_menu(
                    f"Entitlement: {Color.CYAN}{sel_k}{Color.RESET}\nCurrent Value: {Color.WHITE}{cur_v}{Color.RESET}\nChoose action:",
                    ["✏️   Edit Value", "🗑️   Remove Entitlement Key"],
                    breadcrumb=f"NYXWIN › {proj_name.upper()} › SETTINGS › EDIT ENTITLEMENT"
                )
                if act == 0:
                    print_header(f"NYXWIN › {proj_name.upper()} › SETTINGS › EDIT VALUE")
                    new_val_str = prompt_input("New value", str(cur_v))
                    if new_val_str is not None:
                        if isinstance(cur_v, list):
                            ent_data[sel_k] = [x.strip() for x in new_val_str.split(",") if x.strip()]
                        else:
                            ent_data[sel_k] = new_val_str
                        with open(ent_file, "wb") as f:
                            plistlib.dump(ent_data, f)
                elif act == 1:
                    confirm = prompt_input(f"Remove '{sel_k}'? (y/N)")
                    if confirm and confirm.strip().lower() in ("y", "yes"):
                        ent_data.pop(sel_k, None)
                        with open(ent_file, "wb") as f:
                            plistlib.dump(ent_data, f)

def screen_project_config(toolchain: Toolchain, proj_dir: Path):
    """Full-featured Project Configuration Editor."""
    while True:
        cfg = load_project_config(proj_dir)
        if not cfg:
            log_error(f"Failed to load Project.plist from {proj_dir}")
            wait_for_enter()
            return

        proj_name = cfg.get("Name", proj_dir.name)
        exec_name = cfg.get("ExecutableName", proj_name)
        bundle_id = cfg.get("BundleIdentifier", "com.example.app")
        target_ver = str(cfg.get("DeploymentTarget", "17.0"))
        b_ver = str(cfg.get("Version", "1.0"))
        short_ver = str(cfg.get("BuildNumber", b_ver))
        clang_flags = cfg.get("ClangFlags", [])
        swift_flags = cfg.get("SwiftFlags", [])
        linker_flags = cfg.get("LinkerFlags", [])

        has_icon = (proj_dir / "Resources" / "AppIcon60x60.png").is_file() or (proj_dir / "Resources" / "AppIcon.png").is_file()
        icon_status = f"{Color.GREEN}Configured{Color.RESET}" if has_icon else f"{Color.YELLOW}None / Default{Color.RESET}"

        cfg_file, _ = find_project_config_file(proj_dir)
        cfg_label = cfg_file.name if cfg_file else "Project.plist"
        if cfg_file and cfg_file.parent.name == "Config":
            cfg_label = "Config/Project.plist"

        options = [
            f"🏷️   Display Name:            {Color.CYAN}{proj_name}{Color.RESET}",
            f"⚙️   Executable Name:         {Color.CYAN}{exec_name}{Color.RESET}",
            f"📦  Bundle Identifier:       {Color.CYAN}{bundle_id}{Color.RESET}",
            f"🔢  Bundle Version:          {Color.CYAN}{b_ver}{Color.RESET} (Short: {short_ver})",
            f"🎯  iOS Deployment Target:   {Color.CYAN}iOS {target_ver}{Color.RESET}",
            f"🖼️   Manage App Icon:         {icon_status}",
            f"📝  Clang Flags:             {Color.CYAN}[{len(clang_flags)} flags]{Color.RESET}",
            f"🦅  Swift Flags:             {Color.CYAN}[{len(swift_flags)} flags]{Color.RESET}",
            f"🔗  Linker Flags:            {Color.CYAN}[{len(linker_flags)} flags]{Color.RESET}",
            f"🛡️   Manage Entitlements:     {Color.CYAN}Config/Entitlements.plist{Color.RESET}"
        ]

        choice = prompt_menu(
            f"{Color.BOLD}PROJECT SETTINGS & CONFIGURATION{Color.RESET} ({proj_name}):\n  Config File: {cfg_label}\n  Select a setting to modify:",
            options,
            breadcrumb=f"NYXWIN › {proj_name.upper()} › SETTINGS"
        )
        if choice == -1:
            return

        if choice == 0:
            print_header(f"NYXWIN › {proj_name.upper()} › SETTINGS › DISPLAY NAME")
            new_val = prompt_input("Display Name", proj_name)
            if new_val and new_val != proj_name:
                cfg["Name"] = new_val
                save_project_config(proj_dir, cfg)
        elif choice == 1:
            print_header(f"NYXWIN › {proj_name.upper()} › SETTINGS › EXECUTABLE")
            new_val = prompt_input("Executable Binary Name", exec_name)
            if new_val and new_val != exec_name:
                cfg["ExecutableName"] = new_val
                save_project_config(proj_dir, cfg)
        elif choice == 2:
            print_header(f"NYXWIN › {proj_name.upper()} › SETTINGS › BUNDLE ID")
            new_val = prompt_input("Bundle Identifier", bundle_id)
            if new_val and new_val != bundle_id:
                cfg["BundleIdentifier"] = new_val
                save_project_config(proj_dir, cfg)
        elif choice == 3:
            print_header(f"NYXWIN › {proj_name.upper()} › SETTINGS › VERSION")
            new_ver = prompt_input("Marketing Version (e.g. 1.0.0)", b_ver)
            new_short = prompt_input("Build Number (e.g. 1)", short_ver)
            cfg["Version"] = new_ver
            cfg["BuildNumber"] = new_short
            save_project_config(proj_dir, cfg)
        elif choice == 4:
            valid_targets = toolchain.get_deployment_targets()
            target_opts = [f"iOS {vt}" for vt in valid_targets]
            cur_idx = valid_targets.index(target_ver) if target_ver in valid_targets else 0
            t_choice = prompt_menu(
                "Select Minimum iOS Deployment Target:",
                target_opts,
                selected_index=cur_idx,
                breadcrumb=f"NYXWIN › {proj_name.upper()} › SETTINGS › DEPLOYMENT TARGET"
            )
            if t_choice != -1:
                cfg["DeploymentTarget"] = valid_targets[t_choice]
                save_project_config(proj_dir, cfg)
        elif choice == 5:
            screen_change_icon(toolchain, proj_dir)
        elif choice == 6:
            screen_flags_editor(proj_dir, cfg, "ClangFlags", "Clang Flags", proj_name)
        elif choice == 7:
            screen_flags_editor(proj_dir, cfg, "SwiftFlags", "Swift Flags", proj_name)
        elif choice == 8:
            screen_flags_editor(proj_dir, cfg, "LinkerFlags", "Linker Flags", proj_name)
        elif choice == 9:
            screen_entitlements_manager(proj_dir, proj_name)
