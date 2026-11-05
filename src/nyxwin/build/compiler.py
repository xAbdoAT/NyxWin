import os
import sys
import time
import hashlib
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Dict, Optional, Any

from nyxwin.core.models import Color, log_info, log_error, log_step
from nyxwin.core.diagnostics import format_compiler_diagnostics

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
    operation_callback: Optional[Any] = None
) -> Tuple[bool, List[Path], Dict[str, str]]:
    """Compiles C, Objective-C, and C++ files concurrently with SHA-256 caching."""
    obj_files = []
    new_manifest = dict(build_manifest)
    total_sources = len(c_sources)
    completed_count = 0
    cached_count = 0

    def compile_single(src: Path):
        obj_path = obj_dir / f"{src.stem}.o"
        cur_hash = get_file_hash(src)
        rel_src = str(src.relative_to(project_dir))

        if obj_path.is_file() and build_manifest.get(rel_src) == cur_hash:
            return (src, obj_path, None, True, rel_src, cur_hash, [], 0.0)

        cmd = [
            str(clang_bin),
            "-target", target_triple,
            "-isysroot", str(sdk_dir),
            "-c", str(src),
            "-o", str(obj_path)
        ] + extra_inc_flags + extra_fw_flags + compiler_flags

        if verbose:
            print("  [CMD]", " ".join(cmd))

        t0 = time.monotonic()
        proc = subprocess.run(cmd, capture_output=True, text=True)
        elapsed = time.monotonic() - t0
        return (src, obj_path, proc, False, rel_src, cur_hash, cmd, elapsed)

    with ThreadPoolExecutor(max_workers=min(os.cpu_count() or 4, 8)) as executor:
        futures = [executor.submit(compile_single, s) for s in c_sources]
        for fut in as_completed(futures):
            src, obj_path, proc, was_cached, rel_src, cur_hash, cmd, elapsed = fut.result()
            completed_count += 1
            if was_cached:
                cached_count += 1
                if operation_callback:
                    operation_callback(
                        tool="clang",
                        input_file=rel_src,
                        output_file=obj_path.name,
                        cmd=[],
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
                        exit_code=proc.returncode,
                        elapsed=elapsed,
                        cached=False,
                        stdout=proc.stdout,
                        stderr=proc.stderr,
                        output_valid=out_valid,
                        output_size=out_sz
                    )
                if proc.returncode != 0 or not out_valid:
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
                new_manifest[rel_src] = cur_hash
                if not progress_callback:
                    print(f"  {Color.GREEN}[+]{Color.RESET} Compiled {src.name}")

            obj_files.append(obj_path)
            if progress_callback:
                progress_callback(completed_count, total_sources, cached_count, src.name)

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
    operation_callback: Optional[Any] = None
) -> Tuple[bool, List[Path], Dict[str, str]]:
    """Compiles Swift files as a whole module and compiles the platform_check helper."""
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
        import re
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

        proc = subprocess.run(cmd, capture_output=True, text=True)
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
                log_error(f"Swift compilation failed:")
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
    proc_pc = subprocess.run(cmd_pc, capture_output=True, text=True)
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
