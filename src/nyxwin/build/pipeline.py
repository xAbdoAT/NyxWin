import os
import re
import time
import json
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any

from nyxwin.core.models import Color, log_info, log_success, log_warning, log_error, log_step
from nyxwin.core.toolchain import Toolchain
from nyxwin.core.project import (
    find_project_config_file,
    load_project_config,
    expand_project_macros,
    get_or_create_project_id,
)
from nyxwin.config.paths import resolve_project_build_dir, get_project_cache_dir
from nyxwin.build.compiler import compile_c_sources, compile_swift_sources
from nyxwin.build.linker import link_macho_binary, translate_driver_linker_flags
from nyxwin.build.patcher import patch_macho_binary
from nyxwin.build.signer import sign_binary
from nyxwin.build.packager import package_application
from nyxwin.build.process_manager import BuildCancellationController, BuildCancelledError
from nyxwin.build.transcript import BuildTranscript
from nyxwin.tui.components.progress import BuildProgressTracker, LiveProgressManager

_last_tracker: Optional[Any] = None

def get_last_build_tracker() -> Optional[Any]:
    """Returns the BuildProgressTracker from the most recent build_project execution."""
    global _last_tracker
    return _last_tracker


_UNRESOLVED_MACRO_RE = re.compile(r"\$\([^)]*\)?|\$\{[^}]*\}?|\$[A-Za-z_][A-Za-z0-9_]*[\)\}]")

_TWO_TOKEN_PREFIX_FLAGS = (
    "-Xfrontend",
    "-Xllvm",
    "-Xcc",
    "-Xlinker",
    "-Xclang",
    "-D",
    "-U",
    "-isystem",
    "-include",
    "-imacros",
    "-rpath",
    "-u",
    "-undefined",
    "-exported_symbol",
    "-unexported_symbol",
    "-install_name",
)


def _has_unresolved_macro(val: str) -> bool:
    """
    Returns True if a string still contains an unexpanded or malformed $(...) / ${...} macro token.
    Preserves literal '$' characters in compiler definitions, linker arguments, and symbol values.
    """
    return bool(_UNRESOLVED_MACRO_RE.search(val))


def expand_and_parse_build_flags(
    project_config: Dict[str, Any],
    project_dir: Path,
    sdk_dir: Optional[Path] = None,
    cache_dir: Optional[Path] = None,
    build_dir: Optional[Path] = None,
    warning_callback: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Expands canonical project macros in memory (without mutating Project.plist on disk)
    and parses compiler, Swift, and linker flags into structured build inputs.

    Guarantees:
      - Macro expansion occurs before flag classification.
      - Both split ('-I <dir>', '-F <dir>', '-L <dir>') and attached ('-I<dir>', '-F<dir>', '-L<dir>')
        forms are supported across OTHER_CFLAGS, OTHER_CPLUSPLUSFLAGS, OTHER_SWIFT_FLAGS, and OTHER_LDFLAGS.
      - '-F <dir>' and '-F<dir>' always route to framework search paths (extra_fw_flags) and never to '-framework'.
      - C flags (OTHER_CFLAGS) and C++ flags (OTHER_CPLUSPLUSFLAGS) remain separate.
      - Unresolved '$(...)' macros emit a clear warning diagnostic rather than silently passing broken flags.
    """
    expanded = expand_project_macros(
        project_config,
        sdk_root=sdk_dir,
        cache_root=cache_dir,
        project_dir=project_dir,
        target_build_dir=build_dir,
    )

    clang_flags: List[str] = []
    cxx_flags: List[str] = []
    swift_flags: List[str] = []
    include_paths: List[str] = []
    framework_search_paths: List[str] = []
    library_paths: List[str] = []
    frameworks: List[str] = []
    weak_frameworks: List[str] = []
    linker_flags: List[str] = []
    custom_sources: List[str] = []
    unresolved_warnings: List[str] = []

    def warn_if_unresolved(token: str, setting_name: str) -> bool:
        if _has_unresolved_macro(token):
            msg = f"Unresolved macro in {setting_name}: '{token}'"
            unresolved_warnings.append(msg)
            log_warning(msg)
            if warning_callback:
                warning_callback(msg)
            return True
        return False

    def add_unique(target_list: List[str], item: str) -> None:
        if item and item not in target_list:
            target_list.append(item)

    # 1. Explicit Frameworks, WeakFrameworks, Libraries, and core required build settings
    for req_key in ("PRODUCT_NAME", "EXECUTABLE_NAME", "PRODUCT_BUNDLE_IDENTIFIER", "IPHONEOS_DEPLOYMENT_TARGET"):
        req_val = str(expanded.get(req_key, "")).strip()
        if req_val:
            warn_if_unresolved(req_val, req_key)

    for fw in expanded.get("Frameworks", []):
        fw_str = str(fw).strip()
        if fw_str and not warn_if_unresolved(fw_str, "Frameworks"):
            add_unique(frameworks, fw_str)

    for wfw in expanded.get("WeakFrameworks", []):
        wfw_str = str(wfw).strip()
        if wfw_str and not warn_if_unresolved(wfw_str, "WeakFrameworks"):
            add_unique(weak_frameworks, wfw_str)

    for lib in expanded.get("Libraries", []):
        lib_str = str(lib).strip()
        if not lib_str or warn_if_unresolved(lib_str, "Libraries"):
            continue
        lflag = lib_str if lib_str.startswith("-l") else f"-l{lib_str}"
        if not lflag.startswith("-lclang_rt"):
            add_unique(linker_flags, lflag)

    # 2. Parse OTHER_CFLAGS
    raw_clang_flags = [str(x) for x in expanded.get("OTHER_CFLAGS", [])]
    idx = 0
    while idx < len(raw_clang_flags):
        flag = raw_clang_flags[idx]
        if flag in _TWO_TOKEN_PREFIX_FLAGS:
            if idx + 1 < len(raw_clang_flags):
                val = raw_clang_flags[idx + 1]
                bad_f = warn_if_unresolved(flag, "OTHER_CFLAGS")
                bad_v = warn_if_unresolved(val, "OTHER_CFLAGS")
                if not bad_f and not bad_v:
                    clang_flags.extend([flag, val])
                idx += 2
            else:
                warn_if_unresolved(flag, "OTHER_CFLAGS")
                idx += 1
        elif flag == "-I":
            if idx + 1 < len(raw_clang_flags):
                val = raw_clang_flags[idx + 1]
                if not warn_if_unresolved(val, "OTHER_CFLAGS"):
                    add_unique(include_paths, val)
                idx += 2
            else:
                idx += 1
        elif flag == "-F":
            if idx + 1 < len(raw_clang_flags):
                val = raw_clang_flags[idx + 1]
                if not warn_if_unresolved(val, "OTHER_CFLAGS"):
                    add_unique(framework_search_paths, val)
                idx += 2
            else:
                idx += 1
        elif flag == "-L":
            if idx + 1 < len(raw_clang_flags):
                val = raw_clang_flags[idx + 1]
                if not warn_if_unresolved(val, "OTHER_CFLAGS"):
                    add_unique(library_paths, val)
                idx += 2
            else:
                idx += 1
        elif flag == "-framework":
            if idx + 1 < len(raw_clang_flags):
                fw_val = raw_clang_flags[idx + 1]
                if not warn_if_unresolved(fw_val, "OTHER_CFLAGS"):
                    add_unique(frameworks, fw_val)
                idx += 2
            else:
                idx += 1
        elif flag == "-weak_framework":
            if idx + 1 < len(raw_clang_flags):
                wfw_val = raw_clang_flags[idx + 1]
                if not warn_if_unresolved(wfw_val, "OTHER_CFLAGS"):
                    add_unique(weak_frameworks, wfw_val)
                idx += 2
            else:
                idx += 1
        elif flag == "-l":
            if idx + 1 < len(raw_clang_flags):
                lib_val = raw_clang_flags[idx + 1]
                if not warn_if_unresolved(lib_val, "OTHER_CFLAGS"):
                    lflag = f"-l{lib_val}"
                    if not lflag.startswith("-lclang_rt"):
                        add_unique(linker_flags, lflag)
                idx += 2
            else:
                idx += 1
        elif flag.startswith("-I") and len(flag) > 2:
            val = flag[2:]
            if not warn_if_unresolved(val, "OTHER_CFLAGS"):
                add_unique(include_paths, val)
            idx += 1
        elif flag.startswith("-F") and len(flag) > 2:
            val = flag[2:]
            if not warn_if_unresolved(val, "OTHER_CFLAGS"):
                add_unique(framework_search_paths, val)
            idx += 1
        elif flag.startswith("-L") and len(flag) > 2:
            val = flag[2:]
            if not warn_if_unresolved(val, "OTHER_CFLAGS"):
                add_unique(library_paths, val)
            idx += 1
        elif flag.startswith("-l") and len(flag) > 2:
            if not warn_if_unresolved(flag, "OTHER_CFLAGS") and not flag.startswith("-lclang_rt"):
                add_unique(linker_flags, flag)
            idx += 1
        elif flag in ("-target", "-isysroot", "-resource-dir"):
            idx += 2 if idx + 1 < len(raw_clang_flags) else 1
        elif flag.endswith((".c", ".m", ".mm", ".cpp", ".swift")):
            if not warn_if_unresolved(flag, "OTHER_CFLAGS"):
                add_unique(custom_sources, flag)
            idx += 1
        else:
            if not warn_if_unresolved(flag, "OTHER_CFLAGS"):
                clang_flags.append(flag)
            idx += 1

    # 3. Parse OTHER_CPLUSPLUSFLAGS (kept strictly for C++ / ObjC++ compilation)
    raw_cxx_flags = [str(x) for x in expanded.get("OTHER_CPLUSPLUSFLAGS", [])]
    idx = 0
    while idx < len(raw_cxx_flags):
        flag = raw_cxx_flags[idx]
        if flag in _TWO_TOKEN_PREFIX_FLAGS:
            if idx + 1 < len(raw_cxx_flags):
                val = raw_cxx_flags[idx + 1]
                bad_f = warn_if_unresolved(flag, "OTHER_CPLUSPLUSFLAGS")
                bad_v = warn_if_unresolved(val, "OTHER_CPLUSPLUSFLAGS")
                if not bad_f and not bad_v:
                    cxx_flags.extend([flag, val])
                idx += 2
            else:
                warn_if_unresolved(flag, "OTHER_CPLUSPLUSFLAGS")
                idx += 1
        elif flag == "-I":
            if idx + 1 < len(raw_cxx_flags):
                val = raw_cxx_flags[idx + 1]
                if not warn_if_unresolved(val, "OTHER_CPLUSPLUSFLAGS"):
                    add_unique(include_paths, val)
                idx += 2
            else:
                idx += 1
        elif flag == "-F":
            if idx + 1 < len(raw_cxx_flags):
                val = raw_cxx_flags[idx + 1]
                if not warn_if_unresolved(val, "OTHER_CPLUSPLUSFLAGS"):
                    add_unique(framework_search_paths, val)
                idx += 2
            else:
                idx += 1
        elif flag == "-L":
            if idx + 1 < len(raw_cxx_flags):
                val = raw_cxx_flags[idx + 1]
                if not warn_if_unresolved(val, "OTHER_CPLUSPLUSFLAGS"):
                    add_unique(library_paths, val)
                idx += 2
            else:
                idx += 1
        elif flag == "-framework":
            if idx + 1 < len(raw_cxx_flags):
                fw_val = raw_cxx_flags[idx + 1]
                if not warn_if_unresolved(fw_val, "OTHER_CPLUSPLUSFLAGS"):
                    add_unique(frameworks, fw_val)
                idx += 2
            else:
                idx += 1
        elif flag == "-weak_framework":
            if idx + 1 < len(raw_cxx_flags):
                wfw_val = raw_cxx_flags[idx + 1]
                if not warn_if_unresolved(wfw_val, "OTHER_CPLUSPLUSFLAGS"):
                    add_unique(weak_frameworks, wfw_val)
                idx += 2
            else:
                idx += 1
        elif flag.startswith("-I") and len(flag) > 2:
            val = flag[2:]
            if not warn_if_unresolved(val, "OTHER_CPLUSPLUSFLAGS"):
                add_unique(include_paths, val)
            idx += 1
        elif flag.startswith("-F") and len(flag) > 2:
            val = flag[2:]
            if not warn_if_unresolved(val, "OTHER_CPLUSPLUSFLAGS"):
                add_unique(framework_search_paths, val)
            idx += 1
        elif flag.startswith("-L") and len(flag) > 2:
            val = flag[2:]
            if not warn_if_unresolved(val, "OTHER_CPLUSPLUSFLAGS"):
                add_unique(library_paths, val)
            idx += 1
        elif flag in ("-target", "-isysroot", "-resource-dir"):
            idx += 2 if idx + 1 < len(raw_cxx_flags) else 1
        else:
            if not warn_if_unresolved(flag, "OTHER_CPLUSPLUSFLAGS"):
                cxx_flags.append(flag)
            idx += 1

    # 4. Parse OTHER_SWIFT_FLAGS
    raw_swift_flags = [str(x) for x in expanded.get("OTHER_SWIFT_FLAGS", [])]
    idx = 0
    while idx < len(raw_swift_flags):
        sf = raw_swift_flags[idx]
        if sf in ("-target", "-sdk", "-resource-dir", "-module-cache-path"):
            idx += 2 if idx + 1 < len(raw_swift_flags) else 1
        elif sf in ("-parse-as-library", "-emit-object", "-whole-module-optimization"):
            idx += 1
        elif sf in _TWO_TOKEN_PREFIX_FLAGS:
            if idx + 1 < len(raw_swift_flags):
                val = raw_swift_flags[idx + 1]
                bad_f = warn_if_unresolved(sf, "OTHER_SWIFT_FLAGS")
                bad_v = warn_if_unresolved(val, "OTHER_SWIFT_FLAGS")
                if not bad_f and not bad_v:
                    swift_flags.extend([sf, val])
                idx += 2
            else:
                warn_if_unresolved(sf, "OTHER_SWIFT_FLAGS")
                idx += 1
        elif sf == "-I":
            if idx + 1 < len(raw_swift_flags):
                val = raw_swift_flags[idx + 1]
                if not warn_if_unresolved(val, "OTHER_SWIFT_FLAGS"):
                    add_unique(include_paths, val)
                idx += 2
            else:
                idx += 1
        elif sf == "-F":
            if idx + 1 < len(raw_swift_flags):
                val = raw_swift_flags[idx + 1]
                if not warn_if_unresolved(val, "OTHER_SWIFT_FLAGS"):
                    add_unique(framework_search_paths, val)
                idx += 2
            else:
                idx += 1
        elif sf == "-L":
            if idx + 1 < len(raw_swift_flags):
                val = raw_swift_flags[idx + 1]
                if not warn_if_unresolved(val, "OTHER_SWIFT_FLAGS"):
                    add_unique(library_paths, val)
                idx += 2
            else:
                idx += 1
        elif sf == "-framework":
            if idx + 1 < len(raw_swift_flags):
                fw_val = raw_swift_flags[idx + 1]
                if not warn_if_unresolved(fw_val, "OTHER_SWIFT_FLAGS"):
                    add_unique(frameworks, fw_val)
                idx += 2
            else:
                idx += 1
        elif sf == "-weak_framework":
            if idx + 1 < len(raw_swift_flags):
                wfw_val = raw_swift_flags[idx + 1]
                if not warn_if_unresolved(wfw_val, "OTHER_SWIFT_FLAGS"):
                    add_unique(weak_frameworks, wfw_val)
                idx += 2
            else:
                idx += 1
        elif sf.startswith("-I") and len(sf) > 2:
            val = sf[2:]
            if not warn_if_unresolved(val, "OTHER_SWIFT_FLAGS"):
                add_unique(include_paths, val)
            idx += 1
        elif sf.startswith("-F") and len(sf) > 2:
            val = sf[2:]
            if not warn_if_unresolved(val, "OTHER_SWIFT_FLAGS"):
                add_unique(framework_search_paths, val)
            idx += 1
        elif sf.startswith("-L") and len(sf) > 2:
            val = sf[2:]
            if not warn_if_unresolved(val, "OTHER_SWIFT_FLAGS"):
                add_unique(library_paths, val)
            idx += 1
        else:
            if not warn_if_unresolved(sf, "OTHER_SWIFT_FLAGS"):
                swift_flags.append(sf)
            idx += 1

    # 5. Parse OTHER_LDFLAGS (translating Clang-driver -Xlinker and -Wl, syntax for direct ld64.lld invocation)
    raw_linker_input = [str(x) for x in expanded.get("OTHER_LDFLAGS", [])]
    raw_linker_flags, linker_syntax_errors = translate_driver_linker_flags(raw_linker_input)
    for syntax_err in linker_syntax_errors:
        unresolved_warnings.append(syntax_err)
        log_warning(syntax_err)
        if warning_callback:
            warning_callback(syntax_err)

    idx = 0
    while idx < len(raw_linker_flags):
        flag = raw_linker_flags[idx]
        if flag in _TWO_TOKEN_PREFIX_FLAGS:
            if idx + 1 < len(raw_linker_flags):
                val = raw_linker_flags[idx + 1]
                bad_f = warn_if_unresolved(flag, "OTHER_LDFLAGS")
                bad_v = warn_if_unresolved(val, "OTHER_LDFLAGS")
                if not bad_f and not bad_v:
                    linker_flags.extend([flag, val])
                idx += 2
            else:
                if not warn_if_unresolved(flag, "OTHER_LDFLAGS"):
                    err_msg = f"Invalid linker flag in OTHER_LDFLAGS: '{flag}' is missing its required argument"
                    unresolved_warnings.append(err_msg)
                    log_warning(err_msg)
                    if warning_callback:
                        warning_callback(err_msg)
                idx += 1
        elif flag == "-framework":
            if idx + 1 < len(raw_linker_flags):
                fw = raw_linker_flags[idx + 1]
                if not warn_if_unresolved(fw, "OTHER_LDFLAGS"):
                    add_unique(frameworks, fw)
                idx += 2
            else:
                idx += 1
        elif flag == "-weak_framework":
            if idx + 1 < len(raw_linker_flags):
                wfw = raw_linker_flags[idx + 1]
                if not warn_if_unresolved(wfw, "OTHER_LDFLAGS"):
                    add_unique(weak_frameworks, wfw)
                idx += 2
            else:
                idx += 1
        elif flag == "-F":
            if idx + 1 < len(raw_linker_flags):
                val = raw_linker_flags[idx + 1]
                if not warn_if_unresolved(val, "OTHER_LDFLAGS"):
                    add_unique(framework_search_paths, val)
                idx += 2
            else:
                idx += 1
        elif flag == "-L":
            if idx + 1 < len(raw_linker_flags):
                val = raw_linker_flags[idx + 1]
                if not warn_if_unresolved(val, "OTHER_LDFLAGS"):
                    add_unique(library_paths, val)
                idx += 2
            else:
                idx += 1
        elif flag == "-l":
            if idx + 1 < len(raw_linker_flags):
                lib_val = raw_linker_flags[idx + 1]
                if not warn_if_unresolved(lib_val, "OTHER_LDFLAGS"):
                    lflag = f"-l{lib_val}"
                    if not lflag.startswith("-lclang_rt"):
                        add_unique(linker_flags, lflag)
                idx += 2
            else:
                idx += 1
        elif flag.startswith("-F") and len(flag) > 2:
            val = flag[2:]
            if not warn_if_unresolved(val, "OTHER_LDFLAGS"):
                add_unique(framework_search_paths, val)
            idx += 1
        elif flag.startswith("-L") and len(flag) > 2:
            val = flag[2:]
            if not warn_if_unresolved(val, "OTHER_LDFLAGS"):
                add_unique(library_paths, val)
            idx += 1
        elif flag.startswith("-l") and len(flag) > 2:
            if not warn_if_unresolved(flag, "OTHER_LDFLAGS") and not flag.startswith("-lclang_rt"):
                add_unique(linker_flags, flag)
            idx += 1
        else:
            if not warn_if_unresolved(flag, "OTHER_LDFLAGS"):
                linker_flags.append(flag)
            idx += 1

    # 6. Build resolved extra_inc_flags, extra_fw_flags, and resolved library_paths
    extra_inc_flags: List[str] = []
    seen_inc_dirs = set()
    for inc in include_paths:
        cand = Path(inc)
        if not cand.is_absolute():
            cand = (project_dir / inc).resolve()
        cand_str = str(cand)
        if cand_str not in seen_inc_dirs:
            seen_inc_dirs.add(cand_str)
            extra_inc_flags.extend(["-I", cand_str])

    proj_root_str = str(project_dir.resolve())
    if proj_root_str not in seen_inc_dirs:
        seen_inc_dirs.add(proj_root_str)
        extra_inc_flags.extend(["-I", proj_root_str])

    extra_fw_flags: List[str] = []
    seen_fw_dirs = set()
    custom_fw_dir = project_dir / "Frameworks"
    if custom_fw_dir.is_dir():
        fw_root_str = str(custom_fw_dir.resolve())
        seen_fw_dirs.add(fw_root_str)
        extra_fw_flags.extend(["-F", fw_root_str])

    for fwp in framework_search_paths:
        cand = Path(fwp)
        if not cand.is_absolute():
            cand = (project_dir / fwp).resolve()
        cand_str = str(cand)
        if cand_str not in seen_fw_dirs:
            seen_fw_dirs.add(cand_str)
            extra_fw_flags.extend(["-F", cand_str])

    resolved_library_paths: List[str] = []
    for libp in library_paths:
        cand = Path(libp)
        if not cand.is_absolute():
            cand = (project_dir / libp).resolve()
        add_unique(resolved_library_paths, str(cand))

    return {
        "expanded_config": expanded,
        "clang_flags": clang_flags,
        "cxx_flags": cxx_flags,
        "swift_flags": swift_flags,
        "include_paths": include_paths,
        "framework_search_paths": framework_search_paths,
        "library_paths": resolved_library_paths,
        "extra_inc_flags": extra_inc_flags,
        "extra_fw_flags": extra_fw_flags,
        "frameworks": frameworks,
        "weak_frameworks": weak_frameworks,
        "linker_flags": linker_flags,
        "custom_sources": custom_sources,
        "unresolved_warnings": unresolved_warnings,
    }

def _handle_build_cleanup(
    cancel_controller: Optional[Any],
    tracker: Optional[Any],
    progress_mgr: Optional[Any] = None,
    is_success_so_far: bool = False,
    original_exception: Optional[BaseException] = None,
) -> bool:
    """
    Executes subprocess cleanup, records structured cleanup telemetry in the transcript,
    and determines whether the overall build should be considered clean.
    Never hides original exceptions or KeyboardInterrupt.
    Returns True if cleanup completed without confirmed active processes remaining; False otherwise.
    """
    if cancel_controller is None:
        return True

    cleanup_summary: Optional[Dict[str, Any]] = None
    cleanup_exc: Optional[Exception] = None
    try:
        cleanup_summary = cancel_controller.cleanup_all()
    except Exception as ex:
        cleanup_exc = ex

    remaining_count = 0
    unreaped_pids: List[int] = []
    telemetry: Dict[str, Any] = {}

    if cleanup_summary and isinstance(cleanup_summary, dict):
        cleanup_sub = cleanup_summary.get("cleanup", {})
        remaining_count = int(cleanup_summary.get("active_processes_remaining", cleanup_sub.get("active_processes_remaining", 0)))
        unreaped_pids = list(cleanup_sub.get("unreaped_pids", []))
        telemetry = {
            "processes_signalled": cleanup_summary.get("processes_signalled", 0),
            "processes_terminated_gracefully": cleanup_summary.get("processes_terminated_gracefully", 0),
            "processes_force_killed": cleanup_summary.get("processes_force_killed", 0),
            "processes_reaped": cleanup_summary.get("processes_reaped", 0),
            "descendant_pids_killed": cleanup_summary.get("descendant_pids_killed", []),
            "unstarted_tasks_cancelled": cleanup_summary.get("unstarted_tasks_cancelled", 0),
        }
    elif cleanup_exc is not None:
        remaining_count = getattr(cancel_controller, "active_processes_remaining", 0)
        if hasattr(cancel_controller, "_active_processes"):
            try:
                unreaped_pids = [r.pid for r in cancel_controller._active_processes.values() if getattr(r, "is_alive", lambda: False)()]
                remaining_count = len(unreaped_pids)
            except Exception:
                pass

    effective_remaining = max(remaining_count, len(unreaped_pids))

    status = "succeeded"
    err_msg: Optional[str] = None
    if effective_remaining > 0 or unreaped_pids:
        status = "failed"
        err_msg = f"{effective_remaining} build-owned process(es) remained active after cleanup (PIDs: {unreaped_pids})"
    elif cleanup_exc is not None:
        status = "warning"
        err_msg = f"Cleanup exception: {cleanup_exc}"
    elif cleanup_summary and isinstance(cleanup_summary, dict):
        cleanup_sub = cleanup_summary.get("cleanup", {})
        if cleanup_sub.get("error"):
            status = "warning" if effective_remaining == 0 else "failed"
            err_msg = cleanup_sub.get("error")

    # Record structured cleanup in transcript
    transcript = getattr(tracker, "transcript", None)
    if transcript is not None and hasattr(transcript, "record_cleanup"):
        try:
            transcript.record_cleanup(
                attempted=True,
                completed=(status in ("succeeded", "warning")),
                status=status,
                active_processes_remaining=effective_remaining,
                unreaped_pids=unreaped_pids,
                error=err_msg,
                telemetry=telemetry,
            )
        except Exception as ex:
            persistence_err = f"Failed to record cleanup diagnostics: {ex}"
            if tracker is not None:
                tracker.add_warning(f"[persistence] {persistence_err}")
            sys.stderr.write(f"[NyxWin Warning] {persistence_err}\n")

    if tracker is not None:
        if status == "warning" and err_msg:
            tracker.add_warning(f"[cleanup] {err_msg}")
        elif status == "failed" and err_msg:
            tracker.add_error(f"[cleanup] {err_msg}")

    # Return True ONLY if cleanup is cleanly successful or warning with 0 active/unreaped processes;
    # NEVER return True when any process is unreaped or remaining or status is failed.
    is_clean = (status in ("succeeded", "warning")) and (effective_remaining == 0) and (len(unreaped_pids) == 0)
    return is_clean

def build_project(
    toolchain: Toolchain,
    project_dir_or_name: Path,
    target_triple: Optional[str] = None,
    verbose: bool = False,
    requested_sdk: Optional[str] = None,
    profile: str = "auto",
    *,
    cancel_event: Optional[Any] = None,
    cancel_controller: Optional[Any] = None,
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
    build_completed_cleanly = False
    original_exc: Optional[BaseException] = None

    # Initialize or bind BuildCancellationController
    if cancel_controller is None:
        cancel_controller = BuildCancellationController(external_cancel_event=cancel_event)
    elif cancel_event is not None and getattr(cancel_controller, "_external_cancel_event", None) is None:
        cancel_controller._external_cancel_event = cancel_event

    # 1. Resolve Project Directory
    if isinstance(project_dir_or_name, str):
        project_dir_or_name = Path(project_dir_or_name)

    if project_dir_or_name.is_dir():
        project_dir = project_dir_or_name.resolve()
    else:
        found = toolchain.get_project_dir(str(project_dir_or_name)) if hasattr(toolchain, "get_project_dir") else None
        if found and Path(found).is_dir():
            project_dir = Path(found).resolve()
        else:
            cand = toolchain.projects_dir / project_dir_or_name if getattr(toolchain, "projects_dir", None) else None
            if cand and cand.is_dir():
                project_dir = cand.resolve()
            else:
                log_error(f"Project not found: {project_dir_or_name}")
                return False

    project_config = load_project_config(project_dir)
    has_valid_config = bool(project_config)
    if not project_config:
        project_config = {}

    product_name = str(
        project_config.get("PRODUCT_NAME")
        or project_config.get("CFBundleDisplayName")
        or project_dir.name
    )
    display_name = str(project_config.get("CFBundleDisplayName") or product_name)
    app_name = product_name
    exec_name = str(project_config.get("EXECUTABLE_NAME") or product_name)
    bundle_id = str(project_config.get("PRODUCT_BUNDLE_IDENTIFIER") or f"com.example.{product_name.lower()}")
    deployment_target = str(project_config.get("IPHONEOS_DEPLOYMENT_TARGET", "17.0"))
    scheme = project_config.get("TargetType", "Application")
    target_type = "app"

    eff_target_triple = target_triple or f"arm64-apple-ios{deployment_target}"

    proj_id = None
    if has_valid_config:
        try:
            proj_id = get_or_create_project_id(project_dir, project_config)
        except Exception:
            proj_id = None

    global _last_tracker
    tracker = BuildProgressTracker(display_name, eff_target_triple, profile=profile, project_dir=project_dir)
    try:
        transcript = BuildTranscript(
            display_name,
            project_dir,
            eff_target_triple,
            deployment_target,
            profile,
            toolchain,
            product_name=product_name,
            display_name=display_name,
            executable_name=exec_name,
            bundle_id=bundle_id,
            project_id=proj_id,
        )
        tracker.transcript = transcript
    except Exception:
        pass
    tracker.cancel_controller = cancel_controller
    _last_tracker = tracker
    progress_mgr = LiveProgressManager(tracker, cancel_controller=cancel_controller, verbose=verbose)
    progress_mgr.start()

    try:
        cancel_controller.check_cancelled(stage_idx=1)

        # Early validation: configuration existence
        if not has_valid_config:
            err_msg = f"Failed to read project configuration (Project.plist) in {project_dir}"
            log_error(err_msg)
            progress_mgr.finish_failure(1, err_msg, tool="config", exit_code=1)
            return False

        # Check Toolchain readiness
        if not toolchain.sdk_dir or not toolchain.sdk_dir.is_dir():
            from nyxwin.config.paths import get_sdks_root
            err_msg = f"No valid iOS SDK found in {get_sdks_root()}. Run 'nyx sdk install 26.5'."
            log_error(err_msg)
            progress_mgr.finish_failure(1, err_msg, tool="sdk", exit_code=1)
            return False

        if scheme.lower() not in ("application", "app"):
            err_msg = (
                f"Project scheme '{scheme}' is no longer supported.\n"
                f"NyxWin is now focused exclusively on Swift iOS applications ('swiftui' or 'swift-uikit')."
            )
            log_error(err_msg)
            progress_mgr.finish_failure(1, err_msg, tool="config", exit_code=1)
            return False

        # Sanitize Swift module name
        swift_module_name = re.sub(r'[^a-zA-Z0-9_]', '_', exec_name)
        if swift_module_name and swift_module_name[0].isdigit():
            swift_module_name = "_" + swift_module_name
        if not swift_module_name:
            swift_module_name = "App"

        # External Build Intermediates & External Compiler Cache (resolved BEFORE macro expansion)
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

        # Expand canonical project macros and parse compiler/linker flags
        cancel_controller.check_cancelled(stage_idx=1)
        parsed_flags = expand_and_parse_build_flags(
            project_config,
            project_dir=project_dir,
            sdk_dir=toolchain.sdk_dir,
            cache_dir=cache_dir,
            build_dir=build_dir,
            warning_callback=progress_mgr.print_warning,
        )
        clang_flags = parsed_flags["clang_flags"]
        cxx_flags = parsed_flags["cxx_flags"]
        swift_flags = parsed_flags["swift_flags"]
        include_paths = parsed_flags["include_paths"]
        library_paths = parsed_flags["library_paths"]
        extra_inc_flags = parsed_flags["extra_inc_flags"]
        extra_fw_flags = parsed_flags["extra_fw_flags"]
        frameworks = parsed_flags["frameworks"]
        weak_frameworks = parsed_flags["weak_frameworks"]
        linker_flags = parsed_flags["linker_flags"]
        custom_sources = parsed_flags["custom_sources"]
        custom_fw_dir = project_dir / "Frameworks"

        # Step 1: Discover Source Files
        cancel_controller.check_cancelled(stage_idx=1)
        tracker.start_stage(1, "Scanning Source Files")
        if parsed_flags.get("unresolved_warnings"):
            err_detail = "; ".join(parsed_flags["unresolved_warnings"])
            tracker.add_error(err_detail)
            progress_mgr.finish_failure(
                1,
                f"Build aborted due to unresolved project macro(s): {err_detail}",
                tool="config",
                exit_code=1,
            )
            return False

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

        cancel_controller.check_cancelled(stage_idx=1)
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
        cancel_controller.check_cancelled(stage_idx=2)
        tracker.start_stage(2, "Compiling Source Files")
        obj_files = []
        current_manifest = dict(build_manifest)

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

        # 2A: Compile C/ObjC
        if c_sources:
            cancel_controller.check_cancelled(stage_idx=2)
            if not toolchain.clang:
                progress_mgr.finish_failure(2, "clang.exe not found. Please install LLVM on Windows.", tool="clang", exit_code=1)
                return False
            compile_c_res = compile_c_sources(
                toolchain.clang, toolchain.sdk_dir, c_sources, project_dir, obj_dir,
                eff_target_triple, extra_inc_flags, extra_fw_flags, effective_clang_flags,
                current_manifest, verbose,
                progress_callback=tracker.update_c_progress,
                warning_callback=progress_mgr.print_warning,
                error_callback=tracker.add_error,
                operation_callback=tracker.record_operation,
                cxx_flags=cxx_flags,
                cancel_controller=cancel_controller,
            )
            if isinstance(compile_c_res, tuple) and len(compile_c_res) >= 3:
                ok_c, c_objs, current_manifest = compile_c_res[0], compile_c_res[1], compile_c_res[2]
            elif isinstance(compile_c_res, tuple) and len(compile_c_res) == 2:
                ok_c, c_objs = compile_c_res[0], compile_c_res[1]
            else:
                ok_c, c_objs = False, []
            if not ok_c:
                progress_mgr.finish_failure(2, "C/ObjC compilation failed", tool="clang", exit_code=1)
                return False
            obj_files.extend(c_objs)

        # 2B: Compile Swift
        if swift_sources:
            cancel_controller.check_cancelled(stage_idx=2)
            if not toolchain.swiftc:
                progress_mgr.finish_failure(2, "swiftc.exe not found. Please install Swift for Windows.", tool="swiftc", exit_code=1)
                return False
            compile_s_res = compile_swift_sources(
                toolchain.swiftc, toolchain.clang, toolchain.sdk_dir, toolchain.swift_resource_dir,
                toolchain.tools_dir, swift_sources, project_dir, obj_dir,
                eff_target_triple, swift_module_name, app_name, extra_inc_flags, extra_fw_flags,
                swift_flags, current_manifest, verbose, cache_dir=cache_dir,
                progress_callback=tracker.update_swift_progress,
                warning_callback=progress_mgr.print_warning,
                error_callback=tracker.add_error,
                operation_callback=tracker.record_operation,
                cancel_controller=cancel_controller,
            )
            if isinstance(compile_s_res, tuple) and len(compile_s_res) >= 3:
                ok_s, s_objs, current_manifest = compile_s_res[0], compile_s_res[1], compile_s_res[2]
            elif isinstance(compile_s_res, tuple) and len(compile_s_res) == 2:
                ok_s, s_objs = compile_s_res[0], compile_s_res[1]
            else:
                ok_s, s_objs = False, []
            if not ok_s:
                progress_mgr.finish_failure(2, "Swift compilation failed", tool="swiftc", exit_code=1)
                return False
            obj_files.extend(s_objs)

        cancel_controller.check_cancelled(stage_idx=2)
        # Save incremental manifest
        try:
            manifest_file.write_text(json.dumps(current_manifest, indent=2), encoding="utf-8")
        except Exception:
            pass

        tracker.complete_stage(2, f"Compiled {len(obj_files)} objects")

        # Step 3: Link Mach-O
        cancel_controller.check_cancelled(stage_idx=3)
        tracker.start_stage(3, "Linking Mach-O Executable (ld64.lld)")
        linker_bin = toolchain.ld64 if toolchain.ld64 else toolchain.lld
        if not linker_bin:
            progress_mgr.finish_failure(3, "LLVM linker (lld.exe / ld64.lld) not found.", tool="ld64.lld", exit_code=1)
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
            operation_callback=tracker.record_operation,
            cancel_controller=cancel_controller,
        )
        if not ok_link:
            progress_mgr.finish_failure(3, "Mach-O linking failed", tool="ld64.lld", exit_code=1)
            return False

        cancel_controller.check_cancelled(stage_idx=3)
        tracker.complete_stage(3, f"Linked Mach-O binary -> {exec_name}")

        # Step 4: Mach-O Patch #31
        cancel_controller.check_cancelled(stage_idx=4)
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
        # Note: signer.py is strictly preserved. Invocations of ldid run atomically;
        # cancellation is checked immediately before and after this stage boundary.
        cancel_controller.check_cancelled(stage_idx=5)
        tracker.start_stage(5, f"Injecting Entitlements ({profile}) & ldid")
        ok_sign = sign_binary(
            toolchain.ldid, out_binary, project_dir, build_dir,
            profile=profile, verbose=verbose,
            operation_callback=tracker.record_operation
        )
        if not ok_sign:
            progress_mgr.finish_failure(5, "Ad-hoc codesigning with ldid failed", tool="ldid", exit_code=1)
            return False

        cancel_controller.check_cancelled(stage_idx=5)
        tracker.complete_stage(5, f"Signed Mach-O binary ({profile})")

        # Step 6: Packaging
        cancel_controller.check_cancelled(stage_idx=6)
        tracker.start_stage(6, "Packaging Application & Creating .ipa")
        final_artifact_path = package_application(
            build_dir, final_output_dir, project_dir, out_binary,
            app_name, exec_name, bundle_id, deployment_target, target_type,
            project_config, custom_fw_dir, toolchain.ldid,
            operation_callback=tracker.record_operation,
            cancel_controller=cancel_controller,
        )
        cancel_controller.check_cancelled(stage_idx=6)
        artifact_label = "Output IPA"

        if not final_artifact_path or (final_artifact_path.is_file() is False and final_artifact_path.is_dir() is False):
            progress_mgr.finish_failure(6, f"Packaging {artifact_label} failed.", tool="packager", exit_code=1)
            return False

        if final_artifact_path.is_file():
            artifact_size = final_artifact_path.stat().st_size
        else:
            artifact_size = sum(f.stat().st_size for f in final_artifact_path.rglob('*') if f.is_file())

        tracker.ipa_path = final_artifact_path.resolve()
        if tracker.transcript and not tracker.transcript.package_record:
            tracker.transcript.record_package(
                operation="Create IPA Package",
                app_bundle_dir=str(build_dir / "Payload" / f"{product_name}.app"),
                files_included=[],
                ipa_path=str(final_artifact_path.resolve()),
                ipa_size=artifact_size,
                ipa_sha256="",
                is_valid_zip=True,
                info_plist_summary={},
                elapsed=0.0,
            )
        tracker.complete_stage(6, f"Created {final_artifact_path.name} ({artifact_size:,} bytes)")
        if tracker.transcript and not getattr(tracker.transcript, "log_path", None):
            try:
                if hasattr(tracker.transcript, "sync_from_tracker"):
                    tracker.transcript.sync_from_tracker(tracker)
                tracker.log_path = tracker.transcript.finalize(is_success=True)
                tracker.report_path = getattr(tracker.transcript, "report_path", None)
            except Exception:
                pass
        build_completed_cleanly = True
    except BuildCancelledError as bce:
        original_exc = bce
        eff_stage = bce.stage_idx or (tracker.active_stage_idx + 1 if tracker else 1)
        cancel_controller.cancel(reason=str(bce), stage_idx=eff_stage)
        summary = cancel_controller.get_summary()
        if progress_mgr is not None:
            progress_mgr.finish_cancelled(eff_stage, cancel_msg=str(bce), cancellation_info=summary)
        elif tracker is not None:
            tracker.cancel_stage(eff_stage, str(bce))
            tracker.cancellation_info = summary
            if tracker.transcript and not getattr(tracker.transcript, "log_path", None):
                try:
                    tracker.transcript.finalize(
                        is_success=False,
                        failure_stage=eff_stage,
                        failure_reason=str(bce),
                        cancelled=True,
                        cancellation_info=summary,
                    )
                except Exception:
                    pass
        return False
    except KeyboardInterrupt as ki:
        original_exc = ki
        eff_stage = tracker.active_stage_idx + 1 if tracker else 1
        cancel_msg = "Build aborted by user (Ctrl+C)"
        cancel_controller.cancel(reason=cancel_msg, stage_idx=eff_stage)
        summary = cancel_controller.get_summary()
        if progress_mgr is not None:
            progress_mgr.finish_cancelled(eff_stage, cancel_msg=cancel_msg, cancellation_info=summary)
        elif tracker is not None:
            tracker.cancel_stage(eff_stage, cancel_msg)
            tracker.cancellation_info = summary
            if tracker.transcript and not getattr(tracker.transcript, "log_path", None):
                try:
                    tracker.transcript.finalize(
                        is_success=False,
                        failure_stage=eff_stage,
                        failure_reason=cancel_msg,
                        cancelled=True,
                        cancellation_info=summary,
                    )
                except Exception:
                    pass
        return False
    except Exception as e:
        original_exc = e
        eff_stage = tracker.active_stage_idx + 1 if tracker else 1
        err_msg = f"Build error: {e}"
        if progress_mgr is not None:
            progress_mgr.finish_failure(eff_stage, err_msg)
        elif tracker is not None:
            tracker.add_error(err_msg)
            tracker.fail_stage(eff_stage, err_msg)
            if tracker.transcript and not getattr(tracker.transcript, "log_path", None):
                try:
                    tracker.transcript.finalize(
                        is_success=False,
                        failure_stage=eff_stage,
                        failure_reason=err_msg,
                    )
                except Exception:
                    pass
        return False
    finally:
        cleanup_clean = _handle_build_cleanup(
            cancel_controller=cancel_controller,
            tracker=tracker,
            progress_mgr=progress_mgr,
            is_success_so_far=build_completed_cleanly,
            original_exception=original_exc,
        )
        # Render the final outcome card based on actual post-cleanup state
        if progress_mgr is not None:
            if build_completed_cleanly and not progress_mgr.closed:
                if cleanup_clean:
                    progress_mgr.finish_success(final_artifact_path, artifact_size, artifact_label=artifact_label)
                else:
                    err_msg = "Build completed but process cleanup failed (active/unreaped processes remain)"
                    progress_mgr.finish_failure(6, err_msg, tool="cleanup", exit_code=1)
            try:
                progress_mgr.close()
            except Exception:
                pass
        if build_completed_cleanly and not cleanup_clean and original_exc is None:
            build_completed_cleanly = False
    return build_completed_cleanly
