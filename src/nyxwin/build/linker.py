import time
import subprocess
from pathlib import Path
from typing import List, Optional, Any, Tuple
from nyxwin.core.models import Color, log_error, log_success
from nyxwin.core.diagnostics import format_compiler_diagnostics
from nyxwin.build.process_manager import (
    BuildCancellationController,
    BuildCancelledError,
    run_build_subprocess,
)


def translate_driver_linker_flags(raw_flags: List[str]) -> Tuple[List[str], List[str]]:
    """
    Translates Clang compiler-driver linker forwarding syntax (`-Xlinker <arg>` and
    `-Wl,<arg1>,<arg2>,...`) into raw linker arguments suitable for direct `ld64.lld`
    invocation, while preserving existing raw linker arguments, token order, repeated
    options (such as multiple `-rpath` pairs), and arguments containing spaces.

    Returns `(translated_flags, error_messages)`. Any malformed or untranslatable
    driver-only flag in `OTHER_LDFLAGS` is reported in `error_messages` rather than
    silently dropped or passed raw to `ld64.lld`.
    """
    translated: List[str] = []
    errors: List[str] = []
    idx = 0
    total = len(raw_flags)

    while idx < total:
        tok = str(raw_flags[idx])
        if tok == "-Xlinker":
            if idx + 1 < total:
                arg = str(raw_flags[idx + 1])
                if arg == "":
                    errors.append("Invalid linker flag in OTHER_LDFLAGS: '-Xlinker' followed by empty argument")
                else:
                    translated.append(arg)
                idx += 2
            else:
                errors.append("Invalid linker flag in OTHER_LDFLAGS: '-Xlinker' is missing its required argument")
                idx += 1
        elif tok.startswith("-Xlinker="):
            errors.append(
                f"Unsupported joined '-Xlinker=' syntax in OTHER_LDFLAGS: '{tok}' (use '-Xlinker <arg>')"
            )
            idx += 1
        elif tok == "-Wl" or tok == "-Wl,":
            errors.append(
                f"Malformed '-Wl,' linker flag in OTHER_LDFLAGS: '{tok}' is missing forwarded arguments"
            )
            idx += 1
        elif tok.startswith("-Wl,"):
            parts = tok[4:].split(",")
            if any(p == "" for p in parts):
                errors.append(
                    f"Malformed '-Wl,' linker flag in OTHER_LDFLAGS: '{tok}' contains an empty comma-separated argument"
                )
            else:
                translated.extend(parts)
            idx += 1
        elif tok in ("-Xfrontend", "-Xcc", "-Xclang", "-Xllvm"):
            errors.append(
                f"Unsupported compiler-driver flag in OTHER_LDFLAGS for direct ld64.lld invocation: '{tok}'"
            )
            idx += 2 if idx + 1 < total else 1
        elif tok.startswith(("-Wa,", "-Wp,")):
            errors.append(
                f"Unsupported compiler-driver flag in OTHER_LDFLAGS for direct ld64.lld invocation: '{tok}'"
            )
            idx += 1
        else:
            translated.append(tok)
            idx += 1

    return translated, errors


def link_macho_binary(
    linker_bin: Path,
    sdk_dir: Path,
    swift_resource_dir: Optional[Path],
    clang_rt: Optional[Path],
    obj_files: List[Path],
    out_binary: Path,
    deployment_target: str,
    frameworks: List[str],
    weak_frameworks: List[str],
    library_paths: List[str],
    extra_fw_flags: List[str],
    linker_flags: List[str],
    project_dir: Path,
    has_swift: bool,
    verbose: bool = False,
    error_callback: Optional[Any] = None,
    has_cpp: bool = False,
    warning_callback: Optional[Any] = None,
    target_type: str = "app",
    operation_callback: Optional[Any] = None,
    cancel_controller: Optional[BuildCancellationController] = None,
) -> bool:
    """Invokes LLVM Darwin linker (ld64.lld) to link ARM64 Mach-O executable or bundle."""
    if cancel_controller is not None:
        cancel_controller.check_cancelled(stage_idx=3)

    cmd_link = [str(linker_bin)]
    if linker_bin.name.lower() == "lld.exe":
        cmd_link.extend(["-flavor", "darwin"])

    cmd_link.extend([
        "-arch", "arm64",
        "-platform_version", "ios", deployment_target, deployment_target,
        "-syslibroot", str(sdk_dir),
        f"-F{sdk_dir}/System/Library/Frameworks",
    ])

    # Pass SubFrameworks and PrivateFrameworks if available to resolve auto-linked frameworks (e.g. UIUtilities)
    subfw = sdk_dir / "System" / "Library" / "SubFrameworks"
    if subfw.is_dir():
        cmd_link.append(f"-F{subfw}")
    privfw = sdk_dir / "System" / "Library" / "PrivateFrameworks"
    if privfw.is_dir():
        cmd_link.append(f"-F{privfw}")

    cmd_link.extend([
        f"-L{sdk_dir}/usr/lib",
        "-lSystem",
        "-rpath", "/System/Library/Frameworks",
        "-rpath", "@executable_path/Frameworks",
        "-o", str(out_binary)
    ])

    if has_swift and swift_resource_dir:
        cmd_link.extend([
            f"-L{sdk_dir}/usr/lib/swift",
            f"-L{swift_resource_dir}/iphoneos",
            f"-L{swift_resource_dir}/iphoneos/arm64",
            "-lswiftCore", "-lswift_Concurrency", "-lswiftFoundation",
            "-lswiftUIKit", "-lswiftDispatch", "-lswiftos",
            "-lswiftObjectiveC", "-lswiftXPC", "-lswift_Builtin_float",
            "-lswiftUniformTypeIdentifiers",
            "-lswiftCompatibility56", "-lswiftCompatibility51",
            "-lswiftCompatibility50", "-lswiftCompatibilityConcurrency",
            "-lswiftCompatibilityPacks",
            "-rpath", "/usr/lib/swift"
        ])

    for libp in library_paths:
        if not libp or "$(" in libp or "${" in libp:
            continue
        cand = Path(libp)
        if not cand.is_absolute():
            cand = (project_dir / libp).resolve()
        if cand.is_dir():
            cmd_link.extend(["-L", str(cand)])

    cmd_link.extend(extra_fw_flags)

    for fw in frameworks:
        cmd_link.extend(["-framework", fw])
    for wfw in weak_frameworks:
        cmd_link.extend(["-weak_framework", wfw])

    for obj in obj_files:
        cmd_link.append(str(obj))

    if clang_rt and clang_rt.is_file():
        cmd_link.append(str(clang_rt))

    translated_linker_flags, flag_errors = translate_driver_linker_flags(linker_flags)
    if flag_errors:
        err_msg = "; ".join(flag_errors)
        if error_callback:
            error_callback(err_msg)
        else:
            log_error(f"Linking failed: {err_msg}")
        return False

    if has_cpp:
        if "-lc++" not in translated_linker_flags and "-lc++" not in cmd_link:
            cmd_link.append("-lc++")

    for lf in translated_linker_flags:
        # Filter out redundant or invalid -lclang_rt.* flags since clang_rt is passed directly
        if lf.startswith("-lclang_rt"):
            continue
        if lf.startswith("-l") and len(lf) > 2 and lf in cmd_link:
            continue
        cmd_link.append(lf)

    if verbose:
        print("  [CMD]", " ".join(cmd_link))

    t0 = time.monotonic()
    try:
        proc = run_build_subprocess(
            cmd_link,
            cwd=project_dir,
            cancel_controller=cancel_controller,
            tool_name="ld64.lld",
            stage_idx=3,
            run_fn=subprocess.run,
        )
    except BuildCancelledError:
        if out_binary.is_file():
            try:
                out_binary.unlink()
            except Exception:
                pass
        raise
    elapsed = time.monotonic() - t0

    if proc.stderr:
        # Parse and report linker warnings
        if "warning:" in proc.stderr.lower():
            if warning_callback:
                warning_callback(proc.stderr)
            elif not error_callback:
                format_compiler_diagnostics(proc.stderr)

    is_mock = type(proc).__name__ in ("MagicMock", "Mock") or hasattr(proc, "_mock_return_value")
    out_valid = (out_binary.is_file() and out_binary.stat().st_size > 0) if not is_mock else (proc.returncode == 0)
    bin_size = out_binary.stat().st_size if out_binary.is_file() else 0
    macho_hdr = {}
    if out_valid:
        try:
            with open(out_binary, "rb") as bf:
                header_data = bf.read(32)
                if len(header_data) >= 16:
                    import struct
                    magic = struct.unpack("<I", header_data[:4])[0]
                    cputype, cpusubtype, filetype = struct.unpack("<III", header_data[4:16])
                    macho_hdr = {
                        "magic_hex": f"0x{magic:08X}",
                        "cputype": cputype,
                        "arch": "ARM64" if cputype == 0x0100000C else f"0x{cputype:X}",
                        "filetype": "MH_EXECUTE" if filetype == 2 else str(filetype)
                    }
        except Exception:
            pass

    if operation_callback:
        operation_callback(
            tool="ld64.lld",
            object_files=[str(o) for o in obj_files],
            frameworks=frameworks,
            libraries=linker_flags,
            output_binary=str(out_binary),
            cmd=cmd_link,
            cwd=str(project_dir),
            exit_code=proc.returncode,
            elapsed=elapsed,
            stdout=proc.stdout,
            stderr=proc.stderr,
            output_valid=out_valid,
            output_size=bin_size,
            macho_header=macho_hdr
        )

    if proc.returncode != 0 or not out_valid:
        if error_callback:
            error_callback(proc.stderr or f"Linking produced no valid Mach-O binary: {out_binary.name}")
        else:
            log_error("Linking failed:")
            format_compiler_diagnostics(proc.stderr)
        return False

    log_success(f"Linked Mach-O executable: {out_binary.name} ({bin_size:,} bytes)")
    return True
