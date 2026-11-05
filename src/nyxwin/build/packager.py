import os
import shutil
import zipfile
import plistlib
from pathlib import Path
from typing import Dict, Any, Optional

from nyxwin.core.models import Color, log_info, log_warning, log_success
from nyxwin.core.project import expand_macro_variables
from nyxwin.build.assets import flatten_xcassets
from nyxwin.build.signer import sign_embedded_framework

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
    operation_callback: Optional[Any] = None
) -> Optional[Path]:
    """Packages application bundle and creates final .ipa archive."""
    import time
    t0 = time.monotonic()
    payload_dir = build_dir / "Payload"
    app_dir = payload_dir / f"{app_name}.app"
    if app_dir.exists():
        shutil.rmtree(app_dir)
    os.makedirs(app_dir, exist_ok=True)

    # 1. Copy Executable
    shutil.copy2(out_binary, app_dir / exec_name)

    # 2. Generate or Copy Info.plist
    info_src = project_dir / "Config" / "Info.plist"
    bundle_info = project_config.get("BundleInfo")
    bundle_ver = str(project_config.get("Version", "1.0"))
    bundle_short_ver = str(project_config.get("BuildNumber", bundle_ver))

    macro_context = {
        "Name": app_name,
        "ExecutableName": exec_name,
        "BundleIdentifier": bundle_id,
        "Version": bundle_ver,
        "BuildNumber": bundle_short_ver,
        "DeploymentTarget": deployment_target,
    }

    if info_src.is_file():
        shutil.copy2(info_src, app_dir / "Info.plist")
        try:
            with open(app_dir / "Info.plist", "rb") as f:
                copied_info = plistlib.load(f)
            if "UIApplicationSceneManifest" not in copied_info and ((project_dir / "SceneDelegate.swift").exists() or any(project_dir.glob("*SceneDelegate*.swift"))):
                copied_info["UIApplicationSceneManifest"] = {
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
                with open(app_dir / "Info.plist", "wb") as f:
                    plistlib.dump(copied_info, f)
        except Exception:
            pass
    else:
        if isinstance(bundle_info, dict) and bundle_info:
            resolved_info = expand_macro_variables(bundle_info, macro_context)
        else:
            resolved_info = {}

        # Guarantee essential bundle metadata required for TrollStore (Error 176 prevention) and iOS bundle validity
        if "CFBundlePackageType" not in resolved_info:
            resolved_info["CFBundlePackageType"] = "APPL"
        if "CFBundleExecutable" not in resolved_info:
            resolved_info["CFBundleExecutable"] = exec_name
        if "CFBundleIdentifier" not in resolved_info:
            resolved_info["CFBundleIdentifier"] = bundle_id
        if "CFBundleName" not in resolved_info:
            resolved_info["CFBundleName"] = app_name
        if "CFBundleVersion" not in resolved_info:
            resolved_info["CFBundleVersion"] = bundle_ver
        if "CFBundleShortVersionString" not in resolved_info:
            resolved_info["CFBundleShortVersionString"] = bundle_short_ver
        if "MinimumOSVersion" not in resolved_info:
            resolved_info["MinimumOSVersion"] = deployment_target
        if "UIDeviceFamily" not in resolved_info:
            resolved_info["UIDeviceFamily"] = [1, 2]

        # Validate UILaunchStoryboardName and ensure UILaunchScreen to prevent launch crashes
        if target_type == "app":
            storyboard_name = resolved_info.get("UILaunchStoryboardName")
            if storyboard_name:
                has_sb = any((project_dir / "Resources" / f"{storyboard_name}.{ext}").exists() or
                             (app_dir / f"{storyboard_name}.{ext}").exists()
                             for ext in ["storyboard", "storyboardc", "nib"])
                if not has_sb:
                    log_warning(f"UILaunchStoryboardName '{storyboard_name}' not found on disk. Falling back to UILaunchScreen to avoid iOS crash.")
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
                                "UISceneDelegateClassName": "SceneDelegate"
                            }
                        ]
                    }
                }

        with open(app_dir / "Info.plist", "wb") as f:
            plistlib.dump(resolved_info, f)

    # 3. Copy Resources
    resources_dir = project_dir / "Resources"
    if resources_dir.is_dir():
        for item in resources_dir.iterdir():
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
        for fw_item in custom_fw_dir.glob("*.framework"):
            if fw_item.is_dir():
                os.makedirs(app_fw_dir, exist_ok=True)
                dest_fw = app_fw_dir / fw_item.name
                if dest_fw.exists():
                    shutil.rmtree(dest_fw)
                shutil.copytree(fw_item, dest_fw)
                if sign_embedded_framework(ldid_bin, dest_fw):
                    pass
                embedded_count += 1
        if embedded_count > 0:
            log_success(f"Embedded and signed {embedded_count} custom framework(s) into Payload/{app_name}.app/Frameworks/")

    # 6. Create .ipa in dist/
    final_ipa_path = output_dir / f"{app_name}.ipa"
    files_included = []
    with zipfile.ZipFile(final_ipa_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(payload_dir):
            for file in files:
                abs_file = Path(root) / file
                rel_path = abs_file.relative_to(build_dir)
                zipf.write(abs_file, rel_path)
                files_included.append(str(rel_path))

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
                    "HasSceneManifest": "UIApplicationSceneManifest" in inf
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
            is_valid_zip=is_valid_zip,
            info_plist_summary=info_summary,
            elapsed=elapsed
        )

    return final_ipa_path

def create_ipa_package(app_name: str, app_bundle_dir: Path, output_dir: Path) -> Path:
    """
    Deprecated compatibility wrapper for creating an .ipa archive directly from an app bundle directory.
    Canonical project compilation and packaging is coordinated via package_application().
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    final_ipa = output_dir / f"{app_name}.ipa"
    with zipfile.ZipFile(final_ipa, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(app_bundle_dir):
            for f in files:
                abs_f = Path(root) / f
                rel_f = abs_f.relative_to(app_bundle_dir.parent)
                zf.write(abs_f, f"Payload/{rel_f}")
    return final_ipa
