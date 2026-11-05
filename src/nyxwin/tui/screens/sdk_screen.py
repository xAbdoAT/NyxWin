from pathlib import Path
from typing import List

from nyxwin.core.models import Color, log_info, log_success, log_error, log_warning
from nyxwin.core.toolchain import Toolchain
from nyxwin.services.sdk_manager import fetch_available_sdks, get_installed_sdks, install_sdk
from nyxwin.tui.terminal import print_header, prompt_input, wait_for_enter
from nyxwin.tui.menu import prompt_menu

def screen_sdk_manager(toolchain: Toolchain):
    """Interactive iOS SDK Manager Screen (List local SDKs, scrape GitHub, download)."""
    while True:
        installed = get_installed_sdks(toolchain)
        options = []
        for s in installed:
            active_badge = f" {Color.GREEN}★ (active){Color.RESET}" if s["is_active"] else ""
            options.append(f"📁 {s['name']} (iOS {s['version']}) - {s['frameworks_count']} frameworks{active_badge}")

        action_download = len(options)
        options.append(f"{Color.GREEN}[+] 🌐 Download SDK from Community Catalog (GitHub){Color.RESET}")

        action_refresh = len(options)
        options.append(f"{Color.CYAN}[⟳] 🔄 Refresh Installed SDKs{Color.RESET}")

        action_open_root = len(options)
        options.append(f"{Color.CYAN}[📂] 📁 Open SDKs Directory in Explorer{Color.RESET}")

        choice = prompt_menu(
            f"{Color.BOLD}iOS SDK MANAGER{Color.RESET} ({len(installed)} installed in %LOCALAPPDATA%\\NyxWin\\SDKs\\):\n  Select an installed SDK to inspect or download a new version:",
            options,
            breadcrumb="NYXWIN › SDK MANAGER"
        )
        if choice == -1:
            return

        if choice == action_download:
            print_header("NYXWIN › SDK MANAGER › DOWNLOAD")
            log_info("Fetching SDK catalog from GitHub repository...")
            available = fetch_available_sdks()
            if not available:
                log_error("Could not reach GitHub or load SDK tree. Check your internet connection.")
                wait_for_enter()
                continue

            dl_opts = []
            for a in available:
                is_inst = any(inst["name"] == a["name"] for inst in installed)
                inst_badge = f" {Color.GREEN}[INSTALLED]{Color.RESET}" if is_inst else ""
                size_mb = (a["size"] / (1024 * 1024)) if a["size"] else 0
                sz_str = f" (~{size_mb:.0f} MB)" if size_mb > 0 else ""
                dl_opts.append(f"{a['name']}{sz_str}{inst_badge}")

            dl_choice = prompt_menu(
                f"Available Pre-built SDKs ({len(available)} available from xybp888/iOS-SDKs):\n  Select an SDK to download and install:",
                dl_opts,
                breadcrumb="NYXWIN › SDK MANAGER › SELECT DOWNLOAD"
            )
            if dl_choice != -1:
                target_sdk = available[dl_choice]
                print_header(f"DOWNLOADING {target_sdk['name']}")
                install_sdk(toolchain, target_sdk["name"])
                wait_for_enter()
        elif choice == action_refresh:
            toolchain.sdk_dir = toolchain.find_sdk()
        elif choice == action_open_root:
            import os
            from nyxwin.config.paths import get_sdks_root
            sdks_dir = get_sdks_root()
            if sdks_dir.is_dir():
                os.startfile(sdks_dir)
            else:
                log_warning(f"SDK directory does not exist: {sdks_dir}")
                wait_for_enter()
        else:
            sel_sdk = installed[choice]
            act = prompt_menu(
                f"Selected SDK: {Color.CYAN}{sel_sdk['name']}{Color.RESET}\nPath: {sel_sdk['path']}",
                ["Set as Active SDK for this session", "Open SDK Folder in Explorer"]
            )
            if act == 0:
                toolchain.sdk_dir = sel_sdk["path"]
                log_success(f"Set active SDK to: {sel_sdk['name']}")
                wait_for_enter()
            elif act == 1:
                try:
                    import os
                    os.startfile(sel_sdk["path"])
                except Exception as e:
                    log_error(f"Failed to open directory: {e}")
