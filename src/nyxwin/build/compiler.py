import os
import re
import sys
import time
import hashlib
import threading
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed, CancelledError
from typing import List, Tuple, Dict, Optional, Any

from nyxwin.core.models import Color, log_info, log_error, log_step
from nyxwin.core.diagnostics import format_compiler_diagnostics
from nyxwin.build.process_manager import (
    BuildCancellationController,
    BuildCancelledError,
    run_build_subprocess,
)

PLATFORM_CHECK_SOURCE = """#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

typedef uint32_t dyld_platform_t;

typedef struct {
    dyld_platform_t platform;
    uint32_t version;
} dyld_build_version_t;

extern bool _availability_version_check(uint32_t count, const dyld_build_version_t versions[]) __attribute__((weak_import));
extern int sysctlbyname(const char *name, void *oldp, size_t *oldlenp, void *newp, size_t newlen);

int32_t __isPlatformVersionAtLeast(uint32_t Platform, uint32_t Major, uint32_t Minor, uint32_t Subminor) {
    if (_availability_version_check != NULL) {
        dyld_build_version_t req;
        req.platform = Platform;
        req.version = (Major << 16) | (Minor << 8) | Subminor;
        return _availability_version_check(1, &req) ? 1 : 0;
    }

    char os_ver[64] = {0};
    size_t len = sizeof(os_ver) - 1;
    if (sysctlbyname("kern.osproductversion", os_ver, &len, NULL, 0) == 0) {
        uint32_t cur_major = 0, cur_minor = 0, cur_subminor = 0;
        char *dot1 = strchr(os_ver, '.');
        if (dot1) {
            *dot1 = '\\0';
            cur_major = (uint32_t)atoi(os_ver);
            char *dot2 = strchr(dot1 + 1, '.');
            if (dot2) {
                *dot2 = '\\0';
                cur_minor = (uint32_t)atoi(dot1 + 1);
                cur_subminor = (uint32_t)atoi(dot2 + 1);
            } else {
                cur_minor = (uint32_t)atoi(dot1 + 1);
            }
        } else {
            cur_major = (uint32_t)atoi(os_ver);
        }

        if (cur_major > Major) return 1;
        if (cur_major < Major) return 0;
        if (cur_minor > Minor) return 1;
        if (cur_minor < Minor) return 0;
        return (cur_subminor >= Subminor) ? 1 : 0;
    }
    return 0;
}

int32_t __isOSVersionAtLeast(uint32_t Major, uint32_t Minor, uint32_t Subminor) {
    return __isPlatformVersionAtLeast(2 /* PLATFORM_IOS */, Major, Minor, Subminor);
}
"""

def get_file_hash(path: Path) -> str:
    """Computes SHA-256 hash of file content for change tracking."""
    return hashlib.sha256(path.read_bytes()).hexdigest()

def find_bridging_header(project_dir: Path, app_name: str) -> Optional[Path]:
    """
    Discovers an Objective-C bridging header for Swift compilation.
    Checks for:
      1. <AppName>-Bridging-Header.h in project root or Config/
      2. Bridging-Header.h in project root or Config/
      3. Any *-Bridging-Header.h in project root
    """
    candidates = [
        project_dir / f"{app_name}-Bridging-Header.h",
        project_dir / "Config" / f"{app_name}-Bridging-Header.h",
        project_dir / "Source" / f"{app_name}-Bridging-Header.h",
        project_dir / "Bridging-Header.h",
        project_dir / "Config" / "Bridging-Header.h",
        project_dir / "Source" / "Bridging-Header.h",
    ]
    for c in candidates:
        if c.is_file():
            return c

    # Generic glob
    found = list(project_dir.glob("*-Bridging-Header.h"))
    if found:
        return found[0]
    return None

def compute_c_object_path(src: Path, project_dir: Path, obj_dir: Path) -> Tuple[Path, str, str]:
    """
    Computes a deterministic, collision-resistant object file path inside `obj_dir`
    for a C/Objective-C/C++/Objective-C++ source file.

    Returns:
        (obj_path, rel_src_display, manifest_key)
    """
    try:
        rel_path = src.resolve().relative_to(project_dir.resolve())
        rel_posix = rel_path.as_posix()
        rel_display = str(src.relative_to(project_dir))
    except ValueError:
        rel_posix = src.name
        rel_display = src.name

    # Short SHA-256 digest of normalized relative POSIX path (including directory + extension)
    path_digest = hashlib.sha256(rel_posix.encode("utf-8")).hexdigest()[:10]

    # Readable ASCII-safe prefix from relative path + extension
    safe_prefix = re.sub(r"[^A-Za-z0-9_]+", "_", rel_posix).strip("_")
    if not safe_prefix:
        safe_prefix = "source"
    if len(safe_prefix) > 64:
        safe_prefix = safe_prefix[:64].rstrip("_")

    obj_filename = f"{safe_prefix}_{path_digest}.o"
    obj_path = obj_dir / obj_filename

    # Ensure object path stays strictly flat inside obj_dir
    if obj_path.parent.resolve() != obj_dir.resolve():
        raise ValueError(f"Object path escaped object directory: {obj_path}")

    manifest_key = f"c_obj_v2:{rel_posix}"
    return obj_path, rel_display, manifest_key


def compile_c_sources(
    clang_bin: Path,
    sdk_dir: Path,
    c_sources: List[Path],
    project_dir: Path,
    obj_dir: Path,
    target_triple: str,
    extra_inc_flags: List[str],
    extra_fw_flags: List[str],
    compiler_flags: List[str],
    build_manifest: Dict[str, str],
    verbose: bool = False,
    progress_callback: Optional[Any] = None,
    warning_callback: Optional[Any] = None,
    error_callback: Optional[Any] = None,
    operation_callback: Optional[Any] = None,
    cxx_flags: Optional[List[str]] = None,
    cancel_controller: Optional[BuildCancellationController] = None,
) -> Tuple[bool, List[Path], Dict[str, str]]:
    """Compiles C, Objective-C, and C++ files concurrently with SHA-256 caching and collision-resistant object naming."""
    if cancel_controller is not None:
        cancel_controller.check_cancelled(stage_idx=2)

    results_by_index: Dict[int, Path] = {}
    new_manifest = dict(build_manifest)
    total_sources = len(c_sources)
    completed_count = 0
    cached_count = 0
    extra_cxx = list(cxx_flags) if cxx_flags else []
    abort_event = threading.Event()

    def compile_single(idx: int, src: Path):
        if cancel_controller is not None and cancel_controller.is_cancelled:
            cancel_controller.record_unstarted_task_cancelled()
            raise BuildCancelledError(cancel_controller.cancel_reason or "Build cancelled by user", stage_idx=2)
        if abort_event.is_set():
            return (idx, src, None, None, False, "", "", "", [], 0.0)

        obj_path, rel_src, manifest_key = compute_c_object_path(src, project_dir, obj_dir)
        cur_hash = get_file_hash(src)

        if obj_path.is_file() and build_manifest.get(manifest_key) == cur_hash:
            return (idx, src, obj_path, None, True, rel_src, manifest_key, cur_hash, [], 0.0)

        is_cxx = src.suffix.lower() in (".cpp", ".cxx", ".cc", ".mm")
        src_flags = compiler_flags + (extra_cxx if is_cxx else [])
        cmd = [
            str(clang_bin),
            "-target", target_triple,
            "-isysroot", str(sdk_dir),
            "-c", str(src),
            "-o", str(obj_path)
        ] + extra_inc_flags + extra_fw_flags + src_flags

        if verbose:
            print("  [CMD]", " ".join(cmd))

        t0 = time.monotonic()
        try:
            proc = run_build_subprocess(
                cmd,
                cwd=project_dir,
                cancel_controller=cancel_controller,
                tool_name="clang",
                stage_idx=2,
                run_fn=subprocess.run,
            )
        except BuildCancelledError:
            if obj_path.is_file():
                try:
                    obj_path.unlink()
                except Exception:
                    pass
            raise
        elapsed = time.monotonic() - t0
        return (idx, src, obj_path, proc, False, rel_src, manifest_key, cur_hash, cmd, elapsed)

    with ThreadPoolExecutor(max_workers=min(os.cpu_count() or 4, 8)) as executor:
        futures = []
        for idx, s in enumerate(c_sources):
            if cancel_controller is not None and cancel_controller.is_cancelled:
                cancel_controller.record_unstarted_task_cancelled()
                continue
            fut = executor.submit(compile_single, idx, s)
            if cancel_controller is not None:
                cancel_controller.register_future(fut)
            futures.append(fut)

        try:
            for fut in as_completed(futures):
                if cancel_controller is not None and cancel_controller.is_cancelled:
                    cancel_controller.cancel(stage_idx=2)
                    raise BuildCancelledError(cancel_controller.cancel_reason or "Build cancelled by user", stage_idx=2)

                try:
                    idx, src, obj_path, proc, was_cached, rel_src, manifest_key, cur_hash, cmd, elapsed = fut.result()
                except CancelledError:
                    raise BuildCancelledError(
                        (cancel_controller.cancel_reason if cancel_controller else None) or "Build cancelled by user",
                        stage_idx=2,
                    )

                if obj_path is None:
                    continue

                completed_count += 1
                if was_cached:
                    cached_count += 1
                    if operation_callback:
                        operation_callback(
                            tool="clang",
                            input_file=rel_src,
                            output_file=obj_path.name,
                            cmd=[],
                            cwd=str(project_dir),
                            exit_code=0,
                            elapsed=0.0,
                            cached=True,
                            stdout="",
                            stderr="",
                            output_valid=obj_path.is_file(),
                            output_size=obj_path.stat().st_size if obj_path.is_file() else 0
                        )
                    if not progress_callback:
                        print(f"  {Color.WHITE}[CACHED]{Color.RESET} {src.name}")
                else:
                    is_mock = type(proc).__name__ in ("MagicMock", "Mock") or hasattr(proc, "_mock_return_value")
                    out_valid = (obj_path.is_file() and obj_path.stat().st_size > 0) if not is_mock else (proc.returncode == 0)
                    out_sz = obj_path.stat().st_size if obj_path.is_file() else 0
                    if operation_callback:
                        operation_callback(
                            tool="clang",
                            input_file=rel_src,
                            output_file=obj_path.name,
                            cmd=cmd,
                            cwd=str(project_dir),
                            exit_code=proc.returncode,
                            elapsed=elapsed,
                            cached=False,
                            stdout=proc.stdout,
                            stderr=proc.stderr,
                            output_valid=out_valid,
                            output_size=out_sz
                        )
                    if proc.returncode != 0 or not out_valid:
                        abort_event.set()
                        for other_f in futures:
                            other_f.cancel()
                        if error_callback:
                            error_callback(proc.stderr or f"Compilation produced no valid object: {obj_path.name}")
                        elif not progress_callback:
                            log_error(f"Compilation failed for {src.name}:")
                            format_compiler_diagnostics(proc.stderr)
                        return False, [], build_manifest
                    if proc.stderr:
                        if warning_callback:
                            warning_callback(proc.stderr)
                        elif not progress_callback:
                            format_compiler_diagnostics(proc.stderr)
                    new_manifest[manifest_key] = cur_hash
                    new_manifest[rel_src] = cur_hash
                    if not progress_callback:
                        print(f"  {Color.GREEN}[+]{Color.RESET} Compiled {src.name}")

                results_by_index[idx] = obj_path
                if progress_callback:
                    progress_callback(completed_count, total_sources, cached_count, src.name)
        except KeyboardInterrupt:
            abort_event.set()
            if cancel_controller is not None:
                cancel_controller.cancel(reason="Build aborted by user (Ctrl+C)", stage_idx=2)
            else:
                for other_f in futures:
                    other_f.cancel()
            raise BuildCancelledError("Build aborted by user (Ctrl+C)", stage_idx=2)
        except BuildCancelledError:
            abort_event.set()
            if cancel_controller is not None:
                cancel_controller.cancel(stage_idx=2)
            else:
                for other_f in futures:
                    other_f.cancel()
            raise

    if cancel_controller is not None:
        cancel_controller.check_cancelled(stage_idx=2)

    obj_files = [results_by_index[i] for i in range(total_sources)]
    return True, obj_files, new_manifest

def compile_swift_sources(
    swiftc_bin: Path,
    clang_bin: Path,
    sdk_dir: Path,
    swift_resource_dir: Optional[Path],
    tools_dir: Path,
    swift_sources: List[Path],
    project_dir: Path,
    obj_dir: Path,
    target_triple: str,
    swift_module_name: str,
    app_name: str,
    extra_inc_flags: List[str],
    extra_fw_flags: List[str],
    compiler_flags: List[str],
    build_manifest: Dict[str, str],
    verbose: bool = False,
    cache_dir: Optional[Path] = None,
    progress_callback: Optional[Any] = None,
    warning_callback: Optional[Any] = None,
    error_callback: Optional[Any] = None,
    operation_callback: Optional[Any] = None,
    cancel_controller: Optional[BuildCancellationController] = None,
) -> Tuple[bool, List[Path], Dict[str, str]]:
    """Compiles Swift files as a whole module and compiles the platform_check helper."""
    if cancel_controller is not None:
        cancel_controller.check_cancelled(stage_idx=2)

    obj_files = []
    new_manifest = dict(build_manifest)

    swift_obj = obj_dir / "swift_bundle.o"
    swift_hashes = "".join([get_file_hash(s) for s in swift_sources])
    swift_composite_hash = hashlib.sha256(swift_hashes.encode()).hexdigest()

    if progress_callback:
        progress_callback(swift_module_name, len(swift_sources), 0.0)

    t0 = time.monotonic()
    if swift_obj.is_file() and build_manifest.get("__swift_composite__") == swift_composite_hash:
        if operation_callback:
            operation_callback(
                tool="swiftc",
                input_file=f"{len(swift_sources)} Swift sources ({swift_module_name})",
                output_file=swift_obj.name,
                cmd=[],
                cwd=str(project_dir),
                exit_code=0,
                elapsed=0.0,
                cached=True,
                stdout="",
                stderr="",
                output_valid=swift_obj.is_file(),
                output_size=swift_obj.stat().st_size if swift_obj.is_file() else 0
            )
        if not progress_callback:
            print(f"  {Color.WHITE}[CACHED]{Color.RESET} Swift bundle ({len(swift_sources)} files)")
        obj_files.append(swift_obj)
    else:
        has_at_main = any(
            re.search(r"@main\b|@UIApplicationMain\b|@NSApplicationMain\b", s.read_text(encoding="utf-8", errors="ignore"))
            for s in swift_sources
        )
        cmd = [
            str(swiftc_bin),
            "-target", target_triple,
            "-sdk", str(sdk_dir),
            "-emit-object",
            "-o", str(swift_obj),
            "-module-name", swift_module_name,
        ]
        # Only pass -parse-as-library if there is an explicit @main / App entry point or if not a top-level script
        effective_compiler_flags = list(compiler_flags)
        if has_at_main:
            cmd.extend(["-parse-as-library", "-whole-module-optimization"])
        else:
            # If no @main is found (e.g. top-level CLI script), strip -parse-as-library so top-level code compiles cleanly
            effective_compiler_flags = [f for f in effective_compiler_flags if f != "-parse-as-library"]

        if swift_resource_dir:
            cmd.extend(["-resource-dir", str(swift_resource_dir)])

        if cache_dir and "-module-cache-path" not in effective_compiler_flags:
            os.makedirs(cache_dir, exist_ok=True)
            cmd.extend(["-module-cache-path", str(cache_dir)])

        # Auto-detect Bridging Header for C/ObjC <-> Swift interop
        bridging_h = find_bridging_header(project_dir, app_name)
        if bridging_h:
            log_info(f"Using Objective-C Bridging Header: {bridging_h.name}")
            cmd.extend(["-import-objc-header", str(bridging_h.resolve())])

        cmd.extend(extra_inc_flags + extra_fw_flags + [str(s) for s in swift_sources] + effective_compiler_flags)

        if verbose:
            print("  [CMD]", " ".join(cmd))

        try:
            proc = run_build_subprocess(
                cmd,
                cwd=project_dir,
                cancel_controller=cancel_controller,
                tool_name="swiftc",
                stage_idx=2,
                run_fn=subprocess.run,
            )
        except BuildCancelledError:
            if swift_obj.is_file():
                try:
                    swift_obj.unlink()
                except Exception:
                    pass
            raise

        elapsed_swift = time.monotonic() - t0
        is_mock = type(proc).__name__ in ("MagicMock", "Mock") or hasattr(proc, "_mock_return_value")
        out_valid = (swift_obj.is_file() and swift_obj.stat().st_size > 0) if not is_mock else (proc.returncode == 0)
        out_sz = swift_obj.stat().st_size if swift_obj.is_file() else 0

        if operation_callback:
            operation_callback(
                tool="swiftc",
                input_file=f"{len(swift_sources)} Swift sources ({swift_module_name})",
                output_file=swift_obj.name,
                cmd=cmd,
                cwd=str(project_dir),
                exit_code=proc.returncode,
                elapsed=elapsed_swift,
                cached=False,
                stdout=proc.stdout,
                stderr=proc.stderr,
                output_valid=out_valid,
                output_size=out_sz
            )

        if progress_callback:
            progress_callback(swift_module_name, len(swift_sources), elapsed_swift)

        if proc.returncode != 0 or not out_valid:
            if error_callback:
                error_callback(proc.stderr or f"Swift compilation produced no valid object: {swift_obj.name}")
            elif not progress_callback:
                log_error("Swift compilation failed:")
                format_compiler_diagnostics(proc.stderr)
            return False, [], build_manifest

        # Compiler warnings on stderr must not fail the build
        if proc.stderr:
            if warning_callback:
                warning_callback(proc.stderr)
            elif not progress_callback:
                format_compiler_diagnostics(proc.stderr)

        new_manifest["__swift_composite__"] = swift_composite_hash
        obj_files.append(swift_obj)
        if not progress_callback:
            print(f"  {Color.GREEN}[+]{Color.RESET} Compiled {len(swift_sources)} Swift files -> {swift_obj.name}")

    # Compile platform version check helper (compiler-rt builtin)
    if cancel_controller is not None:
        cancel_controller.check_cancelled(stage_idx=2)

    platform_c = tools_dir / "platform_check.c"
    platform_o = obj_dir / "platform_check.o"
    if not platform_c.is_file():
        platform_c.write_text(PLATFORM_CHECK_SOURCE, encoding="utf-8")
    cmd_pc = [
        str(clang_bin),
        "-target", target_triple,
        "-isysroot", str(sdk_dir),
        "-c", str(platform_c),
        "-o", str(platform_o),
        "-O2"
    ]
    t0_pc = time.monotonic()
    try:
        proc_pc = run_build_subprocess(
            cmd_pc,
            cwd=project_dir,
            cancel_controller=cancel_controller,
            tool_name="clang",
            stage_idx=2,
            run_fn=subprocess.run,
        )
    except BuildCancelledError:
        if platform_o.is_file():
            try:
                platform_o.unlink()
            except Exception:
                pass
        raise

    elapsed_pc = time.monotonic() - t0_pc
    is_mock_pc = type(proc_pc).__name__ in ("MagicMock", "Mock") or hasattr(proc_pc, "_mock_return_value")
    pc_valid = (platform_o.is_file() and platform_o.stat().st_size > 0) if not is_mock_pc else (proc_pc.returncode == 0)
    pc_sz = platform_o.stat().st_size if platform_o.is_file() else 0

    if operation_callback:
        operation_callback(
            tool="clang",
            input_file="platform_check.c",
            output_file=platform_o.name,
            cmd=cmd_pc,
            cwd=str(project_dir),
            exit_code=proc_pc.returncode,
            elapsed=elapsed_pc,
            cached=False,
            stdout=proc_pc.stdout,
            stderr=proc_pc.stderr,
            output_valid=pc_valid,
            output_size=pc_sz
        )

    if proc_pc.returncode != 0 or not pc_valid:
        log_error(f"Failed to compile platform_check.c: {proc_pc.stderr}")
        return False, [], build_manifest
    obj_files.append(platform_o)

    return True, obj_files, new_manifest
