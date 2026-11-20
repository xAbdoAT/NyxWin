import os
import json
import zipfile
import urllib.request
import shutil
from pathlib import Path
from typing import List, Dict, Any, Optional

from nyxwin.core.models import Color, log_info, log_success, log_error, log_warning
from nyxwin.core.toolchain import Toolchain
from nyxwin.config.paths import get_sdks_root
from nyxwin.tui.components.status import render_progress_bar

GITHUB_API_URL = "https://api.github.com/repos/xybp888/iOS-SDKs/git/trees/master?recursive=1"

def fetch_available_sdks() -> List[Dict[str, str]]:
    """Fetches list of available pre-built iOS SDKs from xybp888/iOS-SDKs repository on GitHub."""
    req = urllib.request.Request(
        GITHUB_API_URL,
        headers={"User-Agent": "NyxWin-Toolchain-Manager"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            sdks = []
            for item in data.get("tree", []):
                path = item.get("path", "")
                if path.startswith("iPhoneOS") and path.endswith(".sdk.zip"):
                    clean_name = path.replace(".zip", "")
                    ver = clean_name.replace("iPhoneOS", "").replace(".sdk", "")
                    sdks.append({
                        "name": clean_name,
                        "version": ver,
                        "filename": path,
                        "url": f"https://github.com/xybp888/iOS-SDKs/raw/master/{path}",
                        "size": item.get("size", 0)
                    })

            def parse_v(x):
                parts = []
                for p in x["version"].split("."):
                    try:
                        parts.append(int(p))
                    except ValueError:
                        parts.append(0)
                return parts

            sdks.sort(key=parse_v, reverse=True)
            return sdks
    except Exception as e:
        log_error(f"Failed to query online SDK catalog: {e}")
        return []

def get_installed_sdks(toolchain: Toolchain) -> List[Dict[str, Any]]:
    """Returns list of currently installed SDKs inside canonical SDKs directory (%LOCALAPPDATA%\\NyxWin\\SDKs\\)."""
    canonical_root = get_sdks_root()
    search_dirs = [canonical_root]
    # Check toolchain.root_dir / "sdk" as fallback if distinct
    legacy_root = toolchain.root_dir / "sdk"
    if legacy_root.is_dir() and legacy_root.resolve() != canonical_root.resolve():
        search_dirs.append(legacy_root)

    installed = []
    seen_names = set()
    for sdk_root in search_dirs:
        if not sdk_root.is_dir():
            continue
        for d in sorted(sdk_root.iterdir()):
            if d.is_dir() and d.name.startswith("iPhoneOS") and d.name.endswith(".sdk") and d.name not in seen_names:
                fw_count = len(list((d / "System" / "Library" / "Frameworks").glob("*.framework"))) if (d / "System" / "Library" / "Frameworks").is_dir() else 0
                ver = d.name.replace("iPhoneOS", "").replace(".sdk", "")
                is_active = bool(toolchain.sdk_dir and toolchain.sdk_dir.name == d.name)
                installed.append({
                    "name": d.name,
                    "version": ver,
                    "path": d,
                    "frameworks_count": fw_count,
                    "is_active": is_active
                })
                seen_names.add(d.name)
    return installed

def install_sdk(toolchain: Toolchain, version: str) -> bool:
    """Downloads and installs an SDK from xybp888/iOS-SDKs repository into canonical SDKs directory (%LOCALAPPDATA%\\NyxWin\\SDKs\\)."""
    target_name = version if version.endswith(".sdk") else f"iPhoneOS{version}.sdk"
    sdk_root = get_sdks_root()
    dest_dir = sdk_root / target_name
    os.makedirs(sdk_root, exist_ok=True)

    if dest_dir.is_dir() and (dest_dir / "System" / "Library" / "Frameworks").is_dir():
        log_warning(f"SDK '{target_name}' is already installed at: {dest_dir}")
        return True

    filename = f"{target_name}.zip"
    url = f"https://github.com/xybp888/iOS-SDKs/raw/master/{filename}"
    zip_path = sdk_root / filename

    log_info(f"Downloading {target_name} to {sdk_root}...")
    try:
        import time
        t_start = time.time()
        last_print = 0.0

        def reporthook(count, block_size, total_size):
            nonlocal last_print
            now = time.time()
            if now - last_print < 0.1 and count * block_size < total_size:
                return
            last_print = now
            if total_size > 0:
                pct = min(100.0, (count * block_size * 100.0) / total_size)
                mb_down = (count * block_size) / (1024 * 1024)
                mb_total = total_size / (1024 * 1024)
                elapsed = max(0.1, now - t_start)
                speed = mb_down / elapsed
                bar = render_progress_bar(pct, bar_width=20)
                sys.stdout.write(f"\r  {bar} ({mb_down:.1f} MB / {mb_total:.1f} MB) · {speed:.1f} MB/s")
                sys.stdout.flush()

        urllib.request.urlretrieve(url, zip_path, reporthook)
        print()
        log_success(f"Downloaded {filename}")

        log_info(f"Extracting {filename} to {sdk_root}...")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(sdk_root)

        if zip_path.is_file():
            os.remove(zip_path)

        # Refresh toolchain active sdk
        toolchain.sdk_dir = toolchain.find_sdk()
        log_success(f"Successfully installed {target_name}!")
        return True
    except Exception as e:
        log_error(f"Failed to download or extract SDK: {e}")
        return False
