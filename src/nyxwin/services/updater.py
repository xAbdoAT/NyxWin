"""
NyxWin Self-Update and Version Check Service.

Supports checking and downloading updates from:
  1. Official GitHub Releases (default: 'release' channel)
  2. Latest Git repository branch ('dev' / 'main' channel)
"""
import json
import re
import shutil
import subprocess
import urllib.request
import urllib.error
import zipfile
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

import nyxwin
from nyxwin.config.paths import get_package_root, get_temp_root
from nyxwin.core.models import log_info, log_success, log_warning, log_error

GITHUB_REPO = "xAbdoAT/NyxWin"
RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
COMMITS_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/commits/main"
RAW_INIT_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/src/nyxwin/__init__.py"
MAIN_ZIP_URL = f"https://github.com/{GITHUB_REPO}/archive/refs/heads/main.zip"


def parse_semver(version_str: str) -> Tuple[int, int, int]:
    """Parses a version string like 'v1.2.3' or '1.0.0' into a comparable (major, minor, patch) tuple."""
    if not version_str:
        return (0, 0, 0)
    cleaned = version_str.strip().lstrip("vV")
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", cleaned)
    if match:
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    parts = re.findall(r"\d+", cleaned)
    nums = [int(p) for p in parts[:3]]
    while len(nums) < 3:
        nums.append(0)
    return (nums[0], nums[1], nums[2])


def _fetch_json(url: str, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"NyxWin-Updater/{nyxwin.__version__}",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_text(url: str, timeout: float = 5.0) -> Optional[str]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"NyxWin-Updater/{nyxwin.__version__}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def check_for_updates(channel: str = "release", timeout: float = 5.0) -> Dict[str, Any]:
    """
    Checks GitHub for available updates on either the 'release' or 'dev' (main branch) channel.
    """
    current_ver = getattr(nyxwin, "__version__", "1.0.0")
    result: Dict[str, Any] = {
        "checked": False,
        "update_available": False,
        "current_version": current_ver,
        "latest_version": current_ver,
        "latest_commit": None,
        "channel": channel,
        "download_url": MAIN_ZIP_URL,
        "html_url": f"https://github.com/{GITHUB_REPO}",
        "release_notes": "",
        "error": None,
    }

    try:
        if channel == "release":
            try:
                rel_data = _fetch_json(RELEASES_API_URL, timeout=timeout)
                if rel_data and "tag_name" in rel_data:
                    tag = str(rel_data["tag_name"]).lstrip("vV")
                    result["checked"] = True
                    result["latest_version"] = tag
                    result["download_url"] = f"https://github.com/{GITHUB_REPO}/archive/refs/tags/{rel_data['tag_name']}.zip"
                    result["html_url"] = rel_data.get("html_url", result["html_url"])
                    result["release_notes"] = rel_data.get("body", "") or ""
                    result["update_available"] = parse_semver(tag) > parse_semver(current_ver)
                    return result
            except urllib.error.HTTPError as he:
                if he.code != 404:
                    raise
                # 404 means no GitHub Release published yet; fall back to checking main branch __init__.py

        # Check main branch (__init__.py version + latest commit SHA)
        init_text = _fetch_text(RAW_INIT_URL, timeout=timeout)
        remote_ver = current_ver
        if init_text:
            m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', init_text)
            if m:
                remote_ver = m.group(1).strip()

        commit_sha = None
        try:
            commit_data = _fetch_json(COMMITS_API_URL, timeout=timeout)
            if commit_data and "sha" in commit_data:
                commit_sha = str(commit_data["sha"])[:7]
        except Exception:
            pass

        result["checked"] = True
        result["latest_version"] = remote_ver
        result["latest_commit"] = commit_sha
        result["download_url"] = MAIN_ZIP_URL
        if channel in ("dev", "main"):
            # On dev channel, compares semver or allows updating to latest main commit
            result["update_available"] = parse_semver(remote_ver) > parse_semver(current_ver)
        else:
            result["update_available"] = parse_semver(remote_ver) > parse_semver(current_ver)

    except Exception as exc:
        result["error"] = str(exc)

    return result


def perform_update(
    target_dir: Optional[Path] = None,
    channel: str = "release",
    check_only: bool = False,
    force: bool = False,
) -> Tuple[bool, str]:
    """
    Checks for updates and optionally downloads & applies the update in-place.
    User projects, SDKs, caches, and backups in %LOCALAPPDATA%\\NyxWin are untouched.
    """
    install_dir = Path(target_dir).resolve() if target_dir else get_package_root().resolve()
    # If get_package_root() returned src/nyxwin instead of the repo root, step up to repo root if main.py exists
    if install_dir.name == "nyxwin" and install_dir.parent.name == "src":
        cand_root = install_dir.parent.parent
        if (cand_root / "main.py").is_file() or (cand_root / "pyproject.toml").is_file():
            install_dir = cand_root

    log_info(f"Checking for NyxWin updates on '{channel}' channel (Current: v{nyxwin.__version__})...")
    info = check_for_updates(channel=channel)

    if not info["checked"]:
        err = info.get("error") or "Unable to reach GitHub."
        return False, f"Update check failed: {err}"

    latest_ver = info["latest_version"]
    commit_suffix = f" (commit {info['latest_commit']})" if info.get("latest_commit") else ""

    if check_only:
        if info["update_available"]:
            return True, f"Update available: v{info['current_version']} -> v{latest_ver}{commit_suffix}. Run 'nyx update' to install."
        return True, f"NyxWin is up to date (v{info['current_version']}{commit_suffix})."

    if not info["update_available"] and not force and channel == "release":
        return True, f"NyxWin is already up to date (v{info['current_version']}). Use 'nyx update --dev' to pull latest main branch."

    # 1. If install_dir is a clean git checkout and git is available, try git pull when on dev/main
    git_dir = install_dir / ".git"
    if git_dir.is_dir() and channel in ("dev", "main") and shutil.which("git"):
        log_info(f"Updating Git repository at {install_dir}...")
        res = subprocess.run(
            ["git", "-C", str(install_dir), "pull", "--ff-only", "origin", "main"],
            capture_output=True,
            text=True,
        )
        if res.returncode == 0:
            return True, f"Updated NyxWin via git pull to v{latest_ver}{commit_suffix}."
        else:
            log_warning("Git fast-forward pull could not complete; falling back to archive download...")

    # 2. Download archive from GitHub and apply over install_dir
    temp_dir = get_temp_root() / "updater_staging"
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    zip_path = temp_dir / "nyxwin_update.zip"
    dl_url = info["download_url"]
    log_info(f"Downloading update archive from {dl_url}...")

    try:
        req = urllib.request.Request(
            dl_url,
            headers={"User-Agent": f"NyxWin-Updater/{nyxwin.__version__}"},
        )
        with urllib.request.urlopen(req, timeout=30.0) as resp, open(zip_path, "wb") as out_f:
            shutil.copyfileobj(resp, out_f)
    except Exception as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return False, f"Failed to download update archive: {exc}"

    extract_dir = temp_dir / "extracted"
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)
    except Exception as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return False, f"Failed to extract update archive: {exc}"

    # Locate the inner root directory containing src/nyxwin
    source_root = None
    for cand in [extract_dir] + [p for p in extract_dir.iterdir() if p.is_dir()]:
        if (cand / "src" / "nyxwin").is_dir():
            source_root = cand
            break

    if not source_root:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return False, "Downloaded archive did not contain a valid NyxWin source tree."

    # Copy updated application files into install_dir
    items_to_update = [
        "src",
        "docs",
        "main.py",
        "pyproject.toml",
        "install.ps1",
        "install.bat",
        "README.md",
        "SETUP_GUIDE.md",
        "LICENSE",
    ]
    try:
        for item_name in items_to_update:
            src_item = source_root / item_name
            dst_item = install_dir / item_name
            if src_item.is_dir():
                shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
            elif src_item.is_file():
                shutil.copy2(src_item, dst_item)
    except Exception as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return False, f"Failed while applying updated files: {exc}"

    shutil.rmtree(temp_dir, ignore_errors=True)
    return True, f"Successfully updated NyxWin to v{latest_ver}{commit_suffix} at {install_dir}!"
