import os
import re
import time
import json
from pathlib import Path
from typing import Optional, List, Dict, Any

from nyxwin.core.models import Color, log_info, log_success, log_warning, log_error, log_step
from nyxwin.core.toolchain import Toolchain
from nyxwin.core.project import find_project_config_file, load_project_config
from nyxwin.build.compiler import compile_c_sources, compile_swift_sources
from nyxwin.build.linker import link_macho_binary
from nyxwin.build.patcher import patch_macho_binary
from nyxwin.build.signer import sign_binary
from nyxwin.build.packager import package_application
from nyxwin.build.transcript import BuildTranscript
from nyxwin.tui.components.progress import BuildProgressTracker, LiveProgressManager

_last_tracker: Optional[Any] = None

def get_last_build_tracker() -> Optional[Any]:
    """Returns the BuildProgressTracker from the most recent build_project execution."""
    global _last_tracker
    return _last_tracker

def build_project(
    toolchain: Toolchain,
    project_dir_or_name: Path,
    target_triple: Optional[str] = None,
    verbose: bool = False,
    requested_sdk: Optional[str] = None,
    profile: str = "auto"
) -> bool:
    """
    Main compilation and packaging orchestrator.
    Executes:
      1. Source discovery
      2. Multi-threaded incremental compilation (C/ObjC/C++ & Swift)
      3. Darwin Mach-O linking (ld64.lld)
      4. Mach-O Patch #31 application
      5. Entitlements & ad-hoc codesigning (ldid)
      6. Application bundle & .ipa packaging
    """
    start_time = time.time()

    # 1. Resolve Project Directory
    if isinstance(project_dir_or_name, str):
        project_dir_or_name = Path(project_dir_or_name)

    cfg_p, _ = find_project_config_file(project_dir_or_name)
    if project_dir_or_name.is_dir() and cfg_p is not None:
        project_dir = project_dir_or_name.resolve()
    else:
        found = toolchain.get_project_dir(str(project_dir_or_name))
        if found:
            project_dir = found
        else:
            cand = toolchain.projects_dir / project_dir_or_name if toolchain.projects_dir else None
            cfg_p_cand, _ = find_project_config_file(cand) if cand else (None, None)
            if cand and cand.is_dir() and cfg_p_cand is not None:
                project_dir = cand
            else:
                log_error(f"Project not found: {project_dir_or_name}")
                return False

    project_config = load_project_config(project_dir)
    if not project_config:
        log_error(f"Failed to read project configuration (Project.plist) in {project_dir}")
        return False

    # Check Toolchain readiness
    if not toolchain.sdk_dir or not toolchain.sdk_dir.is_dir():
        from nyxwin.config.paths import get_sdks_root
        log_error(f"No valid iOS SDK found in {get_sdks_root()}. Run 'nyx sdk install 26.5'.")
        return False

    app_name = project_config.get("Name", project_dir.name)
    exec_name = project_config.get("ExecutableName", app_name)
    bundle_id = project_config.get("BundleIdentifier", f"com.example.{app_name.lower()}")
    deployment_target = str(project_config.get("DeploymentTarget", "17.0"))
    scheme = project_config.get("TargetType", "Application")
    if scheme.lower() not in ("application", "app"):
        log_error(f"Project scheme '{scheme}' is no longer supported.\nNyxWin is now focused exclusively on Swift iOS applications ('swiftui' or 'swift-uikit').")
        return False
    target_type = "app"

    if not target_triple:
        target_triple = f"arm64-apple-ios{deployment_target}"

    # Extract compiler and linker flags from Project.plist
    clang_flags = []
    swift_flags = []
    include_paths = []
    library_paths = []
    frameworks = []
    weak_frameworks = []
    linker_flags = []
    custom_sources = []

    # Include explicitly declared frameworks from configuration
    for fw in project_config.get("Frameworks", []):
        if fw not in frameworks:
            frameworks.append(fw)
    for wfw in project_config.get("WeakFrameworks", []):
        if wfw not in weak_frameworks:
            weak_frameworks.append(wfw)

    raw_clang_flags = project_config.get("ClangFlags", [])
    idx = 0
    while idx < len(raw_clang_flags):
        flag = raw_clang_flags[idx]
        if flag == "-I" and idx + 1 < len(raw_clang_flags):
            val = raw_clang_flags[idx + 1]
            if "$" not in val:
                include_paths.append(val)
            idx += 2
        elif flag == "-F" and idx + 1 < len(raw_clang_flags):
            val = raw_clang_flags[idx + 1]
            if "$" not in val:
                frameworks.append(val)
            idx += 2
        elif flag == "-framework" and idx + 1 < len(raw_clang_flags):
            frameworks.append(raw_clang_flags[idx + 1])
            idx += 2
        elif flag == "-L" and idx + 1 < len(raw_clang_flags):
            val = raw_clang_flags[idx + 1]
            if "$" not in val:
                library_paths.append(val)
            idx += 2
        elif flag.startswith("-I"):
            val = flag[2:]
            if "$" not in val:
                include_paths.append(val)
            idx += 1
        elif flag.startswith("-L"):
            val = flag[2:]
            if "$" not in val:
                library_paths.append(val)
            idx += 1
        elif flag.startswith("-l"):
            # Filter out -lclang_rt.* because runtime is passed explicitly as an archive
            if not flag.startswith("-lclang_rt"):
                if flag not in linker_flags:
                    linker_flags.append(flag)
            idx += 1
        elif flag in ("-target", "-isysroot", "-resource-dir"):
            idx += 2 if idx + 1 < len(raw_clang_flags) else 1
        elif flag.endswith((".c", ".m", ".mm", ".cpp", ".swift")):
            custom_sources.append(flag)
            idx += 1
        else:
            if flag not in clang_flags:
                clang_flags.append(flag)
            idx += 1

    raw_swift_flags = project_config.get("SwiftFlags", [])
    idx = 0
    while idx < len(raw_swift_flags):
        sf = raw_swift_flags[idx]
        if sf in ("-target", "-sdk", "-resource-dir", "-module-cache-path"):
            idx += 2 if idx + 1 < len(raw_swift_flags) else 1
        elif sf in ("-parse-as-library", "-emit-object", "-whole-module-optimization"):
            idx += 1
        else:
            if sf not in swift_flags:
                swift_flags.append(sf)
            idx += 1

    raw_linker_flags = project_config.get("LinkerFlags", [])
    idx = 0
    while idx < len(raw_linker_flags):
        flag = raw_linker_flags[idx]
        if flag == "-framework" and idx + 1 < len(raw_linker_flags):
            fw = raw_linker_flags[idx + 1]
            if fw not in frameworks:
                frameworks.append(fw)
            idx += 2
        elif flag == "-weak_framework" and idx + 1 < len(raw_linker_flags):
            wfw = raw_linker_flags[idx + 1]
            if wfw not in weak_frameworks:
                weak_frameworks.append(wfw)
            idx += 2
        elif flag.startswith("-l"):
            if not flag.startswith("-lclang_rt"):
                if flag not in linker_flags:
                    linker_flags.append(flag)
            idx += 1
        else:
            if flag not in linker_flags:
                linker_flags.append(flag)
            idx += 1

    # Sanitize Swift module name
    swift_module_name = re.sub(r'[^a-zA-Z0-9_]', '_', exec_name)
    if swift_module_name and swift_module_name[0].isdigit():
        swift_module_name = "_" + swift_module_name
    if not swift_module_name:
        swift_module_name = "App"

    # External Build Intermediates & External Compiler Cache
    from nyxwin.config.paths import resolve_project_build_dir, get_project_cache_dir
    from nyxwin.core.project import get_or_create_project_id

    proj_id = get_or_create_project_id(project_dir, project_config)
    build_dir = resolve_project_build_dir(project_dir, config=project_config, project_id=proj_id)
    cache_dir = get_project_cache_dir(proj_id)
    obj_dir = build_dir / "objects"
    out_binary = build_dir / exec_name
    final_output_dir = project_dir / "dist"

    os.makedirs(obj_dir, exist_ok=True)
    os.makedirs(cache_dir, exist_ok=True)
    os.makedirs(final_output_dir, exist_ok=True)

    # Load incremental build manifest
    manifest_file = build_dir / "build_manifest.json"
    build_manifest = {}
    if manifest_file.is_file():
        try:
            build_manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except Exception:
            build_manifest = {}

    global _last_tracker
    tracker = BuildProgressTracker(app_name, target_triple, profile=profile, project_dir=project_dir)
    try:
        transcript = BuildTranscript(app_name, project_dir, target_triple, deployment_target, profile, toolchain)
        tracker.transcript = transcript
    except Exception:
        pass
    _last_tracker = tracker
    progress_mgr = LiveProgressManager(tracker)
    progress_mgr.start()

    try:
        # Step 1: Discover Source Files
        tracker.start_stage(1, "Scanning Source Files")
        if custom_sources:
            c_sources = [project_dir / s for s in custom_sources if s.endswith((".c", ".m", ".mm", ".cpp"))]
            swift_sources = [project_dir / s for s in custom_sources if s.endswith(".swift")]
        else:
            root_excl_dirs = {
                "config", "resources", "dist",
                "build", "cache", "output", "backups"
            }
            universal_excl_dirs = {
                "__pycache__", "payload"
            }

            all_candidates = []
            proj_root_res = project_dir.resolve()
            for root, dirs, files in os.walk(project_dir):
                curr_res = Path(root).resolve()
                is_root = (curr_res == proj_root_res)

                dirs[:] = [
                    d for d in dirs
                    if not d.startswith(".")
                    and d.lower() not in universal_excl_dirs
                    and not d.lower().endswith(".xcassets")
                    and not d.lower().endswith(".framework")
                    and not (is_root and d.lower() in root_excl_dirs)
                ]
                for f in files:
                    all_candidates.append(Path(root) / f)

            c_sources = [f for f in all_candidates if f.suffix.lower() in (".c", ".m", ".mm", ".cpp")]
            swift_sources = [f for f in all_candidates if f.suffix.lower() == ".swift"]

        if not c_sources and not swift_sources:
            progress_mgr.finish_failure(1, f"No source files (.c, .m, .mm, .cpp, .swift) found in {project_dir}")
            return False

        # Auto-detect SwiftUI frameworks for Swift projects
        if swift_sources:
            has_swiftui = any("import SwiftUI" in s.read_text(encoding="utf-8", errors="ignore") for s in swift_sources)
            if has_swiftui:
                if "SwiftUI" not in frameworks:
                    frameworks.append("SwiftUI")
                if "UIKit" not in frameworks:
                    frameworks.append("UIKit")
                if "SwiftUICore" not in weak_frameworks:
                    weak_frameworks.append("SwiftUICore")

        tracker.complete_stage(1, f"Found {len(c_sources)} C/ObjC and {len(swift_sources)} Swift sources")
        if tracker.transcript:
            excl_dirs = list(root_excl_dirs.union(universal_excl_dirs)) if not custom_sources else []
            tracker.transcript.record_scan(c_sources, swift_sources, excl_dirs)

        # Step 2: Compile Sources
        tracker.start_stage(2, "Compiling Source Files")
        obj_files = []
        current_manifest = dict(build_manifest)

        extra_inc_flags = []
        for inc in include_paths:
            if not inc or "$" in inc:
                continue
            cand = Path(inc)
            if not cand.is_absolute():
                cand = (project_dir / inc).resolve()
            if cand.is_dir():
                extra_inc_flags.extend(["-I", str(cand)])

        # Ensure project directory root is an include search path for sibling headers (#import "Foo.h")
        proj_root_str = str(project_dir.resolve())
        if proj_root_str not in extra_inc_flags:
            extra_inc_flags.extend(["-I", proj_root_str])

        # Auto-enable Clang modules if source code uses @import (e.g. @import UIKit; or @import Foundation;)
        effective_clang_flags = list(clang_flags)
        if c_sources:
            has_at_import = any("@import " in s.read_text(encoding="utf-8", errors="ignore") for s in c_sources)
            if has_at_import:
                if "-fmodules" not in effective_clang_flags:
                    effective_clang_flags.append("-fmodules")
                mod_cache_dir = cache_dir / "ModuleCache"
                mod_cache_dir.mkdir(parents=True, exist_ok=True)
                if not any(f.startswith("-fmodules-cache-path") for f in effective_clang_flags):
                    effective_clang_flags.append(f"-fmodules-cache-path={mod_cache_dir}")

        custom_fw_dir = project_dir / "Frameworks"
        extra_fw_flags = []
        if custom_fw_dir.is_dir():
            extra_fw_flags.extend(["-F", str(custom_fw_dir.resolve())])

        # 2A: Compile C/ObjC
        if c_sources:
            if not toolchain.clang:
                progress_mgr.finish_failure(2, "clang.exe not found. Please install LLVM on Windows.")
                return False
            ok_c, c_objs, current_manifest = compile_c_sources(
                toolchain.clang, toolchain.sdk_dir, c_sources, project_dir, obj_dir,
                target_triple, extra_inc_flags, extra_fw_flags, effective_clang_flags,
                current_manifest, verbose,
                progress_callback=tracker.update_c_progress,
                warning_callback=progress_mgr.print_warning,
                error_callback=tracker.add_error,
                operation_callback=tracker.record_operation
            )
            if not ok_c:
                progress_mgr.finish_failure(2, "C/ObjC compilation failed", tool="clang", exit_code=1)
                return False
            obj_files.extend(c_objs)

        # 2B: Compile Swift
        if swift_sources:
            if not toolchain.swiftc:
                progress_mgr.finish_failure(2, "swiftc.exe not found. Please install Swift for Windows.", tool="swiftc")
                return False
            ok_s, s_objs, current_manifest = compile_swift_sources(
                toolchain.swiftc, toolchain.clang, toolchain.sdk_dir, toolchain.swift_resource_dir,
                toolchain.tools_dir, swift_sources, project_dir, obj_dir,
                target_triple, swift_module_name, app_name, extra_inc_flags, extra_fw_flags,
                swift_flags, current_manifest, verbose, cache_dir=cache_dir,
                progress_callback=tracker.update_swift_progress,
                warning_callback=progress_mgr.print_warning,
                error_callback=tracker.add_error,
                operation_callback=tracker.record_operation
            )
            if not ok_s:
                progress_mgr.finish_failure(2, "Swift compilation failed", tool="swiftc", exit_code=1)
                return False
            obj_files.extend(s_objs)

        # Save incremental manifest
        try:
            manifest_file.write_text(json.dumps(current_manifest, indent=2), encoding="utf-8")
        except Exception:
            pass

        tracker.complete_stage(2, f"Compiled {len(obj_files)} objects")

        # Step 3: Link Mach-O
        tracker.start_stage(3, "Linking Mach-O Executable (ld64.lld)")
        linker_bin = toolchain.ld64 if toolchain.ld64 else toolchain.lld
        if not linker_bin:
            progress_mgr.finish_failure(3, "LLVM linker (lld.exe / ld64.lld) not found.", tool="ld64.lld")
            return False

        has_cpp = any(s.suffix.lower() in (".cpp", ".cxx", ".cc", ".mm") for s in c_sources)
        ok_link = link_macho_binary(
            linker_bin, toolchain.sdk_dir, toolchain.swift_resource_dir, toolchain.clang_rt,
            obj_files, out_binary, deployment_target, frameworks, weak_frameworks,
            library_paths, extra_fw_flags, linker_flags, project_dir, bool(swift_sources), verbose,
            error_callback=tracker.add_error,
            has_cpp=has_cpp,
            warning_callback=progress_mgr.print_warning,
            target_type=target_type,
            operation_callback=tracker.record_operation
        )
        if not ok_link:
            progress_mgr.finish_failure(3, "Mach-O linking failed", tool="ld64.lld", exit_code=1)
            return False

        tracker.complete_stage(3, f"Linked Mach-O binary -> {exec_name}")

        # Step 4: Mach-O Patch #31
        tracker.start_stage(4, "Applying Header Patch #31 (chained fixups)")
        patch_success = patch_macho_binary(out_binary, verbose=verbose)
        if patch_success:
            tracker.complete_stage(4, "Patch #31 applied (LC_LOAD_WEAK_DYLIB fixups)")
        else:
            tracker.complete_stage(4, "Patch #31 skipped or warning")
        if tracker.transcript:
            tracker.transcript.record_patch(
                "Patch #31 (chained fixups)",
                str(out_binary),
                patch_success,
                "LC_LOAD_WEAK_DYLIB fixups" if patch_success else "Skipped"
            )

        # Step 5: Codesigning & Entitlements
        tracker.start_stage(5, f"Injecting Entitlements ({profile}) & ldid")
        ok_sign = sign_binary(
            toolchain.ldid, out_binary, project_dir, build_dir,
            profile=profile, verbose=verbose,
            operation_callback=tracker.record_operation
        )
        if not ok_sign:
            progress_mgr.finish_failure(5, "Ad-hoc codesigning with ldid failed", tool="ldid", exit_code=1)
            return False

        tracker.complete_stage(5, f"Signed Mach-O binary ({profile})")

        # Step 6: Packaging
        tracker.start_stage(6, "Packaging Application & Creating .ipa")
        final_artifact_path = package_application(
            build_dir, final_output_dir, project_dir, out_binary,
            app_name, exec_name, bundle_id, deployment_target, target_type,
            project_config, custom_fw_dir, toolchain.ldid,
            operation_callback=tracker.record_operation
        )
        artifact_label = "Output IPA"

        if not final_artifact_path or (final_artifact_path.is_file() is False and final_artifact_path.is_dir() is False):
            progress_mgr.finish_failure(6, f"Packaging {artifact_label} failed.", tool="packager", exit_code=1)
            return False

        if final_artifact_path.is_file():
            artifact_size = final_artifact_path.stat().st_size
        else:
            artifact_size = sum(f.stat().st_size for f in final_artifact_path.rglob('*') if f.is_file())

        tracker.ipa_path = final_artifact_path.resolve()
        tracker.complete_stage(6, f"Created {final_artifact_path.name} ({artifact_size:,} bytes)")

        progress_mgr.finish_success(final_artifact_path, artifact_size, artifact_label=artifact_label)
        return True
    except KeyboardInterrupt:
        progress_mgr.finish_failure(tracker.active_stage_idx + 1, "Build aborted by user (Ctrl+C)")
        return False
    except Exception as e:
        progress_mgr.finish_failure(tracker.active_stage_idx + 1, f"Build error: {e}")
        return False
    finally:
        progress_mgr.close()
