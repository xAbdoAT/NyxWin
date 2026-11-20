import os
import stat
import time
import shutil
import hashlib
import zipfile
import plistlib
import threading
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

from nyxwin.core.models import Color, log_info, log_warning, log_success
from nyxwin.core.project import expand_macro_variables
from nyxwin.build.assets import flatten_xcassets
from nyxwin.build.signer import sign_embedded_framework
from nyxwin.build.process_manager import BuildCancellationController

# Fixed canonical ZIP timestamp for reproducible IPA archives (1980-01-01 00:00:00)
DETERMINISTIC_ZIP_DATETIME: Tuple[int, int, int, int, int, int] = (1980, 1, 1, 0, 0, 0)
DETERMINISTIC_COMPRESS_LEVEL: int = 6

# Temporary or OS metadata files that must never be packaged into an iOS .app bundle
_EXCLUDED_BUNDLE_FILENAMES = {
    ".ds_store",
    "thumbs.db",
    "desktop.ini",
}
_EXCLUDED_BUNDLE_DIRS = {
    "__pycache__",
    ".git",
    ".svn",
}

_MACHO_MAGIC_BYTES = {
    b"\xfe\xed\xfa\xce",  # MH_MAGIC
    b"\xce\xfa\xed\xfe",  # MH_CIGAM
    b"\xfe\xed\xfa\xcf",  # MH_MAGIC_64
    b"\xcf\xfa\xed\xfe",  # MH_CIGAM_64
    b"\xca\xfe\xba\xbe",  # FAT_MAGIC
    b"\xbe\xba\xfe\xca",  # FAT_CIGAM
}


def _is_excluded_bundle_entry(name: str, is_dir: bool = False) -> bool:
    """Returns True if a file or directory name is a temporary or OS junk artifact."""
    lower = name.lower()
    if is_dir:
        return lower in _EXCLUDED_BUNDLE_DIRS or lower.startswith(".nyx_tmp")
    if lower in _EXCLUDED_BUNDLE_FILENAMES:
        return True
    if lower.endswith(".tmp") or lower.startswith(".nyx_tmp") or lower.endswith(".pyc"):
        return True
    return False


def _is_macho_or_executable(file_path: Path, app_bundle_dir: Path, exec_name: Optional[str] = None) -> bool:
    """
    Determines whether a bundle file should receive executable POSIX mode bits (0755)
    in the IPA archive:
      - The primary bundle executable (<ProductName>.app/<ExecutableName>)
      - Embedded framework binary (<Fw>.framework/<Fw>)
      - Any file starting with a 32/64-bit or universal Mach-O magic header
    """
    try:
        rel = file_path.relative_to(app_bundle_dir)
        parts = rel.parts
        if len(parts) == 1 and exec_name and parts[0] == exec_name:
            return True
        if len(parts) == 1 and parts[0] == app_bundle_dir.stem:
            return True
        if len(parts) == 3 and parts[0] == "Frameworks" and parts[1].endswith(".framework"):
            fw_stem = Path(parts[1]).stem
            if parts[2] == fw_stem:
                return True
        if file_path.is_file() and not file_path.is_symlink():
            with open(file_path, "rb") as f:
                hdr = f.read(4)
                if hdr in _MACHO_MAGIC_BYTES:
                    return True
    except Exception:
        pass
    return False


def package_app_bundle_deterministic(
    app_bundle_dir: Path,
    output_ipa_path: Path,
    exec_name: Optional[str] = None,
    cancel_controller: Optional[BuildCancellationController] = None,
) -> Tuple[Path, List[str], str]:
    """
    Deterministically packages an already-assembled (and signed) `.app` bundle directory
    into an `.ipa` archive at `output_ipa_path`.

    Determinism guarantees for identical input `.app` bundle contents and settings:
      1. Archive entries are sorted in strict lexicographical order of normalized POSIX
         paths (`Payload/<BundleName>.app/...`).
      2. Every `ZipInfo` uses fixed `date_time = (1980, 1, 1, 0, 0, 0)` and `create_system = 3`.
      3. POSIX file mode bits in `external_attr` are normalized deterministically:
         - `0o100755` for main executable, framework binaries, and Mach-O executables.
         - `0o100644` for regular bundle files (`Info.plist`, resources, assets).
         - `0o120755` for symbolic links (stored with `ZIP_STORED` and normalized link target).
      4. Compression uses `ZIP_DEFLATED` at fixed `compresslevel = 6`.
      5. Does not mutate any file inside `app_bundle_dir`.
      6. Writes to a temporary sibling file and atomically replaces `output_ipa_path`
         only upon complete, uncancelled archive creation.

    Returns:
        (final_ipa_path, files_included_posix, ipa_sha256)
    """
    app_bundle_dir = Path(app_bundle_dir)
    if not app_bundle_dir.is_dir():
        raise FileNotFoundError(f"Application bundle directory not found: {app_bundle_dir}")

    bundle_folder_name = app_bundle_dir.name
    if not bundle_folder_name.endswith(".app"):
        bundle_folder_name = f"{bundle_folder_name}.app"

    output_ipa_path = Path(output_ipa_path)
    output_ipa_path.parent.mkdir(parents=True, exist_ok=True)

    if cancel_controller is not None:
        cancel_controller.check_cancelled(stage_idx=6)

    # Collect all candidate entries inside app_bundle_dir without following directory symlinks
    collected_entries: List[Tuple[str, Path, bool]] = []
    for root, dirs, files in os.walk(app_bundle_dir, followlinks=False):
        root_path = Path(root)

        # Separate directory symlinks from real subdirectories and filter excluded directories
        kept_dirs: List[str] = []
        for d in sorted(dirs):
            if _is_excluded_bundle_entry(d, is_dir=True):
                continue
            d_path = root_path / d
            if d_path.is_symlink():
                rel_inside_app = d_path.relative_to(app_bundle_dir).as_posix()
                arcname = f"Payload/{bundle_folder_name}/{rel_inside_app}"
                collected_entries.append((arcname, d_path, True))
            else:
                kept_dirs.append(d)
        dirs[:] = kept_dirs

        for f in sorted(files):
            if _is_excluded_bundle_entry(f, is_dir=False):
                continue
            f_path = root_path / f
            rel_inside_app = f_path.relative_to(app_bundle_dir).as_posix()
            arcname = f"Payload/{bundle_folder_name}/{rel_inside_app}"
            collected_entries.append((arcname, f_path, f_path.is_symlink()))

    # Sort deterministically by normalized POSIX archive path
    collected_entries.sort(key=lambda item: item[0])

    tmp_ipa_name = f".{output_ipa_path.name}.tmp.{os.getpid()}.{threading.get_ident()}"
    tmp_ipa_path = output_ipa_path.parent / tmp_ipa_name
    files_included: List[str] = []

    try:
        with zipfile.ZipFile(
            tmp_ipa_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=DETERMINISTIC_COMPRESS_LEVEL,
        ) as zipf:
            for arcname, abs_path, is_symlink in collected_entries:
                if cancel_controller is not None:
                    cancel_controller.check_cancelled(stage_idx=6)

                zinfo = zipfile.ZipInfo(filename=arcname, date_time=DETERMINISTIC_ZIP_DATETIME)
                zinfo.create_system = 3  # Unix / Darwin attribute layout

                if is_symlink:
                    link_target = os.readlink(abs_path)
                    # Strip Windows extended-length prefix if present on local relative symlinks
                    if link_target.startswith("\\\\?\\"):
                        link_target = link_target[4:]
                    link_target_posix = link_target.replace("\\", "/")
                    zinfo.compress_type = zipfile.ZIP_STORED
                    zinfo.external_attr = (stat.S_IFLNK | 0o755) << 16
                    zipf.writestr(zinfo, link_target_posix.encode("utf-8"), compress_type=zipfile.ZIP_STORED)
                else:
                    is_exec = _is_macho_or_executable(abs_path, app_bundle_dir, exec_name=exec_name)
                    perm_mode = 0o755 if is_exec else 0o644
                    zinfo.compress_type = zipfile.ZIP_DEFLATED
                    zinfo.external_attr = (stat.S_IFREG | perm_mode) << 16
                    data = abs_path.read_bytes()
                    zipf.writestr(
                        zinfo,
                        data,
                        compress_type=zipfile.ZIP_DEFLATED,
                        compresslevel=DETERMINISTIC_COMPRESS_LEVEL,
                    )

                files_included.append(arcname)

        if cancel_controller is not None:
            cancel_controller.check_cancelled(stage_idx=6)

        os.replace(tmp_ipa_path, output_ipa_path)
    finally:
        if tmp_ipa_path.exists():
            try:
                tmp_ipa_path.unlink()
            except Exception:
                pass

    ipa_sha256 = hashlib.sha256(output_ipa_path.read_bytes()).hexdigest()
    return output_ipa_path, files_included, ipa_sha256


def package_application(
    build_dir: Path,
    output_dir: Path,
    project_dir: Path,
    out_binary: Path,
    app_name: str,
    exec_name: str,
    bundle_id: str,
    deployment_target: str,
    target_type: str,
    project_config: Dict[str, Any],
    custom_fw_dir: Path,
    ldid_bin: Path,
    operation_callback: Optional[Any] = None,
    cancel_controller: Optional[BuildCancellationController] = None,
) -> Optional[Path]:
    """Packages application bundle and creates final deterministic .ipa archive."""
    t0 = time.monotonic()
    if cancel_controller is not None:
        cancel_controller.check_cancelled(stage_idx=6)

    product_name = str(project_config.get("PRODUCT_NAME") or app_name)
    display_name = str(project_config.get("CFBundleDisplayName") or product_name)
    payload_dir = build_dir / "Payload"
    if payload_dir.exists():
        shutil.rmtree(payload_dir)
    app_dir = payload_dir / f"{product_name}.app"
    os.makedirs(app_dir, exist_ok=True)

    # 1. Copy Executable (preserving exact signed bytes without modification)
    shutil.copy2(out_binary, app_dir / exec_name)

    # 2. Generate or Copy Info.plist
    info_src = project_dir / "Config" / "Info.plist"
    info_plist_cfg = project_config.get("InfoPlist")
    marketing_ver = str(project_config.get("MARKETING_VERSION", "1.0.0"))
    project_ver = str(project_config.get("CURRENT_PROJECT_VERSION", "1"))

    macro_context = {
        "PRODUCT_NAME": product_name,
        "CFBundleDisplayName": display_name,
        "EXECUTABLE_NAME": exec_name,
        "PRODUCT_BUNDLE_IDENTIFIER": bundle_id,
        "MARKETING_VERSION": marketing_ver,
        "CURRENT_PROJECT_VERSION": project_ver,
        "IPHONEOS_DEPLOYMENT_TARGET": deployment_target,
        "TARGET_BUILD_DIR": str(build_dir),
        "BUILT_PRODUCTS_DIR": str(output_dir),
        "PROJECT_DIR": str(project_dir),
    }

    if info_src.is_file():
        shutil.copy2(info_src, app_dir / "Info.plist")
        try:
            with open(app_dir / "Info.plist", "rb") as f:
                copied_info = plistlib.load(f)
            if isinstance(copied_info, dict):
                copied_info = expand_macro_variables(copied_info, macro_context)
                if "UIApplicationSceneManifest" not in copied_info and (
                    (project_dir / "SceneDelegate.swift").exists() or any(project_dir.glob("*SceneDelegate*.swift"))
                ):
                    copied_info["UIApplicationSceneManifest"] = {
                        "UIApplicationSupportsMultipleScenes": False,
                        "UISceneConfigurations": {
                            "UIWindowSceneSessionRoleApplication": [
                                {
                                    "UISceneConfigurationName": "Default Configuration",
                                    "UISceneDelegateClassName": "SceneDelegate",
                                }
                            ]
                        },
                    }
                with open(app_dir / "Info.plist", "wb") as f:
                    plistlib.dump(copied_info, f, sort_keys=True)
        except Exception:
            pass
    else:
        if isinstance(info_plist_cfg, dict) and info_plist_cfg:
            resolved_info = expand_macro_variables(info_plist_cfg, macro_context)
        else:
            resolved_info = {}

        # Guarantee essential bundle metadata required for TrollStore (Error 176 prevention) and iOS bundle validity
        if "CFBundlePackageType" not in resolved_info:
            resolved_info["CFBundlePackageType"] = "APPL"
        if "CFBundleExecutable" not in resolved_info:
            resolved_info["CFBundleExecutable"] = exec_name
        if "CFBundleIdentifier" not in resolved_info:
            resolved_info["CFBundleIdentifier"] = bundle_id
        if "CFBundleName" not in resolved_info or not resolved_info["CFBundleName"]:
            resolved_info["CFBundleName"] = product_name
        if "CFBundleDisplayName" not in resolved_info or not resolved_info["CFBundleDisplayName"]:
            resolved_info["CFBundleDisplayName"] = display_name
        elif "CFBundleDisplayName" in project_config and isinstance(info_plist_cfg, dict):
            raw_disp = info_plist_cfg.get("CFBundleDisplayName")
            if raw_disp in (None, "", "$(CFBundleDisplayName)", "$(PRODUCT_NAME)", product_name):
                resolved_info["CFBundleDisplayName"] = display_name
        if "CFBundleShortVersionString" not in resolved_info:
            resolved_info["CFBundleShortVersionString"] = marketing_ver
        if "CFBundleVersion" not in resolved_info:
            resolved_info["CFBundleVersion"] = project_ver
        if "MinimumOSVersion" not in resolved_info:
            resolved_info["MinimumOSVersion"] = deployment_target
        if "UIDeviceFamily" not in resolved_info:
            resolved_info["UIDeviceFamily"] = [1, 2]

        # Validate UILaunchStoryboardName and ensure UILaunchScreen to prevent launch crashes
        if target_type == "app":
            storyboard_name = resolved_info.get("UILaunchStoryboardName")
            if storyboard_name:
                has_sb = any(
                    (project_dir / "Resources" / f"{storyboard_name}.{ext}").exists()
                    or (app_dir / f"{storyboard_name}.{ext}").exists()
                    for ext in ["storyboard", "storyboardc", "nib"]
                )
                if not has_sb:
                    log_warning(
                        f"UILaunchStoryboardName '{storyboard_name}' not found on disk. Falling back to UILaunchScreen to avoid iOS crash."
                    )
                    resolved_info.pop("UILaunchStoryboardName", None)
                    resolved_info["UILaunchScreen"] = {}
            elif "UILaunchScreen" not in resolved_info:
                resolved_info["UILaunchScreen"] = {}

        # Guarantee UIApplicationSceneManifest for scene-based UIKit applications
        if target_type == "app" and "UIApplicationSceneManifest" not in resolved_info:
            has_scene = (project_dir / "SceneDelegate.swift").exists() or any(project_dir.glob("*SceneDelegate*.swift"))
            if has_scene:
                resolved_info["UIApplicationSceneManifest"] = {
                    "UIApplicationSupportsMultipleScenes": False,
                    "UISceneConfigurations": {
                        "UIWindowSceneSessionRoleApplication": [
                            {
                                "UISceneConfigurationName": "Default Configuration",
                                "UISceneDelegateClassName": "SceneDelegate",
                            }
                        ]
                    },
                }

        with open(app_dir / "Info.plist", "wb") as f:
            plistlib.dump(resolved_info, f, sort_keys=True)

    # 3. Copy Resources in deterministic sorted order
    resources_dir = project_dir / "Resources"
    if resources_dir.is_dir():
        for item in sorted(resources_dir.iterdir(), key=lambda p: p.name):
            if _is_excluded_bundle_entry(item.name, is_dir=item.is_dir()):
                continue
            dest = app_dir / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)

    # 4. Auto-flatten .xcassets
    flatten_xcassets(project_dir, app_dir)

    # 5. Embed and sign custom frameworks from Projects/<Project>/Frameworks/
    if custom_fw_dir.is_dir():
        app_fw_dir = app_dir / "Frameworks"
        embedded_count = 0
        for fw_item in sorted(custom_fw_dir.glob("*.framework"), key=lambda p: p.name):
            if fw_item.is_dir():
                if cancel_controller is not None:
                    cancel_controller.check_cancelled(stage_idx=6)
                os.makedirs(app_fw_dir, exist_ok=True)
                dest_fw = app_fw_dir / fw_item.name
                if dest_fw.exists():
                    shutil.rmtree(dest_fw)
                shutil.copytree(fw_item, dest_fw)
                if sign_embedded_framework(ldid_bin, dest_fw):
                    pass
                embedded_count += 1
        if embedded_count > 0:
            log_success(f"Embedded and signed {embedded_count} custom framework(s) into Payload/{product_name}.app/Frameworks/")

    # 6. Create deterministic .ipa in dist/ via atomic temporary file
    final_ipa_path = output_dir / f"{product_name}.ipa"
    final_ipa_path, files_included, ipa_sha256 = package_app_bundle_deterministic(
        app_bundle_dir=app_dir,
        output_ipa_path=final_ipa_path,
        exec_name=exec_name,
        cancel_controller=cancel_controller,
    )

    elapsed = time.monotonic() - t0
    is_valid_zip = final_ipa_path.is_file() and zipfile.is_zipfile(final_ipa_path)
    ipa_sz = final_ipa_path.stat().st_size if final_ipa_path.is_file() else 0

    info_summary = {}
    target_info = app_dir / "Info.plist"
    if target_info.is_file():
        try:
            with open(target_info, "rb") as tif:
                inf = plistlib.load(tif)
                info_summary = {
                    "CFBundleExecutable": inf.get("CFBundleExecutable"),
                    "CFBundleIdentifier": inf.get("CFBundleIdentifier"),
                    "CFBundlePackageType": inf.get("CFBundlePackageType"),
                    "MinimumOSVersion": inf.get("MinimumOSVersion"),
                    "HasSceneManifest": "UIApplicationSceneManifest" in inf,
                }
        except Exception:
            pass

    if operation_callback:
        operation_callback(
            operation="Create IPA Package",
            app_bundle_dir=str(app_dir),
            files_included=files_included,
            ipa_path=str(final_ipa_path),
            ipa_size=ipa_sz,
            ipa_sha256=ipa_sha256,
            is_valid_zip=is_valid_zip,
            info_plist_summary=info_summary,
            elapsed=elapsed,
        )

    return final_ipa_path


def create_ipa_package(
    app_name: str,
    app_bundle_dir: Path,
    output_dir: Path,
    cancel_controller: Optional[BuildCancellationController] = None,
) -> Path:
    """
    Creates a deterministic .ipa archive directly from an already-assembled `.app` bundle directory.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    final_ipa = output_dir / f"{app_name}.ipa"
    final_ipa, _, _ = package_app_bundle_deterministic(
        app_bundle_dir=Path(app_bundle_dir),
        output_ipa_path=final_ipa,
        exec_name=app_name,
        cancel_controller=cancel_controller,
    )
    return final_ipa
